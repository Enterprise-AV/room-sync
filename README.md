# Room Sync

Unified AV room naming platform that keeps room names synchronized across
**Zoom Rooms**, **Neat Pulse**, and **Xyte (RackLink Cloud)**.

## How It Works

1. **Nightly sync** (GitHub Actions, 2 AM PT): Fetches all rooms from each
   platform, detects Zoom renames, auto-renames in Neat/Xyte, and generates
   mapping suggestions for unmapped rooms.

2. **Web UI** (GitHub Pages): Dashboard shows discrepancies, suggestions,
   and the change log. Team members sign in with GitHub to approve mappings,
   create new rooms, or decommission existing ones.

3. **Source of truth**: Zoom Rooms. When a room is renamed in Zoom, the
   change propagates to all other platforms automatically.

## Quick Start

### 1. Set GitHub Secrets

On the `Enterprise-AV/room-sync` repo, set these secrets:

| Secret | Value |
|---|---|
| `ZOOM_ACCOUNT_ID` | Zoom S2S OAuth account ID |
| `ZOOM_CLIENT_ID` | Zoom S2S OAuth client ID |
| `ZOOM_CLIENT_SECRET` | Zoom S2S OAuth client secret |
| `NEAT_API_KEY` | Neat Pulse API bearer token |
| `NEAT_ORG_ID` | Neat Pulse org ID |
| `XYTE_API_KEY` | Xyte API key |
| `XYTE_ORG_ID` | Xyte org ID |

### 2. Configure Building Scope

Edit `config/locations.json` with the IDs for your building:

```json
{
  "locations": [
    {
      "name": "B105",
      "zoom_location_ids": ["abc123"],
      "neat_location_id": "456",
      "xyte_building_space_id": "789"
    }
  ]
}
```

Use the discovery helper to find IDs:

```bash
python -m sync.main --discover-building B105
```

### 3. Run the First Sync

Trigger the nightly-sync workflow manually from the Actions tab, or run
locally:

```bash
pip install -r requirements.txt
python -m sync.main --dry-run
```

### 4. Set Up the Web UI

1. Create a GitHub OAuth App (Settings > Developer > OAuth Apps)
2. Deploy the Cloudflare Worker (`worker/oauth-proxy.js`)
3. Update `OAUTH_CLIENT_ID` and `OAUTH_WORKER_URL` in `docs/auth.js`
4. Enable GitHub Pages on the repo (source: GitHub Actions)

## Expanding to More Buildings

Add entries to `config/locations.json`:

```json
{
  "locations": [
    { "name": "B105", "zoom_location_ids": ["..."], ... },
    { "name": "B143", "zoom_location_ids": ["..."], ... }
  ]
}
```

Commit and push. The next nightly sync picks up the new building
automatically. No code changes needed.

To sync all buildings: set `"all": true` in `locations.json`.

## Project Structure

```
sync/               Python sync engine
  zoom_client.py    Zoom Rooms API
  neat_client.py    Neat Pulse API
  xyte_client.py    Xyte (RackLink Cloud) API
  matcher.py        Fuzzy name matching
  reconciler.py     Core sync logic
  mapping.py        Data file I/O
  main.py           CLI entrypoint

docs/               GitHub Pages UI
  index.html        Dashboard
  create.html       Room creation matrix
  decommission.html Decommission with confirmation
  app.js            Main application logic
  auth.js           GitHub OAuth flow
  style.css         Intuitive-inspired theme

data/               Committed data files
  mapping.json      Room-to-room ID mapping
  pending.json      Discrepancies & suggestions
  changelog.json    Change log
  snapshots/        Nightly platform snapshots

config/
  locations.json    Building scope (B105 initially)

worker/
  oauth-proxy.js    Cloudflare Worker for OAuth
```
