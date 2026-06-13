"""Backend Agent definition."""
from google.adk.agents import Agent
from agents.mcp_tools import get_mcp_toolset
from agents.backend.prompt import INSTRUCTION

backend_agent = Agent(
    name="backend_agent",
    description=(
        "Generates modules/{plural}.py (SP business logic) and routes_/{module}.py "
        "(FastAPI router) for a POS GMO module, following the existing pyodbc + JSONResponse pattern."
    ),
    model="gemini-2.5-flash",
    instruction=INSTRUCTION,
    tools=[get_mcp_toolset()],
    output_key="backend_artifacts",
)