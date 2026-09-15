"""Tests for ecosystem_graph.frontend_calls against the real POSVending checkout.

Covers step 16F's "page -> API client -> endpoint" relationship at the layer
this extractor actually models today: API-client-file -> fetch() call ->
endpoint (there is no "page" node yet — pages call these exported functions,
but nothing in ecosystem_graph currently traces page -> function calls; that
would be a frontend-side AST layer this repo doesn't have, same honest-gap
posture as the rest of this module).

Runs against real source, not a fixture copy, per this module's own stated
discipline (verify against the real thing). Skips cleanly if the POSVending
checkout isn't present on this machine, rather than failing CI elsewhere.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from ecosystem_graph.frontend_calls import extract_frontend_edges, extract_frontend_edges_for_modules

FRONTEND_REPO_PATH = "/Users/apple12/PycharmProjects/POSVendingV2/POSVending"
CLIENTS_API_PATH = f"{FRONTEND_REPO_PATH}/src/api/clientsApi.ts"
POS_REWARDS_API_PATH = f"{FRONTEND_REPO_PATH}/src/api/posRewardsApi.ts"

pytestmark = pytest.mark.skipif(
    not Path(CLIENTS_API_PATH).is_file(),
    reason="POSVending checkout not present on this machine",
)


def _edge(edges, func_name):
    matches = [e for e in edges if e["frontend_func"] == func_name]
    assert matches, f"expected an edge for {func_name!r}, got funcs={[e['frontend_func'] for e in edges]}"
    return matches[0]


def test_clients_api_known_literal_edges():
    """clientsApi.ts (verified by direct read, 2026-09-15): four exported
    functions, each with a literal fetch() path — no dynamic-path guessing
    needed for this file."""
    edges = extract_frontend_edges(CLIENTS_API_PATH)

    create = _edge(edges, "createOrUpdateClient")
    assert create["path"] == "/clients"
    assert create["method"] == "POST"

    get_all = _edge(edges, "getAllClients")
    assert get_all["path"] == "/all_clients"
    assert get_all["method"] == "GET"

    upload_qr = _edge(edges, "uploadClientQr")
    assert upload_qr["path"] == "/clients/upload-qr"
    assert upload_qr["method"] == "POST"

    get_one = _edge(edges, "getOneClient")
    assert get_one["path"] == "/one_clients"
    assert get_one["method"] == "POST"

    # A literal path with a real HTTP-verb match is VERIFIED, not just
    # "found" -- confidence is a distinct field from "the edge exists".
    assert all(e["confidence"] == "VERIFIED" for e in edges)


def test_dynamic_path_adjacent_to_base_url_is_reported_unknown_not_guessed():
    """posRewardsApi.ts (verified by direct read, 2026-09-15): its second
    fetch() call is `fetch(`${API_BASE_URL}${path}`, ...)` -- base URL and
    a variable directly adjacent, no literal separator. This is the one
    dynamic-path shape frontend_calls.py's own docstring says it handles:
    reported with path=None and confidence UNKNOWN, never a guess."""
    edges = extract_frontend_edges(POS_REWARDS_API_PATH)
    dynamic = [e for e in edges if e["confidence"] == "UNKNOWN"]
    assert dynamic, "expected at least one UNKNOWN-confidence dynamic-path edge"
    assert all(e["path"] is None for e in dynamic)


def test_known_gap_dynamic_path_with_literal_separator_is_silently_dropped():
    """Documents a real, currently-unfixed limitation (see
    docs/ecosystem-graph.md Limitations): posRewardsApi.ts's FIRST fetch
    call, `fetch(`${API_BASE_URL}/${pluralModule}`, ...)`, has a literal
    "/" between the base URL and the next `${...}` -- neither
    _FETCH_LITERAL_RE nor _FETCH_DYNAMIC_RE matches this shape, so it is
    not reported as an edge at all (not even as an honest UNKNOWN), unlike
    the adjacent-variables case above. This test locks in that current
    behavior so a future fix is a deliberate, visible change to this
    test, not a silent behavior shift."""
    edges = extract_frontend_edges(POS_REWARDS_API_PATH)
    # Only the one adjacent-variables call from the test above is ever
    # returned; the separator-prefixed call is missing entirely.
    assert len(edges) == 1


def test_extract_frontend_edges_for_modules_scopes_by_filename():
    """The module-scoped entry point used by build_graph() only reads the
    named files, not the whole src/api/ directory."""
    edges = extract_frontend_edges_for_modules(FRONTEND_REPO_PATH, ["clientsApi.ts"])
    assert edges, "expected at least the four known clientsApi.ts edges"
    assert all(e["source_file"] == "clientsApi.ts" for e in edges)

    missing = extract_frontend_edges_for_modules(FRONTEND_REPO_PATH, ["doesNotExistApi.ts"])
    assert missing == [], "a nonexistent api file should yield an empty list, not an error"
