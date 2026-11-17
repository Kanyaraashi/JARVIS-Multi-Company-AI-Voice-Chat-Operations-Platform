# JARVIS phone setup: from zero to a real call (Step 33)

This replaces `JARVIS_phone_number_workflow.md`. Every LiveKit and Plivo detail below was checked against their
current documentation on 8 Nov 2026 (links at the end). Things I could NOT verify are marked **[unverified]**.
Prices change: confirm each one on the provider's page before you pay.

---------------------------------------------------------------------

## 0. How a call travels (read once)

```
caller dials +91...  ->  phone company (Plivo)  ->  LiveKit SIP address
   -> inbound trunk ("accept calls for this number")
   -> dispatch rule ("own room call-xxxx, send agent 'jarvis' into it")
   -> your voice worker joins, reads which number was dialled, picks the company from VOICE_NUMBERS
   -> talks (Deepgram/Sarvam hears, Gemini thinks, a voice speaks)
   -> call ends -> call record saved -> shows on /dashboard
```

The company is chosen ONLY from the dialled number (set by the phone network). A caller cannot choose it, and a number that
is not in `VOICE_NUMBERS` is refused. This is what keeps two companies apart on the phone.

Pick your path:

| Path | Number | Cost | Use it for |
|---|---|---|---|
| **A** | US test number from LiveKit | free allowance, see part 2 | Proving the whole phone path works TODAY |
| **B** | Indian +91 number (Plivo, or Exotel/other) | monthly rent + per minute, needs KYC | Real customers in India |

Do A first. It takes about 20 minutes and finds 90% of the problems. B adds paperwork and Indian telecom rules.

---------------------------------------------------------------------

## 1. Before any phone: prove the machine works (PowerShell, project folder)

```powershell
cd C:\N8nJob\JarvusAiCustomer
.\.venv\Scripts\Activate.ps1
docker compose up -d                       # database, api, n8n
alembic upgrade head                       # Step 32 added migration 0006; expect "Running upgrade 0005 -> 0006"
python -m pytest -q                        # expect: all passed
python -m app.voice.preflight              # expect: no FAIL lines. WARN lines are explained on screen
python -m app.voice.model_speed --company smile-dental --rounds 3     # expect a verdict per model
python -m app.voice.text_check             # expect a sensible answer from the company's FAQ
```

**Pass mark:** pytest all green, preflight with zero FAIL, model_speed showing at least one model under about 3 seconds to the
first word. If a command fails, send me the step number and the whole output.

Then the browser call test (the one from Steps 22 to 25). Start the worker in its own window and leave it open:

```powershell
python voice_agent.py dev        # expect: "registered worker" and no red errors
```

Make one browser call, hang up, then read its speed (use the staff key variable you saved earlier):

```powershell
Invoke-RestMethod -Headers @{ "X-API-Key" = $env:YOUR_STAFF_KEY_VARIABLE } "http://localhost:8000/staff/calls/latency?calls=1" | ConvertTo-Json -Depth 5
```

Expect real numbers (not null) in `avg_llm_real_ms`. If they are null, the worker was started before the update: stop it
(Ctrl+C) and start it again.

---------------------------------------------------------------------

## 2. Path A: a LiveKit US test number

**What LiveKit says (docs checked):** LiveKit Phone Numbers are US-only and inbound-only. Every plan includes one free US local number,
and the free "Build" plan includes 50 US local inbound minutes. Releasing a number early still bills the whole month.
A US number is a TEST number. Calling it from India is an international call on your own phone bill.
For a free alternative to dialling, you can also test the phone path from any phone that can call the US (a friend abroad,
a VoIP app you already have). **[unverified]** I cannot tell which of those is free for you.

### 2.1 Install the LiveKit command line tool (once)

```powershell
winget install LiveKit.LiveKitCLI
lk --version                                # expect a version number. If "not recognised", close and reopen PowerShell
lk cloud auth                               # opens a browser: log in, choose your project
```

