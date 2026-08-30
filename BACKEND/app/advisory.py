"""
Sector decision-support layer.

Turns raw forecast + alert output into short, actionable advisories for the
use cases named in the brief: agriculture, aviation, marine, and urban/smart
city planning. Kept rule-based and transparent on purpose — a disaster
manager or farmer needs to trust *why* an advisory was issued, not just the
sentence itself.
"""
from __future__ import annotations

from . import alerts as alerts_mod


def pest_risk_index(day: dict) -> dict:
    """Approximate pest/disease breeding-condition risk from humidity + max
    temperature. Warm (22-34°C) + humid (>=65% RH) conditions are the classic
    window for fungal disease and many crop-pest breeding cycles — this is a
    threshold heuristic, not a species-specific entomological model."""
    humidity = day.get("relative_humidity_2m_max")
    tmax = day.get("temperature_2m_max")
    if humidity is None or tmax is None:
        return {"level": "unknown", "note": "Insufficient data for a pest risk index."}

    if humidity >= 80 and 22 <= tmax <= 34:
        level = "high"
        note = "High humidity + warm temperatures — strong fungal/pest breeding risk. Scout crops closely and consider preventive treatment."
    elif humidity >= 65 and 20 <= tmax <= 36:
        level = "moderate"
        note = "Warm, moderately humid conditions — elevated pest/disease risk. Monitor fields regularly."
    else:
        level = "low"
        note = "Conditions are not particularly favourable for pest/disease outbreaks."
    return {"level": level, "humidity_pct": humidity, "temp_c": tmax, "note": note}


def crosswind_risk(day: dict) -> dict:
    """Crosswind tip-over risk for high-sided vehicles (trucks, buses) on
    exposed roads and bridges, from surface wind gusts."""
    gust = day.get("windgusts_10m_max") or day.get("windspeed_10m_max") or 0
    if gust >= 70:
        level, note = "severe", f"Gusts ~{gust:.0f} km/h — high risk of high-sided vehicle tip-over on exposed/elevated roads; avoid bridges and coastal highways with such vehicles."
    elif gust >= 50:
        level, note = "high", f"Gusts ~{gust:.0f} km/h — crosswind tipping risk for trucks/buses on exposed stretches; reduce speed on bridges."
    elif gust >= 35:
        level, note = "moderate", f"Gusts ~{gust:.0f} km/h — moderate crosswind risk for high-sided vehicles."
    else:
        level, note = "low", "No significant crosswind risk expected."
    return {"level": level, "gust_kmh": gust, "note": note}


def port_delay_risk(marine_day: dict | None) -> dict:
    """Estimate port/loading-operation delay risk from ocean swell height.
    Uses real swell data from Open-Meteo's free Marine Weather API — returns
    'unknown' rather than a made-up number when no marine data is available
    (e.g. an inland location)."""
    if not marine_day:
        return {"level": "unknown", "note": "No marine/swell data available for this location (likely inland)."}
    height = marine_day.get("swell_wave_height_max")
    if height is None:
        height = marine_day.get("wave_height_max")
    if height is None:
        return {"level": "unknown", "note": "Marine forecast did not return swell data for this point."}
    if height >= 4:
        level, note = "severe", f"Swell ~{height:.1f} m — port operations likely suspended; expect significant loading/berthing delays."
    elif height >= 2.5:
        level, note = "high", f"Swell ~{height:.1f} m — loading restrictions and delays likely at exposed berths."
    elif height >= 1.5:
        level, note = "moderate", f"Swell ~{height:.1f} m — minor delays possible; monitor port advisories."
    else:
        level, note = "low", "Sea state favourable for normal port operations."
    return {"level": level, "swell_m": height, "note": note}


