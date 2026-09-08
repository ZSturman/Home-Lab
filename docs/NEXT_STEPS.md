# Home Platform: next steps to production

> **Audit correction — 2026-09-08:** The notes below predate the ecosystem
> recovery audit and are retained only as historical context. Do not use them
> as the current deployment record. The current ownership and recovery source
> is [ecosystem ownership](architecture/ecosystem-ownership.md), with the
> runnable host procedure in [kiosk-lab provisioning](../deploy/kiosk-lab/README.md).

## Current recovery state

The successful SSH audit found the Pi booted cleanly at 08:56 EDT with the
`home-platform-next` Compose project running its Control Plane API, core,
automation controller, Dashboard, Mosquitto, Postgres, and media controller.
The `projects` and `reconciliation_items` Postgres tables existed, so the
Project Hub migration is present in the live database. Workspace Sync's
dashboard, timers, Syncthing, kiosk host services, Home Assistant, and the
legacy `/opt/kiosk-lab` Compose stack also recovered.

Two hardware-profile containers were not healthy at that observation:
`home-platform-next-kiosk-controller-1` was only **Created**, and
`home-platform-next-go2rtc-1` had exited four days earlier. They are not
dependencies of Project Hub or Workspace Sync and must not be silently
promoted as healthy in UI or documentation.

The backup HDD was mounted eventually and an hourly restic backup succeeded,
but the first backup guard after boot failed because the mount was absent.
When connectivity is restored, verify its UUID `/etc/fstab` mount and perform
one controlled reboot. Do not format the existing exFAT drive.

The Pi became unreachable from both Tailscale and its last known LAN address
during this audit after the successful SSH session. No remote change was made
after that loss. Restore network/power access before any deployment or reboot
action, then run `deploy/kiosk-lab/verify.sh` and record its output.

### Required next actions

1. Commit and push **Workspace Sync & Backup Utility** to an owned remote; it
   currently has no commits or remote, so a replacement Pi cannot recover it.
2. Replace the live copied Home Platform tree with the documented
   `/opt/home-platform` checkout and use `deploy/kiosk-lab/bootstrap.sh` only
   after the Pi is reachable and secrets are restored.
3. Verify the external HDD's UUID mount persistence and repeat a reboot test.
4. Investigate the stopped `go2rtc` and never-started kiosk-controller profile
   only if the corresponding camera/Arduino hardware is still intended to be
   part of the live platform.
5. Keep the legacy `/opt/kiosk-lab` stack separate until a dedicated Home
   Assistant MQTT/kiosk migration proves it can be retired.

## Historical native-state notes

The first vertical slice runs on the Pi at
`/home/kiosk/home-platform/home-platform-next` as Compose project
`home-platform-next`.

- Dashboard: Pi loopback only at `http://127.0.0.1:3000`.
- API and PostgreSQL: internal Docker network only.
- Authenticated Platform MQTT: `100.90.61.70:1883` over Tailscale. The Mac
  Node is reconnected on this canonical port.
- `kiosk-controller` directly owns the Arduino Mega at `/dev/ttyACM0`. It has
  verified the installed KIOSK/1 firmware (`firmware=2`, `capabilities=leds`),
  publishes retained Node state and device Events, and receives retained Alert
  LED state.
- Home Assistant authentication, the configured living-room entity read, and a
  no-op brightness service call have passed. The entity reports a 2000–6535 K
  range. The Dashboard/API, safe Automation Run, and Mac Node presence have
  also passed. The USB Logitech Brio 101 is managed by go2rtc with its API,
  RTSP, and WebRTC ports restricted to the Pi Tailnet address.

The previous serial daemon is disabled and the Platform has no legacy adapter,
legacy mirror mode, or connection to the old kiosk MQTT broker. The obsolete
prototype Compose containers are stopped and the private Dashboard is served at
`https://kiosk-lab.tailef7acc.ts.net` by Tailscale Serve to Pi loopback port
3000.

