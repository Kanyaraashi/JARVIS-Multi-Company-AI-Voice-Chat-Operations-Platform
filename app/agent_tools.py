import hashlib
import json
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

API_BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")


def mask_email(email: str) -> str:
    name, _, domain = (email or "").partition("@")
    return f"{name[:1]}***@{domain}" if domain else "***"


def not_confirmed() -> dict:
    print("   [tool] blocked: the customer has not confirmed yet")
    return {
        "ok": False,
        "error": (
            "The customer has not confirmed yet. Say the exact details back to the customer, "
            "ask for a clear yes, and only after they say yes call this tool again with "
            "customer_confirmed set to true."
        ),
    }


def make_tools(api_key: str, session_id: str, log=None):
    """Builds the tools the AI may press. The company's API key stays in here,
    so the AI can never see it or pick a different company."""
    state = {"epoch": 0}
    log = log if log is not None else []

    def make_key(tool: str, *parts: str) -> str:
        """Same request in the same chat gives the same key, so retries are safe."""
        raw = "|".join([session_id, tool, str(state["epoch"]), *parts])
        return hashlib.sha256(raw.encode()).hexdigest()[:40]

    def raw_call(method, path, params=None, body=None, idempotency_key=None):
        headers = {"X-API-Key": api_key}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        shown = json.dumps(params or body or {}, ensure_ascii=False)
        try:
            response = httpx.request(
                method, API_BASE + path,
                params=params, json=body, headers=headers, timeout=15,
            )
        except httpx.RequestError:
            print(f"   [tool] {method} {path} {shown} -> not reachable")
            return {"ok": False, "error": "The business system is not reachable right now."}

        print(f"   [tool] {method} {path} {shown} -> {response.status_code}")

        if response.status_code in (401, 403):
            return {"ok": False, "error": "Not authorized. This cannot be done right now."}
        if response.status_code >= 500:
            return {"ok": False, "error": "The business system had a problem."}
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = None
            if not isinstance(detail, str):
                detail = "Some of the details were not valid."
            return {"ok": False, "error": detail}
        return {"ok": True, "data": response.json()}

    def call_api(method, path, params=None, body=None, idempotency_key=None):
        """Makes the call and records what happened, so another model can continue."""
        result = raw_call(method, path, params, body, idempotency_key)
        log.append(
            {
                "call": f"{method} {path}",
                "sent": json.dumps(params or body or {}, ensure_ascii=False)[:300],
                "ok": result["ok"],
                "result": json.dumps(
                    result.get("data", result.get("error")), ensure_ascii=False, default=str
                )[:500],
            }
        )
        return result

    def search_company_faq(question: str) -> dict:
        """Search this company's FAQ for services, prices, opening hours and policies.
        Use it before answering any factual question about the company.
        An empty list in data means the company has no information on that topic."""
        return call_api("GET", "/faq/search", params={"q": question})

    def lookup_customer(phone: str) -> dict:
        """Find an existing customer by phone number with country code, for example
        +919000000001. If the result is not ok because the customer was not found, they
        are not registered yet. has_email tells you whether emails can be sent, and
        email_hint is the masked address you may say to the customer."""
        result = call_api("GET", "/customers/lookup", params={"phone": phone})
        if result["ok"]:
            data = result["data"]
            email = data.get("email")
            result["data"] = {
                "full_name": data["full_name"],
                "has_email": bool(email),
                "email_hint": mask_email(email) if email else None,
            }
        return result

    def register_customer(
        full_name: str, phone: str, customer_confirmed: bool, email: str = ""
    ) -> dict:
        """Register a NEW customer. Use it only after lookup_customer found nobody and the
        customer agreed to be registered. phone must include the country code. email is
        optional. customer_confirmed must be true only if the customer just agreed."""
        if customer_confirmed is not True:
            return not_confirmed()
        return call_api(
            "POST", "/customers",
            body={
                "full_name": full_name.strip(),
                "phone": phone.replace(" ", ""),
                "email": email.strip() or None,
            },
        )

    def list_my_appointments(customer_phone: str) -> dict:
        """List the customer's upcoming booked appointments (id, date, time, reason).
        Always use this to cancel or reschedule. Never ask the customer for an appointment number."""
        return call_api(
            "GET", "/customers/appointments",
            params={"phone": customer_phone.replace(" ", "")},
        )

    def check_appointment_availability(date: str) -> dict:
        """List the free appointment times for one day. date must be YYYY-MM-DD."""
        return call_api("GET", "/appointments/availability", params={"date": date})

    def book_appointment(
        customer_phone: str, date: str, time: str, customer_confirmed: bool, reason: str = ""
    ) -> dict:
        """Book an appointment for a registered customer. date is YYYY-MM-DD and time is
        24-hour HH:MM. customer_confirmed must be true only if the customer just said yes
        to this exact date and time."""
        if customer_confirmed is not True:
            return not_confirmed()
        phone = customer_phone.replace(" ", "")
        return call_api(
            "POST", "/appointments",
            body={
                "customer_phone": phone,
                "date": date,
                "time": time,
                "reason": reason or None,
            },
            idempotency_key=make_key("book", phone, date, time),
        )

    def reschedule_appointment(
        customer_phone: str, appointment_id: int, date: str, time: str, customer_confirmed: bool
    ) -> dict:
        """Move one of the customer's appointments to a new free time. appointment_id comes
        from list_my_appointments. date is YYYY-MM-DD and time is HH:MM. customer_confirmed
        must be true only if the customer just said yes to this exact new date and time."""
        if customer_confirmed is not True:
            return not_confirmed()
        result = call_api(
            "POST", f"/appointments/{appointment_id}/reschedule",
            body={
                "customer_phone": customer_phone.replace(" ", ""),
                "date": date,
                "time": time,
            },
        )
        if result["ok"] and result["data"].get("changed"):
            state["epoch"] += 1
        return result

    def cancel_appointment(
        customer_phone: str, appointment_id: int, customer_confirmed: bool
    ) -> dict:
        """Cancel one of the customer's appointments. appointment_id comes from
        list_my_appointments. customer_confirmed must be true only if the customer just
        said yes to cancelling that exact appointment."""
        if customer_confirmed is not True:
            return not_confirmed()
        result = call_api(
            "POST", f"/appointments/{appointment_id}/cancel",
            body={"customer_phone": customer_phone.replace(" ", "")},
        )
        if result["ok"] and result["data"].get("changed"):
            state["epoch"] += 1
        return result

    def create_support_ticket(
        subject: str,
        description: str,
        customer_confirmed: bool,
        priority: str = "normal",
        customer_phone: str = "",
    ) -> dict:
        """Create a support ticket for something the tools cannot do. description must be a
        clear sentence about what the customer needs. priority must be low, normal, high or
        urgent. customer_confirmed must be true only if the customer just said yes after you
        read the description back."""
        if customer_confirmed is not True:
            return not_confirmed()
        phone = customer_phone.replace(" ", "")
        return call_api(
            "POST", "/tickets",
            body={
                "subject": subject,
                "description": description,
                "priority": priority,
                "customer_phone": phone or None,
            },
            idempotency_key=make_key("ticket", subject, description, phone),
        )

    def get_ticket_status(ticket_id: int) -> dict:
        """Check the status of a support ticket by its number. Statuses: open = received,
        nobody has started yet; in_progress = staff has started; resolved = finished;
        closed = closed. Report the status exactly as returned."""
        return call_api("GET", f"/tickets/{ticket_id}")

    def transfer_to_human(
        reason: str, customer_confirmed: bool, customer_phone: str = ""
    ) -> dict:
        """Alert the team that the customer wants to speak to a person. reason must be one
        clear sentence. customer_confirmed must be true only if the customer just said yes
        after you read the reason back. The result has within_business_hours: true means
        the team is working now, false means they are closed."""
        if customer_confirmed is not True:
            return not_confirmed()
        phone = customer_phone.replace(" ", "")
        return call_api(
            "POST", "/escalations",
            body={"reason": reason, "customer_phone": phone or None},
            idempotency_key=make_key("escalate", reason, phone),
        )

    def email_my_invoice(customer_phone: str, customer_confirmed: bool) -> dict:
        """Email the customer's latest invoice to the email address on file. The invoice
        details are only in the email: never say amounts, dates or invoice numbers in the
        chat. customer_confirmed must be true only if the customer just said yes to sending
        it to their address on file. The result gives email_hint, a masked address you may say."""
        if customer_confirmed is not True:
            return not_confirmed()
        return call_api(
            "POST", "/invoices/email-request",
            body={"customer_phone": customer_phone.replace(" ", "")},
        )

    return [
        search_company_faq,
        lookup_customer,
        register_customer,
        list_my_appointments,
        check_appointment_availability,
        book_appointment,
        reschedule_appointment,
        cancel_appointment,
        create_support_ticket,
        get_ticket_status,
        transfer_to_human,
        email_my_invoice,
    ]