"""The JARVIS voice agent (Step 22).

Run it (from the project folder, using the launcher voice_agent.py):
    python voice_agent.py dev        connects to LiveKit; handles browser and phone calls
    python voice_agent.py console    talk through this computer's microphone (no LiveKit)

One agent process serves every company. For each call it works out the company (see
config.resolve_company), builds the company's prompt and tools, talks, and finally saves
a call record.
"""
import asyncio
import logging
import uuid

import httpx
from dotenv import load_dotenv

load_dotenv()

from livekit.agents import Agent, AgentServer, AgentSession, JobContext  # noqa: E402

from app import languages  # noqa: E402
from app.agent import handoff  # noqa: E402
from app.agent_tools import API_BASE  # noqa: E402
from app.privacy import install_log_redaction  # noqa: E402
from app.voice import config, providers  # noqa: E402
from app.voice.prompt import build_voice_prompt  # noqa: E402
from app.voice.fast_llm import Hooks  # noqa: E402
from app.voice.recorder import CallRecorder, send, spool  # noqa: E402
from app.voice.tools import build_tools  # noqa: E402

install_log_redaction()  # phone numbers, emails and keys never reach the logs
log = logging.getLogger("jarvis.voice")

GOODBYE_TIME = "I'm sorry, we have reached the time limit for this call. Please call again if you need anything else. Goodbye."
APOLOGY = "I'm sorry, I'm having technical trouble right now. Please try again in a few minutes."
CAP_MESSAGE = "Thank you for calling. Our phone assistant is not available right now. Please contact us by email or call back later. Goodbye."
GOODBYE_SILENT = "I can't hear you, so I'll end the call now. Please call again any time. Goodbye."


class JarvisAgent(Agent):
    def __init__(self, instructions: str, tools: list, greeting: str, greeting_language: str = ""):
        super().__init__(instructions=instructions, tools=tools)
        self._greeting = greeting
        self._greeting_language = greeting_language

    async def on_enter(self) -> None:
        if not self._greeting:
            return
        if self._greeting_language and self._greeting_language != "en-IN":
            # The company greeting is written in English: have the AI say it in the call's first language.
            self.session.generate_reply(instructions=(
                f"Greet the caller in {languages.english_name(self._greeting_language)} by saying this greeting, "
                f"translated naturally into that language and written in its own script: {self._greeting}"))
        else:
            self.session.say(self._greeting)  # fixed text: no AI delay before the first words


def cap_reached(api_key: str, api_base: str = API_BASE, get=httpx.get) -> bool:
    """True when the company has used up its monthly minutes. If the API cannot answer,
    the call goes ahead (a customer is never turned away because of OUR counting problem)."""
    try:
        r = get(api_base + "/company/usage", headers={"X-API-Key": api_key}, timeout=5)
        r.raise_for_status()
        return r.json().get("allowed") is False
    except Exception as exc:
        log.warning("Could not check the monthly limit (%s); letting the call through.", type(exc).__name__)
        return False


def bind_hooks(hooks: Hooks, recorder: CallRecorder) -> None:
    """Lets the call record learn when the AI was slow, a filler was said, or a backup answered."""
    hooks.on_first_token = recorder.note_first_token
    hooks.on_filler = recorder.note_filler

    def switched(from_model: str, to_model: str, reason: str) -> None:
        log.warning("AI model %s -> %s (%s). The caller was not told.", from_model, to_model, reason)
        recorder.note_switch(from_model, to_model, reason)

    hooks.on_switch = switched


def wire_events(session, recorder: CallRecorder, hang_up) -> None:
    """Connects the voice session to the call recorder."""
    recorder.not_answers.add(APOLOGY)

    @session.on("conversation_item_added")
    def _item(event):
        item = event.item
        if getattr(item, "type", None) == "message":
            recorder.on_message(item.role, item.text_content, dict(item.metrics or {}))

    @session.on("close")
    def _closed(event):
        if getattr(event, "error", None) is not None:
            recorder.mark_failed()

    apologised = {"done": False}

    @session.on("error")
    def _error(event):
        recorder.on_error()
        error = getattr(event, "error", None)
        gave_up = getattr(error, "recoverable", True) is False or recorder.errors >= 2
        if gave_up and not apologised["done"]:
            apologised["done"] = True  # speak once; the voice works even when the AI model does not
            try:
                session.say(APOLOGY)
            except Exception:
                log.exception("could not speak the apology")

    away = {"count": 0}

    @session.on("user_state_changed")
    def _user_state(event):
        if event.new_state != "away":
            away["count"] = 0
            return
        away["count"] += 1
        if away["count"] >= 2:  # silent twice in a row: end the call, do not burn minutes
            asyncio.ensure_future(hang_up(GOODBYE_SILENT))
        else:
            session.generate_reply(instructions="Politely ask the caller if they are still there.")


