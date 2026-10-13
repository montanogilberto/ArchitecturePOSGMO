"""
Website commercial core (site_commercial/ + /intake/analyze token allowance):
visit counter, token allowance, lead capture, lead follow-up admin.
No model calls: the analysis is stubbed.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

import business_intake_api  # noqa: E402
from agents.business_intake import cache  # noqa: E402
from site_commercial import routes, store  # noqa: E402

VISITOR = "visitor_abc12345"
ADMIN = {"X-Admin-Key": "test-admin-key"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    store.reset_for_tests(tmp_path / "site.db")
    cache.clear()
    business_intake_api._calls.clear()
    monkeypatch.setenv("SITE_ADMIN_KEY", "test-admin-key")
    monkeypatch.setattr(routes, "FREE_TOKENS", 1000)
    monkeypatch.setattr(routes, "REGISTERED_TOKENS", 10000)

    async def fake_analyze(**kwargs):
        return {"status": "ok", "need": {}, "evidence": {}, "analysis": {}, "website": None,
                "cached": False, "usage": {"tokens": 600}}

    monkeypatch.setattr(business_intake_api, "analyze_business_need", fake_analyze)
    return TestClient(business_intake_api.app)


def lead(**overrides):
    return {"visitorId": VISITOR, "fullName": "Ana Pérez", "phone": "662 123 4567", "email": "",
            "leadSource": "ask_factory", "language": "es", "privacyConsentAccepted": True,
            "analysis": {"businessType": "Carpintería", "readiness": "NEEDS_BOTH", "summary": "Carpintero…"}, **overrides}


# ---------------------------------------------------------------- visit counter

def test_visit_is_counted_once_per_visitor_session(client):
    first = client.post("/site/visit", json={"visitorId": VISITOR, "path": "/es", "language": "es"}).json()
    again = client.post("/site/visit", json={"visitorId": VISITOR, "path": "/es", "language": "es"}).json()
    other = client.post("/site/visit", json={"visitorId": "visitor_other999", "path": "/"}).json()
    assert first["counted"] and not again["counted"] and other["counted"]
    assert client.get("/site/stats").json() == {"total": 2, "today": 2, "uniqueVisitors": 2}


def test_visit_rejects_bad_visitor_ids(client):
    assert client.post("/site/visit", json={"visitorId": "x"}).status_code == 422


def test_ip_is_never_stored_raw(client):
    client.post("/site/visit", json={"visitorId": VISITOR}, headers={"x-forwarded-for": "203.0.113.9"})
    row = store.connection().execute("SELECT ipHash FROM visits").fetchone()
    assert row[0] and "203.0.113.9" not in row[0]


# ---------------------------------------------------------------- token allowance

def test_analysis_tokens_are_counted_and_limited(client):
    body = {"text": "soy carpintero", "visitorId": VISITOR}
    first = client.post("/intake/analyze", json=body).json()
    assert first["allowance"] == {"used": 600, "allowance": 1000, "remaining": 400, "registered": False}
    client.post("/intake/analyze", json={**body, "text": "también vendo muebles"})
    blocked = client.post("/intake/analyze", json={**body, "text": "otra pregunta"})
    assert blocked.status_code == 402 and blocked.json()["detail"]["code"] == "token_limit"


def test_registering_raises_the_allowance(client):
    client.post("/intake/analyze", json={"text": "soy carpintero", "visitorId": VISITOR})
    client.post("/intake/analyze", json={"text": "vendo muebles", "visitorId": VISITOR})
    assert client.post("/intake/analyze", json={"text": "más", "visitorId": VISITOR}).status_code == 402
    r = client.post("/site/leads", json=lead()).json()
    assert r["usage"]["registered"] and r["usage"]["allowance"] == 10000
    assert client.post("/intake/analyze", json={"text": "más", "visitorId": VISITOR}).status_code == 200


def test_cached_answers_cost_no_tokens(client, monkeypatch):
    monkeypatch.setattr(business_intake_api, "lookup_cached", lambda text, url, language: {"status": "ok", "cached": True, "usage": {"tokens": 0}})
    r = client.post("/intake/analyze", json={"text": "soy carpintero", "visitorId": VISITOR}).json()
    assert r["cached"] and r["allowance"]["used"] == 0


# ---------------------------------------------------------------- leads

def test_mini_registration_stores_the_lead_with_its_analysis(client):
    assert client.post("/site/leads", json=lead()).json()["ok"]
    (saved,) = client.get("/site/admin/leads", headers=ADMIN).json()["leads"]
    assert saved["fullName"] == "Ana Pérez" and saved["status"] == "new" and saved["leadSource"] == "ask_factory"
    assert saved["analysis"]["businessType"] == "Carpintería" and saved["privacyConsentAccepted"] is True
    assert "ipHash" not in saved


@pytest.mark.parametrize("overrides, status", [
    ({"privacyConsentAccepted": False}, 400),
    ({"phone": "", "email": ""}, 400),
    ({"email": "not-an-email"}, 422),
    ({"phone": "12"}, 422),
    ({"fullName": "A"}, 422),
    ({"leadSource": "contact_form", "message": ""}, 400),
    ({"leadSource": "spam"}, 422),
])
def test_invalid_leads_are_rejected(client, overrides, status):
    assert client.post("/site/leads", json=lead(**overrides)).status_code == status


def test_contact_form_is_a_lead_with_a_message(client):
    r = client.post("/site/leads", json=lead(leadSource="contact_form", message="Quiero una demo", visitorId=None, analysis=None))
    assert r.status_code == 200
    (saved,) = client.get("/site/admin/leads", headers=ADMIN).json()["leads"]
    assert saved["leadSource"] == "contact_form" and saved["message"] == "Quiero una demo"


def test_honeypot_submissions_are_silently_dropped(client):
    assert client.post("/site/leads", json=lead(website="http://spam")).json() == {"ok": True}
    assert client.get("/site/admin/leads", headers=ADMIN).json()["leads"] == []


def test_lead_submissions_are_rate_limited_per_ip(client, monkeypatch):
    monkeypatch.setattr(routes, "MAX_LEADS_PER_IP_PER_HOUR", 2)
    codes = [client.post("/site/leads", json=lead(visitorId=None)).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


# ---------------------------------------------------------------- follow-up admin

def test_admin_is_disabled_without_a_key(client, monkeypatch):
    monkeypatch.delenv("SITE_ADMIN_KEY")
    assert client.get("/site/admin/leads", headers=ADMIN).status_code == 503


def test_admin_rejects_a_wrong_key(client):
    assert client.get("/site/admin/leads", headers={"X-Admin-Key": "nope"}).status_code == 401
    assert client.get("/site/admin/leads").status_code == 401


def test_follow_up_status_and_notes(client):
    lead_id = client.post("/site/leads", json=lead()).json()["leadId"]
    assert client.patch(f"/site/admin/leads/{lead_id}", json={"status": "contacted", "notes": "Llamar el lunes"}, headers=ADMIN).status_code == 200
    (saved,) = client.get("/site/admin/leads?status=contacted", headers=ADMIN).json()["leads"]
    assert saved["notes"] == "Llamar el lunes"
    assert client.patch("/site/admin/leads/999", json={"status": "won"}, headers=ADMIN).status_code == 404
    assert client.patch(f"/site/admin/leads/{lead_id}", json={"status": "maybe"}, headers=ADMIN).status_code == 422


def test_admin_overview(client):
    client.post("/site/visit", json={"visitorId": VISITOR})
    client.post("/intake/analyze", json={"text": "soy carpintero", "visitorId": VISITOR})
    client.post("/site/leads", json=lead())
    o = client.get("/site/admin/overview", headers=ADMIN).json()
    assert o["visits"]["total"] == 1 and o["tokens"]["tokens"] == 600
    assert o["leads"]["byStatus"]["new"] == 1 and o["leads"]["bySource"] == {"ask_factory": 1}
    assert o["visitsByDay"][0]["visits"] == 1
