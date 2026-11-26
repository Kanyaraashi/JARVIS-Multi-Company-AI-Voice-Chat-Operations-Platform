"""Indian languages on phone calls: the list, the switcher, the Sarvam stack, the prompt, the checks."""
import asyncio
import base64

import httpx
import pytest
from livekit.agents import FunctionTool

from app import languages
from app.voice import config, preflight, providers, sarvam_check
from app.voice import tools as voice_tools
from app.voice.languages import LanguageSwitcher
from app.voice.prompt import LANGUAGE_RULES, VOICE_RULES, build_voice_prompt
from app.voice.recorder import CallRecorder

COMPANY = {"agent_name": "Maya", "name": "Smile Dental", "timezone": "Asia/Kolkata", "instructions": "Be kind."}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("VOICE_LANGUAGE", "VOICE_LANGUAGES", "CHAT_LANGUAGES", "SARVAM_STT_MODE", "SARVAM_STT_LANGUAGE", "SARVAM_SPEAKER"):
        monkeypatch.delenv(name, raising=False)


# ---------- the list ----------
def test_names_codes_and_scripts_are_understood():
    for text in ("te", "te-IN", "te_in", "TELUGU", " Telugu ", "తెలుగు"):
        assert languages.normalise(text) == "te-IN", text
    assert languages.normalise("हिन्दी") == "hi-IN" and languages.normalise("தமிழ்") == "ta-IN" and languages.normalise("Odia") == "od-IN"
    for bad in ("", "klingon", "xx-IN", None, 5, "te-US"):
        assert languages.normalise(bad) is None, bad


def test_every_language_has_a_name_in_its_own_script_and_a_test_sentence():
    assert len(languages.LANGUAGES) == 11
    for code, (english, native) in languages.LANGUAGES.items():
        assert english and native and code in sarvam_check.SENTENCES


def test_lists_keep_order_drop_repeats_and_refuse_unknown_languages():
    assert languages.parse_list("te-IN, Hindi , te, ta-IN") == ["te-IN", "hi-IN", "ta-IN"]
    with pytest.raises(SystemExit, match="not a supported language"):
        languages.parse_list("te-IN, martian")
    with pytest.raises(SystemExit, match="empty"):
        languages.parse_list(" , ")


def test_nothing_set_means_one_english_line_exactly_as_before():
    assert languages.voice_languages({}) == ["en-IN"]
    assert languages.voice_languages({"VOICE_LANGUAGE": "te-IN"}) == ["te-IN"]
    assert languages.voice_languages({"VOICE_LANGUAGES": "hi-IN,te-IN"}) == ["en-IN", "hi-IN", "te-IN"]
    assert languages.voice_languages({"VOICE_LANGUAGE": "te-IN", "VOICE_LANGUAGES": "en-IN,te-IN,ta-IN"}) == ["te-IN", "en-IN", "ta-IN"]
    assert languages.chat_languages({}) == ["en-IN", "hi-IN", "te-IN", "ta-IN"]
    assert languages.chat_languages({"CHAT_LANGUAGES": "te-IN"}) == ["te-IN"]


# ---------- the switcher ----------
class FakeVoice:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def update_options(self, **kwargs):
        if self.fail and kwargs.get("target_language_code") == "te-IN" or self.fail and kwargs.get("language") == "te-IN":
            raise RuntimeError("socket closed")
        self.calls.append(kwargs)


def test_switching_changes_the_voice_and_remembers_the_language():
    tts, stt = FakeVoice(), FakeVoice()
    s = LanguageSwitcher(["en-IN", "hi-IN", "te-IN"], tts=tts, stt=stt, stt_fixed=False)
    assert s.current == "en-IN"
    assert s.switch("Telugu") == {"ok": True, "language": "te-IN", "changed": True}
    assert tts.calls == [{"target_language_code": "te-IN"}] and stt.calls == [] and s.current == "te-IN"   # "auto" listener follows by itself
    assert s.switch("te-IN") == {"ok": True, "language": "te-IN", "changed": False} and len(tts.calls) == 1
    assert s.switch("hi") ["ok"] and s.history == ["en-IN", "te-IN", "hi-IN"]


def test_a_listener_told_one_fixed_language_is_switched_too_and_odia_uses_its_listener_code():
    tts, stt = FakeVoice(), FakeVoice()
    s = LanguageSwitcher(["en-IN", "od-IN"], tts=tts, stt=stt, stt_fixed=True)
    s.switch("od-IN")
    assert tts.calls == [{"target_language_code": "od-IN"}] and stt.calls == [{"language": "or-IN"}]


def test_a_language_the_line_does_not_offer_changes_nothing_and_says_what_is_available():
    tts = FakeVoice()
    s = LanguageSwitcher(["en-IN", "hi-IN"], tts=tts)
    for wish in ("Tamil", "klingon", "", "ta-IN"):
        result = s.switch(wish)
        assert result["ok"] is False and "English (en-IN), Hindi (hi-IN)" in result["error"]
    assert tts.calls == [] and s.current == "en-IN"


