"""Settings and company lookup for the voice agent (Steps 22 and 23)."""
import os
import re
from typing import Optional

ROOM_PHONE_PREFIX = "call-"   # the phone dispatch rule creates rooms called call-<random>
ROOM_WEB_PREFIX = "web-"      # browser test rooms are called web-<company-slug>-<random>
AGENT_NAME = "jarvis"
STACKS = ("deepgram", "sarvam")


def stack() -> str:
    value = os.getenv("VOICE_STACK", "deepgram").strip().lower()
    if value not in STACKS:
        raise SystemExit(f"VOICE_STACK must be one of {', '.join(STACKS)} (you wrote '{value}').")
    return value


def language() -> str:
    return os.getenv("VOICE_LANGUAGE", "en-IN").strip()


def max_call_minutes() -> float:
    return float(os.getenv("VOICE_MAX_CALL_MINUTES", "8"))


def normalize_number(value: Optional[str]) -> str:
    return re.sub(r"[\s\-()]", "", value or "")


def phone_lines() -> dict:
    """VOICE_NUMBERS=+918012345678=smile-dental,+14155550100=shopeasy
    Which company owns which number that people can dial."""
    lines = {}
    for part in os.getenv("VOICE_NUMBERS", "").split(","):
        number, _, slug = part.partition("=")
        number, slug = normalize_number(number), slug.strip()
        if number and slug:
            lines[number] = slug
    return lines


def company_key(slug: str) -> Optional[str]:
    """The company's AI key, from .env: JARVIS_KEY_SMILE_DENTAL for smile-dental."""
    return os.getenv("JARVIS_KEY_" + slug.upper().replace("-", "_")) or None


def resolve_company(room_name: str, attributes: dict, is_console: bool = False) -> Optional[tuple]:
    """Decides which company a call belongs to. Returns (slug, direction) or None.

    The company is NEVER taken from anything the caller says or types:
      phone calls: from the number that was dialled (set by the phone network, not the caller)
      browser tests: from the room name, which only our own token script creates
      other test rooms (for example the LiveKit dashboard console): from VOICE_DEFAULT_COMPANY,
        which is only for development. Leave it empty in production.
    A room starting with call- NEVER gets the default company. Anything else is refused,
    so a call can never fall into the wrong company."""
    if is_console:
        slug = os.getenv("VOICE_DEFAULT_COMPANY", "").strip()
        return (slug, "web") if slug else None

    if room_name.startswith(ROOM_PHONE_PREFIX):
        dialled = normalize_number((attributes or {}).get("sip.trunkPhoneNumber"))
        slug = phone_lines().get(dialled)
        return (slug, "inbound") if slug else None

    if room_name.startswith(ROOM_WEB_PREFIX):
        slug = room_name[len(ROOM_WEB_PREFIX):].rsplit("-", 1)[0]
        if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            return slug, "web"
        return None

    default = os.getenv("VOICE_DEFAULT_COMPANY", "").strip()
    return (default, "web") if default else None
