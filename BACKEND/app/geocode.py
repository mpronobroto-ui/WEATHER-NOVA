"""
Location resolution.

Multi-tier geocoding engine tailored for Indian regions, cities, towns,
neighbourhoods (e.g. Kalighat, Bandra, Whitefield), coastal resorts (e.g. Digha, Mandarmani),
and pilgrimage centres (e.g. Vrindavan, Puri, Tirupati).

Tier 1: Open-Meteo geocoding API with exact-match priority and population/country scoring.
Tier 2: OpenStreetMap / Photon / Nominatim fallback for sub-localities, wards, beaches, and tehsils.
"""
from __future__ import annotations

import logging
import unicodedata
from typing import Optional
import httpx

logger = logging.getLogger("geocode")

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
PHOTON_URL = "https://photon.komoot.io/api/"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Common Indian place aliases and prominent localities that geocoders miss
_ALIASES = {
    "west bengal": "Kolkata, West Bengal",
    "wb": "Kolkata, West Bengal",
    "bengal": "Kolkata, West Bengal",
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
    "digha": "Digha, West Bengal",
    "dakshineswar": "Dakshineswar, Kolkata",
    "dakshineshwar": "Dakshineswar, Kolkata",
    "kalighat": "Kalighat, Kolkata",
    "puri": "Puri, Odisha",
    "mandarmani": "Mandarmani, West Bengal",
    "bakkhali": "Bakkhali, West Bengal",
    "darjeeling": "Darjeeling, West Bengal",
    "siliguri": "Siliguri, West Bengal",
    "salt lake": "Bidhannagar, Kolkata",
    "saltlake": "Bidhannagar, Kolkata",
    "new town": "New Town, Kolkata",
    "howrah": "Howrah, West Bengal",
    "bandra": "Bandra, Mumbai",
    "juhu": "Juhu, Mumbai",
    "andheri": "Andheri, Mumbai",
    "connaught place": "Connaught Place, New Delhi",
    "cp": "Connaught Place, New Delhi",
    "whitefield": "Whitefield, Bengaluru",
    "koramangala": "Koramangala, Bengaluru",
    "indiranagar": "Indiranagar, Bengaluru",
    "electronic city": "Electronic City, Bengaluru",
    "hitec city": "HITEC City, Hyderabad",
    "gachibowli": "Gachibowli, Hyderabad",
    "t nagar": "T Nagar, Chennai",
    "marina beach": "Marina Beach, Chennai",
    "vrindavan": "Vrindavan, Uttar Pradesh",
    "mathura": "Mathura, Uttar Pradesh",
    "ayodhya": "Ayodhya, Uttar Pradesh",
    "varanasi": "Varanasi, Uttar Pradesh",
    "kashi": "Varanasi, Uttar Pradesh",
    "haridwar": "Haridwar, Uttarakhand",
    "rishikesh": "Rishikesh, Uttarakhand",
    "shirdi": "Shirdi, Maharashtra",
    "tirupati": "Tirupati, Andhra Pradesh",
    "coorg": "Coorg, Karnataka",
    "ooty": "Ooty, Tamil Nadu",
    "kodaikanal": "Kodaikanal, Tamil Nadu",
    "munnar": "Munnar, Kerala",
    "alleppey": "Alappuzha, Kerala",
    "alappuzha": "Alappuzha, Kerala",
    "wayanad": "Wayanad, Kerala",
    "vizag": "Visakhapatnam, Andhra Pradesh",
    "pondicherry": "Puducherry",
    "pondy": "Puducherry",
}


