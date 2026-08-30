"""
Phone + OTP login system.

Why OTP-over-SMS instead of username/password: this app already has a
Twilio SMS pipe (app/sms.py) for cyclone/weather alerts, and the whole
point of logging in is "so alerts can be sent to *you*" — so verifying the
phone number IS the login. No passwords to store or leak.

Flow:
  1. POST /api/auth/request-otp {phone}   -> generates a 6-digit code,
     stores it (hashed) with a 5-minute expiry, sends it via SMS.
  2. POST /api/auth/verify-otp {phone, otp} -> on match, issues a signed
     session token (phone + expiry + HMAC signature). No JWT library
     needed — it's the same idea, hand-rolled with stdlib hmac/hashlib so
     no new dependency is required.
  3. Every subsequent request that should be tied to "this phone" (e.g.
     managing cyclone-alert subscriptions) sends `Authorization: Bearer
     <token>`; `require_session()` verifies the signature + expiry.

Storage is a small JSON file (consistent with subscriptions.py) — swap for
a real table if this needs to scale past a few thousand users.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import random
import threading
import time
from typing import Optional

from fastapi import Header, HTTPException

SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-insecure-secret-change-me")
OTP_TTL_SECONDS = int(os.getenv("OTP_TTL_SECONDS", "300"))          # 5 minutes
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(30 * 24 * 3600)))  # 30 days
OTP_MAX_ATTEMPTS = 5

USERS_PATH = os.getenv("USERS_PATH", os.path.join(os.path.dirname(__file__), "..", "users.json"))

_lock = threading.Lock()
_otp_store: dict[str, dict] = {}  # phone -> {hash, expires_at, attempts}


def _normalize_phone(phone: str) -> str:
    phone = (phone or "").strip().replace(" ", "")
    if phone and not phone.startswith("+"):
        # Best-effort default to India country code, since this is an IMD-
        # focused app; callers can always pass a full "+<cc><number>".
        phone = "+91" + phone.lstrip("0")
    return phone


def _hash_otp(phone: str, otp: str) -> str:
    return hashlib.sha256(f"{phone}:{otp}:{SESSION_SECRET}".encode()).hexdigest()


def generate_otp(phone: str) -> str:
    phone = _normalize_phone(phone)
    otp = f"{random.randint(0, 999999):06d}"
    with _lock:
        _otp_store[phone] = {
            "hash": _hash_otp(phone, otp),
            "expires_at": time.time() + OTP_TTL_SECONDS,
            "attempts": 0,
        }
    return otp


def verify_otp(phone: str, otp: str) -> bool:
    phone = _normalize_phone(phone)
    with _lock:
        entry = _otp_store.get(phone)
        if not entry:
            return False
        if time.time() > entry["expires_at"]:
            _otp_store.pop(phone, None)
            return False
        entry["attempts"] += 1
        if entry["attempts"] > OTP_MAX_ATTEMPTS:
            _otp_store.pop(phone, None)
            return False
        ok = hmac.compare_digest(entry["hash"], _hash_otp(phone, otp))
        if ok:
            _otp_store.pop(phone, None)
            _remember_user(phone)
        return ok


def _load_users() -> dict:
    if not os.path.exists(USERS_PATH):
        return {}
    try:
        with open(USERS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _remember_user(phone: str) -> None:
    with _lock:
        users = _load_users()
        users[phone] = {"phone": phone, "last_login": time.time()}
        with open(USERS_PATH, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2)


# --- signed session tokens (hand-rolled, JWT-shaped, no extra dependency) --
def issue_token(phone: str) -> str:
    phone = _normalize_phone(phone)
    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    payload = f"{phone}|{expires_at}"
    sig = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}|{sig}"


def _verify_token(token: str) -> Optional[str]:
    try:
        phone, expires_at, sig = token.split("|")
    except ValueError:
        return None
    payload = f"{phone}|{expires_at}"
    expected = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    if int(expires_at) < time.time():
        return None
    return phone


async def require_session(authorization: str | None = Header(default=None)) -> str:
    """FastAPI dependency: raises 401 if missing/invalid, else returns the
    logged-in phone number."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Login required. Send Authorization: Bearer <token>.")
    token = authorization.split(" ", 1)[1].strip()
    phone = _verify_token(token)
    if not phone:
        raise HTTPException(status_code=401, detail="Session expired or invalid. Please log in again.")
    return phone
