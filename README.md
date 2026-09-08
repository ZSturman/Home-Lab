# Home Platform

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
