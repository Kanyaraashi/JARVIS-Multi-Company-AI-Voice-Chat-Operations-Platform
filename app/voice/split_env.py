"""Makes .env.voice for the voice worker from your .env (Step 30).

    python -m app.voice.split_env

.env.voice contains only voice settings. Your database password, staff keys, n8n secret and
anything else stay out, so a leak from the worker cannot reach them. Values are never printed.
"""
import os
import pathlib
import sys

from dotenv import dotenv_values

ALLOWED_PREFIXES = ("LIVEKIT_", "VOICE_", "GEMINI_", "DEEPGRAM_", "SARVAM_", "JARVIS_KEY_")
NEVER = ("VOICE_SPOOL_DIR",)   # set by docker-compose.voice.yml instead


def split(values: dict):
    keep = {k: v for k, v in values.items() if k.startswith(ALLOWED_PREFIXES) and k not in NEVER and v not in (None, "")}
    left_out = sorted(k for k in values if k not in keep)
    return keep, left_out


def ensure_ignored(folder: pathlib.Path, name: str) -> bool:
    ignore = folder / ".gitignore"
    text = ignore.read_text() if ignore.exists() else ""
    if name in text.splitlines():
        return False
    ignore.write_text(text + ("" if text.endswith("\n") or not text else "\n") + name + "\n")
    return True


def main(argv=None, folder: pathlib.Path = pathlib.Path(".")) -> int:
    source = folder / ".env"
    if not source.exists():
        print("No .env file here. Run this from the project folder.")
        return 1
    keep, left_out = split(dotenv_values(source))
    if not keep:
        print("No voice settings found in .env (LIVEKIT_..., GEMINI_..., DEEPGRAM_..., JARVIS_KEY_...).")
        return 1
    target = folder / ".env.voice"
    lines = [f'{k}="{v}"' if any(c in v for c in " #") else f"{k}={v}" for k, v in sorted(keep.items())]
    target.write_text("\n".join(lines) + "\n")
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    added = ensure_ignored(folder, ".env.voice")
    print(f"wrote {target} with {len(keep)} voice settings:")
    for name in sorted(keep):
        print(f"  {name}")
    print(f"left out ({len(left_out)}): " + ", ".join(left_out))
    if added:
        print("added .env.voice to .gitignore")
    return 0


if __name__ == "__main__":
    sys.exit(main())
