# JARVIS deployment guide (Step 30)

Goal: JARVIS keeps answering calls when your PC is off, and staff open the dashboard over HTTPS.
Do this only after the local test call works (Steps 22 to 29).

## What you will have
- A small Linux server (a "VPS") running Docker.
- Your existing containers (API, database, n8n) plus the **voice worker** and **Caddy** (HTTPS).
- A domain name, for example `jarvis.yourcompany.com`, pointing at the server.

## What I could not test for you
I cannot run Docker on your server or reach the internet from my workspace. The compose files were checked with Docker's own parser, but the first real start is yours. If something fails, send me the exact error and the step number.

## 1. Before you start (on your PC)
1. Commit and push your code to GitHub (private repository).
2. Run the checker: `python -m app.voice.preflight --production`. Fix every FAIL. In production `VOICE_DEFAULT_COMPANY` must be empty.
3. Create the voice-only settings file: `python -m app.voice.split_env`. It writes `.env.voice` (not committed).

## 2. Get a server and a domain
- Any Ubuntu 22.04 or 24.04 server with 2 GB RAM or more works. Choose a region close to your callers (Mumbai or Singapore for India) so calls feel faster. Check each provider's current price yourself.
- Buy or use a domain. In its DNS settings add an **A record**: name `jarvis` (or whatever you want) pointing to the server's public IP.

## 3. Prepare the server (SSH in as your user)
```
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git ufw
sudo usermod -aG docker $USER      # then log out and back in
docker compose version             # must be 2.24 or newer
```
Firewall: only SSH and the web ports. **Never open 5432 (database), 8000 (API) or 5678 (n8n).**
```
sudo ufw allow OpenSSH && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw enable
```

## 4. Copy the project and the secrets
```
git clone https://github.com/YOUR_NAME/YOUR_REPO.git jarvis && cd jarvis
```
`.env` and `.env.voice` are not in git. Copy them from your PC (PowerShell on your PC):
```
scp .env .env.voice youruser@SERVER_IP:~/jarvis/
```
Then on the server:
```
chmod 600 .env .env.voice
nano .env     # add the line  DOMAIN=jarvis.yourcompany.com   and change JARVIS_API_BASE if it still says localhost
```
Use strong, new passwords and keys on the server. Do not reuse the ones from testing.

## 5. Start everything
```
docker compose -f docker-compose.yml -f docker-compose.voice.yml -f docker-compose.proxy.yml up -d --build
docker compose ps
```
Expected: `api`, the database, `voice-worker` and `caddy` all "running". Create the database tables once:
```
docker compose exec api alembic upgrade head
```
(If your API service has another name than `api`, use that name here and in `docker-compose.voice.yml`.)

## 6. Check it
1. `https://YOUR_DOMAIN/health` in a browser shows `{"status":"ok"}` with a padlock.
2. `https://YOUR_DOMAIN/dashboard` opens, and your staff key works.
3. `https://YOUR_DOMAIN/docs` and `https://YOUR_DOMAIN/internal/retry-events` show "404". They must not be reachable.
4. The worker is connected: `docker compose logs --tail 30 voice-worker` shows "registered worker".
5. Make a test call (LiveKit Console or your phone number). Then check `/staff/calls` or the dashboard.
6. n8n keeps calling the API from inside Docker, so its URLs should stay `http://api:8000/...`. Do not point it at the public domain.

## 7. Phone number
Run on your PC: `python -m app.voice.phone_setup`. It writes the two LiveKit files from `VOICE_NUMBERS`. Then follow `PHONE_SETUP_GUIDE.md`.

## 8. Keep it healthy
- **Update:** `git pull` then the same `up -d --build` command as step 5. Run `alembic upgrade head` if a step added a migration.
- **Logs:** `docker compose logs -f voice-worker`.
- **Unsent call records** (API was down): `docker compose exec voice-worker python -m app.voice.spool`.
- **Backups:** a nightly database copy is not optional. Example (change the service name and user to yours):
  `docker compose exec -T db pg_dump -U YOUR_DB_USER YOUR_DB_NAME | gzip > backup-$(date +%F).sql.gz`
  Copy backups off the server, and try restoring one before you need it.
- **Keys:** rotate staff keys with `python -m app.staff_keys new --all --replace`.
- **LiveKit minutes:** the free plan has a monthly limit. Watch usage in the LiveKit dashboard.

## 9. Step 31: safe for real customers

**Real caller address (already on).** `docker-compose.proxy.yml` sets `TRUSTED_PROXY_COUNT=1`, so the rate limiter sees each
caller's own address instead of Caddy's. Without this, ten wrong keys from ONE person would lock out EVERYONE.
Never set it above the number of proxies you really run.

