"""The one-container public demo (Render): files are consistent and carry no secrets."""
import pathlib
import subprocess

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_start_script_is_valid_and_separates_secrets():
    script = ROOT / "deploy" / "demo-start.sh"
    assert subprocess.run(["bash", "-n", str(script)]).returncode == 0
    text = script.read_text()
    assert "-u DATABASE_URL" in text and "-u ADMIN_DATABASE_URL" in text and "-u JARVIS_APP_DB_PASSWORD" in text   # chat gets no database
    assert "-u GEMINI_API_KEY" in text and "JARVIS_KEY_*" in text                                                   # API gets no AI keys
    assert "--host 127.0.0.1" in text and "0.0.0.0" not in text                                                    # only Caddy is public
    assert "API_BASE_URL=http://127.0.0.1:8000" in text and "wait -n" in text


def test_caddy_demo_routes_chat_and_hides_internal_pages():
    caddy = (ROOT / "deploy" / "Caddyfile.demo").read_text()
    assert ":{$PORT}" in caddy and "auto_https off" in caddy and "admin off" in caddy
    assert "/internal/*" in caddy and "respond @private 404" in caddy
    assert "handle /c/*" in caddy and "127.0.0.1:8100" in caddy and "reverse_proxy 127.0.0.1:8000" in caddy


def test_dockerfile_runs_as_normal_user_and_copies_what_it_starts():
    d = (ROOT / "Dockerfile.demo").read_text()
    assert "USER jarvis" in d and "demo-start.sh" in d and "Caddyfile.demo" in d and "COPY app ./app" in d
    assert "sed -i" in d and "requirements-chat.txt" in d and "/usr/bin/caddy" in d


def test_render_blueprint_holds_no_secret_values():
    data = yaml.safe_load((ROOT / "render.yaml").read_text())
    service = data["services"][0]
    assert service["plan"] == "free" and service["runtime"] == "docker" and service["dockerfilePath"] == "./Dockerfile.demo"
    for env in service["envVars"]:
        if env["key"] in ("DATABASE_URL", "GEMINI_API_KEY", "PUBLIC_BASE_URL") or env["key"].startswith(("JARVIS_KEY_", "CHAT_CODE_")):
            assert env.get("sync") is False and "value" not in env, env["key"]        # typed into the dashboard, never in git
    assert {e["key"] for e in service["envVars"]} >= {"DATABASE_URL", "GEMINI_API_KEY", "PUBLIC_BASE_URL", "TRUSTED_PROXY_COUNT"}
