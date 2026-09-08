# Workspace and kiosk-lab ownership

This is the operational ownership decision made from the source trees and a
live `kiosk-lab` inspection on 2026-09-08. It supersedes any implication that
similarly named repositories are interchangeable deployments.

## Decisions

| Responsibility | One owner | Other components' role |
| --- | --- | --- |
| Pi containerized control plane, project API, project coordination jobs, Notion Projects reconciliation | **Home Platform / Project Hub** | HomeLab Control is a client; the Mac node executes only its allowlisted local jobs. |
| Project identity exposed to web/iPhone, Notion page mapping, project creation and reconciliation state | **Project Hub Postgres** | Notion is an external synchronized system, not a second writable local authority. |
| Mac directory sensing and durable filesystem-event history | **Workspace Watcher** | It emits/retains observations only; it neither creates project folders nor owns project metadata. |
| Project Core `.project/` format, local-first experiments, and Finder Clone API | **Project Management System, scoped only to opted-in projects** | It is not a deployed ecosystem service and must not run its Notion import/apply loop beside Project Hub. |
| Mac Workspace files | **Mac filesystem** | The Pi holds coordination state and optional mirrors/backups, never the canonical development checkout. |
| Physical disks, mounts, Syncthing, restic, backup/restore, and storage health | **Workspace Sync & Backup Utility** | Project Hub reads one HTTP storage contract; it never inspects mounts or Workspace Sync state directly. |
| Homelab controls | **HomeLab Control is a UI client** | It reads Project Hub APIs and submits durable requests; it does not own MQTT, SQL, or shell execution. |
| Kiosk display, Arduino protocol, and kiosk-specific telemetry | **Kiosk Lab** | Separate application; no ownership of Project Hub, workspace metadata, or Pi-wide deployment. |

`Bidirectional Project Hub/` is intentionally only a design pointer. Its
implemented code lives in `Home Lab/home-platform`; it is not a second
repository or deployment.

## Runtime and data flow

```text
Mac ~/Workspace/Projects (real source directories)
  -> Workspace Watcher (events.db; sensor only)
  -> Home Platform Mac Node (read-only watcher snapshot; allowed directory jobs)
  <-> Project Hub API/MQTT on kiosk-lab
       -> Postgres: project mapping, jobs, reconciliation, device state
       <-> Notion Projects database
       <- Workspace Sync /api/storage/contract (read-only storage status)

HomeLab Control (macOS/iOS) -> Tailscale Serve -> Home Platform API
Workspace Sync dashboard -> storage/backup administration only
Kiosk Lab -> independent kiosk hardware and telemetry paths only
```

The Mac node queues results durably and polls outstanding jobs even when MQTT
is unavailable. Project creation is idempotent by client key; the job record
is persisted before delivery. While the Mac is offline, Project Hub can retain
phone-created metadata and Notion reconciliation state, but it leaves the
directory-creation job queued. While the Pi is offline, the Mac keeps its
source files and Watcher's local event history; the node retries and
reconciles when it reconnects.

## Repository roles and transitions

- **Home Lab/home-platform** is the authoritative source for the Pi's
  containerized platform and the host-level architecture record. Its
  `deploy/kiosk-lab/` path defines the recovery layout and boot sequence.
- **Workspace Sync & Backup Utility** is intentionally separate: hardware and
  backup lifecycle should not be coupled to project metadata. Its own systemd
  units are the sole owner of `workspace-*` services.
- **Workspace Watcher** remains a Mac-side sensor. Its optional Notion project
  cache is read-only; its optional work-log writer is disabled unless
  explicitly configured. Do not enable that writer as a second Projects sync.
- **Project Management System** has a sound portable `.project/` model but is
  not yet deployed, authenticated, or reconciled with Project Hub. Four
  projects currently opt into it. It is a transition/prototype boundary, not
  an ecosystem-wide authority. A future migration must choose one canonical ID
  and use an explicit import, never run two sync loops.
- **Homelab Control** already follows the correct client-only boundary.
- **Kiosk Lab** was moved from `Workspace/TEMP/Kiosk` to
  `Workspace/Projects/Kiosk Lab`. Its source and uncommitted work were
  preserved. The formerly sourced terminal work-log hook now uses that stable
  path. Its old Pi scripts are historical until their target is verified.

## Database inventory

| Store | Location | Owner and status |
| --- | --- | --- |
| Home Platform PostgreSQL | Pi Compose `data/postgres/`; internal Docker network | Authoritative Project Hub coordination, commands, nodes, events, and reconciliation. Alembic owns schema migration. |
| Workspace Watcher `events.db` | Mac `~/Workspace/Logs/workspace-watcher/events.db` | Authoritative sensor/event history and watcher-local IDs; not authoritative project metadata. |
| Project Core `index.sqlite3` | Mac `~/Workspace/Projects/.project-core/` | Disposable local read model; `.project/` files are only authoritative within explicitly opted-in Project Core projects. |
| Workspace Sync state | mount reality, Syncthing state, restic repository on HDD | No project SQL database. Restic data is backup state, not a live Workspace mirror. |
| Kiosk state / telemetry SQLite | Kiosk Lab local/host runtime state | Kiosk-specific derived state; not read by the platform. |

No service may read or write another owner's database directly. The only
cross-owner storage contract is `GET /api/storage/contract` (Workspace Sync)
and Project Hub's read-only summary endpoint
`GET /api/v1/storage/status`.

## Live audit facts and recovery status

At the successful SSH inspection, `kiosk-lab` was a Raspberry Pi 5 running
Debian 13 on arm64. The post-reboot boot ID started at 08:56 EDT. The Home
Platform control-plane, API, automation, dashboard, Mosquitto, and Postgres
containers had recovered, as had `workspace-dashboard`, Syncthing, the kiosk
host agents, the legacy kiosk stack, and Home Assistant. The external 4.5 TB
Seagate USB HDD (`/dev/sda2`, exFAT, UUID `653E-F09E`) was mounted at
`/mnt/workspace-backup` with about 2.4 TB free.

The first post-boot backup guard correctly failed because that mount was not
yet present; the following hourly run succeeded and added a restic snapshot.
That is fail-closed behavior, but mount persistence remains a required
follow-up: verify the UUID `/etc/fstab` entry and reboot once the Pi is
reachable. Never format the existing exFAT disk to solve this.

The live Pi deployment is not fully reproducible yet: Home Platform was
running from an untracked copied tree under `/home/kiosk/home-platform`, and
Workspace Sync has no Git commit or remote. `deploy/kiosk-lab/bootstrap.sh`
defines the corrected `/opt/home-platform` + `/opt/workspace-util` layout, but
the Workspace Sync tree must first be committed and pushed. The legacy
`/opt/kiosk-lab` Compose stack remains independent and is not a bootstrap
dependency; retire it only after its kiosk hardware/UI replacement is verified.
