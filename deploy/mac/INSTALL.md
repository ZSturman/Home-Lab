# Install the Mac Node Service

1. Copy `nodes/mac/` to `~/Library/Application Support/Home Platform/node/` and
   create a virtual environment under `~/Library/Application Support/Home Platform/venv`.
2. Install `requirements.txt` from that Node directory.
3. Add the MQTT password to Keychain:

   ```sh
   security add-generic-password -U -s 'Home Platform MQTT' -a macbook -w
   ```

4. Render `com.homeplatform.node.plist.template` by replacing the two
   `__HOME_PLATFORM...__` paths and `__HOME_PLATFORM_MQTT_HOST__`, save it as
   `~/Library/LaunchAgents/com.homeplatform.node.plist`, then run:

   ```sh
   launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.homeplatform.node.plist 2>/dev/null || true
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.homeplatform.node.plist
   ```

5. Set `HOMEPLATFORM_MQTT_HOST` to the Control Plane host's Tailnet DNS name
   (or `127.0.0.1` when the Mac itself hosts the Control Plane) and use port
   1883. Verify retained presence, LM Studio health, and a Dashboard test
   notification.

The LaunchAgent must use a Keychain item, not an MQTT password in its plist.

## Host the portable Control Plane on this Mac

Docker Desktop and Tailscale are required. Follow the generic Control Plane
[installation guide](../control-plane/INSTALL.md), set the host identity to
`macbook` in `.env`, and start the base Compose stack without the
`pi-hardware` profile. Add the generated `mqtt_macbook_password` to Keychain,
point this LaunchAgent at `127.0.0.1`, and use Tailscale Serve for the
loopback Dashboard. This replaces the remote broker path; it must not run as a
second active Control Plane with the same Node identity.