### 2.2 Buy the number

```powershell
lk number search --country-code US --area-code 415
lk number purchase --numbers +14155550100   # use a number from the search result, NOT this example
lk number list                              # note the number's ID
```

(You can do the same in the dashboard under Telephony, Phone Numbers.)

### 2.3 Create the two LiveKit settings from your .env

Add the number to `.env` first. Format: `number=company-slug`, comma separated, no spaces:

```
VOICE_NUMBERS=+14155550100=smile-dental
```

Find your number's ID (it starts with `PN_`; if the table is cut off use `lk number list --json`, or copy it from the dashboard under Phone Numbers):

```powershell
lk number list
```

Generate the files with that ID in them and create the dispatch rule:

```powershell
python -m app.voice.phone_setup --trunk-id PN_xxxxxxxx      # writes livekit\inbound-trunk.json and livekit\dispatch-rule.json
lk sip dispatch create livekit\dispatch-rule.json           # prints a rule ID like SDR_xxxx
lk sip dispatch list                                        # your rule must show the PN_ number under trunk IDs
```

LiveKit Phone Numbers need NO inbound trunk, so skip `lk sip inbound create` on this path. **Do not use `lk number update`**: a rule that is not tied
to a number is a catch-all, and LiveKit answers "Failed to update phone number" for those. Putting the `PN_` ID inside the rule (`trunk_ids`) does the tying.
If you get "Dispatch rule for the same trunk, inbound number ... already exists", the rule is already there: run `lk sip dispatch list`, and if it is the
wrong one, `lk sip dispatch delete <SDR_ID>` and create it again.

The dispatch file that was generated looks like this (it names the agent `jarvis`, which must match `AGENT_NAME` in code):

```json
{ "dispatch_rule": { "name": "JARVIS inbound", "trunk_ids": [ "PN_xxxxxxxx" ],
    "rule": { "dispatch_rule_individual": { "room_prefix": "call-" } },
    "room_config": { "agents": [ { "agent_name": "jarvis" } ] } } }
```

### 2.4 Check, then call

```powershell
python -m app.voice.preflight               # the phone lines check should show your number and company
python voice_agent.py dev                   # keep this window visible
```

Call the number. In the worker window you should see, within about 2 seconds of the ring:

```
Call started: company=smile-dental direction=inbound room=call-...
```

Say: "What are your opening hours?" You should hear the greeting first, then an answer from the company FAQ.
Hang up, wait 10 seconds, then:

```powershell
Invoke-RestMethod -Headers @{ "X-API-Key" = $env:YOUR_STAFF_KEY_VARIABLE } "http://localhost:8000/staff/calls?limit=1" | ConvertTo-Json -Depth 4
```

Expect `direction: inbound`, your transcript with phone numbers masked, and an `outcome` of `completed`.
Also open `http://localhost:8000/dashboard` and check the call appears.

**If the phone rings but nobody answers**, go to part 7 (troubleshooting).

---------------------------------------------------------------------

## 3. Path B: a real Indian number

### 3.1 What you must know first (this is where projects get stuck)

1. **Indian rules (TRAI) require voice for India calls to be anchored on servers in India.** Plivo documents that violating calls fail
   with hangup code **4590**. LiveKit's own guide says SIP signalling and media for PSTN calls must stay inside India.
2. **Plivo's data region must be India** for its Indian numbers, and an organisation's region cannot be changed later. If your
   Plivo account is in another region, create a NEW organisation (organisation switcher, "Create New Organization", choose India).
3. **KYC:** Indian numbers need business documents (business registration, proof of address, use case) before purchase.
   A third-party Indian provider (Edesy) states PAN and Aadhaar and about 24 hours review. Expect days, not minutes.
   Start the KYC TODAY, in parallel with everything else.
