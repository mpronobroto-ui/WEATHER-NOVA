"""
Location resolution.

Uses Open-Meteo's free geocoding API (no key required) as the default
provider. In production this is where you would additionally fan out to
IMD's gazetteer / district shapefiles or a GIS service so that Indian
village and tehsil names resolve correctly.
"""
from __future__ import annotations

import httpx
from typing import Optional

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

# Common Indian place aliases that geocoders sometimes miss or misspell
_ALIASES = {
    "west bengal": "Kolkata",
    "wb": "Kolkata",
    "bengal": "Kolkata",
    "bay of bengal": "Port Blair",
    "bay bengal": "Port Blair",
    "arabian sea": "Mumbai",
    "arabian": "Mumbai",
    "andaman": "Port Blair",
    "mmbai": "Mumbai",
    "bombay": "Mumbai",
    "calcutta": "Kolkata",
    "madras": "Chennai",
    "bangalore": "Bengaluru",
    "ncr": "New Delhi",
    "delhi ncr": "New Delhi",
}


async def resolve_location(query: str, language: str = "en") -> Optional[dict]:
    """Resolve a free-text place name to coordinates + metadata.

    Returns None if nothing could be found.
    """
    q = (query or "").strip()
    if not q:
        return None

    # Apply simple alias expansion for common Indian regions
    alias = _ALIASES.get(q.lower())
    search_name = alias or q

    params = {"name": search_name, "count": 3, "language": language or "en", "format": "json"}
    async with httpx.AsyncClient(timeout=8.0) as client:
        try:
            resp = await client.get(GEOCODE_URL, params=params)
            resp.raise_for_status()
        except httpx.HTTPError:
            return None

    data = resp.json()
    results = data.get("results") or []
    if not results:
        return None

    # Prefer results in India when the query is India-related
    top = results[0]
    for r in results:
        if (r.get("country_code") or "").upper() == "IN" or (r.get("country") or "").lower() == "india":
            top = r
            break

    name = top.get("name")
    # Keep the user's original region name when we used an alias
    if alias and q.lower() in _ALIASES:
        name = q.title()

    return {
        "name": name,
        "admin1": top.get("admin1"),  # state
        "admin2": top.get("admin2"),  # district
        "country": top.get("country"),
        "latitude": top.get("latitude"),
        "longitude": top.get("longitude"),
        "timezone": top.get("timezone", "auto"),
    }


async def reverse_label(lat: float, lon: float) -> str:
    """Best-effort human label for a coordinate pair (used for replies)."""
    return f"{lat:.2f}°, {lon:.2f}°"
