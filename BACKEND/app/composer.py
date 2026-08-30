"""
Chat orchestration layer — the actual "conversational engine" of Weather Nova.

Pipeline for every message:
  1. Rule-based NLU parse (instant, offline).
  2. Optional LLM refinement of intent/location (if a key is configured).
  3. Resolve location -> lat/lon (geocoding, or client-supplied GPS coords).
  4. Pull forecast / alerts / historical data for that location.
  5. Build a factual summary + structured payload for the frontend.
  6. Optionally ask the LLM to phrase it naturally in the target language;
     otherwise use the pre-translated template.
"""
from __future__ import annotations

import asyncio

from . import advisory, alerts as alerts_mod, geocode, gis, i18n, llm, nlu, satellite, weather, wis2


async def _fast_reply(fallback_text: str, lang: str, user_question: str = "") -> str:
    """Prefer instant template replies for English; only call LLM for other languages or when needed."""
    if lang == "en" or not llm.llm_available():
        return fallback_text
    return await llm.phrase_reply(
        fallback_text, i18n.SUPPORTED.get(lang, {}).get("name", lang), fallback_text, user_question=user_question
    )



def _cyclone_map_payload(cyclones, region=None):
    for c in cyclones or []:
        if c.get("latest_lat") is not None and c.get("latest_lon") is not None:
            return {
                "lat": c["latest_lat"],
                "lon": c["latest_lon"],
                "label": c.get("name") or region or "storm",
                "zoom": 5,
            }
    return None



