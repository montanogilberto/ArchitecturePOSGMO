"""Tests for repository/commit stamping on EcosystemGraph (step 11:
version-awareness -- "this graph describes the repos as of commit X").

_git_info() is tested directly against this very repo (Agent_POSGMO),
which is guaranteed to be a real git checkout wherever these tests run --
no dependency on POSVending/smartloans_backend being present.
"""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import ecosystem_graph.graph as graph_module
from ecosystem_graph.graph import SCANNER_VERSION, EcosystemGraph, _git_info, build_graph

FACTORY_REPO_PATH = str(Path(__file__).parent.parent.parent)  # Agent_POSGMO root
FRONTEND_REPO_PATH = "/Users/apple12/PycharmProjects/POSVendingV2/POSVending"
BACKEND_REPO_PATH = "/Users/apple12/PycharmProjects/pythonProject/smartloans_backend"


def test_git_info_matches_real_git_rev_parse():
    info = _git_info(FACTORY_REPO_PATH)
    expected_commit = subprocess.run(
        ["git", "-C", FACTORY_REPO_PATH, "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert info["commit"] == expected_commit
    assert info["branch"]  # some branch name, exact value depends on what's checked out


def test_git_info_is_none_not_an_exception_for_a_non_git_path(tmp_path):
    info = _git_info(str(tmp_path))
    assert info == {"commit": None, "branch": None}


def test_ecosystem_graph_defaults_when_built_without_stamping():
    """A graph constructed directly (as this module's own traversal tests
    do) rather than via build_graph() still has sources/scanner_version/
    scanned_at fields -- just empty/default ones, never missing entirely,
    so a caller can uniformly check for staleness without a KeyError."""
    graph = EcosystemGraph(frontend_to_route=[], route_to_sp=[], sp_to_table=[])
    assert graph.sources == {}
    assert graph.scanner_version == SCANNER_VERSION
    assert graph.scanned_at == ""


def test_build_graph_stamps_both_repo_sources(monkeypatch):
    """build_graph() itself must populate sources/scanned_at, not just
    leave them at the dataclass defaults. The live-DB call
    (get_sp_table_dependencies) is monkeypatched out here specifically so
    this test's pass/fail is about stamping, not about DB reachability --
    that's covered separately in test_ecosystem_graph_sql_dependencies.py."""
    if not Path(FRONTEND_REPO_PATH).is_dir() or not Path(BACKEND_REPO_PATH).is_dir():
        pytest.skip("POSVending/smartloans_backend checkouts not present on this machine")

    monkeypatch.setattr(graph_module, "get_sp_table_dependencies", lambda sp_names: [])

    graph = build_graph(BACKEND_REPO_PATH, FRONTEND_REPO_PATH, modules_in_scope={"clients": ["clientsApi.ts"]})

    assert graph.sources["backend"]["path"] == BACKEND_REPO_PATH
    assert graph.sources["backend"]["commit"], "expected a real commit SHA for the backend checkout"
    assert graph.sources["frontend"]["path"] == FRONTEND_REPO_PATH
    assert graph.sources["frontend"]["commit"], "expected a real commit SHA for the frontend checkout"
    assert graph.scanned_at  # non-empty ISO-ish timestamp
    assert graph.scanner_version == SCANNER_VERSION
