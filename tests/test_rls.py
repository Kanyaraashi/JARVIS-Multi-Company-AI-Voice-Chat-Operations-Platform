"""Row-level security: the database itself keeps companies apart."""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session

from app.db import SessionLocal, engine, use_company, use_system
from app.models import Appointment, Company, Customer, Faq, SupportTicket
from app.security import get_current_company
from app.db import get_db
from conftest import AdminSession, admin_engine, KEYS, new_key

TABLES_WITH_COMPANY_ID = [
    "faqs", "customers", "support_tickets", "api_keys", "workflow_events",
    "appointments", "staff_keys", "ticket_updates", "invoices", "audit_log",
]


def app_session(**info) -> Session:
    return SessionLocal(info=info)


# ---------- the API's database user ----------

def test_api_user_cannot_bypass_the_rules(world):
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = current_user"
        )).one()
    assert tuple(row) == (False, False, False, False)


def test_api_user_cannot_delete_truncate_or_change_tables(world):
    with engine.connect() as conn:
        for sql in ("DELETE FROM customers", "TRUNCATE customers", "DROP TABLE faqs",
                    "ALTER TABLE customers ADD COLUMN x int", "SELECT * FROM alembic_version"):
            trans = conn.begin()
            with pytest.raises(ProgrammingError):
                conn.execute(text(sql))
            trans.rollback()


# ---------- fail closed ----------

def test_a_session_with_no_company_sees_nothing(world):
    with AdminSession() as admin:
        assert admin.query(Customer).count() == 3  # the data exists
    with app_session() as db:
        for model in (Customer, Company, Faq):
            assert db.scalars(select(model)).all() == []


def test_a_session_with_no_company_cannot_insert(world):
    with app_session() as db:
        db.add(Faq(company_id=world["dental_id"], question="q", answer="a"))
        with pytest.raises(DBAPIError, match="row-level security"):
            db.commit()


# ---------- one company only ----------

def test_company_session_sees_only_its_own_rows(world):
    with app_session() as db:
        use_company(db, world["dental_id"])
        customers = db.scalars(select(Customer)).all()
        assert {c.full_name for c in customers} == {"Asha Rao", "Sanjay NoEmail"}
        assert [c.slug for c in db.scalars(select(Company)).all()] == ["smile-dental"]
        assert len(db.scalars(select(Faq)).all()) == 1
    with app_session() as db:
        use_company(db, world["shop_id"])
        assert [c.full_name for c in db.scalars(select(Customer)).all()] == ["Dev Shop"]


def test_the_context_survives_commit_and_the_next_transaction(world):
    with app_session() as db:
        use_company(db, world["dental_id"])
        db.add(Faq(company_id=world["dental_id"], question="New?", answer="Yes"))
        db.commit()
        # a new transaction starts here; it must still be limited to this company
        assert len(db.scalars(select(Faq)).all()) == 2
        assert db.scalars(select(Customer).where(Customer.company_id == world["shop_id"])).all() == []


def test_switching_company_inside_a_session_takes_effect_immediately(world):
    with app_session() as db:
        use_company(db, world["dental_id"])
        assert db.query(Customer).count() == 2
        use_company(db, world["shop_id"])
        assert db.query(Customer).count() == 1


def test_a_company_cannot_write_into_another_company(world):
    with app_session() as db:
        use_company(db, world["dental_id"])
        db.add(Faq(company_id=world["shop_id"], question="planted", answer="planted"))
        with pytest.raises(DBAPIError, match="row-level security"):
            db.commit()


def test_a_company_cannot_change_or_move_another_companys_rows(world):
    with app_session() as db:
        use_company(db, world["dental_id"])
        result = db.execute(text("UPDATE customers SET full_name = 'hacked' WHERE company_id = :c"),
                            {"c": world["shop_id"]})
        assert result.rowcount == 0
        db.commit()
        # and it cannot hand its own row to another company
        with pytest.raises(DBAPIError, match="row-level security"):
            db.execute(text("UPDATE customers SET company_id = :c WHERE id = :i"),
                       {"c": world["shop_id"], "i": world["asha_id"]})
    with AdminSession() as admin:
        assert admin.get(Customer, world["dev_id"]).full_name == "Dev Shop"
        assert admin.get(Customer, world["asha_id"]).company_id == world["dental_id"]


def test_system_mode_sees_every_company(world):
    with app_session() as db:
        use_system(db)
        assert db.query(Customer).count() == 3
        assert db.query(Company).count() == 2


def test_a_missing_company_setting_is_not_a_wildcard(world):
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SELECT set_config('app.company_id', '', true)"))
            assert conn.execute(text("SELECT count(*) FROM customers")).scalar() == 0


def test_the_setting_does_not_leak_through_the_connection_pool(world):
    with app_session() as db:
        use_company(db, world["dental_id"])
        assert db.query(Customer).count() == 2
    for _ in range(5):  # likely to reuse the same pooled connection
        with app_session() as db:
            assert db.query(Customer).count() == 0


# ---------- defence in depth: the database stops a forgotten filter ----------

def test_a_forgotten_company_filter_in_the_code_cannot_leak_data(world):
    """An endpoint that forgets WHERE company_id = ... still only returns its own company."""
    leaky = FastAPI()

    @leaky.get("/everything")
    def everything(company=Depends(get_current_company), db: Session = Depends(get_db)):
        return {
            "customers": [c.full_name for c in db.scalars(select(Customer)).all()],  # no filter!
            "faqs": [f.answer for f in db.scalars(select(Faq)).all()],               # no filter!
        }

    client = TestClient(leaky)
    dental = client.get("/everything", headers={"X-API-Key": KEYS["dental"]}).json()
    shop = client.get("/everything", headers={"X-API-Key": KEYS["shop"]}).json()
    assert sorted(dental["customers"]) == ["Asha Rao", "Sanjay NoEmail"]
    assert shop["customers"] == ["Dev Shop"]
    assert all("Dental" in a for a in dental["faqs"]) and all("Shop" in a for a in shop["faqs"])


def test_background_event_sending_still_works_for_every_company(client, world, h, n8n, events):
    for who in ("dental", "shop"):
        client.post("/tickets", json={"subject": "Hello", "description": "Please help"},
                    headers=h(who, **{"Idempotency-Key": new_key()}))
    assert [e["status"] for e in events()] == ["sent", "sent"]
    assert {e["company_id"] for e in events()} == {world["dental_id"], world["shop_id"]}


# ---------- guard against forgetting a new table ----------

def test_every_table_with_a_company_id_is_protected():
    with admin_engine.connect() as conn:
        with_company_id = {r[0] for r in conn.execute(text(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name = 'company_id'"))}
        protected = {r[0] for r in conn.execute(text(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relrowsecurity AND c.relforcerowsecurity"))}
    assert with_company_id == set(TABLES_WITH_COMPANY_ID)
    assert with_company_id <= protected, f"No row-level security on: {with_company_id - protected}"
    assert "companies" in protected
