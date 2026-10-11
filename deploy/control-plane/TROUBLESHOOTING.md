# Troubleshooting

```sh
docker compose ps
docker compose logs --tail=120 control-plane-core control-plane-api automation-controller
docker compose exec postgres pg_isready -U homeplatform -d homeplatform
docker compose exec mosquitto mosquitto_sub -h localhost -t '$SYS/broker/uptime' -C 1
tailscale serve status
```

- A Node shown offline means the retained presence LWT was received; inspect the
  Node Service, credential, and Tailscale path.
- A Dashboard outage must not stop Automation Controller or Control Plane Core.
- An unavailable Home Assistant token affects only lights and Home Assistant
  Devices; it must not block MQTT, Nodes, or Automations.