4. **LiveKit does not sell Indian numbers.** You rent the number from a phone company and point it at LiveKit.
5. **Conflicting statements in the docs:** Plivo's LiveKit page says you MUST enable region pinning for India. LiveKit's own India
   guide says region pinning needs the **Scale plan (from US$500 per month)** but that most teams only need the **India-specific
   SIP hostname** and no plan upgrade. Use the India hostname first (part 3.4). If calls then fail with 4590, ask both
   Plivo support and LiveKit support, in writing, whether your plan is allowed. Do not buy Scale just in case.
6. **[unverified]** Whether the rest of your stack must also run in India (your server running the voice worker, and AI services
   abroad such as Gemini or Deepgram) is not answered clearly in what I could read. The safe plan is to run the voice worker on
   a server in an Indian cloud region (Mumbai or Hyderabad) and to ask Plivo/LiveKit support. Get that answer BEFORE customers.

### 3.2 Order the number (Plivo)

1. Create the India organisation and complete KYC in the Plivo console.
2. Rent an India local or mobile number. Write it in international form, for example `+918012345678`.
3. Wait for approval. You will receive the number only after KYC passes.

(Alternatives such as Exotel or Edesy also sell Indian numbers with SIP forwarding. Their steps differ; the LiveKit side below is identical.
Ask them for "SIP trunk to a LiveKit SIP URI".)

### 3.3 Find your LiveKit SIP address

LiveKit Cloud dashboard, Project settings, copy the **SIP URI**. It looks like `sip:abc123xyz.sip.livekit.cloud`.
The part before `.sip` is your **SIP subdomain**. Your India-only address is:

```
<your-sip-subdomain>.india.sip.livekit.cloud
```

### 3.4 Plivo side: send the number to that address

Console method (easiest):
1. Plivo console: **SIP Trunking, Inbound Trunks, Create Trunk**.
2. **Primary URI:** `<your-sip-subdomain>.india.sip.livekit.cloud;transport=tcp`
   (use `;transport=tls` if you want encrypted signalling).
3. Link your number, create the trunk.
4. **Phone Numbers, Purchased Numbers**, open your number, set **Application Type = SIP Trunk**, pick the trunk, **Save**.

### 3.5 LiveKit side: accept the number

```powershell
# .env: put YOUR number in
#   VOICE_NUMBERS=+918012345678=smile-dental
python -m app.voice.phone_setup
lk sip inbound create livekit\inbound-trunk.json     # prints a trunk ID ST_xxxx
lk sip dispatch create livekit\dispatch-rule.json    # prints a rule ID SDR_xxxx
# tip: python -m app.voice.phone_setup --trunk-id ST_xxxx  (the trunk ID printed above) ties the rule to your trunk before you create it
lk sip inbound list                                  # your number must appear in "numbers"
lk sip dispatch list
```

Create ONE trunk for all your numbers and reuse it (LiveKit warns that trunk-per-call hurts reliability). The generated trunk file
lists every number from `VOICE_NUMBERS`. Adding a new customer later:

```powershell
# 1. add the number to VOICE_NUMBERS in .env (comma separated)   2. regenerate    3. update the trunk
python -m app.voice.phone_setup
lk sip inbound list                                  # copy the trunk ID
lk sip inbound update --id <TRUNK_ID> livekit\inbound-trunk.json   # [unverified: check "lk sip inbound update --help" shows this form]
```

### 3.6 Two companies, two numbers

```
VOICE_NUMBERS=+918012345678=smile-dental,+918087654321=shopeasy
```

Each company has its own number and its own `JARVIS_KEY_...` in `.env`. One dispatch rule serves both. The worker looks up the
dialled number, so a call to the shop number can never load the dental company. Test BOTH numbers, and check the shop call
never shows in the dental dashboard.

### 3.7 Calls to a real customer's own number (call forwarding)

Customers keep their existing public number if their phone provider can forward calls to your new number (the customer asks
their provider for "unconditional" or "no-answer" forwarding). Then they pay nothing extra for a new public number.

---------------------------------------------------------------------

