"""
Step 1 (Construction Reliability): deterministic CRUD SQL generation.

agents/database/sql_templates.py renders database_artifacts for CRUD-shaped
modules with zero LLM calls; database_agent only falls back to the (now
tool-less, retried) LLM for shapes the template can't honestly cover. The
central property under test: template output passes the SAME deterministic
reviewer and fixer that gate every real run, across tenant models and tiers
-- including the real factoryRun spec that scored database: 60 on the LLM
path (snake_case PK, companyId filter on a TENANT_INDEPENDENT module).
"""
import json
from pathlib import Path

import pytest

from agents.database.agent import database_agent, database_llm_agent, llm_output_is_usable
from agents.database.sql_templates import generate_crud_sql, unsupported_reason
from agents.fixer.rules import fix_database
from agents.reviewer.rules import _check_database

ROOT = Path(__file__).parent.parent


def _spec(module="supplier", columns=None, indexes=None, table=None):
    return {
        "module": module,
        "description": "test",
        "db": {
            "table_name": table or f"{module}s",
            "sp_prefix": f"sp_{module}s",
            "columns": columns or [
                {"name": f"{module}Id", "sql_type": "int IDENTITY(1,1) NOT NULL", "nullable": False},
                {"name": "companyId", "sql_type": "int NOT NULL", "nullable": False,
                 "fk_table": "companies", "fk_column": "companyId"},
                {"name": "supplierName", "sql_type": "nvarchar(150)", "nullable": False},
                {"name": "phone", "sql_type": "nvarchar(20)", "nullable": True},
                {"name": "rating", "sql_type": "int", "nullable": True},
                {"name": "notes", "sql_type": "nvarchar(MAX)", "nullable": True},
                {"name": "created_At", "sql_type": "datetime", "nullable": False},
                {"name": "updated_at", "sql_type": "datetime", "nullable": True},
            ],
            "indexes": indexes if indexes is not None else ["companyId", "supplierName"],
        },
    }


def _gate(tier="TIER_1_CATALOG", tenant="TENANT_SCOPED", pattern="CRUD_ONLY", **extra):
    scoped = tenant != "TENANT_INDEPENDENT"
    db_rules = (
        ["companyId INT NOT NULL must be present in CREATE TABLE.",
         "sp_all MUST accept @pjsonfile and filter WHERE companyId = @companyId."]
        if scoped else
        ["companyId is NOT applicable to this module (explicit tenant_model decision) -- "
         "do not add a NOT NULL companyId column or a foreign key to companies."]
    ) + [
        "Every nullable column in SELECT must be wrapped with ISNULL(col, default).",
        "SP mutations must be wrapped in BEGIN TRY / BEGIN TRANSACTION / COMMIT / END TRY BEGIN CATCH ROLLBACK END CATCH.",
    ]
    gate = {
        "status": "APPROVED", "tier": tier, "backend_pattern": pattern, "tenant_model": tenant,
        "mandatory_constraints": {"database": db_rules, "backend": [], "frontend": []},
        "soft_delete_parents": [], "index_recommendations": [],
    }
    gate.update(extra)
    return gate


def _review_and_fix(out, spec, gate):
    issues = _check_database(out, spec, gate)
    fixed, fixes = fix_database(dict(out), {**gate, "_module": spec["module"]})
    return [i.message for i in issues], fixes


# ---------------------------------------------------------------------------
# Reviewer + fixer agreement
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tenant", ["TENANT_SCOPED", "TENANT_INDEPENDENT"])
def test_template_passes_reviewer_with_no_fixer_changes(tenant):
    spec, gate = _spec(), _gate(tenant=tenant)
    out = generate_crud_sql(spec, gate)
    issues, fixes = _review_and_fix(out, spec, gate)
    assert issues == []
    assert fixes == []  # nothing for the deterministic fixer to repair


def test_tenant_independent_has_no_companyId_anywhere():
    spec, gate = _spec(), _gate(tenant="TENANT_INDEPENDENT")
    out = generate_crud_sql(spec, gate)
    for key in ("create_table", "sp_upsert", "sp_all", "sp_one"):
        assert "companyId" not in out[key], key
    assert "IX_suppliers_companyId" not in out["create_table"]  # spec index dropped, not dangling


