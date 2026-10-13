"""
Business Intake (agents/business_intake/ + business_intake_api.py).

Offline tests cover the module file (Product/GMO_MODULES.md), the
deterministic evidence, the cost rules (one model call per text request,
none for a repeated one), the website reader's safety checks, and the HTTP
contract. One live test runs the real agent and is skipped without
GEMINI_API_KEY.
"""
import asyncio
import base64
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

import business_intake_api  # noqa: E402
from agents.business_intake import cache, runner  # noqa: E402
from agents.business_intake.evidence import gather_business_evidence  # noqa: E402
from agents.business_intake.modules import load_modules, match_modules, parse_modules  # noqa: E402
from agents.business_intake.schema import BusinessAnalysis  # noqa: E402
from agents.business_intake.website import WebsiteError, check_url, extract_text  # noqa: E402

CARPENTER_ES = ("soy carpintero voy a abrir mi negocio necesito registrar a mis clientes necesito "
                "registrar mis productos necesito hacer un punto de venta")
LAWYER_ES = ("Hola, necesito crear una nueva empresa como abogada. Necesito registrar a mis "
             "clientes y seguir el proceso legal de cada uno.")


# ---------------------------------------------------------------------------
# Product/GMO_MODULES.md
# ---------------------------------------------------------------------------

def test_module_file_lists_what_pos_already_has():
    ids = {m.id for m in load_modules()}
    assert {"clients", "clientFollowUp", "clientMaps", "qr", "kyc", "suppliers", "sales", "expenses",
            "inventory", "manufacturing", "orders", "tickets", "rewards", "accounting", "dashboard",
            "employees", "users", "alerts", "emails", "notifications", "supportAgents",
            "inventoryRegistrationAgent", "restockAgent", "servicePaymentAgent", "loans", "legalRecovery"} <= ids


def test_every_module_is_complete():
    for m in load_modules():
        assert m.id and m.name and m.application and m.does and m.keywords, m.name
        assert m.kind in ("module", "agent"), m.name
        assert m.wiring, f"{m.name}: add its wiring (or 'not documented yet')"


def test_module_ids_are_unique():
    ids = [m.id for m in load_modules()]
    assert len(ids) == len(set(ids))


def test_parser_reads_application_kind_and_wiring():
    md = "## POS GMO\n\n### Things\n- id: things\n- kind: module\n- keywords: thing, cosa\n- does: Keeps things.\n- backend: /things\n"
    (m,) = parse_modules(md)
    assert (m.id, m.application, m.kind, m.keywords, m.wiring) == ("things", "POS GMO", "module", ["thing", "cosa"], {"backend": "/things"})


def test_spanish_request_matches_modules_without_any_model():
    ids = [m.id for m in match_modules(LAWYER_ES)]
    assert {"clients", "clientFollowUp", "legalRecovery"} <= set(ids)


def test_matching_ignores_accents_and_case():
    assert "loans" in [m.id for m in match_modules("Quiero dar PRÉSTAMOS")]


# ---------------------------------------------------------------------------
# Evidence (deterministic)
# ---------------------------------------------------------------------------

def test_evidence_sends_candidates_in_full_and_the_rest_as_an_index():
    ev = gather_business_evidence(LAWYER_ES)
    candidates = {m["id"] for m in ev["candidateModules"]}
    assert {"clients", "legalRecovery"} <= candidates
    assert all("wiring" in m and "evidenceLevel" in m for m in ev["candidateModules"])
    assert ev["otherModules"] and not any(line.startswith("Clients (CRUD)") for line in ev["otherModules"])


def test_opening_a_business_matches_company_onboarding():
    ids = {m["id"] for m in gather_business_evidence(CARPENTER_ES)["candidateModules"]}
    assert "companyOnboarding" in ids


def test_readiness_per_layer_is_never_assumed_available():
    candidates = {m["id"]: m for m in gather_business_evidence(CARPENTER_ES)["candidateModules"]}
    sales = candidates["sales"]["readiness"]
    assert sales["backend"] == "AVAILABLE" and sales["database"] == "AVAILABLE"
    assert sales["mobile"] in ("PARTIAL", "UNKNOWN") and sales["web"] in ("PARTIAL", "UNKNOWN")
    assert candidates["products"]["readiness"]["mobile"] == "UNKNOWN"


