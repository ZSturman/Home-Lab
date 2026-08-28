from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "control-plane"))

from devices.kiosk.motion import MotionInterpreter
from devices.kiosk.protocol import ProtocolError, led_frame, parse_line


class KioskProtocolTests(unittest.TestCase):
    def test_valid_joy_packet_is_parsed(self) -> None:
        event = parse_line("KIOSK/1 JOY seq=42 x=1023 y=512\n")
        self.assertEqual((event.kind, event.sequence, event.fields["x"]), ("JOY", 42, "1023"))

    def test_invalid_packets_are_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            parse_line("KIOSK/1 JOY seq=1 x=1024 y=512")
        with self.assertRaises(ProtocolError):
            parse_line("KIOSK/1 LED red=solid@500")

    def test_led_frames_include_every_firmware_led(self) -> None:
        frame = led_frame({
            "red": {"mode": "off", "intervalMs": 500},
            "blue": {"mode": "solid", "intervalMs": 500},
            "green": {"mode": "blink", "intervalMs": 700},
            "yellow": {"mode": "off", "intervalMs": 500},
        })
        self.assertEqual(
            frame,
            b"KIOSK/1 LED red=off@500 blue=solid@500 green=blink@700 yellow=off@500\n",
        )


class KioskMotionTests(unittest.TestCase):
    def test_joystick_and_button_actions(self) -> None:
        interpreter = MotionInterpreter()
        self.assertEqual(interpreter.joy(1023, 512, 1.0), ["NAV_RIGHT"])
        self.assertEqual(interpreter.joy(512, 512, 1.1), [])
        self.assertEqual(interpreter.button("down", 2.0), [])
        self.assertEqual(interpreter.button("up", 2.2), ["SELECT"])
        self.assertEqual(interpreter.button("down", 3.0), [])
        self.assertEqual(interpreter.button("up", 3.9), ["HOME"])


if __name__ == "__main__":
    unittest.main()
