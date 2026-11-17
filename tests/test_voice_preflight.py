import json

import httpx
import pytest

from app.voice import phone_setup, preflight

GOOD = {
    "LIVEKIT_URL": "wss://x.livekit.cloud", "LIVEKIT_API_KEY": "k", "LIVEKIT_API_SECRET": "s",
    "VOICE_STACK": "deepgram", "DEEPGRAM_API_KEY": "d", "GEMINI_API_KEY": "g",
    "GEMINI_MODEL": "gemini-3.1-flash-lite", "GEMINI_FALLBACK_MODELS": "gemini-3.5-flash-lite",
    "VOICE_NUMBERS": "+918012345678=smile-dental,+14155550100=shopeasy",
    "JARVIS_KEY_SMILE_DENTAL": "jrv_dental", "JARVIS_KEY_SHOPEASY": "jrv_shop",
    "VOICE_SPOOL_DIR": "/nonexistent-spool",
}
NAMES = {"jrv_dental": ("smile-dental", "Smile Dental"), "jrv_shop": ("shopeasy", "ShopEasy")}


def fake_get(health=200, names=NAMES, down=False):
    def get(url, headers=None, timeout=None):
        if down:
            raise httpx.ConnectError("down")
        request = httpx.Request("GET", url)
        if url.endswith("/health"):
            return httpx.Response(health, request=request)
        who = names.get((headers or {}).get("X-API-Key"))
        if not who:
            return httpx.Response(401, request=request)
        return httpx.Response(200, json={"slug": who[0], "name": who[1]}, request=request)
    return get


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for k in list(__import__("os").environ):
        if k.startswith(("VOICE_", "JARVIS_KEY_")):
            monkeypatch.delenv(k)


def levels(env, **kw):
    for k, v in env.items():
        pass
    return preflight.run(env, fake_get(**kw))


def apply(monkeypatch, env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)


def test_a_complete_setup_has_no_failures(monkeypatch):
    apply(monkeypatch, GOOD)
    results = levels(GOOD)
    assert [r for r in results if r.level == "FAIL"] == []
    assert any(r.name == "company smile-dental" and r.level == "OK" for r in results)


def test_missing_pieces_are_named_without_printing_secrets(monkeypatch, capsys):
    env = dict(GOOD); env.pop("LIVEKIT_API_SECRET"); env.pop("DEEPGRAM_API_KEY"); env["GEMINI_MODEL"] = "gemini-flash-latest"
    apply(monkeypatch, env)
    code = preflight.main([], env=env, get=fake_get())
    out = capsys.readouterr().out
    assert code == 1
    assert "LIVEKIT_API_SECRET is missing" in out and "DEEPGRAM_API_KEY is missing" in out and "aliases" in out
    for secret in ("jrv_dental", "jrv_shop", "wss://x"):
        assert secret not in out.replace("wss://x.livekit.cloud", "") or secret != "jrv_dental"
    assert "jrv_dental" not in out and "jrv_shop" not in out


def test_a_key_that_opens_another_companys_data_is_a_failure(monkeypatch):
    apply(monkeypatch, GOOD)
    swapped = {"jrv_dental": ("shopeasy", "ShopEasy"), "jrv_shop": ("shopeasy", "ShopEasy")}
    r = [x for x in levels(GOOD, names=swapped) if x.name == "company smile-dental"][0]
    assert r.level == "FAIL" and "different company" in r.message


def test_unreachable_api_and_refused_keys_give_clear_advice(monkeypatch):
    apply(monkeypatch, GOOD)
    down = levels(GOOD, down=True)
    assert any(r.name == "api" and r.level == "FAIL" and "docker compose up" in r.message for r in down)
    refused = [x for x in levels(GOOD, names={}) if x.name == "company shopeasy"][0]
    assert refused.level == "FAIL" and "refused" in refused.message


def test_phone_numbers_must_be_international_and_every_line_needs_a_key(monkeypatch):
    env = dict(GOOD, VOICE_NUMBERS="9876543210=smile-dental,+14155550100=shopeasy"); env.pop("JARVIS_KEY_SHOPEASY")
    apply(monkeypatch, env)
    results = levels(env)
    assert any("international form" in r.message for r in results)
    assert any(r.name == "company shopeasy" and "JARVIS_KEY_SHOPEASY" in r.message for r in results)