The adapter source and adapter-only secrets have been removed from the active
Platform deployment. The old `/opt/kiosk-lab` Home Assistant container and its
own broker are still temporarily required by its retained Home Assistant MQTT
package and dashboards; they are not on the Platform control path. Retiring
that remaining old broker requires a separate Home Assistant MQTT migration.

The same base Compose stack now has an explicit host identity and a portable
`standard` profile. It can be moved to macOS for the Dashboard, API,
automation, MQTT, and Mac Node capabilities; the Pi-only Arduino and webcam
services start only with the `pi-hardware` profile.

## Mac portable instance

The Mac standard profile has been started locally as Compose project
`home-platform-mac`. Its Dashboard is private at the Mac's Tailscale Serve
hostname and the Mac Node is connected to its local authenticated MQTT broker.
This is a fresh local PostgreSQL database, not a migration of the Pi's durable
history or hardware state. Do not run both as active Control Planes when the
Pi returns: follow the documented backup/restore migration before choosing one
authoritative host.

## Current acceptance remaining

1. Move the joystick once in each direction, tap the stick, then hold it for
   at least one second. Confirm the resulting Home Assistant changes and
   Platform Events. The controller's configuration mount is now in place;
   these input actions are live against the living-room lights. Green-only is
   the expected normal LED state; it confirms the Platform ping and LED frame
   are reaching the Arduino.
2. The Brio snapshot has passed from a second Tailnet device and the Platform
   reports a healthy producer. Keep go2rtc out of Tailscale Serve and
   Cloudflare; a physical viewing/client-quality check can be repeated when an
   observer is at the Pi.
3. Migrate or intentionally retire the old Home Assistant MQTT package before
   stopping its old broker. Do not remove the Arduino firmware or Home
   Assistant configuration before that migration.

## Historical Project Hub cutover checklist

The Project Hub work (notion_client.py, reconciliation.py, the `projects`/
`reconciliation_items` tables, the workspace-storage contract client) was
built and tested locally against this repo's uncommitted working tree but
had **not** been deployed to the Pi's running `home-platform-next` stack.
Before deploying it:

- `docker-compose.yml`'s top-level `name:` was drifting (`home-platform` vs.
  the Pi's actually-running `home-platform-next` project) -- fixed back to
  `home-platform-next` so `docker compose up -d --build` updates the
  existing containers in place instead of standing up a second, parallel
  stack. See the comment on that line.
- `secrets/notion_token` must exist on the Pi with the real integration
  token (it does not yet -- the Pi's deployed secrets predate this feature).
- `secrets/workspace_contract_token` must exist on the Pi, containing the
  same value as Workspace Sync & Backup Utility's `WORKSPACE_DASHBOARD_TOKEN`
  (from that project's `/etc/workspace-util/secrets.env`), and
  `WORKSPACE_CONTRACT_URL` must be set in the Pi's `.env`.
- No port/network/container-name changes were needed: this project's ports
  (1883 host-bound, 3000 loopback-only, 8080/5432 internal-only) never
  collided with Workspace Sync & Backup Utility's (8787/8788, Tailscale-
  bound only) or the legacy `/opt/kiosk-lab` stack's (8080 host-bound,
  1883 loopback-only -- a different bind address, so no actual conflict,
  but see `docs/kiosk-lab-platform.md` for why that legacy MQTT broker
  still needs its own migration/retirement independent of this work).

See `docs/kiosk-lab-platform.md` for the full Pi-wide picture.

## Later phases (not part of this cutover)

- Wrap Social Posts and Portfolio Publish as Mac-executed Automations only
  after dry-run/check-only parity tests; preserve their approval/journal and QA
  invariants.
- Add Notion cache, analytics imports, Restic simulation/restore verification,
  media abstractions, and configured file roots independently.
- Build public sharing as a separate `public-share-web` deployment. Only its
  token routes may use the Cloudflare Tunnel hostname
  `share.zachary-sturman.com`; the private Dashboard and internal API never do.
  It remains blocked on a Cloudflare Tunnel credential and an explicit choice
  of shareable resource and expiry/access policy.
