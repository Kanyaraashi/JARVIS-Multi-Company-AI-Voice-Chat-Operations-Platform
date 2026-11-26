"""One command that checks the whole voice setup before you make a call (Step 29).

    python -m app.voice.preflight                 normal check
    python -m app.voice.preflight --production    stricter: no development shortcuts allowed

It never prints a key. It cannot hear audio, so it does not replace one real test call.
Exit code 0 means no FAIL lines.
"""
import argparse
import os
import re
import sys
from dataclasses import dataclass
from typing import Callable, List, Mapping, Optional

import httpx
from dotenv import load_dotenv

from app import languages
from app.voice import config

E164 = re.compile(r"^\+[1-9]\d{7,14}$")


@dataclass
class Result:
    level: str      # OK, WARN or FAIL
    name: str
    message: str


def ok(name, message): return Result("OK", name, message)
def warn(name, message): return Result("WARN", name, message)
def fail(name, message): return Result("FAIL", name, message)


def model_names(env: Mapping) -> List[str]:
    first = (env.get("GEMINI_MODEL") or "gemini-3.1-flash-lite").strip()
    rest = (env.get("GEMINI_FALLBACK_MODELS") or "").split(",")
    return [first] + [m.strip() for m in rest if m.strip()]


NUMBER_SETTINGS = {   # name -> must be a whole number? (otherwise any number such as 2.5)
    "AI_ATTEMPTS_PER_MODEL": True, "AI_RETRY_DELAY_SECONDS": False, "AI_TURN_BUDGET_SECONDS": False,
    "AI_MODEL_TIMEOUT_SECONDS": False, "AI_MODEL_COOLDOWN_SECONDS": False,
    "VOICE_MAX_CALL_MINUTES": False, "VOICE_LLM_ATTEMPT_SECONDS": False,
    "VOICE_FIRST_TOKEN_SECONDS": False, "VOICE_FILLER_AFTER_SECONDS": False,
}


def check_numbers(env: Mapping) -> List[Result]:
    """A setting like AI_ATTEMPTS_PER_MODEL=2s crashes the program on start. Catch it here, in plain words."""
    out = []
    for name, whole in NUMBER_SETTINGS.items():
        value = (env.get(name) or "").strip()
        if not value:
            continue
        pattern = r"\d+" if whole else r"\d+(\.\d+)?"
        if not re.fullmatch(pattern, value):
            out.append(fail(name.lower().replace("_", " "),
                            f"{name} is '{value}'. Write only a number" + (" (a whole number)" if whole else "") + ", for example 2, without letters like 's'."))
    return out or [ok("number settings", "all numbers are written correctly")]


def check_livekit(env: Mapping) -> List[Result]:
    out = []
    url = (env.get("LIVEKIT_URL") or "").strip()
    if not url:
        out.append(fail("livekit url", "LIVEKIT_URL is missing in .env (it looks like wss://your-project.livekit.cloud)."))
    elif not re.match(r"^wss?://\S+$", url):
        out.append(fail("livekit url", "LIVEKIT_URL must start with wss:// (copy it from the LiveKit dashboard)."))
    else:
        out.append(ok("livekit url", "set"))
    for name in ("LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        out.append(ok(name.lower().replace("_", " "), "set") if (env.get(name) or "").strip()
                   else fail(name.lower().replace("_", " "), f"{name} is missing in .env."))
    return out


def check_speech(env: Mapping) -> List[Result]:
    stack = (env.get("VOICE_STACK") or "deepgram").strip().lower()
    if stack not in config.STACKS:
        return [fail("speech stack", f"VOICE_STACK must be deepgram or sarvam (you wrote '{stack}').")]
    key = "DEEPGRAM_API_KEY" if stack == "deepgram" else "SARVAM_API_KEY"
    if (env.get(key) or "").strip():
        return [ok("speech stack", f"{stack}, key set")]
    return [fail("speech stack", f"VOICE_STACK is {stack} but {key} is missing in .env.")]


def check_languages(env: Mapping) -> List[Result]:
    """Nothing is said for a plain English line, so existing setups see no change."""
    stack = (env.get("VOICE_STACK") or "deepgram").strip().lower()
    raw = (env.get("VOICE_LANGUAGES") or "").strip()
    start = (env.get("VOICE_LANGUAGE") or "").strip()
    if not raw and start in ("", "en-IN"):
        return []
    try:
        allowed = languages.voice_languages(env)
    except SystemExit as exc:
        return [fail("languages", str(exc))]
    if start and languages.normalise(start) is None:
        return [fail("languages", f"VOICE_LANGUAGE '{start}' is not supported. Use one of: " + ", ".join(languages.LANGUAGES) + ".")]
    out = []
    if stack == "deepgram" and any(c != "en-IN" for c in allowed):
        out.append(warn("languages", "Deepgram is set up for English only here. For Hindi, Telugu, Tamil and the rest, set VOICE_STACK=sarvam."))
    else:
        names = ", ".join(languages.english_name(c) for c in allowed)
        out.append(ok("languages", f"calls start in {languages.english_name(allowed[0])}; allowed: {names}"))
    mode = (env.get("SARVAM_STT_MODE") or "realtime").strip().lower()
    if stack == "sarvam" and mode not in ("realtime", "standard"):
        out.append(fail("sarvam listener", f"SARVAM_STT_MODE must be realtime or standard (you wrote '{mode}')."))
    return out


