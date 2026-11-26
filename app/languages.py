"""Indian languages for phone calls (Sarvam) and the QR chat (Gemini).

Codes are BCP-47 (te-IN). Sarvam's Bulbul v3 voice speaks these 11 languages:
https://docs.sarvam.ai/api/getting-started/models/bulbul.md
Plain Python, no outside libraries, so the voice agent, the chat server and the checks can all use it.
"""
import os
import re
from typing import List, Optional

# code: (English name, name in its own script)
LANGUAGES = {
    "en-IN": ("English", "English"),
    "hi-IN": ("Hindi", "हिन्दी"),
    "te-IN": ("Telugu", "తెలుగు"),
    "ta-IN": ("Tamil", "தமிழ்"),
    "kn-IN": ("Kannada", "ಕನ್ನಡ"),
    "ml-IN": ("Malayalam", "മലയാളം"),
    "mr-IN": ("Marathi", "मराठी"),
    "bn-IN": ("Bengali", "বাংলা"),
    "gu-IN": ("Gujarati", "ગુજરાતી"),
    "pa-IN": ("Punjabi", "ਪੰਜਾਬੀ"),
    "od-IN": ("Odia", "ଓଡ଼ିଆ"),
}
DEFAULT_LIST = "en-IN,hi-IN,te-IN,ta-IN"
STT_CODE = {"od-IN": "or-IN"}          # Sarvam's realtime listener calls Odia or-IN; the voice (TTS) calls it od-IN

_ALIASES = {}
for _code, (_english, _native) in LANGUAGES.items():
    for _name in (_code, _code.split("-")[0], _english, _native):
        _ALIASES[_name.strip().lower()] = _code


def normalise(value) -> Optional[str]:
    """'te', 'te-IN', 'Telugu', 'తెలుగు' -> 'te-IN'. Anything else -> None."""
    if not isinstance(value, str):
        return None
    return _ALIASES.get(re.sub(r"[_\s]+", "-", value.strip()).lower()) or _ALIASES.get(value.strip().lower())


def english_name(code: str) -> str:
    return LANGUAGES[code][0]


def native_name(code: str) -> str:
    return LANGUAGES[code][1]


def parse_list(text: str, label: str = "VOICE_LANGUAGES") -> List[str]:
    """'te-IN, hi-IN' -> ['te-IN', 'hi-IN'] in the order written, no repeats. Stops with a clear message on an unknown language."""
    out = []
    for part in (text or "").split(","):
        if not part.strip():
            continue
        code = normalise(part)
        if code is None:
            known = ", ".join(LANGUAGES)
            raise SystemExit(f"{label} has '{part.strip()}', which is not a supported language. Use these codes: {known}.")
        if code not in out:
            out.append(code)
    if not out:
        raise SystemExit(f"{label} is empty. Example: {DEFAULT_LIST}")
    return out


def voice_languages(env=None) -> List[str]:
    """The languages a call may use. The FIRST one is where every call starts.
    VOICE_LANGUAGE (one code) is the start language; VOICE_LANGUAGES (a list) is everything allowed."""
    env = os.environ if env is None else env
    start = normalise(env.get("VOICE_LANGUAGE") or "en-IN") or "en-IN"
    raw = (env.get("VOICE_LANGUAGES") or "").strip()
    if not raw:
        return [start]                                  # nothing set: one language, exactly as before
    wanted = parse_list(raw)
    return [start] + [c for c in wanted if c != start]


def chat_languages(env=None) -> List[str]:
    """The languages the QR chat offers. The FIRST one is the default."""
    env = os.environ if env is None else env
    return parse_list(env.get("CHAT_LANGUAGES") or DEFAULT_LIST, "CHAT_LANGUAGES")


def list_for_prompt(codes: List[str]) -> str:
    return ", ".join(f"{english_name(c)} ({native_name(c)}, code {c})" if c != "en-IN" else f"English (code {c})" for c in codes)
