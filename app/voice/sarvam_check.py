"""Tries Sarvam with your own key, one short sentence per language, and saves the audio so you can listen.

    python -m app.voice.sarvam_check                 the languages in VOICE_LANGUAGES (or English, Hindi, Telugu, Tamil)
    python -m app.voice.sarvam_check --languages te-IN,ta-IN
    python -m app.voice.sarvam_check --speaker priya

Writes sarvam_test/<language>.wav (open them to listen). It never prints your key. It uses a little of your Sarvam credit
(a few hundred characters). It checks the VOICE (text to speech) only; the listener is tested by a real call.
"""
import argparse
import base64
import os
import pathlib
import sys
import time
from typing import Callable, Optional

import httpx
from dotenv import load_dotenv

from app import languages

URL = "https://api.sarvam.ai/text-to-speech"
SENTENCES = {
    "en-IN": "Hello, thank you for calling. How can I help you today?",
    "hi-IN": "नमस्ते, कॉल करने के लिए धन्यवाद। मैं आपकी कैसे मदद कर सकती हूँ?",
    "te-IN": "నమస్కారం, కాల్ చేసినందుకు ధన్యవాదాలు. నేను మీకు ఎలా సహాయం చేయగలను?",
    "ta-IN": "வணக்கம், அழைத்ததற்கு நன்றி. நான் உங்களுக்கு எப்படி உதவலாம்?",
    "kn-IN": "ನಮಸ್ಕಾರ, ಕರೆ ಮಾಡಿದ್ದಕ್ಕೆ ಧನ್ಯವಾದಗಳು. ನಾನು ನಿಮಗೆ ಹೇಗೆ ಸಹಾಯ ಮಾಡಲಿ?",
    "ml-IN": "നമസ്കാരം, വിളിച്ചതിന് നന്ദി. ഞാൻ നിങ്ങളെ എങ്ങനെ സഹായിക്കണം?",
    "mr-IN": "नमस्कार, कॉल केल्याबद्दल धन्यवाद. मी तुम्हाला कशी मदत करू?",
    "bn-IN": "নমস্কার, ফোন করার জন্য ধন্যবাদ। আমি আপনাকে কীভাবে সাহায্য করতে পারি?",
    "gu-IN": "નમસ્તે, ફોન કરવા બદલ આભાર. હું તમને કેવી રીતે મદદ કરી શકું?",
    "pa-IN": "ਸਤ ਸ੍ਰੀ ਅਕਾਲ, ਕਾਲ ਕਰਨ ਲਈ ਧੰਨਵਾਦ। ਮੈਂ ਤੁਹਾਡੀ ਕਿਵੇਂ ਮਦਦ ਕਰ ਸਕਦੀ ਹਾਂ?",
    "od-IN": "ନମସ୍କାର, କଲ୍ କରିଥିବାରୁ ଧନ୍ୟବାଦ। ମୁଁ ଆପଣଙ୍କୁ କିପରି ସାହାଯ୍ୟ କରିପାରିବି?",
}


def synthesize(key: str, code: str, speaker: Optional[str], post: Callable = httpx.post):
    """Returns (wav_bytes_or_None, message). Never raises, never includes the key."""
    body = {"text": SENTENCES[code], "language_code": code, "model": "bulbul:v3"}
    if speaker:
        body["speaker"] = speaker
    started = time.time()
    try:
        r = post(URL, headers={"api-subscription-key": key, "Content-Type": "application/json"}, json=body, timeout=30)
    except httpx.RequestError as exc:
        return None, f"could not reach Sarvam ({type(exc).__name__}). Check your internet."
    if r.status_code in (401, 403):
        return None, "Sarvam refused the key. Check SARVAM_API_KEY in .env (copy it again from the Sarvam dashboard)."
    if r.status_code == 429:
        return None, "Sarvam says too many requests or no credit left. Check your balance on the Sarvam dashboard."
    if r.status_code != 200:
        return None, f"Sarvam answered {r.status_code}: {r.text[:200]}"
    try:
        audio = base64.b64decode(r.json()["audios"][0])
    except Exception:
        return None, "Sarvam answered, but the reply had no audio."
    return audio, f"ok, {len(audio) // 1024} KB in {time.time() - started:.1f}s"


def main(argv: Optional[list] = None, post: Callable = httpx.post, folder: pathlib.Path = pathlib.Path("sarvam_test")) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--languages", help="comma separated, for example te-IN,ta-IN")
    parser.add_argument("--speaker", default=os.getenv("SARVAM_SPEAKER") or None)
    args = parser.parse_args(argv)
    key = (os.getenv("SARVAM_API_KEY") or "").strip()
    if not key:
        print("SARVAM_API_KEY is missing in .env. Make one at the Sarvam dashboard (new accounts get free credit).")
        return 1
    try:
        wanted = languages.parse_list(args.languages, "--languages") if args.languages else (
            languages.voice_languages() if os.getenv("VOICE_LANGUAGES") else languages.parse_list(languages.DEFAULT_LIST))
    except SystemExit as exc:
        print(exc)
        return 1
    folder.mkdir(exist_ok=True)
    failed = 0
    for code in wanted:
        audio, message = synthesize(key, code, args.speaker, post)
        if audio is None:
            failed += 1
            print(f"[FAIL] {languages.english_name(code)} ({code}): {message}")
            if "refused the key" in message:
                break
            continue
        (folder / f"{code}.wav").write_bytes(audio)
        print(f"[ OK ] {languages.english_name(code)} ({code}): {message} -> {folder / (code + '.wav')}")
    print("\nOpen the .wav files and listen. If a voice sounds wrong, try --speaker (for example priya, kavya, rahul, aditya)." if not failed
          else "\nSome languages failed. Fix the first FAIL line above and run this again.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
