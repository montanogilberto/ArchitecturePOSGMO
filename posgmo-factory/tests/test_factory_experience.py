"""
Factory Knowledge & Experience — Phases 1-2 (Experience + Architecture).

Chunking, headline-splitting, and ranking logic are tested with mocked
embeddings so most of this file never depends on live API calls. The
"_live" tests at the bottom DO call the real Gemini embedding API and query
the real corpus — deliberately promoted from manual verification to real
tests, since they're the actual proof this collection retrieves semantically
relevant precedent, not just plausible-looking chunks:

    "generating multiple SQL statements together"                     (Phase 1)
        -> must rank the real factoryArtifact batching finding highly,
           despite the query never saying "GO", "batch", or
           "CREATE/ALTER PROCEDURE".

    "this entity is not tied to any retail company"                   (Phase 1)
        -> must surface the real organization tenancy-phrasing-gap finding,
           despite the query never saying "companyId" or "tenant".

    "how should a module reference a parent table that hasn't been    (Phase 2)
     created in the live database yet"
        -> must surface real PRD open-question precedent from more than
           one module (organization, projects, factoryRun,
           factoryArtifact all independently hit this same pattern),
           despite the query never naming any specific module or using
           any PRD's exact phrasing ("plain reference field, not a
           foreign key", "table isn't live yet", etc.).

None of these queries use the literal wording of the finding they're
expected to surface — that's the whole point (contrast with
search_decisions' plain substring matching, and with
_classify_tenant_model's brittle keyword signals, agents/decision_gate/
rules.py, found fragile in this same session).
"""
import json

from factory_experience import (
    _chunk_adrs,
    _chunk_milestones,
    _chunk_prds,
    _cosine,
    _split_finding_context,
    search,
)


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def test_chunk_milestones_splits_by_section_and_skips_next():
    text = """# Commercial App — Milestones

## Milestone 1 — first thing

**Input:** some real finding text long enough to pass the minimum length filter here.

**Conclusion:** another finding, also long enough to survive the chunker's length gate.

## Next

Short next-steps text that must never be indexed as a milestone finding.
"""
    chunks = _chunk_milestones(text)
    assert len(chunks) == 2
    assert all(c["milestone"] == "Milestone 1" for c in chunks)
    assert all(c["type"] == "experience" for c in chunks)
    assert all(c["source"] == "commercial-app-milestones.md" for c in chunks)


def test_chunk_milestones_skips_short_fragments():
    text = """## Milestone 1 — x

**Input:** a real finding paragraph long enough to be indexed as real content here.

x
"""
    chunks = _chunk_milestones(text)
    assert len(chunks) == 1  # the bare "x" paragraph must be dropped


def test_chunk_adrs_reads_real_fixtures(tmp_path, monkeypatch):
    adr_dir = tmp_path / "decision_registry"
    adr_dir.mkdir()
    (adr_dir / "ADR-001.json").write_text(json.dumps({
        "id": "ADR-001",
        "request": "Add one-time-use enforcement",
        "selectedClaim": "Use a redemption ledger",
        "rationale": "Prevents abuse",
        "module": "promotionRedemption",
    }))
    monkeypatch.setattr("factory_experience._ADR_DIR", adr_dir)
    chunks = _chunk_adrs()
    assert len(chunks) == 1
    assert chunks[0]["module"] == "promotionRedemption"
    assert chunks[0]["type"] == "decision"
    assert chunks[0]["source"] == "decision_registry"
    assert "redemption ledger" in chunks[0]["context"]


def _write_prd(prd_dir, filename, module, description):
    (prd_dir / filename).write_text(json.dumps({
        "module": module,
        "description": description,
        "fields": [{"name": "x", "type": "string"}],
    }))


