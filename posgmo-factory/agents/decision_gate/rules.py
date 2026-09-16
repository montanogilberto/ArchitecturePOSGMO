# Decision Gate — pure-Python classification logic.
# No LLM involved; all rules are deterministic Python.

"""
Decision Gate — deterministic Python classifier.

Replaces the LLM-based gate entirely. All tier classification, backend pattern
detection, constraint generation, and hard-block checks are pure Python logic —
no LLM involved. Output is written directly to session state as 'gate_result'.

This removes the #1 source of cascading pipeline failures: an LLM re-reasoning
classification rules differently on each run.
"""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event

from decision_registry import get_decisions_for_module, get_decision_for_topic, get_effective_constraints


# ---------------------------------------------------------------------------
# Constants — keyword sets used by all classifiers
# ---------------------------------------------------------------------------

_TIER4_SIGNALS = {
    "sensor", "telemetry", "iot", "hardware", "reading", "water level",
    "temperature", "led", "high-frequency", "device", "actuator", "firmware",
}

_TIER3_SALES_DOMAIN = {
    "sale", "sales", "invoice", "order", "purchase", "billing", "receipt",
    "checkout", "cart",
}

_TIER3_LINE_ITEMS = {
    "line item", "line-item", "items[]", "order detail", "order line",
    "detail table", "item list",
}

# Tables that are known TIER_2 financial parents
_KNOWN_FINANCIAL_TABLES = {
    "sales", "invoices", "orders", "purchases", "expenses", "incomes",
    "payments", "receipts", "cashregistersessions",
}

_TIER2_MONETARY_WORDS = {
    "expense", "income", "payment", "amount", "total", "price", "cost",
    "revenue", "balance", "fee", "charge", "subtotal", "tax", "discount",
    "refund", "deposit", "withdrawal",
}

# Column names that represent ratios/scores — NEVER financial
_RATIO_FIELD_NAMES = {
    "confidencescore", "confidence", "score", "probability", "ratio",
    "percentage", "rate", "accuracy", "precision", "recall", "latitude",
    "longitude", "lat", "lng",
}

_CONNECTOR_TRIGGER_WORDS = {
    "azure", "aws", "stripe", "twilio", "firebase", "openai", "blob storage",
    "face api", "payment gateway", "webhook", "third-party", "orchestrate",
    "upload", "external", "ai model", "iot broker", "smtp", "sendgrid",
}

_STANDARD_CRUD_PATHS = {"/{plural}", "/all_{plural}", "/one_{plural}"}

# ---------------------------------------------------------------------------
# Tenant model — replaces a blanket "companyId is always required" assumption.
#
# Experiment 1/2/3 (docs/experiment1-leadCapture-evaluation.md) traced a real
# security defect back to this exact gate: _build_mandatory_constraints used
# to assert "companyId INT NOT NULL must be present" unconditionally, with no
# awareness of the PRD's own stated exception ("this lead has no existing
# companyId relationship"). Database, Backend, and Frontend agents all
# inherited that assumption independently, in three different runs, in three
# different concrete implementations, all wrong. The fix isn't "add a special
# case for leadCapture" -- it's making tenancy an explicit, checkable
# classification with an UNKNOWN state that BLOCKS construction, instead of a
# hardcoded rule that silently assumes the common case.
# ---------------------------------------------------------------------------

_TENANT_INDEPENDENT_SIGNALS = (
    "no existing companyid relationship",
    "not a pos gmo tenant",
    "no tenant relationship",
    "has no companyid",
)


