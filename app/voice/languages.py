"""Language switching during a phone call.

The caller speaks Telugu, Hindi, Tamil ... The AI notices and calls the tool switch_language. This class then:
  - changes the VOICE (Sarvam text-to-speech) to that language, and
  - changes the LISTENER only when it was told one fixed language (with "auto" it follows the caller by itself).
Nothing else about the call changes: same tools, same company, same call record.
"""
import logging

from app import languages

log = logging.getLogger("jarvis.voice")


class LanguageSwitcher:
    def __init__(self, allowed, tts=None, stt=None, stt_fixed=False):
        self.allowed = list(allowed)
        self.current = self.allowed[0]
        self.tts, self.stt, self.stt_fixed = tts, stt, stt_fixed
        self.history = [self.current]

    def switch(self, value) -> dict:
        code = languages.normalise(value)
        if code is None or code not in self.allowed:
            names = ", ".join(f"{languages.english_name(c)} ({c})" for c in self.allowed)
            return {"ok": False, "error": f"That language is not available on this line. Available: {names}."}
        if code == self.current:
            return {"ok": True, "language": code, "changed": False}
        previous = self.current
        try:
            if self.tts is not None:
                self.tts.update_options(target_language_code=code)
            if self.stt is not None and self.stt_fixed:
                self.stt.update_options(language=languages.STT_CODE.get(code, code))
        except Exception as exc:        # leave the call as it was rather than half-switched
            log.warning("Could not switch the call language to %s (%s)", code, type(exc).__name__)
            try:
                if self.tts is not None:
                    self.tts.update_options(target_language_code=previous)
            except Exception:
                pass
            return {"ok": False, "error": "The language could not be changed. Continue in " + languages.english_name(previous) + "."}
        self.current = code
        self.history.append(code)
        log.info("Call language: %s -> %s", previous, code)
        return {"ok": True, "language": code, "changed": True}
