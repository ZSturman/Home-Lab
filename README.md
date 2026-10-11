# Home Platform

![Actual automation cancellation](../docs/images/functional-home-lab-stop.jpg)

## Functional state — October 6, 2026

Full isolated dashboard/API/Mac-handler flows are in the [parent functional audit](../docs/FUNCTIONAL_AUDIT.md). Real directories, initialization, durable replay, safe completion/Stop and restart persistence passed after routing, UTC and cancellation fixes. Live MQTT/Watcher/Notion/Home Assistant/Pi and physical Safari remain unverified. This is an active incomplete utility; the [parent README](../README.md) separates platforms, and [next steps](../docs/NEXT_STEPS.md) records the primary integration action.

Home Platform is a private, Tailscale-only control interface and Control Plane
for the home lab. The Raspberry Pi currently hosts the hardware profile, while
the portable Control Plane role can run on a Mac or another Docker host.

## First vertical slice

The first slice provides a secured MQTT bus, PostgreSQL-backed Control Plane,
responsive Next.js Dashboard, Mac Node Service, Home Assistant integration, and
a native Arduino kiosk controller. See [architecture overview](docs/architecture/overview.md),
[host profiles](docs/operations/host-profiles.md), and [Control Plane deployment](deploy/control-plane/README.md).

## Bidirectional Project Hub

The Control Plane also keeps the Notion Projects database and
`~/Workspace/Projects` in sync, with phone-initiated project creation. See
[docs/project-hub.md](docs/project-hub.md) for the data model, API, MQTT
topics, and reconciliation algorithm. Requires a Notion integration token in
`secrets/notion_token` (see `deploy/control-plane/bootstrap-secrets.sh`) --
leave that file empty to disable Notion sync without an error.

The Pi-wide ownership decision, database boundaries, offline behavior, and
fresh-host recovery sequence are documented in
[Workspace and kiosk-lab ownership](docs/architecture/ecosystem-ownership.md)
and [kiosk-lab provisioning](deploy/kiosk-lab/README.md).

## Local development

1. Copy `.env.example` to `.env` and create the untracked `secrets/` files
   documented in `deploy/control-plane/INSTALL.md`.
2. Run `docker compose up --build`.
3. Open `http://127.0.0.1:3000`.

The deployment binds the Dashboard to loopback. Pi access is provided through
Tailscale Serve, not an Internet-facing application port.

## Home Platform vNext

The production dashboard uses a shared Control Plane overview for Now, Home,
Projects, Learn, Media, AI, Files, Automations, Data, and System. It never
uses sample data: missing integrations are explicitly shown as unavailable.

- [Discovery report](docs/discovery-2026-09-10.md)
- [Design plan](docs/design-plan.md)
- [View catalog](docs/views.md)
- [Integration catalog](docs/integrations.md)
- [Testing matrix](docs/testing.md)
- [Acceptance report](docs/acceptance-2026-09-10.md)
- [Follow-up work](docs/future-work.md)
