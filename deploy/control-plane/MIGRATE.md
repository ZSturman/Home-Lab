# Migrate the Control Plane role

1. Provision the replacement Node with Docker, Tailscale, and encrypted storage.
2. Stop writes, back up PostgreSQL, `config/`, `secrets/`, data volumes, and
   Automation journals.
3. Restore them to the replacement under a new deployment path; validate
   Compose, migrations, MQTT, and Control Plane health without changing Serve.
4. Move the stable Tailscale Serve target, then verify Node reconnection,
   Desired State delivery, routes, dashboard, safe Automation, Home Assistant,
   and the direct kiosk controller.
5. After backup/restore validation, retire the former Control Plane. It must
   not remain connected as a second MQTT or device-control path.
