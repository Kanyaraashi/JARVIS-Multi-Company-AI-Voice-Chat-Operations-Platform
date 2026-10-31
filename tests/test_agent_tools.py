"""The tools the AI can press, run against the real API (in memory)."""
import httpx
import pytest

from app import agent_tools
from app.agent_tools import make_tools, mask_email
from conftest import KEYS

ASHA = "+919000000001"


@pytest.fixture
def tools(client, world, n8n, monkeypatch):
    """Tools wired to the test API. Returns (tools by name, call log, list of http calls)."""
    sent = []

    def fake_request(method, url, params=None, json=None, headers=None, timeout=None):
        sent.append({"method": method, "path": url.replace(agent_tools.API_BASE, ""),
                     "json": json, "headers": headers})
        return client.request(method, url.replace(agent_tools.API_BASE, ""),
                              params=params, json=json, headers=headers)

    monkeypatch.setattr(agent_tools.httpx, "request", fake_request)
    log = []
    built = make_tools(KEYS["dental"], "session-1", log)
    return {f.__name__: f for f in built}, log, sent


def test_there_are_twelve_tools(tools):
    assert len(tools[0]) == 12


@pytest.mark.parametrize("name,args", [
    ("register_customer", {"full_name": "Nobody", "phone": "+919222222222"}),
    ("book_appointment", {"customer_phone": ASHA, "date": "2030-01-01", "time": "10:00"}),
    ("reschedule_appointment", {"customer_phone": ASHA, "appointment_id": 1, "date": "2030-01-01", "time": "10:00"}),
    ("cancel_appointment", {"customer_phone": ASHA, "appointment_id": 1}),
    ("create_support_ticket", {"subject": "Hello there", "description": "A problem"}),
    ("transfer_to_human", {"reason": "Wants a person"}),
    ("email_my_invoice", {"customer_phone": ASHA}),
])
@pytest.mark.parametrize("flag", [False, None, "yes", 1])
def test_write_tools_refuse_without_a_real_confirmation(tools, name, args, flag):
    by_name, log, sent = tools
    result = by_name[name](customer_confirmed=flag, **args)
    assert result["ok"] is False and "not confirmed" in result["error"]
    assert sent == []  # no call ever reached the API
    assert log == []


def test_faq_tool_returns_only_this_companys_answers(tools):
    by_name, log, sent = tools
    result = by_name["search_company_faq"]("opening hours")
    assert result["ok"] and "Dental" in result["data"][0]["answer"]
    assert sent[0]["headers"]["X-API-Key"] == KEYS["dental"]
    assert log[0]["call"] == "GET /faq/search" and log[0]["ok"] is True


def test_lookup_masks_the_email(tools):
    by_name, *_ = tools
    result = by_name["lookup_customer"](ASHA)
    assert result["data"] == {"full_name": "Asha Rao", "has_email": True,
                              "email_hint": "a***@example.com"}
    assert "asha@example.com" not in str(result)
    no_email = by_name["lookup_customer"]("+919876543210")
    assert no_email["data"]["has_email"] is False and no_email["data"]["email_hint"] is None


def test_lookup_of_unknown_customer_is_a_clean_error(tools):
    by_name, *_ = tools
    result = by_name["lookup_customer"]("+910000000000")
    assert result == {"ok": False, "error": "Customer not found"}


def test_mask_email_helper():
    assert mask_email("kanya@gmail.com") == "k***@gmail.com"
    assert mask_email("") == "***"
    assert mask_email(None) == "***"


def test_register_then_book_then_list_then_reschedule_then_cancel(tools, day):
    by_name, log, sent = tools
    d = day()
    assert by_name["register_customer"](full_name=" Meera ", phone="+91 92222 22222",
                                         customer_confirmed=True)["ok"]
    free = by_name["check_appointment_availability"](d)["data"]["open_slots"]
    assert "10:00" in free
    booked = by_name["book_appointment"](customer_phone="+919222222222", date=d, time="10:00",
                                          customer_confirmed=True, reason="Cleaning")
    assert booked["ok"] and booked["data"]["appointment"]["time"] == "10:00"
    mine = by_name["list_my_appointments"]("+91 92222 22222")["data"]
    assert len(mine) == 1
    appt_id = mine[0]["id"]
    moved = by_name["reschedule_appointment"](customer_phone="+919222222222", appointment_id=appt_id,
                                               date=d, time="11:00", customer_confirmed=True)
    assert moved["ok"] and moved["data"]["changed"] is True
    gone = by_name["cancel_appointment"](customer_phone="+919222222222", appointment_id=appt_id,
                                          customer_confirmed=True)
    assert gone["ok"] and gone["data"]["appointment"]["status"] == "cancelled"


