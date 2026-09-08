# Bidirectional Project Hub

Keeps the Notion Projects database and `~/Workspace/Projects` on the Mac in
sync, in three directions, coordinated by the Control Plane (the "Hub"):

1. **Phone -> new project**: create a project from HomeLab Control. A Notion
   page is created immediately (the Pi is always-on); the folder is created
   durably, even if the Mac is asleep or offline for days.
2. **Notion -> workspace**: a manually-added Notion project with no matching
   folder becomes an actionable Inbox item (create folder / ignore), never a
   silent folder creation.
3. **Workspace -> Notion**: a manually-created folder under
   `~/Workspace/Projects` becomes an actionable Inbox item (create in Notion /
   link to an existing Notion row / ignore), detected by the existing
   [Workspace Watcher](../../Workspace%20Watcher).

Nothing is ever silently deleted. A Notion page or folder that disappears is
marked `PATH_MISSING`/`absent`, never removed on the other side.

## Components reused (not rebuilt)

| Concern | Reused from |
|---|---|
| Always-on coordinator | This repo's existing Postgres + FastAPI `control-plane-api`/`control-plane-core` + Mosquitto |
| Durable job queue | The existing `commands` table + `homeplatform/v1/commands/{node}/request\|result` topics (already idempotent by `command_id`, already typed via an allowlist) |
| Mac agent | `nodes/mac/homeplatform_node/service.py` (the live `com.homeplatform.node` launchd service) -- extended, not replaced. `home-platform/mac-agent/mac_agent.py` is an older, superseded copy and was left untouched. |
| Folder watcher | [Workspace Watcher](../../Workspace%20Watcher) -- already assigns each `Projects/<X>` folder a stable UUID that survives renames/restarts (device+inode matching). Its SQLite DB is read directly (read-only); nothing about its own filesystem-watching logic was changed. |
| Notion schema | The live Projects data source (`title`, `Local Directory` rich_text) -- no new Notion property was added. Notion's own page id is the stable identity; no custom "Hub ID" property was needed. |
| Phone UI | HomeLab Control's existing `AppSection` tabs / `HomeLabClient` / `HomeLabStore` -- a `.projects` tab was added, not a new app. |
| Auth / network boundary | Tailscale Serve + the existing unauthenticated-behind-the-tailnet convention already used by every other mutating endpoint in this API. |

## Data model (Postgres, `alembic/versions/0002_projects.py`)

```
projects
  id                    TEXT PK (uuid, Hub-assigned)
  name                  TEXT
  notion_page_id        TEXT UNIQUE NULL
  workspace_project_id  TEXT UNIQUE NULL   -- Workspace Watcher's project_id
  workspace_path        TEXT NULL          -- absolute path, matches Notion's Local Directory convention
  workspace_device      TEXT NULL          -- node id, e.g. "macbook"
  template              TEXT               -- empty | swift-app | python | web-app | experiment | utility
  notion_state          TEXT               -- present | absent | pending | error
  workspace_state       TEXT               -- present | absent
  sync_state            TEXT               -- see state machine below (cached projection, recomputed by reconciliation)
  created_by            TEXT               -- ios-app | macos-app | reconciliation | other
  idempotency_key       TEXT UNIQUE NULL   -- phone-supplied, dedupes retried creates
  last_error            TEXT NULL
  created_at / updated_at

reconciliation_items
  id                    TEXT PK (uuid)
  kind                  TEXT   -- notion_only | workspace_only
  project_id            TEXT FK -> projects.id NULL
  notion_page_id / notion_name
  workspace_project_id / workspace_path / workspace_name
  status                TEXT   -- open | resolved | ignored
  resolution            TEXT NULL  -- created_folder | created_notion | linked_existing | ignored
  created_at / updated_at / resolved_at
```

There is no separate "jobs" table. `commands` (existing) carries the actual
Mac-bound work; a project job is just a `CommandRecord` whose
`command_type` starts with `project.` and whose `payload.project_id` links it
back to a `projects` row.

### Sync state machine

| notion_state | workspace_state | condition | sync_state |
|---|---|---|---|
| present | present | -- | `SYNCED` |
| present | absent | active create job | `PENDING_WORKSPACE_CREATION` |
| present | absent | no active job | `NOTION_ONLY` |
| absent | present | active create job | `PENDING_NOTION_CREATION` |
| absent | present | no active job | `WORKSPACE_ONLY` |
| -- | -- | reconciliation item ignored | `IGNORED` |
| -- | -- | last project.* job failed | `ERROR` |