**Alerts.** Create a Slack, Discord or n8n webhook and put `ALERT_WEBHOOK_URL=...` in `.env`. Then run every 5 minutes:
`*/5 * * * * cd /opt/jarvis && docker compose exec -T api python -m app.watchdog >> watchdog.log 2>&1`
Test it: stop the api (`docker compose stop api`), wait for the next run, you get one message; start it again, you get "recovered".

**Backups.** `export BACKUP_PASSPHRASE='long secret'` then `bash deploy/backup.sh` (needs `openssl`; set `DB_SERVICE` to your Postgres
service name, see `docker compose ps`). Nightly: `15 2 * * * cd /opt/jarvis && BACKUP_PASSPHRASE=... bash deploy/backup.sh`.
Monthly: `bash deploy/restore_test.sh backups/<file>` must end with RESTORE TEST PASSED. Copy backups off the server.

**Privacy.** `python -m app.retention clean --days 90 --dry-run` then without `--dry-run`. `python -m app.retention erase <slug> <phone>`
for a customer who asks to be forgotten. Put the retention period in your customer contract.

**Tests on every push.** `.github/workflows/ci.yml` runs the migrations and the whole test suite on GitHub. Make a push, open the
Actions tab, expect a green tick.

**Load test.** `python loadtest/load_test.py --key <a TEST company ai key> --users 20 --seconds 20` must print PASS.

**Paid tiers.** Free tiers are for testing. Before real customers: Gemini paid tier (free-tier prompts may be used to improve
Google products, so customer calls should not go through it), a paid Deepgram or Sarvam plan, LiveKit Cloud paid plan, a server of at
least 2 vCPU / 4 GB. Check each provider's current pricing page; I could not verify the numbers.

## 10. Customer chat from a QR code

Customers scan a QR code, a chat page opens on their phone, and the same AI assistant helps them type
their details instead of saying them. The phone line keeps working as before; the page shows a small
"Call us" link when `CHAT_PHONE_<COMPANY>` is set.

**What it can do:** answer questions, book, change and cancel visits, register a new customer, raise a support
ticket, check a ticket, email the latest invoice, and hand over to a person.

**On phones.** It uses the phone's own font and text-size setting, keeps clear of notches and the Android/iPhone
navigation bar, stays above the keyboard, and has a Back arrow. The phone's own back button or swipe returns to the
menu instead of leaving the page.

**Each company has its own QR code, made and revoked like a staff key.** The code is a random string in the address
(`/c/<code>`), so the company name is not in the link and nobody can guess another company's page.

    python -m app.webchat.qr new smile-dental              # a new code + QR files in qr\ (older codes keep working)
    python -m app.webchat.qr new smile-dental --replace    # a new code and every older QR stops working
    python -m app.webchat.qr show smile-dental             # remake the QR files for the current codes
    python -m app.webchat.qr revoke smile-dental           # switch the company's QR codes off
    python -m app.webchat.qr list

Use one code per place (front desk, website, flyer) by running `new` once each, so you can switch one off alone.
A printed QR can be photographed, so it is not a secret like a staff key: that is why codes can be replaced at any time and
why the chat has its own limits. After any change run `python -m app.webchat.split_env` and restart the chat service.
The printable poster is at `PUBLIC_BASE_URL/c/<code>/poster` (it has a Print button).

**Safety on a web page.** On a call the number comes from caller ID. On a web page anyone can type any
number, so the web version is stricter than the phone: it never says a name or an email address; it has no
"list my appointments" (to change or cancel, the customer must give the phone number AND the exact date and
time of the visit); five wrong guesses stop those tools for that chat; booking, tickets, handoffs and
invoice emails have a per-chat limit; and there are per-visitor, per-chat and per-day message limits.
Guessing QR codes is rate limited too. A text-message code would be stronger still, and can be added later.

Add to `.env` (the company's `JARVIS_KEY_<COMPANY>` and `GEMINI_API_KEY` must already be there):

    PUBLIC_BASE_URL=https://jarvis.example.com
    CHAT_PHONE_SMILE_DENTAL=+919876543210     # optional: the "Call us" link
    CHAT_COUNTRY_CODE=+91                      # optional, +91 is the default
    # optional limits: CHAT_MESSAGES_PER_MINUTE=12  CHAT_SESSIONS_PER_HOUR=20  CHAT_MAX_TURNS=40
    #                  CHAT_SESSION_MINUTES=30  CHAT_DAILY_MESSAGES=800  CHAT_BAD_CODES_PER_MINUTE=10

Run it on a server:

    python -m app.webchat.qr new smile-dental
    python -m app.webchat.split_env
    docker compose -f docker-compose.yml -f docker-compose.voice.yml -f docker-compose.chat.yml -f docker-compose.proxy.yml up -d --build