def test_if_the_voice_cannot_switch_the_call_stays_in_its_language():
    tts = FakeVoice(fail=True)
    s = LanguageSwitcher(["en-IN", "te-IN"], tts=tts)
    result = s.switch("te-IN")
    assert result["ok"] is False and "Continue in English" in result["error"] and s.current == "en-IN"


# ---------- the tool the AI can call ----------
def test_the_ai_gets_a_switch_language_tool_only_when_the_line_has_several_languages():
    recorder = CallRecorder("call-x", "web", None, {})
    plain = voice_tools.build_tools("jrv_x", "s", recorder)
    assert len(plain) == 12 and "switch_language" not in {t.info.name for t in plain}
    one = voice_tools.build_tools("jrv_x", "s", recorder, LanguageSwitcher(["en-IN"]))
    assert len(one) == 12
    tts = FakeVoice()
    many = voice_tools.build_tools("jrv_x", "s", recorder, LanguageSwitcher(["en-IN", "te-IN"], tts=tts))
    assert len(many) == 13 and all(isinstance(t, FunctionTool) for t in many)
    tool = {t.info.name: t for t in many}["switch_language"]
    assert "te-IN" in tool.info.description and "language" in str(tool.info)
    result = asyncio.run(tool(language="Telugu"))
    assert result["ok"] is True and tts.calls == [{"target_language_code": "te-IN"}]


# ---------- the prompt ----------
def test_an_english_only_line_gets_exactly_the_old_prompt():
    assert build_voice_prompt(COMPANY).endswith(VOICE_RULES)
    assert build_voice_prompt(COMPANY, ["en-IN"]) == build_voice_prompt(COMPANY)


def test_a_multi_language_prompt_lists_the_languages_the_start_language_and_the_rules():
    prompt = build_voice_prompt(COMPANY, ["te-IN", "en-IN", "hi-IN"])
    assert prompt.endswith(LANGUAGE_RULES.format(listed=languages.list_for_prompt(["te-IN", "en-IN", "hi-IN"]), start="Telugu"))
    assert "Telugu (తెలుగు, code te-IN)" in prompt and "English (code en-IN)" in prompt and "Every call starts in Telugu" in prompt
    assert "switch_language" in prompt and "own script" in prompt and "YYYY-MM-DD" in prompt and VOICE_RULES in prompt
    assert "Telugu" in build_voice_prompt(COMPANY, ["te-IN"])           # a single non-English line still says so


# ---------- the Sarvam stack ----------
@pytest.fixture
def sarvam_env(monkeypatch):
    monkeypatch.setenv("VOICE_STACK", "sarvam")
    monkeypatch.setenv("SARVAM_API_KEY", "sv_test")
    monkeypatch.setenv("GEMINI_API_KEY", "g_test")
    monkeypatch.delenv("GEMINI_FALLBACK_MODELS", raising=False)


def test_several_languages_make_the_listener_adaptive_and_add_a_switcher(sarvam_env, monkeypatch):
    monkeypatch.setenv("VOICE_LANGUAGES", "hi-IN,te-IN,ta-IN")
    built = providers.build_session_parts()
    switcher = built["switcher"]
    assert switcher.allowed == ["en-IN", "hi-IN", "te-IN", "ta-IN"] and switcher.stt_fixed is False
    assert built["names"]["stt"] == "sarvam realtime" and built["names"]["languages"] == "en-IN,hi-IN,te-IN,ta-IN"
    assert built["kwargs"]["turn_handling"] == {"turn_detection": "stt"}


def test_one_language_listens_for_that_language_and_has_no_switcher(sarvam_env, monkeypatch):
    monkeypatch.setenv("VOICE_LANGUAGE", "te-IN")
    built = providers.build_session_parts()
    assert built["switcher"] is None and built["names"]["languages"] == "te-IN"


def test_a_fixed_listener_language_can_be_forced_and_then_follows_the_switch(sarvam_env, monkeypatch):
    monkeypatch.setenv("VOICE_LANGUAGES", "te-IN")
    monkeypatch.setenv("SARVAM_STT_LANGUAGE", "hi-IN")
    assert providers.build_session_parts()["switcher"].stt_fixed is True


def test_standard_listener_mode_uses_voice_detection_instead_of_the_realtime_stream(sarvam_env, monkeypatch):
    monkeypatch.setenv("SARVAM_STT_MODE", "standard")
    monkeypatch.setenv("VOICE_LANGUAGES", "te-IN")
    built = providers.build_session_parts()
    assert built["names"]["stt"] == "sarvam saaras:v4" and "vad" in built["kwargs"] and "turn_handling" not in built["kwargs"]