## 4. The server, not your laptop

A laptop that sleeps drops calls. For real customers run the stack on the server from `DEPLOYMENT.md`:

```bash
docker compose -f docker-compose.yml -f docker-compose.voice.yml -f docker-compose.proxy.yml up -d --build
docker compose logs --tail 30 voice-worker        # expect "registered worker"
```

Step 31 and 32 additions on the server: `docker compose exec api alembic upgrade head`, the watchdog on a 5-minute schedule,
the nightly backup (`deploy/backup.sh`), `TRUSTED_PROXY_COUNT=1` (already in the proxy file).

---------------------------------------------------------------------

## 5. Company setup for a new customer (owner commands, Step 32)

```powershell
python -m app.owner company-new smile-dental "Smile Dental" --agent Maya --cap 600     # 600 call-minutes per month; keys shown ONCE
python -m app.owner user-new smile-dental owner@smile.com "Dr Rao" --role owner         # asks for a password
python -m app.owner overview                                                          # minutes used, cap, open tickets per company
python -m app.owner cap smile-dental 1200                                             # raise the cap (only YOU can)
python -m app.owner company-off smile-dental                                          # stops keys and logins if they stop paying
```

Put the printed AI key into `.env` as `JARVIS_KEY_SMILE_DENTAL=...` and restart the worker. Staff sign in at
`https://YOUR_DOMAIN/dashboard` with company slug, email and password. Roles: **owner** (everything and people),
**manager** (settings, tickets), **agent** (tickets and appointments, no settings).
When a company has used its monthly minutes the caller hears a short "not available right now" message and the call ends.
If the API cannot be reached to count, the call goes ahead (a customer is never refused because of OUR failure).

---------------------------------------------------------------------

## 6. The first-live-call checklist (tick every line)

```
[ ] python -m app.voice.preflight --production        zero FAIL
[ ] docker compose logs voice-worker                  "registered worker", no repeating errors
[ ] Call 1: ask opening hours                          correct answer from the FAQ, greeting heard first
[ ] Call 2: "I want to book an appointment tomorrow"   appointment appears in the dashboard, no duplicate if you ask twice
[ ] Call 3: "I have a problem, please raise a ticket"  ticket appears, staff email goes out via n8n (check the inbox)
[ ] Call 4: ask for a human                            callback ticket is created (this is the handoff that is built in)
[ ] Call 5: say nothing for 20 seconds                 polite goodbye, call ends, record saved
[ ] Call from the SECOND company's number              answers as that company; its data never shows in the first dashboard
[ ] /staff/calls/latency?calls=5                       avg_llm_real_ms under about 3000, failed calls = 0
[ ] Phone a number NOT in VOICE_NUMBERS (if you can)   refused, never answered as a default company
[ ] Watchdog test: stop the api container for 6 min    you get ONE alert, then "recovered" after starting it
[ ] Backup: bash deploy/backup.sh, then restore_test.sh   ends with RESTORE TEST PASSED
```

Do not tell a customer it is live until every line is ticked.

**Tell callers they are talking to an AI and that the call may be stored.** Add one sentence to the company greeting
(`PATCH /staff/company` or the database) such as "This call is answered by an AI assistant and may be recorded for quality."
Indian and EU privacy rules both reward this, and customers trust it more. This is not legal advice: have a lawyer check your
privacy notice and contract. What call content you keep and for how long is yours to decide: `python -m app.retention clean --days 90`.

---------------------------------------------------------------------

## 7. Troubleshooting (what you see, what it means, what to do)

