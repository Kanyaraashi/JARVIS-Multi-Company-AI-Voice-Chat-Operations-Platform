"""Creates a browser test call (no phone needed). Run: python -m app.voice.make_token smile-dental

Prints the LiveKit address and a token. Open https://agents-playground.livekit.io, choose
"Manual", paste both, and press Connect. The token also asks LiveKit to send the agent into
the room. Tokens last 15 minutes and only work for one room.
"""
import datetime
import os
import secrets
import sys

from dotenv import load_dotenv

from app.voice import config

load_dotenv()


def make_token(slug: str) -> tuple:
    from livekit import api

    room = f"{config.ROOM_WEB_PREFIX}{slug}-{secrets.token_hex(3)}"
    token = (
        api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
        .with_identity("tester-" + secrets.token_hex(2))
        .with_name("Browser tester")
        .with_ttl(datetime.timedelta(minutes=15))
        .with_grants(api.VideoGrants(room_join=True, room=room))
        .with_room_config(
            api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=config.AGENT_NAME)])
        )
        .to_jwt()
    )
    return room, token


def main() -> None:
    slug = sys.argv[1] if len(sys.argv) > 1 else "smile-dental"
    for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        if not os.getenv(name):
            sys.exit(f"{name} is missing in .env")
    if not config.company_key(slug):
        sys.exit(f"No key for company '{slug}' in .env (JARVIS_KEY_{slug.upper().replace('-', '_')})")
    room, token = make_token(slug)
    print(f"Room: {room}\n\nLIVEKIT_URL:\n{os.environ['LIVEKIT_URL']}\n\nToken (valid 15 minutes):\n{token}")


if __name__ == "__main__":
    main()