def test_a_wrong_listener_mode_or_language_stops_with_a_clear_message(sarvam_env, monkeypatch):
    monkeypatch.setenv("SARVAM_STT_MODE", "turbo")
    with pytest.raises(SystemExit, match="realtime or standard"):
        providers.build_session_parts()
    monkeypatch.setenv("SARVAM_STT_MODE", "realtime")
    monkeypatch.setenv("VOICE_LANGUAGES", "te-IN,martian")
    with pytest.raises(SystemExit, match="martian"):
        providers.build_session_parts()


def test_deepgram_is_untouched_by_the_language_settings(monkeypatch):
    monkeypatch.setenv("VOICE_STACK", "deepgram")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg_test")
    monkeypatch.setenv("GEMINI_API_KEY", "g_test")
    monkeypatch.delenv("GEMINI_FALLBACK_MODELS", raising=False)
    assert providers.build_session_parts()["switcher"] is None


# ---------- preflight ----------
def test_preflight_says_nothing_for_a_plain_english_line_and_helps_for_the_rest():
    assert preflight.check_languages({}) == [] and preflight.check_languages({"VOICE_LANGUAGE": "en-IN"}) == []
    ok = preflight.check_languages({"VOICE_STACK": "sarvam", "VOICE_LANGUAGES": "hi-IN,te-IN"})
    assert [r.level for r in ok] == ["OK"] and "calls start in English; allowed: English, Hindi, Telugu" in ok[0].message
    warn = preflight.check_languages({"VOICE_STACK": "deepgram", "VOICE_LANGUAGES": "te-IN"})
    assert warn[0].level == "WARN" and "VOICE_STACK=sarvam" in warn[0].message
    assert preflight.check_languages({"VOICE_LANGUAGES": "te-IN,martian"})[0].level == "FAIL"
    assert preflight.check_languages({"VOICE_LANGUAGE": "zz"})[0].level == "FAIL"
    assert preflight.check_languages({"VOICE_STACK": "sarvam", "VOICE_LANGUAGES": "te-IN", "SARVAM_STT_MODE": "turbo"})[-1].level == "FAIL"


# ---------- the Sarvam voice check ----------
class FakeResponse:
    def __init__(self, status=200, body=None, text=""):
        self.status_code, self._body, self.text = status, body, text

    def json(self):
        return self._body


def test_the_voice_check_saves_one_wav_per_language_and_never_prints_the_key(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SARVAM_API_KEY", "sv_SECRET_KEY_123")
    sent = []

    def post(url, headers, json, timeout):
        sent.append((url, headers["api-subscription-key"], json))
        return FakeResponse(200, {"audios": [base64.b64encode(b"RIFFfakewav").decode()]})

    assert sarvam_check.main(["--languages", "te-IN,Hindi", "--speaker", "priya"], post=post, folder=tmp_path / "t") == 0
    out = capsys.readouterr().out
    assert "sv_SECRET" not in out and "Telugu (te-IN): ok" in out and "Hindi (hi-IN): ok" in out
    assert (tmp_path / "t" / "te-IN.wav").read_bytes() == b"RIFFfakewav" and (tmp_path / "t" / "hi-IN.wav").exists()
    assert sent[0][0] == "https://api.sarvam.ai/text-to-speech" and sent[0][1] == "sv_SECRET_KEY_123"
    body = sent[0][2]
    assert body["language_code"] == "te-IN" and body["model"] == "bulbul:v3" and body["speaker"] == "priya" and "తెలుగు" not in body["text"][:0] and body["text"]


@pytest.mark.parametrize("status,words", [(401, "refused the key"), (429, "no credit"), (500, "answered 500")])
def test_the_voice_check_explains_a_refused_key_no_credit_or_an_error(monkeypatch, tmp_path, capsys, status, words):
    monkeypatch.setenv("SARVAM_API_KEY", "sv_k")
    post = lambda url, headers, json, timeout: FakeResponse(status, None, "oops")
    assert sarvam_check.main(["--languages", "te-IN,ta-IN"], post=post, folder=tmp_path / "t") == 1
    out = capsys.readouterr().out
    assert "[FAIL]" in out and words in out


def test_the_voice_check_handles_no_internet_a_missing_key_and_a_bad_language(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    assert sarvam_check.main([], folder=tmp_path / "t") == 1 and "SARVAM_API_KEY is missing" in capsys.readouterr().out
    monkeypatch.setenv("SARVAM_API_KEY", "sv_k")

    def offline(url, headers, json, timeout):
        raise httpx.ConnectError("no network")

    assert sarvam_check.main(["--languages", "te-IN"], post=offline, folder=tmp_path / "t") == 1
    assert "could not reach Sarvam" in capsys.readouterr().out
    assert sarvam_check.main(["--languages", "martian"], folder=tmp_path / "t") == 1


def test_the_sarvam_listener_language_mapping_is_consistent_with_the_check():
    assert config.language() == "en-IN" and languages.STT_CODE == {"od-IN": "or-IN"}
