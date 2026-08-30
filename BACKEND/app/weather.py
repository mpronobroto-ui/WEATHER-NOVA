"""
Weather Nova Backend — Weather Core Module

Single seam to the NWP model provider. Uses Open-Meteo's free forecast +
archive APIs (no API key required) so the whole app runs out of the box,
per the project brief ("no mocked weather, no API keys required to demo").
Swap this file for IMD/NCMRWF GFS or a self-hosted WRF store without
touching any other module — every other file only calls the functions
below and expects the Open-Meteo-shaped `daily` / `current_weather` dicts.
"""
from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any, Dict, List
import httpx

logger = logging.getLogger("weathergpt")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

DAILY_VARS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "precipitation_probability_max",
    "windspeed_10m_max",
    "windgusts_10m_max",
    "winddirection_10m_dominant",
    "uv_index_max",
    "relative_humidity_2m_max",
    "weathercode",
]

# WMO weather codes -> short human label (used by composer.py for replies)
_WEATHER_CODE_LABELS = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "dense freezing drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "slight snow",
    73: "moderate snow",
    75: "heavy snow",
    77: "snow grains",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


def weather_code_label(code: Any) -> str:
    """Map a WMO weather code to a short human-readable label."""
    try:
        return _WEATHER_CODE_LABELS.get(int(code), "changeable conditions")
    except (TypeError, ValueError):
        return "changeable conditions"


async def _get(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                return response.json()
            logger.warning("Weather API responded with status: %d", response.status_code)
            return {"error": True, "reason": f"Upstream status {response.status_code}", "daily": {}}
    except Exception as exc:
        logger.warning("Weather API request failed: %s", exc)
        return {"error": True, "reason": "Network execution timeout.", "daily": {}}


async def get_forecast(lat: float, lon: float, days: int = 7) -> Dict[str, Any]:
    """Fetches real-time NWP forecast + current conditions for a location."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": ",".join(DAILY_VARS),
        "hourly": "precipitation_probability,visibility,windspeed_10m",
        "current_weather": True,
        "timezone": "auto",
        "forecast_days": max(1, min(days, 16)),
    }
    data = await _get(FORECAST_URL, params)
    if data.get("error"):
        return data
    # Normalise Open-Meteo's `current_weather` key so composer.py's
    # `.get("temperature", ...)` lookup always finds a value.
    current = data.get("current_weather") or {}
    return {
        "daily": data.get("daily", {}),
        "hourly": data.get("hourly", {}),
        "current_weather": current,
    }


async def get_historical_summary(lat: float, lon: float, years_back: int = 10) -> List[Dict[str, Any]]:
    """Retrieves historical weather metrics to chart multi-year climatological trends."""
    today = date.today()
    historical_datasets: List[Dict[str, Any]] = []

    for i in range(1, years_back + 1):
        target_year = today.year - i
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": f"{target_year}-01-01",
            "end_date": f"{target_year}-12-31",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            "timezone": "auto",
        }
        data = await _get(ARCHIVE_URL, params)
        daily = data.get("daily") if not data.get("error") else None
        if daily:
            historical_datasets.append({"year": target_year, "data": daily})

    return historical_datasets


async def get_marine_forecast(lat: float, lon: float, days: int = 3) -> Dict[str, Any]:
    """Real ocean swell/wave data from Open-Meteo's free Marine Weather API
    (no key required). Inland coordinates legitimately return no wave data —
    that's an absent-data case for callers to handle, not an error to fake."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "wave_height_max,wind_wave_height_max,swell_wave_height_max",
        "timezone": "auto",
        "forecast_days": max(1, min(days, 8)),
    }
    return await _get(MARINE_URL, params)


async def get_energy_forecast(lat: float, lon: float, days: int = 2) -> Dict[str, Any]:
    """Real hourly solar-irradiance and 80m wind-speed series for a simple
    renewable-energy outlook. This is genuine Open-Meteo NWP data — not a
    physics-based generation model (GraphCast / Prithvi-WxC), which this
    environment has no infrastructure to run."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "shortwave_radiation,direct_radiation,windspeed_80m",
        "timezone": "auto",
        "forecast_days": max(1, min(days, 3)),
    }
    return await _get(FORECAST_URL, params)


def summarize_yearly_trend(datasets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Reduces each year's raw daily archive into one summary row per year,
    oldest first, so composer.py can slice `trend[-5:]` for a recent-years
    snapshot and format each row with `.avg_max_temp_c` / `.total_rainfall_mm`.
    """
    trend: List[Dict[str, Any]] = []
    for entry in sorted(datasets, key=lambda e: e["year"]):
        temps = entry["data"].get("temperature_2m_max", []) or []
        precip = entry["data"].get("precipitation_sum", []) or []
        temps = [t for t in temps if t is not None]
        precip = [p for p in precip if p is not None]
        trend.append({
            "year": entry["year"],
            "avg_max_temp_c": round(sum(temps) / len(temps), 2) if temps else None,
            "total_rainfall_mm": round(sum(precip), 2) if precip else None,
        })
    return trend
