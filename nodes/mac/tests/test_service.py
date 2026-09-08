from __future__ import annotations

import json
import sqlite3
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from homeplatform_node import service  # noqa: E402


class FakePublisher:
    """Mimics DurablePublisher's public surface without any real MQTT/Keychain
    dependency, so handler logic can be tested in isolation."""

    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []
        self.results: dict[str, tuple[str, str, dict]] = {}

    def publish(self, topic: str, payload: dict, *, retain: bool = False, qos: int = 1, correlation_id: str | None = None) -> None:
        self.published.append((topic, payload))

    def saved_command_result(self, command_id: str):
        return self.results.get(command_id)

    def save_command_result(self, command_id: str, status: str, detail: str, result: dict) -> None:
        self.results[command_id] = (status, detail, result)


def make_command_envelope(command_id: str, command_type: str, payload: dict, expires_in: int = 60) -> dict:
    return {
        "command_id": command_id,
        "command_type": command_type,
        "payload": payload,
        "expires_at": service.now() if expires_in <= 0 else _future(expires_in),
    }


def _future(seconds: int) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


class SanitizeProjectNameTests(unittest.TestCase):
    def test_accepts_a_normal_name(self) -> None:
        self.assertEqual(service.sanitize_project_name("ESP32 Sensors"), "ESP32 Sensors")

    def test_rejects_path_traversal(self) -> None:
        with self.assertRaises(ValueError):
            service.sanitize_project_name("../escape")

    def test_rejects_path_separator(self) -> None:
        with self.assertRaises(ValueError):
            service.sanitize_project_name("nested/name")

    def test_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            service.sanitize_project_name("   ")


class CreateDirectoryHandlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = mock.patch.object(service, "PROJECTS_ROOT", Path(self.enterContext_tempdir()) / "Projects")
        self._tmp.start()
        self.addCleanup(self._tmp.stop)
        service.PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)

    def enterContext_tempdir(self) -> str:
        import tempfile
        d = tempfile.mkdtemp(prefix="project-hub-test-")
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        return d

    def test_create_directory_is_completed_and_idempotent(self) -> None:
        publisher = FakePublisher()
        envelope = make_command_envelope("cmd-1", "project.create_directory", {"name": "Drawing AI", "template": "empty"})

        service.handle_command(publisher, envelope)
        self.assertTrue((service.PROJECTS_ROOT / "Drawing AI").is_dir())
        self.assertEqual(publisher.results["cmd-1"][0], "completed")

        # Second delivery of the SAME command_id (duplicate MQTT + poll
        # delivery, or a retried phone submission) must not error and must
        # not re-run side effects -- it replays the cached terminal result.
        publish_count_before = len(publisher.published)
        service.handle_command(publisher, envelope)
        self.assertEqual(len(publisher.published), publish_count_before + 1)  # replay, not re-execution

    def test_create_directory_rejects_unsafe_name(self) -> None:
        publisher = FakePublisher()
        envelope = make_command_envelope("cmd-2", "project.create_directory", {"name": "../escape"})
        service.handle_command(publisher, envelope)
        self.assertEqual(publisher.results["cmd-2"][0], "failed")

    def test_initialize_creates_readme_git_and_metadata(self) -> None:
        publisher = FakePublisher()
        envelope = make_command_envelope("cmd-3", "project.initialize", {"name": "Python Thing", "template": "python"})
        service.handle_command(publisher, envelope)

        target = service.PROJECTS_ROOT / "Python Thing"
        self.assertEqual(publisher.results["cmd-3"][0], "completed")
        self.assertTrue((target / "README.md").exists())
        self.assertTrue((target / ".project-hub.json").exists())
        metadata = json.loads((target / ".project-hub.json").read_text())
        self.assertEqual(metadata["template"], "python")

    def test_unsupported_command_type_is_rejected(self) -> None:
        publisher = FakePublisher()
        envelope = make_command_envelope("cmd-4", "shell.run", {"cmd": "rm -rf /"})
        service.handle_command(publisher, envelope)
        self.assertEqual(publisher.results["cmd-4"][0], "unsupported")

    def test_expired_command_is_marked_expired_not_executed(self) -> None:
        publisher = FakePublisher()
        envelope = make_command_envelope("cmd-5", "project.create_directory", {"name": "Too Late"}, expires_in=-10)
        service.handle_command(publisher, envelope)
        self.assertEqual(publisher.results.get("cmd-5", (None,))[0], "expired")
        self.assertFalse((service.PROJECTS_ROOT / "Too Late").exists())


class WorkspaceProjectsSnapshotTests(unittest.TestCase):
    def test_snapshot_converts_relative_paths_to_absolute(self) -> None:
        import tempfile
        tmp_dir = Path(tempfile.mkdtemp(prefix="workspace-watcher-test-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp_dir, ignore_errors=True))
        db_path = tmp_dir / "events.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE projects (project_id TEXT PRIMARY KEY, path TEXT, name TEXT, status TEXT)")
        conn.execute(
            "INSERT INTO projects VALUES (?,?,?,?)",
            ("proj-uuid-1", "Projects/ESP32 Sensors", "ESP32 Sensors", "active"),
        )
        conn.commit()
        conn.close()

        with mock.patch.object(service, "WORKSPACE_WATCHER_DB", db_path), \
             mock.patch.object(service, "WORKSPACE_ROOT", tmp_dir):
            snapshot = service.workspace_projects_snapshot()

        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0]["workspace_project_id"], "proj-uuid-1")
        self.assertEqual(snapshot[0]["path"], str(tmp_dir / "Projects/ESP32 Sensors"))
        self.assertEqual(snapshot[0]["status"], "active")

    def test_missing_database_returns_empty_list(self) -> None:
        with mock.patch.object(service, "WORKSPACE_WATCHER_DB", Path("/nonexistent/events.db")):
            self.assertEqual(service.workspace_projects_snapshot(), [])


class PollPendingProjectJobsTests(unittest.TestCase):
    def test_poll_delivers_jobs_through_handle_command(self) -> None:
        publisher = FakePublisher()
        jobs = [{
            "id": "cmd-remote-1", "command_type": "workspace.scan",
            "payload": {"project_id": "proj-x"}, "expires_at": _future(60),
        }]

        class FakeResponse:
            status = 200
            def read(self) -> bytes:
                return json.dumps(jobs).encode()
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        with mock.patch.object(service, "urlopen", return_value=FakeResponse()), \
             mock.patch.object(service, "report_state") as fake_report_state:
            service.poll_pending_project_jobs(publisher)

        fake_report_state.assert_called_once_with(publisher)
        self.assertEqual(publisher.results["cmd-remote-1"][0], "completed")

    def test_poll_failure_is_silent(self) -> None:
        publisher = FakePublisher()
        with mock.patch.object(service, "urlopen", side_effect=OSError("network down")):
            service.poll_pending_project_jobs(publisher)  # must not raise
        self.assertEqual(publisher.results, {})


if __name__ == "__main__":
    unittest.main()
