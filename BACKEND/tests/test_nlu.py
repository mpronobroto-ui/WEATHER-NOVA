from app import nlu


def test_parse_query_intents():
    p1 = nlu.parse_query("hi")
    assert p1.intent == "greeting"

    p2 = nlu.parse_query("what can you do?")
    assert p2.intent == "help"

    p3 = nlu.parse_query("will it rain tomorrow in Delhi?")
    assert p3.intent == "umbrella"
    assert p3.day_offset == 1
    assert p3.location_text == "Delhi"

    p4 = nlu.parse_query("any cyclone alert near Chennai?")
    assert p4.intent == "alert"
    assert p4.location_text == "Chennai"

    p5 = nlu.parse_query("crop farming advisory for Punjab")
    assert p5.intent == "agriculture"
    assert "Punjab" in (p5.location_text or "")

    p6 = nlu.parse_query("solar power output forecast for Jaipur")
    assert p6.intent == "energy"
    assert "Jaipur" in (p6.location_text or "")

    p7 = nlu.parse_query("best route under rain for driver")
    assert p7.intent == "fleet"

    p8 = nlu.parse_query("weather of digha")
    assert p8.intent == "current"
    assert p8.location_text == "digha"

    p9 = nlu.parse_query("weather of kalighat")
    assert p9.intent == "current"
    assert p9.location_text == "kalighat"

    p10 = nlu.parse_query("weather of dakshineswar")
    assert p10.intent == "current"
    assert p10.location_text == "dakshineswar"

    p11 = nlu.parse_query("weather in Delhi")
    assert p11.intent == "current"
    assert p11.location_text == "Delhi"

    p12 = nlu.parse_query("weather at kathmandu")
    assert p12.intent == "current"
    assert p12.location_text == "kathmandu"

    p14 = nlu.parse_query("weather at rajarhat, kolkata")
    assert p14.intent == "current"
    assert "rajarhat, kolkata" in (p14.location_text or "").lower()

    p15 = nlu.parse_query("weather at chinar park, kolkata")
    assert p15.intent == "current"
    assert "chinar park, kolkata" in (p15.location_text or "").lower()

    p16 = nlu.parse_query("weather in bandra, mumbai")
    assert p16.intent == "current"
    assert "bandra, mumbai" in (p16.location_text or "").lower()


def test_parse_query_multilingual():
    p_hi = nlu.parse_query("क्या कल दिल्ली में बारिश होगी?")
    assert p_hi.intent == "umbrella"

    p_bn = nlu.parse_query("কলকাতায় কাল আবহাওয়া কেমন?")
    assert p_bn.intent in ("forecast", "current")


def test_split_multi_location():
    assert nlu.split_multi_location("Chennai and Kolkata") == ["Chennai", "Kolkata"]
    assert nlu.split_multi_location("Mumbai / Pune") == ["Mumbai", "Pune"]
    assert nlu.split_multi_location("Rajarhat, Kolkata") == ["Rajarhat, Kolkata"]
    assert nlu.split_multi_location("Delhi") == ["Delhi"]
    assert nlu.split_multi_location("") == []
