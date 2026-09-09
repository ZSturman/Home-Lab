#!/usr/bin/env bash
# Bootstrap the non-destructive, version-controlled services on kiosk-lab.
#
# This script deliberately does not format, repartition, or activate a disk.
# Those actions require an operator to use Workspace Sync's confirmation-gated
# disk-setup.sh first. It is safe to rerun after the two repositories, secrets,
# and mount configuration have been restored.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: sudo deploy/kiosk-lab/bootstrap.sh [--enable-serve]

Required layout (override Workspace Sync with WORKSPACE_UTIL_ROOT):
  /opt/home-platform     this checkout
  /opt/workspace-util    Workspace Sync & Backup Utility checkout

The script installs Workspace Sync's versioned systemd units, starts the
control-plane Compose stack, and enables its safe timers. --enable-serve also
configures Tailscale Serve to proxy the private Dashboard on port 3000.
EOF
}

enable_serve=false
if [[ "${1:-}" == "--enable-serve" ]]; then
  enable_serve=true
  shift
fi
[[ $# -eq 0 ]] || { usage >&2; exit 64; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo 'Run this script with sudo.' >&2; exit 77; }

platform_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
workspace_util_root="${WORKSPACE_UTIL_ROOT:-/opt/workspace-util}"
run_user="${KIOSK_LAB_USER:-kiosk}"

require_file() {
  [[ -f "$1" ]] || { echo "Required file is missing: $1" >&2; exit 66; }
}
require_command() {
  command -v "$1" >/dev/null || { echo "Required command is missing: $1" >&2; exit 69; }
}

require_command docker
require_command systemctl
require_command tailscale
require_command curl
require_command findmnt
require_file "$platform_root/.env"
require_file "$platform_root/docker-compose.yml"
require_file "$platform_root/deploy/kiosk-lab/kiosk-browser.service"
require_file "$platform_root/deploy/kiosk-lab/kiosk-browser.desktop"
require_file "$workspace_util_root/services/pi/workspace-dashboard.service"
require_file /etc/workspace-util/config.yaml
require_file /etc/workspace-util/secrets.env

echo '== Validating Home Platform configuration =='
cd "$platform_root"
# The control-plane dependencies intentionally live in its container image;
# a fresh Pi host is not required to have pydantic installed globally. Use a
# development venv when one is present, otherwise let Compose validate the
# deployable configuration below instead of failing before it can build.
if [[ -x control-plane/.venv/bin/python ]]; then
  control-plane/.venv/bin/python scripts/validate_config.py
else
  echo 'Skipping host-side Python config validation (container dependencies are not installed on this host).'
fi
docker compose --env-file .env config --quiet

echo '== Installing Workspace Sync systemd definitions =='
install -m 0644 "$workspace_util_root"/services/pi/*.service /etc/systemd/system/
install -m 0644 "$workspace_util_root"/services/pi/*.timer /etc/systemd/system/
systemctl daemon-reload

# Dashboard is useful even while the production Workspace SSD is intentionally
# absent. The backup timer is fail-closed: its guard refuses an unmounted HDD.
systemctl enable --now workspace-dashboard.service
systemctl enable --now workspace-backup.timer workspace-backup-retention.timer workspace-backup-check.timer

echo '== Installing kiosk browser startup policy =='
kiosk_home="$(getent passwd "$run_user" | cut -d: -f6)"
[[ -n "$kiosk_home" ]] || { echo "Could not resolve home directory for $run_user" >&2; exit 66; }
install -d -m 0755 -o "$run_user" -g "$run_user" "$kiosk_home/.config/systemd/user" "$kiosk_home/.config/autostart"
install -m 0644 -o "$run_user" -g "$run_user" "$platform_root/deploy/kiosk-lab/kiosk-browser.service" "$kiosk_home/.config/systemd/user/kiosk-browser.service"
install -m 0644 -o "$run_user" -g "$run_user" "$platform_root/deploy/kiosk-lab/kiosk-browser.desktop" "$kiosk_home/.config/autostart/kiosk-browser.desktop"

echo '== Starting Home Platform =='
docker compose --env-file .env up -d --build

if "$enable_serve"; then
  echo '== Configuring tailnet-only HTTPS =='
  tailscale serve --https=443 http://127.0.0.1:3000
fi

echo '== Verifying local services =='
runuser -u "$run_user" -- "$platform_root/deploy/kiosk-lab/verify.sh"
echo 'Bootstrap completed. Disk activation remains a separate, confirmation-gated step.'
