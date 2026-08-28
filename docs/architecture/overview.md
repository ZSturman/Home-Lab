# Architecture overview

```text
Trusted browser ── Tailscale Serve ── Next.js Dashboard ── FastAPI API
                                                   │             │
                                                PostgreSQL   Mosquitto
                                                   │             │
                           Automation Controller ──┘             ├── Mac Node Service
                                                                 ├── Home Assistant integration
                                                                 ├── Native Arduino kiosk controller
                                                                 └── Private Brio webcam (go2rtc)
```

The Control Plane owns Desired State, configuration revisions, command history,
alerts, Automation Runs, and cached read models. Nodes own only their local
Actual State, capabilities, and allowlisted execution. The host that owns the
Control Plane is identified by `HOMEPLATFORM_NODE_ID` and
`HOMEPLATFORM_NODE_NAME`, not by a hard-coded Pi assumption.

The Dashboard never connects to MQTT. The browser uses the Dashboard origin’s
`/api/v1` reverse proxy and WebSocket path; FastAPI reads durable state from
PostgreSQL. MQTT remains the internal state and command bus.

## Runtime boundaries

- `postgres`: durable data only; no host port.
- `mosquitto`: authenticated MQTT; bind to the Pi Tailscale IP only after the
  Mac Node credential is installed.
- `control-plane-core`: validates MQTT, projects it to PostgreSQL, and publishes
  retained Desired State.
- `control-plane-api`: REST and browser WebSocket API; separate from scheduling.
- `automation-controller`: durable Automation Run executor.
- `dashboard`: loopback-only Next.js private UI.
- `kiosk-controller`: the Platform-owned owner of the Arduino Mega USB serial
  device. It validates KIOSK/1 packets, publishes Platform device Events,
  applies retained Alert LED state, and invokes the configured light actions.
  It is restricted to its own MQTT state/input topics and has no legacy-broker
  network connection.
- `go2rtc`: private webcam ingress and streaming. Its API, RTSP, and WebRTC
  ports bind to the Pi Tailscale address only; they are not Serve or Cloudflare
  targets.
- `media-controller`: reports go2rtc's private stream health as a Platform
  Service. It starts only with the `pi-hardware` Compose profile.

The base Compose profile is hardware-neutral and may run on macOS. The
`pi-hardware` profile explicitly adds the Arduino and USB webcam services;
see [host profiles](../operations/host-profiles.md).

## State rules

Desired State is versioned YAML checked into `config/`, validated before
publication, persisted with a checksum, then distributed as retained MQTT.
Actual State is reported by Nodes and Services. A command is inserted into
PostgreSQL before it is sent and receives an idempotent result by correlation ID.

The canonical terminology is defined in [terminology](../terminology/README.md).
