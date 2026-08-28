# Home Platform: next steps to production

## Current native state

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
