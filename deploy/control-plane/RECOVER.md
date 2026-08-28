# Recover

Restore PostgreSQL and state volumes from a known-good backup to an isolated
directory first. Validate configuration checksums, MQTT ACL files, service
health, and Node reconnection before redirecting Tailscale Serve. Never recover
secrets from logs, browser storage, or MQTT retained messages.