`NAME_MISMATCH`, `PATH_MISSING`, and `DUPLICATE` are modeled in
`compute_sync_state` (`control-plane/app/reconciliation.py`) for future use;
name-mismatch detection specifically is a display-side comparison not yet
wired up (both sides' names are stored but not diffed against each other).

## API (`control-plane/app/api.py`, same FastAPI app, same trust boundary)

```
POST   /api/v1/projects                    create (idempotent on idempotency_key)
GET    /api/v1/projects                    list, with sync_state
GET    /api/v1/projects/{id}               detail + job history
GET    /api/v1/projects/jobs               recent project.* commands
GET    /api/v1/projects/jobs/pending       ?node_id= -- the Mac agent's poll target
GET    /api/v1/reconciliation               open items
POST   /api/v1/reconciliation/run           trigger a pass on demand
POST   /api/v1/reconciliation/{id}/resolve  {action: create_folder|create_notion|link_existing|ignore, notion_page_id?}
```

## MQTT

Reuses the `homeplatform/v1` namespace exactly:

- `homeplatform/v1/commands/macbook/request` / `.../result` -- carries
  `project.create_directory`, `project.initialize`, `workspace.scan`.
- `homeplatform/v1/projects/jobs-available` (new, retained, publish-only) --
  wakes an already-connected Mac agent so it doesn't wait for its next 30s
  poll. **Not** the source of truth: the Mac's poll loop runs unconditionally
  every 30s regardless of MQTT state, so a missed message costs at most one
  poll interval, never a lost job.

## Reconciliation (`control-plane/app/reconciliation.py`)

Runs every 5 minutes inside `control-plane-core` and on demand via the API.
Compares the `projects` table, a live Notion query, and the most recent
`workspace_projects` snapshot in each node's `actual_state` (populated by the
Mac agent from Workspace Watcher). It:

- Matches Notion pages to `projects` rows by `notion_page_id`, and workspace
  entries by `workspace_project_id` -- both stable across renames.
- Auto-links (never duplicates) a Notion-only row and a workspace-only row
  that already share the same absolute path.
- Opens at most one `reconciliation_items` row per (kind, key), regardless of
  its current status -- reconciling repeatedly never creates duplicate items,
  Notion rows, directories, or jobs.
- Never deletes anything. A page/folder that disappears flips its side to
  `absent`; the row stays.

## Failure handling

- Every phone create-request carries a client-generated `idempotency_key`;
  a retried submission or a double-tap on two devices returns the existing
  row instead of a duplicate.
- Notion outage/rate-limit: the Notion client retries 429/5xx with backoff
  (mirrors the ~0.35s pacing already used elsewhere in this workspace); a
  failed create leaves `notion_state=error` with `last_error` set rather than
  failing the whole request.
- Mac offline: the job sits `queued` in Postgres; MQTT delivery is
  best-effort, the poll loop is not.
- Duplicate filesystem events: unaffected -- Workspace Watcher's own
  inode-based identity already de-duplicates this before the Hub ever sees
  the snapshot.

## Storage-state contract with Workspace Sync & Backup Utility

kiosk-lab also runs a separate project, **Workspace Sync & Backup Utility**,
which owns everything about physical storage on the Pi: disks, UUID-based
mounts, TEST/PENDING/PRODUCTION workspace state, the backup HDD, Syncthing.
This project never inspects `/dev`, `/etc/fstab`, mount tables, or that
project's config/state files -- it consults `app/workspace_contract.py`,
which calls that project's `GET /api/storage/contract` over Tailscale
(`WORKSPACE_CONTRACT_URL`, token in `secrets/workspace_contract_token`,
copied from that project's own `WORKSPACE_DASHBOARD_TOKEN`). Symmetrically,
Workspace Sync & Backup Utility never reads this project's Postgres tables
or Notion data. See `docs/kiosk-lab-platform.md` for the full picture.

`GET /api/v1/storage/status` on this API proxies that contract, unchanged,
for HomeLab Control's summarized storage panel. The call degrades to
`{"mode": "unknown", ...}` on any failure (timeout, Workspace Sync Utility
down, `WORKSPACE_CONTRACT_URL` unset) -- it never raises, so a storage
outage cannot take down project/Notion reconciliation.

**Project creation while production workspace storage is unavailable:**
`POST /api/v1/projects` already separates metadata from physical creation --
the Postgres row and Notion page are created synchronously and returned
(`202`), while the actual directory is a `queued` `CommandRecord` dispatched
to `workspace_node_id` (today always `macbook`, the Mac's real, always-
available disk) and executed asynchronously, with its own poll-based retry.
Because that target is always the Mac today, this project cannot write onto
the Pi's SD card regardless of Pi storage state -- that's structural
(`HOMEPLATFORM_WORKSPACE_NODE_ID=macbook`), not a runtime check. **If a
Pi-resident workspace node is ever added**, its `project.create_directory`
handler MUST call
`workspace_contract.is_directory_creation_allowed_for_node(node_id)` before
creating anything, and MUST leave the command `queued` (not fail it, not
fall back to a bounded/SD-card path) when it returns `False` -- the existing
belt-and-suspenders poll loop already retries queued commands, so "queued"
here just means "waiting on storage," never "lost."
`workspace_contract.is_directory_creation_allowed_for_node` is already a
no-op (`True`) for every node id other than this Pi's own
`HOMEPLATFORM_NODE_ID`, so today's Mac-only path is unaffected.

## Security

No new attack surface: same Tailscale-only bind, same
unauthenticated-behind-the-tailnet convention as every other mutating
endpoint in `control-plane-api` today. `project.create_directory` /
`project.initialize` / `workspace.scan` are the only new command types the
Mac agent executes, each with a narrow validated payload (name -> sanitized
single path segment under `~/Workspace/Projects`, template -> enum) -- no
shell string ever leaves the Pi.
