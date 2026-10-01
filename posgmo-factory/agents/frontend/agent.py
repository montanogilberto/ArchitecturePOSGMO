"""Frontend Agent definition."""
from google.adk.agents import Agent
from google.genai import types
from agents.models import CODE_MODEL
from agents.preloaded_knowledge import with_preloaded_knowledge
from agents.frontend.prompt import INSTRUCTION

frontend_agent = Agent(
    name="frontend_agent",
    description=(
        "Generates the Ionic React API client, page component, CSS, and App.tsx patches "
        "for this module, applying all existing UI patterns (UTC-7, IVA=0, infinite scroll). "
        "This platform is multi-product (POS, SmartLoans, Rewards, Arcade, Factory GMO's own "
        "commercial app, and others) -- the module being built is not necessarily POS-specific; "
        "read gate_result/specification for what this run actually needs, not an assumed product line."
    ),
    model=CODE_MODEL,
    # Targeted context: frontend/prompt.py names exactly four required inputs
    # -- gate_result, specification, design_brief, and backend_artifacts
    # ("for interface alignment") -- nothing about earlier conversation.
    instruction=with_preloaded_knowledge(
        INSTRUCTION, ["gate_result", "specification", "design_brief", "backend_artifacts"],
        ["get_generation_rules", "get_frontend_patterns", "get_ui_patterns",
         "get_api_contracts", "get_component_catalog"],
        agent_name="frontend_agent",
    ),
    include_contents="none",
    # No tools: knowledge is pre-loaded (agents/preloaded_knowledge.py), same
    # change as backend_agent/architect_agent (Step 1 construction reliability).
    tools=[],
    # JSON mode: the prompt says "no markdown fences", yet 5/5 replays still
    # fenced the ~22k-char JSON, and 2/8 real calls (2026-09-24) produced ~7k
    # output tokens each that failed to parse -> retries were 68% of that
    # run's cost. Constrained decoding makes every reply parseable JSON.
    # Allowed only because this agent has no tools.
    generate_content_config=types.GenerateContentConfig(response_mime_type="application/json"),
    output_key="frontend_artifacts",
)