def test_tenant_scoped_filters_and_scopes_mutations():
    out = generate_crud_sql(_spec(), _gate())
    assert "WHERE [companyId] = @companyId" in out["sp_all"]
    assert "AND t.[companyId] = p.[companyId]" in out["sp_upsert"]  # UPDATE/DELETE can't cross tenants
    assert "FOREIGN KEY ([companyId]) REFERENCES [dbo].[companies]([companyId])" in out["create_table"]


def test_real_factoryRun_spec_that_scored_60_on_llm_path():
    # Fixture captured from the real run's state (last_state.json is
    # gitignored and overwritten by every orchestrator run).
    fx = json.loads((ROOT / "tests/fixtures/factoryRun_spec_gate.json").read_text(encoding="utf-8"))
    spec, gate = fx["specification"], fx["gate_result"]
    out = generate_crud_sql(spec, gate)
    issues, fixes = _review_and_fix(out, spec, gate)
    assert issues == [] and fixes == []
    assert "[factoryRunId] INT IDENTITY(1,1)" in out["create_table"]  # LLM wrote factory_run_id
    assert "companyId" not in out["sp_all"]


def test_tier2_money_columns_forced_to_decimal_10_2():
    cols = _spec()["db"]["columns"][:-2] + [
        {"name": "amountMXN", "sql_type": "decimal(12,4)", "nullable": False},
        {"name": "scoreRatio", "sql_type": "decimal(5,4)", "nullable": True},
        {"name": "created_At", "sql_type": "datetime", "nullable": False},
        {"name": "updated_at", "sql_type": "datetime", "nullable": True},
    ]
    spec = _spec(columns=cols)
    gate = _gate(tier="TIER_2_FINANCIAL", mandatory_constraints={"database": [
        "All monetary DECIMAL columns (amounts, totals, prices) must be DECIMAL(10,2).",
        "Non-monetary decimal columns (scores, ratios, coordinates) keep their original precision (e.g. DECIMAL(5,4)).",
    ]})
    out = generate_crud_sql(spec, gate)
    assert "[amountMXN] DECIMAL(10,2) NOT NULL" in out["create_table"]
    assert "[scoreRatio] DECIMAL(5,4) NULL" in out["create_table"]
    issues, _ = _review_and_fix(out, spec, gate)
    assert issues == []


def test_tier4_uses_datetime2():
    spec = _spec()
    gate = _gate(tier="TIER_4_IOT")
    out = generate_crud_sql(spec, gate)
    assert "[created_At] DATETIME2(3) NOT NULL" in out["create_table"]
    issues, _ = _review_and_fix(out, spec, gate)
    assert issues == []


def test_soft_delete_parent_filter_satisfies_reviewer():
    cols = _spec()["db"]["columns"] + [
        {"name": "projectId", "sql_type": "int", "nullable": True,
         "fk_table": "projects", "fk_column": "projectId"},
    ]
    spec = _spec(columns=cols)
    gate = _gate(soft_delete_parents=[{"fk_table": "projects", "fk_column": "projectId"}])
    out = generate_crud_sql(spec, gate)
    assert "FROM [dbo].[projects] WHERE [active] = '1'" in out["sp_all"]
    assert "[IX_suppliers_projectId]" in out["create_table"]  # FK columns always indexed
    issues, _ = _review_and_fix(out, spec, gate)
    assert issues == []


def test_every_block_is_go_terminated_for_executor_batching():
    out = generate_crud_sql(_spec(), _gate())
    for key in ("create_table", "sp_upsert", "sp_all", "sp_one"):
        assert out[key].rstrip().endswith("GO"), key


def test_nvarchar_max_payload_not_truncated_by_json_value():
    # JSON_VALUE returns at most 4000 chars; MAX columns go through OPENJSON WITH.
    out = generate_crud_sql(_spec(), _gate())
    assert "[notes] NVARCHAR(MAX) '$.notes'" in out["sp_upsert"]


# ---------------------------------------------------------------------------
# Fallback boundaries — never silently drop a mandatory rule
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("gate_kwargs", [
    {"pattern": "ACTION_ROUTER"},
    {"pattern": "BUSINESS_LOGIC"},
    {"tier": "TIER_3_TRANSACTIONAL"},
])
def test_non_crud_shapes_fall_back_to_llm(gate_kwargs):
    assert generate_crud_sql(_spec(), _gate(**gate_kwargs)) is None