async def handle_message(
    text: str,
    lang: str = "en",
    client_lat: float | None = None,
    client_lon: float | None = None,
) -> dict:
    lang = lang if lang in i18n.SUPPORTED else "en"
    parsed = nlu.parse_query(text)

    # Fast path: trust rule NLU when it found a clear intent + location (skip slow LLM refine)
    use_llm_refine = llm.llm_available() and (
        parsed.intent in ("current", "greeting") or not parsed.location_text
    )
    if use_llm_refine:
        refined = await llm.refine_query_understanding(
            text,
            {
                "intent": parsed.intent,
                "location": parsed.location_text,
                "day_offset": parsed.day_offset,
                "horizon_days": parsed.horizon_days,
            },
        )
        intent = refined.get("intent", parsed.intent)
        location_text = refined.get("location") or parsed.location_text
        day_offset = int(refined.get("day_offset", parsed.day_offset) or 0)
        horizon_days = int(refined.get("horizon_days", parsed.horizon_days) or 7)
    else:
        intent = parsed.intent
        location_text = parsed.location_text
        day_offset = parsed.day_offset
        horizon_days = parsed.horizon_days

    if intent == "greeting":
        greet = {
            "en": "Namaste! I'm Weather Nova. Ask me about today's weather, a forecast, alerts, "
                  "advisories for farming, flying, fishing or your city, or fleet/route questions "
                  "(best route under rain, driver fog alerts, fleet weather risk) — in any Indian language.",
        }
        return {
            "reply": greet["en"],
            "lang": lang,
            "intent": intent,
            "data": None,
        }

    if intent == "help":
        help_text = (
            "I'm Weather Nova — ask me things like:\n"
            "• \"weather in Kolkata\" or \"forecast for Mumbai this week\"\n"
            "• \"will it rain tomorrow in Delhi?\" (umbrella advice)\n"
            "• \"any cyclone alerts near Chennai?\"\n"
            "• \"climate trend for Jaipur\"\n"
            "• sector questions — farming, aviation, marine, fleet/routing, "
            "solar/energy, retail, or construction weather risk\n"
            "Just name a place (or share your location) and ask in any Indian language."
        )
        reply = await _fast_reply(help_text, lang, user_question=text)
        return {
            "reply": reply,
            "lang": lang,
            "intent": intent,
            "data": None,
        }

    # Cyclone questions are answered from IMD/WIS2 feeds and do NOT require
    # a city. Detect early so we never fall through to "Which place…?".
    is_cyclone_query = intent == "alert" and any(
        w in text.lower()
        for w in (
            "cyclone", "cyclones", "चक्रवात", "ঘূর্ণিঝড়", "புயல்", "తుఫాను",
            "तूफान", "typhoon", "hurricane", "depression",
        )
    )

    if is_cyclone_query:
        # Support "cyclone near Chennai and Kolkata" -> one cyclone report per
        # named place, so two places asked in one message get two separate
        # yes/no answers instead of being merged into a single lookup.
        requested_locations = nlu.split_multi_location(location_text)
        if not requested_locations:
            requested_locations = [None]

        async def _cyclone_section(loc: str | None) -> tuple[str, dict]:
            region_label = loc or "the requested region"
            try:
                cyclones = await satellite.get_active_cyclones(region=loc)
            except Exception:
                cyclones = []
            mono = satellite.monsoon_status(region=loc)
            if cyclones:
                lines = []
                for c in cyclones[:5]:
                    name = c.get("name") or "Unnamed"
                    cat = c.get("category") or "tropical system"
                    msw = c.get("mean_msw_kmph")
                    kt = c.get("intensity_kt")
                    pos = ""
                    if c.get("latest_lat") is not None and c.get("latest_lon") is not None:
                        pos = f" | Position: {c['latest_lat']:.1f}°, {c['latest_lon']:.1f}°"
                    wind = ""
                    if msw:
                        wind = f" | Max winds ~{msw:.0f} km/h"
                        if kt:
                            wind += f" ({kt:.0f} kt)"
                    elif kt:
                        wind = f" | Intensity ~{kt:.0f} kt"
                    src = c.get("source") or ""
                    basin = c.get("basin") or ""
                    lines.append(f"• {name} — {cat}{wind}{pos} [{src}/{basin}]".replace("/]", "]"))
                section = (
                    f"Yes. Active tropical system(s) near {region_label}:\n"
                    + "\n".join(lines)
                    + f"\n\nSeasonal context: {mono['phase']}. {mono['tip']} "
                    + "Follow official advisories (IMD / PAGASA / JMA / NHC / JTWC)."
                )
            else:
                section = (
                    f"No active tropical cyclone is currently listed near {region_label} "
                    f"in the combined IMD + NHC + RAMMB/CIRA feeds. "
                    f"Seasonal context: {mono['phase']}. {mono['tip']}"
                )
            info = {
                "active_cyclones": cyclones,
                "region": region_label,
                "monsoon": mono,
                "map": _cyclone_map_payload(cyclones, region_label),
            }
            return section, info

        sections = []
        by_location = {}
        first_map = None
        multi = len(requested_locations) > 1
        for loc in requested_locations:
            section, info = await _cyclone_section(loc)
            key = loc or "region"
            sections.append(f"— {key.title()} —\n{section}" if multi else section)
            by_location[key] = info
            if first_map is None and info.get("map"):
                first_map = info["map"]

        reply = "\n\n".join(sections)
        data = {
            "data_source": "IMD + NHC CurrentStorms + RAMMB/CIRA TC realtime (+ WIS2 fallback)",
            "map": first_map,
        }
        if multi:
            data["by_location"] = by_location
        else:
            data.update(next(iter(by_location.values())))

        return {"reply": reply, "lang": lang, "intent": "alert", "data": data}


    # --- resolve location -------------------------------------------------
    place = None
    lat = lon = None
    if location_text:
        place = await geocode.resolve_location(location_text, language=lang)
        if place:
            lat, lon = place["latitude"], place["longitude"]
    # GPS fallback: use device location when the user did not name a place
    if (lat is None or lon is None) and client_lat is not None and client_lon is not None:
        lat, lon = client_lat, client_lon
        place = {"name": await geocode.reverse_label(lat, lon)}

    if lat is None or lon is None:
        # No usable location. Before giving up, if an LLM is configured, try
        # answering as a general weather/meteorology question.
        general = await llm.general_weather_answer(text, i18n.SUPPORTED[lang]["name"])
        if general:
            return {"reply": general, "lang": lang, "intent": intent, "data": None}
        return {
            "reply": i18n.t(i18n.NO_LOCATION_PROMPT, lang),
            "lang": lang,
            "intent": intent,
            "data": None,
            "needs_location": True,
        }

    if location_text and place is None and client_lat is None:
        general = await llm.general_weather_answer(text, i18n.SUPPORTED[lang]["name"])
        if general:
            return {"reply": general, "lang": lang, "intent": intent, "data": None}
        return {
            "reply": i18n.t(i18n.LOCATION_NOT_FOUND, lang),
            "lang": lang,
            "intent": intent,
            "data": None,
        }

    location_label = place.get("name") or location_text or "your location"
    if place.get("admin1"):
        location_label = f"{location_label}, {place['admin1']}"

    # Parallel: district GIS + forecast (faster response)
    district, forecast = await asyncio.gather(
        gis.lookup_district(lat, lon),
        weather.get_forecast(lat, lon, days=max(horizon_days, day_offset + 1)),
    )
    if forecast.get("error") == "rate_limited":
        return {
            "reply": (
                f"Weather models are briefly rate-limited. Please wait a few seconds and try again "
                f"for {place.get('name') if place else location_text or 'your location'}."
            ),
            "lang": lang,
            "intent": intent,
            "data": {"error": "rate_limited"},
        }
    daily = forecast.get("daily", {})
    timeline = alerts_mod.build_alert_timeline(daily)
    idx = min(day_offset, len(timeline) - 1) if timeline else 0

    day_data = {k: (v[idx] if idx < len(v) else None) for k, v in daily.items() if k != "time"}
    today_alert = timeline[idx] if timeline else {"level": "green", "hazards": []}
    current = forecast.get("current_weather", {})

    payload = {
        "location": location_label,
        "coordinates": {"lat": lat, "lon": lon},
        "district": district,
        "current": current,
        "day": day_data,
        "date": daily.get("time", [None])[idx] if daily.get("time") else None,
        "alert": today_alert,
        "alert_label": i18n.alert_label(today_alert["level"], lang),
        "timeline": timeline,
    }
    payload["map"] = {"lat": lat, "lon": lon, "label": location_label, "zoom": 8}

    # Attach satellite-informed cyclone status (IMD + WIS2 fallback)
    try:
        cyclones = await satellite.get_active_cyclones()
        if cyclones:
            payload["active_cyclones"] = cyclones
    except Exception:
        cyclones = []

    # --- build reply per intent --------------------------------------------
    if intent == "umbrella":
        # Precise rain / umbrella answer driven by ensemble precip probability
        # (satellite-assimilated NWP). Example:
        # "No. There is a 0% chance of rain tomorrow in Mumbai."
        rain_prob = day_data.get("precipitation_probability_max")
        precip_mm = day_data.get("precipitation_sum")
        advice = satellite.rain_advice(rain_prob, precip_mm)
        day_label = "today" if day_offset == 0 else ("tomorrow" if day_offset == 1 else f"in {day_offset} days")
        date_str = payload.get("date") or day_label

        fallback_text = (
            f"{advice['verdict']}. {advice['detail']} {day_label} in {location_label}. "
            f"{advice['tip']}"
        )
        # Strong deterministic reply so the user always gets a clear yes/no + % 
        # even when the optional LLM is offline or rephrases poorly.
        reply = fallback_text
        if lang != "en":
            # still try natural phrasing in the requested language
            reply = await llm.phrase_reply(
                fallback_text,
                i18n.SUPPORTED[lang]["name"],
                fallback_text,
                user_question=text,
            )
        payload["umbrella_advice"] = advice
        payload["data_source"] = (
            "Open-Meteo ensemble (GFS/ICON/…) — precipitation probability "
            "derived from models that assimilate satellite observations"
        )

    elif intent in ("current", "forecast"):
        condition = weather.weather_code_label(day_data.get("weathercode"))
        temp = current.get("temperature", day_data.get("temperature_2m_max"))
        fallback_text = i18n.t(i18n.CURRENT_TEMPLATE, lang).format(
            location=location_label,
            condition=condition,
            temp=round(temp, 1) if temp is not None else "—",
            tmin=round(day_data.get("temperature_2m_min", 0), 1),
            tmax=round(day_data.get("temperature_2m_max", 0), 1),
            rain_prob=day_data.get("precipitation_probability_max", 0),
            wind=round(day_data.get("windspeed_10m_max", 0), 1),
        )
        summary_for_llm = (
            f"Location: {location_label}. Condition: {condition}. "
            f"Current temp: {temp}C. Today's range: {day_data.get('temperature_2m_min')}-"
            f"{day_data.get('temperature_2m_max')}C. Rain chance: {day_data.get('precipitation_probability_max')}%. "
            f"Wind up to {day_data.get('windspeed_10m_max')} km/h. "
            f"Alert level: {today_alert['level']} ({', '.join(today_alert['hazards']) or 'no hazards'})."
        )
        if intent == "forecast":
            week_bits = []
            for day in timeline[: min(horizon_days, len(timeline))]:
                week_bits.append(f"{day['date']}: {day['level']} ({', '.join(day['hazards']) or 'normal'})")
            summary_for_llm += " Outlook: " + "; ".join(week_bits)
            payload["outlook"] = timeline[: horizon_days]

        reply = await llm.phrase_reply(summary_for_llm, i18n.SUPPORTED[lang]["name"], fallback_text, user_question=text)

    elif intent == "alert":
        if today_alert["level"] == "green":
            fallback_text = f"No significant weather warnings for {location_label} today ({i18n.alert_label('green', lang)})."
        else:
            fallback_text = (
                f"{i18n.alert_label(today_alert['level'], lang)} warning for {location_label}: "
                f"{', '.join(today_alert['hazards'])}."
            )
        # Enrich with any active cyclones from satellite / IMD feed
        if cyclones:
            names = ", ".join(c["name"] for c in cyclones[:3])
            fallback_text += f" Active cyclone(s) being monitored: {names}."
        summary_for_llm = fallback_text
        reply = await llm.phrase_reply(summary_for_llm, i18n.SUPPORTED[lang]["name"], fallback_text, user_question=text)
        payload["outlook"] = timeline
        live_bulletins = wis2.get_recent_bulletins(limit=3)
        if live_bulletins:
            payload["live_wis2_bulletins"] = live_bulletins

    elif intent == "climate":
        hist = await weather.get_historical_summary(lat, lon, years_back=10)
        trend = weather.summarize_yearly_trend(hist)
        payload["climate_trend"] = trend
        recent = trend[-5:] if len(trend) >= 5 else trend
        fallback_text = "10-year climate snapshot for {}: {}.".format(
            location_label,
            "; ".join(f"{r['year']} avg max {r['avg_max_temp_c']}°C, rain {r['total_rainfall_mm']}mm" for r in recent),
        )
        reply = await _fast_reply(fallback_text, lang, user_question=text)

    elif intent == "agriculture":
        tips = advisory.agriculture_advisory(day_data, today_alert)
        fallback_text = f"Farm advisory for {location_label}: " + " ".join(tips)
        payload["advisory"] = tips
        payload["pest_risk"] = advisory.pest_risk_index(day_data)
        reply = await _fast_reply(fallback_text, lang, user_question=text)

    elif intent == "aviation":
        hourly = forecast.get("hourly", {})
        tips = advisory.aviation_briefing(day_data, hourly, today_alert)
        fallback_text = f"Aviation briefing for {location_label}: " + " ".join(tips)
        payload["advisory"] = tips
        reply = await _fast_reply(fallback_text, lang, user_question=text)

    elif intent == "marine":
        # Real ocean-swell data from Open-Meteo's Marine API (returns nothing
        # useful for inland points, which port_delay_risk() reports as
        # "unknown" rather than inventing a number).
        marine_day = None
        try:
            marine_data = await weather.get_marine_forecast(lat, lon)
            marine_daily = marine_data.get("daily", {}) if not marine_data.get("error") else {}
            if marine_daily:
                marine_day = {k: (v[idx] if idx < len(v) else None) for k, v in marine_daily.items() if k != "time"}
        except Exception:
            marine_day = None
        tips = advisory.marine_advisory(day_data, today_alert, marine_day=marine_day)
        fallback_text = f"Marine advisory for {location_label}: " + " ".join(tips)
        payload["advisory"] = tips
        payload["port_delay_risk"] = advisory.port_delay_risk(marine_day)
        reply = await _fast_reply(fallback_text, lang, user_question=text)

    elif intent == "urban":
        tips = advisory.urban_advisory(day_data, today_alert)
        tips = tips + advisory.safety_tips(day_data, today_alert)
        fallback_text = f"City advisory for {location_label}: " + " ".join(tips)
        payload["advisory"] = tips
        reply = await _fast_reply(fallback_text, lang, user_question=text)

    elif intent == "fleet":
        route_tips = advisory.fleet_route_advisory(day_data, today_alert)
        eld_tips = advisory.driver_eld_alerts(day_data, today_alert)
        tips = route_tips + ["— Driver ELD alerts —"] + eld_tips
        fallback_text = (
            f"Fleet / route weather guidance for {location_label}: "
            + " ".join(route_tips)
            + " Driver alerts: "
            + " ".join(eld_tips)
        )
        payload["advisory"] = tips
        payload["driver_eld_alerts"] = eld_tips
        payload["route_guidance"] = route_tips
        payload["crosswind_risk"] = advisory.crosswind_risk(day_data)
        reply = await _fast_reply(fallback_text, lang, user_question=text)

    elif intent == "energy":
        # Real Open-Meteo shortwave radiation + 80m wind speed — a genuine
        # NWP-derived outlook, not a GraphCast/Prithvi-WxC generation model
        # (running those requires GPU infrastructure this environment doesn't have).
        try:
            energy_data = await weather.get_energy_forecast(lat, lon)
            hourly_energy = energy_data.get("hourly", {}) if not energy_data.get("error") else {}
        except Exception:
            hourly_energy = {}
        summary = advisory.energy_forecast_summary(hourly_energy)
        fallback_text = (
            f"48-hour energy outlook for {location_label}: {summary['solar_outlook']} "
            f"(avg shortwave radiation ~{summary['avg_shortwave_radiation_wm2']} W/m²). "
            f"Wind: {summary['wind_outlook']} (avg ~{summary['avg_windspeed_80m_kmh']} km/h at 80 m)."
        )
        payload["energy_forecast"] = summary
        payload["data_source"] = "Open-Meteo hourly shortwave radiation + 80m wind speed (real NWP data)"
        reply = await _fast_reply(fallback_text, lang, user_question=text)

    elif intent == "retail":
        tips = advisory.retail_advisory(today_alert, timeline)
        fallback_text = f"Retail/inventory advisory for {location_label}: " + " ".join(tips)
        payload["advisory"] = tips
        reply = await _fast_reply(fallback_text, lang, user_question=text)

    elif intent == "construction":
        tips = advisory.construction_advisory(day_data, today_alert)
        fallback_text = f"Construction site advisory for {location_label}: " + " ".join(tips)
        payload["advisory"] = tips
        reply = await _fast_reply(fallback_text, lang, user_question=text)

    else:
        # Rule-based NLU has no dedicated handler for this intent (or the
        # message doesn't look like a structured weather query at all) —
        # last resort before giving up is to let Gemini (or whichever LLM
        # is configured) take a direct shot at it, so "any other statement"
        # still gets a real answer instead of a canned prompt.
        general = await llm.general_weather_answer(text, i18n.SUPPORTED[lang]["name"])
        reply = general if general else i18n.t(i18n.NO_LOCATION_PROMPT, lang)

    if payload is not None and "data_source" not in payload:
        payload["data_source"] = (
            "Open-Meteo ensemble NWP (satellite-assimilated) · IMD colour alerts · WIS2.0"
        )
    return {"reply": reply, "lang": lang, "intent": intent, "data": payload}
