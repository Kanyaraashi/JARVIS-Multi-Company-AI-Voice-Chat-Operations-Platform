"""Chooses the speech-to-text, AI model and text-to-speech services (Step 23).

Two ready-made stacks. Both use the same Gemini model and the same tools:
  deepgram: Deepgram for listening and speaking (free credit on signup)
  sarvam:   Sarvam for listening and speaking (free credits, strong Indian languages)
Pick one with VOICE_STACK in .env. Nothing else in the project changes.
"""
import os

# The plugins MUST be imported here, when the program starts. LiveKit refuses to load a
# plugin from inside a call (on Windows each call runs in a background thread).
from livekit.agents import llm  # noqa: E402
from livekit.plugins import deepgram, google, sarvam, silero  # noqa: E402

from app.voice import config  # noqa: E402


def build_llm():
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY is missing in .env")
    names = [os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip()]
    for name in os.getenv("GEMINI_FALLBACK_MODELS", "").split(","):
        name = name.strip()
        if name and name not in names:
            names.append(name)

    thinking = os.getenv("GEMINI_THINKING_LEVEL", "LOW").strip().upper()
    models = []
    for name in names:
        extra = {}
        if thinking and thinking != "NONE" and name.startswith("gemini-3"):
            extra["thinking_config"] = {"thinking_level": thinking}
        models.append(google.LLM(model=name, api_key=key, temperature=0.2, **extra))
    # If one model fails, the next one answers (the voice version of the chat failover).
    return models[0] if len(models) == 1 else llm.FallbackAdapter(models)


def build_speech(stack: str):
    """Returns (stt, tts, vad, turn_handling, names)."""
    lang = config.language()
    if stack == "deepgram":
        if not os.getenv("DEEPGRAM_API_KEY"):
            raise SystemExit("DEEPGRAM_API_KEY is missing in .env")
        stt = deepgram.STT(model="nova-3", language=lang)
        tts = deepgram.TTS(model=os.getenv("DEEPGRAM_TTS_MODEL", "aura-2-andromeda-en"))
        return stt, tts, silero.VAD.load(), None, {"stt": "deepgram nova-3", "tts": "deepgram aura-2"}

    if not os.getenv("SARVAM_API_KEY"):
        raise SystemExit("SARVAM_API_KEY is missing in .env")
    stt = sarvam.STTRealtime(language=lang, stream_type="balanced")
    speaker = os.getenv("SARVAM_SPEAKER") or None
    tts = sarvam.TTS(target_language_code=lang, model="bulbul:v3", speaker=speaker)
    # Sarvam listens with its own voice detection, so LiveKit's turn detector follows it.
    return stt, tts, None, {"turn_detection": "stt"}, {"stt": "sarvam realtime", "tts": "sarvam bulbul:v3"}


def build_session_parts() -> dict:
    """Everything AgentSession needs, plus the provider names saved on each call record."""
    stt, tts, vad, turn_handling, names = build_speech(config.stack())
    llm = build_llm()
    parts = {"stt": stt, "tts": tts, "llm": llm, "preemptive_generation": False}
    if vad is not None:
        parts["vad"] = vad
    if turn_handling is not None:
        parts["turn_handling"] = turn_handling
    names = {**names, "llm": os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip(), "stack": config.stack()}
    return {"kwargs": parts, "names": names}