def test_unrecognized_adr_constraint_falls_back_to_llm():
    gate = _gate(tenant="TENANT_INDEPENDENT")
    gate["mandatory_constraints"]["database"].append(
        "Enforce rejection via a persistent UNIQUE constraint, not only application-logic GROUP BY/HAVING."
    )
    assert generate_crud_sql(_spec(), gate) is None
    assert "UNIQUE" in unsupported_reason(_spec(), gate)


def test_blocked_gate_emits_blocked_marker():
    out = generate_crud_sql(_spec(), {"status": "BLOCKED", "reason": "FK target missing"})
    assert out["status"] == "blocked" and out["reason"] == "FK target missing"


# ---------------------------------------------------------------------------
# LLM fallback wiring
# ---------------------------------------------------------------------------

def test_llm_fallback_has_no_tools():
    # The MCP tool calls were the remaining MALFORMED_FUNCTION_CALL surface.
    assert database_llm_agent.tools == []
    assert database_agent.sub_agents == [database_llm_agent]


@pytest.mark.parametrize("raw,usable", [
    ("", False),
    ("not json", False),
    ('{"create_table": ""}', False),
    ('{"create_table": "CREATE TABLE x"}', True),
    ('```json\n{"sp_action_router": "CREATE PROCEDURE x"}\n```', True),
    ('{"status": "blocked", "reason": "x"}', True),
    ('{"sql": null, "reason": "blob upload only"}', True),
])
def test_llm_output_usability(raw, usable):
    assert llm_output_is_usable(raw) is usable


def test_update_keeps_not_null_columns_when_omitted():
    # Real-server probe finding: UPDATE without `active` wrote NULL into a
    # NOT NULL column and failed. Nullable columns stay full-replace.
    out = generate_crud_sql(_spec(), _gate())
    assert "t.[supplierName] = ISNULL(p.[supplierName], t.[supplierName])" in out["sp_upsert"]
    assert "t.[phone] = p.[phone]" in out["sp_upsert"]


@pytest.mark.parametrize("sql_type,literal", [("bit", "1"), ("nvarchar(1)", "'1'"), ("char(1)", "'1'")])
def test_active_flag_defaults_to_live_in_both_representations(sql_type, literal):
    # supplier real run: the architect modeled active as NVARCHAR(1) NOT NULL.
    cols = _spec()["db"]["columns"] + [{"name": "active", "sql_type": sql_type, "nullable": False}]
    out = generate_crud_sql(_spec(columns=cols), _gate())
    assert f"DEFAULT {literal}" in out["create_table"]
    assert f"ISNULL(p.[active], {literal})" in out["sp_upsert"]


def test_spec_identity_column_is_pk_when_it_differs_from_module_id():
    # Real run: live posRewardCatalogItems has PK catalogItemId; forcing
    # posRewardCatalogItemId made every SP fail with "Invalid column name".
    cols = [{"name": "catalogItemId", "sql_type": "int IDENTITY(1,1) NOT NULL", "nullable": False}] + \
        _spec()["db"]["columns"][1:]
    spec = _spec(module="posRewardCatalogItem", columns=cols, indexes=[])
    gate = _gate()
    out = generate_crud_sql(spec, gate)
    assert "[catalogItemId] INT IDENTITY(1,1) NOT NULL" in out["create_table"]
    assert "posRewardCatalogItemId" not in json.dumps(out)
    assert "'$.catalogItemId'" in out["sp_one"]
    issues, _ = _review_and_fix(out, spec, gate)
    assert issues == []


def test_backend_stage_retries_backend_agent_without_changing_it():
    from agents.agent import generation_stage
    from agents.backend import backend_agent
    from agents.retry import has_backend_files
    stage = next(a for a in generation_stage.sub_agents if a.name == "backend_stage")
    assert stage.sub_agents == [backend_agent] and stage.max_attempts == 3
    assert backend_agent.output_key == "backend_artifacts"
    assert not has_backend_files("")  # the posRewardCatalogItem MALFORMED_FUNCTION_CALL run
    assert has_backend_files({"module_file": {"path": "m.py", "content": "x"},
                              "route_file": {"path": "r.py", "content": "y"}})


