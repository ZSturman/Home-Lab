# Discovery report — 2026-09-10

## What exists

Home Platform is a private Docker Compose system named `home-platform-next`.
It has a Next.js dashboard, a FastAPI Control Plane, PostgreSQL for durable
state, Mosquitto for internal node communication, an Automation Controller,
and a Mac node. The Pi hardware profile additionally provides a native kiosk
controller, `go2rtc` camera ingress, and a media controller.

The Control Plane is already the shared state boundary. It owns nodes,
service-provider health, alerts, command history, automation runs, projects,
reconciliation items, and resources. The dashboard must continue to use its
HTTP API rather than query PostgreSQL or MQTT directly.

Workspace Sync & Backup Utility is a sibling service, not a dependency to
merge into this repository. It owns storage mounts, Syncthing, restic,
camera capture, backup operations, and the Mac file bridge. Home Platform
currently consumes its narrow, authenticated storage-status contract.

## Existing real integrations

| Integration | Current interface | Discovery result |
| --- | --- | --- |
| Pi/Control Plane | FastAPI, MQTT, PostgreSQL | Implemented |
| Mac node | MQTT with HTTP job polling | Implemented |
| Workspace/backup | Workspace Sync status contract | Implemented |
| Projects/Notion | Control Plane project/reconciliation APIs | Implemented; Notion is token-configured externally |
| Home Assistant | Control Plane integration | Configured extension point; availability is reported at runtime |
| Camera | `go2rtc` + media controller, Pi hardware profile | Profile-gated; provider health is the current safe source |
| LM Studio | Mac-node service provider | Registered; no chat/model API is implemented yet |
| ComfyUI, Tapo, Audiobookshelf, flashcards, Discovery | None found | Not configured / not implemented; must not be represented as working |

## Routing and deployment risk

The intended deployment is `Tailscale Serve -> 127.0.0.1:3000` (the Next.js
dashboard), while Workspace Sync listens separately on Tailscale port 8787.
Initial checks found the public Tailnet root serving the Workspace dashboard
login. The `kiosk` service account was then verified over SSH: Home Platform's
Compose stack was healthy on loopback `:3000`, and Serve was still proxying
the root to Workspace Sync on `:8787`. The deployment corrected Serve to
`127.0.0.1:3000`; Workspace Sync remains healthy on its direct Tailscale
address and port 8787.

## Refactor decision

Keep the Compose project name, database, MQTT topics, provider contracts,
Workspace Sync boundary, and safe command/automation model. Replace the
production dashboard's simulated Demo Lab with a device-aware application
shell whose views are derived from one Control Plane overview payload plus
the existing specialized endpoints. New integrations must register a real
provider or display an explicit unavailable state; no sample cards or
invented charts are permitted.

## Known risks before change

- The live HTTPS route does not currently match the documented Home Platform
  target, so a code change alone cannot satisfy live validation.
- The current dashboard contains simulated interaction data, which conflicts
  with the production real-data requirement.
- Several requested systems have no discovered configuration/API and must be
  visibly blocked rather than stubbed as successful.
- Home Platform has no browser identity/role model beyond its private
  Tailnet/Serve boundary. Any expansion of destructive capabilities requires
  server-side authorization design before exposing controls.
