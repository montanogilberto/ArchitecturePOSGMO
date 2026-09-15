"""
Phase 8 — feature-flagged bridge from the agentic debate (debate_v2/) to
the EXISTING deterministic factory (orchestrator.py / agents/agent.py).

Founding principle from the design discussion: "Agents reason. Deterministic
pipelines execute." This script does NOT replace orchestrator.py and does
NOT auto-generate a PRDInput from debate prose (a Decision's claim is a
sentence, not a field-by-field module spec — turning intent into a PRD is
still a deliberate authoring step, same as today). What it DOES do:

  1. Run the debate over a free-text request.
  2. If the debate escalates (ambiguous intent, or an unresolved high-
     severity conflict) -> STOP. Never proceeds to generation on an
     unresolved question.
  3. If the debate converges AND you already have a hand-written PRD that
     matches the chosen direction, validate that PRD against the existing
     PRDInput schema and show it next to the debate's decision so a human
     can confirm they agree before anything is generated.
  4. ONLY with --execute (default: off) does it call the REAL factory
     (orchestrator.run_factory), which ends in pr_agent pushing branches
     and opening PRs on the real GitHub repos configured in .env. Without
     --execute this is a pure dry run — nothing is generated, nothing is
     pushed, nothing outside this process is touched.

Usage:
    python run_agentic_factory.py "create a new module for rewards" --prd tests/prd_posRewardBalance.json
    python run_agentic_factory.py "create a new module for rewards" --prd tests/prd_posRewardBalance.json --execute
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import ValidationError

from debate_schema import read_blackboard, read_status
from debate_v2.run import run_debate
from debate_v2.solution_package import render_solution_package
from debate_v2.transcript import render_transcript
from decision_registry import record_decision
from prd_schema import PRDInput

load_dotenv()


def validate_prd(prd_path: Path) -> PRDInput:
    """Same gate the real factory already applies (prd_schema.PRDInput) —
    reused here, not reimplemented, so a PRD accepted by this bridge is
    guaranteed acceptable to orchestrator.py too."""
    raw = json.loads(prd_path.read_text(encoding="utf-8"))
    return PRDInput.model_validate(raw)


async def run_agentic_gate(request: str, prd_path: Optional[Path], execute: bool) -> int:
    print(f"=== Debate: {request!r} ===\n")
    state = await run_debate(request)
    print(render_transcript(state))

    status = read_status(state)
    decisions = read_blackboard(state, "decisions")

    out_dir = Path(__file__).parent / "debate_v2_output"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "SOLUTION_PACKAGE.md").write_text(render_solution_package(state), encoding="utf-8")
    print(f"\nSolution Package written to {out_dir / 'SOLUTION_PACKAGE.md'}")

    if status.needs_user_input or not decisions:
        print("\n=== GATE: STOPPED ===")
        print("The debate did not converge — nothing will be generated.")
        if status.escalation_reason:
            print(f"Reason: {status.escalation_reason}")
        for q in status.open_questions:
            print(f"  ? {q}")
        return 1

    decision = decisions[0]
    print("\n=== GATE: CONVERGED ===")
    print(f"Decision: {decision.selected_claim}")
    print(f"Confidence: {decision.confidence:.2f}")

    module = None
    prd: Optional[PRDInput] = None
    if prd_path is not None:
        try:
            prd = validate_prd(prd_path)
        except (ValidationError, FileNotFoundError, json.JSONDecodeError) as exc:
            print(f"\n=== GATE: PRD INVALID ===\n{exc}")
            return 1
        module = prd.module
        print(f"\nPRD '{prd_path}' is valid against the existing PRDInput schema: "
              f"module={prd.module!r}, {len(prd.fields)} field(s).")

    # Persist the decision now, regardless of what happens next — a
    # converged decision is worth keeping even on a dry run with no --prd
    # yet, so "why did you decide X" stays answerable later.
    record = record_decision(request=request, decision=decision, module=module)
    print(f"\nRecorded as {record['id']} in the Decision Registry "
          f"(decision_registry/{record['id']}.json)")

    if prd_path is None:
        print("\nNo --prd given — nothing to validate or execute. Pass a PRD file that "
              "implements this decision to continue.")
        return 0

    if not execute:
        print("\n--execute not passed: dry run only. The real factory "
              "(orchestrator.run_factory) was NOT invoked, nothing was generated, "
              "and nothing was pushed to GitHub.")
        return 0

    print("\n=== EXECUTING THE REAL FACTORY (orchestrator.run_factory) ===")
    print("This calls the SAME deterministic pipeline as `python orchestrator.py`, "
          "including the PR Agent step that pushes to the configured GitHub repos.")
    from orchestrator import run_factory  # deferred: only import the real factory if --execute
    result = await run_factory(prd.model_dump())
    print("\n=== FACTORY RESULT ===")
    print(json.dumps(result, indent=2, default=str))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("request", help="Free-text feature request, e.g. 'create a new module for rewards'")
    parser.add_argument("--prd", type=Path, default=None,
                         help="Path to a hand-written PRD JSON implementing the debate's decision")
    parser.add_argument("--execute", action="store_true",
                         help="Actually run the real factory (generates files, opens PRs). Default: dry run.")
    args = parser.parse_args()

    exit_code = asyncio.run(run_agentic_gate(args.request, args.prd, args.execute))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
