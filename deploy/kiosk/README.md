# Install the native kiosk controller

The `kiosk-controller` Compose service owns the Arduino Mega directly. Confirm
the host resolves the known Arduino USB identity to `/dev/ttyACM0`, then start
the service using the `pi-hardware` Compose profile. It requires no legacy
broker credential or compatibility profile, and does not start on a standard
Mac Control Plane host.