def _classify_tenant_model(prd_raw: dict) -> tuple[str, str]:
    """
    Returns (tenant_model, reason). tenant_model is one of:
      TENANT_SCOPED       -- default. This module's rows belong to an existing
                             company, like the great majority of POS GMO modules.
      TENANT_INDEPENDENT  -- PRD explicitly states no existing companyId
                             relationship, and nothing else about the module
                             creates ambiguity about how tenant identity would
                             even be established.
      UNKNOWN             -- PRD gives a tenant-independence signal AND also
                             exposes an unauthenticated public write path --
                             i.e. something other than "assume the normal
                             tenant model" is clearly going on, but which
                             specific alternative (derive companyId server-side?
                             reject public writes entirely? something else?)
                             has not been decided by anyone. Construction must
                             not guess here; see get_decision_for_topic.
    """
    if not prd_raw:
        return "TENANT_SCOPED", "prd_raw not available in session state -- defaulting to standard tenant model."

    text_blobs = [prd_raw.get("description", "") or ""]
    for f in (prd_raw.get("fields") or []):
        text_blobs.append(f.get("description", "") or "")
    full_text = " ".join(text_blobs).lower()

    if not any(sig in full_text for sig in _TENANT_INDEPENDENT_SIGNALS):
        return "TENANT_SCOPED", "No tenancy-exception language found in the PRD -- default POS GMO assumption applies."

    endpoints = ((prd_raw.get("backend") or {}).get("endpoints")) or []
    has_public_write = any(
        "public" in ((ep.get("path", "") + " " + ep.get("description", "")).lower())
        and "unauthenticated" in (ep.get("description", "") or "").lower()
        for ep in endpoints
    )
    if has_public_write:
        return (
            "UNKNOWN",
            "PRD states this module has no existing companyId relationship AND exposes "
            "an unauthenticated public write path -- how tenant identity should be "
            "established for those writes is an architecture decision, not something "
            "to assume. Record a tenant_model decision via decision_registry.record_decision "
            "(topic='tenant_model') before construction can proceed.",
        )
    return (
        "TENANT_INDEPENDENT",
        "PRD states this module has no existing companyId relationship and has no "
        "unauthenticated public write path that would need one supplied externally.",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _words(text: str) -> str:
    return text.lower() if text else ""


def _has_any(text: str, keywords: set) -> bool:
    t = _words(text)
    return any(kw in t for kw in keywords)


def _is_ratio_column(col_name: str, sql_type: str) -> bool:
    """Return True if this decimal column is clearly a ratio/score, NOT money."""
    name_lower = col_name.lower().replace("_", "")
    if name_lower in _RATIO_FIELD_NAMES:
        return True
    # decimal(5,x) or decimal(x,4+) → almost certainly a ratio, not money
    if "decimal" in sql_type.lower():
        import re
        m = re.search(r"decimal\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)", sql_type.lower())
        if m:
            scale = int(m.group(2))
            if scale >= 4:
                return True
    return False


# ---------------------------------------------------------------------------
# Core classifier
# ---------------------------------------------------------------------------

def _classify_tier(spec: dict, schema_analysis: dict) -> tuple[str, str]:
    """
    Returns (tier, reason) deterministically.
    Priority: TIER_4 > TIER_3 > TIER_2 > TIER_1
    """
    desc = _words(spec.get("description", ""))
    columns = spec.get("db", {}).get("columns", [])
    prd_hints = spec.get("prd_hints", {})

    # ── TIER_4: physical hardware only ──────────────────────────────────────
    if _has_any(desc, _TIER4_SIGNALS):
        # Make sure it's not just "Azure API" language misread as hardware
        azure_only = _has_any(desc, {"azure", "aws", "api", "blob"}) and not _has_any(
            desc, {"sensor", "hardware", "device", "telemetry", "iot"}
        )
        if not azure_only:
            return "TIER_4_IOT", "Description mentions physical hardware/sensor signals."

    # ── TIER_3: ALL three conditions required ────────────────────────────────
    has_sales_domain = _has_any(desc, _TIER3_SALES_DOMAIN)
    has_line_items = _has_any(desc, _TIER3_LINE_ITEMS)
    fk_tables = {
        c.get("fk_table", "").lower()
        for c in columns
        if c.get("fk_table")
    }
    has_financial_fk = bool(fk_tables & _KNOWN_FINANCIAL_TABLES)

    if has_sales_domain and has_line_items and has_financial_fk:
        return (
            "TIER_3_TRANSACTIONAL",
            "Business domain is sales/orders, spec describes line items, and has FK to a financial parent table.",
        )

    # ── TIER_2: monetary decimal columns ────────────────────────────────────
    # A column is financial only if its NAME suggests money AND it's decimal/money type
    for col in columns:
        col_name = col.get("name", "")
        sql_type = col.get("sql_type", "").lower()
        is_decimal = any(t in sql_type for t in ("decimal", "money", "numeric", "float"))
        if not is_decimal:
            continue
        if _is_ratio_column(col_name, sql_type):
            continue  # skip scores, probabilities, GPS coords
        if _has_any(col_name, _TIER2_MONETARY_WORDS) or _has_any(desc, _TIER2_MONETARY_WORDS):
            return (
                "TIER_2_FINANCIAL",
                f"Column '{col_name}' is a monetary decimal ({sql_type}) and description/name indicates financial data.",
            )

    return "TIER_1_CATALOG", "No financial amounts, no line-items, no hardware signals — simple master data."


def _classify_backend_pattern(spec: dict) -> tuple[str, list[dict]]:
    """
    Returns (backend_pattern, connector_endpoints[]).
    CRUD_AND_CONNECTOR when PRD declares custom endpoints that mention external services.
    """
    prd_hints = spec.get("prd_hints", {})
    endpoints = prd_hints.get("backend_endpoints", [])
    module = spec.get("module", "module")
    columns = spec.get("db", {}).get("columns", [])
    plural = f"{module}s"

    connectors = []
    for ep in endpoints:
        path = ep.get("path", "")
        desc = ep.get("description") or ""
        req_schema = ep.get("requestSchema") or ""
        res_schema = ep.get("responseSchema") or ""

        # Skip if path matches standard CRUD pattern
        normalized = path.replace(plural, "{plural}").replace(module, "{plural}")
        if normalized in _STANDARD_CRUD_PATHS:
            continue

        # Flag as connector if description mentions external services
        if _has_any(desc + " " + req_schema + " " + res_schema, _CONNECTOR_TRIGGER_WORDS):
            # Infer external service from description
            external = []
            if "face api" in desc.lower() or "face" in desc.lower():
                external.append("Azure Face API")
            if "blob" in desc.lower() or "storage" in desc.lower():
                external.append("Azure Blob Storage")
            if "stripe" in desc.lower():
                external.append("Stripe")
            if not external:
                external.append("External Service")

            # Infer request/response fields from column names
            col_names = [c.get("name") for c in columns if c.get("name")]
            connectors.append({
                "method": ep.get("method", "POST"),
                "path": path,
                "description": desc,
                "external_service": ", ".join(external),
                "request_fields": col_names[:5],
                "response_fields": [c for c in col_names if c not in ("created_At", "updated_at", "companyId")],
                "notes": f"Use os.getenv() for credentials. httpx.AsyncClient for HTTP calls.",
            })

    if connectors:
        return "CRUD_AND_CONNECTOR", connectors
    return "CRUD_ONLY", []


def _build_mandatory_constraints(tier: str, backend_pattern: str, connector_endpoints: list,
                                  tenant_model: str = "TENANT_SCOPED",
                                  tenant_constraints: list | None = None) -> dict:
    """Build mandatory_constraints dict deterministically from tier."""
    db_rules = []
    backend_rules = [
        "all_{plural}_sp(json_file: dict) must pass json_file to sp_all via @pjsonfile (never zero-arg).",
        "Never use round() on any value returned from the database.",
    ]

    if tenant_model in ("TENANT_SCOPED", "TENANT_DERIVED"):
        db_rules.append("companyId INT NOT NULL must be present in CREATE TABLE.")
        db_rules.append("sp_all MUST accept @pjsonfile and filter WHERE companyId = @companyId.")
    elif tenant_model == "TENANT_INDEPENDENT":
        db_rules.append(
            "companyId is NOT applicable to this module (explicit tenant_model decision) -- "
            "do not add a NOT NULL companyId column or a foreign key to companies."
        )
        for c in (tenant_constraints or []):
            db_rules.append(c)
            backend_rules.append(c)

    db_rules += [
        "Every nullable column in SELECT must be wrapped with ISNULL(col, default).",
        "SP mutations must be wrapped in BEGIN TRY / BEGIN TRANSACTION / COMMIT / END TRY BEGIN CATCH ROLLBACK END CATCH.",
    ]
    frontend_rules = [
        "UTC-7 offset (toHermosillo) must be applied to every date field displayed.",
        "IVA = 0 always. Never compute tax.",
        "Use catch (err) with (err as Error).message — never catch (err: any).",
        "All event handlers must use specific CustomEvent generic types — never bare CustomEvent or CustomEvent<any>.",
    ]

    if tier == "TIER_2_FINANCIAL":
        db_rules.append("All monetary DECIMAL columns (amounts, totals, prices) must be DECIMAL(10,2).")
        db_rules.append("Non-monetary decimal columns (scores, ratios, coordinates) keep their original precision (e.g. DECIMAL(5,4)).")
        backend_rules.append("Return raw DECIMAL values — no rounding, no float conversion.")
        frontend_rules.append("Display monetary amounts with .toFixed(2). Do not recompute totals client-side.")

    elif tier == "TIER_3_TRANSACTIONAL":
        db_rules.append("Generate TWO tables: header + detail. SP_upsert handles both in one transaction.")
        frontend_rules.append("Master-detail view: IonModal for line items. Total from server only.")

    elif tier == "TIER_4_IOT":
        db_rules.append("Use DATETIME2(3) instead of DATETIME for all timestamp columns.")
        db_rules.append("No soft delete (no active flag) — sensor readings are immutable.")
        frontend_rules.append("Chart/graph view — no IonList.")

    if backend_pattern == "CRUD_AND_CONNECTOR":
        for ep in connector_endpoints:
            backend_rules.append(
                f"Connector '{ep['path']}': use httpx.AsyncClient, os.getenv() for secrets, "
                f"call {ep['external_service']}. Match response_fields: {ep['response_fields']}."
            )

    return {"database": db_rules, "backend": backend_rules, "frontend": frontend_rules}


def _apply_generic_decisions(mandatory_constraints: dict, applicable_decisions: list[dict]) -> None:
    """Generic decision -> constraint propagation, in place.

    tenant_model has its own dedicated classifier/block logic above (a
    proven, tested special case -- not touched here). Every OTHER recorded
    decision, regardless of topic, flows through this one small loop: no
    future decision topic (duplicate_policy, consent, retention, ...) should
    ever require decision_gate to grow a new bespoke classifier function.
    The decision registry is the extensibility point; this gate is just
    plumbing.
    """
    for d in applicable_decisions:
        if d.get("topic") == "tenant_model":
            continue  # already applied explicitly, above -- see module docstring note
        for layer, items in get_effective_constraints(d).items():
            if layer in mandatory_constraints:
                mandatory_constraints[layer].extend(items)


def _build_index_recommendations(tier: str, columns: list, tenant_model: str = "TENANT_SCOPED") -> list[dict]:
    indexes = []
    if tenant_model in ("TENANT_SCOPED", "TENANT_DERIVED"):
        indexes.append({"column": "companyId", "reason": "every query filters by company"})
    if tier in ("TIER_2_FINANCIAL", "TIER_3_TRANSACTIONAL"):
        indexes.append({"column": "created_At", "reason": "financial reports sort by date"})
    # Add indexes for FK columns
    for col in columns:
        if col.get("fk_table") and col["name"] != "companyId":
            indexes.append({"column": col["name"], "reason": f"FK to {col['fk_table']}"})
    return indexes


def _detect_soft_delete_parents(spec: dict, schema_analysis: dict) -> list[dict]:
    """Check schema_analysis.table_details for parent tables that have an 'active' column."""
    result = []
    table_details = schema_analysis.get("table_details", {})
    columns = spec.get("db", {}).get("columns", [])

    for col in columns:
        fk_table = col.get("fk_table")
        if not fk_table or fk_table == "companies":
            continue
        details = table_details.get(fk_table, {})
        has_active = "active" in [c.lower() for c in details.get("columns", [])]
        if has_active:
            result.append({
                "fk_table": fk_table,
                "fk_column": col["name"],
                "has_active_flag": True,
                "sp_filter_required": (
                    f"INNER JOIN dbo.{fk_table} p ON t.{col['name']} = p.{col.get('fk_column','id')}"
                    f" WHERE p.active = '1'"
                ),
            })
    return result


def _hard_block_check(spec: dict, schema_analysis: dict) -> dict | None:
    """
    Returns a BLOCKED gate_result if a hard block condition is met, else None.
    Current hard blocks: invalid FK targets.
    (table_already_exists is a warning, not a block — CREATE OR ALTER handles it.)
    """
    valid_fk_targets = {t["table"].lower() for t in schema_analysis.get("valid_fk_targets", [])}
    columns = spec.get("db", {}).get("columns", [])

    for col in columns:
        fk_table = col.get("fk_table")
        if fk_table and fk_table.lower() not in valid_fk_targets:
            return {
                "status": "BLOCKED",
                "tier": "BLOCKED",
                "tier_reason": "Hard block — invalid FK target.",
                "backend_pattern": "CRUD_ONLY",
                "connector_endpoints": [],
                "mandatory_constraints": {"database": [], "backend": [], "frontend": []},
                "soft_delete_parents": [],
                "index_recommendations": [],
                "warnings": [],
                "reason": f"FK target '{fk_table}' does not exist in the live database.",
                "fix": f"Create table '{fk_table}' first, or remove the FK from the spec.",
                "summary": f"Pipeline blocked: FK target '{fk_table}' not found in DB.",
            }
    return None


# ---------------------------------------------------------------------------
# Core gate logic — pure Python, no LLM
# ---------------------------------------------------------------------------

def _safe_load(raw: Any, default: dict | None = None) -> dict:
    if default is None:
        default = {}
    if not isinstance(raw, str):
        return raw if isinstance(raw, dict) else default
    raw = raw.strip()
    if not raw:
        return default
    if raw.startswith("```"):
        lines = [l for l in raw.splitlines() if not l.strip().startswith("```")]
        raw = "\n".join(lines).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def compute_gate_result(state: dict) -> dict:
    """
    Pure-Python gate logic. Reads 'specification' and 'schema_analysis' from
    the given state dict and returns the gate_result dict.
    """
    raw_spec = state.get("specification", "")
    raw_schema = state.get("schema_analysis", "")
    print(
        f"[gate] specification type={type(raw_spec).__name__} "
        f"len={len(str(raw_spec))} preview={str(raw_spec)[:120]!r}",
        flush=True,
    )

    spec = _safe_load(raw_spec)
    schema = _safe_load(raw_schema)

    if not spec:
        return {
            "status": "BLOCKED",
            "tier": "BLOCKED",
            "tier_reason": "No specification found in session state.",
            "backend_pattern": "CRUD_ONLY",
            "connector_endpoints": [],
            "mandatory_constraints": {"database": [], "backend": [], "frontend": []},
            "soft_delete_parents": [],
            "index_recommendations": [],
            "applicable_decisions": [],
            "warnings": [],
            "reason": "specification key missing from session state.",
            "fix": "Ensure Architect Agent ran successfully before Decision Gate.",
            "summary": "Pipeline blocked: specification not found.",
        }

    hard_block = _hard_block_check(spec, schema)
    if hard_block:
        hard_block.setdefault("applicable_decisions", [])
        return hard_block

    module = spec.get("module", "")

    # Tenant model: an explicit, recorded decision always wins over the
    # heuristic (a human/debate call is authoritative; the heuristic is only
    # a fallback for when no one has decided yet). See _classify_tenant_model
    # for why this replaced a blanket "companyId always required" rule.
    tenant_decision = get_decision_for_topic(module, "tenant_model") if module else None
    if tenant_decision:
        tenant_model = tenant_decision["selectedClaim"]
        tenant_model_reason = f"Explicit decision {tenant_decision['id']}: {tenant_decision['rationale']}"
        tenant_constraints = tenant_decision.get("constraints", [])
    else:
        tenant_model, tenant_model_reason = _classify_tenant_model(_safe_load(state.get("prd_raw", "")))
        tenant_constraints = []

    if tenant_model == "UNKNOWN":
        return {
            "status": "BLOCKED",
            "tier": "BLOCKED",
            "tier_reason": "Hard block — tenant model undecided.",
            "backend_pattern": "CRUD_ONLY",
            "connector_endpoints": [],
            "mandatory_constraints": {"database": [], "backend": [], "frontend": []},
            "soft_delete_parents": [],
            "index_recommendations": [],
            "applicable_decisions": [],
            "tenant_model": "UNKNOWN",
            "tenant_model_reason": tenant_model_reason,
            "warnings": [],
            "reason": tenant_model_reason,
            "fix": (
                f"Record an explicit tenant_model decision for module '{module}' via "
                f"decision_registry.record_decision(topic='tenant_model', module='{module}', ...) "
                "before construction can proceed. Do not remove this block by guessing."
            ),
            "summary": f"Pipeline blocked: tenant model for '{module}' is undecided.",
        }

    tier, tier_reason = _classify_tier(spec, schema)
    backend_pattern, connector_endpoints = _classify_backend_pattern(spec)
    columns = spec.get("db", {}).get("columns", [])
    mandatory_constraints = _build_mandatory_constraints(
        tier, backend_pattern, connector_endpoints, tenant_model, tenant_constraints
    )
    soft_delete_parents = _detect_soft_delete_parents(spec, schema)
    index_recommendations = _build_index_recommendations(tier, columns, tenant_model)

    # Prior architecture decisions for this module (decision_registry.py,
    # populated by run_agentic_factory.py's debate-convergence gate). Pure
    # lookup, no semantic judgment: this
    # gate does not decide whether the spec CONTRADICTS a prior decision —
    # that requires reading free text, which a zero-LLM gate can't do
    # reliably. It only makes the decision visible to every downstream agent
    # via gate_result, same as mandatory_constraints already is; the
    # Architect (agents/architect/prompt.py) is the one instructed to
    # actually reconcile against it, upstream of this gate.
    applicable_decisions = get_decisions_for_module(module) if module else []
    _apply_generic_decisions(mandatory_constraints, applicable_decisions)

    warnings = []
    if schema.get("table_already_exists"):
        warnings.append("Table already exists — Database Agent will use CREATE OR ALTER. No action needed.")
    for ref in schema.get("risky_references", []):
        warnings.append(f"PRD references '{ref}' but it was not found in the DB — will not be generated.")
    prd_hints = spec.get("prd_hints", {})
    if prd_hints.get("frontend_ui_pattern") == "Wizard Flow Layout":
        warnings.append("Wizard Flow Layout detected — Camera capture (Capacitor) must be wired manually after generation.")
    for d in applicable_decisions:
        warnings.append(
            f"Prior decision {d['id']} recorded for module '{module}': {d['selectedClaim']} "
            f"— honor this unless it conflicts with live schema_analysis, in which case the live schema wins."
        )

    return {
        "status": "APPROVED",
        "tier": tier,
        "tier_reason": tier_reason,
        "backend_pattern": backend_pattern,
        "connector_endpoints": connector_endpoints,
        "mandatory_constraints": mandatory_constraints,
        "soft_delete_parents": soft_delete_parents,
        "index_recommendations": index_recommendations,
        "applicable_decisions": applicable_decisions,
        "tenant_model": tenant_model,
        "tenant_model_reason": tenant_model_reason,
        "warnings": warnings,
        "summary": (
            f"Module classified as {tier} with {backend_pattern}. "
            f"{'Key constraint: ' + mandatory_constraints['database'][0] if mandatory_constraints['database'] else ''}"
        ),
    }


# ---------------------------------------------------------------------------
# Pure BaseAgent — no LLM, no tool call required
# ---------------------------------------------------------------------------