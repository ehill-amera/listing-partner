"""Which rooms the facts require against the kept photos. No model call."""

from __future__ import annotations

import math

STRONG_MIN = 3


def required_rooms(facts: dict) -> list[str]:
    rooms = [f"bedroom {i + 1}" for i in range(int(facts["bedrooms"]))]
    rooms += [f"bathroom {i + 1}" for i in range(math.ceil(facts["bathrooms"]))]
    return [*rooms, "kitchen", "living area", "front exterior"]


def _label_for(room: str) -> str:
    if room == "living area":
        return "living room"
    return room.rsplit(" ", 1)[0] if room[-1].isdigit() else room


def _strong(photo: dict) -> bool:
    return photo["sharpness"] >= STRONG_MIN and photo["framing"] >= STRONG_MIN


def check_coverage(facts: dict, kept: list[dict]) -> list[dict]:
    """One row per required room. Each photo covers one room, strongest first."""
    pools: dict[str, list[dict]] = {}
    for photo in sorted(kept, key=lambda p: not _strong(p)):
        pools.setdefault(photo["room"], []).append(photo)
    rows = []
    for room in required_rooms(facts):
        pool = pools.get(_label_for(room), [])
        if not pool:
            rows.append({"room": room, "status": "missing", "photo": None})
            continue
        photo = pool.pop(0)
        status = "found" if _strong(photo) else "no strong shot"
        rows.append({"room": room, "status": status, "photo": photo["id"]})
    return rows