def _normalize(text: str) -> str:
    """Strip accents and lowercase for reliable comparisons (e.g. Kālīghāt -> kalighat)."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = nfkd.encode("ASCII", "ignore").decode("utf-8")
    return ascii_text.strip().lower()


def _score_openmeteo_result(r: dict, target_norm: str) -> float:
    """Calculate match score for an Open-Meteo result."""
    name_norm = _normalize(r.get("name") or "")
    country_code = (r.get("country_code") or "").upper()
    is_india = country_code == "IN" or (r.get("country") or "").lower() == "india"
    population = float(r.get("population") or 0)

    score = 0.0

    if name_norm == target_norm:
        # Exact match: 100 for India, 90 for rest of the world (e.g. Kathmandu, Tokyo, London)
        score += 100.0 if is_india else 90.0
    elif name_norm.startswith(target_norm) or target_norm.startswith(name_norm):
        # Prefix / partial match
        score += 70.0 if is_india else 55.0
    elif target_norm in name_norm or name_norm in target_norm:
        score += 50.0 if is_india else 35.0
    elif is_india:
        score += 30.0

    # Population bonus for major cities (up to 15 points)
    if population > 0:
        score += min(15.0, population / 100000.0)

    # Feature code bonus for national capitals (PPLC) or major administrative seats (PPLA)
    feature_code = (r.get("feature_code") or "").upper()
    if feature_code in ("PPLC", "PPLA", "PPLA2"):
        score += 10.0

    return score


async def _geocode_openmeteo(search_name: str, language: str = "en") -> Optional[dict]:
    """Tier 1 geocoding via Open-Meteo."""
    params = {"name": search_name, "count": 10, "language": language or "en", "format": "json"}
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(GEOCODE_URL, params=params)
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception as exc:
        logger.debug("Open-Meteo geocode error: %s", exc)
        return None

    results = data.get("results") or []
    if not results:
        return None

    target_norm = _normalize(search_name.split(",")[0])
    scored = [(_score_openmeteo_result(r, target_norm), r) for r in results]
    scored.sort(key=lambda x: x[0], reverse=True)

    best_score, top = scored[0]
    # Only return if confidence is adequate
    if best_score < 40.0:
        return None

    return {
        "name": top.get("name"),
        "admin1": top.get("admin1"),  # state
        "admin2": top.get("admin2"),  # district
        "country": top.get("country"),
        "latitude": top.get("latitude"),
        "longitude": top.get("longitude"),
        "timezone": top.get("timezone", "auto"),
        "score": best_score,
    }


async def _geocode_osm_fallback(search_name: str) -> Optional[dict]:
    """Tier 2 fallback using Photon (OSM) / Nominatim for Indian localities and global places."""
    # 1. Try Photon (fast, no rate-limit issues, full OSM features)
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(PHOTON_URL, params={"q": search_name, "limit": 5})
            if resp.status_code == 200:
                data = resp.json()
                features = data.get("features") or []
                target_norm = _normalize(search_name.split(",")[0])
                
                indian_feature = None
                global_exact = None

                for f in features:
                    props = f.get("properties") or {}
                    geom = f.get("geometry") or {}
                    coords = geom.get("coordinates") or []
                    if len(coords) < 2:
                        continue
                    cc = (props.get("countrycode") or "").upper()
                    is_in = cc == "IN" or (props.get("country") or "").lower() == "india"
                    name_norm = _normalize(props.get("name") or "")

                    if is_in and indian_feature is None:
                        indian_feature = (props, coords)
                    if name_norm == target_norm and global_exact is None:
                        global_exact = (props, coords)

                selected = indian_feature or global_exact or (
                    (features[0].get("properties", {}), features[0].get("geometry", {}).get("coordinates", []))
                    if features else None
                )
                if selected and selected[0] and len(selected[1]) >= 2:
                    props, coords = selected
                    country = props.get("country") or ("India" if (props.get("countrycode") or "").upper() == "IN" else "International")
                    tz = "Asia/Kolkata" if country == "India" else "auto"
                    return {
                        "name": props.get("name") or search_name.title(),
                        "admin1": props.get("state"),
                        "admin2": props.get("city") or props.get("county") or props.get("district"),
                        "country": country,
                        "latitude": float(coords[1]),
                        "longitude": float(coords[0]),
                        "timezone": tz,
                    }
    except Exception as exc:
        logger.debug("Photon fallback failed: %s", exc)

    # 2. Try Nominatim as secondary fallback
    try:
        headers = {"User-Agent": "WeatherNova/1.0 (weather-intelligence)"}
        params = {"q": search_name, "format": "json", "countrycodes": "in", "limit": 3}
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(NOMINATIM_URL, params=params, headers=headers)
            if resp.status_code == 200:
                results = resp.json()
                if results and isinstance(results, list):
                    top = results[0]
                    display = top.get("display_name", "")
                    parts = [p.strip() for p in display.split(",")]
                    admin1 = parts[-2] if len(parts) >= 3 else None
                    admin2 = parts[-3] if len(parts) >= 4 else None
                    return {
                        "name": top.get("name") or parts[0] or search_name.title(),
                        "admin1": admin1,
                        "admin2": admin2,
                        "country": "India",
                        "latitude": float(top["lat"]),
                        "longitude": float(top["lon"]),
                        "timezone": "Asia/Kolkata",
                    }
    except Exception as exc:
        logger.debug("Nominatim fallback failed: %s", exc)

    return None


async def resolve_location(query: Optional[str] = None, language: str = "en") -> Optional[dict]:
    """Resolve a free-text place name to coordinates + metadata.

    Returns None if nothing could be found.
    """
    q = (query or "").strip()
    if not q:
        return None

    # Apply alias expansion for common Indian regions / localities
    alias = _ALIASES.get(q.lower())
    search_name = alias or q

    # 1. Try Open-Meteo Geocoder first
    result = await _geocode_openmeteo(search_name, language=language)

    # 2. If Open-Meteo match is not high confidence, try OSM / Photon fallback
    if not result or result.get("score", 0) < 85.0:
        osm_result = await _geocode_osm_fallback(search_name)
        if osm_result:
            result = osm_result

    # 3. If still nothing and an alias wasn't used, try OSM with raw query
    if not result and not alias:
        result = await _geocode_osm_fallback(q)

    if not result:
        return None

    name = result.get("name")
    # If the alias is a more descriptive name, prefer result name or clean alias
    if alias and q.lower() in ("wb", "ncr", "cp", "mmbai"):
        name = result.get("name")
    elif alias and q.lower() in _ALIASES:
        name = result.get("name") or q.title()

    return {
        "name": name,
        "admin1": result.get("admin1"),  # state
        "admin2": result.get("admin2"),  # district / city
        "country": result.get("country"),
        "latitude": result.get("latitude"),
        "longitude": result.get("longitude"),
        "timezone": result.get("timezone", "auto"),
    }


async def reverse_label(lat: float, lon: float) -> str:
    """Best-effort human label for a coordinate pair (used for replies)."""
    return f"{lat:.2f}°, {lon:.2f}°"
