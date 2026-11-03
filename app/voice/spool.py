"""Sends call records that could not be saved earlier. Run: python -m app.voice.spool"""
import json

from dotenv import load_dotenv

from app.agent_tools import API_BASE
from app.voice import config
from app.voice.recorder import send, spool_dir

load_dotenv()


def main() -> None:
    files = sorted(spool_dir().glob("*.json")) if spool_dir().exists() else []
    if not files:
        print("Nothing waiting. All call records were saved.")
        return
    saved = 0
    for path in files:
        data = json.loads(path.read_text())
        key = config.company_key(data["company"])
        if not key:
            print(f"  skip {path.name}: no key for company {data['company']} in .env")
            continue
        ok, reason = send(API_BASE, key, data["payload"], attempts=2)
        print(f"  {'saved' if ok else 'FAILED'}  {path.name}  {'' if ok else reason}")
        if ok:
            path.unlink()
            saved += 1
    print(f"{saved} of {len(files)} saved.")


if __name__ == "__main__":
    main()
