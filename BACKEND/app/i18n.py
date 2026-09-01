"""
Lightweight multilingual layer for Indian languages.

Rather than depend on a paid translation API (fragile in a hackathon demo),
core response templates are pre-translated for the languages below and
filled in with live data at runtime. Free-form LLM answers (see llm.py) are
asked to respond directly in the requested language when an LLM key is
configured. Add a new language by adding one dict entry — no other code
changes needed.
"""
from __future__ import annotations

SUPPORTED = {
    "en": {"name": "English", "speech": "en-IN"},
    "hi": {"name": "हिन्दी", "speech": "hi-IN"},
    "bn": {"name": "বাংলা", "speech": "bn-IN"},
    "ta": {"name": "தமிழ்", "speech": "ta-IN"},
    "te": {"name": "తెలుగు", "speech": "te-IN"},
    "mr": {"name": "मराठी", "speech": "mr-IN"},
    "gu": {"name": "ગુજરાતી", "speech": "gu-IN"},
    "pa": {"name": "ਪੰਜਾਬੀ", "speech": "pa-IN"},
    "kn": {"name": "ಕನ್ನಡ", "speech": "kn-IN"},
    "ml": {"name": "മലയാളം", "speech": "ml-IN"},
    "or": {"name": "ଓଡ଼ିଆ", "speech": "or-IN"},
    "ur": {"name": "اردو", "speech": "ur-IN"},
}

ALERT_LABEL = {
    "green": {"en": "Green (No warning)", "hi": "हरा (कोई चेतावनी नहीं)", "bn": "সবুজ (কোনো সতর্কতা নেই)",
              "ta": "பச்சை (எச்சரிக்கை இல்லை)", "te": "గ్రీన్ (హెచ్చరిక లేదు)", "mr": "हिरवा (इशारा नाही)",
              "gu": "લીલો (કોઈ ચેતવણી નથી)", "pa": "ਹਰਾ (ਕੋਈ ਚੇਤਾਵਨੀ ਨਹੀਂ)", "kn": "ಹಸಿರು (ಎಚ್ಚರಿಕೆ ಇಲ್ಲ)",
              "ml": "പച്ച (മുന്നറിയിപ്പ് ഇല്ല)", "or": "ସବୁଜ (କୌଣସି ଚେତାବନୀ ନାହିଁ)", "ur": "سبز (کوئی وارننگ نہیں)"},
    "yellow": {"en": "Yellow (Watch)", "hi": "पीला (सतर्क रहें)", "bn": "হলুদ (সতর্কতা)", "ta": "மஞ்சள் (கவனிக்கவும்)",
               "te": "పసుపు (గమనించండి)", "mr": "पिवळा (सावध रहा)", "gu": "પીળો (સાવચેત રહો)",
               "pa": "ਪੀਲਾ (ਸੁਚੇਤ ਰਹੋ)", "kn": "ಹಳದಿ (ಎಚ್ಚರಿಕೆಯಿಂದಿರಿ)", "ml": "മഞ്ഞ (ജാഗ്രത)",
               "or": "ହଳଦିଆ (ସତର୍କ ରୁହନ୍ତୁ)", "ur": "پیلا (چوکنا رہیں)"},
    "orange": {"en": "Orange (Be prepared)", "hi": "नारंगी (तैयार रहें)", "bn": "কমলা (প্রস্তুত থাকুন)",
               "ta": "ஆரஞ்சு (தயாராக இருங்கள்)", "te": "నారింజ (సిద్ధంగా ఉండండి)", "mr": "नारिंगी (सज्ज रहा)",
               "gu": "નારંગી (તૈયાર રહો)", "pa": "ਸੰਤਰੀ (ਤਿਆਰ ਰਹੋ)", "kn": "ಕಿತ್ತಳೆ (ಸಿದ್ಧರಾಗಿರಿ)",
               "ml": "ഓറഞ്ച് (തയ്യാറാകുക)", "or": "କମଳା (ପ୍ରସ୍ତୁତ ରୁହନ୍ତୁ)", "ur": "نارنجی (تیار رہیں)"},
    "red": {"en": "Red (Take action)", "hi": "लाल (कार्रवाई करें)", "bn": "লাল (ব্যবস্থা নিন)", "ta": "சிவப்பு (நடவடிக்கை எடுக்கவும்)",
            "te": "ఎరుపు (చర్య తీసుకోండి)", "mr": "लाल (कृती करा)", "gu": "લાલ (પગલાં લો)",
            "pa": "ਲਾਲ (ਕਾਰਵਾਈ ਕਰੋ)", "kn": "ಕೆಂಪು (ಕ್ರಮ ಕೈಗೊಳ್ಳಿ)", "ml": "ചുവപ്പ് (നടപടി സ്വീകരിക്കുക)",
            "or": "ଲାଲ (ପଦକ୍ଷେପ ନିଅନ୍ତୁ)", "ur": "سرخ (کارروائی کریں)"},
}

