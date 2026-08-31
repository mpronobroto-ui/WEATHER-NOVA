"""
Query-understanding engine.

Design choice for the hackathon: ship a deterministic, dependency-free rule
engine as the DEFAULT path so the demo works instantly with no API key, then
let `llm.py` optionally take over parsing (and final phrasing) when an LLM
key (OpenAI / Gemini / a local Llama via Ollama) is configured in the
environment. Judges can therefore see both a zero-cost baseline and the
"real" LLM-in-the-loop mode by just setting an env var.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

INTENT_KEYWORDS = {
    "alert": [
        "alert", "warning", "cyclone", "flood", "storm", "danger", "warn",
        "चेतावनी", "अलर्ट", "बाढ़", "तूफान", "चक्रवात",
        "সতর্কতা", "বন্যা", "ঘূর্ণিঝড়",
        "எச்சரிக்கை", "புயல்", "வெள்ளம்",
        "హెచ్చరిక", "తుఫాను", "వరద",
        "इशारा", "पूर", "चक्रीवादळ",
    ],
    "umbrella": [
        "umbrella", "rain", "raining", "rainfall", "precip", "wet", "shower",
        "take umbrella", "need umbrella", "carry umbrella", "will it rain",
        "छतरी", "बारिश", "वर्षा", "बरसात",
        "ছাতা", "বৃষ্টি",
        "குடை", "மழை",
        "గొడుగు", "వర్షం",
        "छत्री", "पाऊस",
    ],
    "forecast": [
        "forecast", "week", "tomorrow", "next", "coming days", "7 day", "5 day",
        "पूर्वानुमान", "कल", "अगले", "सप्ताह",
        "পূর্বাভাস", "আগামীকাল", "সপ্তাহ",
        "முன்னறிவிப்பு", "நாளை", "வாரம்",
        "సూచన", "రేపు", "వారం",
        "अंदाज", "उद्या", "आठवडा",
    ],
    "climate": [
        "climate", "trend", "history", "historical", "average", "past years", "over the years",
        "जलवायु", "इतिहास", "औसत", "पिछले वर्ष",
        "জলবায়ু", "ইতিহাস", "গড়",
        "காலநிலை", "வரலாறு", "சராசரி",
        "వాతావరణ ధోరణి", "చరిత్ర", "సగటు",
    ],
    "agriculture": [
        "crop", "farm", "farmer", "sowing", "irrigation", "agri",
        "फसल", "किसान", "खेत", "सिंचाई", "बुवाई",
        "ফসল", "কৃষক", "চাষ",
        "பயிர்", "விவசாயி", "பாசனம்",
        "పంట", "రైతు", "సాగు",
    ],
    "aviation": [
        "flight", "aviation", "airport", "pilot", "runway", "taf", "metar",
        "उड़ान", "विमान", "हवाई अड्डा",
        "ফ্লাইট", "বিমান",
        "விமானம்", "விமான நிலையம்",
    ],
    "marine": [
        "sea", "marine", "fisherman", "fishing", "coast", "boat", "ocean",
        "समुद्र", "मछुआरे", "तट",
        "সমুদ্র", "জেলে", "উপকূল",
        "கடல்", "மீனவர்", "கடற்கரை",
        "సముద్రం", "మత్స్యకారుడు",
    ],
    "urban": [
        "city", "urban", "municipal", "drainage", "waterlogging", "smart city",
        "शहर", "नगर", "जलभराव",
        "শহর", "পৌর", "জলাবদ্ধতা",
        "நகரம்", "வடிகால்",
    ],
    "fleet": [
        "fleet", "route", "routing", "alternate route", "best route", "driver", "drivers",
        "eld", "cab", "taxi", "dispatch", "eta", "traffic impact", "road risk",
        "fog", "visibility", "reduce speed", "driver alert", "fleet risk",
        "weather impact on route", "reroute", "detour", "logistics",
        "बेस्ट रूट", "रूट", "फ्लीट", "ड्राइवर", "कोहरा", "दृश्यता",
        "বিকল্প রুট", "ফ্লিট", "ড্রাইভার", "কুয়াশা",
        "மாற்று வழி", "ஓட்டுநர்", "மூடுபனி",
        "మార్గం", "డ్రైవర్", "పొగమంచు",
    ],
    "energy": [
        "solar", "renewable", "wind turbine", "turbine", "energy", "irradiance",
        "grid operator", "power output", "energy grid", "energy forecast",
        "सौर", "पवन ऊर्जा", "ऊर्जा",
    ],
    "retail": [
        "retail", "inventory", "stock up", "restock", "shop", "store", "shopkeeper",
        "sales forecast", "consumer demand", "दुकान", "स्टॉक",
    ],
    "construction": [
        "construction", "crane", "site manager", "contractor", "build schedule",
        "work stoppage", "scaffolding", "जोखिम निर्माण", "निर्माण स्थल",
    ],
    "greeting": [
        "hi", "hello", "hey", "namaste", "नमस्ते", "हाय", "হ্যালো", "வணக்கம்", "నమస్తే",
    ],
    "help": [
        "what can you do", "what can you help", "what can i ask", "what do you do",
        "how do you work", "how does this work", "help", "commands", "capabilities",
        "features", "what are you", "who are you", "what is this", "instructions",
        "how to use", "user guide", "options", "menu",
        "तुम क्या कर सकते हो", "मदद", "सहायता",
        "তুমি কী করতে পারো", "সাহায্য",
        "நீ என்ன செய்ய முடியும்", "உதவி",
        "నువ్వు ఏమి చేయగలవు", "సహాయం",
    ],
    "current": [
        "now", "current", "today", "right now",
        "अभी", "आज", "वर्तमान",
        "এখন", "আজ",
        "இப்போது", "இன்று",
        "ఇప్పుడు", "ఈరోజు",
    ],
}

# Words to strip out before what's left is treated as a location candidate.
STOPWORDS = set(
    """
    the a an is are was were will would can could may might in at on of for to my your our weather forecast
    tell me what is show give please today tomorrow tommorow tomorow now current next week
    help commands capabilities features instructions guide options menu
    happen happens happening let know going get
    climate trend history alert warning crop farm farmer flight aviation
    marine sea fishing city urban fleet route routing driver cab taxi dispatch
    fog visibility eld logistics how about umbrella rain raining rainfall
    take need carry should i do you think there any near around about
    cyclone cyclones storm storms flood floods danger warn
    best alternate suggestions suggestion risk impact eta under due heavy
    reduce speed drivers driver alerts alerts alert roads road primary secondary
    solar renewable wind turbine energy irradiance grid operator power output forecast
    retail inventory stock up restock shop store shopkeeper sales consumer demand
    construction crane site manager contractor build schedule work stoppage scaffolding
    और का की के में है हैं क्या मौसम
    बताओ बताइए कैसा कल आज अभी की के लिए पास कोई क्या चाहिए ले जानी
    পরিস্থিতি কেমন আজ আবহাওয়া কেমন
    வானிலை எப்படி இருக்கும் இன்று என்ன
    """.split()
)

DAY_WORDS = {
    "today": 0, "आज": 0, "আজ": 0, "இன்று": 0, "ఈరోజు": 0,
    "tomorrow": 1, "tommorow": 1, "tomorow": 1, "tomorro": 1,
    "कल": 1, "আগামীকাল": 1, "நாளை": 1, "రేపు": 1,
    "day after tomorrow": 2, "परसों": 2,
}


WORD_CHAR_PATTERN = r"[\w\u0900-\u097F\u0980-\u09FF\u0B80-\u0BFF\u0C00-\u0C7F]"


def _match_keyword(pattern_text: str, text: str) -> bool:
    """Match a keyword or multi-word phrase against text respecting word boundaries.
    Avoids accidental partial-word collisions like 'hi' matching inside 'Dakshineswar' or 'Delhi'."""
    pat = rf"(?<!{WORD_CHAR_PATTERN}){re.escape(pattern_text.lower())}(?!{WORD_CHAR_PATTERN})"
    return bool(re.search(pat, text, re.IGNORECASE))


def _strip_keyword(pattern_text: str, text: str) -> str:
    """Remove a keyword or multi-word phrase from text respecting word boundaries."""
    pat = rf"(?<!{WORD_CHAR_PATTERN}){re.escape(pattern_text)}(?!{WORD_CHAR_PATTERN})"
    return re.sub(pat, " ", text, flags=re.IGNORECASE)


@dataclass
class ParsedQuery:
    intent: str = "current"
    location_text: str | None = None
    day_offset: int = 0
    horizon_days: int = 7
    raw_text: str = ""
    matched_keywords: list[str] = field(default_factory=list)


def _detect_intent(text_lower: str) -> tuple[str, list[str]]:
    scores: dict[str, list[str]] = {}
    for intent, words in INTENT_KEYWORDS.items():
        hits = [w for w in words if _match_keyword(w, text_lower)]
        if hits:
            scores[intent] = hits

    # Strong fleet/route signals should win even if "rain"/"alert" also matched
    # (e.g. "best route under rain", "driver alert for fog").
    FLEET_STRONG = (
        "fleet", "route", "routing", "alternate route", "best route", "driver", "drivers",
        "eld", "cab", "taxi", "dispatch", "eta", "reroute", "detour", "logistics",
        "driver alert", "fleet risk", "fleet weather", "reduce speed",
    )
    if "fleet" in scores and any(_match_keyword(s, text_lower) for s in FLEET_STRONG):
        return "fleet", scores["fleet"]

    # Same idea for the newer sector intents: a specific word like "solar"
    # or "crane" should win even if a generic word like "forecast" also
    # matched (e.g. "solar energy forecast for Jaipur").
    ENERGY_STRONG = ("solar", "renewable", "wind turbine", "turbine", "irradiance", "energy grid", "power output")
    if "energy" in scores and any(_match_keyword(s, text_lower) for s in ENERGY_STRONG):
        return "energy", scores["energy"]

    RETAIL_STRONG = ("retail", "inventory", "stock up", "restock", "shopkeeper", "sales forecast", "consumer demand")
    if "retail" in scores and any(_match_keyword(s, text_lower) for s in RETAIL_STRONG):
        return "retail", scores["retail"]

    CONSTRUCTION_STRONG = ("crane", "construction site", "work stoppage", "build schedule", "scaffolding", "site manager")
    if "construction" in scores and any(_match_keyword(s, text_lower) for s in CONSTRUCTION_STRONG):
        return "construction", scores["construction"]

    # priority order: alert > umbrella (rain questions) > climate > forecast > sectors > current > greeting
    for intent in [
        "alert", "umbrella", "climate", "forecast", "fleet", "agriculture", "aviation",
        "marine", "urban", "energy", "retail", "construction", "greeting", "help", "current",
    ]:
        if intent in scores:
            return intent, scores[intent]
    return "current", []


def _detect_day_offset(text_lower: str) -> tuple[int, int]:
    for phrase, offset in DAY_WORDS.items():
        if _match_keyword(phrase, text_lower):
            return offset, max(offset + 1, 3)
    if re.search(r"\b(5|five)\s*-?\s*day", text_lower):
        return 0, 5
    if re.search(r"\b(7|seven|week)\b", text_lower):
        return 0, 7
    if re.search(r"\b(10|ten)\s*-?\s*day", text_lower):
        return 0, 10
    return 0, 7


def _extract_location(raw_text: str, intent: str, matched_keywords: list[str]) -> str | None:
    text = raw_text
    # remove matched intent keywords first (longest first to avoid partial overlap issues)
    for kw in sorted(matched_keywords, key=len, reverse=True):
        text = _strip_keyword(kw, text)

    # strip day-offset words so "for Kolkata tomorrow" → Kolkata
    for phrase in sorted(DAY_WORDS.keys(), key=len, reverse=True):
        text = _strip_keyword(phrase, text)

    # common connector patterns: "weather in X", "for X", "near X", "around X"
    m = re.search(
        r"(?:in|at|for|near|around|over|of)\s+([A-Za-z\u0900-\u097F\u0980-\u09FF\u0B80-\u0BFF\u0C00-\u0C7F .]+?)(?:\?|$|,)",
        text,
        re.IGNORECASE,
    )
    if m:
        candidate = m.group(1).strip(" ?.!,")
        parts = [p for p in candidate.split() if p.lower() not in STOPWORDS and p.lower() not in DAY_WORDS]
        candidate = " ".join(parts).strip()
        if candidate:
            return candidate

    # strip stopwords token by token, keep the remainder
    tokens = re.findall(r"[\w\u0900-\u097F\u0980-\u09FF\u0B80-\u0BFF\u0C00-\u0C7F]+", text)
    remainder = [
        tok for tok in tokens
        if tok.lower() not in STOPWORDS and tok.lower() not in DAY_WORDS and len(tok) > 1
    ]
    if remainder:
        return " ".join(remainder).strip()
    return None


_LOCATION_SPLIT_RE = re.compile(
    r"\s*(?:,|/|\bvs\.?\b|\band\b|\b&\b|\bas well as\b)\s*", re.IGNORECASE
)


def split_multi_location(text: str | None) -> list[str]:
    """Split a location phrase that may name more than one place.

    'Chennai and Kolkata' -> ['Chennai', 'Kolkata']
    'Mumbai'              -> ['Mumbai']
    None / ''             -> []

    Word-boundary matching on 'and'/'vs'/'&' avoids splitting inside place
    names that happen to contain those letters (e.g. "Andaman").
    """
    if not text or not text.strip():
        return []
    parts = [p.strip(" ?.!,") for p in _LOCATION_SPLIT_RE.split(text)]
    return [p for p in parts if p]


def parse_query(text: str) -> ParsedQuery:
    text = text.strip()
    text_lower = text.lower()
    intent, matched = _detect_intent(text_lower)
    day_offset, horizon = _detect_day_offset(text_lower)
    location = _extract_location(text, intent, matched)

    if intent in ("greeting", "help"):
        if location:
            intent = "forecast" if (day_offset > 0 or horizon < 7) else "current"
        else:
            location = None

    return ParsedQuery(
        intent=intent,
        location_text=location,
        day_offset=day_offset,
        horizon_days=horizon,
        raw_text=text,
        matched_keywords=matched,
    )
