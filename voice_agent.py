"""Starts the JARVIS voice agent.

    python voice_agent.py dev        connects to LiveKit (browser and phone calls)
    python voice_agent.py console    talk through this computer's microphone, no LiveKit needed
"""
from livekit.agents import cli

from app.voice.worker import server

if __name__ == "__main__":
    cli.run_app(server)
