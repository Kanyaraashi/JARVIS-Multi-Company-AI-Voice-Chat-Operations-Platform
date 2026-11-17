"""The safety layer between a web page and the company's tools.

On a phone call the number comes from caller ID. On a web page anyone can TYPE any number, so the
same tools would let a stranger read or change somebody else's appointments. This layer makes the
web chat safe without any text message or email code:

  * lookup_customer only says "registered" or not. It never returns a name or an email hint.
  * list_my_appointments does not exist here. To cancel or move a visit the customer must give the
    phone number AND the exact date and time of that visit; nothing else is ever revealed.
  * Wrong identity guesses are counted. After MAX_FAILS the identity tools stop for that chat.
  * Anything that creates something (booking, ticket, handoff, invoice email) has a per-chat limit.
  * The invoice tool never returns the masked email address.

It also turns the reply tags the AI writes ([[ask:phone]], [[choices: A | B]]) into data for the page.
"""
import functools
import inspect
import re

from app.agent_tools import make_tools, not_confirmed

MAX_FAILS = 5
CAPS = {
    "lookup_customer": 10,
    "register_customer": 3,
    "book_appointment": 3,
    "create_support_ticket": 3,
    "transfer_to_human": 2,
    "email_my_invoice": 2,
}
LOCKED = {
    "ok": False,
    "error": "Too many attempts to match a booking or ticket in this chat. Please call us, or ask to speak to a person.",
}
NOT_FOUND = {
    "ok": False,
    "error": "I could not find an appointment at that date and time for that phone number.",
}
TOO_MANY = {"ok": False, "error": "That was already done several times in this chat. Please ask to speak to a person."}


def clean_time(value: str) -> str:
    """9:5, 09:05, 9.05 all become 09:05. Anything else stays as typed and will not match."""
    match = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", value or "")
    return f"{int(match.group(1)):02d}:{match.group(2)}" if match else (value or "").strip()


def web_tools(api_key: str, session_id: str, log=None):
    base = {fn.__name__: fn for fn in make_tools(api_key, session_id, log)}
    state = {"fails": 0, "uses": {}}

    def locked() -> bool:
        return state["fails"] >= MAX_FAILS

    def limited(name):
        """Counts every real attempt of a tool and stops it after its cap."""
        fn = base[name]
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            confirmed = sig.bind(*args, **kwargs).arguments.get("customer_confirmed", True)
            if confirmed is True:                      # asking for a yes is not an attempt
                state["uses"][name] = state["uses"].get(name, 0) + 1
                if state["uses"][name] > CAPS[name]:
                    return dict(TOO_MANY)
            return fn(*args, **kwargs)

        return wrapper

    def lookup_customer(phone: str) -> dict:
        """Check whether a phone number with country code belongs to a registered customer. The
        result only says that the customer is registered and whether an email address is on file.
        It never gives a name or an address. If it is not ok because the customer was not found,
        they are not registered yet."""
        state["uses"]["lookup_customer"] = state["uses"].get("lookup_customer", 0) + 1
        if state["uses"]["lookup_customer"] > CAPS["lookup_customer"]:
            return dict(TOO_MANY)
        result = base["lookup_customer"](phone)
        if result["ok"]:
            return {"ok": True, "data": {"registered": True, "has_email": bool(result["data"].get("has_email"))}}
        return result

    def find_appointment(phone: str, date: str, time: str):
        if locked():
            return None, dict(LOCKED)
        listed = base["list_my_appointments"](phone)
        wanted = clean_time(time)
        if listed["ok"]:
            for appt in listed["data"]:
                if appt.get("date") == (date or "").strip() and appt.get("time") == wanted:
                    return appt, None
        state["fails"] += 1
        return None, dict(NOT_FOUND)

    def cancel_appointment(
        customer_phone: str, current_date: str, current_time: str, customer_confirmed: bool
    ) -> dict:
        """Cancel one of the customer's appointments. The customer must tell you their phone number
        and the date (YYYY-MM-DD) and time (24-hour HH:MM) of the appointment they want to cancel.
        You cannot list appointments. customer_confirmed must be true only if the customer just
        said yes to cancelling that exact appointment."""
        if customer_confirmed is not True:
            return not_confirmed()
        appt, error = find_appointment(customer_phone, current_date, current_time)
        if error:
            return error
        return base["cancel_appointment"](customer_phone, appt["id"], True)

    def reschedule_appointment(
        customer_phone: str, current_date: str, current_time: str,
        new_date: str, new_time: str, customer_confirmed: bool,
    ) -> dict:
        """Move one of the customer's appointments. The customer must tell you their phone number
        and the current date (YYYY-MM-DD) and time (24-hour HH:MM) of the appointment. new_date and
        new_time are the free time they picked. customer_confirmed must be true only if the
        customer just said yes to this exact new date and time."""
        if customer_confirmed is not True:
            return not_confirmed()
        appt, error = find_appointment(customer_phone, current_date, current_time)
        if error:
            return error
        return base["reschedule_appointment"](customer_phone, appt["id"], new_date, new_time, True)

    def get_ticket_status(ticket_id: int, customer_phone: str) -> dict:
        """Check the status of a support ticket. You need both the ticket number and the phone
        number of the customer the ticket belongs to. If the result is not ok, say you cannot
        find that ticket for that phone number. Statuses: open = received, nobody has started
        yet; in_progress = staff has started; resolved = finished; closed = closed. Report the
        status exactly as returned."""
        if locked():
            return dict(LOCKED)
        result = base["get_ticket_status"](ticket_id, customer_phone)
        if not result["ok"]:
            state["fails"] += 1
        return result

    def email_my_invoice(customer_phone: str, customer_confirmed: bool) -> dict:
        """Email the customer's latest invoice to the email address on file. The invoice details
        are only in the email: never say amounts, dates or invoice numbers in the chat, and never
        say any part of the address. customer_confirmed must be true only if the customer just
        said yes to sending it to the address on file."""
        result = limited("email_my_invoice")(customer_phone, customer_confirmed)
        if result.get("ok") and isinstance(result.get("data"), dict):
            result["data"] = {k: v for k, v in result["data"].items() if "hint" not in k and "email" not in k}
        return result

    return [
        base["search_company_faq"],
        lookup_customer,
        limited("register_customer"),
        base["check_appointment_availability"],
        limited("book_appointment"),
        reschedule_appointment,
        cancel_appointment,
        limited("create_support_ticket"),
        get_ticket_status,
        limited("transfer_to_human"),
        email_my_invoice,
    ]


