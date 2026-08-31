"""
Alert-subscription store.

Deliberately simple (a JSON file, not a database) so it works with zero
setup — a phone number, a location, and a language. `sms.dispatch_alerts()`
walks this list on a timer and sends a warning to anyone whose location is
under an Orange/Red alert. Swap this for a real table (Postgres) if the
subscriber list needs to scale past a few thousand entries.
"""
from __future__ import annotations

import json
import os
import threading

STORE_PATH = os.getenv("SUBSCRIPTIONS_PATH", os.path.join(os.path.dirname(__file__), "..", "subscriptions.json"))
_lock = threading.RLock()


def _load() -> list[dict]:
    if not os.path.exists(STORE_PATH):
        return []
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(items: list[dict]) -> None:
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)


def add_subscription(
    phone: str,
    lat: float,
    lon: float,
    lang: str = "en",
    label: str | None = None,
    cyclone_alerts: bool = True,
) -> dict:
    with _lock:
        items = _load()
        items = [i for i in items if i.get("phone") != phone]  # replace existing
        entry = {
            "phone": phone,
            "lat": lat,
            "lon": lon,
            "lang": lang,
            "label": label,
            "cyclone_alerts": cyclone_alerts,
        }
        items.append(entry)
        _save(items)
        return entry


def remove_subscription(phone: str) -> bool:
    with _lock:
        items = _load()
        new_items = [i for i in items if i.get("phone") != phone]
        changed = len(new_items) != len(items)
        if changed:
            _save(new_items)
        return changed


def list_subscriptions() -> list[dict]:
    with _lock:
        return _load()


def get_subscription(phone: str) -> dict | None:
    with _lock:
        for item in _load():
            if item.get("phone") == phone:
                return item
    return None
