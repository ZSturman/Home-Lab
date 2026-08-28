# Ingress and secrets

The private Dashboard is available only through Tailscale Serve. It is not a
Cloudflare origin and has no public listener.

MQTT is protected by per-client credentials and ACLs. The portable default
binds it to loopback; bind it to a host's Tailscale address only when a remote
authenticated Node needs it. Do not re-enable anonymous MQTT to troubleshoot a
connection.

Future public sharing uses a separate `public-share-web` deployment connected
through Cloudflare Tunnel at `share.zachary-sturman.com`. Its origin may only
serve hashed Share Session token routes. It must not proxy `/api/v1`, private
Dashboard pages, MQTT, files, or go2rtc.

Secrets live outside Git:

- Pi: root-readable `secrets/` files or Docker secrets.
- Mac: Keychain items referenced by the LaunchAgent.
- Config: opaque `secret://` references only.

Rotate a credential by adding its replacement, updating the dependent service,
validating the new health report, then revoking the old credential.
