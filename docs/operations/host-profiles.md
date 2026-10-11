# Host profiles and portable deployment

The Control Plane role is portable. Its identity is explicit rather than
inferred from a hostname or CPU architecture:

| Setting | Purpose |
| --- | --- |
| `HOMEPLATFORM_NODE_ID` | Stable Node identity that owns locally attached services. |
| `HOMEPLATFORM_NODE_NAME` | Human-readable name shown by the Dashboard. |
| `HOMEPLATFORM_NODE_HOSTNAME` | Hostname reported by Pi-attached services; it is not used by the portable profile. |
| `HOMEPLATFORM_HARDWARE_PROFILE` | `standard` for a portable Core, or `pi-hardware` when the Pi USB services are enabled. |

The default Compose invocation starts the portable Core only: PostgreSQL,
authenticated MQTT, API, automation controller, and loopback Dashboard. This
works on a Mac or a Pi and does not request an Arduino serial device or Linux
video device.

On the Pi, configure the identity as `pi-control-plane` / `Home Pi`, set
`HOMEPLATFORM_HARDWARE_PROFILE=pi-hardware`, and start the optional hardware
services deliberately:

```sh
docker compose --profile pi-hardware up -d --build
```

That profile includes go2rtc and `media-controller`. Its USB mapping is
configured through `WEBCAM_HOST_DEVICE`; do not enable this profile on macOS
Docker Desktop.

On a Mac hosting the Control Plane, use a stable Node id already represented
in `config/nodes.yaml` (currently `macbook`), for example:

```dotenv
HOMEPLATFORM_NODE_ID=macbook
HOMEPLATFORM_NODE_NAME=Zachary's MacBook Pro
HOMEPLATFORM_HARDWARE_PROFILE=standard
MQTT_BIND_IP=127.0.0.1
```

If an older local `.env` belongs to another deployment, preserve it and use a
separate runtime file instead. The included `.env.mac` is a local example for
this Mac; start it with `docker compose --env-file .env.mac` so both Compose
and its services use the same selected profile.

The dashboard remains loopback-only. Publish only that port privately through
the Mac's Tailscale client:

```sh
tailscale serve --bg 3000
tailscale serve status
```

Open the resulting Tailnet HTTPS name from the phone while it is signed into
the same Tailnet. Do not Serve MQTT, PostgreSQL, FastAPI, Home Assistant, or
go2rtc.

Moving the role is a migration, not an active-active setup. Before redirecting
the Mac Node Service to a locally hosted broker, stop its connection to the
former broker, provision its matching MQTT credential in the new broker, and
then verify a single retained `macbook` presence record.

The supported Mac Node implementation is `nodes/mac/`. The older unreferenced
`mac-agent/` directory is not part of this deployment path and must not be
started alongside it.
