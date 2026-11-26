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


def language_tool(switcher, recorder):
    async def switch_language(language: str) -> dict:
        """Change the language of this phone call. Call it as soon as the caller speaks or asks for a different language
        from the list on this line. Pass the language code, for example te-IN for Telugu, hi-IN for Hindi, ta-IN for Tamil,
        en-IN for English. After it returns ok, speak in that language."""
        result = switcher.switch(language)
        recorder.tool_finished("switch_language", result)
        return result

    return function_tool(switch_language, name="switch_language", description=inspect.getdoc(switch_language))


def build_tools(api_key: str, session_id: str, recorder, switcher=None) -> list:
    tools = [adapt(fn, recorder) for fn in make_tools(api_key, session_id)]
    if switcher is not None and len(switcher.allowed) > 1:
        tools.append(language_tool(switcher, recorder))
    return tools
