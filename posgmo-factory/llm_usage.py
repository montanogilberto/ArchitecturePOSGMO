"""
Per-run LLM token usage and estimated cost.

The Gemini bill (2026-09) was ~MXN 460 in one week, driven by ~17M input
tokens/day during Step 1 reliability batches, with no way to see from a run
which agent spent them or whether the implicit prefix cache was hitting.
This module aggregates every model response's usage_metadata by agent as
events stream past (orchestrator.run_factory, scripts/step1_reliability.py).

Purely additive: never blocks, retries, or changes agent behavior.

Prices: USD per 1M tokens, Gemini API paid tier (ai.google.dev pricing,
checked 2026-09-24). Thinking tokens are billed at the output rate.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

PRICES_PER_M = {
    # model prefix: (input, cached input, output)
    "gemini-2.5-flash-lite": (0.10, 0.01, 0.40),
    "gemini-3.1-flash-lite": (0.25, 0.025, 1.50),
    "gemini-2.5-flash": (0.30, 0.03, 2.50),
}
_COUNTERS = ("calls", "prompt", "cached", "output", "thoughts")


def _price(model: str) -> tuple[float, float, float] | None:
    # Longest prefix first, so "flash-lite" never matches as plain "flash".
    for prefix in sorted(PRICES_PER_M, key=len, reverse=True):
        if (model or "").startswith(prefix):
            return PRICES_PER_M[prefix]
    return None


class UsageTracker:
    def __init__(self) -> None:
        self._by_agent: dict[tuple[str, str], dict[str, int]] = defaultdict(
            lambda: dict.fromkeys(_COUNTERS, 0)
        )

    def observe(self, event: Any) -> None:
        usage = getattr(event, "usage_metadata", None)
        if usage is None:
            return
        row = self._by_agent[(getattr(event, "author", "") or "?", getattr(event, "model_version", "") or "?")]
        row["calls"] += 1
        row["prompt"] += usage.prompt_token_count or 0
        row["cached"] += usage.cached_content_token_count or 0
        row["output"] += usage.candidates_token_count or 0
        row["thoughts"] += usage.thoughts_token_count or 0

    def summary(self) -> dict:
        agents, total = [], dict.fromkeys(_COUNTERS, 0)
        total_cost, unpriced = 0.0, set()
        for (agent, model), row in sorted(self._by_agent.items()):
            price = _price(model)
            cost = None
            if price:
                in_p, cached_p, out_p = price
                cost = ((row["prompt"] - row["cached"]) * in_p + row["cached"] * cached_p
                        + (row["output"] + row["thoughts"]) * out_p) / 1e6
                total_cost += cost
            else:
                unpriced.add(model)
            agents.append({"agent": agent, "model": model, **row,
                           "cost_usd": round(cost, 4) if cost is not None else None})
            for k in _COUNTERS:
                total[k] += row[k]
        total["cache_hit_ratio"] = round(total["cached"] / total["prompt"], 3) if total["prompt"] else 0.0
        return {"total": total, "est_cost_usd": round(total_cost, 4),
                "unpriced_models": sorted(unpriced), "agents": agents}


def format_summary(summary: dict) -> str:
    t = summary["total"]
    lines = [f"[usage] calls={t['calls']} input={t['prompt']:,} cached={t['cached']:,} "
             f"({t['cache_hit_ratio']:.0%}) output={t['output']:,} thinking={t['thoughts']:,} "
             f"est_cost=${summary['est_cost_usd']:.4f}"]
    for a in summary["agents"]:
        lines.append(f"[usage]   {a['agent']:<26} {a['model']:<24} calls={a['calls']:<3} "
                     f"input={a['prompt']:>9,} cached={a['cached']:>9,} out={a['output']:>7,} "
                     f"think={a['thoughts']:>7,} ${a['cost_usd'] if a['cost_usd'] is not None else '?'}")
    return "\n".join(lines)
