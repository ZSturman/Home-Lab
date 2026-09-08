#!/usr/bin/env bash
# Read-only health verification for a provisioned kiosk-lab host.
set -euo pipefail

failures=0
check() {
  local label="$1"; shift
  if "$@"; then
    printf 'ok  %s\n' "$label"
  else
    printf 'ERR %s\n' "$label" >&2
    failures=$((failures + 1))
  fi
}

check 'workspace dashboard service' systemctl is-active --quiet workspace-dashboard.service
# Workspace Sync deliberately binds to the Pi's Tailscale address, not
# loopback or the public LAN. Resolve that address instead of falsely
# reporting an active private dashboard as unavailable.
tailscale_ip="$(tailscale ip -4)"
check 'workspace dashboard health' curl --fail --silent --show-error "http://${tailscale_ip}:8787/api/health"
check 'Home Platform Compose stack' docker compose ls --format json
check 'Home Platform API through Dashboard proxy' curl --fail --silent --show-error http://127.0.0.1:3000/api/v1/system/snapshot

if findmnt --mountpoint /mnt/workspace-backup >/dev/null 2>&1; then
  printf 'ok  backup HDD mounted at /mnt/workspace-backup\n'
else
  printf 'WARN backup HDD is not mounted; backup timers will fail closed until it is restored\n' >&2
fi

tailscale serve status
exit "$failures"