def check_models(env: Mapping) -> List[Result]:
    out = []
    if not (env.get("GEMINI_API_KEY") or "").strip():
        out.append(fail("gemini key", "GEMINI_API_KEY is missing in .env."))
    else:
        out.append(ok("gemini key", "set"))
    names = model_names(env)
    bad = [n for n in names if "latest" in n or not re.fullmatch(r"[a-z0-9][a-z0-9.\-]*", n)]
    if bad:
        out.append(fail("models", "Use exact model names, not aliases or odd characters: " + ", ".join(bad)))
        return out
    if len(set(names)) != len(names):
        out.append(warn("models", "A model is listed twice. Each backup should be a different model."))
    elif len(names) == 1:
        out.append(warn("models", "Only one model. Add GEMINI_FALLBACK_MODELS so a slow or broken model is replaced quietly."))
    else:
        out.append(ok("models", "main " + names[0] + ", backup " + ", ".join(names[1:])))
    return out


def check_lines(env: Mapping, production: bool) -> List[Result]:
    out = []
    raw = [p for p in (env.get("VOICE_NUMBERS") or "").split(",") if p.strip()]
    lines = config.phone_lines()
    if len(lines) != len(raw):
        out.append(fail("phone numbers", "VOICE_NUMBERS has an entry that is not written number=company-slug."))
    for number in lines:
        if not E164.match(number):
            out.append(fail("phone numbers", f"{number} is not in international form, for example +918012345678."))
    default = (env.get("VOICE_DEFAULT_COMPANY") or "").strip()
    if default:
        out.append((fail if production else warn)("default company",
                    "VOICE_DEFAULT_COMPANY is for development tests only. Empty it before real customers call."))
    if not lines and not default:
        out.append(fail("companies", "No company can receive calls: set VOICE_NUMBERS (phone) or VOICE_DEFAULT_COMPANY (testing)."))
    elif lines and not any(r.level == "FAIL" for r in out):
        out.append(ok("phone numbers", ", ".join(f"{n} -> {s}" for n, s in lines.items())))
    return out


def company_slugs(env: Mapping) -> List[str]:
    slugs = list(dict.fromkeys(config.phone_lines().values()))
    default = (env.get("VOICE_DEFAULT_COMPANY") or "").strip()
    if default and default not in slugs:
        slugs.append(default)
    return slugs


def check_api(env: Mapping, get: Callable) -> List[Result]:
    base = (env.get("JARVIS_API_BASE") or "http://localhost:8000").rstrip("/")
    out = []
    try:
        health = get(base + "/health", timeout=8)
        out.append(ok("api", f"{base} is healthy") if health.status_code == 200
                   else fail("api", f"{base}/health answered {health.status_code}. Run: docker compose up -d"))
    except Exception:
        return [fail("api", f"Cannot reach {base}. Is Docker running? Try: docker compose up -d")]
    for slug in company_slugs(env):
        key = config.company_key(slug)
        label = "company " + slug
        if not key:
            out.append(fail(label, f"JARVIS_KEY_{slug.upper().replace('-', '_')} is missing in .env."))
            continue
        try:
            r = get(base + "/company/me", headers={"X-API-Key": key}, timeout=8)
        except Exception:
            out.append(fail(label, "The API stopped answering."))
            continue
        if r.status_code != 200:
            out.append(fail(label, f"Its key was refused ({r.status_code}). Create a new AI key for this company."))
        elif r.json().get("slug") not in (None, slug):
            # The most dangerous mistake: a key that opens a DIFFERENT company's data.
            out.append(fail(label, "This key belongs to a different company. Fix .env now, calls would mix companies."))
        else:
            out.append(ok(label, "key works" + (f" ({r.json().get('name')})" if r.json().get("name") else "")))
    return out


def check_spool(env: Mapping) -> List[Result]:
    folder = env.get("VOICE_SPOOL_DIR") or "voice_spool"
    try:
        waiting = [f for f in os.listdir(folder) if f.endswith(".json")]
    except FileNotFoundError:
        waiting = []
    if waiting:
        return [warn("unsent calls", f"{len(waiting)} call record(s) are waiting in {folder}. Run: python -m app.voice.spool")]
    return [ok("unsent calls", "none waiting")]


def run(env: Mapping, get: Callable = httpx.get, production: bool = False) -> List[Result]:
    return (check_numbers(env) + check_livekit(env) + check_speech(env) + check_languages(env) + check_models(env) + check_lines(env, production)
            + check_api(env, get) + check_spool(env))


def main(argv: Optional[list] = None, env: Optional[Mapping] = None, get: Callable = httpx.get) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args(argv)
    results = run(env if env is not None else os.environ, get, args.production)
    for r in results:
        print(f"[{r.level:^4}] {r.name}: {r.message}")
    fails = sum(r.level == "FAIL" for r in results)
    warns = sum(r.level == "WARN" for r in results)
    print()
    if fails:
        print(f"{fails} problem(s) to fix before a call will work.")
    else:
        print("All checks passed" + (f" ({warns} warning(s))." if warns else "."))
        print("Next: python -m app.voice.model_speed --company <slug>, then make one real test call.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
