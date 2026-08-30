"""
Early-warning dissemination — SMS today, Cell-Broadcast-ready architecture.

The brief calls for "extreme weather alerts and early warning dissemination"
reaching people beyond the chat window — critical for rural users without a
smartphone open at the right moment. This module sends real SMS via
Twilio's REST API (no SDK dependency, just httpx) to everyone subscribed
near a hazardous location.

True Cell Broadcast (the SMS-like blast IMD/NDMA use for cyclone warnings,
via India's SACHET / Common Alerting Protocol gateway) requires a signed
agreement with a telecom's Cell Broadcast Centre — not something any app can
call directly. `dispatch_alerts()` is exactly the seam where that would
plug in: replace `_send_sms()` with a CAP-formatted POST to a CBC/SACHET
gateway and every subscriber in this file starts receiving Cell Broadcast
warnings instead of / in addition to SMS, with no other code changes.

Degrades gracefully: with no Twilio credentials set, `dispatch_alerts()`
still evaluates every subscriber's alert level (useful for testing / for the
`/api/alerts/dispatch` endpoint's dry-run response) but skips the actual
send and reports it was skipped.
"""
from __future__ import annotations

import logging
import math
import os

import httpx

from . import alerts as alerts_mod
from . import i18n, satellite, subscriptions, weather

logger = logging.getLogger("sms")

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")

DISPATCH_MIN_LEVEL = os.getenv("ALERT_DISPATCH_MIN_LEVEL", "orange")  # orange or red
_LEVEL_RANK = {"green": 0, "yellow": 1, "orange": 2, "red": 3}

# A subscriber gets a cyclone SMS once an active storm's centre comes within
# this radius of their saved location. Default 100km — a tight, closer-to-
# landfall warning radius (raise it via CYCLONE_ALERT_RADIUS_KM if you want
# earlier/wider warnings).
CYCLONE_ALERT_RADIUS_KM = float(os.getenv("CYCLONE_ALERT_RADIUS_KM", "100"))


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def sms_configured() -> bool:
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER)


async def _send_sms(to_phone: str, body: str) -> bool:
    if not sms_configured():
        return False
    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    data = {"From": TWILIO_FROM_NUMBER, "To": to_phone, "Body": body}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(url, data=data, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
            return resp.status_code < 300
        except Exception as exc:
            logger.warning("SMS send failed to %s: %s", to_phone, exc)
            return False


async def dispatch_alerts() -> dict:
    """Check every subscriber's location; send an SMS warning to anyone
    whose area is at/above DISPATCH_MIN_LEVEL today. Returns a summary dict
    (used by the /api/alerts/dispatch endpoint and the background task).
    """
    subs = subscriptions.list_subscriptions()
    results = {"checked": 0, "warned": 0, "sent": 0, "skipped_no_credentials": not sms_configured(), "details": []}

    for sub in subs:
        results["checked"] += 1
        try:
            forecast = await weather.get_forecast(sub["lat"], sub["lon"], days=1)
            timeline = alerts_mod.build_alert_timeline(forecast.get("daily", {}))
            today = timeline[0] if timeline else {"level": "green", "hazards": []}
        except Exception as exc:
            results["details"].append({"phone": sub["phone"], "error": str(exc)})
            continue

        if _LEVEL_RANK.get(today["level"], 0) >= _LEVEL_RANK.get(DISPATCH_MIN_LEVEL, 2):
            results["warned"] += 1
            lang = sub.get("lang", "en")
            label = i18n.alert_label(today["level"], lang)
            hazards = ", ".join(today["hazards"]) or "severe weather"
            body = f"WeatherGPT alert [{label}]: {hazards} expected near your location today. Stay safe."
            sent = await _send_sms(sub["phone"], body)
            if sent:
                results["sent"] += 1
            results["details"].append({"phone": sub["phone"], "level": today["level"], "hazards": today["hazards"], "sms_sent": sent})

    return results


async def dispatch_cyclone_alerts() -> dict:
    """Check every subscriber who opted into cyclone_alerts against the
    live IMD + NHC + RAMMB/CIRA storm list; SMS anyone within
    CYCLONE_ALERT_RADIUS_KM of an active storm's current centre. Only fires
    an SMS the first time a given (phone, storm name) pair goes into range
    this run — call this on a timer (see main.py startup loop).
    """
    subs = [s for s in subscriptions.list_subscriptions() if s.get("cyclone_alerts", True)]
    results = {"checked": 0, "warned": 0, "sent": 0, "skipped_no_credentials": not sms_configured(), "details": []}
    if not subs:
        return results

    try:
        storms = await satellite.get_active_cyclones()
    except Exception as exc:
        results["error"] = str(exc)
        return results

    tracked = [s for s in storms if s.get("latest_lat") is not None and s.get("latest_lon") is not None]

    for sub in subs:
        results["checked"] += 1
        nearby = []
        for storm in tracked:
            dist = _haversine_km(sub["lat"], sub["lon"], storm["latest_lat"], storm["latest_lon"])
            if dist <= CYCLONE_ALERT_RADIUS_KM:
                nearby.append((storm, round(dist)))
        if not nearby:
            continue
        results["warned"] += 1
        lang = sub.get("lang", "en")
        names = ", ".join(f"{s['name']} (~{d}km away)" for s, d in nearby[:3])
        body = f"Weather Nova cyclone alert: active storm(s) near your saved location — {names}. Follow official IMD/PAGASA/NHC advisories."
        sent = await _send_sms(sub["phone"], body)
        if sent:
            results["sent"] += 1
        results["details"].append({
            "phone": sub["phone"],
            "storms": [{"name": s["name"], "distance_km": d} for s, d in nearby],
            "sms_sent": sent,
        })

    return results