def test_configuration_comes_from_the_registry():
    onboarding = next(m for m in gather_business_evidence(CARPENTER_ES)["candidateModules"] if m["id"] == "companyOnboarding")
    assert "company_modules" in onboarding["readiness"]["configuration"]


def test_carpenter_request_has_few_candidates_not_the_whole_catalog():
    ids = {m["id"] for m in gather_business_evidence(CARPENTER_ES)["candidateModules"]}
    assert {"clients", "products", "sales"} <= ids
    assert not ids & {"inventory", "manufacturing", "suppliers", "expenses", "tickets", "dashboard"}


def test_wiring_is_verified_against_the_repository_knowledge():
    sales = next(m for m in gather_business_evidence(CARPENTER_ES)["candidateModules"] if m["id"] == "sales")
    assert sales["evidenceLevel"] == "implementation-verified"
    assert "/income" in sales["verified"]["routes"] and "sp_income" in sales["verified"]["storedProcedures"]
    assert "income" in sales["verified"]["tables"] and "incomeApi.ts" in sales["verified"]["frontend"]


def test_modules_without_verified_wiring_are_catalog_only():
    alerts = next(m for m in gather_business_evidence("necesito alertas")["candidateModules"] if m["id"] == "alerts")
    assert alerts["evidenceLevel"] == "catalog-only"


def test_repository_inventory_lets_the_analyst_find_hidden_implementations():
    inventory = gather_business_evidence(CARPENTER_ES)["repositoryInventory"]
    assert "/income" in inventory["backendRoutes"] and "/tickets" in inventory["backendRoutes"]
    assert "income" in inventory["tables"] and "sp_income" in inventory["storedProcedures"]


def test_follow_up_design_reveals_its_credit_domain():
    follow_up = next(m for m in gather_business_evidence(LAWYER_ES)["candidateModules"] if m["id"] == "clientFollowUp")
    text = " ".join(d["description"] for d in follow_up["draftDesigns"]) + " " + follow_up["does"]
    assert "credit" in text


def test_evidence_shows_legal_cases_are_tied_to_loans():
    columns = gather_business_evidence(LAWYER_ES)["tables"]["legalCases"]["columns"]
    assert "loanId int NOT NULL" in columns


def test_catalog_only_modules_are_reported_as_assumptions():
    ev = gather_business_evidence("necesito alertas")
    assert any("Alerts" in a["claim"] and "catalog only" in a["claim"] for a in ev["assumptions"])


def test_every_verified_fact_has_a_source():
    facts = gather_business_evidence(LAWYER_ES)["verifiedFacts"]
    assert facts and all(f["source"] for f in facts)


# ---------------------------------------------------------------------------
# Cost: one model call per text request, none when repeated
# ---------------------------------------------------------------------------

SAMPLE_ANALYSIS = {
    "understood": True,
    "restatedNeed": "A law firm needs to register clients and track their legal cases.",
    "summary": "A law firm needs to register clients and track their legal cases.",
    "businessType": "Law firm",
    "placement": {"application": "POS GMO", "asCompany": True, "explanation": "Joins as Company N."},
    "onboarding": "Register the firm as a company on POS GMO and activate Clients.",
    "workflow": [{"step": "Client", "basis": "verified"}, {"step": "Legal case", "basis": "verified"},
                 {"step": "Deadlines", "basis": "inferred"}],
    "requiredCapabilities": [{"capability": "Clients", "basis": "verified", "decision": "REUSE"},
                             {"capability": "Users and roles", "basis": "inferred", "decision": "CONFIGURE"},
                             {"capability": "Legal cases", "basis": "verified", "decision": "CREATE"}],
    "existingCapabilities": [{"capability": "Clients", "evidence": "/clients, clients table", "mobile": "PARTIAL",
                              "web": "PARTIAL", "backend": "AVAILABLE", "database": "AVAILABLE", "configurationRequired": ""}],
    "configuration": [{"capability": "Users and roles", "setting": "Create the lawyer and assistant roles", "why": "Two people use it."}],
    "extend": [],
    "create": [{"capability": "Legal cases", "suggestedModule": "legalCase", "whyNotReuse": "legalCases is SmartLoans recovery.",
                "scope": "Cases per client", "layers": ["database", "backend", "mobile", "web"]}],
    "investigate": [{"capability": "Documents", "knownEvidence": "None", "unknowns": "Storage", "inspect": "Blob storage",
                     "possibleOutcomes": "REUSE or CREATE"}],
    "notApplicable": [],
    "businessQuestions": ["What steps does a case go through?"],
    "mobileExperience": "Uses the GMO app for clients.",
    "webExperience": "Uses the GMO web platform.",
    "infrastructure": {"explanation": "Nothing new: the firm uses GMO."},
    "risks": [],
    "companyIsolation": "companyId from session.",
    "onboardingReadiness": "NEEDS_BUSINESS_CLARIFICATION",
    "onboardingPlan": ["Register the company", "Activate Clients"],
    "developmentRequests": [{"type": "NEW_CAPABILITY", "request": "Create a legalCase GMO capability ..."}],
    "factoryRecommendation": "Onboard now with Clients; legal cases need a new GMO capability.",
}


