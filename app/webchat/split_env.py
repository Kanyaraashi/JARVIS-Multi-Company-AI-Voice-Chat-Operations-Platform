"""Makes .env.chat for the customer web chat service from your .env.

    python -m app.webchat.split_env

.env.chat contains only chat settings (the AI key, each company's JARVIS_KEY_..., CHAT_..., PUBLIC_BASE_URL).
Your database password, staff keys, n8n secret and the voice keys stay out. Values are never printed.
"""
import os
import pathlib
import sys

from dotenv import dotenv_values

from app.voice.split_env import ensure_ignored

ALLOWED_PREFIXES = ("GEMINI_", "JARVIS_KEY_", "CHAT_", "PUBLIC_BASE_URL")


def split(values: dict):
    keep = {k: v for k, v in values.items() if k.startswith(ALLOWED_PREFIXES) and v not in (None, "")}
    return keep, sorted(k for k in values if k not in keep)


def main(folder: pathlib.Path = pathlib.Path(".")) -> int:
    source = folder / ".env"
    if not source.exists():
        print("No .env file here. Run this from the project folder.")
        return 1
    keep, left_out = split(dotenv_values(source))
    if "PUBLIC_BASE_URL" not in keep:
        print("PUBLIC_BASE_URL is missing in .env. Add a line like:  PUBLIC_BASE_URL=https://jarvis.example.com")
        return 1
    if not any(k.startswith("JARVIS_KEY_") for k in keep):
        print("No JARVIS_KEY_<COMPANY> found in .env. The chat needs each company's AI key.")
        return 1
    target = folder / ".env.chat"
    lines = [f'{k}="{v}"' if any(c in v for c in " #") else f"{k}={v}" for k, v in sorted(keep.items())]
    target.write_text("\n".join(lines) + "\n")
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    added = ensure_ignored(folder, ".env.chat")
    print(f"wrote {target} with {len(keep)} settings:")
    for name in sorted(keep):
        print(f"  {name}")
    print(f"left out ({len(left_out)}): " + ", ".join(left_out))
    if added:
        print("added .env.chat to .gitignore")
    return 0


if __name__ == "__main__":
    sys.exit(main())
