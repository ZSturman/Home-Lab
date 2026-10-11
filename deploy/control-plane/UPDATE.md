# Update

1. Read `docker compose ps` and save current image IDs.
2. Run `python3 scripts/validate_config.py`.
3. Build and apply with `docker compose up -d --build`.
4. Confirm migrations, Core, API, Dashboard, and MQTT health in order.
5. Test the private Dashboard, `GET /api/v1/platform/overview`, Mac presence,
   and a safe Automation Run.

Before applying an update on `kiosk-lab`, verify the live routing is still
`Tailscale Serve -> 127.0.0.1:3000`; do not replace the Workspace Sync service
on 8787 or create a second Compose project. After update, test the private
HTTPS URL at the device widths listed in `docs/testing.md`.

If any required check fails, return to the previous image/tag and retain the
database volume. Do not downgrade schema migrations without a tested recovery
procedure.
