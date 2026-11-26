"""The customer web chat: the safety layer, the reply tags, the server limits, the QR code and poster."""
import re

import pytest
from fastapi.testclient import TestClient

from app.agent import TurnFailed
from app.webchat import guard, qr, server


# ---------- a fake set of company tools that records what was really called ----------
class FakeTools:
    def __init__(self, appointments=None):
        self.calls = []
        self.appointments = appointments if appointments is not None else [
            {"id": 7, "date": "2026-11-12", "time": "10:30", "status": "booked"},
        ]

    def build(self):
        calls = self.calls

        def search_company_faq(question: str) -> dict:
            calls.append(("faq", question)); return {"ok": True, "data": []}

        def lookup_customer(phone: str) -> dict:
            calls.append(("lookup", phone))
            if phone == "+919000000001":
                return {"ok": True, "data": {"full_name": "Asha Rao", "has_email": True, "email_hint": "a***@x.com"}}
            return {"ok": False, "error": "Customer not found"}

        def register_customer(full_name: str, phone: str, customer_confirmed: bool, email: str = "") -> dict:
            calls.append(("register", phone)); return {"ok": True, "data": {}}

        def list_my_appointments(customer_phone: str) -> dict:
            calls.append(("list", customer_phone))
            if customer_phone != "+919000000001":
                return {"ok": False, "error": "Customer not found"}
            return {"ok": True, "data": self.appointments}

        def check_appointment_availability(date: str) -> dict:
            return {"ok": True, "data": {"slots": ["10:30"]}}

        def book_appointment(customer_phone: str, date: str, time: str, customer_confirmed: bool, reason: str = "") -> dict:
            if customer_confirmed is not True:
                return {"ok": False, "error": "The customer has not confirmed yet."}
            calls.append(("book", date, time)); return {"ok": True, "data": {}}

        def reschedule_appointment(customer_phone: str, appointment_id: int, date: str, time: str, customer_confirmed: bool) -> dict:
            calls.append(("reschedule", appointment_id, date, time)); return {"ok": True, "data": {"changed": True}}

        def cancel_appointment(customer_phone: str, appointment_id: int, customer_confirmed: bool) -> dict:
            calls.append(("cancel", appointment_id)); return {"ok": True, "data": {"changed": True}}

        def create_support_ticket(subject: str, description: str, customer_confirmed: bool, priority: str = "normal", customer_phone: str = "") -> dict:
            if customer_confirmed is not True:
                return {"ok": False, "error": "The customer has not confirmed yet."}
            calls.append(("ticket", subject)); return {"ok": True, "data": {"id": 3}}

        def get_ticket_status(ticket_id: int, customer_phone: str) -> dict:
            calls.append(("status", ticket_id))
            if ticket_id == 3 and customer_phone == "+919000000001":
                return {"ok": True, "data": {"status": "open"}}
            return {"ok": False, "error": "Ticket not found"}

        def transfer_to_human(reason: str, customer_confirmed: bool, customer_phone: str = "") -> dict:
            calls.append(("human", reason)); return {"ok": True, "data": {"within_business_hours": True}}

        def email_my_invoice(customer_phone: str, customer_confirmed: bool) -> dict:
            if customer_confirmed is not True:
                return {"ok": False, "error": "The customer has not confirmed yet."}
            calls.append(("invoice", customer_phone))
            return {"ok": True, "data": {"sent": True, "email_hint": "a***@x.com"}}

        return [search_company_faq, lookup_customer, register_customer, list_my_appointments,
                check_appointment_availability, book_appointment, reschedule_appointment, cancel_appointment,
                create_support_ticket, get_ticket_status, transfer_to_human, email_my_invoice]


@pytest.fixture
def tools(monkeypatch):
    fake = FakeTools()
    monkeypatch.setattr(guard, "make_tools", lambda *a, **k: fake.build())
    built = {fn.__name__: fn for fn in guard.web_tools("key", "session")}
    return fake, built


