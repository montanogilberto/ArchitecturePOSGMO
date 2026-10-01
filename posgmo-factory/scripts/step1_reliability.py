"""
Step 1 reliability harness: repeated REAL Factory runs, recorded as evidence.

Same pipeline as run_local_export.py (root_agent minus pr_agent and
design_consistency_agent -> no GitHub calls), with FACTORY_SQL_MODE=validate
so database_executor runs the generated SQL on the real server inside a
transaction that is rolled back (nothing persists, no live SP is replaced).

Per run it records: elapsed time, database generator (template / llm) and
LLM attempts, LLM/tool failures (pipeline_diagnostics), SQL execution
result, reviewer scores + issues, review-loop iterations. Appends one JSON
line per run to docs/evidence/step1/runs.jsonl and saves the run's artifacts
for inspection under docs/evidence/step1/artifacts/.

    python scripts/step1_reliability.py tests/prd_supplier.json --runs 3
    python scripts/step1_reliability.py tests/prd_factoryRunUsage.json --target commercial --runs 3
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ["FACTORY_SQL_MODE"] = "validate"

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
# Belt and braces: this harness must never reach GitHub, however the pipeline
# is wrapped (pr_agent inside pr_stage escaped the strip once -- see
# run_local_export._strip_pr_and_design_consistency). Without a token, any
# GitHub tool fails before sending a request.
for _var in ("GITHUB_TOKEN", "GH_TOKEN"):
    os.environ.pop(_var, None)

from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai.types import Content, Part  # noqa: E402

from orchestrator import _build_session_state  # noqa: E402  (also installs the model-redirect patch)
from pipeline_diagnostics import classify_event  # noqa: E402
from llm_usage import UsageTracker, format_summary as format_usage  # noqa: E402
from prd_schema import PRDInput  # noqa: E402
from run_local_export import _strip_pr_and_design_consistency  # noqa: E402
from agents import root_agent  # noqa: E402
from agents.database.sql_templates import _safe_load  # noqa: E402

EVIDENCE = ROOT / "docs" / "evidence" / "step1"


async def one_run(prd_dict: dict, target: str, run_label: str) -> dict:
    _strip_pr_and_design_consistency()
    service = InMemorySessionService()
    runner = Runner(agent=root_agent, app_name="posgmo_factory_step1", session_service=service)
    prd = PRDInput.model_validate(prd_dict)
    session = await service.create_session(
        app_name="posgmo_factory_step1", user_id="step1", state=_build_session_state(prd, target=target)
    )
    message = Content(role="user", parts=[Part(text=json.dumps(prd.model_dump()))])

    diagnostics, crash = [], None
    usage = UsageTracker()
    started = time.monotonic()
    try:
        async for event in runner.run_async(user_id="step1", session_id=session.id, new_message=message):
            usage.observe(event)
            flagged = classify_event(event)
            if flagged:
                diagnostics.append(flagged)
    except Exception as e:  # noqa: BLE001 -- a crashed run is evidence, not a harness failure
        import traceback
        crash = f"{type(e).__name__}: {str(e)[:300]} | " + traceback.format_exc()[-1500:]
    elapsed = round(time.monotonic() - started, 1)

    state = dict((await service.get_session(
        app_name="posgmo_factory_step1", user_id="step1", session_id=session.id)).state)
    db = _safe_load(state.get("database_artifacts"))
    review = _safe_load(state.get("review_result"))
    execution = db.get("execution") or {}
    exec_errors = [d.get("message", "")[:200] for d in execution.get("details", []) if d.get("status") != "ok"
                   and not str(d.get("status", "")).startswith("skipped")]

    record = {
        "run": run_label,
        "module": prd.module,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "elapsed_s": elapsed,
        "crash": crash,
        "gate": {k: _safe_load(state.get("gate_result")).get(k) for k in ("status", "tier", "tenant_model", "backend_pattern")},
        "database_generation": db.get("generation"),
        "sql_execution": {"success": execution.get("success"), "mode": execution.get("mode"),
                          "batches": len(execution.get("details", [])), "errors": exec_errors},
        "review": {"scores": review.get("scores"), "passed": review.get("passed"),
                   "issues": [f"{i.get('artifact')}: {i.get('message')}" for i in review.get("issues", [])]},
        "review_loop_iteration": state.get("review_loop_iteration"),
        # prd_enricher saves via a large dict tool argument (the pattern that
        # made database_agent unreliable) -- track whether it actually landed.
        "enriched_prd_saved": bool(_safe_load(state.get("enriched_prd"))),
        "architect_attempts": _safe_load(state.get("specification_attempts")),
        "backend_attempts": _safe_load(state.get("backend_artifacts_attempts")),
        "spec_reconciliation": _safe_load(state.get("spec_reconciliation")),
        "llm_tool_failures": diagnostics,
        "database_agent_failures": [d for d in diagnostics if d.get("agent", "").startswith("database")],
        "llm_usage": usage.summary(),
    }
    print(format_usage(record["llm_usage"]), flush=True)
    art_dir = EVIDENCE / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)
    (art_dir / f"{run_label}.json").write_text(json.dumps({
        k: state.get(k) for k in ("specification", "gate_result", "database_artifacts",
                                  "backend_artifacts", "frontend_artifacts", "review_result")
    }, indent=2, default=str), encoding="utf-8")
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prd_path", type=Path)
    ap.add_argument("--target", default="pos")
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()

    prd_dict = json.loads(args.prd_path.read_text(encoding="utf-8"))
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for i in range(1, args.runs + 1):
        label = f"{prd_dict['module']}-{stamp}-{i}"
        rec = asyncio.run(one_run(prd_dict, args.target, label))
        with (EVIDENCE / "runs.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        g = rec["database_generation"] or {}
        print(f"[step1] {label} elapsed={rec['elapsed_s']}s generator={g.get('generator')} "
              f"llm_attempts={g.get('llm_attempts')} sql_ok={rec['sql_execution']['success']} "
              f"scores={rec['review']['scores']} passed={rec['review']['passed']} "
              f"db_failures={len(rec['database_agent_failures'])} crash={rec['crash']}", flush=True)


if __name__ == "__main__":
    main()
