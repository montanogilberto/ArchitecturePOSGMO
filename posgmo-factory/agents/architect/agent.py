"""Architect Agent definition."""
from google.adk.agents import Agent
from agents.models import CODE_MODEL
from agents.architect.knowledge import with_architect_knowledge
from agents.architect.prompt import INSTRUCTION

architect_agent = Agent(
    name="architect_agent",
    description=(
        "Reads a PRD JSON, consults the POS GMO knowledge base via MCP, "
        "and produces a SpecificationJSON consumed by all downstream agents."
    ),
    model=CODE_MODEL,
    # Knowledge pre-loaded instead of fetched via MCP tool calls: at
    # temperature 0 a MALFORMED_FUNCTION_CALL reproduced on every retry
    # (Step 1 evidence). See agents/architect/knowledge.py.
    instruction=with_architect_knowledge(INSTRUCTION),
    tools=[],
    output_key="specification",
    generate_content_config={"temperature": 0},
)