# {location}, {temp}, {tmin}, {tmax}, {condition}, {rain_prob}, {wind} are filled at runtime
CURRENT_TEMPLATE = {
    "en": "Weather in {location}: {condition}, {temp}°C right now (range {tmin}–{tmax}°C). "
          "Rain chance {rain_prob}%, wind {wind} km/h.",
    "hi": "{location} में मौसम: {condition}, अभी {temp}°C (सीमा {tmin}–{tmax}°C)। "
          "बारिश की संभावना {rain_prob}%, हवा {wind} किमी/घंटा।",
    "bn": "{location}-এ আবহাওয়া: {condition}, এখন {temp}°সে (সীমা {tmin}–{tmax}°সে)। "
          "বৃষ্টির সম্ভাবনা {rain_prob}%, বাতাস {wind} কিমি/ঘণ্টা।",
    "ta": "{location} வானிலை: {condition}, இப்போது {temp}°C (வரம்பு {tmin}–{tmax}°C). "
          "மழை வாய்ப்பு {rain_prob}%, காற்று {wind} கிமீ/மணி.",
    "te": "{location} వాతావరణం: {condition}, ప్రస్తుతం {temp}°C (పరిధి {tmin}–{tmax}°C). "
          "వర్షం అవకాశం {rain_prob}%, గాలి {wind} కి.మీ/గం.",
    "mr": "{location} मधील हवामान: {condition}, सध्या {temp}°C (श्रेणी {tmin}–{tmax}°C). "
          "पावसाची शक्यता {rain_prob}%, वारा {wind} किमी/तास.",
    "gu": "{location} માં હવામાન: {condition}, હાલમાં {temp}°C (શ્રેણી {tmin}–{tmax}°C). "
          "વરસાદની શક્યતા {rain_prob}%, પવન {wind} કિમી/કલાક.",
    "pa": "{location} ਵਿੱਚ ਮੌਸਮ: {condition}, ਹੁਣ {temp}°C (ਰੇਂਜ {tmin}–{tmax}°C)। "
          "ਮੀਂਹ ਦੀ ਸੰਭਾਵਨਾ {rain_prob}%, ਹਵਾ {wind} ਕਿਮੀ/ਘੰਟਾ।",
    "kn": "{location} ನಲ್ಲಿ ಹವಾಮಾನ: {condition}, ಈಗ {temp}°C (ವ್ಯಾಪ್ತಿ {tmin}–{tmax}°C). "
          "ಮಳೆಯ ಸಾಧ್ಯತೆ {rain_prob}%, ಗಾಳಿ {wind} ಕಿಮೀ/ಗಂ.",
    "ml": "{location} ലെ കാലാവസ്ഥ: {condition}, ഇപ്പോൾ {temp}°C (പരിധി {tmin}–{tmax}°C). "
          "മഴ സാധ്യത {rain_prob}%, കാറ്റ് {wind} കി.മീ/മണിക്കൂർ.",
    "or": "{location} ର ପାଣିପାଗ: {condition}, ବର୍ତ୍ତମାନ {temp}°C (ପରିସର {tmin}–{tmax}°C)। "
          "ବର୍ଷାର ସମ୍ଭାବନା {rain_prob}%, ପବନ {wind} କିମି/ଘଣ୍ଟା।",
    "ur": "{location} کا موسم: {condition}، ابھی {temp}°C (رینج {tmin}–{tmax}°C)۔ "
          "بارش کا امکان {rain_prob}%، ہوا {wind} کلومیٹر/گھنٹہ۔",
}

