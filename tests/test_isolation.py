"""Company A must never see or change company B's data."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from conftest import AdminSession as SessionLocal
from conftest import new_key


def make_ticket(client, h, who, phone=None):
    return client.post(
        "/tickets",
        json={"subject": "Question", "description": "Something is wrong",
              "customer_phone": phone},
        headers=h(who, **{"Idempotency-Key": new_key()}),
    )


def test_missing_and_wrong_keys_are_rejected(client, world, h):
    assert client.get("/company/me").status_code == 401
    assert client.get("/company/me", headers={"X-API-Key": "jrv_nope"}).status_code == 401


def test_each_key_sees_only_its_own_company(client, world, h):
    assert client.get("/company/me", headers=h("dental")).json()["slug"] == "smile-dental"
    assert client.get("/company/me", headers=h("shop")).json()["slug"] == "shopeasy"


def test_faq_search_is_separated(client, world, h):
    dental = client.get("/faq/search", params={"q": "opening hours"}, headers=h("dental")).json()
    shop = client.get("/faq/search", params={"q": "opening hours"}, headers=h("shop")).json()
    assert len(dental) == 1 and "Dental" in dental[0]["answer"]
    assert shop == []
    policy = client.get("/faq/search", params={"q": "return policy"}, headers=h("dental")).json()
    assert policy == []


def test_same_phone_in_two_companies_gives_different_customers(client, world, h):
    a = client.get("/customers/lookup", params={"phone": "+919000000001"}, headers=h("dental")).json()
    b = client.get("/customers/lookup", params={"phone": "+919000000001"}, headers=h("shop")).json()
    assert a["full_name"] == "Asha Rao"
    assert b["full_name"] == "Dev Shop"
    assert a["id"] != b["id"]


def test_customer_of_another_company_is_not_found(client, world, h):
    r = client.get("/customers/lookup", params={"phone": "+919876543210"}, headers=h("shop"))
    assert r.status_code == 404


def test_cannot_read_another_companys_ticket(client, world, h, n8n):
    ticket_id = make_ticket(client, h, "dental", phone="+919000000001").json()["ticket"]["id"]
    ok = client.get(f"/tickets/{ticket_id}", params={"customer_phone": "+919000000001"}, headers=h("dental"))
    assert ok.status_code == 200
    # the shop has a customer with the very same phone number, but it is not their ticket
    other = client.get(f"/tickets/{ticket_id}", params={"customer_phone": "+919000000001"}, headers=h("shop"))
    assert other.status_code == 404


def test_cannot_attach_a_ticket_to_another_companys_customer(client, world, h, n8n):
    r = make_ticket(client, h, "shop", phone="+919876543210")  # Sanjay is a dental customer
    assert r.status_code == 404


def test_cannot_read_or_cancel_another_companys_appointment(client, world, h, n8n, day):
    booked = client.post(
        "/appointments",
        json={"customer_phone": "+919000000001", "date": day(), "time": "10:00:00"},
        headers=h("dental", **{"Idempotency-Key": new_key()}),
    ).json()["appointment"]
    appt = booked["id"]

    assert client.get(f"/appointments/{appt}", headers=h("shop")).status_code == 404
    # The shop has a customer with the same phone number, but still must not be able to cancel it.
    r = client.post(
        f"/appointments/{appt}/cancel",
        json={"customer_phone": "+919000000001"},
        headers=h("shop"),
    )
    assert r.status_code == 404
    assert client.get(f"/appointments/{appt}", headers=h("dental")).json()["status"] == "booked"


def test_availability_is_per_company(client, world, h, n8n, day):
    d = day()
    client.post(
        "/appointments",
        json={"customer_phone": "+919000000001", "date": d, "time": "10:00:00"},
        headers=h("dental", **{"Idempotency-Key": new_key()}),
    )
    dental = client.get("/appointments/availability", params={"date": d}, headers=h("dental")).json()
    shop = client.get("/appointments/availability", params={"date": d}, headers=h("shop")).json()
    assert "10:00" not in dental["open_slots"]
    assert "10:00" in shop["open_slots"]


def test_the_same_slot_can_be_booked_in_two_companies(client, world, h, n8n, day):
    d = day()
    for who in ("dental", "shop"):
        r = client.post(
            "/appointments",
            json={"customer_phone": "+919000000001", "date": d, "time": "11:00:00"},
            headers=h(who, **{"Idempotency-Key": new_key()}),
        )
        assert r.status_code == 200


def test_customers_appointment_list_is_per_company(client, world, h, n8n, day):
    client.post(
        "/appointments",
        json={"customer_phone": "+919000000001", "date": day(), "time": "10:00:00"},
        headers=h("dental", **{"Idempotency-Key": new_key()}),
    )
    assert len(client.get("/customers/appointments", params={"phone": "+919000000001"},
                          headers=h("dental")).json()) == 1
    assert client.get("/customers/appointments", params={"phone": "+919000000001"},
                      headers=h("shop")).json() == []


def test_invoice_of_another_company_is_never_reachable(client, world, h, n8n):
    r = client.post("/invoices/email-request", json={"customer_phone": "+919000000001"},
                    headers=h("shop"))
    assert r.status_code == 404  # the shop customer has no invoices; Asha's are not visible


def test_database_itself_blocks_a_cross_company_link(world):
    """Even a coding mistake cannot link a ticket to another company's customer."""
    with SessionLocal() as db:
        with pytest.raises(IntegrityError):
            db.execute(text(
                "INSERT INTO support_tickets (company_id, customer_id, subject, description,"
                " idempotency_key) VALUES (:c, :cust, 's', 'd', 'k-cross-1')"
            ), {"c": world["shop_id"], "cust": world["asha_id"]})
            db.commit()