def energy_forecast_summary(hourly: dict) -> dict:
    """Turns a raw Open-Meteo hourly series (shortwave radiation + 80m wind
    speed) into a simple solar/wind outlook. Genuine NWP numbers — not a
    substitute for a physics-based yield model like GraphCast/Prithvi-WxC."""
    radiation = [v for v in (hourly.get("shortwave_radiation") or []) if v is not None]
    wind80 = [v for v in (hourly.get("windspeed_80m") or []) if v is not None]

    avg_radiation = round(sum(radiation) / len(radiation), 1) if radiation else None
    peak_radiation = round(max(radiation), 1) if radiation else None
    avg_wind80 = round(sum(wind80) / len(wind80), 1) if wind80 else None
    max_wind80 = round(max(wind80), 1) if wind80 else None

    if avg_radiation is None:
        solar_outlook = "unknown — no radiation data returned"
    elif avg_radiation >= 400:
        solar_outlook = "strong solar generation expected"
    elif avg_radiation >= 200:
        solar_outlook = "moderate solar generation expected"
    else:
        solar_outlook = "weak solar generation — cloud cover likely"

    if avg_wind80 is None:
        wind_outlook = "unknown — no wind data returned"
    elif max_wind80 and max_wind80 >= 90:
        wind_outlook = "turbines likely to cut out at times — gusts exceed safe operating limits"
    elif avg_wind80 >= 12:
        wind_outlook = "strong, steady output expected (near-rated turbine output)"
    elif avg_wind80 >= 6:
        wind_outlook = "moderate output expected"
    elif avg_wind80 >= 3:
        wind_outlook = "light output — below optimal turbine range"
    else:
        wind_outlook = "little to no wind output expected — below typical cut-in speed"

    return {
        "avg_shortwave_radiation_wm2": avg_radiation,
        "peak_shortwave_radiation_wm2": peak_radiation,
        "solar_outlook": solar_outlook,
        "avg_windspeed_80m_kmh": avg_wind80,
        "max_windspeed_80m_kmh": max_wind80,
        "wind_outlook": wind_outlook,
        "horizon_hours": len(radiation) or len(wind80),
    }


def retail_advisory(alert: dict, timeline: list[dict]) -> list[str]:
    """Stock-ahead suggestions for local retailers, based on the hazard
    outlook over the next few days (not just today)."""
    tips: list[str] = []
    upcoming = timeline[:4] if timeline else [alert]
    hazards_ahead = " ".join(" ".join(day.get("hazards", [])) for day in upcoming)
    worst = "green"
    for day in upcoming:
        if alerts_mod.COLOR_RANK.get(day.get("level", "green"), 0) > alerts_mod.COLOR_RANK.get(worst, 0):
            worst = day.get("level", "green")

    if "rainfall" in hazards_ahead or "rain" in hazards_ahead:
        tips.append("Stock up on umbrellas, raincoats, tarpaulins and bottled water — heavy rain/flood risk in the coming days.")
    if worst in ("orange", "red") and ("wind" in hazards_ahead or "gust" in hazards_ahead):
        tips.append("Stock generators, torches, batteries and non-perishables ahead of possible storm/cyclone disruption.")
    if "heat wave" in hazards_ahead:
        tips.append("Stock cold beverages, ORS/electrolytes, fans and sun-protection items — heat wave conditions ahead.")
    if "cold" in hazards_ahead:
        tips.append("Stock warm clothing, blankets and heaters — cold wave conditions ahead.")
    if not tips:
        tips.append("No extreme-weather-driven demand shift expected in the next few days — normal stocking levels should suffice.")
    tips.append(f"Outlook hazard level over the next {len(upcoming)} day(s): {worst.upper()}.")
    return tips


def construction_advisory(day: dict, alert: dict) -> list[str]:
    """Work-stoppage guidance for site/crane operations, based on lightning,
    surface wind gusts (a proxy for wind shear risk to crane operations),
    and heat-index risk."""
    tips: list[str] = []
    code = day.get("weathercode")
    gust = day.get("windgusts_10m_max") or day.get("windspeed_10m_max") or 0
    tmax = day.get("temperature_2m_max")

    if code is not None and int(code) >= 95:
        tips.append("STOP outdoor/crane work: thunderstorm with lightning risk in the area — resume only after the storm has cleared the site.")
    if gust >= 60:
        tips.append(f"STOP crane/high-elevation work: gusts ~{gust:.0f} km/h exceed typical crane wind limits.")
    elif gust >= 40:
        tips.append(f"CAUTION for crane/high-elevation work: gusts ~{gust:.0f} km/h are approaching limits — supervisor sign-off recommended.")
    if tmax is not None and tmax >= 40:
        tips.append("Reschedule strenuous outdoor work to early morning/evening — extreme heat-index risk at midday.")
    if not tips:
        tips.append("No weather-driven work-stoppage triggers today — normal site operations can proceed.")
    tips.append(f"Site hazard level: {(alert.get('level') or 'green').upper()}.")
    return tips


