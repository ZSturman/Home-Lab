# Testing and validation

## Automated checks run

```bash
./.venv/bin/python -m pytest tests/control_plane -q
# 56 passed

cd dashboard && npm run typecheck
# passed

cd dashboard && npm run build
# passed

./.venv/bin/python scripts/validate_config.py
# Configuration valid
```

`test_platform_overview.py` verifies that the shared overview produces an
explainable priority order from a critical alert, provider outage, failed
automation, and failed backup state.

## Local browser exercise

The built dashboard was opened locally and all ten primary navigation views
were selected. Browser viewport checks covered 320×240 ambient, 390×844
phone, 834×1194 tablet, and 1280×800 desktop. `?display=ambient` remained
read-only at the small-display size; phone navigation changed to touch-sized
bottom navigation; desktop restored the sidebar. The local build had no
configured Control Plane proxy, so it correctly displayed a transport error
and honest empty states rather than sample data.

## Device matrix

| View class | Ambient/small | Phone ≤850px | Tablet 851–1100px | Desktop |
| --- | --- | --- | --- | --- |
| Now/Glance | Implemented | Implemented | Implemented | Implemented |
| Home, Projects, Learn, Media, AI, Files, Automations, Data, System | Intentionally Now-only | CSS responsive navigation/cards | CSS responsive grids | Sidebar/grids |

## Live deployment validation

The Pi was reached as `kiosk@kiosk-lab`. The updated `control-plane-api` and
`dashboard` containers were rebuilt and recreated; `GET
http://127.0.0.1:3000/api/v1/platform/overview` returned real records (10
attention items, 100 projects, 3 providers, completed backup). Tailscale
Serve was changed from the stale Workspace Sync root proxy to the documented
private `127.0.0.1:3000` target, and the live HTTPS API returned the same
overview. Workspace Sync `:8787/api/health` remained healthy.

The deployed URL was opened and every primary navigation view was selected.
The live 320×240 ambient view showed the actual date/time, top attention item,
backup, current project, camera, and Pi state. Phone/tablet/desktop breakpoints
were exercised locally; a physical Pi-panel visual check is still recommended.
