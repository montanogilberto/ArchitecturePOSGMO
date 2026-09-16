"""Frontend Agent definition."""
from google.adk.agents import Agent
from agents.mcp_tools import get_mcp_toolset
from agents.frontend.prompt import INSTRUCTION
from agents.state_injection import with_state

frontend_agent = Agent(
    name="frontend_agent",
    description=(
        "Generates the Ionic React API client, page component, CSS, and App.tsx patches "
        "for this module, applying all existing UI patterns (UTC-7, IVA=0, infinite scroll). "
        "This platform is multi-product (POS, SmartLoans, Rewards, Arcade, Factory GMO's own "
        "commercial app, and others) -- the module being built is not necessarily POS-specific; "
        "read gate_result/specification for what this run actually needs, not an assumed product line."
    ),
    model="gemini-2.5-flash",
    # Targeted context: frontend/prompt.py names exactly four required inputs
    # -- gate_result, specification, design_brief, and backend_artifacts
    # ("for interface alignment") -- nothing about earlier conversation.
    instruction=with_state(INSTRUCTION, ["gate_result", "specification", "design_brief", "backend_artifacts"]),
    include_contents="none",
    tools=[get_mcp_toolset()],
    output_key="frontend_artifacts",
)