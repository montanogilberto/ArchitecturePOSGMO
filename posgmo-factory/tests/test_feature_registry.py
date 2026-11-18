import json

from agents.feature_registry.rules import build_registration, registration_sql, run_feature_registry


class _Ctx:
    def __init__(self, state):
        self.state = state


FRONTEND = {
    "app_patches": {
        "private_route": '<PrivateRoute exact path="/suppliers" component={SupplierPage} />',
        "menu_section": "Catálogo",
        "canAccess_key": "suppliers",
    },
    "setting_patch": {"section": "Catálogo", "code": "suppliers", "label": "Proveedores", "icon": "peopleOutline"},
    "rolePermissions_patch": {"roles_to_add": ["manager"]},
}


def test_build_registration_uses_frontend_decisions():
    p = build_registration(FRONTEND, "supplier", "Supplier")
    assert p == {
        "featureCode": "suppliers", "displayName": "Supplier", "label": "Proveedores",
        "section": "Catálogo", "icon": "peopleOutline", "route": "/suppliers",
        "roles": ["admin", "manager"],
    }


def test_unknown_section_icon_and_roles_fall_back():
    fe = {"app_patches": {"canAccess_key": "widgets"},
          "setting_patch": {"section": "Sistema", "icon": "x; DROP"},
          "rolePermissions_patch": {"roles_to_add": ["pos", "borrower"]}}
    p = build_registration(fe)
    assert p["section"] == "Administración"
    assert p["icon"] == "settingsOutline"
    assert p["roles"] == ["admin"]  # self-service roles never granted staff modules
    assert p["route"] is None


def test_invalid_code_skips():
    assert build_registration({"app_patches": {"canAccess_key": "bad code'"}}) is None


def test_sql_escapes_quotes():
    p = build_registration(FRONTEND)
    p["label"] = "O'Brien"
    sql = registration_sql(p)
    assert "EXEC [dbo].[sp_uiFeatures_register] @pjsonfile = N'" in sql
    assert "O''Brien" in sql and sql.rstrip().endswith("GO")


def test_stage_writes_feature_registration_into_database_artifacts():
    state = {"frontend_artifacts": json.dumps(FRONTEND),
             "database_artifacts": json.dumps({"sp_all": "CREATE PROCEDURE ..."}),
             "module": "supplier", "Module": "Supplier"}
    report = run_feature_registry(_Ctx(state))
    assert report["status"] == "registered"
    db = json.loads(state["database_artifacts"])
    assert db["sp_all"] == "CREATE PROCEDURE ..."
    assert "sp_uiFeatures_register" in db["feature_registration"]


def test_stage_skips_without_frontend():
    state = {"database_artifacts": "{}"}
    assert run_feature_registry(_Ctx(state))["status"] == "skipped"
    assert "feature_registration" not in json.loads(state["database_artifacts"])
