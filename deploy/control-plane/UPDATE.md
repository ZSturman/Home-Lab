# Update

1. Read `docker compose ps` and save current image IDs.
2. Run `python3 scripts/validate_config.py`.
3. Build and apply with `docker compose up -d --build`.
4. Confirm migrations, Core, API, Dashboard, and MQTT health in order.
5. Test the private Dashboard, Mac presence, and a safe Automation Run.

If any required check fails, return to the previous image/tag and retain the
database volume. Do not downgrade schema migrations without a tested recovery
procedure.
