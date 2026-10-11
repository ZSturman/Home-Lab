# Integration catalog

| Integration | Host/interface | Status | Failure behavior and setup requirement |
| --- | --- | --- | --- |
| Control Plane/Postgres/Mosquitto | Pi Compose network | Working | Dashboard reads FastAPI only; database/MQTT remain private |
| Tailscale Serve | Pi HTTPS ingress | Working | Verified after deployment: root proxies privately to `127.0.0.1:3000`; Workspace Sync remains on port 8787 |
| Workspace Sync | Pi :8787 authenticated status contract | Working interface | Overview degrades storage/backup only; file/restore administration remains there |
| Mac node | MQTT + HTTP polling | Working interface | Node/provider state becomes unavailable when heartbeat stops |
| Notion Projects/Resources | Control Plane API | Partial | Requires existing token and configured database IDs; generic source inspection/CRUD is not implemented |
| Home Assistant | typed Control Plane client | Configured extension | Light actions are typed and server-side; health depends on provider report/token |
| go2rtc/Brio camera | Pi hardware profile | Partial | Provider health can appear; authenticated snapshot/event proxy is required before media UI |
| LM Studio | Mac provider `lmstudio` | Partial | Health capability exists; model list/chat requires a registered Mac-node API |
| ComfyUI | Mac | Not configured | Add curated workflow/provider API before any controls or jobs are shown |
| Audiobookshelf | Pi/Mac | Not configured | Install and register a media provider; no library is faked |
| Tapo P110M | Pi/Mac | Not configured | Register a measured feed with timestamps before Energy UI/charts are enabled |
| Flashcards/Discovery | Notion/feed services | Not configured | Add a source, scheduler/scoring model, and credentials; no recommendations are fabricated |

Secrets remain outside Git in Docker secrets, environment configuration, or
Mac Keychain. The browser never receives tokens, filesystem roots, or direct
MQTT credentials.
