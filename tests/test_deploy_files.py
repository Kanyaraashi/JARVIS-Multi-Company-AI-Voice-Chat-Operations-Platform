"""Step 30: the deployment files. Docker itself is not run here, so these check the files' content."""
import pathlib
import re

import yaml

from app.voice import split_env

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load(name):
    return yaml.safe_load((ROOT / name).read_text())


def test_voice_compose_is_locked_down_and_gets_no_database_secrets():
    worker = load("docker-compose.voice.yml")["services"]["voice-worker"]
    assert worker["env_file"] == ".env.voice" and worker["restart"] == "unless-stopped"
    assert worker["read_only"] is True and "ALL" in worker["cap_drop"] and "no-new-privileges:true" in worker["security_opt"]
    assert worker["environment"]["JARVIS_API_BASE"].startswith("http://api:8000")
    assert "ports" not in worker                                           # nothing is opened to the internet
    assert not any("DATABASE" in k or "SECRET" in k for k in worker["environment"])


def test_dockerfile_runs_as_a_normal_user_in_production_mode():
    text = (ROOT / "Dockerfile.voice").read_text()
    assert re.search(r"^USER jarvis$", text, re.M) and 'CMD ["python", "voice_agent.py", "start"]' in text
    assert "COPY .env" not in text and "COPY . " not in text               # secrets are never baked into the image


def test_proxy_hides_internal_pages_and_closes_the_direct_api_port():
    compose = (ROOT / "docker-compose.proxy.yml").read_text()
    assert "!reset []" in compose and '"443:443"' in compose and "DOMAIN:?" in compose
    parsed = yaml.safe_load(compose.replace("!reset []", "[]"))
    assert parsed["services"]["caddy"]["image"].startswith("caddy:")
    caddy = (ROOT / "deploy" / "Caddyfile").read_text()
    assert "/internal/*" in caddy and "/docs" in caddy and "respond @private 404" in caddy
    assert "reverse_proxy api:8000" in caddy and "Strict-Transport-Security" in caddy


def test_split_env_keeps_only_voice_settings_and_never_prints_values(tmp_path, capsys):
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgresql://owner:secretpw@db/x\nN8N_WEBHOOK_SECRET=n8nsecret\nSTAFF=stf_abc\n"
        "LIVEKIT_URL=wss://x.livekit.cloud\nGEMINI_API_KEY=g123\nGEMINI_MODEL=gemini-3.1-flash-lite\n"
        "JARVIS_KEY_SMILE_DENTAL=jrv_d\nVOICE_NUMBERS=+918012345678=smile-dental\nVOICE_SPOOL_DIR=voice_spool\nEMPTY_ONE=\nVOICE_NOTE=hello world\n")
    assert split_env.main(folder=tmp_path) == 0
    out = capsys.readouterr().out
    written = (tmp_path / ".env.voice").read_text()
    for secret in ("secretpw", "n8nsecret", "stf_abc", "DATABASE_URL", "VOICE_SPOOL_DIR"):
        assert secret not in written
    assert "GEMINI_API_KEY=g123" in written and "JARVIS_KEY_SMILE_DENTAL=jrv_d" in written and 'VOICE_NOTE="hello world"' in written
    assert "g123" not in out and "jrv_d" not in out                         # values never shown on screen
    assert ".env.voice" in (tmp_path / ".gitignore").read_text()
    split_env.main(folder=tmp_path)                                          # a second run adds no duplicate line
    assert (tmp_path / ".gitignore").read_text().count(".env.voice") == 1


def test_split_env_refuses_without_env_or_voice_settings(tmp_path):
    assert split_env.main(folder=tmp_path) == 1
    (tmp_path / ".env").write_text("DATABASE_URL=x\n")
    assert split_env.main(folder=tmp_path) == 1
