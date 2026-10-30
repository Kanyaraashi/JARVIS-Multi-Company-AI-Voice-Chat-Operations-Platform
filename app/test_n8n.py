import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

secret = os.getenv("N8N_WEBHOOK_SECRET")
if not secret:
    sys.exit("N8N_WEBHOOK_SECRET is not set in .env")

email = input("Type your real email address and press Enter: ").strip()
base = "http://localhost:5679/webhook/"

company = {"slug": "smile-dental", "name": "Smile Dental Clinic", "agent_name": "Maya"}
customer = {"name": "Test Customer", "email": email}

tests = {
    "appointment-created": {
        "company": company,
        "appointment": {
            "id": 0, "date": "Saturday, 31 October 2026",
            "time": "05:30 PM", "reason": "Test",
        },
        "customer": customer,
    },
    "appointment-rescheduled": {
        "company": company,
        "appointment": {
            "id": 0,
            "old_date": "Saturday, 31 October 2026", "old_time": "05:30 PM",
            "date": "Saturday, 31 October 2026", "time": "04:30 PM",
            "reason": "Test",
        },
        "customer": customer,
    },
    "appointment-cancelled": {
        "company": company,
        "appointment": {
            "id": 0, "date": "Saturday, 31 October 2026",
            "time": "04:30 PM", "reason": "Test",
        },
        "customer": customer,
    },
    "ticket-created": {
        "company": company,
        "ticket": {
            "id": 0, "subject": "Test ticket", "description": "This is a test.",
            "priority": "normal", "status": "open",
        },
        "customer_name": "Test Customer",
    },
}

for path, payload in tests.items():
    try:
        response = httpx.post(
            base + path, json=payload, headers={"X-Jarvis-Secret": secret}, timeout=15
        )
        print(f"{path:26} -> {response.status_code}")
    except httpx.RequestError as exc:
        print(f"{path:26} -> not reachable ({type(exc).__name__})")