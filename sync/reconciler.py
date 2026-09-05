"""Core reconciliation logic.

Compares rooms across Zoom, Neat Pulse, and Xyte, detects renames,
flags discrepancies, and suggests mappings for unmapped rooms.
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import mapping as mp
from .matcher import find_suggestions
from .zoom_client import ZoomClient
from .neat_client import NeatClient
from .xyte_client import XyteClient

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _today():
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def load_locations_config() -> dict:
    path = os.path.join(CONFIG_DIR, "locations.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_snapshot(platform: str, data):
    """Write a nightly snapshot file."""
    snap_dir = os.path.join(DATA_DIR, "snapshots")
    os.makedirs(snap_dir, exist_ok=True)
    path = os.path.join(snap_dir, f"{platform}_{_today()}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


# -- Fetch rooms from all platforms --------------------------------------

def fetch_all(config: dict, zoom: ZoomClient, neat: NeatClient, xyte: XyteClient):
    """Fetch rooms from all three platforms, scoped by *config*.

    Returns ``(zoom_rooms, neat_rooms, xyte_spaces)`` where each is a
    list of dicts.
    """
    sync_all = config.get("all", False)
    locations = config.get("locations", [])

    zoom_loc_ids = None
    neat_loc_id = None
    xyte_building_ids = []

    if not sync_all and locations:
        zoom_loc_ids = []
        for loc in locations:
            zoom_loc_ids.extend(loc.get("zoom_location_ids", []))
        # Use first location's neat ID (multi-building handled by iterating)
        neat_loc_id = locations[0].get("neat_location_id")
        xyte_building_ids = [loc.get("xyte_building_space_id") for loc in locations
                             if loc.get("xyte_building_space_id")]

    # Fetch in parallel
    with ThreadPoolExecutor(max_workers=3) as ex:
        zoom_future = ex.submit(zoom.list_rooms, zoom_loc_ids)
        neat_future = ex.submit(neat.list_rooms, neat_loc_id)

        def _get_xyte_spaces():
            spaces = []
            if sync_all or not xyte_building_ids:
                for sid, path, item in xyte.walk_spaces(xyte.org_id):
                    item["_path"] = path
                    spaces.append(item)
            else:
                for bid in xyte_building_ids:
                    for sid, path, item in xyte.walk_spaces(bid):
                        item["_path"] = path
                        spaces.append(item)
            return spaces

        xyte_future = ex.submit(_get_xyte_spaces)

        zoom_rooms = zoom_future.result()
        neat_rooms = neat_future.result()
        xyte_spaces = xyte_future.result()

    # Save snapshots
    _save_snapshot("zoom", zoom_rooms)
    _save_snapshot("neat", neat_rooms)
    _save_snapshot("xyte", xyte_spaces)

    return zoom_rooms, neat_rooms, xyte_spaces


# -- Reconcile ----------------------------------------------------------

def reconcile(zoom: ZoomClient, neat: NeatClient, xyte: XyteClient,
              *, dry_run=False):
    """Run a full reconciliation cycle.

    1. Fetch rooms from all platforms (scoped by locations.json).
    2. For mapped rooms: detect Zoom renames → auto-rename in Neat/Xyte.
    3. For unmapped rooms: suggest matches.
    4. Write updated data files.

    Returns a summary dict.
    """
    config = load_locations_config()
    zoom_rooms, neat_rooms, xyte_spaces = fetch_all(config, zoom, neat, xyte)

    data = mp.load_mapping()
    changelog = mp.load_changelog()
    pending = mp.load_pending()

    # Build lookup indexes
    zoom_by_id = {r["id"]: r for r in zoom_rooms}
    neat_by_id = {r["id"]: r for r in neat_rooms}
    xyte_by_id = {s["id"]: s for s in xyte_spaces}

    stats = {"auto_renames": 0, "discrepancies": 0, "new_suggestions": 0,
             "unmapped_zoom": 0, "unmapped_neat": 0, "unmapped_xyte": 0}

    # -- Check mapped rooms -----------------------------------------------

    stale_uids = []
    for uid, room in list(data["rooms"].items()):
        zoom_id = room.get("zoom_room_id")
        neat_id = room.get("neat_room_id")
        xyte_id = room.get("xyte_space_id")
        canonical = room["canonical_name"]

        zoom_room = zoom_by_id.get(zoom_id) if zoom_id else None
        neat_room = neat_by_id.get(neat_id) if neat_id else None
        xyte_space = xyte_by_id.get(xyte_id) if xyte_id else None

        # Detect Zoom rename (Zoom is source of truth)
        if zoom_room:
            current_zoom_name = zoom_room.get("name", "").strip()
            if current_zoom_name and current_zoom_name != canonical:
                old_name = canonical
                room["canonical_name"] = current_zoom_name
                print(f"  [auto-rename] '{old_name}' → '{current_zoom_name}'")

                if not dry_run:
                    # Rename in Neat Pulse
                    if neat_id and neat_room:
                        try:
                            neat.rename_room(neat_id, current_zoom_name)
                            print(f"    Neat Pulse: renamed")
                        except Exception as e:
                            print(f"    Neat Pulse: rename failed: {e}")

                    # Rename in Xyte
                    if xyte_id and xyte_space:
                        try:
                            xyte.rename_space(xyte_id, current_zoom_name)
                            print(f"    Xyte: space renamed")
                        except Exception as e:
                            print(f"    Xyte: space rename failed: {e}")

                mp.log_change(changelog, action="auto_rename",
                              room_name=current_zoom_name, uid=uid,
                              details=f"Zoom renamed from '{old_name}' to '{current_zoom_name}'")
                stats["auto_renames"] += 1

            room["last_verified"] = _now_iso()

        # Detect name mismatches (someone renamed in Neat/Xyte directly)
        if neat_room and neat_room.get("name", "").strip() != room["canonical_name"]:
            if neat_room.get("name", "").strip():
                pending["discrepancies"].append({
                    "uid": uid,
                    "canonical_name": room["canonical_name"],
                    "platform": "neat",
                    "platform_name": neat_room["name"].strip(),
                    "platform_id": neat_id,
                    "detected": _now_iso(),
                })
                stats["discrepancies"] += 1

        if xyte_space and xyte_space.get("name", "").strip() != room["canonical_name"]:
            # Only flag leaf spaces that look like room names
            pending["discrepancies"].append({
                "uid": uid,
                "canonical_name": room["canonical_name"],
                "platform": "xyte",
                "platform_name": xyte_space["name"].strip(),
                "platform_id": xyte_id,
                "detected": _now_iso(),
            })
            stats["discrepancies"] += 1

        # Detect deleted rooms
        if zoom_id and zoom_id not in zoom_by_id:
            stale_uids.append((uid, "zoom"))
        if neat_id and neat_id not in neat_by_id:
            stale_uids.append((uid, "neat"))
        if xyte_id and xyte_id not in xyte_by_id:
            stale_uids.append((uid, "xyte"))

    # -- Find unmapped rooms -----------------------------------------------

    mapped_zoom_ids = {r["zoom_room_id"] for r in data["rooms"].values() if r.get("zoom_room_id")}
    mapped_neat_ids = {r["neat_room_id"] for r in data["rooms"].values() if r.get("neat_room_id")}
    mapped_xyte_ids = {r["xyte_space_id"] for r in data["rooms"].values() if r.get("xyte_space_id")}

    unmapped_zoom = [r for r in zoom_rooms if r["id"] not in mapped_zoom_ids]
    unmapped_neat = [r for r in neat_rooms if r["id"] not in mapped_neat_ids]
    # Only consider leaf Xyte spaces (rooms), not building/floor containers
    unmapped_xyte = [s for s in xyte_spaces
                     if s["id"] not in mapped_xyte_ids
                     and s.get("_path", "").count("/") >= 2]

    data["unmapped_zoom"] = [{"id": r["id"], "name": r.get("name", "")} for r in unmapped_zoom]
    data["unmapped_neat"] = [{"id": r["id"], "name": r.get("name", "")} for r in unmapped_neat]
    data["unmapped_xyte"] = [{"id": s["id"], "name": s.get("name", "")} for s in unmapped_xyte]

    stats["unmapped_zoom"] = len(unmapped_zoom)
    stats["unmapped_neat"] = len(unmapped_neat)
    stats["unmapped_xyte"] = len(unmapped_xyte)

    # -- Generate suggestions -----------------------------------------------

    # Zoom→Neat suggestions
    zn_suggestions = find_suggestions(unmapped_zoom, unmapped_neat)
    for s in zn_suggestions:
        pending["suggestions"].append({
            "source_platform": "zoom",
            "source_id": s["source"]["id"],
            "source_name": s["source"].get("name", ""),
            "matches": [
                {"platform": "neat", "id": m["target"]["id"],
                 "name": m["target"].get("name", ""), "score": m["score"]}
                for m in s["suggestions"]
            ],
            "detected": _now_iso(),
        })
        stats["new_suggestions"] += 1

    # Zoom→Xyte suggestions
    zx_suggestions = find_suggestions(unmapped_zoom, unmapped_xyte)
    for s in zx_suggestions:
        pending["suggestions"].append({
            "source_platform": "zoom",
            "source_id": s["source"]["id"],
            "source_name": s["source"].get("name", ""),
            "matches": [
                {"platform": "xyte", "id": m["target"]["id"],
                 "name": m["target"].get("name", ""), "score": m["score"]}
                for m in s["suggestions"]
            ],
            "detected": _now_iso(),
        })
        stats["new_suggestions"] += 1

    # -- Save ---------------------------------------------------------------

    if not dry_run:
        mp.save_mapping(data)
        mp.save_pending(pending)
        mp.save_changelog(changelog)

    return stats


# -- Apply approved changes -----------------------------------------------

def apply_mapping(payload: list, zoom: ZoomClient, neat: NeatClient, xyte: XyteClient):
    """Accept approved mapping suggestions.

    *payload* is a list of dicts: ``{"zoom_id", "neat_id", "xyte_space_id"}``.
    """
    data = mp.load_mapping()
    changelog = mp.load_changelog()

    for entry in payload:
        zoom_id = entry.get("zoom_id")
        neat_id = entry.get("neat_id")
        xyte_id = entry.get("xyte_space_id")

        # Resolve canonical name from Zoom
        canonical = ""
        if zoom_id:
            try:
                zr = zoom.get_room(zoom_id)
                canonical = zr.get("basic", {}).get("name", zr.get("name", "")).strip()
            except Exception:
                canonical = entry.get("name", "")
        if not canonical:
            canonical = entry.get("name", "unknown")

        uid = mp.add_room(
            data,
            canonical_name=canonical,
            location=entry.get("location", ""),
            zoom_room_id=zoom_id,
            neat_room_id=neat_id,
            xyte_space_id=xyte_id,
        )
        mp.log_change(changelog, action="mapping_approved",
                      room_name=canonical, uid=uid,
                      details=f"Mapped: zoom={zoom_id}, neat={neat_id}, xyte={xyte_id}")

    mp.save_mapping(data)
    mp.save_changelog(changelog)
    return len(payload)


def create_rooms(payload: list, zoom: ZoomClient, neat: NeatClient, xyte: XyteClient):
    """Create rooms on specified platforms.

    *payload* is a list of dicts:
    ``{"name", "location", "platforms": ["zoom","neat","xyte"], ...}``
    """
    data = mp.load_mapping()
    changelog = mp.load_changelog()
    config = load_locations_config()
    created = 0

    for entry in payload:
        name = entry["name"]
        platforms = entry.get("platforms", [])
        location = entry.get("location", "")

        zoom_id = None
        neat_id = None
        xyte_id = None

        if "neat" in platforms:
            neat_loc_id = entry.get("neat_location_id")
            if neat_loc_id:
                try:
                    result = neat.create_room(neat_loc_id, name)
                    neat_id = result.get("id")
                    print(f"  Neat Pulse: created '{name}' (id={neat_id})")
                except Exception as e:
                    print(f"  Neat Pulse: failed to create '{name}': {e}")

        if "xyte" in platforms:
            xyte_building_id = entry.get("xyte_building_space_id")
            xyte_floor = entry.get("xyte_floor", "1st")
            if xyte_building_id:
                try:
                    floor_id = xyte.find_or_create_space(xyte_floor, xyte_building_id)
                    xyte_id = xyte.find_or_create_space(name, floor_id)
                    print(f"  Xyte: created space '{name}' (id={xyte_id})")
                except Exception as e:
                    print(f"  Xyte: failed to create '{name}': {e}")

        uid = mp.add_room(
            data,
            canonical_name=name,
            location=location,
            zoom_room_id=zoom_id,
            neat_room_id=neat_id,
            xyte_space_id=xyte_id,
        )
        mp.log_change(changelog, action="room_created",
                      room_name=name, uid=uid,
                      details=f"Created on: {', '.join(platforms)}")
        created += 1

    mp.save_mapping(data)
    mp.save_changelog(changelog)
    return created


def decommission_rooms(payload: list, zoom: ZoomClient, neat: NeatClient, xyte: XyteClient):
    """Decommission rooms from all platforms.

    *payload* is a list of dicts: ``{"uid", "confirmation_name"}``.
    """
    data = mp.load_mapping()
    changelog = mp.load_changelog()
    decommissioned = 0

    for entry in payload:
        uid = entry["uid"]
        confirmation = entry["confirmation_name"]

        room = data["rooms"].get(uid)
        if not room:
            print(f"  [skip] Unknown room UUID: {uid}")
            continue

        # Server-side name verification
        if room["canonical_name"] != confirmation:
            print(f"  [skip] Name mismatch for {uid}: "
                  f"expected '{room['canonical_name']}', got '{confirmation}'")
            continue

        name = room["canonical_name"]
        print(f"  Decommissioning '{name}'...")

        # Zoom
        zoom_id = room.get("zoom_room_id")
        if zoom_id:
            try:
                zoom.delete_room(zoom_id)
                print(f"    Zoom: deleted")
            except Exception as e:
                print(f"    Zoom: delete failed: {e}")

        # Neat Pulse
        neat_id = room.get("neat_room_id")
        if neat_id:
            try:
                neat.delete_room(neat_id)
                print(f"    Neat Pulse: deleted (devices become unassigned)")
            except Exception as e:
                print(f"    Neat Pulse: delete failed: {e}")

        # Xyte — move devices to Unsorted, delete space, cascade cleanup
        xyte_id = room.get("xyte_space_id")
        if xyte_id:
            # Find the building space ID for this room
            config = load_locations_config()
            building_id = None
            for loc in config.get("locations", []):
                if loc.get("xyte_building_space_id"):
                    building_id = loc["xyte_building_space_id"]
                    break
            if building_id:
                try:
                    logs = xyte.decommission_space(xyte_id, building_id)
                    for msg in logs:
                        print(f"    Xyte: {msg}")
                except Exception as e:
                    print(f"    Xyte: decommission failed: {e}")

        # Remove from mapping
        mp.remove_room(data, uid)
        mp.log_change(changelog, action="decommissioned",
                      room_name=name, uid=uid,
                      details=f"Removed from all platforms")
        decommissioned += 1

    mp.save_mapping(data)
    mp.save_changelog(changelog)
    return decommissioned
