"""Gives the voice agent the same 12 tools as the chat agent (Step 22).

The tools in app/agent_tools.py are plain functions that call our API with the company's
key. Here each one is wrapped so that LiveKit can offer it to the AI model, the call runs
in a background thread (so the audio never stalls while the API answers) and the result is
noted for the call record. The company key stays inside the tools: the model never sees it.
"""
import asyncio
import functools
import inspect

from livekit.agents import function_tool

from app.agent_tools import make_tools


def adapt(fn, recorder):
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            result = await asyncio.to_thread(fn, *args, **kwargs)
        except Exception:
            recorder.tool_finished(fn.__name__, {"ok": False})
            raise
        recorder.tool_finished(fn.__name__, result)
        return result

    return function_tool(wrapper, name=fn.__name__, description=inspect.getdoc(fn))


def build_tools(api_key: str, session_id: str, recorder) -> list:
    return [adapt(fn, recorder) for fn in make_tools(api_key, session_id)]
