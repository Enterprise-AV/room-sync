"""CLI entrypoint for the Room Sync tool.

Usage:
    python -m sync.main                          # Full nightly sync
    python -m sync.main --dry-run                # Show what would change
    python -m sync.main --approve-mapping        # Apply approved mappings
    python -m sync.main --create-rooms           # Create rooms from pending
    python -m sync.main --decommission           # Decommission rooms from pending
    python -m sync.main --discover-building B143 # Print IDs for a building
"""

import json
import os
import sys

# Inject the Windows certificate store for corporate SSL proxy
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from . import reconciler
from .zoom_client import ZoomClient
from .neat_client import NeatClient
from .xyte_client import XyteClient


def _load_payload() -> list:
    """Load the action payload from the APPLY_PAYLOAD env var."""
    raw = os.environ.get("APPLY_PAYLOAD", "[]")
    return json.loads(raw)


def cmd_sync(dry_run=False):
    """Run the full nightly reconciliation."""
    print("=" * 60)
    print("  Room Sync — Nightly Reconciliation")
    print("=" * 60)
    if dry_run:
        print("  (dry-run mode — no changes will be written)\n")
    else:
        print()

    zoom = ZoomClient()
    neat = NeatClient()
    xyte = XyteClient()

    stats = reconciler.reconcile(zoom, neat, xyte, dry_run=dry_run)

    print()
    print("  Summary:")
    print(f"    Auto-renames:     {stats['auto_renames']}")
    print(f"    Discrepancies:    {stats['discrepancies']}")
    print(f"    New suggestions:  {stats['new_suggestions']}")
    print(f"    Unmapped (Zoom):  {stats['unmapped_zoom']}")
    print(f"    Unmapped (Neat):  {stats['unmapped_neat']}")
    print(f"    Unmapped (Xyte):  {stats['unmapped_xyte']}")
    print()


def cmd_approve_mapping():
    """Apply approved mapping suggestions from APPLY_PAYLOAD."""
    print("Applying approved mappings...")
    payload = _load_payload()
    if not payload:
        print("  No payload provided.")
        return

    zoom = ZoomClient()
    neat = NeatClient()
    xyte = XyteClient()

    count = reconciler.apply_mapping(payload, zoom, neat, xyte)
    print(f"  Mapped {count} room(s).")


def cmd_create_rooms():
    """Create rooms from APPLY_PAYLOAD."""
    print("Creating rooms...")
    payload = _load_payload()
    if not payload:
        print("  No payload provided.")
        return

    zoom = ZoomClient()
    neat = NeatClient()
    xyte = XyteClient()

    count = reconciler.create_rooms(payload, zoom, neat, xyte)
    print(f"  Created {count} room(s).")


def cmd_decommission():
    """Decommission rooms from APPLY_PAYLOAD."""
    print("Decommissioning rooms...")
    payload = _load_payload()
    if not payload:
        print("  No payload provided.")
        return

    zoom = ZoomClient()
    neat = NeatClient()
    xyte = XyteClient()

    count = reconciler.decommission_rooms(payload, zoom, neat, xyte)
    print(f"  Decommissioned {count} room(s).")


def cmd_discover_building(building_name: str):
    """Print platform IDs for a building, ready to paste into locations.json."""
    print(f"Discovering building '{building_name}' across all platforms...\n")

    # Zoom
    try:
        zoom = ZoomClient()
        matches = zoom.discover_locations(building_name)
        print("  Zoom Rooms locations:")
        if matches:
            ids = []
            for loc in matches:
                print(f"    - {loc.get('name', '?')}  (id: {loc['id']})")
                ids.append(loc["id"])
            print(f"    zoom_location_ids: {json.dumps(ids)}")
        else:
            print("    (none found)")
    except Exception as e:
        print(f"    Error: {e}")

    print()

    # Neat Pulse
    try:
        neat = NeatClient()
        loc = neat.discover_location(building_name)
        print("  Neat Pulse location:")
        if loc:
            print(f"    - {loc.get('name', '?')}  (id: {loc['id']})")
            print(f"    neat_location_id: \"{loc['id']}\"")
        else:
            print("    (none found)")
    except Exception as e:
        print(f"    Error: {e}")

    print()

    # Xyte
    try:
        xyte = XyteClient()
        space = xyte.discover_building(building_name)
        print("  Xyte (RackLink Cloud) building space:")
        if space:
            print(f"    - {space['name']}  (id: {space['id']}, path: {space['path']})")
            print(f"    xyte_building_space_id: \"{space['id']}\"")
        else:
            print("    (none found)")
    except Exception as e:
        print(f"    Error: {e}")

    print()
    print("  Add these IDs to config/locations.json to enable syncing.")


def main():
    args = sys.argv[1:]

    if not args:
        cmd_sync()
    elif args == ["--dry-run"]:
        cmd_sync(dry_run=True)
    elif args == ["--approve-mapping"]:
        cmd_approve_mapping()
    elif args == ["--create-rooms"]:
        cmd_create_rooms()
    elif args == ["--decommission"]:
        cmd_decommission()
    elif len(args) == 2 and args[0] == "--discover-building":
        cmd_discover_building(args[1])
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