TAG = re.compile(r"\[\[(.*?)\]\]", re.S)
MAX_CHOICES = 8
MAX_CHOICE_LEN = 40


def parse_reply(text: str):
    """Splits the AI's text into (words for the customer, what to ask: 'phone'/'email'/None, choices)."""
    ask, choices = None, []
    for tag in TAG.findall(text or ""):
        name, _, value = tag.partition(":")
        name = name.strip().lower()
        if name == "ask" and value.strip().lower() in ("phone", "email") and ask is None:
            ask = value.strip().lower()
        elif name == "choices" and not choices:
            for item in value.split("|"):
                item = " ".join(item.split())[:MAX_CHOICE_LEN]
                if item and item not in choices:
                    choices.append(item)
            choices = choices[:MAX_CHOICES]
    words = TAG.sub("", text or "").strip()
    if ask:
        choices = []
    return words, ask, choices


WEB_RULES = """
Web chat rules (you are typing in a chat page the customer opened by scanning a QR code). These replace any earlier rule they disagree with:
- Write short, plain sentences. No markdown, no lists, no emojis.
- Never say a customer's name, email or any part of an email address, and never say what appointments or invoices exist. lookup_customer only tells you whether the number is registered. Ask for the customer's name only when you are registering them.
- When you need the customer's mobile number, ask for it in one short sentence and end your reply with [[ask:phone]]. The page shows a number field and sends it back as "My mobile number is +91...". Typed numbers are exact, so do not read them back.
- When you need an email address, end with [[ask:email]]. Typed addresses are exact too. Never ask for a number or an email twice in a row.
- When the customer should pick from a few options (a day, a time, yes or no, what they want), end your reply with [[choices: First | Second | Third]]. At most 8 short choices. Days look like "Wed 12 Nov", times like "10:30 AM". For every confirmation use [[choices: Yes | No]]. Use only one tag per reply, at the very end, and never mention the tags.
- You cannot list appointments. To cancel or move a visit, ask for the phone number and the exact date and time of that visit. If the tool cannot find it, say so, never hint at other visits, and offer to pass the request to a person.
- For invoices say only "the email address we have on file".
- The customer may start by tapping a menu choice such as "Book an appointment", "Change or cancel a visit", "Check on a request" or "Talk to a person". Treat it as their request and take the first step.
- If a tool says there were too many attempts, stop trying, and offer to pass the request to a person.
"""