@pytest.mark.parametrize("raw,usable", [
    ("", False),
    ('{"module": "x", "db": {"columns": []}}', False),
    ('```json\n{"module": "x", "db": {"columns": [{"name": "xId"}]}}\n```', True),
])
def test_architect_stage_usability(raw, usable):
    from agents.retry import has_specification
    assert has_specification(raw) is usable


# ---------------------------------------------------------------------------
# Existing live table is authoritative over the spec
# ---------------------------------------------------------------------------

_LIVE_CATALOG = [  # live posRewardCatalogItems (hand-built 2026-09-17), abridged
    {"name": "catalogItemId", "type": "int", "nullable": False, "is_identity": True, "is_pk": True},
    {"name": "companyId", "type": "int", "nullable": False},
    {"name": "name", "type": "nvarchar", "max_length": 120, "nullable": False},
    {"name": "requiredPoints", "type": "decimal", "precision": 10, "scale": 2, "nullable": False},
    {"name": "isActive", "type": "bit", "nullable": False},
    {"name": "created_At", "type": "datetime2", "nullable": False},
    {"name": "updated_at", "type": "datetime2", "nullable": True},
]


def test_live_table_pk_overrides_invented_spec_pk():
    # Real run 2: architect invented posRewardCatalogItemId for an existing table.
    cols = [
        {"name": "posRewardCatalogItemId", "sql_type": "int IDENTITY(1,1) NOT NULL", "nullable": False},
        {"name": "companyId", "sql_type": "int", "nullable": False},
        {"name": "name", "sql_type": "nvarchar(120)", "nullable": False},
        {"name": "requiredPoints", "sql_type": "decimal(10,2)", "nullable": False},
        {"name": "isActive", "sql_type": "bit", "nullable": False},
    ]
    spec = _spec(module="posRewardCatalogItem", columns=cols, indexes=[], table="posRewardCatalogItems")
    gate = _gate()
    out = generate_crud_sql(spec, gate, _LIVE_CATALOG)
    assert "posRewardCatalogItemId" not in json.dumps(out)
    assert "'$.catalogItemId'" in out["sp_one"] and out["existing_table"] is True
    assert "schema_drift" not in out
    issues, _ = _review_and_fix(out, generate_spec_as_reconciled(spec, gate), gate)
    assert issues == []


def generate_spec_as_reconciled(spec, gate):
    from agents.database.sql_templates import reconcile_with_live
    return reconcile_with_live(spec, gate, _LIVE_CATALOG)[0]


def test_spec_columns_missing_from_live_table_are_reported_not_referenced():
    cols = _spec()["db"]["columns"][:3] + [{"name": "newField", "sql_type": "nvarchar(50)", "nullable": True}]
    spec = _spec(module="posRewardCatalogItem", columns=cols, indexes=[], table="posRewardCatalogItems")
    out = generate_crud_sql(spec, _gate(), _LIVE_CATALOG)
    assert "newField" not in out["sp_upsert"]  # would fail with Invalid column name
    assert "newField" in out["schema_drift"]
    issues = [i.message for i in _check_database(out, spec, _gate())]
    assert any("needs a migration decision" in m for m in issues)


def test_live_table_disagreeing_with_tenant_model_falls_back():
    from agents.database.sql_templates import fallback_reason
    gate = _gate(tenant="TENANT_INDEPENDENT")
    assert generate_crud_sql(_spec(), gate, _LIVE_CATALOG) is None
    assert "disagrees with live table" in fallback_reason(_spec(), gate, _LIVE_CATALOG)


def test_spec_reconciler_corrects_pk_for_every_layer():
    from agents.spec_reconciler.rules import reconcile_specification
    cols = [
        {"name": "posRewardCatalogItemId", "sql_type": "int IDENTITY(1,1) NOT NULL", "nullable": False},
        {"name": "name", "sql_type": "nvarchar(120)", "nullable": False},
        {"name": "legacyCode", "sql_type": "nvarchar(20)", "nullable": True},
    ]
    spec = _spec(module="posRewardCatalogItem", columns=cols, indexes=["name", "legacyCode"],
                 table="posRewardCatalogItems")
    state = {"specification": json.dumps(spec), "gate_result": json.dumps(_gate())}
    new_spec, record = reconcile_specification(state, lookup=lambda t: _LIVE_CATALOG)
    assert record["pk_corrected"] and record["live_pk"] == "catalogItemId"
    assert new_spec["db"]["columns"][0]["name"] == "catalogItemId"
    assert new_spec["db"]["schema_drift"] == ["legacyCode"]
    assert new_spec["db"]["indexes"] == ["name"]
    out = generate_crud_sql(new_spec, _gate())
    assert out["schema_drift"] == ["legacyCode"]  # carried through to the reviewer