@pytest.fixture
def fake_model(monkeypatch):
    """Replaces the model call; records which agents were called."""
    calls = []

    async def fake_run(agent, parts, schema, usage):
        calls.append(agent.name)
        return schema.model_validate(SAMPLE_ANALYSIS)

    monkeypatch.setattr(runner, "_run", fake_run)
    cache.clear()
    yield calls
    cache.clear()


def test_text_request_makes_exactly_one_model_call(fake_model):
    result = asyncio.run(runner.analyze_business_need(text=LAWYER_ES, language="es"))
    assert result["status"] == "ok" and result["cached"] is False
    assert fake_model == ["intake_analyst_agent"]
    assert "Clients (CRUD)" in [c["name"] for c in result["evidence"]["candidates"]]


def test_repeated_request_is_answered_from_cache_without_a_model_call(fake_model):
    asyncio.run(runner.analyze_business_need(text=LAWYER_ES, language="es"))
    again = asyncio.run(runner.analyze_business_need(text="  hola, NECESITO crear una nueva empresa como abogada. necesito registrar a mis "
                                                         "clientes y seguir el proceso legal de cada uno ", language="es"))
    assert again["cached"] is True
    assert fake_model == ["intake_analyst_agent"]


def test_cache_is_per_language_and_website(fake_model):
    asyncio.run(runner.analyze_business_need(text=LAWYER_ES, language="es"))
    asyncio.run(runner.analyze_business_need(text=LAWYER_ES, language="en"))
    assert len(fake_model) == 2


def test_not_understood_becomes_a_question(fake_model, monkeypatch):
    async def fake_run(agent, parts, schema, usage):
        return schema.model_validate({**SAMPLE_ANALYSIS, "understood": False, "businessQuestions": ["¿Qué tipo de negocio tienes?"]})
    monkeypatch.setattr(runner, "_run", fake_run)
    result = asyncio.run(runner.analyze_business_need(text="asdf", language="es"))
    assert result == {"status": "needs_clarification", "need": {"transcript": "", "request": ""},
                      "question": "¿Qué tipo de negocio tienes?", "cached": False, "usage": {"tokens": 0}}


def test_development_requests_are_dropped_unless_gmo_must_be_extended(fake_model):
    result = asyncio.run(runner.analyze_business_need(text=LAWYER_ES, language="es"))
    assert result["analysis"]["onboardingReadiness"] == "NEEDS_BUSINESS_CLARIFICATION"
    assert result["analysis"]["developmentRequests"] == []


@pytest.mark.parametrize("readiness", ["READY", "READY_WITH_CONFIGURATION", "NEEDS_REPOSITORY_INVESTIGATION", "NEEDS_BOTH"])
def test_onboarding_alone_never_produces_development_requests(fake_model, monkeypatch, readiness):
    async def fake_run(agent, parts, schema, usage):
        return schema.model_validate({**SAMPLE_ANALYSIS, "onboardingReadiness": readiness})
    monkeypatch.setattr(runner, "_run", fake_run)
    assert asyncio.run(runner.analyze_business_need(text=LAWYER_ES, language="es"))["analysis"]["developmentRequests"] == []


