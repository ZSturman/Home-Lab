# Install the Control Plane

1. Copy this repository to the target Docker host. Set its stable identity in
   `.env` before starting anything. A Mac host should use the existing
   `macbook` Node identity; the Pi hardware host uses `pi-control-plane`.
   See [host profiles](../../docs/operations/host-profiles.md).
2. Create Docker secret files without placing passwords in `.env`. Their host
   permissions keep them inaccessible to the deploy user; root can read them
   and only the Mosquitto runtime user can read its password database:

   ```sh
   sh deploy/control-plane/bootstrap-secrets.sh
   ```

   Put the least-privilege Home Assistant token in
   `secrets/home_assistant_token` only when the Home Assistant slice is ready.
3. Keep the Dashboard bound to `127.0.0.1:3000` and MQTT on loopback unless a
   remote authenticated Node requires a Tailnet binding. Do not retain a prior
   broker as a compatibility layer.
4. Validate config, build, and start the portable stack:

   ```sh
   python3 scripts/validate_config.py
   docker compose config --quiet
   docker compose up -d --build
   docker compose ps
   ```

   On the Pi only, add `--profile pi-hardware` to the `up` command after
   verifying the Arduino and webcam device paths.

5. Point that host's Tailscale Serve at `http://127.0.0.1:3000` only after the
   Dashboard health page and Node test pass. Do not expose MQTT, PostgreSQL,
   API, Home Assistant, or go2rtc through Serve.

## Recovery

Use the backup/restore procedure in [RECOVER.md](RECOVER.md) for data recovery.
Do not keep an old MQTT broker or adapter running as a routine rollback path.
