import getpass
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

API_BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
STATUSES = {"in_progress", "resolved", "closed"}


def call(method, path, key, **kwargs):
    try:
        response = httpx.request(
            method, API_BASE + path, headers={"X-API-Key": key}, timeout=15, **kwargs
        )
    except httpx.RequestError:
        print("Cannot reach the JARVIS API. Is uvicorn running?")
        return None
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text[:100]
        print(f"Error {response.status_code}: {detail}")
        return None
    return response.json()


def show_tickets(key, status=None):
    params = {"status": status} if status else None
    tickets = call("GET", "/staff/tickets", key, params=params)
    if tickets is None:
        return None
    if not tickets:
        print("No tickets found.")
        return tickets
    print(f"\n{'ID':>4}  {'STATUS':12} {'PRIORITY':8} {'CUSTOMER':18} SUBJECT")
    for t in tickets:
        customer = (t["customer_name"] or "-")[:18]
        print(f"{t['id']:>4}  {t['status']:12} {t['priority']:8} {customer:18} {t['subject'][:50]}")
    print()
    return tickets


def show_details(key):
    ticket_id = input("Ticket number: ").strip()
    tickets = call("GET", "/staff/tickets", key) or []
    for t in tickets:
        if str(t["id"]) == ticket_id:
            print(f"\nTicket {t['id']} | {t['status']} | {t['priority']}")
            print(f"Customer: {t['customer_name'] or '-'} {t['customer_phone'] or ''}")
            print(f"Subject:  {t['subject']}")
            print(f"Details:  {t['description']}\n")
            return
    print("Not found in the latest 50 tickets.")


def update_ticket(key):
    ticket_id = input("Ticket number: ").strip()
    if not ticket_id.isdigit():
        print("Please type a number.")
        return
    status = input("New status (in_progress / resolved / closed): ").strip()
    if status not in STATUSES:
        print("Status must be in_progress, resolved or closed.")
        return
    note = input("Message for the customer (optional, press Enter to skip): ").strip()
    if input(f"Set ticket {ticket_id} to {status}? (yes/no): ").strip().lower() != "yes":
        print("Cancelled.")
        return

    result = call(
        "PATCH", f"/staff/tickets/{ticket_id}", key,
        json={"status": status, "note": note or None},
    )
    if result is None:
        return
    if result["changed"]:
        print(
            f"Ticket {ticket_id} is now {result['ticket']['status']}. "
            "The customer is emailed if they have an address on file."
        )
    else:
        print("Nothing changed (it already had that status). No email was sent.")


def main():
    key = getpass.getpass("Staff key (typing is hidden): ").strip()
    if not key:
        return
    while True:
        print("1) Open tickets   2) All tickets   3) Ticket details   4) Update a ticket   q) Quit")
        choice = input("> ").strip().lower()
        if choice == "1":
            show_tickets(key, "open")
        elif choice == "2":
            show_tickets(key)
        elif choice == "3":
            show_details(key)
        elif choice == "4":
            update_ticket(key)
        elif choice == "q":
            break


if __name__ == "__main__":
    main()