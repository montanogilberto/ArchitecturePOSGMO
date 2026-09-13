"""Phase 3 — cross-checks against the canonical live-tracked schema
(Database/structure_database.csv + sql_relationships.json). No live DB
connection, no GitHub API — local files only."""

from debate_schema import ContextItemKind
from debate_v2.context import gather_context
from debate_v2.context_graph import (
    check_domain_has_no_matching_table,
    check_referenced_parent_tables,
    load_schema_tables,
    neighbors_of,
)


def test_schema_has_real_tables_loaded():
    tables = load_schema_tables()
    assert len(tables) > 50           # sanity: this is the real 119-table schema, not empty
    assert "companies" in tables
    assert "clients" in tables


def test_reward_domain_has_no_table_in_the_real_schema():
    """This is the concrete discrepancy Phase 3 exists to catch: the draft
    PRD's own prose claims an 'existing loan-behavior rewardBalances table',
    but no such table is in the canonical schema snapshot."""
    item = check_domain_has_no_matching_table("reward")
    assert item.kind == ContextItemKind.verified_fact
    assert "No table matching 'reward'" in item.claim


def test_known_domain_table_is_found():
    item = check_domain_has_no_matching_table("client")
    assert "real table(s) matching 'client'" in item.claim


def test_referenced_parent_tables_split_verified_vs_assumption():
    items = check_referenced_parent_tables(["companies", "not_a_real_table_xyz"])
    by_claim = {i.claim: i for i in items}
    companies_item = next(i for c, i in by_claim.items() if c.startswith("Parent table 'companies'"))
    fake_item = next(i for c, i in by_claim.items() if "not_a_real_table_xyz" in c)
    assert companies_item.kind == ContextItemKind.verified_fact
    assert fake_item.kind == ContextItemKind.assumption


def test_neighbors_of_known_table_returns_lists():
    nb = neighbors_of("companies")
    assert isinstance(nb["parents"], list)
    assert isinstance(nb["children"], list)


def test_gather_context_now_includes_schema_cross_check_for_rewards():
    """End-to-end (still zero LLM calls): the full gather_context() pipeline
    surfaces the schema contradiction alongside the Phase 2 PRD evidence."""
    verified, assumptions = gather_context("create a new module for rewards")
    verified_claims = " ".join(v.claim for v in verified)
    assert "No table matching 'reward' exists in the current schema snapshot" in verified_claims
    assert "Parent table 'companies' exists in the schema" in verified_claims
    # posRewardCatalogItem is listed as a *parentModule* in one draft PRD's
    # relationships[] but is not itself a real table yet — must be an assumption.
    assumption_claims = " ".join(a.claim for a in assumptions)
    assert "posRewardCatalogItem" in assumption_claims
