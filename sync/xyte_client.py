"""Xyte (RackLink Cloud) API client.

All credentials are read from environment variables — never hardcoded.

Xyte hierarchy: Org Root > Building > Floor > Room
Each "room" in Xyte is a *space* that may contain devices (PDUs).
"""

import os
import time

import requests

XYTE_BASE_URL = "https://hub.xyte.io/core/v1/organization"


class XyteClient:
    def __init__(self):
        self.api_key = os.environ["XYTE_API_KEY"]
        self.org_id = int(os.environ["XYTE_ORG_ID"])

    def _headers(self) -> dict:
        return {
            "Authorization": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    # -- Spaces ----------------------------------------------------------

    def list_spaces(self, parent_id) -> list:
        """Return direct child spaces under *parent_id*."""
        parent_id = int(parent_id)
        resp = requests.get(
            f"{XYTE_BASE_URL}/spaces",
            headers=self._headers(),
            params={"parent_id": parent_id},
            timeout=30,
        )
        resp.raise_for_status()
        return [
            item for item in resp.json().get("items", [])
            if item.get("parent_id") == parent_id
        ]

    def walk_spaces(self, parent_id, path=""):
        """Recursively yield ``(space_id, full_path, space_dict)`` for every
        space under *parent_id*."""
        for item in self.list_spaces(parent_id):
            item_path = f"{path}/{item['name']}" if path else item["name"]
            yield item["id"], item_path, item
            yield from self.walk_spaces(item["id"], item_path)

    def get_children(self, parent_id) -> dict:
        """Return ``{name: space_id}`` for direct children."""
        return {item["name"]: item["id"] for item in self.list_spaces(parent_id)}

    def create_space(self, name: str, parent_id) -> int:
        resp = requests.post(
            f"{XYTE_BASE_URL}/spaces",
            headers=self._headers(),
            json={"name": name, "parent_id": parent_id},
            timeout=30,
        )
        if resp.status_code == 422:
            # Already exists — look it up
            children = self.get_children(parent_id)
            if name in children:
                return children[name]
            raise RuntimeError(
                f"422 on create but '{name}' not found under parent {parent_id}"
            )
        resp.raise_for_status()
        return resp.json()["id"]

    def find_or_create_space(self, name: str, parent_id) -> int:
        children = self.get_children(parent_id)
        if name in children:
            return children[name]
        return self.create_space(name, parent_id)

    def rename_space(self, space_id, new_name: str) -> dict:
        resp = requests.patch(
            f"{XYTE_BASE_URL}/spaces/{space_id}",
            headers=self._headers(),
            json={"name": new_name},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json() if resp.text else {}

    def delete_space(self, space_id) -> None:
        resp = requests.delete(
            f"{XYTE_BASE_URL}/spaces/{space_id}",
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()

    def get_parent_space(self, space_id):
        """Return the parent_id of a space, or ``None``."""
        resp = requests.get(
            f"{XYTE_BASE_URL}/spaces/{space_id}",
            headers=self._headers(),
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json().get("parent_id")
        return None

    # -- Devices ---------------------------------------------------------

    def list_devices(self) -> list:
        """Return all devices in the org (paginated)."""
        devices = []
        page = 1
        while True:
            resp = requests.get(
                f"{XYTE_BASE_URL}/devices",
                headers=self._headers(),
                params={"page": page, "per_page": 100},
                timeout=30,
            )
            resp.raise_for_status()
            body = resp.json()
            devices.extend(body.get("items", []))
            if not body.get("next_page"):
                break
            page = body["next_page"]
        return devices

    def get_devices_in_space(self, space_id) -> list:
        """Return devices whose space matches *space_id*."""
        return [
            d for d in self.list_devices()
            if (d.get("space") or {}).get("id") == space_id
        ]

    def move_device(self, device_id, space_id) -> dict:
        resp = requests.post(
            f"{XYTE_BASE_URL}/devices/{device_id}/move",
            headers=self._headers(),
            json={"space_id": space_id},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json() if resp.text else {}

    def rename_device(self, device_id, new_name: str) -> dict:
        resp = requests.patch(
            f"{XYTE_BASE_URL}/devices/{device_id}",
            headers=self._headers(),
            json={"name": new_name},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json() if resp.text else {}

    # -- Decommission helpers --------------------------------------------

    def find_or_create_unsorted_space(self, building_space_id) -> int:
        """Find or create an 'Unsorted' space under a building."""
        return self.find_or_create_space("Unsorted", building_space_id)

    def decommission_space(self, room_space_id, building_space_id):
        """Move devices to Unsorted, delete the room space, cascade-clean
        empty parents up to (but not including) the org root.

        Returns a list of log messages describing what was done.
        """
        log = []

        # 1) Move devices to Unsorted
        devices = self.get_devices_in_space(room_space_id)
        if devices:
            unsorted_id = self.find_or_create_unsorted_space(building_space_id)
            for dev in devices:
                dev_id = dev["id"]
                dev_name = dev.get("name", dev_id)
                self.move_device(dev_id, unsorted_id)
                log.append(f"Moved device '{dev_name}' ({dev_id}) to Unsorted")
                time.sleep(0.3)

        # 2) Delete the room space
        self.delete_space(room_space_id)
        log.append(f"Deleted room space {room_space_id}")

        # 3) Cascade cleanup of empty parents (floor, then building)
        self._cascade_cleanup(room_space_id, log)

        return log

    def _cascade_cleanup(self, deleted_space_id, log):
        """After deleting a space, check if its parent is now an empty leaf
        and delete it too.  Repeats upward but never touches the org root."""
        parent_id = self.get_parent_space(deleted_space_id)
        if parent_id is None or parent_id == self.org_id:
            return

        children = self.list_spaces(parent_id)
        if children:
            return  # parent still has children

        # Check for devices directly in the parent
        devices = self.get_devices_in_space(parent_id)
        if devices:
            return

        self.delete_space(parent_id)
        log.append(f"Cleaned up empty parent space {parent_id}")
        self._cascade_cleanup(parent_id, log)

    # -- Discovery -------------------------------------------------------

    def discover_building(self, building_name: str):
        """Find a building space whose name contains *building_name*."""
        target = building_name.strip().upper()
        for sid, path, item in self.walk_spaces(self.org_id):
            if "/" not in path and target in item["name"].upper():
                return {"id": sid, "name": item["name"], "path": path}
        return None