def test_development_requests_are_kept_when_ready_after_extension(fake_model, monkeypatch):
    async def fake_run(agent, parts, schema, usage):
        return schema.model_validate({**SAMPLE_ANALYSIS, "onboardingReadiness": "READY_AFTER_EXTENSION"})
    monkeypatch.setattr(runner, "_run", fake_run)
    assert asyncio.run(runner.analyze_business_need(text=LAWYER_ES, language="es"))["analysis"]["developmentRequests"]


def test_no_new_infrastructure_by_default():
    infra = BusinessAnalysis.model_validate({**SAMPLE_ANALYSIS, "infrastructure": {}}).infrastructure
    assert not any([infra.newWebsite, infra.newMobileApp, infra.newBackend, infra.newDatabase, infra.newDeployment, infra.newHosting])


def test_decisions_outside_the_five_are_rejected():
    bad = {**SAMPLE_ANALYSIS, "requiredCapabilities": [{"capability": "X", "basis": "verified", "decision": "MAYBE"}]}
    with pytest.raises(Exception):
        BusinessAnalysis.model_validate(bad)


def test_business_analysis_schema_accepts_a_complete_analysis():
    assert BusinessAnalysis.model_validate(SAMPLE_ANALYSIS).placement.asCompany is True


# ---------------------------------------------------------------------------
# Website reader
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "http://localhost/", "http://127.0.0.1/", "http://10.0.0.5/", "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/", "file:///etc/passwd", "ftp://example.com/",
    "https://example.com:8443/",
])
def test_website_reader_refuses_non_public_addresses(url):
    with pytest.raises(WebsiteError):
        check_url(url)


def test_website_text_extraction_keeps_text_and_drops_scripts():
    page = extract_text("""<html><head><title>Despacho Legal Pérez</title>
        <meta name="description" content="Abogados en Hermosillo"><script>steal()</script><style>x{}</style></head>
        <body><h1>Derecho familiar y mercantil</h1><p>Consultas &amp; juicios</p></body></html>""")
    assert page["title"] == "Despacho Legal Pérez"
    assert page["description"] == "Abogados en Hermosillo"
    assert "Derecho familiar y mercantil Consultas & juicios" in page["text"]
    assert "steal" not in page["text"] and "x{}" not in page["text"]


def test_unreachable_website_is_reported_not_fatal(fake_model, monkeypatch):
    def broken(url):
        raise WebsiteError("The website could not be reached.")
    monkeypatch.setattr(runner, "fetch_website", broken)
    result = asyncio.run(runner.analyze_business_need(text=LAWYER_ES, url="https://nope.example", language="es"))
    assert result["status"] == "ok"
    assert result["website"] == {"url": "https://nope.example", "error": "The website could not be reached."}


# ---------------------------------------------------------------------------
# HTTP contract (agent stubbed)
# ---------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    calls = []

    async def fake_analyze(**kwargs):
        calls.append(kwargs)
        return {"status": "ok", "need": {}, "evidence": {}, "analysis": SAMPLE_ANALYSIS, "website": None, "cached": False}

    monkeypatch.setattr(business_intake_api, "analyze_business_need", fake_analyze)
    business_intake_api._calls.clear()
    cache.clear()
    test_client = TestClient(business_intake_api.app)
    test_client.calls = calls
    return test_client


def test_text_request_is_analyzed(client):
    r = client.post("/intake/analyze", json={"text": LAWYER_ES, "language": "es"})
    assert r.status_code == 200
    assert client.calls[0]["language"] == "es" and client.calls[0]["audio"] is None


def test_website_without_scheme_gets_https(client):
    client.post("/intake/analyze", json={"text": "hola", "url": "despacho-perez.mx"})
    assert client.calls[0]["url"] == "https://despacho-perez.mx"


def test_audio_request_is_decoded_and_mime_normalized(client):
    audio = b"RIFF0000WAVEfmt "
    r = client.post("/intake/analyze", json={"audioBase64": base64.b64encode(audio).decode(), "audioMimeType": "audio/wav;codecs=1"})
    assert r.status_code == 200
    assert client.calls[0]["audio"] == audio and client.calls[0]["audio_mime_type"] == "audio/wav"


