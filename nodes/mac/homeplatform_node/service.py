from __future__ import annotations

import json
import os
import platform
import socket
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

import paho.mqtt.client as mqtt

BASE_TOPIC = "homeplatform/v1"
NODE_ID = os.environ.get("HOMEPLATFORM_NODE_ID", "macbook")
STATE_DIRECTORY = Path(os.environ.get("HOMEPLATFORM_STATE_DIRECTORY", "~/Library/Application Support/Home Platform")).expanduser()
STATE_DIRECTORY.mkdir(parents=True, exist_ok=True)
SPOOL_PATH = STATE_DIRECTORY / "node-outbox.sqlite3"
DESIRED_STATE_PATH = STATE_DIRECTORY / "desired-state.json"

# Bidirectional Project Hub: the folder tree this node owns, the Workspace
# Watcher database it reads (read-only, never written by this process), and
# the Control Plane API this node polls as a belt-and-suspenders fallback to
# MQTT delivery -- see project.create_directory / project.initialize /
# workspace.scan below.
WORKSPACE_ROOT = Path(os.environ.get("HOMEPLATFORM_WORKSPACE_ROOT", "~/Workspace")).expanduser()
PROJECTS_ROOT = WORKSPACE_ROOT / "Projects"
WORKSPACE_WATCHER_DB = Path(os.environ.get(
    "HOMEPLATFORM_WORKSPACE_WATCHER_DB", str(WORKSPACE_ROOT / "Logs/workspace-watcher/events.db"),
))
API_BASE_URL = os.environ.get("HOMEPLATFORM_API_URL", "http://127.0.0.1:3000").rstrip("/")
PROJECT_JOB_POLL_TIMEOUT_SECONDS = 5


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def envelope(payload: dict, correlation_id: str | None = None) -> dict:
    return {
        "schema_version": 1,
        "event_id": str(uuid4()),
        "producer": NODE_ID,
        "occurred_at": now(),
        "correlation_id": correlation_id,
        "payload": payload,
    }


def keychain_password() -> str:
    value = os.environ.get("HOMEPLATFORM_MQTT_PASSWORD")
    if value:
        return value
    service = os.environ.get("HOMEPLATFORM_MQTT_KEYCHAIN_SERVICE", "Home Platform MQTT")
    account = os.environ.get("HOMEPLATFORM_MQTT_KEYCHAIN_ACCOUNT", NODE_ID)
    result = subprocess.run(
        ["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"No MQTT password in Keychain for {service}/{account}")
    return result.stdout.strip()


def probe(url: str) -> bool:
    try:
        with urlopen(Request(url, method="GET"), timeout=2) as response:
            return 200 <= response.status < 500
    except Exception:
        return False


def process_running(name: str) -> bool:
    return subprocess.run(["/usr/bin/pgrep", "-x", name], capture_output=True, check=False).returncode == 0


class DurablePublisher:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.connected = False
        self.connection = sqlite3.connect(SPOOL_PATH, check_same_thread=False)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY, topic TEXT, payload TEXT, qos INTEGER, retain INTEGER)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS command_results (command_id TEXT PRIMARY KEY, status TEXT NOT NULL, detail TEXT NOT NULL, result TEXT NOT NULL)"
        )
        self.connection.commit()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"homeplatform-{NODE_ID}")
        self.client.username_pw_set(os.environ.get("HOMEPLATFORM_MQTT_USERNAME", NODE_ID), keychain_password())
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        self.client.will_set(
            f"{BASE_TOPIC}/nodes/{NODE_ID}/presence",
            json.dumps(envelope({"status": "offline", "hostname": socket.gethostname(), "health": "offline"})),
            qos=1,
            retain=True,
        )

    def start(self) -> None:
        host = os.environ.get("HOMEPLATFORM_MQTT_HOST", "127.0.0.1")
        port = int(os.environ.get("HOMEPLATFORM_MQTT_PORT", "1883"))
        self.client.connect_async(host, port, keepalive=30)
        self.client.loop_start()

    def stop(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()
        self.connection.close()

    def on_connect(self, client: mqtt.Client, _userdata: object, _flags: object, _reason: object, _properties: object) -> None:
        self.connected = True
        client.subscribe(f"{BASE_TOPIC}/commands/{NODE_ID}/request", qos=1)
        client.subscribe(f"{BASE_TOPIC}/config/desired-state/global", qos=1)
        client.subscribe(f"{BASE_TOPIC}/projects/jobs-available", qos=1)
        self.flush()
        report_state(self)
        # A reconnect may have missed retained/queued messages while this
        # node was offline; always reconcile against the Hub's own record of
        # pending work rather than trusting MQTT delivery alone.
        poll_pending_project_jobs(self)

    def on_disconnect(self, _client: mqtt.Client, _userdata: object, _flags: object, _reason: object, _properties: object) -> None:
        self.connected = False

    def on_message(self, _client: mqtt.Client, _userdata: object, message: mqtt.MQTTMessage) -> None:
        try:
            event = json.loads(message.payload.decode())
            payload = event["payload"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError):
            return
        if message.topic.endswith("/request"):
            handle_command(self, payload)
        elif message.topic.endswith("/global"):
            DESIRED_STATE_PATH.write_text(json.dumps(payload, indent=2) + "\n")
        elif message.topic.endswith("/jobs-available"):
            # Retained wake ping only -- never trusted as the sole delivery
            # path. The unconditional 30s loop below polls regardless.
            poll_pending_project_jobs(self)

    def publish(self, topic: str, payload: dict, *, retain: bool = False, qos: int = 1, correlation_id: str | None = None) -> None:
        encoded = json.dumps(envelope(payload, correlation_id), separators=(",", ":"))
        with self.lock:
            if self.connected and self.client.publish(topic, encoded, qos=qos, retain=retain).rc == mqtt.MQTT_ERR_SUCCESS:
                return
            self.connection.execute("INSERT INTO outbox(topic, payload, qos, retain) VALUES (?, ?, ?, ?)", (topic, encoded, qos, int(retain)))
            self.connection.commit()

    def saved_command_result(self, command_id: str) -> tuple[str, str, dict] | None:
        row = self.connection.execute(
            "SELECT status, detail, result FROM command_results WHERE command_id = ?", (command_id,)
        ).fetchone()
        return (str(row[0]), str(row[1]), json.loads(str(row[2]))) if row else None

    def save_command_result(self, command_id: str, status: str, detail: str, result: dict) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO command_results(command_id, status, detail, result) VALUES (?, ?, ?, ?)",
            (command_id, status, detail, json.dumps(result, separators=(",", ":"))),
        )
        self.connection.commit()

    def flush(self) -> None:
        with self.lock:
            rows = list(self.connection.execute("SELECT id, topic, payload, qos, retain FROM outbox ORDER BY id"))
            for row_id, topic, payload, qos, retain in rows:
                result = self.client.publish(topic, payload, qos=qos, retain=bool(retain))
                if result.rc != mqtt.MQTT_ERR_SUCCESS:
                    return
                self.connection.execute("DELETE FROM outbox WHERE id = ?", (row_id,))
            self.connection.commit()


