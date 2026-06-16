"""PRD Enricher — tool functions."""
from __future__ import annotations

import json

from google.adk.tools.tool_context import ToolContext


def save_enriched_prd(enriched_prd: dict, tool_context: ToolContext) -> dict:
    """
    Saves the domain-enriched PRD to session state so the Architect
    can read it instead of the raw user-supplied PRD.

    Args:
        enriched_prd: The full enriched PRD dict — original fields merged
                      with domain context (workflow, business_rules, ui_hints,
                      suggested_fields, validation_rules).

    Returns:
        Confirmation dict.
    """
    tool_context.state["enriched_prd"] = json.dumps(enriched_prd)
    module = enriched_prd.get("module", "?")
    tier   = enriched_prd.get("domain_context", {}).get("tier", "?")
    wf     = enriched_prd.get("domain_context", {}).get("workflow", {})
    states = wf.get("states", [])
    print(
        f"[prd_enricher] saved enriched_prd — module={module} tier={tier} "
        f"workflow_states={len(states)}",
        flush=True,
    )
    return {"status": "saved", "module": module, "tier": tier}
