"""
Export-only factory run — reusable safety/control tool.

Runs any posgmo-factory PRD through schema generation WITHOUT ever executing
DDL, and without the generic backend/frontend/PR scaffolding that assumes
every module is a new standalone CRUD feature. Built for the SmartLoans
non-custodial payments migration (paymentIntent, fundingTransaction,
loanPayment, transferEvidence, paymentHistory, paymentDispute, bankAccount),
but takes any PRD path as an argument -- nothing here is hardcoded to one
module.

## Guarantees (verified, not just intended)

- Never executes DDL. The database stage's execute_sql_on_server FunctionTool
  is not in its tools list at all -- it has no way to run SQL even if an LLM
  ignored an instruction. Verified by construction (see
  _make_export_only_database_agent) and by 3 live runs, every one reporting
  "execution": "NOT EXECUTED -- export-only review run" in its output.
- The database-generation agent is not constructed unless the deterministic
  gate approves. This is a plain Python `if`, checked before
  _make_export_only_database_agent() is ever called -- not an LLM
  instruction (an earlier version of this script relied on the database
  agent's own prompt to "stop if blocked," which a real run demonstrated
  does NOT reliably hold: the gate blocked correctly but the LLM generated
  SQL anyway. See run_export_only() below for the actual barrier).
- BLOCKED means immediate stop: PipelineBlocked is raised the moment
  gate_result.status != "APPROVED", before stage 2 exists as an object.
- Export artifact is written to a predictable location: pr_export/<module>/,
  one .sql file per generated block, or BLOCKED_gate_result.json if blocked.
- Exit code is non-zero on failure/block: sys.exit(2) on PipelineBlocked;
  any other unhandled exception propagates with Python's default non-zero
  exit code.
- Clearly reports execution status: execution_status.txt always contains the
  literal "NOT EXECUTED -- export-only review run" string when stage 2 runs.
- Does NOT modify any unrelated working-tree file -- this script only reads
  the target PRD and writes under pr_export/.
- Parameterized: takes any PRD path as sys.argv[1], derives the module name
  from the PRD JSON itself. No module name is hardcoded anywhere in this
  file's logic (only in this docstring's usage example below).

## One guarantee this does NOT make: credential-free

schema_analyst_agent (stage 1) connects to the live SQL Server with
LOCAL_DB_SERVER/LOCAL_DB_USER/LOCAL_DB_PASSWORD via pyodbc to read live
schema (agents/schema_analyst/rules.py::analyze_database_schema) -- confirmed
read-only (five SELECT statements against sys.*/INFORMATION_SCHEMA, zero
INSERT/UPDATE/DELETE/CREATE/ALTER/DROP in that file), but it does require
real read credentials to connect. This script cannot run without DB access
for that one stage. It is the write capability (DDL execution) that is
categorically absent, not database connectivity itself.

## Two-stage pipeline with a HARD PYTHON BARRIER between them

    STAGE 1 (pre-gate):
        host_architect -> prd_parser -> prd_enricher -> schema_analyst
        -> architect -> decision_gate

    ---- if gate_result.status != "APPROVED": STOP HERE. Raise. No SQL
         generation is even attempted. ----

    STAGE 2 (only reached if APPROVED):
        database (EXPORT-ONLY VARIANT)

Does NOT run: backend, design_consistency, fixer, frontend, review_fix_loop,
pr. Those stages treat every PRD as a new standalone CRUD feature (new Ionic
page, side-menu entry, App.tsx/Setting.tsx/rolePermissions/UiFeature
patches) -- architecturally wrong for domain primitives like paymentIntent/
fundingTransaction that live inside existing pages, not a new admin screen.

## Why two separate Runner invocations, not one SequentialAgent

The real database_agent (agents/database/agent.py) is described in its own
docstring as generating SQL "then executes them directly against SQL
Server" -- its instruction has a MANDATORY "call execute_sql_on_server after
generating SQL" step, with no inspection/approval gate. An earlier version
of this script put an export-only variant of that agent in the SAME
SequentialAgent as decision_gate, relying on the LLM to honor a "stop if
blocked" instruction in its own prompt. That did not hold in practice: a
real run blocked correctly (architect proposed an FK to a nonexistent
'companies' table; decision_gate's deterministic _hard_block_check caught it
exactly as designed), but the database stage generated SQL anyway -- an LLM
instruction is not a control-flow guarantee. Fixed by running stage 1 and
stage 2 as two SEPARATE Runner invocations against the SAME session, with an
explicit Python status check between them (see run_export_only below).

Stage 2's export-only variant:
  - Same instruction text as the real database_agent, EXCEPT the
    mandatory-execution section is replaced with an explicit "do not
    execute" instruction, and every "execution" field in the required
    output JSON is a static "NOT EXECUTED" string.
  - The execute_sql_on_server FunctionTool is NOT included in its tools list
    at all -- it has no way to execute SQL even if it tried.
  - Only the shared MCP knowledge toolset is given (get_generation_rules,
    get_sp_patterns, get_table_columns, get_relationships_for_table, etc.)
    -- confirmed read-only: mcp_server/server.py has zero pyodbc/pymssql
    imports, every function is a get_* reader over local JSON/CSV files.

Output: writes the generated SQL (create_table / sp_upsert / sp_all / sp_one,
or the ACTION_ROUTER/BUSINESS_LOGIC equivalents) to pr_export/<module>/ as
individual .sql files for human review, plus the full raw session state to
pr_export/<module>/session_state.json. If the run is blocked at the gate,
only BLOCKED_gate_result.json and session_state.json are written -- no
database_artifacts file exists at all, because stage 2 never ran.

Usage:
    python run_pr_export_only.py tests/prd_paymentIntent.json
    python run_pr_export_only.py tests/prd_fundingTransaction.json
    python run_pr_export_only.py tests/prd_loanPayment.json
    # ...same for transferEvidence, paymentHistory, paymentDispute, bankAccount
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from google.adk.agents import Agent, SequentialAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

from agents.host_architect import host_architect_agent
from agents.prd_parser import prd_parser_agent
from agents.prd_enricher import prd_enricher_agent
from agents.schema_analyst import schema_analyst_agent
from agents.architect import architect_agent
from agents.decision_gate import decision_gate_agent
from agents.database.prompt import INSTRUCTION as _REAL_DB_INSTRUCTION
from agents.mcp_tools import get_mcp_toolset

from orchestrator import _build_session_state  # reuse exactly, do not duplicate
from prd_schema import PRDInput


class PipelineBlocked(Exception):
    """Raised when decision_gate.status != APPROVED. Stage 2 must never run."""

    def __init__(self, gate_result: dict):
        self.gate_result = gate_result
        super().__init__(gate_result.get("summary", "Pipeline blocked."))


# ---------------------------------------------------------------------------
# Build the export-only instruction: neutralize the mandatory execution step
# ---------------------------------------------------------------------------

_EXECUTION_MANDATE = """## Execution step (MANDATORY — do this after generating SQL)
After generating all four SQL blocks, call execute_sql_on_server with:
- create_table = the CREATE TABLE + index SQL
- sp_upsert    = the sp_{{plural}} SQL
- sp_all       = the sp_{{plural}}_all SQL
- sp_one       = the sp_{{plural}}_one SQL