| Symptom | Likely cause | Fix |
|---|---|---|
| Caller hears ringing forever / busy | Number not linked to the trunk, or inbound trunk does not list the number | `lk sip inbound list`: number must be there in `+` form. Plivo: number set to SIP Trunk |
| Call connects, silence, then hangs up | No worker running or wrong agent name | Start `python voice_agent.py dev`. `AGENT_NAME` is `jarvis`; the dispatch rule must say `jarvis` |
| Room appears in LiveKit, worker log silent | Dispatch rule has no agent or a different name | `lk sip dispatch list`, re-create with the generated file |
| Worker says "does not belong to any company line" | Dialled number is not in `VOICE_NUMBERS` (spelling, missing `+`, spaces) | Fix `.env`, restart the worker. Compare with `python -m app.voice.preflight` |
| Worker says "No key for company" | `JARVIS_KEY_<SLUG>` missing in `.env` (dashes become underscores, upper case) | Add it and restart |
| Worker says "Could not load company ... Is the JARVIS API running?" | API down or `API_BASE_URL` wrong | `docker compose ps`, open `/health` |
| Plivo hangup code 4590 | India media anchoring rule | Use the `.india.sip.livekit.cloud` address and a Plivo India organisation; then ask both support teams (part 3.1, point 5) |
| Greeting heard, then long silence on every question | Slow or failing model | `python -m app.voice.model_speed`; check Gemini key and quota; failover should say "One moment please." |
| Caller hears "not available right now" | Company is over its monthly cap | `python -m app.owner overview`, then `cap` |
| Call record missing | API unreachable at hang-up; it waits in `voice_spool` | `python -m app.voice.spool` (or inside the container) |
| One-way audio or choppy voice | Network or codec problem | **[unverified]** Check provider logs first (Plivo Zentrunk logs), then LiveKit Cloud telephony call logs |
| `lk` says unauthorized | Not logged in | `lk cloud auth` |
| JSON error from `lk sip ... create` | Wrong file shape | Regenerate with `python -m app.voice.phone_setup`; the shapes are the documented ones (`trunk` / `dispatch_rule` wrappers, snake_case names) |

First places to look, in order: Plivo logs, LiveKit Cloud Telephony call logs, the worker window, `docker compose logs api`.

---------------------------------------------------------------------

## 8. What it costs (all **[unverified until you check today]**)

* LiveKit Cloud: Build $0 (1 free US number, 50 US inbound minutes, 5 concurrent agent sessions), Ship from $50 a month, Scale from $500 a month.
  The free plan's 5 concurrent sessions means at most 5 calls at the same time.
* India number via Edesy (third party, their page): about Rs 0.50 a minute, number rent from Rs 499 a month, plus 18% GST.
  Plivo shows its own India prices on its pricing page; confirm there.
* AI providers (Gemini, Deepgram or Sarvam) bill separately and change often; move to paid plans before real customers (see DEPLOYMENT.md, part 9).

Work out your price to the customer as: (phone + LiveKit + AI cost per minute) x expected minutes x about 2.5, plus a setup fee.
Use `python -m app.owner overview` after a month for real minutes.

---------------------------------------------------------------------

## 9. Git

```powershell
git add -A
git commit -m "Steps 31-33: security, alerts, backups, logins, usage caps, phone guide"
git push
```
Check the GitHub "Actions" tab for a green tick (the CI file from Step 31).

---------------------------------------------------------------------

Sources checked on 8 Nov 2026:
LiveKit [dispatch rules](https://docs.livekit.io/telephony/accepting-calls/dispatch-rule/),
[inbound trunks](https://docs.livekit.io/telephony/accepting-calls/inbound-trunk/),
[phone numbers](https://docs.livekit.io/telephony/start/phone-numbers),
[region pinning](https://docs.livekit.io/telephony/features/region-pinning.md),
[Plivo quickstart](https://docs.livekit.io/telephony/start/providers/plivo.md),
[India field guide](https://livekit.com/field-guides/guide/support-india-data-sovereignty),
[pricing](https://livekit.com/pricing.md).
Plivo [calling in India](https://www.plivo.com/docs/voice-agents/sip-trunking/deploy/calling-in-india.md).
Edesy [Indian number guide](https://edesy.in/blog/connect-livekit-agent-to-indian-number-sip-2026.md) (third party).
