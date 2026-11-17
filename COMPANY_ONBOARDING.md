# Adding a company to JARVIS (keys, database and settings)

Run everything in PowerShell, inside `C:\N8nJob\JarvusAiCustomer`, with the virtual environment on (`.\.venv\Scripts\Activate.ps1`).
The commands use the owner's database login from `.env`, so run them only on your own machine or server.

## 1. How a company exists in the system

There is ONE database for every company. A company is a row in `companies`; every other table (customers, appointments,
tickets, FAQs, calls, keys) carries that company's `company_id`, and the database itself (row-level security) only lets a
request see rows of the company its key belongs to. So "adding a company" never means a new database or copying code.
You never edit these tables by hand. The commands below do it and write an audit entry for each change.

| Piece | Where it lives | Made by | Who holds it |
|---|---|---|---|
| Company row (name, agent, hours, greeting, time zone, minutes cap) | database `companies` | `owner company-new` / `onboard`, changed by `hours`, `text`, `cap` | nobody, it is data |
| AI key `jrv_...` | database `api_keys` (fingerprint only) + your `.env` as `JARVIS_KEY_<SLUG>` | `company-new`, `ai-key-new` | the phone worker and the chat server only |
| Staff key `stf_...` | database `staff_keys` (fingerprint only) | `company-new`, `python -m app.staff_keys new <slug>` | the company's team or a script |
| Staff logins (email + password) | database `staff_users` (scrambled password) | `owner user-new` | one named person each |
| QR code | `.env` as `CHAT_CODE_<SLUG>` (+ files in `qr/`) | `python -m app.webchat.qr new <slug>` | printed for customers |
| Phone number | `.env` as `VOICE_NUMBERS=+number=slug` | you, plus LiveKit | callers |
| FAQs, customers | database | `faq-add`, `faq-import`, `customers-import` | the company's data |

Keys are shown once and only a fingerprint is stored, so nobody can read one back. A lost key is replaced, not recovered.
One key, login or QR code never works for two companies. The `<SLUG>` in a setting name is the company slug in capitals with
dashes turned into underscores (`green-clinic` becomes `GREEN_CLINIC`).

## 2. The fast way: one file

Copy `examples\company.example.json` to `green-clinic.json`, change the values, then:

```powershell
python -m app.owner onboard green-clinic.json --check      # checks the whole file, creates nothing
python -m app.owner onboard green-clinic.json              # creates the company, hours, greeting and FAQs
```

The file is checked completely before anything is created, so a typo never leaves half a company behind. The command prints
the AI key and a first staff key ONCE. Copy them now.

## 3. The rest, in order

```powershell
# 3.1 put the AI key in .env (one line, key from step 2)
#     JARVIS_KEY_GREEN_CLINIC=jrv_...

# 3.2 first staff login (it asks for the password)
python -m app.owner user-new green-clinic owner@greenclinic.example "Dr Rao" --role owner

# 3.3 the company's own QR code
#     PUBLIC_BASE_URL in .env must be the real public address, not localhost
python -m app.webchat.qr new green-clinic

# 3.4 phone number (only when it has one): add to VOICE_NUMBERS in .env, e.g.
#     VOICE_NUMBERS=+14154176488=smile-dental,+918012345678=green-clinic
#     CHAT_PHONE_GREEN_CLINIC=+918012345678          (optional "Call us" link on the chat page)
#     then follow PHONE_SETUP_GUIDE.md

# 3.5 rebuild the trimmed settings files and restart the worker and the chat service
python -m app.voice.split_env
python -m app.webchat.split_env
```

## 4. Loading the client's existing information

What can be loaded now: FAQs and the customer list. Both are CSV files (in Excel: Save As, CSV UTF-8) with the exact column
names in the first row. Always run with `--check` first: it prints what would happen and writes nothing.

```powershell
python -m app.owner faq-import green-clinic examples\faqs.example.csv --check
python -m app.owner faq-import green-clinic examples\faqs.example.csv
python -m app.owner customers-import green-clinic examples\customers.example.csv --check
python -m app.owner customers-import green-clinic examples\customers.example.csv --country-code +91
```

- Columns: FAQs `question,answer`; customers `full_name,phone,email` (email may be empty).
- Phone numbers are made consistent (`98450 12345` becomes `+919845012345`). Rows with an invalid number or email are listed
  by line number and skipped. Numbers already registered are left untouched. Running the same file twice adds nothing.
- NOT loaded: appointment history, invoices, tickets, or a live link to the client's own booking or records system. That
  would be a separate piece of work (an adapter or an n8n workflow), agreed per client.

## 5. Changing a company later

```powershell
python -m app.owner hours green-clinic --open 8 --close 20 --slot 15 --closed sat,sun --timezone Asia/Kolkata
python -m app.owner text green-clinic --greeting "Hello from Green Clinic" --instructions "Be brief."
python -m app.owner faq-add green-clinic "Do you open on holidays?" "No, we are closed on public holidays."
python -m app.owner faq-list green-clinic
python -m app.owner cap green-clinic 900                   # monthly call minutes, or: none
python -m app.owner ai-key-new green-clinic                # a second AI key; the old one keeps working
python -m app.owner ai-key-new green-clinic --replace      # new key, old ones stop AT ONCE: update .env and restart straight away
python -m app.staff_keys new green-clinic --replace        # new staff key, old staff keys stop
python -m app.webchat.qr new green-clinic --replace        # new QR code; printed posters of the old one stop working
python -m app.owner company-off green-clinic               # pause everything for this company (company-on to resume)
```

The company's owner or a manager can also change hours and the time zone themselves in the staff screen (`/staff/company`).
FAQs, greeting and the AI instructions are owner-tool only.

## 6. Check it before handing over

```powershell
python -m app.owner overview                               # the company is listed, ON
python -m app.voice.preflight                              # no FAIL lines
```

1. Open the QR link, book a test appointment, and see it on the staff screen.
2. Sign in as the new owner at `/dashboard` with the company slug.
3. Isolation check: sign in to a DIFFERENT company and confirm none of the new company's customers, tickets or calls appear.
4. Delete your test records through the staff screen before the client uses it.
