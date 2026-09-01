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
    "rajarhat": "Rajarhat, West Bengal",
    "rajarhat, kolkata": "Rajarhat, West Bengal",
    "rajarhat kolkata": "Rajarhat, West Bengal",
    "chinar park": "Chinar Park, Kolkata",
    "chinar park, kolkata": "Chinar Park, Kolkata",
    "chinar park kolkata": "Chinar Park, Kolkata",
    "salt lake": "Bidhannagar, Kolkata",
    "saltlake": "Bidhannagar, Kolkata",
    "salt lake, kolkata": "Bidhannagar, Kolkata",
    "salt lake city": "Bidhannagar, Kolkata",
    "sector 5": "Sector V, Bidhannagar, Kolkata",
    "sector v": "Sector V, Bidhannagar, Kolkata",
    "new town": "New Town, Kolkata",
    "newtown": "New Town, Kolkata",
    "new town, kolkata": "New Town, Kolkata",
    "action area 1": "New Town, Kolkata",
    "action area 2": "New Town, Kolkata",
    "action area 3": "New Town, Kolkata",
    "baguiati": "Baguiati, Kolkata",
    "dum dum": "Dum Dum, Kolkata",
    "dumdum": "Dum Dum, Kolkata",
    "gariahat": "Gariahat, Kolkata",
    "shyambazar": "Shyambazar, Kolkata",
    "esplanade": "Esplanade, Kolkata",
    "park street": "Park Street, Kolkata",
    "alipore": "Alipore, Kolkata",
    "behala": "Behala, Kolkata",
    "jadavpur": "Jadavpur, Kolkata",
    "tollygunge": "Tollygunge, Kolkata",
    "ballygunge": "Ballygunge, Kolkata",
    "sealdah": "Sealdah, Kolkata",
    "howrah": "Howrah, West Bengal",
    "bandra": "Bandra, Mumbai",
    "bandra, mumbai": "Bandra, Mumbai",
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


