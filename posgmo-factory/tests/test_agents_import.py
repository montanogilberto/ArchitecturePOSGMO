"""
Smoke tests -- verifies all agent subpackages import cleanly and expose
the expected agent objects with correct names and output_keys.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_architect_agent_importable():
    from agents.architect import architect_agent
    assert architect_agent.name == "architect_agent"
    assert architect_agent.output_key == "specification"


def test_database_agent_importable():
    from agents.database import database_agent
    assert database_agent.name == "database_agent"
    assert database_agent.output_key == "database_artifacts"


def test_backend_agent_importable():
    from agents.backend import backend_agent
    assert backend_agent.name == "backend_agent"
    assert backend_agent.output_key == "backend_artifacts"


def test_frontend_agent_importable():
    from agents.frontend import frontend_agent
    assert frontend_agent.name == "frontend_agent"
    assert frontend_agent.output_key == "frontend_artifacts"


def test_reviewer_agent_importable():
    from agents.reviewer import reviewer_agent
    assert reviewer_agent.name == "reviewer_agent"
    # reviewer_agent uses output_key=None -- run_review() writes directly to session state


def test_pr_agent_importable():
    from agents.pr import pr_agent
    assert pr_agent.name == "pr_agent"
    assert pr_agent.output_key == "pr_result"


def test_prd_parser_agent_importable():
    from agents.prd_parser import prd_parser_agent
    assert prd_parser_agent.name == "prd_parser_agent"
    assert prd_parser_agent.output_key == "prd_context"


def test_schema_analyst_agent_importable():
    from agents.schema_analyst import schema_analyst_agent
    assert schema_analyst_agent.name == "schema_analyst_agent"
    assert schema_analyst_agent.output_key == "schema_analysis"


def test_decision_gate_agent_importable():
    from agents.decision_gate import decision_gate_agent
    assert decision_gate_agent.name == "decision_gate_agent"


def test_fixer_agent_importable():
    from agents.fixer import fixer_agent
    assert fixer_agent.name == "fixer_agent"


def test_design_consistency_agent_importable():
    from agents.design_consistency import design_consistency_agent
    assert design_consistency_agent.name == "design_consistency_agent"
    assert design_consistency_agent.output_key == "design_brief"


def test_root_agent_pipeline_importable():
    from agents import root_agent
    assert root_agent.name == "posgmo_factory"
    agent_names = [a.name for a in root_agent.sub_agents]
    assert "prd_parser_agent"     in agent_names
    assert "schema_analyst_agent" in agent_names
    assert "architect_agent"      in agent_names
    assert "decision_gate_agent"  in agent_names
    assert "generation_stage"     in agent_names
    assert "fixer_agent"          in agent_names
    assert "frontend_agent"       in agent_names
    assert "reviewer_agent"       in agent_names
    assert "pr_agent"             in agent_names


def test_generation_stage_contains_parallel_agents():
    from agents import root_agent
    gen_stage = next(a for a in root_agent.sub_agents if a.name == "generation_stage")
    sub_names = [a.name for a in gen_stage.sub_agents]
    assert "database_agent"           in sub_names
    assert "backend_agent"            in sub_names
    assert "design_consistency_agent" in sub_names


def test_rules_have_no_adk_agent_imports():
    """Verify rules.py files contain only tool logic, not ADK agent framework imports."""
    import importlib, types
    forbidden = {"Agent", "SequentialAgent", "ParallelAgent", "FunctionTool"}
    packages = [
        "agents.schema_analyst.rules",
        "agents.database.rules",
        "agents.design_consistency.rules",
        "agents.fixer.rules",
        "agents.reviewer.rules",
        "agents.pr.rules",
        "agents.architect.rules",
        "agents.backend.rules",
        "agents.frontend.rules",
        "agents.prd_parser.rules",
    ]
    for pkg in packages:
        mod = importlib.import_module(pkg)
        for name in forbidden:
            assert not hasattr(mod, name), (
                f"{pkg} exports '{name}' — ADK agent classes must stay in agent.py"
            )


def test_prompt_files_export_instruction():
    """Every prompt.py must export INSTRUCTION or _INSTRUCTION."""
    import importlib
    packages = [
        ("agents.prd_parser.prompt",        "INSTRUCTION"),
        ("agents.schema_analyst.prompt",     "INSTRUCTION"),
        ("agents.architect.prompt",          "INSTRUCTION"),
        ("agents.decision_gate.prompt",      "DESCRIPTION"),
        ("agents.database.prompt",           "INSTRUCTION"),
        ("agents.backend.prompt",            "INSTRUCTION"),
        ("agents.design_consistency.prompt", "INSTRUCTION"),
        ("agents.fixer.prompt",              "_INSTRUCTION"),
        ("agents.frontend.prompt",           "INSTRUCTION"),
        ("agents.reviewer.prompt",           "_INSTRUCTION"),
        ("agents.pr.prompt",                 "INSTRUCTION"),
    ]
    for pkg, attr in packages:
        mod = importlib.import_module(pkg)
        assert hasattr(mod, attr), f"{pkg} missing '{attr}'"
        val = getattr(mod, attr)
        assert isinstance(val, str) and len(val) > 20, (
            f"{pkg}.{attr} is not a non-empty string"
        )