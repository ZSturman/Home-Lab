# Home Platform vNext design plan

## Information architecture

The production navigation is: **Now, Home, Projects, Learn, Media, AI,
Files, Automations, Data, System**. Navigation is an application state, not
a collection of unrelated dashboards. Each view consumes the same Control
Plane overview and then a small number of purpose-built APIs.

## Shared state and priority

`GET /api/v1/platform/overview` will combine durable Control Plane state
(alerts, automation runs, nodes, service providers, projects, resources) and
the existing best-effort Workspace Sync status. It computes a deterministic
Attention queue: critical/error alerts, offline or degraded providers,
failed automation runs, Workspace backup/storage warnings, then project work.
Each item includes a reason and source. No LLM participates in prioritization.

## Device behavior

| Device class | Navigation and layout |
| --- | --- |
| Small display | `?display=ambient`; read-only Now/Glance rotation, large type, no scroll-dependent controls |
| Pi display | wide ambient Home/Now layout, with read-only state by default |
| Phone | fixed bottom navigation for the primary areas, one-column cards, touch targets ≥44px |
| Tablet | persistent compact sidebar and two-column detail panels |
| Desktop | sidebar, advanced System/Data administration, dense lists only where useful |

The client chooses layout from viewport capability, while actions are only
rendered for controls backed by existing safe server endpoints. The server
continues to enforce safe operation boundaries: only registered automations,
allowlisted node commands, and defined Home Assistant actions are accepted.

## Delivery order

1. Add the overview/Attention API with tests.
2. Replace the simulated dashboard with the responsive real-data shell.
3. Surface existing Projects, Automations, Workspace, providers, nodes, and
   alerts in their appropriate views.
4. Mark unavailable integrations honestly, with configuration requirements.
5. Build/type-check and run Control Plane tests.
6. Deploy incrementally after the Pi route and SSH access are verified; test
   the actual Serve URL at small-display, phone, tablet, Pi-display, and
   desktop widths.

## Explicit non-goals for this migration

No public file sharing tunnel, arbitrary shell execution, simulated media
catalogue, fake power history, or invented Notion/LM Studio/ComfyUI data will
be added. Those integrations need credentials and registered providers first.
