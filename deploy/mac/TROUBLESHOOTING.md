# Mac Node troubleshooting

Check `~/Library/Logs/homeplatform-node.log`, the Keychain item, Tailscale
connectivity, and the launchd job. A sleeping Mac should report offline through
LWT; the active Control Plane and unrelated Platform capabilities remain
available.
