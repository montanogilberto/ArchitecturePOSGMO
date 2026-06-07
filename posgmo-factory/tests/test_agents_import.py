"""
Smoke tests — verifies all agent modules import cleanly and expose
the expected agent objects with correct names and output_keys.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_architect_agent_importable():
    from agents.architect_agent import architect_agent
    assert architect_agent.name == "architect_agent"
    assert architect_agent.output_key == "specification"


def test_database_agent_importable():
    from agents.database_agent import database_agent
    assert database_agent.name == "database_agent"
    assert database_agent.output_key == "database_artifacts"


def test_backend_agent_importable():
    from agents.backend_agent import backend_agent
    assert backend_agent.name == "backend_agent"
    assert backend_agent.output_key == "backend_artifacts"


def test_frontend_agent_importable():
    from agents.frontend_agent import frontend_agent
    assert frontend_agent.name == "frontend_agent"
    assert frontend_agent.output_key == "frontend_artifacts"


def test_reviewer_agent_importable():
    from agents.reviewer_agent import reviewer_agent
    assert reviewer_agent.name == "reviewer_agent"
    assert reviewer_agent.output_key == "review_result"


def test_pr_agent_importable():
    from agents.pr_agent import pr_agent
    assert pr_agent.name == "pr_agent"
    assert pr_agent.output_key == "pr_result"


def test_orchestrator_pipeline_importable():
    from orchestrator import factory_pipeline
    agent_names = [a.name for a in factory_pipeline.sub_agents]
    assert "architect_agent"  in agent_names
    assert "parallel_codegen" in agent_names
    assert "frontend_agent"   in agent_names
    assert "reviewer_agent"   in agent_names
    assert "pr_agent"         in agent_names


def test_parallel_codegen_contains_db_and_backend():
    from orchestrator import _parallel_codegen
    names = [a.name for a in _parallel_codegen.sub_agents]
    assert "database_agent" in names
    assert "backend_agent"  in names
