"""Architect Agent definition."""
from google.adk.agents import Agent
from agents.mcp_tools import get_mcp_toolset
from agents.architect.prompt import INSTRUCTION

architect_agent = Agent(
    name="architect_agent",
    description=(
        "Reads a PRD JSON, consults the POS GMO knowledge base via MCP, "
        "and produces a SpecificationJSON consumed by all downstream agents."
    ),
    model="gemini-2.5-flash",
    instruction=lambda _ctx: INSTRUCTION,
    tools=[get_mcp_toolset()],
    output_key="specification",
    generate_content_config={"temperature": 0},
)