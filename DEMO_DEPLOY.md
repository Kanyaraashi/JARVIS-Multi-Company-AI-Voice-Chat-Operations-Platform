# Public demo: Render (free) + Neon (free database)

Goal: anyone scans the QR code in your README and the booking chat opens on their phone. No localhost.
One Render web service runs everything the demo needs (API + staff screen + customer chat) in one container. The phone
line, n8n and status emails are NOT part of this demo.

Free-tier facts (checked 17 Nov 2026, they change, re-check before relying on them):
- Render free web service: sleeps after 15 minutes without traffic, takes about a minute to wake, 750 free hours a month per workspace,
  the filesystem is wiped on restart. Render's own free Postgres is deleted after 30 days, so use Neon instead.
  https://render.com/docs/free
- Neon free: 1 GB storage, 100 compute-hours a month, compute sleeps after 5 minutes idle. https://neon.com/faqs/free-plan-limits-and-quotas

**Not verified by me:** the Render build, Neon letting the migration create the `jarvis_app` role, and the real client address
seen behind Render. Each step below says what to expect. If one differs, send me the step and the full output.

Everything runs in PowerShell, in `C:\N8nJob\JarvusAiCustomer`, with the virtual environment on.
Never paste a key or a connection string into chat, git or the README.

---------------------------------------------------------------------

## 1. Neon: the database (5 minutes)

1. Sign up at neon.com and create a project (name `jarvis-demo`). Pick the region closest to your Render region (Singapore for both, if offered).
2. On the project dashboard choose Connect and copy the DIRECT connection string (the host has no `-pooler` in it).
   It looks like `postgresql://OWNER:PASSWORD@ep-xxxx.REGION.aws.neon.tech/DBNAME?sslmode=require`.
3. For our code, change the start to `postgresql+psycopg://` (keep the rest). Call this the OWNER URL.

## 2. Create the tables and the restricted database user (once)

```powershell
$env:DATABASE_URL = "postgresql+psycopg://OWNER:PASSWORD@ep-xxxx.REGION.aws.neon.tech/DBNAME?sslmode=require"
$env:ADMIN_DATABASE_URL = $env:DATABASE_URL
$env:JARVIS_APP_DB_PASSWORD = python -c "import secrets; print(secrets.token_urlsafe(24))"
alembic upgrade head
python -m app.check_rls
```

Variables set like this last only in this PowerShell window, so the demo values never touch your real `.env`.
Expect: `Running upgrade ... -> 0006` lines, then `check_rls` ending with every line PASS (it proves one company cannot see another).
Keep `$env:JARVIS_APP_DB_PASSWORD` visible once (`$env:JARVIS_APP_DB_PASSWORD`) and save it in a password manager: you need it in step 4.
If `alembic` says it cannot create the role, send me the full error.

## 3. Create the demo company (still in the same window)

```powershell
(Get-Content examples\company.example.json) -replace 'green-clinic','demo-clinic' -replace 'Green Clinic','Demo Clinic' | Set-Content demo-clinic.json
python -m app.owner onboard demo-clinic.json
python -m app.owner user-new demo-clinic demo@example.com "Demo Owner" --role owner
python -m app.owner customers-import demo-clinic examples\customers.example.csv
Remove-Item demo-clinic.json
```

The AI key (`jrv_...`) prints ONCE: copy it for step 4. The staff login you just made lets you open the staff screen on the demo.

## 4. Render: the web service

1. Push this repo to GitHub first (it must contain `render.yaml`, `Dockerfile.demo`, `deploy/demo-start.sh`, `deploy/Caddyfile.demo`).
2. On render.com: New, then Blueprint, pick your repo. It reads `render.yaml` and asks for the values marked secret. Fill:
   - `DATABASE_URL`: `postgresql+psycopg://jarvis_app:APP_PASSWORD@ep-xxxx.REGION.aws.neon.tech/DBNAME?sslmode=require`
     (the SAME host and database as step 1, but user `jarvis_app` and the password from step 2, NOT the owner login).
   - `GEMINI_API_KEY`: a NEW key made only for the demo (so you can switch it off), from Google AI Studio.
   - `JARVIS_KEY_DEMO_CLINIC`: the `jrv_...` key from step 3.
   - `PUBLIC_BASE_URL` and `CHAT_CODE_DEMO_CLINIC`: type `x` for now. You fix them in step 5.
3. Wait for the first deploy. Expect the log to end with the API and chat starting, and the service shown as Live.
   Note the address Render gives you, like `https://jarvis-demo-xxxx.onrender.com`.
4. Open `https://<address>/health`. Expect `{"status":"ok"}` (the first request after idle takes about a minute).

## 5. Make the QR code for the real address

The QR tool reads and writes a `.env` in the folder you run it from, so use a scratch folder and keep your real `.env` out of it:

```powershell
New-Item -ItemType Directory C:\N8nJob\demo-qr -Force | Out-Null
Set-Content C:\N8nJob\demo-qr\.env "JARVIS_KEY_DEMO_CLINIC=jrv_paste_the_demo_key`nPUBLIC_BASE_URL=https://jarvis-demo-xxxx.onrender.com"
cd C:\N8nJob\demo-qr
$env:PYTHONPATH = "C:\N8nJob\JarvusAiCustomer"
python -m app.webchat.qr new demo-clinic
```

Expect a link like `https://jarvis-demo-xxxx.onrender.com/c/AbCdEfGhIjKl` and files in `C:\N8nJob\demo-qr\qr\` (`.png` for the README, `.svg` for printing).
Then in Render, Environment: set `PUBLIC_BASE_URL` to the real address and `CHAT_CODE_DEMO_CLINIC` to the 12-character code at the end of the link
(it is also saved in `C:\N8nJob\demo-qr\.env`). Save: Render redeploys.
When finished, close the window or run `Remove-Item C:\N8nJob\demo-qr -Recurse -Force`; the PNG is the only thing to keep (copy it to `docs\demo-qr.png` in the repo: a QR is not a secret).

## 6. Check it like an interviewer

1. On your phone, switch Wi-Fi off, scan the QR. The chat should open (allow a minute if it was asleep).
2. Book a test appointment. This is the first time the chat talks to the real Gemini model: tell me exactly what it did.
3. Open `https://<address>/dashboard`, company `demo-clinic`, the demo login. The booking should appear.
4. If the chat page loads but replies fail, the Render logs show why (most often the Gemini key or the `JARVIS_KEY_DEMO_CLINIC` value).

## 7. Put it in the README

```
Live demo (free hosting, the first load can take a minute to wake): https://jarvis-demo-xxxx.onrender.com/c/CODE
Staff screen: https://jarvis-demo-xxxx.onrender.com/dashboard   company: demo-clinic   login: demo@example.com
```

Do not publish the staff login password. Give it to interviewers privately, or leave the staff screen out of the README and show it in a screen recording.

## Limits and cautions

- Strangers can use the chat, so it spends your demo Gemini quota. `CHAT_DAILY_MESSAGES=200` caps a day's messages; lower it, or delete the demo Gemini key to switch the demo off.
- `TRUSTED_PROXY_COUNT=0` means all visitors share one rate-limit address behind Render. That is safe but one noisy visitor can slow others down. Leave it unless you have checked how Render passes the real address.
- No n8n and no phone: confirmation emails are not sent from the demo, and the "Call us" link only shows if `CHAT_PHONE_DEMO_CLINIC` is set.
- Chat conversations live in memory, so a sleep or redeploy clears them. Bookings are saved in Neon.
- When Render's 750 free hours or Neon's 100 compute-hours run out, the demo stops until next month.
- Put only made-up customers in the demo database.
