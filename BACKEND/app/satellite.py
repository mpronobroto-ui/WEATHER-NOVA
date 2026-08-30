"""
Satellite-informed weather & cyclone data layer.

- Precipitation probability: Open-Meteo ensembles (satellite-assimilated).
- Cyclones: multi-source, no API key
    * IMD — North Indian Ocean (India / Bay of Bengal / Arabian Sea)
    * NHC CurrentStorms.json — Atlantic + East/Central Pacific
    * RAMMB/CIRA TC realtime — global list incl. Western Pacific (Philippines, Japan)
    * WIS2.0 bulletins — fallback
"""
from __future__ import annotations

import difflib
import logging
import re
from datetime import date
from typing import Any, Optional

import httpx

from . import wis2

logger = logging.getLogger("satellite")

IMD_CYCLONE_TRACK = "https://api.imd.gov.in/api/v1/cyclone_track"
NHC_CURRENT_STORMS = "https://www.nhc.noaa.gov/CurrentStorms.json"
RAMMB_TC_REALTIME = "https://rammb-data.cira.colostate.edu/tc_realtime/"

# Region keyword → preferred basins / name filters
_REGION_HINTS = {
    "philippines": {"basins": {"wp"}, "keywords": ("philippine", "par", "luzon", "mindanao", "visayas")},
    "philippine": {"basins": {"wp"}, "keywords": ("philippine", "par")},
    "japan": {"basins": {"wp"}, "keywords": ("japan", "okinawa")},
    "taiwan": {"basins": {"wp"}, "keywords": ("taiwan",)},
    "china": {"basins": {"wp"}, "keywords": ("china", "south china")},
    "vietnam": {"basins": {"wp"}, "keywords": ("vietnam",)},
    "pacific": {"basins": {"wp", "ep", "cp"}, "keywords": ()},
    "western pacific": {"basins": {"wp"}, "keywords": ()},
    "atlantic": {"basins": {"al"}, "keywords": ()},
    "caribbean": {"basins": {"al"}, "keywords": ()},
    "gulf": {"basins": {"al"}, "keywords": ()},
    "india": {"basins": {"io", "ni", "bb", "as"}, "keywords": ("india", "bengal", "arabian")},
    "bengal": {"basins": {"io", "ni"}, "keywords": ("bengal",)},
    "arabian": {"basins": {"io", "ni"}, "keywords": ("arabian",)},
    "australia": {"basins": {"sh", "au"}, "keywords": ("australia",)},
}


async def get_active_cyclones(region: str | None = None) -> list[dict[str, Any]]:
    """Merge active storms from IMD + NHC + RAMMB. Optionally filter by region text."""
    storms: list[dict[str, Any]] = []
    seen = set()

    for fetcher in (_fetch_rammb, _fetch_nhc, _fetch_imd):
        try:
            batch = await fetcher()
        except Exception as exc:
            logger.debug("%s failed: %s", fetcher.__name__, exc)
            batch = []
        for s in batch:
            key = (s.get("name") or "").upper().strip()
            if not key or key in seen:
                continue
            seen.add(key)
            storms.append(s)

    if not storms:
        storms = _wis2_cyclone_fallback()

    if region:
        storms = _filter_by_region(storms, region)
    # Enrich filtered (or top) storms with lat/lon/winds for detailed Yes answers
    for s in storms[:4]:
        if s.get("source") == "RAMMB/CIRA" and s.get("latest_lat") is None and s.get("id"):
            try:
                await _enrich_rammb_storm(s)
            except Exception as exc:
                logger.debug("post-filter enrich failed: %s", exc)
    return storms


async def _fetch_imd() -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.get(IMD_CYCLONE_TRACK)
        resp.raise_for_status()
        body = resp.json()
    data = body.get("data") or {}
    points = (data.get("observed") or []) + (data.get("forecast") or [])
    by_name: dict[str, dict] = {}
    for pt in points:
        name = (pt.get("CYCLONE_NAME") or pt.get("name") or "").strip().upper()
        if not name or name == "UNKNOWN":
            continue
        entry = by_name.setdefault(
            name,
            {
                "name": name,
                "category": pt.get("Category") or pt.get("category"),
                "latest_lat": None,
                "latest_lon": None,
                "mean_msw_kmph": None,
                "basin": "IO",
                "points": [],
                "source": "IMD",
            },
        )
        lat = _to_float(pt.get("lat") or pt.get("latitude"))
        lon = _to_float(pt.get("lon") or pt.get("longitude"))
        msw = _to_float(pt.get("Mean MSW (kmph)") or pt.get("msw") or pt.get("Mean MSW"))
        if lat is not None:
            entry["latest_lat"] = lat
        if lon is not None:
            entry["latest_lon"] = lon
        if msw is not None:
            entry["mean_msw_kmph"] = msw
        entry["points"].append({"lat": lat, "lon": lon, "msw_kmph": msw})
    return list(by_name.values())


