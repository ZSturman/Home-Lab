#!/bin/ash
# Copy static policy and the password database into the writable container
# filesystem. The broker then drops to its dedicated uid without needing any
# host-mounted config file to be world-readable.
set -eu
umask 077

for path in /run/homeplatform/mosquitto.conf /run/homeplatform/acl /run/secrets/mosquitto_password_database; do
  if [ ! -r "$path" ]; then
    echo "Missing required Mosquitto input: $path" >&2
    exit 1
  fi
done

case "${HOMEPLATFORM_KIOSK_NODE_ID:-}" in
  ''|*[!a-z0-9-]*)
    echo "HOMEPLATFORM_KIOSK_NODE_ID must be a lowercase node identifier" >&2
    exit 1
    ;;
esac

cp /run/homeplatform/mosquitto.conf /mosquitto/config/mosquitto.conf
sed "s/__KIOSK_NODE_ID__/${HOMEPLATFORM_KIOSK_NODE_ID}/g" /run/homeplatform/acl >/mosquitto/config/acl
cp /run/secrets/mosquitto_password_database /mosquitto/config/mosquitto.passwd
chown mosquitto:mosquitto /mosquitto/config/mosquitto.conf /mosquitto/config/acl /mosquitto/config/mosquitto.passwd
chmod 600 /mosquitto/config/mosquitto.conf /mosquitto/config/acl /mosquitto/config/mosquitto.passwd

exec /docker-entrypoint.sh "$@"
