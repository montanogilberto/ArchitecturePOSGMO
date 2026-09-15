"""
Context Agent — deterministic (zero LLM calls). Populates the blackboard's
context_verified_facts / context_assumptions BEFORE any expert proposes.

This is the doc's "Existing system first -> Reuse -> Extend -> Only then
Create" rule made mechanical: experts must argue from what actually exists
on disk, not from a guess. Phase 2 scope is filesystem-only (this repo's
tests/*.json PRD filenames + the architecture knowledge JSON files) — no
live DB, no GitHub API. Those belong to the fuller Context/Repository
Analyst in a later phase.

gather_context() is a pure function (no ADK dependency) so it is directly
unit-testable against the real repo state — see tests/test_debate_v2_context.py.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import AsyncGenerator, List, Tuple

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions

from debate_schema import ContextItem, ContextItemKind
from debate_v2.context_graph import check_domain_has_no_matching_table, check_referenced_parent_tables

_FACTORY_ROOT = Path(__file__).resolve().parent.parent      # posgmo-factory/
_KNOWLEDGE_ROOT = _FACTORY_ROOT.parent                        # repo root

_STOPWORDS = {"create", "a", "an", "the", "new", "module", "for", "add", "build", "make", "implement"}

# Real POS GMO domain vocabulary (CLAUDE.md's Business Domains table +
# doc-adjacent terms). A request naming several of these — e.g. "Clients,
# POS sales/tickets, Incomes, Expenses, Accounting, Payments..." — must be
# evidence-checked against EACH domain it touches, not just the last word
# in the sentence (that heuristic was fine for a single-module request but
# silently drops everything except the last noun for a multi-domain one).
_KNOWN_DOMAIN_TERMS = [
    "client", "ticket", "income", "expense", "accounting", "payment",
    "product", "reward", "notification", "cashregister", "chat",
]


def _extract_keywords(request: str) -> List[str]:
    """Returns every known domain term the request mentions, in vocabulary
    order. Falls back to the old single-last-word heuristic when nothing
    from the known vocabulary matches, so an arbitrary/unlisted domain
    (e.g. a genuinely new one) still gets checked instead of silently
    producing zero evidence."""
    text = request.lower()
    matches = [term for term in _KNOWN_DOMAIN_TERMS if term in text]
    if matches:
        return matches
    words = re.findall(r"[a-zA-Z]+", text)
    candidates = [w for w in words if w not in _STOPWORDS]
    fallback = candidates[-1] if candidates else (words[-1] if words else "")
    return [fallback] if fallback else []


def gather_context(request: str) -> Tuple[List[ContextItem], List[ContextItem]]:
    """Returns (verified_facts, assumptions) merged across every domain
    keyword the request touches. Every verified_fact traces to something
    actually read from disk in THIS call — nothing is asserted without a
    `source` citation."""
    keywords = _extract_keywords(request)
    if not keywords:
        return [], [ContextItem(
            kind=ContextItemKind.assumption,
            claim="Could not extract a domain keyword from the request; nothing was verified.",
        )]

    verified: List[ContextItem] = []
    assumptions: List[ContextItem] = []
    for keyword in keywords:
        v, a = _gather_for_keyword(keyword)
        verified.extend(v)
        assumptions.extend(a)
    return verified, assumptions


def _gather_for_keyword(keyword: str) -> Tuple[List[ContextItem], List[ContextItem]]:
    verified: List[ContextItem] = []
    assumptions: List[ContextItem] = []

    # 1) Draft PRDs already prepared for this keyword. Match case-insensitively
    # and against the singular stem too (filenames use camelCase singulars,
    # e.g. 'posRewardBalance.json' for the request keyword 'rewards').
    singular = keyword[:-1] if keyword.endswith("s") and len(keyword) > 3 else keyword
    tests_dir = _FACTORY_ROOT / "tests"
    matching_prds = (
        sorted(p.name for p in tests_dir.glob("prd_*.json") if singular in p.name.lower())
        if tests_dir.exists() else []
    )
    parent_module_names: List[str] = []
    if matching_prds:
        verified.append(ContextItem(
            kind=ContextItemKind.verified_fact,
            claim=f"{len(matching_prds)} draft PRD file(s) already exist for '{keyword}': "
                  f"{', '.join(matching_prds)}.",
            source="repo:posgmo-factory/tests/",
        ))
        for name in matching_prds:
            try:
                data = json.loads((tests_dir / name).read_text(encoding="utf-8"))
            except Exception:
                continue
            desc = data.get("description", "")
            if re.search(r"existing|separate|no shared key", desc, re.IGNORECASE):
                verified.append(ContextItem(
                    kind=ContextItemKind.verified_fact,
                    claim=f"{name} description explicitly calls out an existing/adjacent "
                          f"concept: \"{desc}\"",
                    source=f"repo:posgmo-factory/tests/{name}",
                ))
            for rel in data.get("relationships", []):
                parent = rel.get("parentModule") if isinstance(rel, dict) else rel
                if parent:
                    parent_module_names.append(parent)
    else:
        assumptions.append(ContextItem(
            kind=ContextItemKind.assumption,
            claim=f"No draft PRD files found under tests/ matching '{keyword}' — assuming no "
                  f"prior design work exists (unverified: naming could differ).",
        ))

    # 2) Has this keyword already gone through the factory (generated output)?
    generated_hit = any(
        (_FACTORY_ROOT / sub).exists()
        and any(singular in p.name.lower() for p in (_FACTORY_ROOT / sub).rglob("*"))
        for sub in ("generated", "local_export", "pr_export")
    )
    verified.append(ContextItem(
        kind=ContextItemKind.verified_fact,
        claim=(f"Generated output already exists for '{keyword}' under generated/, "
               f"local_export/, or pr_export/." if generated_hit else
               f"No generated output exists yet for '{keyword}' in generated/, local_export/, "
               f"or pr_export/."),
        source="repo:posgmo-factory/{generated,local_export,pr_export}/",
    ))

    # 3) Is this keyword documented in the architecture knowledge base?
    knowledge_hits: List[str] = []
    for sub in ("Backend", "Frontend", "Database"):
        d = _KNOWLEDGE_ROOT / sub
        if not d.exists():
            continue
        for f in d.glob("*"):
            if not f.is_file():
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if singular in text.lower():
                knowledge_hits.append(f"{sub}/{f.name}")
    if knowledge_hits:
        verified.append(ContextItem(
            kind=ContextItemKind.verified_fact,
            claim=f"'{keyword}' is mentioned in the architecture knowledge base: "
                  f"{', '.join(knowledge_hits)}.",
            source="knowledge:" + ",".join(knowledge_hits),
        ))
    else:
        assumptions.append(ContextItem(
            kind=ContextItemKind.assumption,
            claim=f"'{keyword}' is not documented in any Backend/Frontend/Database knowledge "
                  f"file — assuming it is not an established business domain yet (unverified: "
                  f"the knowledge base may simply be incomplete).",
        ))

    # 4) Phase 3 — cross-check against the CANONICAL live-tracked schema
    # (Database/structure_database.csv + sql_relationships.json), rather
    # than trusting a draft PRD's own prose about what "already exists".
    verified.append(check_domain_has_no_matching_table(singular))
    if parent_module_names:
        for item in check_referenced_parent_tables(parent_module_names):
            (verified if item.kind == ContextItemKind.verified_fact else assumptions).append(item)

    return verified, assumptions


class ContextAgent(BaseAgent):
    """Deterministic evidence gatherer — zero LLM calls. Runs first, before
    any expert proposes (acceptance criterion #2: evidence before judgment)."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        request = ctx.session.state.get("request", "")
        verified, assumptions = gather_context(request)

        vf_list = json.loads(ctx.session.state.get("context_verified_facts") or "[]")
        vf_list.extend(item.model_dump(mode="json") for item in verified)
        as_list = json.loads(ctx.session.state.get("context_assumptions") or "[]")
        as_list.extend(item.model_dump(mode="json") for item in assumptions)

        print(f"[context_agent] verified_facts={len(verified)} assumptions={len(assumptions)}", flush=True)

        yield Event(
            author=self.name,
            actions=EventActions(state_delta={
                "context_verified_facts": json.dumps(vf_list),
                "context_assumptions": json.dumps(as_list),
            }),
        )