NO_LOCATION_PROMPT = {
    "en": "Which place would you like the weather for? You can also tap the location button.",
    "hi": "आप किस स्थान का मौसम जानना चाहते हैं? आप लोकेशन बटन भी दबा सकते हैं।",
    "bn": "আপনি কোন স্থানের আবহাওয়া জানতে চান? আপনি লোকেশন বোতামও চাপতে পারেন।",
    "ta": "எந்த இடத்திற்கான வானிலையை அறிய விரும்புகிறீர்கள்? இருப்பிடப் பொத்தானையும் தட்டலாம்.",
    "te": "మీరు ఏ ప్రదేశం వాతావరణం తెలుసుకోవాలనుకుంటున్నారు? లొకేషన్ బటన్ కూడా నొక్కవచ్చు.",
    "mr": "तुम्हाला कोणत्या ठिकाणचे हवामान हवे आहे? तुम्ही लोकेशन बटण देखील दाबू शकता.",
    "gu": "તમે કયા સ્થળનું હવામાન જાણવા માંગો છો? તમે લોકેશન બટન પણ દબાવી શકો છો.",
    "pa": "ਤੁਸੀਂ ਕਿਸ ਸਥਾਨ ਦਾ ਮੌਸਮ ਜਾਣਨਾ ਚਾਹੁੰਦੇ ਹੋ? ਤੁਸੀਂ ਲੋਕੇਸ਼ਨ ਬਟਨ ਵੀ ਦਬਾ ਸਕਦੇ ਹੋ।",
    "kn": "ನೀವು ಯಾವ ಸ್ಥಳದ ಹವಾಮಾನ ತಿಳಿಯಬೇಕು? ಲೊಕೇಶನ್ ಬಟನ್ ಅನ್ನೂ ಒತ್ತಬಹುದು.",
    "ml": "ഏത് സ്ഥലത്തെ കാലാവസ്ഥയാണ് അറിയേണ്ടത്? ലൊക്കേഷൻ ബട്ടണും അമർത്താം.",
    "or": "ଆପଣ କେଉଁ ସ୍ଥାନର ପାଣିପାଗ ଜାଣିବାକୁ ଚାହାଁନ୍ତି? ଆପଣ ଲୋକେସନ ବଟନ ମଧ୍ୟ ଦବାଇ ପାରିବେ।",
    "ur": "آپ کس جگہ کا موسم جاننا چاہتے ہیں؟ آپ لوکیشن بٹن بھی دبا سکتے ہیں۔",
}

LOCATION_NOT_FOUND = {
    "en": "I couldn't find that place. Could you check the spelling or try a nearby bigger town?",
    "hi": "मुझे वह स्थान नहीं मिला। कृपया वर्तनी जांचें या पास के बड़े शहर का नाम आज़माएँ।",
    "bn": "আমি সেই স্থানটি খুঁজে পাইনি। বানান পরীক্ষা করুন বা কাছের বড় শহরের নাম ব্যবহার করুন।",
    "ta": "அந்த இடத்தை என்னால் கண்டுபிடிக்க முடியவில்லை. எழுத்துப்பிழையை சரிபார்க்கவும்.",
    "te": "ఆ ప్రదేశం కనుగొనబడలేదు. స్పెల్లింగ్ చెక్ చేయండి లేదా దగ్గరి పెద్ద పట్టణం ప్రయత్నించండి.",
    "mr": "ते ठिकाण सापडले नाही. स्पेलिंग तपासा किंवा जवळच्या मोठ्या शहराचे नाव वापरा.",
    "gu": "તે સ્થળ મળ્યું નથી. જોડણી તપાસો અથવા નજીકના મોટા શહેરનું નામ અજમાવો.",
    "pa": "ਉਹ ਸਥਾਨ ਨਹੀਂ ਮਿਲਿਆ। ਸਪੈਲਿੰਗ ਦੀ ਜਾਂਚ ਕਰੋ ਜਾਂ ਨੇੜਲੇ ਵੱਡੇ ਸ਼ਹਿਰ ਦਾ ਨਾਂ ਵਰਤੋ।",
    "kn": "ಆ ಸ್ಥಳ ಸಿಗಲಿಲ್ಲ. ಕಾಗುಣಿತ ಪರಿಶೀಲಿಸಿ ಅಥವಾ ಹತ್ತಿರದ ದೊಡ್ಡ ಪಟ್ಟಣ ಪ್ರಯತ್ನಿಸಿ.",
    "ml": "ആ സ്ഥലം കണ്ടെത്താനായില്ല. സ്പെല്ലിംഗ് പരിശോധിക്കുക അല്ലെങ്കിൽ അടുത്തുള്ള വലിയ പട്ടണം ശ്രമിക്കുക.",
    "or": "ମୁଁ ସେହି ସ୍ଥାନ ପାଇଲି ନାହିଁ। ବନାନ ଯାଞ୍ଚ କରନ୍ତୁ କିମ୍ବା ନିକଟସ୍ଥ ବଡ଼ ସହରର ନାମ ଚେଷ୍ଟା କରନ୍ତୁ।",
    "ur": "مجھے وہ جگہ نہیں ملی۔ ہجے چیک کریں یا قریبی بڑے شہر کا نام آزمائیں۔",
}


def t(table: dict[str, str], lang: str) -> str:
    return table.get(lang, table.get("en", ""))


def alert_label(level: str, lang: str) -> str:
    level_dict = ALERT_LABEL.get(level, ALERT_LABEL["green"])
    return level_dict.get(lang, level_dict.get("en", "Green"))

