# Kiosk troubleshooting

If LED or joystick behavior is wrong, inspect `kiosk-controller` first:

```sh
docker compose logs -f kiosk-controller
ls -l /dev/serial/by-id/*Arduino*
```

The service is the only serial owner. A red blink means the Arduino has not
received a valid Platform ping within seven seconds; check the service and USB
device before reflashing firmware.