async def _fetch_nhc() -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": "WeatherGPT/1.1"}) as client:
        resp = await client.get(NHC_CURRENT_STORMS)
        resp.raise_for_status()
        body = resp.json()
    out = []
    for s in body.get("activeStorms") or []:
        name = (s.get("name") or "").strip().upper()
        if not name:
            continue
        lat = s.get("latitudeNumeric")
        lon = s.get("longitudeNumeric")
        # intensity is often knots
        knots = _to_float(s.get("intensity"))
        msw = round(knots * 1.852, 1) if knots else None
        sid = (s.get("id") or "").lower()
        basin = sid[:2].upper() if len(sid) >= 2 else "AL"
        out.append(
            {
                "name": name,
                "category": s.get("classification") or s.get("type"),
                "latest_lat": lat,
                "latest_lon": lon,
                "mean_msw_kmph": msw,
                "basin": basin,
                "points": [],
                "source": "NHC",
                "id": s.get("id"),
                "last_update": s.get("lastUpdate"),
            }
        )
    return out


async def _fetch_rammb() -> list[dict[str, Any]]:
    """Parse CIRA/RAMMB TC realtime HTML for global active systems (incl. WP typhoons)."""
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 WeatherGPT"}) as client:
        resp = await client.get(RAMMB_TC_REALTIME)
        resp.raise_for_status()
        html = resp.text
    out = []
    # e.g. storm.asp?storm_identifier=wp172026">WP172026 - Typhoon SAUDEL
    for m in re.finditer(
        r'storm_identifier=([a-z0-9]+)"[^>]*>\s*([A-Z0-9]+)\s*-\s*([^<]+)',
        html,
        re.I,
    ):
        sid, code, label = m.group(1), m.group(2), m.group(3)
        label = re.sub(r"<[^>]+>", "", label).strip()
        label = re.sub(r"\s+", " ", label)
        # "Typhoon SAUDEL" or "Tropical Depression NARRA" or "INVEST"
        parts = label.split()
        name = parts[-1].upper() if parts else code.upper()
        category = " ".join(parts[:-1]) if len(parts) > 1 else None
        basin = code[:2].upper() if len(code) >= 2 else sid[:2].upper()
        if name in ("INVEST",):
            name = f"INVEST {code.upper()}"
        out.append(
            {
                "name": name,
                "category": category,
                "latest_lat": None,
                "latest_lon": None,
                "mean_msw_kmph": None,
                "intensity_kt": None,
                "basin": basin,
                "points": [],
                "source": "RAMMB/CIRA",
                "id": sid.lower(),
                "label": label,
                "detail_url": f"https://rammb-data.cira.colostate.edu/tc_realtime/storm.asp?storm_identifier={sid.lower()}",
            }
        )
    # Enrich up to 5 storms with lat/lon/intensity from storm pages
    for s in out[:5]:
        try:
            await _enrich_rammb_storm(s)
        except Exception as exc:
            logger.debug("enrich %s failed: %s", s.get("id"), exc)
    return out


async def _enrich_rammb_storm(storm: dict) -> None:
    sid = storm.get("id")
    if not sid:
        return
    url = f"https://rammb-data.cira.colostate.edu/tc_realtime/storm.asp?storm_identifier={sid}"
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 WeatherGPT"}) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        html = resp.text
    cells = re.findall(r"<td[^>]*>(.*?)</td>", html, re.I | re.S)
    cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
    cells = [c for c in cells if c]
    # Find first forecast row: after headers Forecast Hour, Latitude, Longitude, Intensity
    for i, c in enumerate(cells):
        if c == "0" and i + 3 < len(cells):
            lat = _to_float(cells[i + 1])
            lon = _to_float(cells[i + 2])
            intensity = _to_float(cells[i + 3])
            if lat is not None and lon is not None and abs(lat) > 0.1:
                storm["latest_lat"] = lat
                storm["latest_lon"] = lon
            if intensity and intensity > 0:
                storm["intensity_kt"] = intensity
                storm["mean_msw_kmph"] = round(intensity * 1.852, 1)
            break


def _wis2_cyclone_fallback() -> list[dict[str, Any]]:
    bulletins = wis2.get_recent_bulletins(limit=5)
    return [
        {
            "name": b.get("data_id") or "WIS2 bulletin",
            "category": None,
            "latest_lat": None,
            "latest_lon": None,
            "mean_msw_kmph": None,
            "basin": None,
            "points": [],
            "source": "WIS2",
            "canonical_link": b.get("canonical_link"),
            "received_at": b.get("received_at"),
        }
        for b in bulletins
    ]


_INDIA_TOKENS = (
    "bengal", "odisha", "andhra", "tamil", "gujarat", "mumbai", "chennai",
    "kolkata", "kerala", "goa", "india", "bangladesh", "sri lanka",
)

# Every fuzzy-matchable token (region-hint keys + India tokens), used so a
# misspelling like "phillipines" or "phillippines" still resolves instead of
# silently falling through to "show every storm on Earth".
_ALL_REGION_TOKENS = list(_REGION_HINTS.keys()) + list(_INDIA_TOKENS)


