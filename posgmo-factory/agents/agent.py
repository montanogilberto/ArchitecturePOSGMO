"""
POS GMO AI Factory — Pipeline Assembly

Imports all agents from their subpackages and assembles the root_agent
SequentialAgent with the full pipeline.

Pipeline stages:
  1.  prd_parser          — parse PRD JSON → session state vars
  2.  prd_enricher        — inject domain context → enriched_prd
  3.  schema_analyst      — query live DB → schema_analysis
  4.  architect           — design SpecificationJSON from enriched_prd + schema
  5.  decision_gate       — deterministic tier + constraint classification
  6.  generation_stage    — database + backend + design IN PARALLEL
  7.  fixer               — post-generation deterministic fixers (SQL, Python, TS)
  8.  frontend            — generate TSX / CSS / app patches
  9.  review_fix_loop     — reviewer → exit_check → review_fixer (up to 3×)
  10. pr                  — push to GitHub, open PRs
"""
from google.adk.agents import SequentialAgent, ParallelAgent, LoopAgent

from agents.prd_parser          import prd_parser_agent
from agents.prd_enricher        import prd_enricher_agent
from agents.schema_analyst      import schema_analyst_agent
from agents.architect           import architect_agent
from agents.decision_gate       import decision_gate_agent
from agents.database            import database_agent
from agents.backend             import backend_agent
from agents.design_consistency  import design_consistency_agent
from agents.fixer               import fixer_agent
from agents.frontend            import frontend_agent
from agents.reviewer            import reviewer_agent
from agents.loop_exit           import loop_exit_agent
from agents.review_fixer        import review_fixer_agent
from agents.pr                  import pr_agent

# Step 6: database, backend, and design_consistency are independent — run concurrently.
generation_stage = ParallelAgent(
    name="generation_stage",
    description="Concurrent SQL, Python, and design extraction",
    sub_agents=[
        database_agent,
        backend_agent,
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

root_agent = SequentialAgent(
    name="posgmo_factory",
    description="POS GMO Software Factory",
    sub_agents=[
        prd_parser_agent,      # 1
        prd_enricher_agent,    # 2
        schema_analyst_agent,  # 3
        architect_agent,       # 4
        decision_gate_agent,   # 5
        generation_stage,      # 6
        fixer_agent,           # 7
        frontend_agent,        # 8
        review_fix_loop,       # 9  ← iterative loop
        pr_agent,              # 10
    ],
)
