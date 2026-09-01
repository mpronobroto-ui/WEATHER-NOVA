from app import alerts, advisory, satellite


def test_evaluate_day_green():
    day = {
        "precipitation_sum": 0.0,
        "precipitation_probability_max": 10,
        "windspeed_10m_max": 15.0,
        "temperature_2m_max": 30.0,
        "temperature_2m_min": 20.0,
        "weathercode": 1,
    }
    res = alerts.evaluate_day(day)
    assert res["level"] == "green"
    assert len(res["hazards"]) == 0


def test_evaluate_day_red_rainfall():
    day = {
        "precipitation_sum": 210.0,
        "precipitation_probability_max": 95,
        "windspeed_10m_max": 20.0,
        "temperature_2m_max": 28.0,
        "temperature_2m_min": 24.0,
        "weathercode": 65,
    }
    res = alerts.evaluate_day(day)
    assert res["level"] == "red"
    assert any("flood" in h or "heavy rainfall" in h for h in res["hazards"])


def test_evaluate_day_heat_wave():
    day = {
        "precipitation_sum": 0.0,
        "precipitation_probability_max": 0,
        "windspeed_10m_max": 10.0,
        "temperature_2m_max": 46.0,
        "temperature_2m_min": 32.0,
        "weathercode": 0,
    }
    res = alerts.evaluate_day(day)
    assert res["level"] == "red"
    assert any("heat wave" in h for h in res["hazards"])


def test_rain_advice():
    advice_no = satellite.rain_advice(0, 0.0)
    assert advice_no["verdict"] == "No"

    advice_high = satellite.rain_advice(85, 25.0)
    assert advice_high["verdict"] == "Yes, definitely"
    assert advice_high["probability_pct"] == 85
    assert advice_high["expected_mm"] == 25.0


def test_advisories():
    day = {
        "relative_humidity_2m_max": 85,
        "temperature_2m_max": 30.0,
        "windgusts_10m_max": 65.0,
        "precipitation_probability_max": 90,
    }
    today_alert = {"level": "orange", "hazards": ["strong gusty winds"]}

    pest = advisory.pest_risk_index(day)
    assert pest["level"] == "high"

    crosswind = advisory.crosswind_risk(day)
    assert crosswind["level"] == "high"

    agri = advisory.agriculture_advisory(day, today_alert)
    assert len(agri) > 0
