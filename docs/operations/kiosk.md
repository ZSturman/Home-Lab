# Kiosk and Arduino integration

`kiosk-controller` is the Platform-owned, exclusive serial owner of the
Arduino Mega at `/dev/ttyACM0`. It uses the retained KIOSK/1 firmware protocol
directly; there is no legacy MQTT broker, mirror mode, adapter, or keyboard
emulation in this path. It runs only in the Pi hardware profile, and uses the
configured host's `HOMEPLATFORM_NODE_ID` for its Node state.

The host’s stable identity is
`/dev/serial/by-id/usb-Arduino__www.arduino.cc__0042_557313235363515112D0-if00`.
Compose maps the resolved `/dev/ttyACM0` device into only this controller
container. If a future reconnect changes that mapping, update
`KIOSK_CONTROLLER_PORT` and the Compose device mapping together.

Mappings:

- Select: toggle `living-room-lights`.
- Up/Down: coalesced brightness +/-3% actions.
- Left: 150 K warmer; Right: 150 K cooler; values clamp to the Home Assistant
  entity’s reported range.

Solid green is the normal connected state when no alert is active. Red has
highest LED priority and is the Arduino's no-Platform-ping failsafe. Blue/yellow together means a Share has active
external viewers; therefore an ordinary running state is suppressed while a
Share is public. Yellow uses a 1.2-second digital pulse on pin 43. A future
move to a verified PWM pin is required for true breathing.

The native controller publishes validated input Events at
`homeplatform/v1/devices/kiosk/input`, action results at
`homeplatform/v1/devices/kiosk/action-result`, and retained node state for
`pi-control-plane`. It receives retained Alert LED state only. The Arduino
keeps its independent seven-second heartbeat failsafe: without a Platform ping,
it blinks red.