KNOWN = "+919000000001"


# ---------- the safety layer ----------
def test_the_web_chat_has_no_way_to_list_appointments(tools):
    _, built = tools
    assert "list_my_appointments" not in built
    assert {"search_company_faq", "lookup_customer", "register_customer", "check_appointment_availability",
            "book_appointment", "reschedule_appointment", "cancel_appointment", "create_support_ticket",
            "get_ticket_status", "transfer_to_human", "email_my_invoice"} == set(built)


def test_lookup_never_reveals_a_name_or_an_email_hint(tools):
    _, built = tools
    found = built["lookup_customer"](KNOWN)
    assert found == {"ok": True, "data": {"registered": True, "has_email": True}}
    assert "Asha" not in str(found) and "x.com" not in str(found)
    assert built["lookup_customer"]("+919111111111")["ok"] is False


def test_cancel_needs_the_exact_date_and_time_and_never_guesses(tools):
    fake, built = tools
    wrong = built["cancel_appointment"](KNOWN, "2026-11-12", "11:30", True)
    assert wrong == guard.NOT_FOUND and not any(c[0] == "cancel" for c in fake.calls)
    done = built["cancel_appointment"](KNOWN, "2026-11-12", "10:30", True)
    assert done["ok"] is True and ("cancel", 7) in fake.calls


def test_a_stranger_gets_the_same_answer_for_an_unknown_number_and_a_wrong_time(tools):
    _, built = tools
    unknown = built["cancel_appointment"]("+919111111111", "2026-11-12", "10:30", True)
    wrong_time = built["cancel_appointment"](KNOWN, "2026-11-12", "09:00", True)
    assert unknown == wrong_time == guard.NOT_FOUND


def test_time_typed_loosely_still_matches(tools):
    fake, built = tools
    assert guard.clean_time("9.05") == "09:05" and guard.clean_time(" 10:30 ") == "10:30"
    assert built["cancel_appointment"](KNOWN, "2026-11-12", "10.30", True)["ok"] is True


def test_five_wrong_guesses_lock_the_identity_tools_even_for_a_right_guess(tools):
    fake, built = tools
    for hour in ("08:00", "09:00", "11:00", "12:00", "13:00"):
        built["cancel_appointment"](KNOWN, "2026-11-12", hour, True)
    right = built["cancel_appointment"](KNOWN, "2026-11-12", "10:30", True)
    assert right == guard.LOCKED and not any(c[0] == "cancel" for c in fake.calls)
    assert built["get_ticket_status"](3, KNOWN) == guard.LOCKED
    assert built["reschedule_appointment"](KNOWN, "2026-11-12", "10:30", "2026-11-13", "10:30", True) == guard.LOCKED


def test_reschedule_moves_only_the_matched_visit(tools):
    fake, built = tools
    out = built["reschedule_appointment"](KNOWN, "2026-11-12", "10:30", "2026-11-13", "14:40", True)
    assert out["ok"] is True and ("reschedule", 7, "2026-11-13", "14:40") in fake.calls


def test_a_change_without_a_clear_yes_does_nothing(tools):
    fake, built = tools
    for name, args in (("cancel_appointment", (KNOWN, "2026-11-12", "10:30", False)),
                       ("reschedule_appointment", (KNOWN, "2026-11-12", "10:30", "2026-11-13", "14:40", False))):
        assert built[name](*args)["ok"] is False
    assert fake.calls == []


def test_ticket_status_counts_wrong_guesses(tools):
    _, built = tools
    assert built["get_ticket_status"](3, KNOWN)["ok"] is True
    for number in (4, 5, 6, 7, 8):
        assert built["get_ticket_status"](number, KNOWN)["ok"] is False
    assert built["get_ticket_status"](3, KNOWN) == guard.LOCKED


