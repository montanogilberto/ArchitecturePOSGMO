from google.adk.agents import SequentialAgent

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

root_agent = SequentialAgent(
    name="posgmo_factory",
    description="POS GMO Software Factory",
    sub_agents=[
        prd_parser_agent,          # 1. parse PRD → session state vars
        schema_analyst_agent,      # 2. query live DB → db_context + schema_analysis
        architect_agent,           # 3. design spec using real schema data
        decision_gate_agent,       # 4. classify tier, hard-block, emit constraints
        database_agent,            # 5. generate + execute SQL
        backend_agent,             # 5. generate Python modules + routes
        design_consistency_agent,  # 6. fetch real pages → design_context + design_brief
        frontend_agent,            # 7. generate TSX/CSS matching real codebase style
        reviewer_agent,            # 8. score all artifacts
        pr_agent,                  # 9. push to GitHub + open PRs
    ],
)