def test_spec_reconciler_leaves_new_tables_alone():
    from agents.spec_reconciler.rules import reconcile_specification
    state = {"specification": json.dumps(_spec()), "gate_result": json.dumps(_gate())}
    assert reconcile_specification(state, lookup=lambda t: None) == (None, {"status": "new_table", "table": "suppliers"})


def test_architect_has_no_tools_and_gets_knowledge_inline():
    from agents.architect import architect_agent
    from agents.architect.knowledge import build_architect_knowledge
    assert architect_agent.tools == []  # temperature-0 MALFORMED_FUNCTION_CALL surface removed
    k = build_architect_knowledge("supplier", "supplier catalog")
    assert set(k) >= {"1. generation_rules", "4. sp_patterns", "5. decisions_for_module(supplier)"}
    assert any("NOT AUTHORITATIVE" in key for key in k)  # evidence stays labeled as evidence


def test_review_fixer_repairs_customevent_any_after_frontend_generation():
    # fixer_agent runs before frontend_agent, so review_fixer is the only
    # deterministic path for this finding (supplier run: frontend 80).
    from agents.review_fixer.rules import apply_review_fixes
    page = ("import { IonCheckbox } from '@ionic/react';\n"
            "const onToggle = (e: CustomEvent<any>) => setActive(e.detail.checked);\n")
    review = {"issues": [{"artifact": "frontend", "severity": "error",
                          "message": "CustomEvent<any> forbidden — use specific generic (CheckboxChangeEventDetail, etc.)"}]}

    class _Ctx:
        state = {"review_result": json.dumps(review),
                 "frontend_artifacts": json.dumps({"page_file": {"path": "p.tsx", "content": page}})}

    result = apply_review_fixes(_Ctx())
    assert result["skipped"] == [] and len(result["fixed"]) == 1
    assert "CustomEvent<any>" not in json.loads(_Ctx.state["frontend_artifacts"])["page_file"]["content"]


def test_construction_agents_have_no_tool_call_surface():
    from agents.architect import architect_agent
    from agents.backend import backend_agent
    from agents.frontend import frontend_agent
    from agents.preloaded_knowledge import load_sources
    for agent in (architect_agent, backend_agent, frontend_agent, database_llm_agent):
        assert agent.tools == [], agent.name
    k = load_sources(["get_generation_rules", "get_backend_routes"])
    assert "unavailable" not in json.dumps(k)[:200] and list(k) == ["1. get_generation_rules", "2. get_backend_routes"]


def test_single_sql_execution_error_fails_review():
    # leadCapture real run: one failed batch used to score exactly 90 = pass.
    out = generate_crud_sql(_spec(), _gate())
    out["execution"] = {"success": False, "details": [
        {"status": "error", "message": "Incorrect syntax near '('. (102)"}]}
    from agents.reviewer.rules import _score
    issues = _check_database(out, _spec(), _gate())
    assert _score(issues, "database") < 90


def test_repair_signal_is_rollback_only_and_reports_server_errors():
    from unittest.mock import patch
    from agents.database.agent import sql_errors_on_server
    out = generate_crud_sql(_spec(), _gate())
    fake = {"success": False, "details": [
        {"status": "ok", "batch_preview": "CREATE TABLE"},
        {"status": "error", "batch_preview": "CREATE UNIQUE INDEX", "message": "Incorrect syntax near '('."}]}
    with patch("agents.database.rules.execute_sql_on_server", return_value=fake) as ex:
        errors = sql_errors_on_server(json.dumps(out))
    assert ex.call_args.kwargs == {"validate_only": True}  # never persists, whatever FACTORY_SQL_MODE is
    assert len(errors) == 1 and "Incorrect syntax" in errors[0]
    assert sql_errors_on_server('{"sp_action_router": "x"}') == []  # shapes the executor can't run