def test_invoice_email_never_returns_the_address_and_is_capped(tools):
    _, built = tools
    out = built["email_my_invoice"](KNOWN, True)
    assert out["ok"] is True and "x.com" not in str(out) and "hint" not in str(out)
    built["email_my_invoice"](KNOWN, True)
    assert built["email_my_invoice"](KNOWN, True) == guard.TOO_MANY


def test_asking_for_a_yes_does_not_use_up_the_limit(tools):
    fake, built = tools
    for _ in range(6):
        assert built["book_appointment"](KNOWN, "2026-11-12", "10:30", False)["ok"] is False
    for _ in range(3):
        assert built["book_appointment"](KNOWN, "2026-11-12", "10:30", True)["ok"] is True
    assert built["book_appointment"](KNOWN, "2026-11-12", "10:30", True) == guard.TOO_MANY
    assert len([c for c in fake.calls if c[0] == "book"]) == 3


def test_tickets_and_handoffs_are_capped_per_chat(tools):
    _, built = tools
    for _ in range(3):
        assert built["create_support_ticket"]("s", "d", True)["ok"] is True
    assert built["create_support_ticket"]("s", "d", True) == guard.TOO_MANY
    for _ in range(2):
        assert built["transfer_to_human"]("r", True)["ok"] is True
    assert built["transfer_to_human"]("r", True) == guard.TOO_MANY


def test_two_chats_never_share_limits(monkeypatch):
    fake = FakeTools()
    monkeypatch.setattr(guard, "make_tools", lambda *a, **k: fake.build())
    one = {f.__name__: f for f in guard.web_tools("k", "a")}
    two = {f.__name__: f for f in guard.web_tools("k", "b")}
    for hour in ("08:00", "09:00", "11:00", "12:00", "13:00"):
        one["cancel_appointment"](KNOWN, "2026-11-12", hour, True)
    assert one["cancel_appointment"](KNOWN, "2026-11-12", "10:30", True) == guard.LOCKED
    assert two["cancel_appointment"](KNOWN, "2026-11-12", "10:30", True)["ok"] is True


# ---------- reply tags ----------
def test_tags_are_removed_and_turned_into_data():
    words, ask, choices = guard.parse_reply("Which day suits you? [[choices: Tue 11 Nov | Wed 12 Nov | Tue 11 Nov | ]]")
    assert words == "Which day suits you?" and ask is None and choices == ["Tue 11 Nov", "Wed 12 Nov"]
    words, ask, choices = guard.parse_reply("What is your mobile number? [[ask:phone]] [[choices: A | B]]")
    assert words == "What is your mobile number?" and ask == "phone" and choices == []
    assert guard.parse_reply("Hello [[ask:password]]")[1:] == (None, [])
    assert "[[" not in guard.parse_reply("x [[weird]] y [[ask:email]]")[0]


def test_choices_are_limited_in_number_and_length():
    _, _, choices = guard.parse_reply("Pick [[choices: " + " | ".join(f"Option {i}" for i in range(20)) + "]]")
    assert len(choices) == guard.MAX_CHOICES
    _, _, long = guard.parse_reply("Pick [[choices: " + "x" * 200 + " | y]]")
    assert len(long[0]) == guard.MAX_CHOICE_LEN


# ---------- the server ----------
DENTAL = "DentalCode_01"          # the QR code of Smile Dental (random in real life)
SHOP = "ShopCode_0002"


class FakeAI:
    def __init__(self, key, replies):
        self.key, self.replies, self.heard = key, list(replies), []

    def send(self, text):
        self.heard.append(text)
        reply = self.replies.pop(0) if self.replies else "Okay."
        if isinstance(reply, Exception):
            raise reply
        return reply, "fake-model"