def test_chunk_prds_splits_paragraphs_and_tags_architecture_type(tmp_path, monkeypatch):
    prd_dir = tmp_path / "tests"
    prd_dir.mkdir()
    _write_prd(prd_dir, "prd_widget.json", "widget", (
        "Intro paragraph long enough to survive the minimum chunk length filter here.\n\n"
        "CONSTRAINTS\n- a real constraint sentence long enough to survive the filter too."
    ))
    monkeypatch.setattr("factory_experience._PRD_DIR", prd_dir)

    chunks = _chunk_prds()
    assert len(chunks) == 2
    assert all(c["module"] == "widget" for c in chunks)
    assert all(c["type"] == "architecture" for c in chunks)
    assert all(c["source"] == "prd_widget.json" for c in chunks)
    assert any("CONSTRAINTS" in c["finding"] for c in chunks)


def test_chunk_prds_splits_open_questions_into_individual_items(tmp_path, monkeypatch):
    """The real point of Phase 2's chunking: each numbered open question
    becomes its OWN chunk, not one giant blob diluting every question's
    signal together — confirmed against the real corpus (factoryArtifact
    alone has 6 open questions that must retrieve independently)."""
    prd_dir = tmp_path / "tests"
    prd_dir.mkdir()
    _write_prd(prd_dir, "prd_widget.json", "widget", (
        "Intro paragraph long enough to survive the minimum chunk length filter here.\n\n"
        "OPEN ARCHITECTURAL QUESTIONS -- deliberately unresolved\n"
        "1. First open question, long enough on its own to survive the length filter.\n"
        "2. Second open question, also long enough on its own to survive the filter."
    ))
    monkeypatch.setattr("factory_experience._PRD_DIR", prd_dir)

    chunks = _chunk_prds()
    question_chunks = [c for c in chunks if "open question" in c["finding"]]
    assert len(question_chunks) == 2
    assert "First open question" in question_chunks[0]["context"]
    assert "Second open question" in question_chunks[1]["context"]
    # Neither question's chunk should contain the OTHER question's text —
    # that's the dilution this split exists to prevent.
    assert "Second open question" not in question_chunks[0]["context"]
    assert "First open question" not in question_chunks[1]["context"]


def test_chunk_prds_skips_missing_or_empty_description(tmp_path, monkeypatch):
    prd_dir = tmp_path / "tests"
    prd_dir.mkdir()
    (prd_dir / "prd_empty.json").write_text(json.dumps({"module": "empty", "fields": []}))
    monkeypatch.setattr("factory_experience._PRD_DIR", prd_dir)
    assert _chunk_prds() == []


# ---------------------------------------------------------------------------
# finding/context split
# ---------------------------------------------------------------------------

def test_split_finding_context_extracts_bold_headline():
    text = "**Bug #2 — database batching, root-caused, not patched:**\nThe rest of the paragraph."
    finding, context = _split_finding_context(text)
    assert finding == "Bug #2 — database batching, root-caused, not patched"
    assert context == text  # context is always the full original text


def test_split_finding_context_falls_back_to_first_line():
    text = "no bold lead-in here, just plain prose\nsecond line"
    finding, context = _split_finding_context(text)
    assert finding == "no bold lead-in here, just plain prose"
    assert context == text


# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------

def test_cosine_identical_vectors_score_one():
    v = [0.5, 0.5, 0.7071]
    assert abs(_cosine(v, v) - 1.0) < 1e-6


