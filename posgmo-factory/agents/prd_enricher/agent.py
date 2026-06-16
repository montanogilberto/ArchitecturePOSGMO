"""PRD Enricher Agent definition."""
from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from agents.mcp_tools import get_mcp_toolset
from agents.prd_enricher.prompt import INSTRUCTION
from agents.prd_enricher.rules import save_enriched_prd

prd_enricher_agent = Agent(
    name="prd_enricher_agent",
    description=(
        "Enriches a thin PRD with domain context: tier classification, workflow states, "
        "business validation rules, missing standard fields, and UI layout hints. "
        "Runs after PRD Parser and before Schema Analyst."
    ),
    model="gemini-2.5-flash",
    instruction=lambda _ctx: INSTRUCTION,  # lambda bypasses ADK inject_session_state KeyError
    tools=[
        get_mcp_toolset(),
        FunctionTool(func=save_enriched_prd),
    ],
    # output_key omitted — save_enriched_prd writes directly to state["enriched_prd"]
)
