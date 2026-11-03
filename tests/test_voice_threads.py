"""On Windows LiveKit runs every call in a background thread, and refuses to load a
plugin there. This test starts the agent module in the main thread, then builds the
speech services from a background thread, exactly like a call does."""
import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

SCRIPT = textwrap.dedent("""
    import sys, threading
    import app.voice.worker  # what voice_agent.py does, in the main thread
    result = {}
    def job():
        try:
            from app.voice import providers
            result["ok"] = sorted(providers.build_session_parts()["kwargs"])
        except BaseException as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
    thread = threading.Thread(target=job); thread.start(); thread.join()
    print(result)
""")


@pytest.mark.parametrize("stack", ["deepgram", "sarvam"])
def test_speech_services_can_be_built_inside_a_call_thread(stack):
    env = {**os.environ, "PYTHONPATH": str(ROOT), "VOICE_STACK": stack, "DEEPGRAM_API_KEY": "x",
           "SARVAM_API_KEY": "x", "GEMINI_API_KEY": "x"}
    done = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)
    assert "'ok'" in done.stdout, done.stdout + done.stderr
    assert "'llm'" in done.stdout and "'stt'" in done.stdout and "'tts'" in done.stdout
