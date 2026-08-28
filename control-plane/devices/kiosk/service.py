"""Platform-owned serial driver for the Arduino Mega kiosk controller."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import signal
import socket
import threading
import time

import paho.mqtt.client as mqtt
import serial

from app.home_assistant import HomeAssistantClient
from app.mqtt import MqttPublisher, envelope
from app.settings import get_settings
from app.topics import ALERTS_CURRENT, BASE_TOPIC, node_actual_state, node_capabilities, node_presence

from .motion import MotionInterpreter
from .protocol import ProtocolError, led_frame, parse_line


LOG = logging.getLogger("homeplatform-kiosk-controller")
INPUT_TOPIC = f"{BASE_TOPIC}/devices/kiosk/input"
ACTION_RESULT_TOPIC = f"{BASE_TOPIC}/devices/kiosk/action-result"
DEFAULT_LED = {
    "red": {"mode": "off", "intervalMs": 500},
    "blue": {"mode": "blink", "intervalMs": 700},
    "green": {"mode": "solid", "intervalMs": 500},
    "yellow": {"mode": "off", "intervalMs": 500},
}


class KioskController:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.node_id = self.settings.platform_node_id
        self.running = True
        self.port = os.environ.get("KIOSK_CONTROLLER_PORT", "/dev/ttyACM0")
        self.hostname = os.environ.get("HOMEPLATFORM_NODE_HOSTNAME", socket.gethostname())
        self.latest_led = DEFAULT_LED
        self.interpreter = MotionInterpreter()
        self.last_action_at = 0.0
        self.state = "starting"
        self.state_detail = ""
        self.firmware: str | None = None
        self.device_capabilities: list[str] = []
        self.publisher = MqttPublisher(self.settings, "kiosk-controller")
        self.publisher.client.on_connect = self.on_platform_connect
        self.publisher.client.on_message = self.on_platform_message
        self.publisher.client.will_set(
            node_presence(self.node_id),
            json.dumps(envelope("kiosk-controller", {
                "status": "offline", "hostname": self.hostname, "os": platform.platform(), "health": "offline",
            }), separators=(",", ":")),
            qos=1,
            retain=True,
        )

    def publish_state(self, status: str, *, detail: str = "") -> None:
        self.state, self.state_detail = status, detail
        healthy = "healthy" if status == "connected" else "degraded"
        self.publisher.publish_event(
            node_presence(self.node_id),
            {"status": "online", "hostname": self.hostname, "os": platform.platform(), "health": healthy},
            retain=True,
        )
        self.publisher.publish_event(
            node_actual_state(self.node_id),
            {"kiosk_controller": {
                "status": status,
                "port": self.port,
                "detail": detail,
                "firmware": self.firmware,
                "device_capabilities": self.device_capabilities,
            }},
            retain=True,
        )
        self.publisher.publish_event(
            node_capabilities(self.node_id),
            {"capabilities": ["kiosk-controller", "joystick-input", "status-led", "home-assistant-light-control"]},
            retain=True,
        )

    def on_platform_connect(
        self, client: mqtt.Client, userdata: object, flags: object, reason: object, properties: object,
    ) -> None:
        self.publisher._on_connect(client, userdata, flags, reason, properties)
        if getattr(reason, "is_failure", False):
            return
        client.subscribe(ALERTS_CURRENT, qos=1)
        self.publish_state(self.state, detail=self.state_detail)

    def on_platform_message(self, _client: mqtt.Client, _userdata: object, message: mqtt.MQTTMessage) -> None:
        if message.topic != ALERTS_CURRENT:
            return
        try:
            candidate = json.loads(message.payload.decode())["payload"]["led"]
            led_frame(candidate)
            self.latest_led = candidate
        except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError, ProtocolError, ValueError) as exc:
            LOG.warning("Rejected invalid Platform LED projection: %s", exc)

    def run(self) -> None:
        self.publisher.start()
        retry = 1.0
        while self.running:
            try:
                with serial.Serial(self.port, 115200, timeout=0.25, write_timeout=1) as connection:
                    retry = 1.0
                    self.interpreter = MotionInterpreter()
                    self.publish_state("connected")
                    LOG.info("Connected to Arduino Mega at %s", self.port)
                    self.session(connection)
            except (serial.SerialException, OSError) as exc:
                LOG.warning("Serial unavailable at %s: %s", self.port, exc)
                self.publish_state("disconnected", detail=str(exc))
                time.sleep(retry)
                retry = min(retry * 2, 10)
        self.publisher.stop()

    def session(self, connection: serial.Serial) -> None:
        last_ping = 0.0
        while self.running:
            now = time.monotonic()
            if now - last_ping >= 2:
                connection.write(b"KIOSK/1 PING\n")
                connection.write(led_frame(self.latest_led))
                last_ping = now
            raw = connection.readline()
            if not raw:
                continue
            try:
                event = parse_line(raw)
            except (ProtocolError, UnicodeDecodeError) as exc:
                LOG.warning("Rejected Arduino packet: %s", exc)
                continue
            if event.kind == "HELLO":
                self.firmware = event.fields.get("firmware")
                self.device_capabilities = event.fields.get("capabilities", "").split(",") if event.fields.get("capabilities") else []
                self.publish_state(self.state, detail=self.state_detail)
                LOG.info("Arduino firmware=%s capabilities=%s", event.fields.get("firmware"), event.fields.get("capabilities"))
                continue
            actions: list[str] = []
            if event.kind == "JOY":
                actions = self.interpreter.joy(int(event.fields["x"]), int(event.fields["y"]), now)
            elif event.kind == "BUTTON":
                actions = self.interpreter.button(event.fields["state"], now)
            for action in actions:
                self.handle_action(action, event.sequence, event.fields, now)

    def handle_action(self, action: str, sequence: int | None, raw: dict[str, str], now: float) -> None:
        if action != "SELECT" and now - self.last_action_at < 0.12:
            return
        self.last_action_at = now
        event = {"version": 1, "source": "arduino-mega", "sequence": sequence, "action": action, "raw": raw}
        self.publisher.publish_event(INPUT_TOPIC, event)
        LOG.info("action=%s port=%s", action, self.port)
        if action in {"SELECT", "NAV_UP", "SCROLL_UP", "NAV_DOWN", "SCROLL_DOWN", "NAV_LEFT", "NAV_RIGHT"}:
            threading.Thread(target=self.perform_light_action, args=(action,), daemon=True).start()

    def perform_light_action(self, action: str) -> None:
        client = HomeAssistantClient(self.settings)
        try:
            if action == "SELECT":
                result = asyncio.run(client.perform_light_action("living-room-lights", "toggle", None))
            elif action in {"NAV_UP", "SCROLL_UP"}:
                result = asyncio.run(client.perform_light_action("living-room-lights", "brightness", 3))
            elif action in {"NAV_DOWN", "SCROLL_DOWN"}:
                result = asyncio.run(client.perform_light_action("living-room-lights", "brightness", -3))
            elif action == "NAV_LEFT":
                result = asyncio.run(client.perform_light_action("living-room-lights", "color_temperature", -150))
            else:
                result = asyncio.run(client.perform_light_action("living-room-lights", "color_temperature", 150))
            self.publisher.publish_event(ACTION_RESULT_TOPIC, {"action": action, "status": "completed", "result": result})
        except Exception as exc:
            LOG.warning("Home Assistant action %s failed: %s", action, exc)
            self.publisher.publish_event(ACTION_RESULT_TOPIC, {"action": action, "status": "failed", "detail": str(exc)})


def main() -> None:
    logging.basicConfig(level=os.environ.get("KIOSK_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    controller = KioskController()
    signal.signal(signal.SIGTERM, lambda *_: setattr(controller, "running", False))
    signal.signal(signal.SIGINT, lambda *_: setattr(controller, "running", False))
    controller.run()


if __name__ == "__main__":
    main()
