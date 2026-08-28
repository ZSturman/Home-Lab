import json
import os
import platform
import socket
import subprocess
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt


MQTT_HOST = os.getenv(
    "HOMEPLATFORM_MQTT_HOST",
    "100.90.61.70",
)

MQTT_PORT = int(
    os.getenv(
        "HOMEPLATFORM_MQTT_PORT",
        "1883",
    )
)

DEVICE_ID = "macbook"
BASE_TOPIC = "homeplatform"


def now():
    return datetime.now(
        timezone.utc
    ).isoformat()


def publish_status(
    client,
    status: str,
):

    payload = {
        "status": status,
        "hostname": socket.gethostname(),
        "os": platform.platform(),
        "last_seen": now(),
    }

    client.publish(
        f"{BASE_TOPIC}/devices/{DEVICE_ID}/status",
        json.dumps(payload),
        qos=1,
        retain=True,
    )


def show_notification(
    title: str,
    message: str,
):

    script = (
        f'display notification '
        f'{json.dumps(message)} '
        f'with title '
        f'{json.dumps(title)}'
    )

    subprocess.run(
        [
            "osascript",
            "-e",
            script,
        ],
        check=True,
    )


def on_connect(
    client,
    userdata,
    flags,
    reason_code,
    properties,
):

    print(
        f"Connected to MQTT: "
        f"{reason_code}"
    )

    client.subscribe(
        f"{BASE_TOPIC}/commands/"
        f"{DEVICE_ID}/#",
        qos=1,
    )

    publish_status(
        client,
        "online",
    )


def on_message(
    client,
    userdata,
    msg,
):

    print(
        f"Received {msg.topic}: "
        f"{msg.payload}"
    )

    try:
        payload = json.loads(
            msg.payload.decode(
                "utf-8"
            )
        )

        command_id = payload.get(
            "command_id"
        )

        if msg.topic.endswith(
            "/notify"
        ):
            show_notification(
                payload.get(
                    "title",
                    "Home Platform",
                ),
                payload.get(
                    "message",
                    "",
                ),
            )

            result = {
                "command_id": command_id,
                "status": "completed",
                "timestamp": now(),
            }

        else:
            result = {
                "command_id": command_id,
                "status": "unsupported",
                "timestamp": now(),
            }

    except Exception as exc:

        result = {
            "status": "failed",
            "error": str(exc),
            "timestamp": now(),
        }

    client.publish(
        f"{BASE_TOPIC}/events/"
        f"{DEVICE_ID}/commands",
        json.dumps(result),
        qos=1,
    )


client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id=(
        f"homeplatform-"
        f"{DEVICE_ID}"
    ),
)


offline_message = {
    "status": "offline",
    "last_seen": now(),
}


client.will_set(
    f"{BASE_TOPIC}/devices/"
    f"{DEVICE_ID}/status",
    payload=json.dumps(
        offline_message
    ),
    qos=1,
    retain=True,
)


client.on_connect = on_connect
client.on_message = on_message


while True:

    try:
        client.connect(
            MQTT_HOST,
            MQTT_PORT,
            keepalive=30,
        )

        client.loop_forever()

    except Exception as exc:
        print(
            f"MQTT connection failed: "
            f"{exc}"
        )

        time.sleep(5)