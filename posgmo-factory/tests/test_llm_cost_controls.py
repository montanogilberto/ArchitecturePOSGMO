"""Cost controls: model routing, cache-friendly prompt order, usage accounting."""
from types import SimpleNamespace

from google.genai.types import GenerateContentResponseUsageMetadata as Usage

from agents.models import CODE_MODEL, LIGHT_MODEL
from llm_usage import UsageTracker


def _instruction(agent, state):
    return agent.instruction(SimpleNamespace(state=state))


def test_code_agents_use_code_model_and_light_agents_use_light_model():
    from agents.architect.agent import architect_agent
    from agents.backend.agent import backend_agent
    from agents.database.agent import database_llm_agent
    from agents.design_consistency.agent import design_consistency_agent
    from agents.frontend.agent import frontend_agent
    from agents.host_architect.agent import host_architect_agent
    from agents.pr.agent import pr_agent
    from agents.prd_enricher.agent import prd_enricher_agent
    from agents.prd_parser.agent import prd_parser_agent
    from agents.schema_analyst.agent import schema_analyst_agent

    for a in (architect_agent, prd_enricher_agent, database_llm_agent, backend_agent, frontend_agent, pr_agent):
        assert a.model == CODE_MODEL, a.name
    for a in (host_architect_agent, prd_parser_agent, schema_analyst_agent, design_consistency_agent):
        assert a.model == LIGHT_MODEL, a.name


def test_per_run_state_comes_after_static_knowledge():
    """Implicit prefix caching only reuses an identical prefix: two runs with
    different state must share everything up to the state blocks."""
    from agents.backend.agent import backend_agent
    from agents.database.agent import database_llm_agent
    from agents.frontend.agent import frontend_agent

    for agent in (backend_agent, frontend_agent, database_llm_agent):
        a = _instruction(agent, {"specification": '{"db":{"table_name":"suppliers"}}', "gate_result": "{}"})
        b = _instruction(agent, {"specification": '{"db":{"table_name":"clients"}}', "gate_result": '{"tier":1}'})
        state_at = a.index("## Current `")
        assert a.index("## Pre-loaded knowledge") < state_at, agent.name
        shared = next(i for i, (x, y) in enumerate(zip(a, b)) if x != y)
        assert shared / len(a) > 0.9, agent.name


def test_usage_tracker_prices_cache_and_thinking():
    t = UsageTracker()
    t.observe(SimpleNamespace(author="backend_agent", model_version="gemini-2.5-flash", usage_metadata=Usage(
        prompt_token_count=1_000_000, cached_content_token_count=800_000,
        candidates_token_count=100_000, thoughts_token_count=100_000)))
    t.observe(SimpleNamespace(author="prd_parser_agent", model_version="gemini-2.5-flash-lite-001",
                              usage_metadata=Usage(prompt_token_count=1_000_000, candidates_token_count=0)))
    t.observe(SimpleNamespace(author="reviewer_agent", usage_metadata=None))  # pure-Python stage

    s = t.summary()
    # flash: 200k*0.30 + 800k*0.03 + 200k*2.50 = 0.06 + 0.024 + 0.50; lite: 1M*0.10
    assert s["est_cost_usd"] == round(0.584 + 0.10, 4)
    assert s["total"]["calls"] == 2
    assert s["total"]["cache_hit_ratio"] == 0.4
    assert s["unpriced_models"] == []


def test_frontend_agent_uses_json_mode():
    from agents.frontend.agent import frontend_agent

    assert frontend_agent.generate_content_config.response_mime_type == "application/json"
    assert not frontend_agent.tools  # JSON mode is only valid on a tool-less agent


def test_describe_unusable_names_the_cause():
    from agents.retry import describe_unusable

    assert describe_unusable(None) == "empty"
    assert describe_unusable('{"page_file": {}}') == "JSON parsed but required content missing"
    assert describe_unusable('{"page_file": "a\\q"}').startswith("invalid JSON: Invalid \\escape")
    assert describe_unusable("Here is the JSON: {}").startswith("invalid JSON")