def test_cosine_orthogonal_vectors_score_zero():
    assert abs(_cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9


# ---------------------------------------------------------------------------
# search() ranking + no-fabrication guarantee (mocked embeddings)
# ---------------------------------------------------------------------------

def test_search_ranks_by_similarity_not_keyword_overlap(tmp_path, monkeypatch):
    index_path = tmp_path / "factory_experience_index.json"
    index_path.write_text(json.dumps({"chunks": [
        {"source": "commercial-app-milestones.md", "milestone": "Milestone 1", "module": None,
         "type": "experience", "finding": "unrelated", "context": "unrelated finding about frontend routing",
         "embedding": [1.0, 0.0, 0.0]},
        {"source": "commercial-app-milestones.md", "milestone": "Milestone 2", "module": None,
         "type": "experience", "finding": "the real match", "context": "worded completely differently",
         "embedding": [0.0, 1.0, 0.0]},
    ]}))
    monkeypatch.setattr("factory_experience._INDEX_PATH", index_path)
    monkeypatch.setattr("factory_experience._embed", lambda texts: [[0.0, 1.0, 0.0]])

    results = search("some query with zero word overlap with chunk b's text", top_k=2)
    assert results[0]["finding"] == "the real match"
    assert results[0]["score"] > results[1]["score"]


def test_search_never_fabricates_result_content(tmp_path, monkeypatch):
    """Every field except `score` must be a verbatim copy of what's stored
    in the index — nothing in the retrieval path generates text, so there's
    no fabrication surface. This is a structural guarantee, not a heuristic:
    prove it by checking exact equality against the stored chunk, not just
    'looks plausible'."""
    stored_chunk = {
        "source": "commercial-app-milestones.md", "milestone": "Milestone 6", "module": None,
        "type": "experience", "finding": "Bug #2 — database batching",
        "context": "the exact, full, original paragraph text with no alteration whatsoever",
        "embedding": [1.0, 0.0],
    }
    index_path = tmp_path / "factory_experience_index.json"
    index_path.write_text(json.dumps({"chunks": [stored_chunk]}))
    monkeypatch.setattr("factory_experience._INDEX_PATH", index_path)
    monkeypatch.setattr("factory_experience._embed", lambda texts: [[1.0, 0.0]])

    result = search("anything", top_k=1)[0]
    assert result["source"] == stored_chunk["source"]
    assert result["finding"] == stored_chunk["finding"]
    assert result["context"] == stored_chunk["context"]
    assert result["milestone"] == stored_chunk["milestone"]


def test_search_returns_empty_list_when_index_has_no_chunks(tmp_path, monkeypatch):
    """An unknown/irrelevant query against an empty index must return
    nothing — not a low-confidence guess dressed up as a result."""
    index_path = tmp_path / "factory_experience_index.json"
    index_path.write_text(json.dumps({"chunks": []}))
    monkeypatch.setattr("factory_experience._INDEX_PATH", index_path)
    monkeypatch.setattr("factory_experience._embed", lambda texts: [[1.0, 0.0]])

    assert search("anything at all", top_k=3) == []


# ---------------------------------------------------------------------------
# Live proof — real embedding API, real corpus. Promoted from manual
# verification (see module docstring) because this is the actual evidence
# that semantic retrieval works here, not a nice-to-have extra.
# ---------------------------------------------------------------------------

def test_live_sql_batching_query_surfaces_factoryartifact_finding():
    results = search("generating multiple SQL statements together", top_k=3)
    assert any(
        r["milestone"] == "Milestone 6" and "batching" in r["finding"].lower()
        for r in results
    ), f"expected the factoryArtifact batching finding in top 3, got: {[r['finding'] for r in results]}"


def test_live_tenancy_paraphrase_surfaces_organization_precedent():
    results = search("this entity is not tied to any retail company", top_k=3)
    assert any(r["milestone"] == "Milestone 2" for r in results), (
        f"expected the organization tenancy-phrasing-gap finding (Milestone 2) "
        f"in top 3, got: {[(r['milestone'], r['finding']) for r in results]}"
    )


def test_live_cross_prd_not_live_yet_reference_pattern_surfaces_multiple_modules():
    """Phase 2's proof: this exact 'reference a parent that isn't live yet'
    pattern was independently hit by organization, projects, factoryRun, and
    factoryArtifact's own PRDs, each worded differently. A generic query
    with no module name and none of their specific phrasing should surface
    more than one of them, not just a lucky single match."""
    results = search(
        "how should a module reference a parent table that hasn't been created in the live database yet",
        top_k=5,
    )
    architecture_hits = {r["module"] for r in results if r["type"] == "architecture"}
    assert len(architecture_hits) >= 2, (
        f"expected precedent from at least 2 different PRDs, got modules: "
        f"{[(r['module'], r['finding']) for r in results]}"
    )
