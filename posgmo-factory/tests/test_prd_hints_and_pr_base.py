"""F1: PRD database hints reach the database stage. F2: the Factory only
branches from and opens PRs into development."""
from __future__ import annotations

import glob
import json

import pytest
from pydantic import ValidationError

from agents.database.sql_templates import generate_crud_sql, unsupported_reason
from agents.pr import rules as pr
from agents.spec_reconciler.rules import forward_database_hints
from prd_schema import PRDInput

HINTS = ["CHECK quantity > 0", "Append-only: no update or delete action"]


def _prd(**extra):
    return {"module": "supplier", "description": "A supplier of goods.",
            "fields": [{"name": "supplierName", "type": "string"}], **extra}


def test_hints_survive_prd_input():
    prd = PRDInput.model_validate(_prd(database={"hints": HINTS}))
    assert prd.model_dump()["database"]["hints"] == HINTS


@pytest.mark.parametrize("section,payload", [
    ("database", {"hint": ["typo"]}),
    ("frontend", {"route": "/x"}),
    ("backend", {"endpoints": [{"path": "/x", "verb": "POST"}]}),
])
def test_unknown_nested_key_fails_instead_of_vanishing(section, payload):
    with pytest.raises(ValidationError):
        PRDInput.model_validate(_prd(**{section: payload}))


def test_every_real_prd_still_validates():
    files = glob.glob("tests/prd_*.json") + glob.glob("examples/prd_*.json")
    assert files
    for f in files:
        PRDInput.model_validate(json.load(open(f, encoding="utf-8")))


def _state(spec=None, hints=HINTS):
    return {"specification": json.dumps(spec or {"module": "supplier", "db": {"columns": []}}),
            "prd_raw": json.dumps(_prd(database={"hints": hints}))}


def test_reconciler_forwards_hints_without_the_architect():
    spec, count = forward_database_hints(_state())
    assert spec["prd_hints"]["database_hints"] == HINTS and count == 2


def test_forwarding_is_idempotent_and_skips_prds_without_hints():
    spec, _ = forward_database_hints(_state())
    assert forward_database_hints(_state(spec)) == (None, 2)
    assert forward_database_hints(_state(hints=[])) == (None, 0)


def test_hints_send_the_module_past_the_crud_template():
    spec = {"module": "supplier", "db": {"table_name": "suppliers", "columns": [{"name": "a", "sql_type": "int"}]},
            "prd_hints": {"database_hints": HINTS}}
    gate = {"backend_pattern": "CRUD_ONLY", "tier": "TIER_1_CATALOG"}
    assert "2 database hint(s)" in unsupported_reason(spec, gate)
    assert generate_crud_sql(json.dumps(spec), json.dumps(gate), None) is None


class _FakeResponse:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"object": {"sha": "abc"}, "html_url": "u"}


class _FakeClient:
    calls: list = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw.get("json")))
        return _FakeResponse()

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw.get("json")))
        return _FakeResponse()


@pytest.fixture
def github(monkeypatch):
    _FakeClient.calls = []
    monkeypatch.setattr(pr.httpx, "Client", _FakeClient)
    monkeypatch.setenv("GITHUB_TOKEN", "test")
    return _FakeClient


def test_branch_forks_from_development_by_default(github):
    pr.github_create_branch("o/r", "feat/x-module")
    assert github.calls[0][1].endswith("/git/ref/heads/development")


def test_pr_targets_development_by_default(github):
    pr.github_create_pr("o/r", "feat/x-module", "t", "b")
    assert github.calls[0][2]["base"] == "development"


@pytest.mark.parametrize("base", ["main", "qa"])
def test_promotion_branches_are_refused_without_touching_github(github, base):
    assert pr.github_create_branch("o/r", "feat/x", base)["status"] == "refused"
    assert pr.github_create_pr("o/r", "feat/x", "t", "b", base)["status"] == "refused"
    assert github.calls == []
