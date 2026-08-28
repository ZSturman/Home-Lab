"""Convert KIOSK/1 joystick samples into platform input actions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Calibration:
    center_x: int = 512
    center_y: int = 512
    min_x: int = 0
    max_x: int = 1023
    min_y: int = 0
    max_y: int = 1023
    dead_zone: float = 0.12
    invert_x: bool = False
    invert_y: bool = False
    initial_repeat_ms: int = 300
    minimum_repeat_ms: int = 75
    acceleration_ms: int = 1200
    long_press_ms: int = 800
    scroll_hold_ms: int = 650


class MotionInterpreter:
    def __init__(self, calibration: Calibration = Calibration()) -> None:
        self.calibration = calibration
        self.direction: str | None = None
        self.direction_started = 0.0
        self.next_repeat = 0.0
        self.button_down: float | None = None

    def joy(self, x: int, y: int, now: float) -> list[str]:
        direction = self._direction(x, y)
        if direction is None:
            self.direction = None
            return []
        if direction != self.direction:
            self.direction, self.direction_started = direction, now
            self.next_repeat = now + self.calibration.initial_repeat_ms / 1000
            return [self._action_for(direction, now)]
        if now < self.next_repeat:
            return []
        elapsed = (now - self.direction_started) * 1000
        progress = min(1.0, elapsed / self.calibration.acceleration_ms)
        interval = self.calibration.initial_repeat_ms + (
            self.calibration.minimum_repeat_ms - self.calibration.initial_repeat_ms
        ) * progress
        self.next_repeat = now + max(interval, 50) / 1000
        return [self._action_for(direction, now)]

    def button(self, state: str, now: float) -> list[str]:
        if state == "down":
            if self.button_down is None:
                self.button_down = now
            return []
        if self.button_down is None:
            return []
        duration = (now - self.button_down) * 1000
        self.button_down = None
        return ["HOME" if duration >= self.calibration.long_press_ms else "SELECT"]

    def _action_for(self, direction: str, now: float) -> str:
        held = (now - self.direction_started) * 1000
        if direction in {"up", "down"} and held >= self.calibration.scroll_hold_ms:
            return "SCROLL_UP" if direction == "up" else "SCROLL_DOWN"
        return f"NAV_{direction.upper()}"

    def _direction(self, x: int, y: int) -> str | None:
        horizontal = self._axis(x, self.calibration.center_x, self.calibration.min_x, self.calibration.max_x)
        vertical = self._axis(y, self.calibration.center_y, self.calibration.min_y, self.calibration.max_y)
        if self.calibration.invert_x:
            horizontal *= -1
        if self.calibration.invert_y:
            vertical *= -1
        if max(abs(horizontal), abs(vertical)) < self.calibration.dead_zone:
            return None
        if abs(horizontal) >= abs(vertical):
            return "right" if horizontal > 0 else "left"
        return "down" if vertical > 0 else "up"

    @staticmethod
    def _axis(value: int, center: int, minimum: int, maximum: int) -> float:
        span = maximum - center if value >= center else center - minimum
        return 0 if span <= 0 else max(-1.0, min(1.0, (value - center) / span))
