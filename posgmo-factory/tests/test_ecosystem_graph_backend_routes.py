"""Tests for ecosystem_graph.backend_routes against the real smartloans_backend
checkout.

Covers step 16F's "endpoint -> backend route -> stored procedure" chain.
Ground truth verified by direct read of routes_/clients.py + modules/clients.py
(2026-09-15):
    POST /clients            -> clients_sp            -> EXEC [dbo].[sp_clients]
    GET  /all_clients         -> all_clients_sp         -> EXEC [dbo].[sp_clients_all]
    POST /one_clients         -> one_clients_sp         -> EXEC sp_clients_one
    POST /clients/upload-qr   -> upload_client_qr_sp    -> EXEC [dbo].[sp_clients_qr]

Skips cleanly if the smartloans_backend checkout isn't present on this
machine.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from ecosystem_graph.backend_routes import extract_backend_edges, resolve_route_to_sp

BACKEND_REPO_PATH = "/Users/apple12/PycharmProjects/pythonProject/smartloans_backend"
CLIENTS_ROUTES_PATH = f"{BACKEND_REPO_PATH}/routes_/clients.py"

pytestmark = pytest.mark.skipif(
    not Path(CLIENTS_ROUTES_PATH).is_file(),
    reason="smartloans_backend checkout not present on this machine",
)


def _route(resolved, method, path):
    matches = [r for r in resolved if r["method"] == method and r["path"] == path]
    assert matches, f"expected a resolved route for {method} {path}, got {[(r['method'], r['path']) for r in resolved]}"
    return matches[0]


def test_extract_backend_edges_finds_all_four_clients_routes():
    extraction = extract_backend_edges(BACKEND_REPO_PATH, modules_in_scope=["clients"])
    paths = {(r["method"], r["path"]) for r in extraction["routes"]}
    assert paths == {
        ("POST", "/clients"),
        ("GET", "/all_clients"),
        ("POST", "/one_clients"),
        ("POST", "/clients/upload-qr"),
    }


def test_resolve_route_to_sp_matches_verified_ground_truth():
    extraction = extract_backend_edges(BACKEND_REPO_PATH, modules_in_scope=["clients"])
    resolved = resolve_route_to_sp(extraction)

    assert _route(resolved, "POST", "/clients")["stored_procedures"] == ["sp_clients"]
    assert _route(resolved, "GET", "/all_clients")["stored_procedures"] == ["sp_clients_all"]
    assert _route(resolved, "POST", "/one_clients")["stored_procedures"] == ["sp_clients_one"]
    assert _route(resolved, "POST", "/clients/upload-qr")["stored_procedures"] == ["sp_clients_qr"]

    # Every one of these four resolves to a real SP -- all VERIFIED.
    assert all(r["confidence"] == "VERIFIED" for r in resolved)


def test_confidence_is_unknown_when_delegate_chain_has_no_sp():
    """Synthetic case (not from real source -- this repo has no verified
    example of an in-scope route resolving to zero SPs handy, see the
    module's own honest-gap posture): a route whose only delegate is a
    function with no EXEC and no further calls must resolve to an empty
    stored_procedures list AND an explicit UNKNOWN confidence, not a
    silent VERIFIED-by-omission."""
    extraction = {
        "routes": [{
            "path": "/nowhere", "method": "GET", "handler_func": "nowhere",
            "delegates_to": ["does_nothing"], "source_file": "synthetic.py",
        }],
        "function_info": {"does_nothing": {"sp_names": [], "calls": []}},
    }
    resolved = resolve_route_to_sp(extraction)
    assert resolved[0]["stored_procedures"] == []
    assert resolved[0]["confidence"] == "UNKNOWN"


def test_unresolvable_route_returns_empty_list_not_a_guess():
    """A route whose delegate chain resolves to nothing in scope must come
    back as an honest empty list (see module docstring), never a guessed
    stored procedure name."""
    extraction = extract_backend_edges(BACKEND_REPO_PATH, modules_in_scope=["nonexistent_module_xyz"])
    resolved = resolve_route_to_sp(extraction)
    assert resolved == []