def report_state(publisher: DurablePublisher) -> None:
    lm_studio_healthy = probe(os.environ.get("HOMEPLATFORM_LMSTUDIO_URL", "http://127.0.0.1:1234/v1/models"))
    comfyui_healthy = probe(os.environ.get("HOMEPLATFORM_COMFYUI_URL", "http://127.0.0.1:8188/system_stats"))
    presence = {"status": "online", "hostname": socket.gethostname(), "os": platform.platform(), "health": "healthy"}
    publisher.publish(f"{BASE_TOPIC}/nodes/{NODE_ID}/presence", presence, retain=True)
    publisher.publish(
        f"{BASE_TOPIC}/nodes/{NODE_ID}/actual-state",
        {
            "lmstudio": "healthy" if lm_studio_healthy else "offline",
            "comfyui": "healthy" if comfyui_healthy else "offline",
            "hammerspoon": "healthy" if process_running("Hammerspoon") else "offline",
            "workspace_projects": workspace_projects_snapshot(),
        },
        retain=True,
    )
    publisher.publish(
        f"{BASE_TOPIC}/nodes/{NODE_ID}/capabilities",
        {"capabilities": ["notifications", "hammerspoon-bridge", "text-generation", "image-generation", "macos-files"]},
        retain=True,
    )
    publisher.publish(
        f"{BASE_TOPIC}/services/{NODE_ID}/lmstudio/health",
        {"health": "healthy" if lm_studio_healthy else "offline", "capabilities": {"text-generation": True}},
        retain=True,
    )
    publisher.publish(
        f"{BASE_TOPIC}/services/{NODE_ID}/comfyui/health",
        {"health": "healthy" if comfyui_healthy else "offline", "capabilities": {"image-generation": True}},
        retain=True,
    )


def command_result(publisher: DurablePublisher, command_id: str, status: str, detail: str = "", result: dict | None = None) -> None:
    final_result = result or {}
    if status in {"completed", "failed", "unsupported", "expired"}:
        publisher.save_command_result(command_id, status, detail, final_result)
    publisher.publish(
        f"{BASE_TOPIC}/commands/{NODE_ID}/result",
        {"command_id": command_id, "status": status, "detail": detail, "result": final_result},
        correlation_id=command_id,
    )


def show_notification(title: str, message: str) -> None:
    script = f"display notification {json.dumps(message)} with title {json.dumps(title)}"
    subprocess.run(["/usr/bin/osascript", "-e", script], check=True, timeout=10)


def workspace_projects_snapshot() -> list[dict]:
    """Read-only snapshot of Workspace Watcher's project registry, converted
    from workspace-root-relative paths to absolute paths (to match Notion's
    Local Directory convention) so the Hub can match the two by string
    equality. Returns [] if Workspace Watcher has never run yet -- that is
    not an error, just "no scan available"."""
    if not WORKSPACE_WATCHER_DB.exists():
        return []
    try:
        uri = f"file:{WORKSPACE_WATCHER_DB}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=2)
        try:
            connection.row_factory = sqlite3.Row
            rows = connection.execute("SELECT project_id, path, name, status FROM projects").fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return []
    return [
        {
            "workspace_project_id": row["project_id"],
            "name": row["name"],
            "path": str(WORKSPACE_ROOT / row["path"]),
            "status": row["status"],
        }
        for row in rows
    ]


