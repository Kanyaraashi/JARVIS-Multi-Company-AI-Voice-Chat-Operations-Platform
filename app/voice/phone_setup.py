"""Writes the two LiveKit phone files from your VOICE_NUMBERS setting (Step 29).

    python -m app.voice.phone_setup            writes livekit/inbound-trunk.json and livekit/dispatch-rule.json
    python -m app.voice.phone_setup --out dir  writes them somewhere else

Then you run the two `lk` commands it prints. Nothing is sent to LiveKit by this script.
"""
import argparse
import json
import pathlib
import sys

from dotenv import load_dotenv

from app.voice import config
from app.voice.preflight import E164


def build_files(lines: dict) -> dict:
    numbers = sorted(lines)
    return {
        "inbound-trunk.json": {"trunk": {"name": "JARVIS inbound", "numbers": numbers}},
        "dispatch-rule.json": {"dispatch_rule": {
            "name": "JARVIS inbound",
            "rule": {"dispatch_rule_individual": {"room_prefix": config.ROOM_PHONE_PREFIX}},
            "room_config": {"agents": [{"agent_name": config.AGENT_NAME}]},
        }},
    }


def main(argv=None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="livekit")
    args = parser.parse_args(argv)
    lines = config.phone_lines()
    if not lines:
        print("VOICE_NUMBERS is empty. Add it to .env, for example: VOICE_NUMBERS=+918012345678=smile-dental")
        return 1
    bad = [n for n in lines if not E164.match(n)]
    if bad:
        print("These numbers are not in international form (+ country code, digits only): " + ", ".join(bad))
        return 1
    folder = pathlib.Path(args.out)
    folder.mkdir(parents=True, exist_ok=True)
    for name, body in build_files(lines).items():
        (folder / name).write_text(json.dumps(body, indent=2) + "\n")
        print(f"wrote {folder / name}")
    print("\nNow run these two commands (you need the LiveKit command line tool, and `lk cloud auth` once):")
    print(f"  lk sip inbound create {folder / 'inbound-trunk.json'}")
    print(f"  lk sip dispatch create {folder / 'dispatch-rule.json'}")
    print("\nIndian (+91) numbers: send calls to the INDIA address <your SIP subdomain>.india.sip.livekit.cloud"
          " (see PHONE_SETUP_GUIDE.md, part 5).")
    print("The phone company must send calls for these numbers to your LiveKit SIP address:")
    for number, slug in sorted(lines.items()):
        print(f"  {number}  ->  {slug}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