def test_default_company_is_a_warning_in_testing_and_a_failure_in_production(monkeypatch):
    env = dict(GOOD, VOICE_DEFAULT_COMPANY="smile-dental"); apply(monkeypatch, env)
    assert [r.level for r in preflight.run(env, fake_get()) if r.name == "default company"] == ["WARN"]
    assert [r.level for r in preflight.run(env, fake_get(), production=True) if r.name == "default company"] == ["FAIL"]


def test_one_model_is_a_warning_and_waiting_spooled_calls_are_reported(monkeypatch, tmp_path):
    (tmp_path / "a.json").write_text("{}")
    env = dict(GOOD, GEMINI_FALLBACK_MODELS="", VOICE_SPOOL_DIR=str(tmp_path)); apply(monkeypatch, env)
    results = levels(env)
    assert any(r.name == "models" and r.level == "WARN" for r in results)
    assert any(r.name == "unsent calls" and r.level == "WARN" and "1 call record" in r.message for r in results)


def test_phone_setup_writes_both_files_and_refuses_bad_numbers(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("VOICE_NUMBERS", "+918012345678=smile-dental,+14155550100=shopeasy")
    assert phone_setup.main(["--out", str(tmp_path)]) == 0
    trunk = json.loads((tmp_path / "inbound-trunk.json").read_text())
    rule = json.loads((tmp_path / "dispatch-rule.json").read_text())
    assert trunk["trunk"]["numbers"] == ["+14155550100", "+918012345678"]
    assert rule["dispatch_rule"]["rule"]["dispatch_rule_individual"]["room_prefix"] == "call-"
    assert rule["dispatch_rule"]["room_config"]["agents"] == [{"agent_name": "jarvis"}]
    assert "lk sip inbound create" in capsys.readouterr().out
    monkeypatch.setenv("VOICE_NUMBERS", "98765=smile-dental")
    assert phone_setup.main(["--out", str(tmp_path / "x")]) == 1
    monkeypatch.setenv("VOICE_NUMBERS", "")
    assert phone_setup.main(["--out", str(tmp_path / "y")]) == 1


def test_a_number_setting_with_letters_is_caught_before_it_crashes_the_program(monkeypatch):
    env = dict(GOOD, AI_ATTEMPTS_PER_MODEL="2s", VOICE_FIRST_TOKEN_SECONDS="6 seconds", AI_RETRY_DELAY_SECONDS="1.5")
    apply(monkeypatch, env)
    bad = [r for r in levels(env) if r.level == "FAIL"]
    assert {r.name for r in bad} == {"ai attempts per model", "voice first token seconds"}
    assert "without letters" in bad[0].message and "'2s'" in [r.message for r in bad if "attempts" in r.name][0]
    assert any(r.name == "number settings" for r in levels(GOOD))


def test_dispatch_rule_can_be_tied_to_a_phone_number_or_trunk(tmp_path, monkeypatch):
    from app.voice import phone_setup
    monkeypatch.setenv("VOICE_NUMBERS", "+14155550100=smile-dental")
    assert phone_setup.main(["--out", str(tmp_path), "--trunk-id", "PN_abc123XYZ"]) == 0
    rule = json.loads((tmp_path / "dispatch-rule.json").read_text())["dispatch_rule"]
    assert rule["trunk_ids"] == ["PN_abc123XYZ"] and rule["rule"]["dispatch_rule_individual"]["room_prefix"] == "call-"
    assert phone_setup.main(["--out", str(tmp_path)]) == 0
    assert "trunk_ids" not in json.loads((tmp_path / "dispatch-rule.json").read_text())["dispatch_rule"]


def test_a_real_livekit_number_id_with_an_underscore_inside_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_NUMBERS", "+14155550100=smile-dental")
    assert phone_setup.main(["--out", str(tmp_path), "--trunk-id", "PN_PPN_ShLxrppoNLze"]) == 0


def test_a_wrong_looking_trunk_id_is_refused(tmp_path, monkeypatch, capsys):
    from app.voice import phone_setup
    monkeypatch.setenv("VOICE_NUMBERS", "+14155550100=smile-dental")
    for bad in ("PPN_XXXXXXX", "SDR_abcdef12", "PN_", "abc"):
        assert phone_setup.main(["--out", str(tmp_path), "--trunk-id", bad]) == 1
    assert not (tmp_path / "dispatch-rule.json").exists() and "PN_" in capsys.readouterr().out
