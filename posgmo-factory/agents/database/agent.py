"""Database Agent definition."""
from google.adk.agents import Agent
from agents.mcp_tools import get_mcp_toolset
from agents.database.prompt import INSTRUCTION
from agents.state_injection import with_state

database_agent = Agent(
    name="database_agent",
    description=(
        "Generates CREATE TABLE and all stored procedures for this module, as text. "
        "Does not execute them -- see database_executor_agent, which runs immediately "
        "after this one. This platform is multi-product (POS, SmartLoans, Rewards, "
        "Arcade, Factory GMO's own commercial app, and others) -- the module being "
        "built is not necessarily POS-specific; read gate_result/specification for "
        "what this run actually needs, not an assumed product line."
    ),
    model="gemini-2.5-flash",
    # Targeted context: this agent's own prompt says it needs exactly
    # "gate_result" and "specification" from session state (see
    # database/prompt.py) -- nothing about the raw PRD or earlier
    # conversation. Inlining those two keys directly + include_contents='none'
    # gives it exactly that, instead of either the full accumulated
    # conversation (Experiments 1-4: repeated MALFORMED_FUNCTION_CALL here)
    # or nothing (which would starve it of data its own prompt requires).
    instruction=with_state(INSTRUCTION, ["gate_result", "specification"]),
    include_contents="none",
    # No execute_sql_on_server tool here anymore -- see
    # agents/database_executor/agent.py. Investigation (docs/experiment1-
    # leadCapture-evaluation.md) traced this agent's chronic
    # MALFORMED_FUNCTION_CALL failures to the tool call itself: it required
    # serializing four large, quote- and GO-heavy SQL strings as JSON
    # function-call arguments, the highest-friction interface in the
    # pipeline, and made the model write the same SQL twice (once as tool
    # arguments, once again as output_key text). Writing the SQL once, as
    # plain text, removes that failure mode entirely -- execution moves to a
    # separate, deterministic, zero-LLM step.
    tools=[get_mcp_toolset()],
    output_key="database_artifacts",
)