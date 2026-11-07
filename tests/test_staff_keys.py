"""The owner command that creates and replaces staff keys."""
from sqlalchemy import select

from app import staff_keys
from app.models import AuditLog, StaffKey
from conftest import AdminSession, KEYS


def staff(world, client, who):
    return client.get("/staff/company", headers={"X-API-Key": who})


def test_a_new_key_works_and_is_stored_only_as_a_fingerprint(client, world, capsys, monkeypatch):
    monkeypatch.setenv("ADMIN_DATABASE_URL", __import__("os").environ["ADMIN_DATABASE_URL"])
    assert staff_keys.main(["new", "smile-dental"]) == 0
    out = capsys.readouterr().out
    raw = next(line.split("key:")[1].strip() for line in out.splitlines() if "key:" in line)
    assert raw.startswith("stf_") and len(raw) > 40
    assert staff(world, client, raw).status_code == 200
    assert staff(world, client, KEYS["dental_staff"]).status_code == 200     # old key still works without --replace
    with AdminSession() as db:
        stored = [k.key_hash for k in db.scalars(select(StaffKey))]
        assert raw not in stored and all(len(h) == 64 for h in stored)


def test_replace_switches_off_old_keys_of_that_company_only(client, world, capsys):
    assert staff_keys.main(["new", "smile-dental", "--replace"]) == 0
    raw = next(l.split("key:")[1].strip() for l in capsys.readouterr().out.splitlines() if "key:" in l)
    assert staff(world, client, KEYS["dental_staff"]).status_code == 401      # the exposed key is dead
    assert staff(world, client, raw).status_code == 200
    assert staff(world, client, KEYS["shop_staff"]).status_code == 200        # the other company is untouched


def test_all_replaces_every_company_and_keys_never_cross_companies(client, world, capsys):
    assert staff_keys.main(["new", "--all", "--replace"]) == 0
    lines = capsys.readouterr().out.splitlines()
    keys = [l.split("key:")[1].strip() for l in lines if "key:" in l]
    assert len(keys) == 2 and keys[0] != keys[1]
    for old in ("dental_staff", "shop_staff"):
        assert staff(world, client, KEYS[old]).status_code == 401
    names = [staff(world, client, k).json()["name"] for k in keys]
    assert sorted(names) == ["ShopEasy", "Smile Dental"]
    with AdminSession() as db:
        assert len(list(db.scalars(select(AuditLog).where(AuditLog.action == "staff_key.issue")))) == 2


def test_bad_input_is_refused_with_a_clear_message(world, capsys):
    assert staff_keys.main(["new", "no-such-company"]) == 1
    assert "No company with slug" in capsys.readouterr().out
    assert staff_keys.main(["new"]) == 2
    assert staff_keys.main(["new", "smile-dental", "--all"]) == 2


def test_list_shows_companies_and_active_key_counts(world, capsys):
    assert staff_keys.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "smile-dental" in out and "shopeasy" in out and "active staff keys: 1" in out