def test_cached_answer_skips_the_agent_and_the_rate_limit(client, monkeypatch):
    monkeypatch.setattr(business_intake_api, "RATE_LIMIT_PER_HOUR", 0)
    monkeypatch.setattr(business_intake_api, "lookup_cached", lambda text, url, language: {"status": "ok", "cached": True})
    r = client.post("/intake/analyze", json={"text": LAWYER_ES})
    assert r.status_code == 200 and r.json()["cached"] is True
    assert client.calls == []


@pytest.mark.parametrize("body, status", [
    ({}, 400),
    ({"text": "   "}, 400),
    ({"text": "x" * 2001}, 422),
    ({"text": "hola", "url": "x" * 501}, 422),
    ({"text": "hola", "language": "fr"}, 422),
    ({"audioBase64": "aGVsbG8=", "audioMimeType": "video/mp4"}, 400),
    ({"audioBase64": "not base64!!", "audioMimeType": "audio/wav"}, 400),
])
def test_invalid_requests_are_rejected_before_calling_the_agent(client, body, status):
    assert client.post("/intake/analyze", json=body).status_code == status
    assert client.calls == []


def test_rate_limit_per_ip(client, monkeypatch):
    monkeypatch.setattr(business_intake_api, "RATE_LIMIT_PER_HOUR", 2)
    headers = {"x-forwarded-for": "203.0.113.7"}
    codes = [client.post("/intake/analyze", json={"text": f"hola {i}"}, headers=headers).status_code for i in range(3)]
    assert codes == [200, 200, 429]


@pytest.mark.parametrize("origin, allowed", [
    ("http://localhost:5173", True), ("http://127.0.0.1:3000", True), ("http://192.168.1.20:8080", True),
    ("http://10.0.0.7:8080", True), ("capacitor://localhost", True), ("https://evil.example.com", False),
    ("http://192.168.1.20.evil.com", False),
])
def test_cors_local_development_origins(client, origin, allowed):
    r = client.options("/intake/analyze", headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
    assert (r.headers.get("access-control-allow-origin") == origin) is allowed


def test_cors_allows_the_local_website(client):
    r = client.options("/intake/analyze", headers={"Origin": "http://localhost:8080", "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:8080"


# ---------------------------------------------------------------------------
# Live (real Gemini call)
# ---------------------------------------------------------------------------

requires_gemini = pytest.mark.skipif(not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
                                     reason="live test: requires GEMINI_API_KEY")


@requires_gemini
def test_live_lawyer_joins_gmo_and_gets_legal_cases_as_a_gmo_capability():
    cache.clear()
    a = asyncio.run(runner.analyze_business_need(text=LAWYER_ES, language="es"))["analysis"]
    assert a["placement"]["application"] == "POS GMO" and a["placement"]["asCompany"]
    reused = " ".join(f"{r['capability']} {r['evidence']}" for r in a["existingCapabilities"]).lower()
    assert "legalcases" not in reused.replace(" ", "") and "recuperación legal" not in reused
    assert any(c["decision"] in ("CREATE", "INVESTIGATE") for c in a["requiredCapabilities"]
               if "legal" in c["capability"].lower() or "caso" in c["capability"].lower())
    assert not any(a["infrastructure"][k] for k in ("newWebsite", "newMobileApp", "newBackend", "newDatabase", "newDeployment", "newHosting"))
    assert 1 <= len(a["businessQuestions"]) <= 3


@requires_gemini
def test_live_carpenter_is_onboarded_not_given_an_app():
    cache.clear()
    a = asyncio.run(runner.analyze_business_need(text=CARPENTER_ES, language="es"))["analysis"]
    assert a["onboardingPlan"], "a company joining GMO needs an onboarding plan"
    assert len(a["existingCapabilities"]) <= 6, [r["capability"] for r in a["existingCapabilities"]]
    assert not any(a["infrastructure"][k] for k in ("newWebsite", "newMobileApp", "newBackend", "newDatabase", "newDeployment", "newHosting"))
    assert a["onboardingReadiness"] != "READY"
    assert a["developmentRequests"] == [] or a["onboardingReadiness"] == "READY_AFTER_EXTENSION"