def agriculture_advisory(day: dict, alert: dict) -> list[str]:
    tips = []
    rain = day.get("precipitation_sum") or 0
    rain_prob = day.get("precipitation_probability_max") or 0
    wind = day.get("windspeed_10m_max") or 0
    tmax = day.get("temperature_2m_max")

    if alert["level"] in ("orange", "red") and "rainfall" in " ".join(alert["hazards"]):
        tips.append("Delay spraying/fertigation and pesticide application — heavy rain expected.")
        tips.append("Ensure field drainage channels are clear to prevent waterlogging.")
    elif rain_prob >= 60:
        tips.append("Hold off irrigation today — rain is likely, save water and cost.")
    elif rain < 1 and (tmax or 0) >= 35:
        tips.append("Irrigate during early morning or evening to reduce evaporation loss.")

    if wind >= 40:
        tips.append("Avoid spraying operations — wind drift risk is high.")
    if tmax is not None and tmax >= 40:
        tips.append("Provide shade/mulching for sensitive crops and extra water for livestock.")

    pest = pest_risk_index(day)
    if pest["level"] in ("moderate", "high"):
        tips.append(f"Pest/disease risk: {pest['level'].upper()} — {pest['note']}")

    if not tips:
        tips.append("Conditions look normal for routine field operations.")
    return tips


def aviation_briefing(day: dict, hourly_slice: dict, alert: dict) -> list[str]:
    notes = []
    wind = day.get("windgusts_10m_max") or day.get("windspeed_10m_max") or 0
    code = day.get("weathercode")
    if wind >= 45:
        notes.append(f"Gusts up to {wind:.0f} km/h — expect crosswind/turbulence advisories.")
    if code is not None and int(code) in (45, 48):
        notes.append("Fog/low visibility conditions reported — check METAR/TAF before departure.")
    if code is not None and int(code) >= 95:
        notes.append("Thunderstorm activity in the area — possible convective diversions/delays.")
    if alert["level"] in ("orange", "red"):
        notes.append(f"Overall day hazard level: {alert['level'].upper()} — brief crew accordingly.")
    if not notes:
        notes.append("No significant en-route hazards identified from model guidance.")
    notes.append("This is model-derived guidance, not a substitute for official METAR/TAF/SIGMET.")
    return notes


def marine_advisory(day: dict, alert: dict, marine_day: dict | None = None) -> list[str]:
    tips = []
    wind = day.get("windgusts_10m_max") or day.get("windspeed_10m_max") or 0
    if wind >= 62:
        tips.append("Gale-force winds likely — fishermen advised NOT to venture into the sea.")
    elif wind >= 40:
        tips.append("Rough sea conditions possible — exercise caution, small craft advisory.")
    else:
        tips.append("Sea conditions look moderate — normal precautions apply.")
    if alert["level"] in ("orange", "red"):
        tips.append("Monitor coastal warnings closely; conditions may deteriorate.")

    port = port_delay_risk(marine_day)
    if port["level"] not in ("unknown", "low"):
        tips.append(f"Port/loading advisory: {port['note']}")

    return tips


def urban_advisory(day: dict, alert: dict) -> list[str]:
    tips = []
    rain = day.get("precipitation_sum") or 0
    tmax = day.get("temperature_2m_max")
    if rain >= 64.5:
        tips.append("Waterlogging risk in low-lying areas — municipal drainage teams should be on standby.")
    if tmax is not None and tmax >= 40:
        tips.append("Activate heat-action-plan measures: hydration points, shade for outdoor workers.")
    if alert["level"] in ("orange", "red"):
        tips.append("Consider public alert dissemination via SMS/sirens for vulnerable localities.")
    if not tips:
        tips.append("No special civic measures indicated for today.")
    return tips