def sanitize_project_name(name: str) -> str:
    value = name.strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise ValueError(f"Refusing unsafe project name: {name!r}")
    return value


def initialize_project(target: Path, name: str, template: str) -> None:
    """Safe, generic initialization only -- no arbitrary commands. Every
    template gets this baseline; template-specific scaffolding beyond it is
    intentionally not yet implemented (see AGENTS.md / README)."""
    readme = target / "README.md"
    if not readme.exists():
        readme.write_text(f"# {name}\n", encoding="utf-8")
    metadata = target / ".project-hub.json"
    if not metadata.exists():
        metadata.write_text(
            json.dumps({"name": name, "template": template, "created_at": now()}, indent=2) + "\n",
            encoding="utf-8",
        )
    if not (target / ".git").exists():
        subprocess.run(["/usr/bin/git", "init", "-q"], cwd=target, check=False, timeout=10)


def poll_pending_project_jobs(publisher: DurablePublisher) -> None:
    """Belt-and-suspenders fallback: ask the Hub directly for any project.*
    command still outstanding for this node, independent of whether its MQTT
    request was ever received. handle_command's own saved-result cache makes
    processing the same job through both paths harmless."""
    url = f"{API_BASE_URL}/api/v1/projects/jobs/pending?node_id={NODE_ID}"
    try:
        with urlopen(Request(url, method="GET"), timeout=PROJECT_JOB_POLL_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                return
            jobs = json.loads(response.read().decode())
    except Exception:
        return
    for job in jobs:
        try:
            handle_command(publisher, {
                "command_id": job["id"],
                "command_type": job["command_type"],
                "payload": job["payload"],
                "expires_at": job["expires_at"],
            })
        except Exception:
            continue


def handle_command(publisher: DurablePublisher, payload: dict) -> None:
    command_id = str(payload.get("command_id", ""))
    if not command_id:
        return
    previous = publisher.saved_command_result(command_id)
    if previous:
        status, detail, result = previous
        publisher.publish(
            f"{BASE_TOPIC}/commands/{NODE_ID}/result",
            {"command_id": command_id, "status": status, "detail": detail, "result": result},
            correlation_id=command_id,
        )
        return
    expires_at = payload.get("expires_at", "")
    try:
        if datetime.fromisoformat(expires_at.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
            command_result(publisher, command_id, "expired", "Command TTL elapsed")
            return
    except ValueError:
        command_result(publisher, command_id, "failed", "Invalid command expiry")
        return
    command_type = payload.get("command_type")
    command_result(publisher, command_id, "accepted")
    command_result(publisher, command_id, "running")
    if command_type == "notification.show":
        try:
            data = payload.get("payload", {})
            show_notification(str(data.get("title", "Home Platform")), str(data.get("message", "")))
            command_result(publisher, command_id, "completed")
        except Exception as exc:
            command_result(publisher, command_id, "failed", str(exc))
    elif command_type == "node.refresh-health":
        report_state(publisher)
        command_result(publisher, command_id, "completed")
    elif command_type == "project.create_directory":
        try:
            data = payload.get("payload", {})
            name = sanitize_project_name(str(data.get("name", "")))
            target = PROJECTS_ROOT / name
            target.mkdir(parents=True, exist_ok=True)  # already-exists is success, not failure
            command_result(publisher, command_id, "completed", result={"workspace_path": str(target)})
        except ValueError as exc:
            command_result(publisher, command_id, "failed", str(exc))
        except OSError as exc:
            command_result(publisher, command_id, "failed", f"Could not create directory: {exc}")
    elif command_type == "project.initialize":
        try:
            data = payload.get("payload", {})
            name = sanitize_project_name(str(data.get("name", "")))
            template = str(data.get("template", "empty"))
            target = PROJECTS_ROOT / name
            target.mkdir(parents=True, exist_ok=True)
            initialize_project(target, name, template)
            command_result(publisher, command_id, "completed", result={"workspace_path": str(target), "template": template})
        except ValueError as exc:
            command_result(publisher, command_id, "failed", str(exc))
        except OSError as exc:
            command_result(publisher, command_id, "failed", f"Could not initialize project: {exc}")
    elif command_type == "workspace.scan":
        report_state(publisher)
        command_result(publisher, command_id, "completed")
    else:
        command_result(publisher, command_id, "unsupported", f"Allowlist rejects {command_type}")


def main() -> None:
    publisher = DurablePublisher()
    publisher.start()
    try:
        while True:
            time.sleep(30)
            if publisher.connected:
                report_state(publisher)
            # Unconditional: runs whether or not MQTT is currently connected,
            # so a days-long MQTT/Pi outage cannot make a queued job vanish.
            poll_pending_project_jobs(publisher)
    except KeyboardInterrupt:
        pass
    finally:
        publisher.stop()


if __name__ == "__main__":
    main()
