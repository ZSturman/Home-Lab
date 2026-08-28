# Mac Node Service

The Mac Node Service reports Actual State and capabilities, accepts only
allowlisted Commands, and reads its MQTT password from macOS Keychain. It does
not own Desired State or Platform configuration.

Install through `deploy/mac/INSTALL.md`; do not run this service with a
plaintext MQTT password in a launchd plist.

Use MQTT port 1883. Set `HOMEPLATFORM_MQTT_HOST` to the active Control Plane's
Tailnet DNS name, or to `127.0.0.1` when this Mac hosts the portable Control
Plane, then confirm presence and an allowlisted test command.
