# kiosk-lab provisioning and recovery

`Home Lab/home-platform` is the authoritative deployment repository for the
Pi's containerized control plane. `Workspace Sync & Backup Utility` remains a
separate source repository because it owns physical storage, restic, Syncthing,
and its systemd units. This directory is the host-level contract that joins
those two deliberately separate concerns without coupling their databases.

## Fresh Pi recovery

1. Install Debian 13 / Raspberry Pi OS 64-bit, create the `kiosk` user, and
   install Docker Compose, Python 3, Tailscale, Syncthing, restic, and curl.
2. Join the tailnet and confirm `tailscale status` sees the Mac. Install the
   Mac's public key for `kiosk`; use `ssh kiosk@kiosk-lab`, never the macOS
   username.
3. Restore the two source checkouts to `/opt/home-platform` and
   `/opt/workspace-util`. The Home Platform remote is
   `https://github.com/ZSturman/Home-Lab.git`. Workspace Sync has no remote or
   commit at this audit, so it must be committed and pushed before this flow is
   genuinely disaster-recoverable; the bootstrap script intentionally never
   invents a repository URL.
4. Restore `/opt/home-platform/.env`, its `secrets/` directory, and
   `/etc/workspace-util/{config.yaml,secrets.env}` from the secret backup.
   Never restore them from git or logs.
5. Attach the backup HDD. For a replacement drive or a host lacking a stable
   `/etc/fstab` entry, run `/opt/workspace-util/scripts/disk-setup.sh backup`
   and choose the existing data partition **without** `--format`. Confirm the
   UUID mount using `findmnt /mnt/workspace-backup`. Do the equivalent
   confirmation-gated step for a future production Workspace SSD/NVMe.
6. Run one idempotent command:

   ```sh
   cd /opt/home-platform
   sudo WORKSPACE_UTIL_ROOT=/opt/workspace-util deploy/kiosk-lab/bootstrap.sh --enable-serve
   ```

7. Verify the result with `deploy/kiosk-lab/verify.sh`, then from the Mac run
   `tailscale ping kiosk-lab`, `ssh kiosk@kiosk-lab`, and request
   `https://kiosk-lab.tailef7acc.ts.net/api/v1/system/snapshot`.

`bootstrap.sh` never formats disks, creates a Workspace mirror on the Pi's SD
card, or starts the legacy kiosk stack. Workspace Sync's mount guards retain
their fail-closed behavior.

## Persistent-state recovery

- Restore the Home Platform Postgres bind-mounted `data/postgres/` only while
  the control-plane stack is stopped, then let Compose run Alembic migrations.
- The backup HDD's restic repository is recovered with the existing
  `WORKSPACE_BACKUP_PASSWORD`; without it, snapshots are intentionally
  unreadable.
- The Mac's real `~/Workspace` directories remain primary source files. The Pi
  stores coordination state, storage/backup state, and optional mirrors—not
  the canonical development checkout.
- Do not restore or start `/opt/kiosk-lab` as part of this procedure. It is a
  separately assessed legacy deployment, not a dependency of the platform.
