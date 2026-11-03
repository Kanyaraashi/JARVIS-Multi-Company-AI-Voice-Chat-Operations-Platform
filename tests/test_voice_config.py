"""Which company does a call belong to, and are the speech stacks built correctly?"""
import pytest

from app.voice import config, providers


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("VOICE_NUMBERS", "+91 80 1234 5678=smile-dental, +14155550100=shopeasy")
    monkeypatch.delenv("VOICE_DEFAULT_COMPANY", raising=False)
    monkeypatch.setenv("JARVIS_KEY_SMILE_DENTAL", "jrv_x")


# ---------- the company comes from the dialled number, never from the caller ----------

def test_a_phone_call_belongs_to_the_company_that_owns_the_dialled_number():
    assert config.resolve_company("call-abc", {"sip.trunkPhoneNumber": "+918012345678"}) == ("smile-dental", "inbound")
    assert config.resolve_company("call-abc", {"sip.trunkPhoneNumber": "+14155550100"}) == ("shopeasy", "inbound")
    assert config.resolve_company("call-abc", {"sip.trunkPhoneNumber": "+91 80-1234-5678"}) == ("smile-dental", "inbound")


def test_a_phone_call_to_an_unknown_number_is_refused_not_given_a_default(monkeypatch):
    monkeypatch.setenv("VOICE_DEFAULT_COMPANY", "smile-dental")
    assert config.resolve_company("call-abc", {"sip.trunkPhoneNumber": "+919999999999"}) is None
    assert config.resolve_company("call-abc", {}) is None


def test_a_phone_call_cannot_pick_a_company_through_its_room_name_or_other_attributes():
    attrs = {"company": "shopeasy", "sip.trunkPhoneNumber": "+918012345678"}
    assert config.resolve_company("call-web-shopeasy-abc", attrs) == ("smile-dental", "inbound")


def test_browser_test_rooms_carry_the_company_in_their_name():
    assert config.resolve_company("web-smile-dental-a1b2c3", {}) == ("smile-dental", "web")
    assert config.resolve_company("web-shopeasy-ff00ee", {}) == ("shopeasy", "web")


def test_a_browser_room_ignores_phone_attributes():
    assert config.resolve_company("web-shopeasy-ff00ee", {"sip.trunkPhoneNumber": "+918012345678"}) == ("shopeasy", "web")


@pytest.mark.parametrize("room", ["", "lobby", "web-", "web-UPPER-abc123", "web-bad slug-abc123", "web--abc123", "xcall-1"])
def test_rooms_that_do_not_follow_the_rules_are_refused(room):
    assert config.resolve_company(room, {}) is None


def test_console_mode_uses_the_default_company_only_if_one_is_set(monkeypatch):
    assert config.resolve_company("", {}, is_console=True) is None
    monkeypatch.setenv("VOICE_DEFAULT_COMPANY", "smile-dental")
    assert config.resolve_company("", {}, is_console=True) == ("smile-dental", "web")


def test_other_test_rooms_use_the_default_company_only_when_one_is_set(monkeypatch):
    assert config.resolve_company("console-4821", {}) is None
    monkeypatch.setenv("VOICE_DEFAULT_COMPANY", "smile-dental")
    assert config.resolve_company("console-4821", {}) == ("smile-dental", "web")
    assert config.resolve_company("lobby", {}) == ("smile-dental", "web")
    # the default never applies to phone rooms or to malformed browser-test rooms
    assert config.resolve_company("call-abc", {}) is None
    assert config.resolve_company("web-UPPER-abc123", {}) is None


def test_company_keys_come_from_env_by_slug(monkeypatch):
    assert config.company_key("smile-dental") == "jrv_x"
    assert config.company_key("unknown-co") is None


def test_a_wrong_stack_name_stops_with_a_clear_message(monkeypatch):
    monkeypatch.setenv("VOICE_STACK", "magic")
    with pytest.raises(SystemExit, match="VOICE_STACK"):
        config.stack()


# ---------- the two speech stacks ----------

def test_deepgram_stack_builds(monkeypatch):
    monkeypatch.setenv("VOICE_STACK", "deepgram")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg_test")
    monkeypatch.setenv("GEMINI_API_KEY", "g_test")
    monkeypatch.delenv("GEMINI_FALLBACK_MODELS", raising=False)
    built = providers.build_session_parts()
    kwargs = built["kwargs"]
    assert {"stt", "tts", "llm", "vad"} <= set(kwargs)
    assert kwargs["preemptive_generation"] is False  # no early answers before the caller finished
    assert built["names"]["stack"] == "deepgram" and "nova-3" in built["names"]["stt"]


def test_sarvam_stack_builds_and_lets_sarvam_decide_when_the_caller_stopped(monkeypatch):
    monkeypatch.setenv("VOICE_STACK", "sarvam")
    monkeypatch.setenv("SARVAM_API_KEY", "sv_test")
    monkeypatch.setenv("GEMINI_API_KEY", "g_test")
    kwargs = providers.build_session_parts()["kwargs"]
    assert kwargs["turn_handling"] == {"turn_detection": "stt"} and "vad" not in kwargs


def test_missing_speech_keys_stop_with_a_clear_message(monkeypatch):
    monkeypatch.setenv("VOICE_STACK", "deepgram")
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="DEEPGRAM_API_KEY"):
        providers.build_session_parts()
    monkeypatch.setenv("VOICE_STACK", "sarvam")
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="SARVAM_API_KEY"):
        providers.build_session_parts()


def test_several_gemini_models_become_a_failover_chain(monkeypatch):
    from livekit.agents import llm
    monkeypatch.setenv("GEMINI_API_KEY", "g_test")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "gemini-2.5-flash, gemini-3.1-flash-lite")
    chain = providers.build_llm()
    assert isinstance(chain, llm.FallbackAdapter)
    monkeypatch.delenv("GEMINI_FALLBACK_MODELS")
    assert not isinstance(providers.build_llm(), llm.FallbackAdapter)


# ---------- the browser test token ----------

def test_the_browser_token_is_for_one_room_and_dispatches_the_agent(monkeypatch):
    import jwt
    from app.voice.make_token import make_token
    monkeypatch.setenv("LIVEKIT_API_KEY", "devkey")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "x" * 40)
    room, token = make_token("smile-dental")
    claims = jwt.decode(token, "x" * 40, algorithms=["HS256"], options={"verify_aud": False})
    assert room.startswith("web-smile-dental-") and claims["video"]["room"] == room
    assert claims["video"]["roomJoin"] is True
    assert claims["roomConfig"]["agents"][0]["agentName"] == "jarvis"
    assert config.resolve_company(room, {}) == ("smile-dental", "web")
    assert claims["exp"] - claims["nbf"] <= 15 * 60 + 5
