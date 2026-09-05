"""Neat Pulse API client.

All credentials are read from environment variables — never hardcoded.
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor

import requests

NEAT_BASE_URL = "https://api.pulse.neat.no/v1"


class NeatClient:
    def __init__(self):
        self.api_key = os.environ["NEAT_API_KEY"]
        self.org_id = os.environ["NEAT_ORG_ID"]

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def list_locations(self) -> list:
        """Return all locations in the org."""
        resp = requests.get(
            f"{NEAT_BASE_URL}/orgs/{self.org_id}/locations",
            headers=self._headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return data.get("locations") or data.get("data") or []

    def list_rooms(self, location_id=None) -> list:
        """Return rooms, optionally filtered by location ID.

        The Neat Pulse API does not support server-side location filtering,
        so we fetch all rooms and filter client-side when *location_id* is
        provided.
        """
        resp = requests.get(
            f"{NEAT_BASE_URL}/orgs/{self.org_id}/rooms",
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        rooms = data.get("rooms") if isinstance(data, dict) else data

        # Normalize names
        for r in rooms:
            raw = r.get("name", "")
            r["_raw_name"] = raw
            r["name"] = raw.strip()

        if location_id is None:
            return rooms

        # Need per-room details to filter by location
        details = self._fetch_all_details(rooms)
        return [
            r for r in rooms
            if str((details.get(r["id"], {}).get("location") or {}).get("id", "")) == str(location_id)
        ]

    def _fetch_all_details(self, rooms: list) -> dict:
        """Fetch details for all rooms in parallel (3 workers)."""
        def _get(room):
            time.sleep(0.05)
            return room["id"], self.get_room(room["id"])
        with ThreadPoolExecutor(max_workers=3) as ex:
            return dict(ex.map(_get, rooms))

    def get_room(self, room_id) -> dict:
        resp = requests.get(
            f"{NEAT_BASE_URL}/orgs/{self.org_id}/rooms/{room_id}",
            headers=self._headers(),
            timeout=15,
        )
        if resp.status_code == 200:
            try:
                return resp.json()
            except Exception:
                pass
        return {}

    def rename_room(self, room_id, new_name: str) -> dict:
        resp = requests.patch(
            f"{NEAT_BASE_URL}/orgs/{self.org_id}/rooms/{room_id}",
            headers=self._headers(),
            json={"name": new_name},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json() if resp.text else {}

    def create_room(self, location_id, name: str) -> dict:
        resp = requests.post(
            f"{NEAT_BASE_URL}/orgs/{self.org_id}/rooms",
            headers=self._headers(),
            json={"locationId": location_id, "name": name},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json() if resp.text else {}

    def delete_room(self, room_id) -> int:
        resp = requests.delete(
            f"{NEAT_BASE_URL}/orgs/{self.org_id}/rooms/{room_id}",
            headers=self._headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.status_code

    def create_location(self, name: str) -> dict:
        resp = requests.post(
            f"{NEAT_BASE_URL}/orgs/{self.org_id}/locations",
            headers=self._headers(),
            json={"name": name},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json() if resp.text else {}

    def discover_location(self, building_name: str):
        """Find a Neat Pulse location whose name contains *building_name*."""
        locations = self.list_locations()
        target = building_name.strip().upper()
        for loc in locations:
            if target in loc.get("name", "").strip().upper():
                return loc
        return None
