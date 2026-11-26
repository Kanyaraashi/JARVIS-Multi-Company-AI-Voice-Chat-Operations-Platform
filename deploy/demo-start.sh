#!/usr/bin/env bash
# Starts the API (port 8000), the customer chat (port 8100) and Caddy (the public $PORT) in ONE container.
# If any of the three stops, the whole container stops so Render restarts it cleanly.
# The chat is started WITHOUT the database settings and the API WITHOUT the AI keys, so each keeps only what it needs.
set -u
export PORT="${PORT:-10000}"
export XDG_DATA_HOME=/tmp/caddy-data XDG_CONFIG_HOME=/tmp/caddy-config

if [ -z "${DATABASE_URL:-}" ]; then echo "DATABASE_URL is not set"; exit 1; fi

api_unset=(-u GEMINI_API_KEY)
chat_unset=(-u DATABASE_URL -u ADMIN_DATABASE_URL -u JARVIS_APP_DB_PASSWORD -u N8N_WEBHOOK_SECRET)
for name in $(compgen -e); do
  case "$name" in JARVIS_KEY_*|CHAT_CODE_*|CHAT_PHONE_*) api_unset+=(-u "$name");; esac
done

env "${api_unset[@]}" uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --no-access-log &
env "${chat_unset[@]}" API_BASE_URL=http://127.0.0.1:8000 \
  uvicorn app.webchat.server:app --host 127.0.0.1 --port 8100 --proxy-headers --no-access-log &
caddy run --config /app/deploy/Caddyfile.demo --adapter caddyfile &

wait -n
code=$?
echo "A process stopped (exit $code). Stopping the container so it restarts."
exit "$code"
