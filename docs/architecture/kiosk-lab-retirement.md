# Kiosk Lab retirement boundary

Kiosk Lab is a retired source system. Its Arduino controller, physical display
and browser runtime, Pi display helper, and all Kiosk-originated Notion access
are not Home Platform migration targets.

Home Platform must not install, configure, or start a Kiosk controller. The
currently active browser/display service is retained temporarily because its
unit was installed on 2026-09-09 and started on 2026-09-10; it is not a Kiosk
Lab migration target. This decision does not remove unrelated Home Platform
hardware such as the webcam or media services.

The legacy local data under `~/Library/Application Support/KioskTelemetry/` is
preserved while Workspace Watcher takes over local telemetry and session data.
Consumers must use their own configuration for Notion and must not import
credentials or database identifiers from Kiosk Lab.

The current remote kiosk browser service and `/usr/local/bin/kiosk-display`
helper are live deployment artifacts. They are intentionally not changed by
this repository update; remove them only through a separately approved remote
decommissioning action after the recently installed display use is confirmed
unneeded.