def test_bare_ionrefresher_handler_typed_and_imported():
    # factoryRunUsage batch-4 run: `handleRefresh = async (event: CustomEvent)`
    # failed review every iteration; the bare fixer only knew IonDatetime.
    from agents.fixer.rules import fix_frontend
    page = ("import { IonContent, IonRefresher } from '@ionic/react';\n"
            "const handleRefresh = async (event: CustomEvent) => { event.detail.complete(); };\n"
            "<IonRefresher slot=\"fixed\" onIonRefresh={handleRefresh} />\n"
            "<IonRefresher onIonRefresh={(e: CustomEvent) => e.detail.complete()} />\n")
    fe, fixes = fix_frontend({"page_file": {"content": page}, "api_file": {"content": ""}}, {})
    out = fe["page_file"]["content"]
    assert out.count("CustomEvent<RefresherEventDetail>") == 2
    assert "RefresherEventDetail" in out.split("from '@ionic/react'")[0]  # imported
    from agents.reviewer.rules import _check_frontend
    assert not any("Bare CustomEvent" in i.message for i in _check_frontend(fe, {"module": "x"}, {}))


def test_fixer_agent_is_pure_python_and_applies_fixes():
    # 11/29 real runs: the LLM-wrapped fixer returned an empty turn and no fixer ran.
    import asyncio
    from types import SimpleNamespace
    from google.adk.agents import BaseAgent, LlmAgent
    from agents.fixer import fixer_agent
    assert isinstance(fixer_agent, BaseAgent) and not isinstance(fixer_agent, LlmAgent)
    route = '@router.post("/one_posRewardCatalogItem")\ndef one_posRewardCatalogItem(json: dict): ...\n'
    state = {"module": "posRewardCatalogItem", "gate_result": json.dumps(_gate()),
             "backend_artifacts": json.dumps({"module_file": {"content": "x"}, "route_file": {"content": route}})}
    ctx = SimpleNamespace(session=SimpleNamespace(state=state))

    async def _run():
        return [e async for e in fixer_agent._run_async_impl(ctx)]

    (event,) = asyncio.run(_run())
    fixed = json.loads(event.actions.state_delta["backend_artifacts"])["route_file"]["content"]
    assert "/one_posRewardCatalogItems" in fixed and "def one_posRewardCatalogItems(" in fixed


def test_review_loop_stages_are_pure_python_and_escalate():
    # factoryRunUsage-20260923-092926-3: LLM-wrapped reviewer never called
    # run_review -> run ended with no verdict at all.
    import asyncio
    from types import SimpleNamespace
    from google.adk.agents import LlmAgent
    from agents.reviewer import reviewer_agent
    from agents.loop_exit import loop_exit_agent
    from agents.review_fixer import review_fixer_agent
    for a in (reviewer_agent, loop_exit_agent, review_fixer_agent):
        assert not isinstance(a, LlmAgent), a.name
    out = generate_crud_sql(_spec(), _gate())
    state = {"module": "supplier", "specification": json.dumps(_spec()), "gate_result": json.dumps(_gate()),
             "database_artifacts": json.dumps(out)}
    ctx = SimpleNamespace(session=SimpleNamespace(state=state))

    async def _events(agent):
        return [e async for e in agent._run_async_impl(ctx)]

    (review_event,) = asyncio.run(_events(reviewer_agent))
    state.update(review_event.actions.state_delta)
    assert json.loads(state["review_result"])["scores"]["database"] == 100
    state["review_loop_iteration"] = 2  # third check hits the iteration limit
    (exit_event,) = asyncio.run(_events(loop_exit_agent))
    assert exit_event.actions.escalate is True


def test_migration_required_is_surfaced_by_reviewer():
    out = generate_crud_sql(_spec(), _gate())
    out["migration_required"] = "UNIQUE on normalized email (ADR-002) needs a computed column on live leadCaptures"
    msgs = [i.message for i in _check_database(out, _spec(), _gate())]
    assert any("needs a migration" in m for m in msgs)


def test_database_llm_fallback_sees_spec_reconciliation():
    from google.adk.agents.readonly_context import ReadonlyContext  # noqa: F401 (API sanity)
    from types import SimpleNamespace
    provider = database_llm_agent.instruction
    text = provider(SimpleNamespace(state={"spec_reconciliation": json.dumps({"status": "reconciled"}),
                                           "specification": "{}", "gate_result": "{}"}))
    assert "## Current `spec_reconciliation`" in text and "migration_required" in text