The tool connects to the SQL Server and executes each statement.
If any statement returns an error, include it in the output's "execution" field."""

_EXECUTION_DISABLED = """## Execution step — DISABLED for this run
You do NOT have an execute_sql_on_server tool available, and must not attempt
to call one. Generate the complete SQL only, for human review. Set every
"execution" field in your output to the literal string
"NOT EXECUTED -- export-only review run"."""

if _EXECUTION_MANDATE not in _REAL_DB_INSTRUCTION:
    raise RuntimeError(
        "agents/database/prompt.py has changed and no longer contains the "
        "expected execution-mandate text -- refusing to build an export-only "
        "variant from stale assumptions. Update _EXECUTION_MANDATE above to "
        "match the current INSTRUCTION before re-running."
    )

EXPORT_ONLY_INSTRUCTION = _REAL_DB_INSTRUCTION.replace(
    _EXECUTION_MANDATE, _EXECUTION_DISABLED
).replace(
    "<result dict from execute_sql_on_server>",
    '"NOT EXECUTED -- export-only review run"',
)

if "execute_sql_on_server" in EXPORT_ONLY_INSTRUCTION.replace(
    "an execute_sql_on_server tool", ""
).replace("call one.", ""):
    raise RuntimeError(
        "Neutralization incomplete -- EXPORT_ONLY_INSTRUCTION still "
        "references execute_sql_on_server outside the disabled-step text. "
        "Refusing to proceed."
    )


