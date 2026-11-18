"""Backend Agent definition."""
from google.adk.agents import Agent
from agents.models import CODE_MODEL
from agents.preloaded_knowledge import with_preloaded_knowledge
from agents.backend.prompt import INSTRUCTION

backend_agent = Agent(
    name="backend_agent",
    description=(
        "Generates modules/{plural}.py (SP business logic) and routes_/{module}.py "
        "(FastAPI router) for this module, following the existing pyodbc + JSONResponse "
        "pattern. This platform is multi-product (POS, SmartLoans, Rewards, Arcade, "
        "Factory GMO's own commercial app, and others) -- the module being built is not "
        "necessarily POS-specific; read gate_result/specification for what this run "
        "actually needs, not an assumed product line."
    ),
    model=CODE_MODEL,
    # Targeted context: backend/prompt.py declares "gate_result" and
    # "specification" as its required inputs, nothing else. See
    # database_agent for the full rationale (Experiments 1-4 repeatedly hit
    # MALFORMED_FUNCTION_CALL / empty turns here under full conversation
    # history -- this is the "critical test" agent from Experiment 4).
    instruction=with_preloaded_knowledge(
        INSTRUCTION, ["gate_result", "specification"],
        ["get_generation_rules", "get_backend_patterns", "get_backend_routes", "get_sp_patterns"],
        agent_name="backend_agent",
    ),
    include_contents="none",
    # No tools: knowledge is pre-loaded (agents/preloaded_knowledge.py). Step 1
    # evidence: MALFORMED_FUNCTION_CALL on these calls failed 3/3 retries in a run.
    tools=[],
    output_key="backend_artifacts",
)