async def save_call(recorder: CallRecorder, slug: str, api_key: str, api_base: str = API_BASE) -> str:
    """Saves the call record. Returns what happened, in words, for the log."""
    payload = recorder.payload()
    saved, reason = await asyncio.to_thread(send, api_base, api_key, payload)
    if saved:
        result = f"call record saved ({payload['outcome']})"
    else:
        path = spool(slug, payload, reason)
        result = f"call record NOT saved ({reason}); kept in {path}"
    if payload["outcome"] == "failed":
        # Same promise as the chat agent: a caller whose call broke is never dropped.
        sent = await asyncio.to_thread(
            handoff, api_key, recorder.last_user_text() or "(the caller said nothing)",
            recorder.caller_phone, recorder.room_name,
        )
        result += "; callback request recorded" if sent else "; callback request could NOT be recorded"
    return result


async def entrypoint(ctx: JobContext) -> None:  # pragma: no cover (needs a live call)
    console = ctx.is_fake_job()
    attributes: dict = {}
    if not console:
        await ctx.connect()
        participant = await ctx.wait_for_participant()
        attributes = dict(participant.attributes)

    room_name = ctx.room.name if not console else f"web-console-{uuid.uuid4().hex[:6]}"
    resolved = config.resolve_company(room_name if not console else "", attributes, console)
    if resolved is None:
        log.error("Refusing call in room %s: it does not belong to any company line.", room_name)
        ctx.shutdown(reason="unknown line")
        return
    slug, direction = resolved
    api_key = config.company_key(slug)
    if not api_key:
        log.error("No key for company %s in .env", slug)
        ctx.shutdown(reason="no company key")
        return

    try:
        response = await asyncio.to_thread(
            httpx.get, API_BASE + "/company/me", headers={"X-API-Key": api_key}, timeout=10
        )
        response.raise_for_status()
        company = response.json()
    except Exception as exc:  # the API is down: better to hang up than to talk without tools
        log.error("Could not load company %s (%s). Is the JARVIS API running?", slug, type(exc).__name__)
        ctx.shutdown(reason="api unavailable")
        return

    blocked = await asyncio.to_thread(cap_reached, api_key)
    if blocked:
        log.warning("Company %s used all its monthly minutes: telling the caller and hanging up.", slug)
    hooks = Hooks()
    parts = providers.build_session_parts(hooks)
    caller = attributes.get("sip.phoneNumber") if direction == "inbound" else None
    recorder = CallRecorder(room_name, direction, caller, parts["names"])
    bind_hooks(hooks, recorder)
    session = AgentSession(**parts["kwargs"])
    switcher = parts["switcher"]
    allowed = switcher.allowed if switcher else languages.voice_languages()
    agent = JarvisAgent(
        build_voice_prompt(company, allowed),
        [] if blocked else build_tools(api_key, uuid.uuid4().hex, recorder, switcher),
        "" if blocked else company["greeting"],
        allowed[0],
    )

    async def hang_up(message: str) -> None:
        try:
            await session.say(message, allow_interruptions=False)
        except Exception:
            log.exception("could not say goodbye")
        ctx.shutdown(reason="call ended by agent")

    async def time_limit() -> None:
        await asyncio.sleep(config.max_call_minutes() * 60)
        await hang_up(GOODBYE_TIME)

    wire_events(session, recorder, hang_up)
    limit_task = {"task": None}

    async def finish() -> None:
        if limit_task["task"]:
            limit_task["task"].cancel()
        log.info("%s: %s", room_name, await save_call(recorder, slug, api_key))

    ctx.add_shutdown_callback(finish)
    await session.start(agent=agent, room=ctx.room)
    if blocked:
        await hang_up(CAP_MESSAGE)
        return
    limit_task["task"] = asyncio.create_task(time_limit())
    log.info("Call started: company=%s direction=%s room=%s stack=%s languages=%s", slug, direction, room_name, config.stack(), ",".join(allowed))


server = AgentServer()
server.rtc_session(entrypoint, agent_name=config.AGENT_NAME)
