# Private webcam streaming

The Logitech Brio 101 is managed by the `go2rtc` service in the Home Platform
Compose project. It receives the host's stable by-id camera device as
`/dev/video0`, captures the camera's native MJPEG at 1280×720/30fps, and
transcodes it to H.264 for RTSP and WebRTC consumers.

The service ports (1984, 8554, and 8555 TCP/UDP) bind only to the Pi Tailscale
address. They are never published through Tailscale Serve or Cloudflare. The
private snapshot endpoint is:

```text
http://100.90.61.70:1984/api/frame.jpeg?src=brio
```

Check service and stream health from the Pi:

```sh
docker compose ps go2rtc
curl --fail http://100.90.61.70:1984/api/frame.jpeg?src=brio -o /tmp/brio.jpeg
```

`media-controller` polls go2rtc on the internal Compose network and reports
the `brio-webcam` Platform Service as `healthy`, `degraded`, or `offline` over
authenticated MQTT. A reported `healthy` state means the named stream has at
least one active producer; it never makes camera content public.

If the USB device is re-enumerated, verify the host by-id path in
`/dev/v4l/by-id/` before changing the Compose device mapping. Do not fall back
to a broad `/dev` mount.
