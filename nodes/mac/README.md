# Mac Node Service

The Mac Node Service reports Actual State and capabilities, accepts only
allowlisted Commands, and reads its MQTT password from macOS Keychain. It does
not own Desired State or Platform configuration.

Install through `deploy/mac/INSTALL.md`; do not run this service with a
plaintext MQTT password in a launchd plist.

Use MQTT port 1883. Set `HOMEPLATFORM_MQTT_HOST` to the active Control Plane's
Tailnet DNS name, or to `127.0.0.1` when this Mac hosts the portable Control
Plane, then confirm presence and an allowlisted test command.

## Bidirectional Project Hub

This service also owns `~/Workspace/Projects`: it executes three additional
allowlisted commands (`project.create_directory`, `project.initialize`,
`workspace.scan` -- typed operations only, never an arbitrary shell string),
and reports a read-only snapshot of
[Workspace Watcher](../../../Workspace%20Watcher)'s project registry as part
of its normal 30s Actual State report. It also polls
`GET {HOMEPLATFORM_API_URL}/api/v1/projects/jobs/pending` every 30s and on
receipt of a retained `homeplatform/v1/projects/jobs-available` MQTT ping --
this is a belt-and-suspenders fallback, not the primary delivery path, so a
missed/lost MQTT message never loses a job.

Relevant environment variables (all optional, sensible defaults shown):

| Variable | Default | Purpose |
|---|---|---|
| `HOMEPLATFORM_WORKSPACE_ROOT` | `~/Workspace` | Root the Mac agent creates/reads project folders under (`Projects/` is appended) |
| `HOMEPLATFORM_WORKSPACE_WATCHER_DB` | `~/Workspace/Logs/workspace-watcher/events.db` | Workspace Watcher's SQLite file, opened read-only |
| `HOMEPLATFORM_API_URL` | `http://127.0.0.1:3000` | Control Plane base URL for the belt-and-suspenders job poll -- set this to the same Tailscale URL configured in HomeLab Control's Settings |

Workspace Watcher itself must be running (`launchctl list | grep workspace-watcher`)
for the workspace-side snapshot to stay current -- see its own README for
installation.