def _score_openmeteo_result(r: dict, target_norm: str, context_norms: list[str]) -> float:
    """Calculate match score for an Open-Meteo result."""
    name_norm = _normalize(r.get("name") or "")
    country_code = (r.get("country_code") or "").upper()
    country_norm = _normalize(r.get("country") or "")
    admin1_norm = _normalize(r.get("admin1") or "")
    admin2_norm = _normalize(r.get("admin2") or "")
    admin3_norm = _normalize(r.get("admin3") or "")
    is_india = country_code == "IN" or country_norm == "india"
    population = float(r.get("population") or 0)

    score = 0.0

    if name_norm == target_norm:
        # Exact name match
        score += 100.0 if is_india else 80.0
    elif name_norm.startswith(target_norm) or target_norm.startswith(name_norm):
        score += 70.0 if is_india else 55.0
    elif target_norm in name_norm or name_norm in target_norm:
        score += 50.0 if is_india else 35.0
    elif is_india:
        score += 20.0

    # Context validation: if user specified "X, context" (e.g. "rajarhat, kolkata" or "paris, texas")
    if context_norms:
        matched_context = False
        for ctx in context_norms:
            if (
                ctx in admin1_norm or admin1_norm in ctx or
                ctx in admin2_norm or admin2_norm in ctx or
                ctx in admin3_norm or admin3_norm in ctx or
                ctx in country_norm or country_norm in ctx or
                ctx in name_norm
            ):
                matched_context = True
                break
        if matched_context:
            score += 50.0
        else:
            # Candidate does not match the requested city/state/region context
            score -= 80.0

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
    parts = [p.strip() for p in search_name.split(",") if p.strip()]
    primary_name = parts[0] if parts else search_name
    context_norms = [_normalize(p) for p in parts[1:]]

    headers = {"User-Agent": "WeatherNova/1.0 (weather-intelligence)"}
    queries_to_try = [primary_name]
    if search_name != primary_name:
        queries_to_try.insert(0, search_name)

    results = []
    for q_term in queries_to_try:
        params = {"name": q_term, "count": 10, "language": language or "en", "format": "json"}
        try:
            async with httpx.AsyncClient(headers=headers, timeout=8.0, follow_redirects=True) as client:
                resp = await client.get(GEOCODE_URL, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    r_list = data.get("results") or []
                    if r_list:
                        results = r_list
                        break
        except Exception as exc:
            logger.debug("Open-Meteo geocode error: %s", exc)

    if not results:
        return None

    target_norm = _normalize(primary_name)
    scored = [(_score_openmeteo_result(r, target_norm, context_norms), r) for r in results]
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
    headers = {"User-Agent": "WeatherNova/1.0 (weather-intelligence)"}
    parts = [p.strip() for p in search_name.split(",") if p.strip()]
    primary_name = parts[0] if parts else search_name
    context_norms = [_normalize(p) for p in parts[1:]]

    # 1. Try Nominatim for structured precision (with addressdetails)
    try:
        params = {"q": search_name, "format": "json", "countrycodes": "in", "addressdetails": 1, "limit": 5}
        async with httpx.AsyncClient(headers=headers, timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(NOMINATIM_URL, params=params)
            if resp.status_code == 200:
                results = resp.json()
                if results and isinstance(results, list):
                    selected = results[0]
                    if context_norms:
                        for r in results:
                            disp_norm = _normalize(r.get("display_name", ""))
                            if any(ctx in disp_norm for ctx in context_norms):
                                selected = r
                                break
                    addr = selected.get("address") or {}
                    admin1 = addr.get("state")
                    admin2 = addr.get("city") or addr.get("county") or addr.get("state_district") or addr.get("suburb")
                    country = addr.get("country") or "India"
                    return {
                        "name": selected.get("name") or primary_name.title(),
                        "admin1": admin1,
                        "admin2": admin2,
                        "country": country,
                        "latitude": float(selected["lat"]),
                        "longitude": float(selected["lon"]),
                        "timezone": "Asia/Kolkata",
                    }
    except Exception as exc:
        logger.debug("Nominatim IN fallback failed: %s", exc)

    # 2. Try Photon with User-Agent header
    try:
        async with httpx.AsyncClient(headers=headers, timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(PHOTON_URL, params={"q": search_name, "limit": 5})
            if resp.status_code == 200:
                data = resp.json()
                features = data.get("features") or []
                target_norm = _normalize(primary_name)
                
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
                    state_norm = _normalize(props.get("state") or "")
                    city_norm = _normalize(props.get("city") or props.get("county") or props.get("district") or "")

                    if context_norms:
                        if not any(ctx in state_norm or ctx in city_norm or ctx in name_norm for ctx in context_norms):
                            continue

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
                        "name": props.get("name") or primary_name.title(),
                        "admin1": props.get("state"),
                        "admin2": props.get("city") or props.get("county") or props.get("district"),
                        "country": country,
                        "latitude": float(coords[1]),
                        "longitude": float(coords[0]),
                        "timezone": tz,
                    }
    except Exception as exc:
        logger.debug("Photon fallback failed: %s", exc)

    # 3. Global Nominatim fallback for international locations
    try:
        params = {"q": search_name, "format": "json", "addressdetails": 1, "limit": 3}
        async with httpx.AsyncClient(headers=headers, timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(NOMINATIM_URL, params=params)
            if resp.status_code == 200:
                results = resp.json()
                if results and isinstance(results, list):
                    top = results[0]
                    addr = top.get("address") or {}
                    country = addr.get("country") or "International"
                    admin1 = addr.get("state")
                    admin2 = addr.get("city") or addr.get("county") or addr.get("district")
                    tz = "Asia/Kolkata" if country.lower() == "india" else "auto"
                    return {
                        "name": top.get("name") or primary_name.title(),
                        "admin1": admin1,
                        "admin2": admin2,
                        "country": country,
                        "latitude": float(top["lat"]),
                        "longitude": float(top["lon"]),
                        "timezone": tz,
                    }
    except Exception as exc:
        logger.debug("Nominatim global fallback failed: %s", exc)

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
    if not alias:
        parts = [p.strip() for p in q.split(",") if p.strip()]
        if len(parts) > 1 and parts[0].lower() in _ALIASES:
            alias = _ALIASES[parts[0].lower()]
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
