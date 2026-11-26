"""Chooses the speech-to-text, AI model and text-to-speech services (Step 23).

Two ready-made stacks. Both use the same Gemini model and the same tools:
  deepgram: Deepgram for listening and speaking (free credit on signup)
  sarvam:   Sarvam for listening and speaking (free credits, strong Indian languages)
Pick one with VOICE_STACK in .env. Nothing else in the project changes.
"""
import os

# The plugins MUST be imported here, when the program starts. LiveKit refuses to load a
# plugin from inside a call (on Windows each call runs in a background thread).
from livekit.plugins import deepgram, google, sarvam, silero  # noqa: E402

from app import languages  # noqa: E402
from app.voice import config  # noqa: E402
from app.voice.languages import LanguageSwitcher  # noqa: E402
from app.voice.fast_llm import FastFailoverLLM, Hooks  # noqa: E402


MIN_GEMINI_DEADLINE = 10.0


def build_gemini(name: str, key: str):
    """One Gemini model, set up the way voice calls need it."""
    thinking = os.getenv("GEMINI_THINKING_LEVEL", "LOW").strip().upper()
    extra = {}
    if thinking and thinking != "NONE" and name.startswith("gemini-3"):
        extra["thinking_config"] = {"thinking_level": thinking}
    return google.LLM(model=name, api_key=key, temperature=0.2, **extra)


def build_llm(hooks=None):
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY is missing in .env")
    names = [os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip()]
    for name in os.getenv("GEMINI_FALLBACK_MODELS", "").split(","):
        name = name.strip()
        if name and name not in names:
            names.append(name)

    for name in names:
        if "latest" in name:
            raise SystemExit(
                f"GEMINI model '{name}' is an alias. Voice calls need an exact model name, because "
                "the LiveKit plugin cannot tell what an alias points to and then loses the "
                "data Gemini 3 needs for tool calls. Use a name like gemini-3.1-flash-lite or "
                "gemini-3.5-flash-lite in GEMINI_MODEL and GEMINI_FALLBACK_MODELS."
            )

    models = [build_gemini(name, key) for name in names]
    # Quick, quiet failover (Step 25): if a model gives nothing for VOICE_FIRST_TOKEN_SECONDS,
    # or fails, the next model answers. The caller never hears a model name; after
    # VOICE_FILLER_AFTER_SECONDS of silence they hear VOICE_FILLER_TEXT once per question.
    # Each try still needs at least 10 seconds of deadline: Gemini REFUSES shorter ones.
    attempt = max(MIN_GEMINI_DEADLINE, float(os.getenv("VOICE_LLM_ATTEMPT_SECONDS", "12")))
    return FastFailoverLLM(
        models,
        first_token_seconds=float(os.getenv("VOICE_FIRST_TOKEN_SECONDS", "6")),
        filler_after_seconds=float(os.getenv("VOICE_FILLER_AFTER_SECONDS", "2.5")),
        filler_text=os.getenv("VOICE_FILLER_TEXT", "One moment please.").strip() or "One moment please.",
        attempt_timeout=attempt,
        hooks=hooks or Hooks(),
    )


def build_speech(stack: str):
    """Returns (stt, tts, vad, turn_handling, names, switcher). The switcher is None unless the line offers several languages."""
    allowed = languages.voice_languages()
    lang = allowed[0]
    many = len(allowed) > 1
    if stack == "deepgram":
        if not os.getenv("DEEPGRAM_API_KEY"):
            raise SystemExit("DEEPGRAM_API_KEY is missing in .env")
        stt = deepgram.STT(model="nova-3", language=lang)
        tts = deepgram.TTS(model=os.getenv("DEEPGRAM_TTS_MODEL", "aura-2-andromeda-en"))
        return stt, tts, silero.VAD.load(), None, {"stt": "deepgram nova-3", "tts": "deepgram aura-2"}, None

    if not os.getenv("SARVAM_API_KEY"):
        raise SystemExit("SARVAM_API_KEY is missing in .env")
    mode = os.getenv("SARVAM_STT_MODE", "realtime").strip().lower()
    if mode not in ("realtime", "standard"):
        raise SystemExit(f"SARVAM_STT_MODE must be realtime or standard (you wrote '{mode}').")
    override = os.getenv("SARVAM_STT_LANGUAGE", "").strip()
    speaker = os.getenv("SARVAM_SPEAKER") or None
    if mode == "realtime":
        # "auto": Sarvam follows whichever listed language the caller speaks. One language: it listens for that one.
        stt_language = override or ("auto" if many else languages.STT_CODE.get(lang, lang))
        stt = sarvam.STTRealtime(language=stt_language, stream_type="balanced")
        # Sarvam listens with its own voice detection, so LiveKit's turn detector follows it.
        vad, turn_handling, stt_name, fixed = None, {"turn_detection": "stt"}, "sarvam realtime", stt_language != "auto"
    else:
        # The older, non-streaming listener: a little slower per sentence, but it needs no realtime access.
        stt_language = override or ("unknown" if many else lang)
        stt = sarvam.STT(language=stt_language, model="saaras:v4")
        vad, turn_handling, stt_name, fixed = silero.VAD.load(), None, "sarvam saaras:v4", False
    tts = sarvam.TTS(target_language_code=lang, model="bulbul:v3", speaker=speaker)
    switcher = LanguageSwitcher(allowed, tts=tts, stt=stt, stt_fixed=fixed) if many else None
    return stt, tts, vad, turn_handling, {"stt": stt_name, "tts": "sarvam bulbul:v3"}, switcher


def build_session_parts(hooks=None) -> dict:
    """Everything AgentSession needs, plus the provider names saved on each call record."""
    stt, tts, vad, turn_handling, names, switcher = build_speech(config.stack())
    chain = build_llm(hooks)
    parts = {"stt": stt, "tts": tts, "llm": chain, "preemptive_generation": False}
    if vad is not None:
        parts["vad"] = vad
    if turn_handling is not None:
        parts["turn_handling"] = turn_handling
    names = {**names, "llm": os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip(), "stack": config.stack(),
             "languages": ",".join(languages.voice_languages())}
    return {"kwargs": parts, "names": names, "switcher": switcher}
