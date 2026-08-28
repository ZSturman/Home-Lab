#!/usr/bin/env sh
# Create the local files consumed as Docker secrets. Never print their values.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$ROOT"
umask 077

if [ ! -f .env ]; then
  cp .env.example .env
fi
mkdir -p secrets data/postgres data/mosquitto

new_secret() {
  path="secrets/$1"
  if [ ! -s "$path" ]; then
    openssl rand -hex 32 >"$path"
  fi
  chmod 600 "$path"
}

new_secret postgres_password
new_secret mqtt_control_plane_password
new_secret mqtt_macbook_password
new_secret mqtt_kiosk_controller_password
new_secret mqtt_health_password

# Home Assistant is explicitly opt-in. Put the least-privilege token in this
# file after it is created in Home Assistant; an empty file keeps the API safe.
if [ ! -f secrets/home_assistant_token ]; then
  : >secrets/home_assistant_token
fi
chmod 600 secrets/home_assistant_token

if [ ! -f secrets/mosquitto.passwd ]; then
  docker run --rm -v "$ROOT/secrets:/secrets" eclipse-mosquitto:2.0.22 sh -ec '
    password() { tr -d "\\r\\n" <"/secrets/$1"; }
    mosquitto_passwd -b -c /secrets/mosquitto.passwd control-plane "$(password mqtt_control_plane_password)"
    mosquitto_passwd -b /secrets/mosquitto.passwd macbook "$(password mqtt_macbook_password)"
    mosquitto_passwd -b /secrets/mosquitto.passwd kiosk-controller "$(password mqtt_kiosk_controller_password)"
    mosquitto_passwd -b /secrets/mosquitto.passwd healthcheck "$(password mqtt_health_password)"
    chown root:root /secrets/mosquitto.passwd
    chmod 600 /secrets/mosquitto.passwd
  '
  # Host root owns this 0600 database. The broker entrypoint copies it into its
  # private runtime filesystem before Mosquitto drops privileges.
fi

printf '%s\n' 'Docker secret files are ready. MQTT and database passwords were not printed.'
