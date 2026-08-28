# Update the Mac Node Service

Stop the LaunchAgent, update source and Python dependencies, then bootstrap the
same plist. Confirm `launchctl print gui/$(id -u)/com.homeplatform.node`, Mac
presence, and a test notification before considering the update complete.