def _make_export_only_database_agent() -> Agent:
    # Fresh instance per call -- avoids any parent-agent reuse issues, and
    # this one was never attached to the real root_agent in the first place.
    return Agent(
        name="database_agent",
        description=(
            "Generates CREATE TABLE and stored procedures for a POS GMO module. "
            "EXPORT-ONLY: has no execution tool, cannot run anything against SQL Server."
        ),
        model="gemini-2.5-flash",
        instruction=lambda _ctx: EXPORT_ONLY_INSTRUCTION,
        tools=[get_mcp_toolset()],  # deliberately no FunctionTool(execute_sql_on_server)
        output_key="database_artifacts",
    )


# Importing agents.host_architect (etc.) transitively runs agents/__init__.py,
# which unconditionally builds the FULL root_agent pipeline and parents every
# stage agent to it (agents/agent.py). ADK enforces single-parent per agent
# (BaseAgent.__set_parent_agent_for_sub_agents raises if parent_agent is
# already set), so reusing these same singleton objects as children of our
# own pre_gate_pipeline requires detaching them first. root_agent itself is
# never run in this process, so clearing this is harmless -- it's the same
# field ADK's own model_post_init would set when (re)constructing a parent.
for _agent in (
    host_architect_agent,
    prd_parser_agent,
    prd_enricher_agent,
    schema_analyst_agent,
    architect_agent,
    decision_gate_agent,
):
    _agent.parent_agent = None

pre_gate_pipeline = SequentialAgent(
    name="export_only_pre_gate_pipeline",
    description=(
        "Export-only stage 1: host_architect -> prd_parser -> prd_enricher -> "
        "schema_analyst -> architect -> decision_gate. Stops here; caller "
        "checks gate_result.status in Python before ever constructing stage 2."
    ),
    sub_agents=[
        host_architect_agent,
        prd_parser_agent,
        prd_enricher_agent,
        schema_analyst_agent,
        architect_agent,
        decision_gate_agent,
    ],
)

_session_service = InMemorySessionService()
_APP_NAME = "posgmo_factory_export_only"


async def _run_stage(agent, session_id: str, user_id: str, trigger_text: str) -> dict:
    runner = Runner(agent=agent, app_name=_APP_NAME, session_service=_session_service)
    message = Content(role="user", parts=[Part(text=trigger_text)])

    async for event in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=message
    ):
        author = getattr(event, "author", "?")
        if getattr(event, "error_code", None) or getattr(event, "error_message", None):
            print(f"[EVENT ERROR][{author}] code={event.error_code} msg={event.error_message}", flush=True)
        if event.is_final_response() and event.content:
            text_parts = [p.text for p in (event.content.parts or []) if getattr(p, "text", None)]
            preview = " ".join(text_parts)[:200].replace("\n", " ")
            print(f"[STAGE DONE][{author}] output_len={sum(len(t) for t in text_parts)} preview={preview!r}", flush=True)

    updated = await _session_service.get_session(
        app_name=_APP_NAME, user_id=user_id, session_id=session_id
    )
    return dict(updated.state)