@pytest.fixture
def chat(monkeypatch):
    monkeypatch.setenv("JARVIS_KEY_SMILE_DENTAL", "jrv_dental_key_for_tests")
    monkeypatch.setenv("JARVIS_KEY_SHOPEASY", "jrv_shop_key_for_tests")
    monkeypatch.setenv("CHAT_CODE_SMILE_DENTAL", DENTAL)
    monkeypatch.setenv("CHAT_CODE_SHOPEASY", SHOP)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://jarvis.example.com")
    for name in ("CHAT_MESSAGES_PER_MINUTE", "CHAT_MAX_TURNS", "CHAT_DAILY_MESSAGES", "CHAT_SESSIONS_PER_HOUR", "CHAT_BAD_CODES_PER_MINUTE"):
        monkeypatch.delenv(name, raising=False)
    made = {}

    def factory(company, key, session_id):
        ai = FakeAI(key, made.get("replies", []))
        made.setdefault("ais", []).append(ai)
        return ai

    monkeypatch.setattr(server, "FACTORY", factory)
    names = {"smile-dental": "Smile Dental Clinic", "shopeasy": "ShopEasy"}
    monkeypatch.setattr(server, "load_company", lambda slug: {"name": names[slug], "agent_name": "Asha"})
    for limiter in (server.message_limiter, server.session_limiter, server.bad_code_limiter):
        limiter.reset()
    server.SESSIONS.clear(); server.DAILY.clear(); server.COMPANIES.clear()
    client = TestClient(server.app)
    client.made = made
    return client


def start(chat, code=DENTAL):
    r = chat.post(f"/c/{code}/session")
    assert r.status_code == 200
    return r.json()["session"]


def test_only_a_listed_code_opens_a_chat_and_the_company_name_is_not_the_address(chat):
    assert chat.get(f"/c/{DENTAL}").status_code == 200
    for wrong in ("smile-dental", "shopeasy", "WrongCode_9999", "x", "..%2F..%2Fetc", "A" * 100):
        assert chat.get(f"/c/{wrong}").status_code in (404, 422), wrong
        assert chat.post(f"/c/{wrong}/session").status_code in (404, 422), wrong


def test_page_has_no_company_data_and_no_secrets(chat):
    page = chat.get(f"/c/{DENTAL}")
    assert "Smile Dental" not in page.text and "jrv_" not in page.text and f'data-code="{DENTAL}"' in page.text


def test_page_security_headers_and_rules_match_the_dashboard(chat):
    a, b = chat.get(f"/c/{DENTAL}"), chat.get(f"/c/{DENTAL}")
    csp = a.headers["content-security-policy"]
    nonce = re.search(r"script-src 'nonce-([\w\-]+)'", csp).group(1)
    assert "default-src 'none'" in csp and "connect-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert f'nonce="{nonce}"' in a.text and a.text.count('nonce="') == 2
    assert nonce not in b.headers["content-security-policy"] and a.headers["cache-control"] == "no-store"
    html = a.text
    for forbidden in ("localStorage", "sessionStorage", "document.cookie", "innerHTML", "outerHTML", "insertAdjacentHTML",
                      "document.write", "eval(", "new Function", "location.search", "location.hash"):
        assert forbidden not in html, forbidden
    assert 'style="' not in html and "<link" not in html and "fonts.googleapis" not in html
    web = html.replace("http://www.w3.org/2000/svg", "")
    assert "http://" not in web and "https://" not in web
    assert "prefers-color-scheme:dark" in html


def test_page_is_made_for_phones(chat):
    html = chat.get(f"/c/{DENTAL}").text
    for needed in ("viewport-fit=cover", "interactive-widget=resizes-content", "env(safe-area-inset-top)",
                   "env(safe-area-inset-bottom)", "env(safe-area-inset-left)", "visualViewport", "100dvh",
                   "-apple-system-body", "-webkit-text-size-adjust", 'name="theme-color"', "max(16px,1rem)",
                   "system-ui", "-apple-system", "Roboto"):
        assert needed in html, needed
    assert re.search(r"font-size:\s*\d+px", html) is None or "max(16px" in html      # sizes come from rem, so the phone's text size applies
    assert 'id="back"' in html and "popstate" in html and "pushState" in html


