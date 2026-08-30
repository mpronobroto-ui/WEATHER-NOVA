"""
Weather Nova Backend — FastAPI entry point.

This is what `uvicorn main:app` actually boots. It wires together every
module under app/ (nlu, composer, weather, alerts, geocode, gis, i18n, llm,
satellite, sms, subscriptions, wis2) behind a small set of REST endpoints
that FRONTEND/index.html already calls:

    GET  /api/health         -> liveness check
    GET  /api/languages      -> supported languages for the language picker
    GET  /api/status         -> integration status strip (WIS2 / LLM / SMS)
    POST /api/chat           -> the main conversational endpoint
    WS   /ws/chat            -> same conversation, over a websocket

Plus the subscription + alert-dispatch endpoints described in DEMO.md /
ARCHITECTURE.md for the SMS early-warning feature.
"""
from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv

# Must run BEFORE `from app import ...` below — several app modules (llm.py,
# sms.py, auth.py, wis2.py) read os.getenv(...) at *import time* to set
# module-level constants like GEMINI_API_KEY. If .env is loaded any later
# than this, those constants are already frozen as None/empty and the key
# is silently ignored for the lifetime of the process.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import auth, composer, gis, i18n, llm, sms, subscriptions, wis2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("weathergpt")

app = FastAPI(title="Weather Nova API", version="1.0.0")

# The frontend is served separately (nginx on :8080 in docker-compose, or a
# plain `python -m http.server` while developing) so CORS must be open.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    lang: str = "en"
    lat: float | None = None
    lon: float | None = None


class SubscribeRequest(BaseModel):
    lat: float
    lon: float
    lang: str = "en"
    label: str | None = None
    cyclone_alerts: bool = True


class RequestOtpRequest(BaseModel):
    phone: str


class VerifyOtpRequest(BaseModel):
    phone: str
    otp: str


# ---------------------------------------------------------------------------
# Lifecycle — start/stop the optional WIS2.0 MQTT listener with the app
# ---------------------------------------------------------------------------
_dispatch_task: asyncio.Task | None = None
DISPATCH_INTERVAL_SECONDS = int(os.getenv("ALERT_DISPATCH_INTERVAL_SECONDS", "3600"))


async def _dispatch_loop() -> None:
    """Periodically re-checks every subscriber against the live weather-alert
    level AND the live cyclone list, texting anyone newly in range. Runs
    only while at least one Twilio credential is set; otherwise it's a
    harmless no-op loop (dispatch_* already degrade gracefully with
    skipped_no_credentials=True)."""
    while True:
        try:
            await sms.dispatch_alerts()
            await sms.dispatch_cyclone_alerts()
        except Exception as exc:
            logger.warning("Scheduled alert dispatch failed: %s", exc)
        await asyncio.sleep(DISPATCH_INTERVAL_SECONDS)


@app.on_event("startup")
async def on_startup() -> None:
    global _dispatch_task
    try:
        wis2.start_listener()
    except Exception as exc:
        logger.warning("WIS2 listener failed to start: %s", exc)
    if sms.sms_configured():
        _dispatch_task = asyncio.create_task(_dispatch_loop())


@app.on_event("shutdown")
async def on_shutdown() -> None:
    try:
        wis2.stop_listener()
    except Exception:
        pass
    if _dispatch_task:
        _dispatch_task.cancel()


# ---------------------------------------------------------------------------
# Health / meta endpoints
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/languages")
async def languages() -> dict:
    return i18n.SUPPORTED


@app.get("/api/status")
async def status() -> dict:
    return {
        "integrations": {
            "wis2_mqtt": wis2.get_status(),
            "llm": {"status": "enabled" if llm.llm_available() else "disabled"},
            "sms_twilio": {"status": "configured" if sms.sms_configured() else "not_configured"},
            "gis": {"status": "available" if await gis.gis_available() else "unavailable"},
        }
    }


# ---------------------------------------------------------------------------
# Core conversational endpoint
# ---------------------------------------------------------------------------
@app.post("/api/chat")
async def chat(req: ChatRequest) -> dict:
    return await composer.handle_message(
        req.message,
        lang=req.lang,
        client_lat=req.lat,
        client_lon=req.lon,
    )


@app.websocket("/ws/chat")
async def chat_ws(ws: WebSocket) -> None:
    await ws.accept()
    try:
        while True:
            payload = await ws.receive_json()
            result = await composer.handle_message(
                payload.get("message", ""),
                lang=payload.get("lang", "en"),
                client_lat=payload.get("lat"),
                client_lon=payload.get("lon"),
            )
            await ws.send_json(result)
    except WebSocketDisconnect:
        pass


# ---------------------------------------------------------------------------
# Login — phone number + OTP (no password to store; verifying the phone IS
# the login, since the whole point is "so alerts can reach you").
# ---------------------------------------------------------------------------
@app.post("/api/auth/request-otp")
async def request_otp(req: RequestOtpRequest) -> dict:
    if not req.phone or len(req.phone.strip()) < 6:
        raise HTTPException(status_code=400, detail="Enter a valid phone number.")
    otp = auth.generate_otp(req.phone)
    if sms.sms_configured():
        sent = await sms._send_sms(auth._normalize_phone(req.phone), f"Your Weather Nova login code is {otp}. It expires in 5 minutes.")
        return {"sent": sent, "channel": "sms"}
    # No Twilio configured (e.g. local dev) — return the code directly so
    # the flow is still testable instead of dead-ending.
    logger.info("SMS not configured — dev OTP for %s is %s", req.phone, otp)
    return {"sent": False, "channel": "dev", "dev_otp": otp}


@app.post("/api/auth/verify-otp")
async def verify_otp(req: VerifyOtpRequest) -> dict:
    if not auth.verify_otp(req.phone, req.otp):
        raise HTTPException(status_code=401, detail="Incorrect or expired code.")
    phone = auth._normalize_phone(req.phone)
    token = auth.issue_token(phone)
    return {"token": token, "phone": phone}


@app.get("/api/auth/me")
async def me(phone: str = Depends(auth.require_session)) -> dict:
    return {"phone": phone, "subscription": subscriptions.get_subscription(phone)}


# ---------------------------------------------------------------------------
# SMS early-warning subscriptions (requires login — Authorization: Bearer)
# ---------------------------------------------------------------------------
@app.post("/api/subscribe")
async def subscribe(req: SubscribeRequest, phone: str = Depends(auth.require_session)) -> dict:
    return subscriptions.add_subscription(
        phone, req.lat, req.lon, lang=req.lang, label=req.label, cyclone_alerts=req.cyclone_alerts
    )


@app.delete("/api/subscribe")
async def unsubscribe(phone: str = Depends(auth.require_session)) -> dict:
    removed = subscriptions.remove_subscription(phone)
    return {"removed": removed}


@app.get("/api/subscriptions")
async def get_subscriptions(phone: str = Depends(auth.require_session)) -> dict:
    # Only the logged-in user's own subscription — not everyone's.
    return subscriptions.get_subscription(phone) or {}


@app.post("/api/alerts/dispatch")
async def dispatch_alerts() -> dict:
    weather_result = await sms.dispatch_alerts()
    cyclone_result = await sms.dispatch_cyclone_alerts()
    return {"weather_alerts": weather_result, "cyclone_alerts": cyclone_result}
