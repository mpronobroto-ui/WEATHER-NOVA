"""
Optional LLM-in-the-loop layer.

The platform works fully offline-of-LLM using nlu.py's rule engine (so the
demo never breaks for want of an API key). If any of the environment
variables below are set, this module additionally asks a real LLM to
(a) double-check/refine intent+location extraction and (b) rephrase the
final answer more conversationally / in a requested regional language it
wasn't explicitly templated for. This mirrors how a production Weather Nova
would plug into OpenAI / Llama / Gemini per the suggested tech stack.

Supported (set ONE of these):
  OPENAI_API_KEY        -> uses OpenAI-compatible /v1/chat/completions
  GEMINI_API_KEY         -> uses Gemini generateContent REST endpoint
  OLLAMA_URL              -> e.g. http://localhost:11434 for a local Llama model
"""
from __future__ import annotations

import json
import logging
import os
import httpx

logger = logging.getLogger("llm")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
OLLAMA_URL = os.getenv("OLLAMA_URL")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")


def llm_available() -> bool:
    return bool(OPENAI_API_KEY or GEMINI_API_KEY or OLLAMA_URL)


async def _call_openai(prompt: str) -> str | None:
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    body = {"model": OPENAI_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}
    async with httpx.AsyncClient(timeout=6.0) as client:
        try:
            r = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.warning("OpenAI call failed: %s", exc)
            return None


async def _call_gemini(prompt: str) -> str | None:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.post(url, json=body)
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except httpx.HTTPStatusError as exc:
            # Surface WHY it failed (bad key, revoked key, wrong model name,
            # quota) instead of silently falling back — this is the single
            # most common cause of "I added the key but nothing changed".
            logger.warning("Gemini call failed: HTTP %s — %s", exc.response.status_code, exc.response.text[:300])
            return None
        except Exception as exc:
            logger.warning("Gemini call failed: %s", exc)
            return None


async def _call_ollama(prompt: str) -> str | None:
    async with httpx.AsyncClient(timeout=8.0) as client:
        try:
            r = await client.post(
                f"{OLLAMA_URL.rstrip('/')}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            )
            r.raise_for_status()
            return r.json().get("response")
        except Exception:
            return None


async def ask_llm(prompt: str) -> str | None:
    if OPENAI_API_KEY:
        return await _call_openai(prompt)
    if GEMINI_API_KEY:
        return await _call_gemini(prompt)
    if OLLAMA_URL:
        return await _call_ollama(prompt)
    return None


async def refine_query_understanding(raw_text: str, fallback: dict) -> dict:
    """Ask the LLM to extract {intent, location, day_offset, horizon_days}.
    Falls back to the rule-engine result on any failure or if no LLM is configured.
    """
    if not llm_available():
        return fallback

    prompt = (
        "Extract weather-query intent from the user's message, which may be in English or any "
        "Indian language (Hindi, Bengali, Tamil, Telugu, Marathi, Gujarati, Punjabi, Kannada, "
        "Malayalam, Odia, Urdu) and may contain spelling mistakes or transliteration. "
        "Return STRICT JSON only, no prose, no markdown fences, with keys: "
        'intent (one of: current, forecast, alert, climate, agriculture, aviation, marine, urban, fleet, greeting), '
        "location (the place name mentioned, in English/romanized form, or null if none is mentioned), "
        "day_offset (integer, 0=today, 1=tomorrow, etc.), horizon_days (integer 1-16, how many days of "
        "outlook are being asked for; default 7 if unclear).\n\n"
        f"User message: {raw_text!r}"
    )
    raw = await ask_llm(prompt)
    if not raw:
        return fallback
    try:
        cleaned = raw.strip().strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        parsed = json.loads(cleaned)
        merged = dict(fallback)
        merged.update({k: v for k, v in parsed.items() if v not in (None, "")})
        return merged
    except Exception:
        return fallback


async def phrase_reply(context_summary: str, lang_name: str, fallback_text: str, user_question: str | None = None) -> str:
    """Ask the LLM to turn a factual summary into a natural, directly-relevant
    answer in the target language. Falls back to the template-generated text
    if no LLM is configured or the call fails.
    """
    if not llm_available():
        return fallback_text

    question_line = f'The user actually asked: "{user_question}"\n' if user_question else ""
    prompt = (
        f"You are Weather Nova — respond like Google Gemini: clear, friendly, structured, and accurate. {question_line}"
        f"Using ONLY the verified weather data below, write a natural answer in {lang_name} "
        "(short paragraphs or bullets OK, max ~120 words). "
        "Keep every number, %, date, and place EXACTLY as given — never invent temperatures, storm names, or wind speeds. "
        "Add at most one practical tip that follows directly from the data "
        "(umbrella, heat safety, travel caution).\n\n"
        "Verified data:\n" + context_summary
    )
    result = await ask_llm(prompt)
    return result.strip() if result else fallback_text


async def general_weather_answer(user_question: str, lang_name: str) -> str | None:
    """For questions that don't need a specific location (e.g. 'why does it
    rain more during monsoon', 'what is a heat wave') — answer directly from
    the model's general meteorology knowledge. Returns None if no LLM is
    configured, so the caller can fall back to asking for a location.
    """
    if not llm_available():
        return None
    prompt = (
        "You are Weather Nova with a Gemini-like conversational style: warm, precise, and helpful. "
        f"Answer in {lang_name} in 3–8 clear sentences. Explain weather/climate concepts simply. "
        "If a specific place is required and missing, ask for the city/region in the same language. "
        "Do not invent live storm names or current temperatures — say when the user should check a live forecast.\n\n"
        f"Question: {user_question}"
    )
    result = await ask_llm(prompt)
    return result.strip() if result else None