def test_session_returns_no_key_and_a_message_gets_a_parsed_reply(chat):
    chat.made["replies"] = ["What is your mobile number? [[ask:phone]]"]
    r = chat.post(f"/c/{DENTAL}/session")
    assert r.json()["name"] == "Smile Dental Clinic" and "jrv_" not in r.text
    token = r.json()["session"]
    reply = chat.post(f"/c/{DENTAL}/message", json={"session": token, "text": "I would like to book an appointment"})
    assert reply.status_code == 200 and reply.json() == {"reply": "What is your mobile number?", "ask": "phone", "choices": []}
    assert chat.made["ais"][0].key == "jrv_dental_key_for_tests"


def test_each_company_has_its_own_code_key_and_chats(chat):
    token = start(chat, DENTAL)
    assert chat.post(f"/c/{SHOP}/message", json={"session": token, "text": "hello there"}).status_code == 410
    shop = start(chat, SHOP)
    assert chat.made["ais"][1].key == "jrv_shop_key_for_tests" and chat.made["ais"][0].key != chat.made["ais"][1].key
    assert chat.post(f"/c/{DENTAL}/message", json={"session": shop, "text": "hello there"}).status_code == 410


def test_a_chat_cannot_be_moved_to_another_code_even_of_the_same_company(chat, monkeypatch):
    monkeypatch.setenv("CHAT_CODE_SMILE_DENTAL", f"{DENTAL},DentalDesk_02")
    desk1, desk2 = start(chat, DENTAL), start(chat, "DentalDesk_02")
    assert chat.post("/c/DentalDesk_02/message", json={"session": desk1, "text": "hello there"}).status_code == 410
    assert chat.post(f"/c/{DENTAL}/message", json={"session": desk1, "text": "hello there"}).status_code == 200
    assert chat.post("/c/DentalDesk_02/message", json={"session": desk2, "text": "hello there"}).status_code == 200


def test_replacing_a_code_kills_the_old_qr(chat, monkeypatch):
    token = start(chat, DENTAL)
    monkeypatch.setenv("CHAT_CODE_SMILE_DENTAL", "DentalNewCode_9")                 # what "new --replace" does, after a restart
    assert chat.get(f"/c/{DENTAL}").status_code == 404
    assert chat.post(f"/c/{DENTAL}/message", json={"session": token, "text": "hello there"}).status_code == 404
    assert chat.get("/c/DentalNewCode_9").status_code == 200


def test_revoking_all_codes_turns_the_chat_off(chat, monkeypatch):
    monkeypatch.delenv("CHAT_CODE_SMILE_DENTAL")
    assert chat.get(f"/c/{DENTAL}").status_code == 404 and chat.get(f"/c/{SHOP}").status_code == 200


def test_a_code_for_a_company_without_a_key_does_nothing(chat, monkeypatch):
    monkeypatch.setenv("CHAT_CODE_GHOST_CO", "GhostCode_0003")
    assert chat.get("/c/GhostCode_0003").status_code == 404


def test_guessing_codes_is_rate_limited(chat, monkeypatch):
    monkeypatch.setenv("CHAT_BAD_CODES_PER_MINUTE", "3")
    codes = [chat.get(f"/c/GuessNumber_{i:03d}").status_code for i in range(5)]
    assert codes == [404, 404, 404, 429, 429]
    assert chat.get(f"/c/{DENTAL}").status_code == 429                       # even the right code waits, so guessing cannot continue


def test_bad_tokens_and_bad_input_are_refused(chat):
    start(chat)
    assert chat.post(f"/c/{DENTAL}/message", json={"session": "x" * 30, "text": "hi"}).status_code == 410
    token = start(chat)
    assert chat.post(f"/c/{DENTAL}/message", json={"session": token, "text": "a" * 501}).status_code == 422
    assert chat.post(f"/c/{DENTAL}/message", json={"session": token, "text": ""}).status_code == 422
    assert chat.post(f"/c/{DENTAL}/message", json={"session": "short", "text": "hi"}).status_code == 422