def test_retry_attempt_sees_what_was_wrong_and_notice_is_cleared():
    # Architect at temperature 0 answered "I have completed my task..." 3/3:
    # identical input = identical answer. The retry must change the input.
    import asyncio
    from types import SimpleNamespace
    from google.adk.events import Event, EventActions
    from agents.retry import has_specification, retry_key, retry_notice, run_with_retries

    seen = []

    class _Fake:
        name = "architect_agent"

        async def run_async(self, ctx):
            seen.append(retry_notice(ctx.session.state, self.name))
            out = "I have completed my task." if len(seen) == 1 else json.dumps(_spec())
            yield Event(author=self.name, actions=EventActions(state_delta={"specification": out}))

    ctx = SimpleNamespace(session=SimpleNamespace(state={}))
    report = {}

    async def _go():
        async for _ in run_with_retries(_Fake(), ctx, "specification", has_specification, 3, report):
            pass

    asyncio.run(_go())
    assert report["attempts"] == 2 and report["succeeded"]
    assert seen[0] == "" and "I have completed my task." in seen[1] and "ONLY the complete JSON" in seen[1]
    assert retry_key("architect_agent") not in ctx.session.state  # never leaks into later stages


def test_retry_attempts_are_branch_isolated_in_adk():
    # ADK showed agents their own earlier attempt ("I have completed the
    # previous request..."); per-attempt branches hide it, keep the rest.
    from typing import Optional
    from pydantic import BaseModel
    from google.adk.events import Event
    from google.adk.flows.llm_flows.contents import _is_event_belongs_to_branch
    from agents.retry import _attempt_context

    class _Ctx(BaseModel):
        branch: Optional[str] = None

    a1 = _attempt_context(_Ctx(branch="generation_stage.backend_stage"), "backend_agent", 1).branch
    a2 = _attempt_context(_Ctx(branch="generation_stage.backend_stage"), "backend_agent", 2).branch
    assert not _is_event_belongs_to_branch(a2, Event(author="backend_agent", branch=a1))
    assert _is_event_belongs_to_branch(a2, Event(author="user"))
    top = _attempt_context(_Ctx(), "architect_agent", 2).branch
    assert top == "architect_agent_attempt2"
    assert not _is_event_belongs_to_branch(top, Event(author="architect_agent", branch="architect_agent_attempt1"))


def test_fixer_tolerates_null_sql_keys_and_stage_never_crashes_run():
    # leadCapture-20260923-095805-2: LLM returned "create_table": null for an
    # existing live table; fix_database crashed the whole run with TypeError.
    import asyncio
    from types import SimpleNamespace
    from agents.fixer.rules import fix_database
    from agents.deterministic_stage import DeterministicToolStage
    fixed, _ = fix_database({"create_table": None, "sp_all": "SELECT 1", "sp_one": None, "sp_upsert": None},
                            {"_module": "leadCapture", "tier": "TIER_1_CATALOG"})
    assert fixed["create_table"] == ""

    def _boom(_ctx):
        raise ValueError("boom")

    stage = DeterministicToolStage(name="boom_stage", fn=_boom)
    ctx = SimpleNamespace(session=SimpleNamespace(state={}))

    async def _run():
        return [e async for e in stage._run_async_impl(ctx)]

    (event,) = asyncio.run(_run())
    assert "ValueError: boom" in event.actions.state_delta["boom_stage_error"]


def test_live_conflict_is_surfaced_deterministically():
    out = generate_crud_sql(_spec(), _gate())
    out["live_conflict"] = "tenant_model TENANT_INDEPENDENT disagrees with live table (has companyId)"
    msgs = [i.message for i in _check_database(out, _spec(), _gate())]
    assert any("conflicts with the gate decision" in m for m in msgs)


def test_gate_fk_check_uses_live_table_list_not_only_llm_summary():
    from agents.decision_gate.rules import _hard_block_check
    spec = _spec()  # companyId FK -> companies
    summary_missing_companies = {"valid_fk_targets": [{"table": "employees"}]}
    assert _hard_block_check(spec, summary_missing_companies) is not None  # old behavior
    assert _hard_block_check(spec, summary_missing_companies, ["companies", "employees"]) is None
    assert _hard_block_check(spec, summary_missing_companies, ["employees"]) is not None  # truly missing still blocks
