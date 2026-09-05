# Room Sync — Agent Notes

## Project Overview

Room Sync is a unified AV room naming platform that keeps room names
synchronized across Zoom Rooms, Neat Pulse, and Xyte (RackLink Cloud).
Zoom is the source of truth — when a room is renamed in Zoom, the change
propagates automatically to Neat Pulse and Xyte.

## Key Architecture

- **Sync engine** (`sync/`): Python package that fetches rooms from all
  platforms, detects renames, generates mapping suggestions, and applies
  changes. All API credentials are read from `os.environ` (GitHub Actions
  secrets at runtime).
- **GitHub Actions workflows** (`.github/workflows/`): Nightly sync runs
  at 2 AM PT. Apply-changes workflow is triggered by the web UI via
  `workflow_dispatch`. Deploy-pages workflow publishes the static site.
- **GitHub Pages UI** (`docs/`): Vanilla HTML/JS/CSS. Dashboard shows
  discrepancies, suggestions, and changelog. Create and decommission
  pages dispatch workflows via GitHub API.
- **Data files** (`data/`): JSON files committed to the repo. `mapping.json`
  stores the room-to-room ID mapping. `pending.json` stores discrepancies
  and suggestions. `changelog.json` stores the change log.
- **Config** (`config/locations.json`): Controls which buildings are synced.
  Start with B105, add more buildings by adding entries.
- **OAuth** (`worker/oauth-proxy.js`): Cloudflare Worker exchanges GitHub
  OAuth codes for tokens. Client secret stays server-side.

## Build / Run Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run nightly sync (requires env vars)
python -m sync.main

# Dry-run (show what would change without writing)
python -m sync.main --dry-run

# Apply approved mappings
APPLY_PAYLOAD='[{"zoom_id":"...","neat_id":"..."}]' python -m sync.main --approve-mapping

# Create rooms
APPLY_PAYLOAD='[{"name":"...","platforms":["neat","xyte"]}]' python -m sync.main --create-rooms

# Decommission rooms
APPLY_PAYLOAD='[{"uid":"...","confirmation_name":"..."}]' python -m sync.main --decommission

# Discover building IDs across all platforms
python -m sync.main --discover-building B143
```

## Required Environment Variables

| Variable | Description |
|---|---|
| `ZOOM_ACCOUNT_ID` | Zoom S2S OAuth account ID |
| `ZOOM_CLIENT_ID` | Zoom S2S OAuth client ID |
| `ZOOM_CLIENT_SECRET` | Zoom S2S OAuth client secret |
| `NEAT_API_KEY` | Neat Pulse API bearer token |
| `NEAT_ORG_ID` | Neat Pulse organization ID |
| `XYTE_API_KEY` | Xyte (RackLink Cloud) API key |
| `XYTE_ORG_ID` | Xyte organization ID |
| `APPLY_PAYLOAD` | JSON payload for apply-changes commands |

## Important Patterns

### Credentials
- **NEVER** hardcode API keys, tokens, or passwords in source code.
- All credentials are GitHub Actions secrets injected as env vars at runtime.
- The Cloudflare Worker secrets are set via `wrangler secret put`.
- No base64-encoded constants — read plaintext from `os.environ`.

### Location scoping
- `config/locations.json` controls which buildings are synced.
- Each platform client accepts a location filter parameter.
- Set `"all": true` to sync all buildings (no filtering).

### Decommissioning
- **Zoom**: `DELETE /v2/rooms/{id}`
- **Neat Pulse**: `DELETE /v1/orgs/{org}/rooms/{id}` — devices become unassigned
- **Xyte**: Move devices to Unsorted → delete space → cascade cleanup empty parents

### Corporate SSL proxy
Uses `truststore` for corporate SSL inspection — same pattern as all other
Enterprise-AV scripts.

## Dependencies

- `requests` — HTTP calls
- `truststore` — Windows cert store injection for corporate proxy
- `difflib` (stdlib) — Fuzzy name matching