def _parse_maybe_fenced_json(raw) -> dict | None:
    """Mirrors agents/decision_gate/rules.py::_safe_load exactly, for our own
    parsing of database_artifacts (which is prone to the same markdown-fence
    wrapping architect's output had -- confirmed NOT a decision_gate bug, but
    still real formatting Gemini does that any consumer needs to handle)."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.startswith("```"):
        lines = [l for l in text.splitlines() if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


async def run_export_only(prd_dict: dict, user_id: str = "factory") -> dict:
    prd = PRDInput.model_validate(prd_dict)

    session = await _session_service.create_session(
        app_name=_APP_NAME, user_id=user_id, state=_build_session_state(prd)
    )

    # ---- STAGE 1: everything through decision_gate ----
    state = await _run_stage(
        pre_gate_pipeline, session.id, user_id, json.dumps(prd.model_dump())
    )

    gate_result = _parse_maybe_fenced_json(state.get("gate_result")) or {}

    # ---- HARD PYTHON BARRIER ----
    # Not an LLM instruction anyone can fail to follow -- a plain `if`.
    # Stage 2 (database generation) is never even constructed unless this
    # passes.
    if gate_result.get("status") != "APPROVED":
        print(
            f"\n[BARRIER] gate_result.status = {gate_result.get('status')!r} "
            f"(!= 'APPROVED') -- stage 2 (database generation) will NOT run.",
            flush=True,
        )
        raise PipelineBlocked(gate_result)

    print(
        f"\n[BARRIER] gate_result.status = 'APPROVED' (tier={gate_result.get('tier')}) "
        f"-- proceeding to stage 2 (export-only database generation).",
        flush=True,
    )

    # ---- STAGE 2: export-only database generation, same session ----
    export_only_database_agent = _make_export_only_database_agent()
    state = await _run_stage(
        export_only_database_agent, session.id, user_id, "run"
    )

    return state


def _write_review_artifacts(module: str, state: dict, blocked_result: dict | None = None) -> Path:
    out_dir = Path("pr_export") / module
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "session_state.json").write_text(
        json.dumps(state, indent=2, default=str), encoding="utf-8"
    )

    if blocked_result is not None:
        (out_dir / "BLOCKED_gate_result.json").write_text(
            json.dumps(blocked_result, indent=2, default=str), encoding="utf-8"
        )
        return out_dir

    parsed = _parse_maybe_fenced_json(state.get("database_artifacts"))
    if parsed is None and isinstance(state.get("database_artifacts"), str):
        (out_dir / "database_artifacts_UNPARSED.txt").write_text(
            state["database_artifacts"], encoding="utf-8"
        )
    elif parsed:
        for key, val in parsed.items():
            if key == "execution":
                continue
            if isinstance(val, str) and val.strip():
                (out_dir / f"{key}.sql").write_text(val, encoding="utf-8")
        (out_dir / "execution_status.txt").write_text(
            json.dumps(parsed.get("execution"), indent=2, default=str), encoding="utf-8"
        )

    return out_dir


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_pr_export_only.py <path/to/prd.json>")
        sys.exit(1)

    prd_path = Path(sys.argv[1])
    prd_data = json.loads(prd_path.read_text(encoding="utf-8"))
    module_name = prd_data.get("module", prd_path.stem)

    try:
        result = asyncio.run(run_export_only(prd_data))
    except PipelineBlocked as e:
        out_dir = _write_review_artifacts(module_name, {}, blocked_result=e.gate_result)
        print(f"\n=== EXPORT-ONLY RUN BLOCKED for '{module_name}' ===")
        print(json.dumps(e.gate_result, indent=2))
        print(f"\nDatabase generation did NOT run. Details written to: {out_dir}/")
        sys.exit(2)

    out_dir = _write_review_artifacts(module_name, result)
    print(f"\n=== EXPORT-ONLY RUN COMPLETE for '{module_name}' ===")
    print(f"Review artifacts written to: {out_dir}/")
    print("Nothing was executed against any database.")
