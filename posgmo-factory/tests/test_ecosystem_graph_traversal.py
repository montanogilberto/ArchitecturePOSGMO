"""Pure-unit tests for ecosystem_graph.graph.what_breaks_if_changed().

Deliberately uses a synthetic EcosystemGraph fixture, not live extraction —
this is the one layer of ecosystem_graph that has no external dependency
(no filesystem, no DB) and is worth testing in full isolation from the three
extractors, whose own correctness is covered separately in
test_ecosystem_graph_frontend_calls.py and test_ecosystem_graph_backend_routes.py.

The fixture below mirrors the real, verified clients-module shape (see the
other two test files for how those edges were confirmed against source) so
a reader can cross-check it's not an arbitrary toy graph.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ecosystem_graph.graph import EcosystemGraph, what_breaks_if_changed


def _clients_graph() -> EcosystemGraph:
    return EcosystemGraph(
        frontend_to_route=[
            {"frontend_node": "clientsApi.ts:createOrUpdateClient", "path": "/clients", "method": "POST"},
            {"frontend_node": "clientsApi.ts:getAllClients", "path": "/all_clients", "method": "GET"},
        ],
        route_to_sp=[
            {"path": "/clients", "method": "POST", "stored_procedures": ["sp_clients"]},
            {"path": "/all_clients", "method": "GET", "stored_procedures": ["sp_clients_all"]},
        ],
        sp_to_table=[
            {"procedure": "sp_clients", "table": "clients"},
            {"procedure": "sp_clients_all", "table": "clients"},
        ],
    )


def test_table_change_reaches_both_routes_and_both_frontend_calls():
    result = what_breaks_if_changed(_clients_graph(), "table", "clients")
    assert result["directly_affects"] == ["stored procedure sp_clients", "stored procedure sp_clients_all"]
    assert result["transitively_affects"] == [
        "frontend call clientsApi.ts:createOrUpdateClient",
        "frontend call clientsApi.ts:getAllClients",
        "route GET /all_clients",
        "route POST /clients",
    ]


def test_stored_procedure_change_reaches_its_one_route_and_frontend_call():
    result = what_breaks_if_changed(_clients_graph(), "stored_procedure", "sp_clients")
    assert result["directly_affects"] == ["route POST /clients"]
    assert result["transitively_affects"] == ["frontend call clientsApi.ts:createOrUpdateClient"]


def test_route_change_reaches_its_frontend_call_only_no_transitive_hop():
    result = what_breaks_if_changed(_clients_graph(), "route", "POST /clients")
    assert result["directly_affects"] == ["frontend call clientsApi.ts:createOrUpdateClient"]
    assert result["transitively_affects"] == []


def test_unknown_node_returns_empty_lists_not_an_error():
    """Per the function's own docstring: an empty result must not be
    mistaken for 'nothing depends on this' — it means nothing in the
    current MODULES_IN_SCOPE coverage was extracted. Still, the function
    itself must not raise for a node it has no data on."""
    result = what_breaks_if_changed(_clients_graph(), "table", "some_table_never_seen")
    assert result == {"directly_affects": [], "transitively_affects": []}
