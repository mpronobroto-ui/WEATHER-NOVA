"""
Extreme-weather alert engine.

India's Meteorological Department (IMD) issues nowcasts and warnings using a
four-colour code — Green (no action), Yellow (watch), Orange (be prepared),
Red (take action). We reuse that exact convention here so the output looks
and behaves like a real bulletin, and derive it from thresholded forecast
variables. In production, `evaluate_day` is the seam where you would instead
ingest actual IMD/NDMA bulletins over WIS2.0 / MQTT and merge them with the
model-derived signal below rather than compute it from scratch.
"""
from __future__ import annotations

COLOR_RANK = {"green": 0, "yellow": 1, "orange": 2, "red": 3}


def _bump(level: str, candidate: str) -> str:
    return candidate if COLOR_RANK[candidate] > COLOR_RANK[level] else level


def evaluate_day(day: dict) -> dict:
    """day: one entry of daily forecast data (already zipped by index)."""
    level = "green"
    hazards = []

    rain = day.get("precipitation_sum") or 0
    rain_prob = day.get("precipitation_probability_max") or 0
    wind = day.get("windgusts_10m_max") or day.get("windspeed_10m_max") or 0
    tmax = day.get("temperature_2m_max")
    tmin = day.get("temperature_2m_min")
    code = day.get("weathercode")

    # Heavy rainfall / flood risk (IMD-style mm/day bands, simplified)
    if rain >= 204.4:
        level = _bump(level, "red")
        hazards.append("extremely heavy rainfall — flood risk")
    elif rain >= 115.6:
        level = _bump(level, "orange")
        hazards.append("very heavy rainfall")
    elif rain >= 64.5:
        level = _bump(level, "yellow")
        hazards.append("heavy rainfall")
    elif rain_prob >= 70:
        level = _bump(level, "yellow")
        hazards.append("high chance of rain")

    # Wind / gale / cyclone-proxy
    if wind >= 90:
        level = _bump(level, "red")
        hazards.append("damaging wind gusts")
    elif wind >= 62:
        level = _bump(level, "orange")
        hazards.append("strong gusty winds")
    elif wind >= 45:
        level = _bump(level, "yellow")
        hazards.append("gusty winds")

    # Heat wave (very approximate; real IMD heat-wave criteria compare to
    # local normals and are region-specific)
    if tmax is not None:
        if tmax >= 45:
            level = _bump(level, "red")
            hazards.append("severe heat wave")
        elif tmax >= 40:
            level = _bump(level, "orange")
            hazards.append("heat wave conditions")

    # Cold wave
    if tmin is not None:
        if tmin <= 2:
            level = _bump(level, "orange")
            hazards.append("cold wave")
        elif tmin <= 5:
            level = _bump(level, "yellow")
            hazards.append("cold conditions")

    # Thunderstorm codes (WMO 95-99)
    if code is not None and int(code) >= 95:
        level = _bump(level, "orange")
        hazards.append("thunderstorm with lightning risk")

    return {"level": level, "hazards": hazards}


def build_alert_timeline(daily: dict) -> list[dict]:
    """daily: the raw `daily` block from the Open-Meteo forecast response."""
    dates = daily.get("time", [])
    n = len(dates)
    timeline = []
    for i in range(n):
        day = {k: (v[i] if i < len(v) else None) for k, v in daily.items() if k != "time"}
        result = evaluate_day(day)
        timeline.append({"date": dates[i], **result})
    return timeline
