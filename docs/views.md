# View catalog

All production views are backed by `GET /api/v1/platform/overview`, which is
composed from durable Control Plane records plus Workspace Sync's approved
status contract. It refreshes every 15 seconds; a failed upstream is shown as
stale/unavailable without preventing the rest of the app from rendering.

| View | Purpose and layout | Devices | Real source / endpoint | Actions and permission boundary | Current status |
| --- | --- | --- | --- | --- | --- |
| Now | Deterministic priority queue, compact glance cards | All; `?display=ambient` is read-only | alerts, providers, automation runs, Workspace Sync; `/api/v1/platform/overview` | None | Working against the shared read model |
| Home | Home Assistant state/control and camera provider state | Phone, tablet, desktop, Pi display | providers/nodes; overview | Only the existing typed Home Assistant light action | Partial: camera snapshots/events need a registered authenticated proxy |
| Projects | Project Hub records and recent/current project | Phone, tablet, desktop | projects; overview | Read-only in this dashboard | Working when Project Hub has records; no invented scores/Next Work |
| Learn | Flashcard and Discovery landing states | All | None discovered | None | Blocked: Notion flashcard source and discovery feeds/scoring absent |
| Media | Camera transport and media-library capability state | Phone, tablet, desktop | camera provider; overview | None | Partial: no stream proxy; Audiobookshelf absent |
| AI | LM Studio provider/compute-node state and ComfyUI status | Phone, tablet, desktop | providers/nodes; overview | None | Partial: LM Studio health only; chat/models/ComfyUI workflow API absent |
| Files | Workspace/backup status boundary | Phone, tablet, desktop | Workspace Sync proxy; overview | None; detailed file/backup operations remain in Workspace Sync | Working for status; browse/restore intentionally remain in the owning service |
| Automations | Durable runs plus registry | Phone, tablet, desktop | runs/registry; overview | `POST /api/v1/automations/{id}/runs` only for registered Control Plane automations | Working |
| Data | Durable Project Resource records and generic-Notion state | Phone, tablet, desktop | resources; overview | None | Partial: Projects/Resources only; generic Notion browser/CRUD absent |
| System | Nodes, providers, services, attention queue | Tablet, desktop, Pi display; usable on phone | nodes/providers/alerts; overview | Existing typed provider health-check request only | Working |

## Device modes

- **Ambient/Waveshare:** `?display=ambient` removes navigation and controls,
  shows only Now/Glance with large, low-density content.
- **Phone:** bottom, touch-sized (44px) navigation and one-column cards.
- **Tablet:** two-column cards where available.
- **Desktop/Pi display:** sidebar, three-column operational glance.

Errors show a dismissible transport notice and retain empty/unavailable states.
No view silently replaces an unavailable integration with sample data.
