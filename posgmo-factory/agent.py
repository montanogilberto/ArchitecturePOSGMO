"""
POS GMO AI Factory — standalone entry point for `adk web`.

ADK's app discovery expects <agents_dir>/<app_name>/agent.py (with a
root_agent) directly, or root_agent.yaml. root_agent has always lived one
level deeper, at agents/agent.py (see CLAUDE.md's "Factory Code
Architecture") — this file bridges that gap the same way prd-builder/
agent.py already does for the prd_builder_agent app. Never existed before;
selecting "posgmo-factory" in the dev UI's app dropdown and sending a
message hit exactly this: "No root_agent found for 'posgmo-factory'."

This exposes the REAL root_agent -- the full pipeline INCLUDING pr_agent,
not the sandboxed run_local_export.py version every automated run in this
project's history has used. A session against this app that completes
successfully through pr_agent will attempt a real GitHub push. That's the
correct behavior for this entry point (it's the same root_agent
orchestrator.py's real run_factory() uses) -- just worth knowing before
running a full PRD through it interactively.

Usage:
    cd /Users/apple12/Agent_POSGMO
    adk web
    (select "posgmo-factory" from the app dropdown)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from agents import root_agent  # noqa: E402
