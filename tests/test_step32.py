"""Step 32: personal logins, roles, usage caps, the owner tool."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select

from app import owner
from app.accounts import check_password, hash_password
from app.models import AuditLog, CallRecord, Company, StaffSession, StaffUser
from app.usage import month_window, usage_for
from app.voice.worker import cap_reached
from conftest import AdminSession, KEYS

PW = "correct-horse-battery"


def add_user(world, slug_id="dental_id", email="boss@x.com", role="owner", password=PW):
    with AdminSession() as db:
        db.add(StaffUser(company_id=world[slug_id], email=email, full_name="Test Person", role=role,
                         password_hash=hash_password(password)))
        db.commit()


def login(client, company="smile-dental", email="boss@x.com", password=PW):
    return client.post("/staff/login", json={"company": company, "email": email, "password": password})


def tok(client, **kw):
    r = login(client, **kw)
    assert r.status_code == 200, r.text
    return {"X-API-Key": r.json()["token"]}


def test_password_hash_is_salted_and_checks(world):
    a, b = hash_password("same-password-1"), hash_password("same-password-1")
    assert a != b and check_password("same-password-1", a) and not check_password("other", a)
    assert not check_password("x", "garbage")


def test_login_works_and_token_opens_staff_screens(client, world):
    add_user(world)
    r = login(client)
    assert r.status_code == 200 and r.json()["token"].startswith("stu_") and r.json()["role"] == "owner"
    h = {"X-API-Key": r.json()["token"]}
    assert client.get("/staff/company", headers=h).json()["name"] == "Smile Dental"
    assert client.get("/staff/me", headers=h).json()["kind"] == "login"
    with AdminSession() as db:
        assert "stu_" not in " ".join(s.token_hash for s in db.scalars(select(StaffSession)))   # only a fingerprint
        assert db.scalar(select(AuditLog).where(AuditLog.action == "staff_user.login"))


def test_wrong_password_unknown_email_and_unknown_company_look_the_same(client, world):
    add_user(world)
    msgs = {login(client, password="nope-nope-nope").json()["detail"],
            login(client, email="who@x.com").json()["detail"],
            login(client, company="no-such").json()["detail"]}
    assert msgs == {"Invalid login"}


def test_five_wrong_passwords_lock_the_account_even_for_the_right_password(client, world, monkeypatch):
    add_user(world)
    for i in range(5):
        client.post("/staff/login", json={"company": "smile-dental", "email": "boss@x.com", "password": "wrong-pass-1"},
                    headers={"X-Forwarded-For": f"9.9.9.{i}"})
    from app.ratelimit import reset_all
    reset_all()
    assert login(client).status_code == 429
    with AdminSession() as db:
        u = db.scalar(select(StaffUser)); u.locked_until = datetime.now(timezone.utc) - timedelta(minutes=1); db.commit()
    assert login(client).status_code == 200                                   # lock expired


def test_a_login_never_opens_another_company(client, world):
    add_user(world)
    h = tok(client)
    assert client.get("/staff/company", headers=h).json()["name"] == "Smile Dental"
    add_user(world, "shop_id", "boss@x.com")                                  # same email in the other company
    assert login(client, company="shopeasy").status_code == 200
    assert client.get("/staff/company", headers=tok(client, company="shopeasy")).json()["name"] == "ShopEasy"
    assert client.get("/staff/users", headers=h).json()[0]["email"] == "boss@x.com" and len(client.get("/staff/users", headers=h).json()) == 1


def test_expired_and_logged_out_tokens_stop_working(client, world):
    add_user(world)
    h = tok(client)
    assert client.post("/staff/logout", headers=h).status_code == 200
    assert client.get("/staff/company", headers=h).status_code == 401
    h2 = tok(client)
    with AdminSession() as db:
        s = db.scalars(select(StaffSession).where(StaffSession.revoked.is_(False))).one()
        s.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1); db.commit()
    assert client.get("/staff/company", headers=h2).status_code == 401


def test_ai_key_cannot_use_staff_routes_and_stu_token_cannot_be_forged(client, world):
    assert client.get("/staff/company", headers={"X-API-Key": KEYS["dental"]}).status_code == 401
    assert client.get("/staff/company", headers={"X-API-Key": "stu_" + "a" * 40}).status_code == 401


def test_roles_agent_cannot_change_settings_manager_can_only_owner_manages_people(client, world):
    add_user(world, email="a@x.com", role="agent"); add_user(world, email="m@x.com", role="manager"); add_user(world)
    agent, manager, owner_h = (tok(client, email=e) for e in ("a@x.com", "m@x.com", "boss@x.com"))
    patch = lambda h: client.patch("/staff/company", json={"open_hour": 8}, headers=h).status_code
    assert patch(agent) == 403 and patch(manager) == 200 and patch(owner_h) == 200
    assert client.get("/staff/company", headers=agent).status_code == 200                # may still look
    assert client.get("/staff/users", headers=manager).status_code == 403
    assert client.get("/staff/users", headers={"X-API-Key": KEYS["dental_staff"]}).status_code == 200   # key = owner rights
    with AdminSession() as db:
        who = db.scalar(select(AuditLog).where(AuditLog.action == "company.settings_update").order_by(AuditLog.id.desc()))
        assert who.actor_label == "boss@x.com"                                          # per-person audit


def test_owner_adds_people_resets_passwords_and_switching_off_ends_their_sessions(client, world):
    add_user(world)
    h = tok(client)
    assert client.post("/staff/users", json={"email": "N@X.com", "full_name": "New Agent", "role": "agent", "password": "short"}, headers=h).status_code == 422
    r = client.post("/staff/users", json={"email": "N@X.com", "full_name": "New Agent", "role": "agent", "password": "a-fine-password"}, headers=h)
    assert r.status_code == 201 and r.json()["email"] == "n@x.com"
    assert client.post("/staff/users", json={"email": "n@x.com", "full_name": "Dup", "role": "agent", "password": "a-fine-password"}, headers=h).status_code == 409
    new_h = tok(client, email="n@x.com", password="a-fine-password")
    uid = r.json()["id"]
    assert client.patch(f"/staff/users/{uid}", json={"is_active": False}, headers=h).status_code == 200
    assert client.get("/staff/company", headers=new_h).status_code == 401
    assert login(client, email="n@x.com", password="a-fine-password").status_code == 401
    client.patch(f"/staff/users/{uid}", json={"is_active": True, "password": "brand-new-pass-1"}, headers=h)
    assert login(client, email="n@x.com", password="brand-new-pass-1").status_code == 200


def test_the_last_owner_cannot_be_removed_and_other_companies_users_are_invisible(client, world):
    add_user(world); add_user(world, "shop_id", "s@x.com")
    h = tok(client)
    me = client.get("/staff/users", headers=h).json()[0]["id"]
    assert client.patch(f"/staff/users/{me}", json={"role": "agent"}, headers=h).status_code == 409
    with AdminSession() as db:
        other = db.scalar(select(StaffUser).where(StaffUser.email == "s@x.com")).id
    assert client.patch(f"/staff/users/{other}", json={"is_active": False}, headers=h).status_code == 404


# ---- usage -----------------------------------------------------------------------------
def add_minutes(world, minutes, company="dental_id", when=None, room="r"):
    when = when or datetime.now(timezone.utc)
    with AdminSession() as db:
        db.add(CallRecord(company_id=world[company], room_name=f"call-{room}-{minutes}", direction="inbound", started_at=when,
                          ended_at=when, duration_seconds=minutes * 60, outcome="completed", turn_count=1,
                          transcript=[], tools_used=[], latency_turns=[], providers={}))
        db.commit()


def test_usage_counts_this_month_only_per_company_and_enforces_the_cap(client, world):
    add_minutes(world, 30); add_minutes(world, 99, "shop_id")
    add_minutes(world, 500, when=datetime.now(timezone.utc) - timedelta(days=45), room="old")
    ai = {"X-API-Key": KEYS["dental"]}
    u = client.get("/company/usage", headers=ai).json()
    assert u["used_minutes"] == 30 and u["cap_minutes"] is None and u["allowed"] is True and u["percent"] is None
    with AdminSession() as db:
        db.get(Company, world["dental_id"]).monthly_minutes_cap = 60; db.commit()
    assert client.get("/company/usage", headers=ai).json()["percent"] == 50
    add_minutes(world, 30, room="more")
    u = client.get("/staff/usage", headers={"X-API-Key": KEYS["dental_staff"]}).json()
    assert u["allowed"] is False and u["percent"] == 100
    assert client.get("/company/usage", headers={"X-API-Key": KEYS["shop"]}).json()["allowed"] is True


def test_month_window_follows_the_company_time_zone():
    company = SimpleNamespace(timezone="Asia/Kolkata")
    label, start, end = month_window(company, datetime(2026, 11, 30, 19, 0, tzinfo=timezone.utc))   # already Dec 1 in India
    assert label == "2026-12" and start == datetime(2026, 11, 30, 18, 30, tzinfo=timezone.utc)
    assert end == datetime(2026, 12, 31, 18, 30, tzinfo=timezone.utc)


def test_worker_blocks_over_cap_and_fails_open_when_the_api_is_down():
    ok = lambda body: (lambda url, headers=None, timeout=None: SimpleNamespace(raise_for_status=lambda: None, json=lambda: body))
    assert cap_reached("k", get=ok({"allowed": False})) is True
    assert cap_reached("k", get=ok({"allowed": True})) is False
    def boom(*a, **k): raise OSError("down")
    assert cap_reached("k", get=boom) is False


# ---- owner tool ------------------------------------------------------------------------
def test_owner_creates_a_working_company_sets_a_cap_and_a_login(client, world, capsys):
    assert owner.main(["company-new", "new-clinic", "New Clinic", "--agent", "Anu", "--cap", "100"]) == 0
    out = capsys.readouterr().out
    ai = next(l.split(":", 1)[1].strip() for l in out.splitlines() if "AI key" in l)
    staff = next(l.split(":", 1)[1].strip() for l in out.splitlines() if l.strip().startswith("staff key"))
    assert client.get("/company/me", headers={"X-API-Key": ai}).json()["slug"] == "new-clinic"
    assert client.get("/staff/usage", headers={"X-API-Key": staff}).json()["cap_minutes"] == 100
    assert client.get("/company/me", headers={"X-API-Key": KEYS["dental"]}).json()["slug"] == "smile-dental"
    assert owner.main(["company-new", "new-clinic", "Again"]) == 1
    assert owner.main(["company-new", "Bad Slug", "x"]) == 1
    assert owner.main(["cap", "new-clinic", "none"]) == 0
    assert owner.main(["cap", "new-clinic", "abc"]) == 2
    assert owner.main(["user-new", "new-clinic", "me@clinic.com", "Me", "--role", "owner", "--password", PW]) == 0
    assert login(client, company="new-clinic", email="me@clinic.com").status_code == 200
    assert owner.main(["user-new", "new-clinic", "me@clinic.com", "Me", "--password", PW]) == 1
    assert owner.main(["user-new", "new-clinic", "x@clinic.com", "X", "--password", "short"]) == 1
    capsys.readouterr()
    assert owner.main(["overview"]) == 0 and "new-clinic" in capsys.readouterr().out


def test_switching_a_company_off_stops_its_logins_and_keys(client, world):
    add_user(world)
    h = tok(client)
    assert owner.main(["company-off", "smile-dental"]) == 0
    assert client.get("/staff/company", headers=h).status_code == 403
    assert login(client).status_code == 401
    assert owner.main(["company-on", "smile-dental"]) == 0
    assert client.get("/staff/company", headers=h).status_code == 200


def test_dashboard_page_offers_both_sign_in_ways_without_external_resources(client):
    html = client.get("/dashboard").text
    assert 'id="userform"' in html and 'id="loginform"' in html and 'type="password"' in html
    assert "localStorage" not in html and "innerHTML" not in html
