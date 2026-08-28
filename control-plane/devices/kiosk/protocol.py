"""Validated KIOSK/1 framing used by the retained Arduino Mega firmware."""

from __future__ import annotations

from dataclasses import dataclass


VERSION = "KIOSK/1"


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class SerialEvent:
    kind: str
    sequence: int | None
    fields: dict[str, str]


def parse_line(raw: str | bytes) -> SerialEvent:
    if isinstance(raw, bytes):
        raw = raw.decode("ascii", errors="strict")
    values = raw.strip().split()
    if len(values) < 2 or values[0] != VERSION:
        raise ProtocolError("Expected KIOSK/1 packet")
    kind = values[1].upper()
    if kind not in {"HELLO", "JOY", "BUTTON"}:
        raise ProtocolError(f"Unsupported event {kind}")
    fields: dict[str, str] = {}
    for token in values[2:]:
        if token.count("=") != 1:
            raise ProtocolError("Malformed field")
        key, value = token.split("=", 1)
        if not key or not value or key in fields:
            raise ProtocolError("Duplicate or empty field")
        fields[key] = value
    allowed = {
        "HELLO": {"firmware", "device", "capabilities"},
        "JOY": {"seq", "x", "y"},
        "BUTTON": {"seq", "id", "state"},
    }[kind]
    required = {
        "HELLO": {"firmware"},
        "JOY": {"seq", "x", "y"},
        "BUTTON": {"seq", "id", "state"},
    }[kind]
    if set(fields) - allowed or not required <= set(fields):
        raise ProtocolError(f"Invalid {kind} fields")
    if kind == "JOY":
        for key in ("seq", "x", "y"):
            if not fields[key].isdigit():
                raise ProtocolError(f"{key} is not numeric")
        if not (0 <= int(fields["x"]) <= 1023 and 0 <= int(fields["y"]) <= 1023):
            raise ProtocolError("Joystick axis outside 0..1023")
    if kind == "BUTTON" and (fields["id"] != "joy" or fields["state"] not in {"down", "up"}):
        raise ProtocolError("Unsupported button")
    return SerialEvent(kind, int(fields["seq"]) if "seq" in fields else None, fields)


def led_frame(frame: dict[str, dict[str, int | str]]) -> bytes:
    parts: list[str] = []
    for color in ("red", "blue", "green", "yellow"):
        value = frame.get(color)
        if not isinstance(value, dict):
            raise ProtocolError(f"Missing LED {color}")
        mode, interval = str(value.get("mode")), int(value.get("intervalMs", 500))
        if mode not in {"off", "solid", "blink"} or not 100 <= interval <= 5000:
            raise ProtocolError(f"Invalid LED {color}")
        parts.append(f"{color}={mode}@{interval}")
    return f"{VERSION} LED {' '.join(parts)}\n".encode("ascii")
