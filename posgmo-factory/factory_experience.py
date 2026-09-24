"""
Factory Knowledge & Experience -- Phases 1-3.

Semantic memory over what the Factory has already learned:
- Phase 1 (Experience): milestone findings (docs/commercial-app-milestones.md)
  and recorded architecture decisions (decision_registry/ADR-*.json) --
  what happened when a module was actually RUN.
- Phase 2 (Architecture): every PRD's own narrative (tests/prd_*.json's
  `description` field -- business requirements, constraints, and especially
  OPEN ARCHITECTURAL QUESTIONS) -- the design REASONING behind a module,
  captured before it was ever run.
- Phase 3 (Implementation): actual generated code from local_export/*/
  artifacts.json -- real SQL/backend/frontend files the Factory previously
  produced. Filtered per LAYER by that layer's own reviewer score (>= 80),
  not per module -- a module that failed overall can still have one
  genuinely good layer (confirmed on real data: notificationDispatch's
  backend scored 20 and must never be offered as "how we did it", but its
  database and frontend both scored 100 and are legitimately reusable
  reference). Never blindly copied truth -- the reviewer still verifies
  whatever gets generated next, same as every other layer.

All three phases share one corpus, one retrieval mechanism, one MCP tool
(search_factory_experience) -- an agent doesn't need to know which phase
indexed a given result, only that its `type` field says "experience",
"decision", "architecture", or "implementation".

Deliberately NOT a replacement for mcp_server's structured getters (schema,
SP patterns, routes) -- those stay exact-match lookups because exact lookup
is superior for facts (see mcp_server/server.py). This is for the opposite
case: "has something like this been tried before," where the wording won't
match a keyword search. _classify_tenant_model's brittle substring signal
matching and the TIER_4 "led"-inside-"controlled" false positive (both found
and fixed in this same session, agents/decision_gate/rules.py) are exactly
the failure mode semantic retrieval is meant to fix -- a differently-worded
PRD describing the same tenancy exception wouldn't match either bug's fixed
keyword list, but should surface the same precedent semantically.

Design principle this module must never violate (stated explicitly by the
user when this was scoped): RAG retrieves evidence, agents reason over it,
MCP/Graph stays the authoritative source of facts, the reviewer verifies the
resulting implementation. This module is not a source of truth -- every
result it returns is a verbatim, sourced excerpt of something already
written to disk (a milestone finding, a recorded ADR, a PRD's own text, or
a previously generated implementation file); nothing here is generated or
synthesized, so there is no fabrication surface in the retrieval path
itself.

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
_PRD_DIR = _ROOT / "tests"
_LOCAL_EXPORT_DIR = _ROOT / "local_export"
_MIN_LAYER_SCORE = 80  # a layer must score at least this to be "proven" reference material
_INDEX_PATH = _ROOT / "factory_experience_index.json"
_EMBEDDING_MODEL = "gemini-embedding-001"

_MIN_CHUNK_CHARS = 40  # skip stray short lines / table row fragments
_BOLD_LEAD_RE = re.compile(r"^\*\*([^*]+)\*\*:?\s*")
_OPEN_QUESTIONS_HEADER_RE = re.compile(r"^OPEN ARCHITECTURAL QUESTIONS\b.*$", re.IGNORECASE | re.MULTILINE)
_NUMBERED_ITEM_SPLIT_RE = re.compile(r"\n(?=\d+\.\s)")
_SECTION_HEADER_RE = re.compile(r"^([A-Z][A-Z /]{6,})(?:\s*[-—].*)?$")


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


def _prd_finding_label(text: str, module: str, section: str | None) -> str:
    if section:
        return f"{module} — {section}"
    first_line = text.split("\n", 1)[0].strip()
    return f"{module}: {first_line[:120]}"


def _chunk_prds() -> list[dict]:
    """
    Chunk every tests/prd_*.json's `description` narrative: each blank-line
    paragraph is one chunk, EXCEPT the OPEN ARCHITECTURAL QUESTIONS section,
    which is further split into one chunk per numbered question -- these are
    the highest-value, most distinctly reusable architectural precedent
    (e.g. "how does a module reference a parent table that isn't live yet"
    recurs, worded differently, across organization/projects/factoryRun/
    factoryArtifact -- merging them into one big chunk per PRD would dilute
    each individual question's own signal).
    """
    chunks: list[dict] = []
    if not _PRD_DIR.exists():
        return chunks
    for path in sorted(_PRD_DIR.glob("prd_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        module = data.get("module") or path.stem.removeprefix("prd_")
        description = (data.get("description") or "").strip()
        if not description:
            continue
        for para in re.split(r"\n\s*\n", description):
            para = para.strip()
            if not para:
                continue
            header_match = _SECTION_HEADER_RE.match(para.split("\n", 1)[0])
            section_name = header_match.group(1).strip() if header_match else None

            if section_name and section_name.upper().startswith("OPEN ARCHITECTURAL"):
                body = para.split("\n", 1)[1] if "\n" in para else ""
                for item in _NUMBERED_ITEM_SPLIT_RE.split(body):
                    item = item.strip()
                    if len(item) < _MIN_CHUNK_CHARS:
                        continue
                    item_label = item.split("\n", 1)[0][:100].rstrip(".")
                    chunks.append({
                        "source": path.name,
                        "milestone": None,
                        "module": module,
                        "type": "architecture",
                        "finding": f"{module} — open question: {item_label}",
                        "context": item,
                    })
                continue

            if len(para) < _MIN_CHUNK_CHARS:
                continue
            chunks.append({
                "source": path.name,
                "milestone": None,
                "module": module,
                "type": "architecture",
                "finding": _prd_finding_label(para, module, section_name),
                "context": para,
            })
    return chunks


def _parse_artifact_json(raw) -> dict:
    """database_artifacts/backend_artifacts/frontend_artifacts are stored as
    JSON strings, sometimes wrapped in ```json markdown fences the LLM adds
    despite being told not to (same shape every other consumer in this repo
    already has to handle -- see agents/reviewer/rules.py, agents/fixer/
    rules.py). Returns {} on anything unparseable rather than raising, since
    this is best-effort reference indexing, not a correctness-critical path."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    body = raw.strip()
    if body.startswith("```"):
        body = "\n".join(l for l in body.splitlines() if not l.strip().startswith("```")).strip()
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


# layer -> (session-state key, {file key: is this a {"path","content"} object, or a plain SQL string?})
_LAYER_FILE_KEYS = {
    "database": ["create_table", "sp_upsert", "sp_all", "sp_one"],       # plain strings
    "backend": ["module_file", "route_file"],                            # {"path","content"} objects
    "frontend": ["api_file", "page_file", "css_file"],                   # {"path","content"} objects
}


def _chunk_implementations() -> list[dict]:
    """
    One chunk per generated FILE (not sub-split like prose -- "show me how
    we implemented a similar module" is a whole-file browsing use case),
    filtered per LAYER by that layer's own reviewer score, not per module --
    a module that failed overall can still have one genuinely proven layer.
    See _MIN_LAYER_SCORE and the module docstring for why this filter is not
    optional: unfiltered, this would offer the Factory's own known-broken
    code as if it were a good pattern to copy.
    """
    chunks: list[dict] = []
    if not _LOCAL_EXPORT_DIR.exists():
        return chunks
    for module_dir in sorted(_LOCAL_EXPORT_DIR.iterdir()):
        artifacts_path = module_dir / "artifacts.json"
        if not module_dir.is_dir() or not artifacts_path.exists():
            continue
        try:
            data = json.loads(artifacts_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        module = module_dir.name
        review = _parse_artifact_json(data.get("review_result", "{}"))
        scores = review.get("scores") or {}

        for layer, file_keys in _LAYER_FILE_KEYS.items():
            score = scores.get(layer)
            if not isinstance(score, (int, float)) or score < _MIN_LAYER_SCORE:
                continue  # not proven -- missing, None, or below the bar
            layer_data = _parse_artifact_json(data.get(f"{layer}_artifacts", "{}"))
            for key in file_keys:
                raw_field = layer_data.get(key)
                if layer == "database":
                    content, path = raw_field, key
                else:
                    content = raw_field.get("content", "") if isinstance(raw_field, dict) else ""
                    path = raw_field.get("path", key) if isinstance(raw_field, dict) else key
                if not content or not isinstance(content, str) or len(content) < _MIN_CHUNK_CHARS:
                    continue
                chunks.append({
                    "source": f"local_export/{module}/artifacts.json",
                    "milestone": None,
                    "module": module,
                    "type": "implementation",
                    "finding": f"{module} — {layer} — {path} (reviewer score {score})",
                    "context": content,
                })
    return chunks


_MAX_EMBED_BATCH = 90  # API hard limit is 100 requests/batch; leave headroom


def _embed(texts: list[str]) -> list[list[float]]:
    """Batches internally — Phase 2 pushed the corpus past the API's 100-
    items-per-request limit for the first time (146 chunks vs. Phase 1's
    59), confirmed live: a single call over the full corpus raised
    'at most 100 requests can be in one batch'. Callers never need to know
    the corpus is big enough to require this."""
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    vectors: list[list[float]] = []
    for i in range(0, len(texts), _MAX_EMBED_BATCH):
        batch = texts[i:i + _MAX_EMBED_BATCH]
        result = client.models.embed_content(model=_EMBEDDING_MODEL, contents=batch)
        vectors.extend(e.values for e in result.embeddings)
    return vectors


def _embed_text_for_chunk(chunk: dict) -> str:
    """What actually gets embedded — finding + context, so the short
    headline contributes to the match even for a long context paragraph."""
    return f"{chunk['finding']}. {chunk['context']}"


def build_index() -> dict:
    """Recomputes the full index from the current corpus and writes it to
    disk. Costs one embedding API call batch — not run on every query, only
    when the corpus changes (a new milestone or ADR is recorded)."""
    chunks = (
        _chunk_milestones(_MILESTONES_PATH.read_text(encoding="utf-8"))
        + _chunk_adrs()
        + _chunk_prds()
        + _chunk_implementations()
    )
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