def test_booking_twice_in_the_same_chat_does_not_double_book(tools, day):
    by_name, log, sent = tools
    d = day()
    args = dict(customer_phone=ASHA, date=d, time="10:00", customer_confirmed=True)
    first = by_name["book_appointment"](**args)
    second = by_name["book_appointment"](**args)
    assert first["data"]["already_existed"] is False
    assert second["data"]["already_existed"] is True  # same chat, same key
    book_calls = [c for c in sent if c["path"] == "/appointments"]
    assert book_calls[0]["headers"]["Idempotency-Key"] == book_calls[1]["headers"]["Idempotency-Key"]


def test_booking_the_same_slot_again_after_cancelling_is_a_new_booking(tools, day):
    by_name, *_ = tools
    d = day()
    args = dict(customer_phone=ASHA, date=d, time="10:00", customer_confirmed=True)
    first = by_name["book_appointment"](**args)["data"]["appointment"]["id"]
    by_name["cancel_appointment"](customer_phone=ASHA, appointment_id=first, customer_confirmed=True)
    again = by_name["book_appointment"](**args)
    assert again["ok"] and again["data"]["already_existed"] is False  # the epoch changed
    assert again["data"]["appointment"]["id"] != first


def test_ticket_and_status_tools(tools):
    by_name, *_ = tools
    created = by_name["create_support_ticket"](subject="Billing", description="Charged twice",
                                               customer_confirmed=True, priority="high",
                                               customer_phone=ASHA)
    assert created["ok"]
    tid = created["data"]["ticket"]["id"]
    assert by_name["get_ticket_status"](tid)["data"]["status"] == "open"
    assert by_name["get_ticket_status"](9999) == {"ok": False, "error": "Ticket not found"}


def test_transfer_to_human_tool(tools):
    by_name, *_ = tools
    result = by_name["transfer_to_human"](reason="Wants a callback", customer_confirmed=True,
                                          customer_phone=ASHA)
    assert result["ok"] and result["data"]["ticket"]["priority"] == "urgent"
    assert isinstance(result["data"]["within_business_hours"], bool)


def test_invoice_tool_never_returns_amounts(tools):
    by_name, *_ = tools
    result = by_name["email_my_invoice"](customer_phone=ASHA, customer_confirmed=True)
    assert result["ok"] and result["data"]["email_hint"] == "a***@example.com"
    assert "800" not in str(result) and "INV-" not in str(result)


def test_validation_errors_become_a_friendly_message(tools):
    by_name, *_ = tools
    result = by_name["register_customer"](full_name="X", phone="123", customer_confirmed=True)
    assert result["ok"] is False and isinstance(result["error"], str)


def test_business_system_down_is_reported_not_hidden(tools, monkeypatch):
    by_name, log, _ = tools

    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(agent_tools.httpx, "request", boom)
    result = by_name["search_company_faq"]("hours")
    assert result == {"ok": False, "error": "The business system is not reachable right now."}
    assert log[0]["ok"] is False


def test_wrong_api_key_and_server_errors_are_reported(client, world, monkeypatch):
    def respond(code, body=None):
        def fake(method, url, **kw):
            return httpx.Response(code, json=body if body is not None else {},
                                  request=httpx.Request(method, url))
        return fake

    tool = {f.__name__: f for f in make_tools("jrv_wrong", "s1")}["search_company_faq"]
    monkeypatch.setattr(agent_tools.httpx, "request", respond(401))
    assert "Not authorized" in tool("hours")["error"]
    monkeypatch.setattr(agent_tools.httpx, "request", respond(500))
    assert "had a problem" in tool("hours")["error"]
    monkeypatch.setattr(agent_tools.httpx, "request", respond(422, {"detail": [{"msg": "bad"}]}))
    assert tool("hours")["error"] == "Some of the details were not valid."
    monkeypatch.setattr(agent_tools.httpx, "request",
                        lambda m, u, **k: httpx.Response(400, text="not json", request=httpx.Request(m, u)))
    assert tool("hours")["error"] == "Some of the details were not valid."
