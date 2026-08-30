"""
Live WIS2.0 ingestion.

WIS2.0 (WMO Information System 2.0) is the successor to the old GTS network:
national met services publish data-availability notifications over MQTT to a
"WIS2 Global Broker", and anyone can subscribe for free. This module
connects to the real public Global Broker operated by Météo-France
(`globalbroker.meteo.fr`, TLS port 8883, username/password `everyone`) and
subscribes to the cyclone-track forecast topic across all WIS2 centres using
the `+` wildcard, per WMO's published WIS2 Cookbook.

Reference topic hierarchy (WMO Unified Data Policy, Annex 1):
    cache/a/wis2/<centre-id>/data/core/weather/prediction/forecast/cyclone_tracks

This is genuinely live data — not a simulation — but it depends on outbound
network access to port 8883 and on some WIS2 centre actively publishing at
any given moment, so the ingestion degrades gracefully (empty bulletin list)
rather than breaking the app when neither is available, e.g. on a locked-down
hackathon Wi-Fi.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from collections import deque
from datetime import datetime, timezone

logger = logging.getLogger("wis2")

WIS2_ENABLE = os.getenv("WIS2_ENABLE", "true").lower() in ("1", "true", "yes")
WIS2_BROKER_HOST = os.getenv("WIS2_BROKER_HOST", "globalbroker.meteo.fr")
WIS2_BROKER_PORT = int(os.getenv("WIS2_BROKER_PORT", "8883"))
WIS2_USERNAME = os.getenv("WIS2_USERNAME", "everyone")
WIS2_PASSWORD = os.getenv("WIS2_PASSWORD", "everyone")
WIS2_TOPIC = os.getenv(
    "WIS2_TOPIC",
    "cache/a/wis2/+/data/core/weather/prediction/forecast/cyclone_tracks",
)

_bulletins: deque = deque(maxlen=50)
_lock = threading.Lock()
_client = None
_status = {"connected": False, "last_error": None}


def _on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        logger.info("WIS2: connected to %s", WIS2_BROKER_HOST)
        _status["connected"] = True
        _status["last_error"] = None
        client.subscribe(WIS2_TOPIC)
    else:
        _status["connected"] = False
        _status["last_error"] = f"connect failed: {reason_code}"
        logger.warning("WIS2: connect failed: %s", reason_code)


def _on_disconnect(client, userdata, *args):
    _status["connected"] = False


def _on_message(client, userdata, message):
    try:
        payload = json.loads(message.payload.decode("utf-8"))
    except Exception:
        return

    props = payload.get("properties", {})
    links = payload.get("links", [])
    canonical = next((l.get("href") for l in links if l.get("rel") == "canonical"), None)

    entry = {
        "topic": message.topic,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "wigos_station_identifier": props.get("wigos_station_identifier"),
        "data_id": props.get("data_id"),
        "datetime": props.get("datetime") or props.get("pubtime"),
        "canonical_link": canonical,
    }
    with _lock:
        _bulletins.appendleft(entry)


def start_listener() -> None:
    """Start the background MQTT listener thread. Safe to call once at
    application startup. No-ops if WIS2_ENABLE=false or paho-mqtt / network
    access is unavailable.
    """
    global _client
    if not WIS2_ENABLE:
        logger.info("WIS2: disabled via WIS2_ENABLE=false")
        return
    try:
        from paho.mqtt import client as mqtt_client
    except ImportError:
        logger.warning("WIS2: paho-mqtt not installed, skipping live ingestion")
        _status["last_error"] = "paho-mqtt not installed"
        return

    try:
        client = mqtt_client.Client(
            mqtt_client.CallbackAPIVersion.VERSION2, client_id="weathergpt-" + os.urandom(3).hex()
        )
        client.username_pw_set(WIS2_USERNAME, WIS2_PASSWORD)
        client.tls_set(tls_version=2)
        client.on_connect = _on_connect
        client.on_disconnect = _on_disconnect
        client.on_message = _on_message
        client.connect_async(WIS2_BROKER_HOST, WIS2_BROKER_PORT, keepalive=60)
        client.loop_start()
        _client = client
        logger.info("WIS2: listener starting (%s:%s, topic=%s)", WIS2_BROKER_HOST, WIS2_BROKER_PORT, WIS2_TOPIC)
    except Exception as exc:
        logger.warning("WIS2: could not start listener: %s", exc)
        _status["last_error"] = str(exc)


def stop_listener() -> None:
    global _client
    if _client is not None:
        try:
            _client.loop_stop()
            _client.disconnect()
        except Exception:
            pass
        _client = None


def get_recent_bulletins(limit: int = 10) -> list[dict]:
    with _lock:
        return list(_bulletins)[:limit]


def get_status() -> dict:
    return {
        "enabled": WIS2_ENABLE,
        "broker": WIS2_BROKER_HOST,
        "topic": WIS2_TOPIC,
        "connected": _status["connected"],
        "last_error": _status["last_error"],
        "bulletins_buffered": len(_bulletins),
    }
