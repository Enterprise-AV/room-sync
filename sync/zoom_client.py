"""Zoom Rooms API client.

All credentials are read from environment variables — never hardcoded.
"""

import os
import time

import requests

ZOOM_BASE_URL = "https://api.zoom.us/v2"


class ZoomClient:
    def __init__(self):
        self.account_id = os.environ["ZOOM_ACCOUNT_ID"]
        self.client_id = os.environ["ZOOM_CLIENT_ID"]
        self.client_secret = os.environ["ZOOM_CLIENT_SECRET"]
        self._token = None
        self._last_call = 0.0

    def _rate_limit(self):
        """Enforce 10 req/sec rate limit for S2S OAuth."""
        elapsed = time.time() - self._last_call
        if elapsed < 0.1:
            time.sleep(0.1 - elapsed)
        self._last_call = time.time()

    def _get_token(self) -> str:
        if self._token:
            return self._token
        resp = requests.post(
            "https://zoom.us/oauth/token",
            params={"grant_type": "account_credentials", "account_id": self.account_id},
            auth=(self.client_id, self.client_secret),
            timeout=15,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Zoom auth failed: {resp.status_code} {resp.text}")
        self._token = resp.json()["access_token"]
        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    def list_locations(self) -> list:
        """Return all Zoom Rooms locations (paginated)."""
        locations = []
        params = {"page_size": 100}
        while True:
            self._rate_limit()
            resp = requests.get(
                f"{ZOOM_BASE_URL}/rooms/locations",
                headers=self._headers(),
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            locations.extend(data.get("locations", []))
            npt = data.get("next_page_token", "")
            if not npt:
                break
            params["next_page_token"] = npt
        return locations

    def list_rooms(self, location_ids=None) -> list:
        """Return rooms, optionally filtered by location ID(s).

        If *location_ids* is ``None`` all rooms across every location are
        returned.  Otherwise only rooms whose ``location_id`` is in the
        given list are fetched.
        """
        if location_ids is None:
            return self._list_all_rooms()

        all_rooms = []
        for loc_id in location_ids:
            all_rooms.extend(self._list_rooms_for_location(loc_id))
        return all_rooms

    def _list_all_rooms(self) -> list:
        rooms = []
        params = {"page_size": 100}
        while True:
            self._rate_limit()
            resp = requests.get(
                f"{ZOOM_BASE_URL}/rooms",
                headers=self._headers(),
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            rooms.extend(data.get("rooms", []))
            npt = data.get("next_page_token", "")
            if not npt:
                break
            params["next_page_token"] = npt
        return rooms

    def _list_rooms_for_location(self, location_id: str) -> list:
        rooms = []
        params = {"page_size": 100, "location_id": location_id}
        while True:
            self._rate_limit()
            resp = requests.get(
                f"{ZOOM_BASE_URL}/rooms",
                headers=self._headers(),
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            rooms.extend(data.get("rooms", []))
            npt = data.get("next_page_token", "")
            if not npt:
                break
            params["next_page_token"] = npt
        return rooms

    def get_room(self, room_id: str) -> dict:
        self._rate_limit()
        resp = requests.get(
            f"{ZOOM_BASE_URL}/rooms/{room_id}",
            headers=self._headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def rename_room(self, room_id: str, new_name: str) -> dict:
        self._rate_limit()
        resp = requests.patch(
            f"{ZOOM_BASE_URL}/rooms/{room_id}",
            headers=self._headers(),
            json={"basic": {"name": new_name}},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json() if resp.text else {}

    def delete_room(self, room_id: str) -> int:
        self._rate_limit()
        resp = requests.delete(
            f"{ZOOM_BASE_URL}/rooms/{room_id}",
            headers=self._headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.status_code

    def discover_locations(self, building_name: str) -> list:
        """Find Zoom location(s) whose name contains *building_name*."""
        locations = self.list_locations()
        matches = []
        target = building_name.strip().upper()
        for loc in locations:
            if target in loc.get("name", "").strip().upper():
                matches.append(loc)
        return matches
