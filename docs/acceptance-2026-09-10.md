# Home Platform vNext acceptance report — 2026-09-10

## Delivered

- Shared Control Plane overview API with deterministic, explainable Attention
  prioritization across alerts, providers, automation runs, and Workspace
  backup state.
- Production real-data navigation: Now, Home, Projects, Learn, Media, AI,
  Files, Automations, Data, and System.
- Compact read-only ambient mode (`?display=ambient`) for small displays.
- Responsive touch navigation, tablet grids, desktop sidebar, provider health
  checks, typed Home Assistant controls, and registered automation controls.
- View, integration, design, discovery, testing, and future-work catalogs.

## Deployed services and validation

`control-plane-api` and `dashboard` were rebuilt on `kiosk-lab`; both are up.
Tailscale Serve now privately proxies the live root to `127.0.0.1:3000`.
Live overview returned 100 real projects, three provider reports (LM Studio
healthy, Brio healthy, ComfyUI offline), a completed backup, and the live
attention queue. Workspace Sync remained healthy on port 8787.

## Limitations

No generic Notion CRUD, flashcards, Discovery feeds, Audiobookshelf, Tapo
energy history, LM Studio chat/model controls, ComfyUI workflows, camera media
proxy, public sharing, or browser role model was discovered/configured. Each is
shown honestly as unavailable/partial; required next steps are in
`docs/integrations.md` and `docs/future-work.md`.
