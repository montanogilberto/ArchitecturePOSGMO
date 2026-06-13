"""
agents package

Exposes root_agent (the full factory pipeline) and all individual agents
via their subpackages.
"""
from agents.agent import root_agent

__all__ = ["root_agent"]