def test_message_rate_limit_session_limit_and_turn_cap(chat, monkeypatch):
    token = start(chat)
    monkeypatch.setenv("CHAT_MESSAGES_PER_MINUTE", "3")
    codes = [chat.post(f"/c/{DENTAL}/message", json={"session": token, "text": "hi there"}).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    server.message_limiter.reset(); monkeypatch.delenv("CHAT_MESSAGES_PER_MINUTE")
    monkeypatch.setenv("CHAT_MAX_TURNS", "2")
    t2 = start(chat)
    codes = [chat.post(f"/c/{DENTAL}/message", json={"session": t2, "text": "hi there"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    server.session_limiter.reset(); monkeypatch.setenv("CHAT_SESSIONS_PER_HOUR", "2")
    assert [chat.post(f"/c/{DENTAL}/session").status_code for _ in range(3)] == [200, 200, 429]


def test_the_daily_budget_protects_the_ai_bill(chat, monkeypatch):
    monkeypatch.setenv("CHAT_DAILY_MESSAGES", "2")
    token = start(chat)
    codes = [chat.post(f"/c/{DENTAL}/message", json={"session": token, "text": "hi there"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    other = start(chat, SHOP)                              # another company has its own budget
    assert chat.post(f"/c/{SHOP}/message", json={"session": other, "text": "hi there"}).status_code == 200


def test_expired_chats_are_gone(chat):
    token = start(chat)
    server.SESSIONS[token]["expires"] = 0
    assert chat.post(f"/c/{DENTAL}/message", json={"session": token, "text": "hi there"}).status_code == 410


def test_when_the_ai_is_down_the_customer_is_handed_to_staff_not_dropped(chat, monkeypatch):
    chat.made["replies"] = [TurnFailed("down")]
    seen = {}

    def fake_handoff(key, text, phone, session_id):
        seen.update(key=key, text=text, phone=phone)
        return {"within_business_hours": True}

    monkeypatch.setattr(server, "handoff", fake_handoff)
    token = start(chat)
    r = chat.post(f"/c/{DENTAL}/message", json={"session": token, "text": "call me on +91********* please"})
    assert r.status_code == 200 and "passed your request to our team" in r.json()["reply"]
    assert seen == {"key": "jrv_dental_key_for_tests", "text": "call me on +91**********8 please", "phone": "+91*******"}


def test_a_bug_in_a_turn_hands_over_to_staff_instead_of_an_error_page(chat, monkeypatch):
    chat.made["replies"] = [RuntimeError("boom")]
    monkeypatch.setattr(server, "handoff", lambda *a: {"within_business_hours": True})
    token = start(chat)
    r = chat.post(f"/c/{DENTAL}/message", json={"session": token, "text": "hello there"})
    assert r.status_code == 200 and "passed your request to our team" in r.json()["reply"]
    assert chat.post(f"/c/{DENTAL}/message", json={"session": token, "text": "still there"}).status_code == 200   # chat is not stuck busy


def test_if_the_ai_cannot_start_the_customer_gets_a_clean_message_not_a_stack_trace(chat, monkeypatch):
    def broken(company, key, session_id):
        raise KeyError("GEMINI_API_KEY")
    monkeypatch.setattr(server, "FACTORY", broken)
    r = chat.post(f"/c/{DENTAL}/session")
    assert r.status_code == 503 and "GEMINI" not in r.text and "try again" in r.json()["detail"]


@pytest.fixture(autouse=True)
def _no_real_public_url(monkeypatch):
    """Your real .env sets PUBLIC_BASE_URL; these tests must not depend on it."""
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)


# ---------- QR code and poster ----------
def test_public_url_is_built_only_from_a_valid_base_and_code():
    assert qr.public_url(DENTAL, "https://jarvis.example.com/") == f"https://jarvis.example.com/c/{DENTAL}"
    for base in ("", "ftp://x.com", "jarvis.example.com"):
        with pytest.raises(ValueError):
            qr.public_url(DENTAL, base)
    for bad in ("short", "../etc/passwd_xx", "has space code!", ""):
        with pytest.raises(ValueError):
            qr.public_url(bad, "https://x.com")


def test_qr_svg_is_made_here_and_is_different_for_each_company(chat):
    a, b = chat.get(f"/c/{DENTAL}/qr.svg"), chat.get(f"/c/{SHOP}/qr.svg")
    assert a.status_code == 200 and a.headers["content-type"].startswith("image/svg+xml") and a.text.startswith("<svg")
    assert a.content == qr.svg_bytes(f"https://jarvis.example.com/c/{DENTAL}") and a.content != b.content
    assert chat.get("/c/WrongCode_9999/qr.svg").status_code == 404


def test_qr_png_is_a_real_png():
    assert qr.png_bytes(f"https://jarvis.example.com/c/{DENTAL}")[:8] == b"\x89PNG\r\n\x1a\n"


def test_poster_has_the_company_the_qr_and_is_safe(chat, monkeypatch):
    r = chat.get(f"/c/{DENTAL}/poster")
    assert r.status_code == 200 and "Smile Dental Clinic" in r.text and "<svg" in r.text
    assert f"https://jarvis.example.com/c/{DENTAL}" in r.text and 'style="' not in r.text
    assert "unsafe-inline" not in r.headers["content-security-policy"]
    monkeypatch.setattr(server, "load_company", lambda slug: {"name": "<script>alert(1)</script>", "agent_name": "A"})
    assert "<script>alert(1)</script>" not in chat.get(f"/c/{DENTAL}/poster").text
    monkeypatch.delenv("PUBLIC_BASE_URL")
    assert chat.get(f"/c/{DENTAL}/poster").status_code == 503 and chat.get(f"/c/{DENTAL}/qr.svg").status_code == 503


# ---------- making, replacing and revoking codes (like staff keys) ----------
@pytest.fixture
def folder(tmp_path):
    (tmp_path / ".env").write_text("DATABASE_URL=postgresql://x\nJARVIS_KEY_SMILE_DENTAL=jrv_x\nPUBLIC_BASE_URL=https://jarvis.example.com\nOTHER=keep me\n")
    return tmp_path


def codes_in(folder, slug="smile-dental"):
    return qr.codes_of(qr.read_env(folder / ".env"), slug)


def test_new_makes_a_random_code_and_qr_files_and_keeps_other_env_lines(folder, capsys):
    assert qr.main(["new", "smile-dental"], folder) == 0
    codes = codes_in(folder)
    assert len(codes) == 1 and qr.CODE.match(codes[0])
    env = (folder / ".env").read_text()
    assert "OTHER=keep me" in env and "DATABASE_URL=postgresql://x" in env and f"CHAT_CODE_SMILE_DENTAL={codes[0]}" in env
    stem = f"smile-dental-{codes[0][:4]}"
    assert (folder / "qr" / f"{stem}.svg").exists() and (folder / "qr" / f"{stem}.png").exists()
    assert f"https://jarvis.example.com/c/{codes[0]}" in capsys.readouterr().out


def test_every_new_code_is_different_and_older_ones_keep_working(folder):
    qr.main(["new", "smile-dental"], folder); qr.main(["new", "smile-dental"], folder)
    codes = codes_in(folder)
    assert len(codes) == 2 and codes[0] != codes[1]


def test_replace_kills_every_older_code(folder):
    qr.main(["new", "smile-dental"], folder)
    old = codes_in(folder)[0]
    assert qr.main(["new", "smile-dental", "--replace"], folder) == 0
    now = codes_in(folder)
    assert len(now) == 1 and now[0] != old and old not in (folder / ".env").read_text()


def test_revoke_removes_the_codes_and_nothing_else(folder, capsys):
    qr.main(["new", "smile-dental"], folder)
    assert qr.main(["revoke", "smile-dental"], folder) == 0
    assert codes_in(folder) == [] and "OTHER=keep me" in (folder / ".env").read_text() and "CHAT_CODE_" not in (folder / ".env").read_text()


def test_show_remakes_files_and_list_counts_codes(folder, capsys):
    qr.main(["new", "smile-dental"], folder)
    for f in (folder / "qr").iterdir():
        f.unlink()
    assert qr.main(["show", "smile-dental"], folder) == 0 and len(list((folder / "qr").iterdir())) == 2
    capsys.readouterr()
    assert qr.main(["list"], folder) == 0 and "smile-dental: 1 active code(s)" in capsys.readouterr().out


def test_cli_refuses_unknown_companies_bad_names_and_a_missing_base_address(folder, capsys):
    assert qr.main(["new", "no-such-co"], folder) == 1 and "JARVIS_KEY_NO_SUCH_CO" in capsys.readouterr().out
    assert qr.main(["new", "../etc"], folder) == 1 and qr.main([], folder) == 1 and qr.main(["bogus"], folder) == 1
    (folder / ".env").write_text("JARVIS_KEY_SMILE_DENTAL=jrv_x\n")
    assert qr.main(["new", "smile-dental"], folder) == 1 and "PUBLIC_BASE_URL" in capsys.readouterr().out
    assert codes_in(folder) == []                                           # nothing was changed when it failed


# ---------- deployment helpers ----------
def test_chat_env_file_leaves_out_database_password_and_staff_keys(tmp_path):
    from app.webchat import split_env
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgresql://owner:secret@db/x\nJARVIS_APP_DB_PASSWORD=pw\nJARVIS_STAFF_SMILE=stf_x\n"
        "N8N_WEBHOOK_SECRET=n8n\nGEMINI_API_KEY=g\nJARVIS_KEY_SMILE_DENTAL=jrv_x\nCHAT_PHONE_SMILE_DENTAL=+919876543210\n"
        "CHAT_CODE_SMILE_DENTAL=AbCdEf123456\nPUBLIC_BASE_URL=https://jarvis.example.com\nLIVEKIT_API_SECRET=lk\n")
    assert split_env.main(tmp_path) == 0
    written = (tmp_path / ".env.chat").read_text()
    for kept in ("GEMINI_API_KEY", "JARVIS_KEY_SMILE_DENTAL", "CHAT_PHONE_SMILE_DENTAL", "CHAT_CODE_SMILE_DENTAL", "PUBLIC_BASE_URL"):
        assert kept in written
    for left in ("DATABASE_URL", "JARVIS_APP_DB_PASSWORD", "JARVIS_STAFF_SMILE", "N8N_WEBHOOK_SECRET", "LIVEKIT_API_SECRET", "secret@db"):
        assert left not in written
    assert ".env.chat" in (tmp_path / ".gitignore").read_text()


def test_chat_env_file_needs_the_public_address_and_a_company_key(tmp_path):
    from app.webchat import split_env
    (tmp_path / ".env").write_text("GEMINI_API_KEY=g\nJARVIS_KEY_SMILE_DENTAL=jrv_x\n")
    assert split_env.main(tmp_path) == 1
    (tmp_path / ".env").write_text("GEMINI_API_KEY=g\nPUBLIC_BASE_URL=https://x.com\n")
    assert split_env.main(tmp_path) == 1


def test_caddy_sends_only_the_chat_paths_to_the_chat_service():
    import pathlib
    text = (pathlib.Path(__file__).resolve().parents[1] / "deploy" / "Caddyfile").read_text()
    assert "handle /c/*" in text and "webchat:8100" in text and "api:8000" in text
    assert "@private path /internal/*" in text                       # still blocked from the internet
