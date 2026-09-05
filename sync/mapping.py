"""Read and write the persistent room-to-room ID mapping.

The mapping file (``data/mapping.json``) stores stable UUIDs for each
room, linking platform-specific IDs so renames can propagate.  No
credentials or sensitive data are stored in this file.
"""

import json
import os
import uuid
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MAPPING_PATH = os.path.join(DATA_DIR, "mapping.json")
PENDING_PATH = os.path.join(DATA_DIR, "pending.json")
CHANGELOG_PATH = os.path.join(DATA_DIR, "changelog.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_uuid() -> str:
    return str(uuid.uuid4())


# -- Mapping CRUD -------------------------------------------------------

def load_mapping() -> dict:
    """Load ``mapping.json``, returning a default structure if missing."""
    if os.path.exists(MAPPING_PATH):
        with open(MAPPING_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {
        "version": 1,
        "last_sync": None,
        "rooms": {},
        "unmapped_zoom": [],
        "unmapped_neat": [],
        "unmapped_xyte": [],
    }


def save_mapping(data: dict) -> None:
    data["last_sync"] = _now_iso()
    os.makedirs(os.path.dirname(MAPPING_PATH), exist_ok=True)
    with open(MAPPING_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def add_room(mapping: dict, *, canonical_name: str, location: str = "",
             zoom_room_id=None, neat_room_id=None,
             xyte_space_id=None, xyte_device_ids=None) -> str:
    """Add a new room entry and return its UUID."""
    uid = _new_uuid()
    mapping["rooms"][uid] = {
        "canonical_name": canonical_name,
        "zoom_room_id": zoom_room_id,
        "neat_room_id": neat_room_id,
        "xyte_space_id": xyte_space_id,
        "xyte_device_ids": xyte_device_ids or [],
        "location": location,
        "created": _now_iso(),
        "last_verified": _now_iso(),
    }
    return uid


def remove_room(mapping: dict, uid: str) -> dict | None:
    """Remove a room by UUID.  Returns the removed entry or ``None``."""
    return mapping["rooms"].pop(uid, None)


def find_room_by_platform_id(mapping: dict, platform: str, platform_id) -> tuple:
    """Find a room by its platform-specific ID.

    Returns ``(uuid, room_dict)`` or ``(None, None)``.
    """
    key = {
        "zoom": "zoom_room_id",
        "neat": "neat_room_id",
        "xyte": "xyte_space_id",
    }.get(platform)
    if not key:
        return None, None

    pid = str(platform_id)
    for uid, room in mapping["rooms"].items():
        if str(room.get(key, "")) == pid:
            return uid, room
    return None, None


# -- Pending (discrepancies / suggestions) --------------------------------

def load_pending() -> dict:
    if os.path.exists(PENDING_PATH):
        with open(PENDING_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"suggestions": [], "discrepancies": [], "create_requests": [], "decommission_requests": []}


def save_pending(data: dict) -> None:
    os.makedirs(os.path.dirname(PENDING_PATH), exist_ok=True)
    with open(PENDING_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


# -- Changelog -----------------------------------------------------------

def load_changelog() -> list:
    if os.path.exists(CHANGELOG_PATH):
        with open(CHANGELOG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_changelog(entries: list) -> None:
    os.makedirs(os.path.dirname(CHANGELOG_PATH), exist_ok=True)
    with open(CHANGELOG_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
        f.write("\n")


def log_change(entries: list, *, action: str, details: str,
               room_name: str = "", uid: str = "") -> None:
    """Append a changelog entry."""
    entries.append({
        "timestamp": _now_iso(),
        "action": action,
        "room_name": room_name,
        "uid": uid,
        "details": details,
    })
