"""
POS GMO AI Factory — Pipeline Assembly

Imports all agents from their subpackages and assembles the root_agent
SequentialAgent with the full pipeline.

Pipeline stages:
  0.  host_architect      — detect app profile (POS/LOANS/VENDING/CUSTOM) → app_profile
  1.  prd_parser          — parse PRD JSON → session state vars
  2.  prd_enricher        — inject domain context → enriched_prd
  3.  schema_analyst      — query live DB → schema_analysis
  4.  architect           — design SpecificationJSON (bounded retries: agents/retry.py)
  5.  decision_gate       — deterministic tier + constraint classification
  5b. spec_reconciler     — deterministic: existing live table outranks the spec
  6.  generation_stage    — database + backend + design IN PARALLEL
  6b. database_executor   — deterministic, zero-LLM: executes database_agent's SQL
  7.  fixer               — post-generation deterministic fixers (SQL, Python, TS)
  8.  frontend            — generate TSX / CSS / app patches
  9.  review_fix_loop     — reviewer → exit_check → review_fixer (up to 3×)
  10. pr                  — deterministic gate (agents/pr_gate.py) then push to GitHub, open PRs
"""
from google.adk.agents import SequentialAgent, ParallelAgent, LoopAgent

from agents.host_architect       import host_architect_agent
from agents.prd_parser          import prd_parser_agent
from agents.prd_enricher        import prd_enricher_agent
from agents.schema_analyst      import schema_analyst_agent
from agents.architect           import architect_agent
from agents.decision_gate       import decision_gate_agent
from agents.spec_reconciler     import spec_reconciler_agent
from agents.database            import database_agent
from agents.database_executor   import database_executor_agent
from agents.backend             import backend_agent
from agents.design_consistency  import design_consistency_agent
from agents.fixer               import fixer_agent
from agents.frontend            import frontend_agent
from agents.reviewer            import reviewer_agent
from agents.loop_exit           import loop_exit_agent
from agents.review_fixer        import review_fixer_agent
from agents.pr                  import pr_agent
from agents.pr_gate             import make_pr_gate_agent
from agents.retry               import RetryUntilUsable, has_backend_files, has_frontend_files, has_specification

# Step 6: database, backend, and design_consistency are independent — run concurrently.
# backend_agent unchanged, but a MALFORMED_FUNCTION_CALL / empty turn no
# longer fails the whole run: the stage is retried (max 3) until
# backend_artifacts carries module + route files. See agents/retry.py.
backend_stage = RetryUntilUsable(
    name="backend_stage",
    description="backend_agent with bounded retries on unusable output",
    sub_agents=[backend_agent],
    output_key="backend_artifacts",
    is_usable=has_backend_files,
)

architect_stage = RetryUntilUsable(
    name="architect_stage",
    description="architect_agent with bounded retries until a usable specification exists",
    sub_agents=[architect_agent],
    output_key="specification",
    is_usable=has_specification,
)

generation_stage = ParallelAgent(
    name="generation_stage",
    description="Concurrent SQL, Python, and design extraction",
    sub_agents=[
        database_agent,
        backend_stage,
        design_consistency_agent,
    ],
)

# Step 9: Review → check if done → fix → repeat (max 3 iterations).
# Loop order: reviewer scores artifacts → loop_exit escalates if passed →
#             review_fixer applies targeted fixes → reviewer re-scores.
review_fix_loop = LoopAgent(
    name="review_fix_loop",
    description="Iterative review-and-fix cycle until artifacts pass or max iterations",
    max_iterations=3,
    sub_agents=[
        reviewer_agent,
        loop_exit_agent,
        review_fixer_agent,
    ],
)

frontend_stage = RetryUntilUsable(
    name="frontend_stage",
    description="frontend_agent with bounded retries on empty output",
    sub_agents=[frontend_agent],
    output_key="frontend_artifacts",
    is_usable=has_frontend_files,
)

# Step 10: deterministic hard gate -- pr_agent only actually runs (and can
# only push to the real repos) when gate_result.status == "APPROVED" and
# review_result.passed is literally True, checked in Python rather than
# trusted to the LLM's own prompt instructions. See agents/pr_gate/.
pr_stage = make_pr_gate_agent(pr_agent)

root_agent = SequentialAgent(
    name="posgmo_factory",
    description="POS GMO Software Factory",
    sub_agents=[
        host_architect_agent,    # 0
        prd_parser_agent,        # 1
        prd_enricher_agent,      # 2
        schema_analyst_agent,    # 3
        architect_stage,         # 4  (architect_agent, retried -- agents/retry.py)
        decision_gate_agent,     # 5
        spec_reconciler_agent,   # 5b — deterministic: live table outranks the spec (agents/spec_reconciler)
        generation_stage,        # 6
        database_executor_agent, # 6b — must run after generation_stage: reads database_agent's output
        fixer_agent,             # 7
        frontend_stage,          # 8  (frontend_agent, retried -- agents/retry.py)
        review_fix_loop,         # 9  ← iterative loop
        pr_stage,                # 10 (pr_agent, hard-gated -- agents/pr_gate.py)
    ],
)
