"""
Factory Knowledge & Experience -- Phase 1: the Experience collection.

Semantic memory over what the Factory has already learned by actually
RUNNING: milestone findings (docs/commercial-app-milestones.md) and recorded
architecture decisions (decision_registry/ADR-*.json). Deliberately NOT a
replacement for mcp_server's structured getters (schema, SP patterns,
routes) -- those stay exact-match lookups because exact lookup is superior
for facts (see mcp_server/server.py). This is for the opposite case: "has
something like this been tried before," where the wording won't match a
keyword search. _classify_tenant_model's brittle substring signal matching
and the TIER_4 "led"-inside-"controlled" false positive (both found and
fixed in this same session, agents/decision_gate/rules.py) are exactly the
failure mode semantic retrieval is meant to fix -- a differently-worded PRD
describing the same tenancy exception wouldn't match either bug's fixed
keyword list, but should surface the same precedent semantically.

Design principle this module must never violate (stated explicitly by the
user when this was scoped): RAG retrieves evidence, agents reason over it,
MCP/Graph stays the authoritative source of facts, the reviewer verifies the
resulting implementation. This module is not a source of truth -- every
result it returns is a verbatim, sourced excerpt of something already
written to disk (a milestone finding or a recorded ADR); nothing here is
generated or synthesized, so there is no fabrication surface in the
retrieval path itself.

Usage:
    python factory_experience.py --rebuild            # (re)compute the index
    python factory_experience.py --query "..."        # ad-hoc CLI search
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

_ROOT = Path(__file__).parent
_MILESTONES_PATH = _ROOT / "docs" / "commercial-app-milestones.md"
_ADR_DIR = _ROOT / "decision_registry"
_INDEX_PATH = _ROOT / "factory_experience_index.json"
_EMBEDDING_MODEL = "gemini-embedding-001"

_MIN_CHUNK_CHARS = 40  # skip stray short lines / table row fragments
_BOLD_LEAD_RE = re.compile(r"^\*\*([^*]+)\*\*:?\s*")


def _split_finding_context(text: str) -> tuple[str, str]:
    """
    finding: a short, scannable headline for this chunk. context: the full
    chunk text an agent should actually read. Most chunks in this repo's
    established convention open with a **Bold label:** (e.g. "**Bug #2 --
    database batching, root-caused, not patched:**") -- use that verbatim as
    the headline when present; fall back to the first line, truncated, when
    it isn't (e.g. a markdown table fragment).
    """
    m = _BOLD_LEAD_RE.match(text)
    if m:
        finding = m.group(1).strip().rstrip(":").rstrip("—").strip()
        return finding, text
    first_line = text.split("\n", 1)[0].strip()
    return first_line[:150], text


def _chunk_milestones(text: str) -> list[dict]:
    """
    Split commercial-app-milestones.md into per-finding chunks: first by
    '## Milestone N -- ...' section (skips '## Next' and any other
    non-milestone section), then within each milestone by blank-line-
    separated paragraph -- this repo's own established convention for a
    distinct, citable finding within a milestone.
    """
    chunks: list[dict] = []
    sections = re.split(r"\n(?=## )", text)
    for section in sections:
        header_match = re.match(r"## (.+)", section)
        if not header_match:
            continue
        title = header_match.group(1).strip()
        if not title.lower().startswith("milestone"):
            continue
        milestone_label = title.split("—", 1)[0].strip()  # e.g. "Milestone 6"
        body = section[header_match.end():].strip()
        for para in re.split(r"\n\s*\n", body):
            para = para.strip()
            if len(para) < _MIN_CHUNK_CHARS:
                continue
            finding, context = _split_finding_context(para)
            chunks.append({
                "source": "commercial-app-milestones.md",
                "milestone": milestone_label,
                "module": None,
                "type": "experience",
                "finding": finding,
                "context": context,
            })
    return chunks


def _chunk_adrs() -> list[dict]:
    chunks: list[dict] = []
    if not _ADR_DIR.exists():
        return chunks
    for path in sorted(_ADR_DIR.glob("ADR-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        context = " ".join(filter(None, [
            data.get("request", ""),
            data.get("selectedClaim", ""),
            data.get("rationale", ""),
        ]))
        if not context.strip():
            continue
        adr_id = data.get("id", path.stem)
        module = data.get("module")
        chunks.append({
            "source": "decision_registry",
            "milestone": None,
            "module": module,
            "type": "decision",
            "finding": f"{adr_id} — {module}" if module else adr_id,
            "context": context,
        })
    return chunks


def _embed(texts: list[str]) -> list[list[float]]:
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    result = client.models.embed_content(model=_EMBEDDING_MODEL, contents=texts)
    return [e.values for e in result.embeddings]


def _embed_text_for_chunk(chunk: dict) -> str:
    """What actually gets embedded — finding + context, so the short
    headline contributes to the match even for a long context paragraph."""
    return f"{chunk['finding']}. {chunk['context']}"


def build_index() -> dict:
    """Recomputes the full index from the current corpus and writes it to
    disk. Costs one embedding API call batch — not run on every query, only
    when the corpus changes (a new milestone or ADR is recorded)."""
    chunks = _chunk_milestones(_MILESTONES_PATH.read_text(encoding="utf-8")) + _chunk_adrs()
    if not chunks:
        return {"chunks": 0}
    vectors = _embed([_embed_text_for_chunk(c) for c in chunks])
    for chunk, vector in zip(chunks, vectors):
        chunk["embedding"] = vector
    # Compact, not indent=2: each chunk's embedding is 3072 floats, and
    # pretty-printing put one float per line — 59 chunks blew this up to
    # 180K+ lines / 3.8MB for what should be a small metadata file. Not
    # meant to be hand-read anyway (use --query for that); rebuilds on any
    # corpus change regardless, so diff-friendliness wouldn't have helped.
    _INDEX_PATH.write_text(json.dumps({"chunks": chunks}, separators=(",", ":")), encoding="utf-8")
    return {"chunks": len(chunks)}


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def search(query: str, top_k: int = 3) -> list[dict]:
    """
    Semantic search over the Experience collection. Returns up to top_k
    results, highest score first: {source, milestone, module, type, score,
    finding, context}. Every field except `score` is a verbatim copy of
    something already on disk (a milestone paragraph or an ADR's own
    fields) — nothing here is generated, so there is no fabrication surface.
    Evidence to weigh, not a fact to trust blindly; the caller still has to
    reason about relevance using the score. Builds the index on first use if
    it doesn't exist yet on disk.
    """
    if not _INDEX_PATH.exists():
        build_index()
    index = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    chunks = index.get("chunks", [])
    if not chunks:
        return []
    query_vector = _embed([query])[0]
    scored = [
        {
            "source": c["source"],
            "milestone": c.get("milestone"),
            "module": c.get("module"),
            "type": c.get("type"),
            "score": _cosine(query_vector, c["embedding"]),
            "finding": c["finding"],
            "context": c["context"],
        }
        for c in chunks
    ]
    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:top_k]


if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--query", type=str)
    args = parser.parse_args()

    if args.rebuild:
        result = build_index()
        print(f"Indexed {result['chunks']} chunks -> {_INDEX_PATH}")

    if args.query:
        for r in search(args.query):
            print(f"[{r['score']:.3f}] {r['source']} / {r.get('milestone') or r.get('module')} ({r['type']})")
            print(f"    finding: {r['finding']}")
            print(f"    context: {r['context'][:200]}")
            print()
