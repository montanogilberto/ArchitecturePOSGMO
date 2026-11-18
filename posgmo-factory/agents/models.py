"""
Model routing for the factory's LLM agents -- one place to change models.

CODE_MODEL: agents whose output is a spec or generated code (architect,
prd_enricher, database_llm, backend, frontend) and pr_agent, whose multi-step
GitHub tool sequence must not malform. Quality here saves retries.

LIGHT_MODEL: agents that classify, call one tool, or extract (host_architect,
prd_parser, schema_analyst, design_consistency) -- cheaper input and output
than Flash. gemini-2.5-flash-lite would be cheaper still but returns 404
"no longer available to new users" for this project (2026-09-24).

reviewer / gates / fixers / loop_exit / spec_reconciler are pure Python
(zero LLM calls) and do not appear here.

Override per environment without code changes, e.g. to revert the split:
    FACTORY_LIGHT_MODEL=gemini-2.5-flash python orchestrator.py ...
"""
from __future__ import annotations

import os

CODE_MODEL = os.getenv("FACTORY_CODE_MODEL", "gemini-2.5-flash")
LIGHT_MODEL = os.getenv("FACTORY_LIGHT_MODEL", "gemini-3.1-flash-lite")
