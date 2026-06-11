from google.adk.agents import SequentialAgent, ParallelAgent

from agents.prd_parser_agent import prd_parser_agent
from agents.schema_analyst_agent import schema_analyst_agent
from agents.architect_agent import architect_agent
from agents.decision_gate_agent import decision_gate_agent
from agents.database_agent import database_agent
from agents.backend_agent import backend_agent
from agents.design_consistency_agent import design_consistency_agent
from agents.frontend_agent import frontend_agent
from agents.reviewer_agent import reviewer_agent
from agents.pr_agent import pr_agent

# database, backend, and design_consistency only depend on gate_result + specification
# — they are independent of each other and can run concurrently.
generation_stage = ParallelAgent(
    name="generation_stage",
    description="Concurrent SQL, Python, and design extraction",
    sub_agents=[
        database_agent,            # generates + executes SQL
        backend_agent,             # generates Python modules + routes
        design_consistency_agent,  # fetches real pages → design_brief
    ],
)

root_agent = SequentialAgent(
    name="posgmo_factory",
    description="POS GMO Software Factory",
    sub_agents=[
        prd_parser_agent,    # 1. parse PRD → session state vars
        schema_analyst_agent, # 2. query live DB → schema_analysis
        architect_agent,      # 3. design spec using real schema data
        decision_gate_agent,  # 4. classify tier, hard-block, emit constraints
        generation_stage,     # 5. database + backend + design IN PARALLEL
        frontend_agent,       # 6. generate TSX/CSS (needs backend_artifacts + design_brief)
        reviewer_agent,       # 7. score all artifacts
        pr_agent,             # 8. push to GitHub + open PRs
    ],
)