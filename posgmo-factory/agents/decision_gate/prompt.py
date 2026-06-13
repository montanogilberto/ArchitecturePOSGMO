"""
Decision Gate — no LLM prompt.

This agent is a pure-Python BaseAgent. It runs compute_gate_result()
directly and writes gate_result to session state via Event state_delta.
No instruction string is passed to an LLM.
"""

DESCRIPTION = (
    "Deterministic quality gate: classifies module tier (TIER_1_CATALOG "
    "through TIER_4_IOT), detects backend pattern (CRUD_ONLY vs "
    "CRUD_AND_CONNECTOR), emits mandatory_constraints. Pure Python — "
    "zero LLM classification."
)