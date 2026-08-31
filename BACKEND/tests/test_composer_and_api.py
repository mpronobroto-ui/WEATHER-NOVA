import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from app import composer


@pytest.mark.asyncio
async def test_composer_greeting():
    res = await composer.handle_message("hello")
    assert res["intent"] == "greeting"
    assert "Namaste" in res["reply"] or "Weather Nova" in res["reply"]


@pytest.mark.asyncio
async def test_composer_help():
    res = await composer.handle_message("help")
    assert res["intent"] == "help"
    assert "Weather Nova" in res["reply"]


@pytest.mark.asyncio
async def test_composer_digha():
    res = await composer.handle_message("weather of digha")
    assert res["intent"] in ("current", "forecast")
    assert res["data"] is not None
    assert "Digha" in res["data"]["location"]
    # Check that real numbers are returned
    day = res["data"]["day"]
    assert day.get("temperature_2m_max") is not None
    assert day.get("temperature_2m_min") is not None
    assert day.get("precipitation_probability_max") is not None
    assert "°C" in res["reply"]


@pytest.mark.asyncio
async def test_composer_kalighat():
    res = await composer.handle_message("weather of kalighat")
    assert res["intent"] in ("current", "forecast")
    assert res["data"] is not None
    assert "Kalighat" in res["data"]["location"]
    day = res["data"]["day"]
    assert day.get("temperature_2m_max") is not None


@pytest.mark.asyncio
async def test_composer_dakshineswar():
    res = await composer.handle_message("weather of dakshineswar")
    assert res["intent"] in ("current", "forecast")
    assert res["data"] is not None
    assert "Dakshineswar" in res["data"]["location"]
    day = res["data"]["day"]
    assert day.get("temperature_2m_max") is not None
    assert "°C" in res["reply"]


@pytest.mark.asyncio
async def test_api_health_and_languages():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r_health = await ac.get("/api/health")
        assert r_health.status_code == 200
        assert r_health.json() == {"status": "ok"}

        r_langs = await ac.get("/api/languages")
        assert r_langs.status_code == 200
        langs = r_langs.json()
        assert "en" in langs
        assert "hi" in langs
        assert "bn" in langs


@pytest.mark.asyncio
async def test_api_chat_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r_chat = await ac.post("/api/chat", json={"message": "weather in Kolkata", "lang": "en"})
        assert r_chat.status_code == 200
        data = r_chat.json()
        assert "reply" in data
        assert data["data"] is not None
        assert "Kolkata" in data["data"]["location"]