def safety_tips(day: dict, alert: dict) -> list[str]:
    """Cross-cutting public safety tips for urban/general users."""
    tips = []
    rain_prob = day.get("precipitation_probability_max") or 0
    tmax = day.get("temperature_2m_max") or 0
    gust = day.get("windgusts_10m_max") or 0
    if rain_prob >= 60:
        tips.append("Carry rain protection; avoid waterlogged underpasses if rainfall is heavy.")
    if tmax >= 40:
        tips.append("Extreme heat — hydrate, avoid outdoor work 12–16h, check on elderly neighbours.")
    elif tmax >= 36:
        tips.append("Hot day — limit midday exposure and drink water regularly.")
    if gust >= 60:
        tips.append("Strong gusts possible — secure loose outdoor objects and avoid weak structures.")
    if alert.get("level") in ("orange", "red"):
        tips.append("Official warning level elevated — follow IMD / local disaster management updates.")
    if not tips:
        tips.append("No special hazards flagged — normal outdoor activity is fine.")
    return tips


def fleet_route_advisory(day: dict, alert: dict) -> list[str]:
    """Weather-impacted route guidance for cab / logistics fleets.

    Designed so the server can later expand this into multi-route simulation
    while the client (ELD / dispatch) stays light.
    """
    tips = []
    rain = day.get("precipitation_sum") or 0
    rain_prob = day.get("precipitation_probability_max") or 0
    gust = day.get("windgusts_10m_max") or day.get("windspeed_10m_max") or 0
    code = day.get("weathercode")
    tmax = day.get("temperature_2m_max")

    # Visibility / fog (WMO codes 45, 48)
    if code is not None and int(code) in (45, 48):
        tips.append(
            "Driver alert: Low visibility (fog) expected — reduce speed, increase following distance, "
            "and prefer main arterial roads with better lighting."
        )
        tips.append("Dispatch: Prefer alternate routes that avoid low-lying fog-prone stretches and river valleys.")

    # Heavy rain / waterlogging risk
    if alert.get("level") in ("orange", "red") and "rainfall" in " ".join(alert.get("hazards") or []):
        tips.append(
            "Best route under rain: Avoid underpasses, known waterlogging pockets and low bridges. "
            "Suggest elevated or higher-drainage corridors."
        )
        tips.append("ETA impact: Expect 15–40% longer travel times on secondary roads; update passenger ETAs.")
    elif rain_prob >= 60 or rain >= 10:
        tips.append(
            "Rain likely — recommend alternate routes that stay on primary roads; "
            "watch for surface flooding after intense bursts."
        )

    # Wind / gusts / crosswind tipping risk
    crosswind = crosswind_risk(day)
    if crosswind["level"] in ("severe", "high", "moderate"):
        tips.append(crosswind["note"])

    # Heat (driver / vehicle stress)
    if tmax is not None and tmax >= 40:
        tips.append(
            "Extreme heat — schedule shorter continuous driving blocks, ensure AC is functional, "
            "and prioritise shaded parking for idle fleet."
        )

    # Generic fleet risk summary
    level = (alert.get("level") or "green").upper()
    tips.append(f"Fleet weather risk level for this area: {level} (IMD-style colour scale).")

    if not any("Driver alert" in t or "Best route" in t or "Rain likely" in t for t in tips):
        tips.insert(0, "Routes look manageable — normal driving with standard weather caution is fine.")

    return tips


def driver_eld_alerts(day: dict, alert: dict) -> list[str]:
    """Short, actionable push-style messages suitable for an ELD / in-cab display."""
    alerts_out = []
    code = day.get("weathercode")
    rain_prob = day.get("precipitation_probability_max") or 0
    gust = day.get("windgusts_10m_max") or day.get("windspeed_10m_max") or 0
    rain = day.get("precipitation_sum") or 0

    if code is not None and int(code) in (45, 48):
        alerts_out.append("Reduce speed: Low visibility (fog) predicted along your corridor.")
    if rain_prob >= 70 or rain >= 20:
        alerts_out.append("Heavy rain risk ahead — avoid underpasses; prefer main roads.")
    if gust >= 60:
        alerts_out.append("Strong gusts expected — reduce speed on bridges and open roads.")
    if alert.get("level") in ("orange", "red"):
        alerts_out.append(
            f"Official hazard level {alert['level'].upper()} — follow dispatch instructions and local advisories."
        )
    if not alerts_out:
        alerts_out.append("No critical driver hazard for the next few hours — drive normally with weather awareness.")
    return alerts_out
