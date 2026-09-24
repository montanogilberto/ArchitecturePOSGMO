"""PRD Builder Agent definition — Phase 4 of Factory Knowledge & Experience."""
from google.adk.agents import Agent
from agents.mcp_tools import get_mcp_toolset
from agents.prd_builder.prompt import INSTRUCTION

prd_builder_agent = Agent(
    name="prd_builder_agent",
    description=(
        "Turns a raw, informal request into a PRD JSON the Software "
        "Construction Factory can execute. Researches via "
        "search_factory_experience (past architecture/experience/decisions/"
        "implementations) and MCP's structured getters before writing "
        "anything, so tenant-model and relationship decisions are made "
        "from evidence, not assumed. Asks a clarifying question instead of "
        "guessing when the request is too vague to research."
    ),
    model="gemini-2.5-flash",
    instruction=lambda _ctx: INSTRUCTION,
    tools=[get_mcp_toolset()],
    output_key="prd_builder_output",
)