def _resolve_region_hint(r: str) -> dict | None:
    """Find the best region-hint for free-text `r` (already lowercased).

    1. Exact substring match against known keys (fast path).
    2. Fuzzy match against each word in `r` (handles typos like
       "phillipines" -> "philippines") using difflib, so a bad spelling
       still narrows the cyclone list to the right basin instead of
       returning every active storm worldwide.
    """
    for key, val in sorted(_REGION_HINTS.items(), key=lambda kv: -len(kv[0])):
        if key in r:
            return val
    if any(tok in r for tok in _INDIA_TOKENS):
        return _REGION_HINTS["india"]

    words = re.findall(r"[a-z]+", r)
    for word in words:
        if len(word) < 5:
            continue
        match = difflib.get_close_matches(word, _ALL_REGION_TOKENS, n=1, cutoff=0.78)
        if match:
            key = match[0]
            return _REGION_HINTS.get(key) or _REGION_HINTS["india"]
    return None


def _filter_by_region(storms: list[dict[str, Any]], region: str) -> list[dict[str, Any]]:
    r = (region or "").lower().strip()
    if not r:
        return storms
    hint = _resolve_region_hint(r)
    if not hint:
        # Region text didn't resolve to any known basin/country — do NOT
        # fall back to the full global list (that used to leak unrelated
        # Atlantic/East-Pacific storms into an unrelated place's answer).
        # Returning [] makes the caller correctly report "no cyclone found
        # near <place>" instead of an irrelevant worldwide dump.
        return []
    basins = {b.lower() for b in hint["basins"]}
    keywords = hint.get("keywords") or ()
    filtered = []
    for s in storms:
        b = (s.get("basin") or "").lower()
        src = (s.get("source") or "").upper()
        label = (s.get("label") or s.get("name") or "").lower()
        if b in basins:
            filtered.append(s)
            continue
        if ("io" in basins or "ni" in basins) and src == "IMD":
            filtered.append(s)
            continue
        if keywords and any(kw in label for kw in keywords):
            filtered.append(s)
    return filtered


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(str(v).replace("N", "").replace("S", "").replace("E", "").replace("W", "").strip())
    except (TypeError, ValueError):
        return None


def rain_advice(prob: Optional[float], precip_mm: Optional[float] = None) -> dict[str, str]:
    p = float(prob) if prob is not None else 0.0
    mm = float(precip_mm) if precip_mm is not None else 0.0

    if p <= 5 and mm < 0.2:
        verdict, detail, tip = "No", f"There is a {int(round(p))}% chance of rain", "You can leave the umbrella at home."
    elif p <= 20:
        verdict, detail, tip = "Probably not", f"Only a {int(round(p))}% chance of rain", "A light jacket is enough; umbrella optional."
    elif p <= 40:
        verdict, detail, tip = "Maybe", f"Around {int(round(p))}% chance of rain", "Keep a compact umbrella handy just in case."
    elif p <= 60:
        verdict, detail, tip = "Yes, better take one", f"{int(round(p))}% chance of rain", "Carry an umbrella."
    else:
        verdict, detail, tip = "Yes, definitely", f"High chance of rain ({int(round(p))}%)", "Take a sturdy umbrella or raincoat."
    if mm >= 10:
        tip += f" Expected rainfall ~{mm:.1f} mm."
    return {
        "verdict": verdict,
        "detail": detail,
        "tip": tip,
        "probability_pct": int(round(p)),
        "expected_mm": round(mm, 1),
    }


def monsoon_status(for_date: date | None = None, region: str | None = None) -> dict:
    """Seasonal context — India-centric by default; neutral for other regions."""
    d = for_date or date.today()
    m = d.month
    r = (region or "").lower()
    if any(k in r for k in ("philippines", "japan", "taiwan", "vietnam", "pacific", "china")):
        if m in (6, 7, 8, 9, 10, 11):
            phase = "Western Pacific typhoon season"
            tip = "Monitor PAGASA / JMA / JTWC advisories for the Philippine Sea and South China Sea."
        else:
            phase = "Off-peak typhoon window (region dependent)"
            tip = "Fewer systems on average — still check official tropical outlooks."
        return {"month": m, "phase": phase, "tip": tip, "date": d.isoformat()}

    if m in (6, 7, 8, 9):
        phase = "Southwest monsoon active season"
        tip = "Heavy rain and flood risk elevated — follow district IMD bulletins."
    elif m == 10:
        phase = "Monsoon withdrawal / post-monsoon"
        tip = "Cyclone risk rises in Bay of Bengal — monitor IMD cyclone bulletins."
    elif m in (11, 12):
        phase = "Northeast monsoon / post-monsoon cyclone window"
        tip = "Tamil Nadu & SE coast: rain + Bay cyclone vigilance."
    elif m in (4, 5):
        phase = "Pre-monsoon / heat + early cyclone window"
        tip = "Heat stress inland; Arabian Sea / Bay systems possible."
    else:
        phase = "Winter / dry season (region dependent)"
        tip = "Fog/cold-wave risk in north; dry farming planning."
    return {"month": m, "phase": phase, "tip": tip, "date": d.isoformat()}
