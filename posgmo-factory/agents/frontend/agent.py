"""Frontend Agent definition."""
from google.adk.agents import Agent
from agents.mcp_tools import get_mcp_toolset
from agents.frontend.prompt import INSTRUCTION

frontend_agent = Agent(
    name="frontend_agent",
    description=(
        "Generates the Ionic React API client, page component, CSS, and App.tsx patches "
        "for a POS GMO module, applying all existing UI patterns (UTC-7, IVA=0, infinite scroll)."
    ),
    model="gemini-2.5-flash",
    instruction=INSTRUCTION,
    tools=[get_mcp_toolset()],
    output_key="frontend_artifacts",
)