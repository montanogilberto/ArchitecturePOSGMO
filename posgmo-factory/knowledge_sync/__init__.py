"""
Knowledge sync — keeps the Factory's knowledge files in step with the real
GMO repositories, so every module the Factory generates starts from the
CURRENT architecture and style, not a months-old snapshot.

Roadmap: Inventory plan task 1 (docs/gmo-agentic-roadmap.md). Runs before
every Factory run (orchestrator.run_factory) and on demand:

    python -m knowledge_sync            # sync + drift report
    python -m knowledge_sync --check    # report drift only, write nothing

Facts (routes, SPs, schema, components, pages, agents) are extracted
deterministically — no LLM. Curated fields already in the knowledge files
(descriptions, roles, tags) are preserved; entries no longer found are
marked "stale", never silently deleted.
"""
from knowledge_sync.sync import run_before_factory, sync_knowledge

__all__ = ["sync_knowledge", "run_before_factory"]
