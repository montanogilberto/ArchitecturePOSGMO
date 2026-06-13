"""
POS GMO AI Factory — Pipeline Assembly

Imports all agents from their subpackages and assembles the root_agent
SequentialAgent with the full 9-step pipeline.
"""
from google.adk.agents import SequentialAgent, ParallelAgent

from agents.prd_parser        import prd_parser_agent
from agents.schema_analyst    import schema_analyst_agent
from agents.architect         import architect_agent
from agents.decision_gate     import decision_gate_agent
from agents.database          import database_agent
from agents.backend           import backend_agent
from agents.design_consistency import design_consistency_agent
from agents.fixer             import fixer_agent
from agents.frontend          import frontend_agent
from agents.reviewer          import reviewer_agent
from agents.pr                import pr_agent

# database, backend, and design_consistency are independent of each other
# and run concurrently inside the generation stage.
generation_stage = ParallelAgent(
    name="generation_stage",
    description="Concurrent SQL, Python, and design extraction",
    sub_agents=[
        database_agent,            # generates + executes SQL
        backend_agent,             # generates Python modules + routes
        design_consistency_agent,  # fetches real pages -> design_brief
    ],
)

root_agent = SequentialAgent(
    name="posgmo_factory",
    description="POS GMO Software Factory",
    sub_agents=[
        prd_parser_agent,      # 1. parse PRD -> session state vars
        schema_analyst_agent,  # 2. query live DB -> schema_analysis
        architect_agent,       # 3. design spec using real schema data
        decision_gate_agent,   # 4. deterministic tier + constraint classification
        generation_stage,      # 5. database + backend + design IN PARALLEL
        fixer_agent,           # 6. deterministic artifact fixers (SQL, Python, TS)
        frontend_agent,        # 7. generate TSX/CSS
        reviewer_agent,        # 8. score all artifacts
        pr_agent,              # 9. push to GitHub + open PRs
    ],
)