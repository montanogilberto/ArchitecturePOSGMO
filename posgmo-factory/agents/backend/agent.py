"""Backend Agent definition."""
from google.adk.agents import Agent
from agents.mcp_tools import get_mcp_toolset
from agents.backend.prompt import INSTRUCTION
from agents.state_injection import with_state

backend_agent = Agent(
    name="backend_agent",
    description=(
        "Generates modules/{plural}.py (SP business logic) and routes_/{module}.py "
        "(FastAPI router) for a POS GMO module, following the existing pyodbc + JSONResponse pattern."
    ),
    model="gemini-2.5-flash",
    # Targeted context: backend/prompt.py declares "gate_result" and
    # "specification" as its required inputs, nothing else. See
    # database_agent for the full rationale (Experiments 1-4 repeatedly hit
    # MALFORMED_FUNCTION_CALL / empty turns here under full conversation
    # history -- this is the "critical test" agent from Experiment 4).
    instruction=with_state(INSTRUCTION, ["gate_result", "specification"]),
    include_contents="none",
    tools=[get_mcp_toolset()],
    output_key="backend_artifacts",
)