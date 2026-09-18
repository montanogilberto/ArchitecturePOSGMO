"""Reviewer respects gate_result.tenant_model for companyId SQL checks."""

from agents.reviewer.rules import _check_database


def test_tenant_independent_rejects_company_id_column():
    gate = {"tier": "TIER_1_CATALOG", "tenant_model": "TENANT_INDEPENDENT"}
    spec = {"module": "organization"}
    db = {
        "create_table": "CREATE TABLE organizations (organizationId INT IDENTITY(1,1), companyId INT, created_At datetime, updated_at datetime)",
        "sp_upsert": "BEGIN TRY BEGIN TRANSACTION DECLARE @payload TABLE (x int) GOTO Finish Finish: COMMIT END TRY",
        "sp_all": "EXEC sp @pjsonfile VARCHAR(MAX) SELECT * FROM organizations FOR JSON AUTO, ROOT('organizations')",
        "sp_one": "EXEC sp @pjsonfile VARCHAR(MAX) SELECT * FROM organizations FOR JSON AUTO, ROOT('organizations')",
        "execution": {},
    }
    issues = _check_database(db, spec, gate)
    assert any("must not appear" in i.message and "companyId" in i.message for i in issues)


def test_tenant_scoped_still_requires_company_id():
    gate = {"tier": "TIER_1_CATALOG", "tenant_model": "TENANT_SCOPED"}
    spec = {"module": "supplier"}
    db = {
        "create_table": "CREATE TABLE suppliers (supplierId INT IDENTITY(1,1), created_At datetime, updated_at datetime)",
        "sp_upsert": "",
        "sp_all": "",
        "sp_one": "",
        "execution": {},
    }
    issues = _check_database(db, spec, gate)
    assert any(i.message == "companyId column missing from CREATE TABLE" for i in issues)
