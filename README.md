# Home Platform

Home Platform is a private, Tailscale-only control interface and Control Plane
for the home lab. The Raspberry Pi currently hosts the hardware profile, while
the portable Control Plane role can run on a Mac or another Docker host.

## First vertical slice

The first slice provides a secured MQTT bus, PostgreSQL-backed Control Plane,
responsive Next.js Dashboard, Mac Node Service, Home Assistant integration, and
a native Arduino kiosk controller. See [architecture overview](docs/architecture/overview.md),
[host profiles](docs/operations/host-profiles.md), and [Control Plane deployment](deploy/control-plane/README.md).

## Local development

1. Copy `.env.example` to `.env` and create the untracked `secrets/` files
   documented in `deploy/control-plane/INSTALL.md`.
2. Run `docker compose up --build`.
3. Open `http://127.0.0.1:3000`.

The deployment binds the Dashboard to loopback. Pi access is provided through
Tailscale Serve, not an Internet-facing application port.
