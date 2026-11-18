"""MVVM frontend layout: one source of paths (frontend_layout.py), enforced on
the spec by the reconciler, checked by the reviewer, repaired by the fixers."""
from __future__ import annotations

import copy
import json

from frontend_layout import layout, normalize_spec_frontend, resolve_area
from prd_schema import SpecificationJSON
from agents.fixer.rules import fix_frontend
from agents.retry import has_frontend_files
from agents.review_fixer.rules import _frontend_key_for
from agents.reviewer.rules import _check_frontend
from agents.spec_reconciler.rules import normalize_frontend_paths

P = layout("supplier", "admin")


# ---------------------------------------------------------------------------
# layout + spec normalization
# ---------------------------------------------------------------------------

def test_layout_matches_the_repo_mvvm_feature_shape():
    assert P["page_file"] == "src/pages/admin/SupplierPage.tsx"
    assert P["view_file"] == "src/pages/admin/Supplier/SupplierView.tsx"
    assert P["logic_file"] == "src/pages/admin/Supplier/SupplierLogic.ts"
    assert P["css_file"] == "src/pages/admin/Supplier/Supplier.css"
    assert P["api_file"] == "src/api/supplierApi.ts"
    assert P["app_import_line"] == "import SupplierPage from './pages/admin/SupplierPage';"


def test_resolve_area_accepts_valid_folder_and_falls_back_to_module():
    assert resolve_area("supplier", "Admin/") == "admin"
    assert resolve_area("cashRegister", None) == "cashregister"
    assert resolve_area("supplier", "../etc") == "supplier"


def test_normalize_spec_rewrites_flat_paths_to_mvvm():
    spec = {"module": "supplier", "frontend": {"area": "admin", "api_file": "src/api/supplierApi.ts",
                                               "page_file": "src/pages/SupplierPage.tsx",
                                               "css_file": "src/pages/SupplierPage.css"}}
    spec, changed = normalize_spec_frontend(spec)
    assert spec["frontend"]["page_file"] == P["page_file"] and spec["frontend"]["view_file"] == P["view_file"]
    assert set(changed) == {"page_file", "view_file", "logic_file", "css_file"}
    assert normalize_spec_frontend(spec)[1] is None  # idempotent


def test_spec_reconciler_enforces_paths_from_state():
    state = {"specification": json.dumps({"module": "supplier", "frontend": {"page_file": "x.tsx"}})}
    spec, changed = normalize_frontend_paths(state)
    assert spec["frontend"]["area"] == "supplier" and "page_file" in changed


def test_specification_json_validator_uses_the_same_layout():
    spec = SpecificationJSON.model_validate({
        "module": "supplier", "description": "d",
        "db": {"table_name": "suppliers", "sp_prefix": "x", "columns": []},
        "backend": {"module_file": "m", "route_file": "r", "router_prefix": "/suppliers", "sp_calls": []},
        "frontend": {"area": "admin", "api_file": "a", "page_file": "p", "css_file": "c", "route_path": "/suppliers",
                     "roles": ["Admin"], "has_list_view": True, "has_detail_view": False,
                     "typescript_interfaces": ["Supplier"]},
    })
    assert spec.frontend.logic_file == P["logic_file"] and spec.frontend.css_file == P["css_file"]


# ---------------------------------------------------------------------------
# reviewer
# ---------------------------------------------------------------------------

SPEC = {"module": "supplier", "frontend": {"area": "admin", "view_file": P["view_file"], "has_list_view": True}}

GOOD = {
    "api_file": {"path": P["api_file"], "content": (
        "const BASE_URL = import.meta.env.VITE_API_URL ?? 'x';\n"
        "export interface Supplier { supplierId: number }\n")},
    "page_file": {"path": P["page_file"], "content": (
        "import React from 'react';\nimport './Supplier/Supplier.css';\n"
        "import SupplierView from './Supplier/SupplierView';\n"
        "const SupplierPage: React.FC = () => <SupplierView />;\nexport default SupplierPage;\n")},
    "view_file": {"path": P["view_file"], "content": (
        "import { IonPage, IonContent, IonLoading, IonToast, IonInfiniteScroll } from '@ionic/react';\n"
        "import Header from '../../../components/layout/Header';\n"
        "import { usePopovers } from '../../../hooks/usePopovers';\n"
        "import { useSupplier } from './SupplierLogic';\n"
        "const SupplierView = () => { const vm = useSupplier(); const pops = usePopovers();\n"
        "  return <IonPage><Header screenTitle='Proveedores' {...pops.headerProps} /><IonContent>\n"
        "  {vm.items.map(i => toHermosillo(i.created_At))}<IonInfiniteScroll />\n"
        "  <IonToast {...vm.toastProps} /><IonLoading isOpen={vm.loading} /></IonContent></IonPage>; };\n")},
    "logic_file": {"path": P["logic_file"], "content": (
        "import { useIonViewWillEnter } from '@ionic/react';\n"
        "import { toHermosillo } from '../../../utils/format';\n"
        "export const useSupplier = () => { useIonViewWillEnter(() => {}); return {}; };\n"
        "export type SupplierVM = ReturnType<typeof useSupplier>;\n")},
    "css_file": {"path": P["css_file"], "content": ".supplier-content {}"},
    "app_patches": {"import_line": P["app_import_line"], "private_route": "x", "menu_item": "x"},
    "setting_patch": {"section": "Catálogo", "code": "suppliers"},
}


def _errors(fe, spec=SPEC):
    return [i for i in _check_frontend(fe, spec, {}) if i.severity != "warning"]


def test_compliant_mvvm_module_has_no_errors():
    assert _errors(GOOD) == []


def _with(key, content=None, path=None):
    fe = copy.deepcopy(GOOD)
    if content is not None:
        fe[key]["content"] = content
    if path is not None:
        fe[key]["path"] = path
    return fe


def test_fetch_in_view_is_flagged_on_the_view():
    fe = _with("view_file", GOOD["view_file"]["content"] + "fetch('/x');\n")
    assert any(i.file == P["view_file"] and "fetch()" in i.message for i in _errors(fe))


def test_shell_with_state_is_flagged():
    fe = _with("page_file", GOOD["page_file"]["content"] + "const [a] = useState(0);\n")
    assert any(i.file == P["page_file"] and "Router shell" in i.message for i in _errors(fe))


def test_missing_logic_file_is_flagged():
    fe = _with("logic_file", "")
    assert any("logic_file missing" in i.message for i in _errors(fe))


def test_wrong_path_is_flagged_with_the_expected_path():
    fe = _with("view_file", path="src/pages/SupplierView.tsx")
    assert any(i.message.startswith(f"view_file path must be {P['view_file']}") for i in _errors(fe))


def test_flat_app_import_line_is_flagged():
    fe = copy.deepcopy(GOOD)
    fe["app_patches"]["import_line"] = "import SupplierPage from './pages/SupplierPage';"
    assert any("import_line must be" in i.message for i in _errors(fe))


def test_legacy_single_page_spec_keeps_old_behaviour():
    legacy = {"page_file": {"content": "import Header from '../components/Header';"}, "api_file": {"content": ""}}
    msgs = [i.message for i in _errors(legacy, {"module": "supplier", "frontend": {}})]
    assert not any("MVVM" in m or "Router shell" in m for m in msgs)
    assert not any(m.startswith("Missing: import Header") for m in msgs)


# ---------------------------------------------------------------------------
# fixers + retry
# ---------------------------------------------------------------------------

def test_fixer_repairs_catch_any_in_logic_file():
    fe = _with("logic_file", "try { x() } catch (err: any) { }")
    fe, fixes = fix_frontend(fe, {})
    assert "catch (err: any)" not in fe["logic_file"]["content"] and fixes


def test_review_fixer_targets_the_issue_file():
    assert _frontend_key_for(GOOD, P["view_file"]) == "view_file"
    assert _frontend_key_for(GOOD, "src/pages/other/SupplierLogic.ts") == "logic_file"
    assert _frontend_key_for(GOOD, "") == "page_file"


def test_retry_requires_view_and_logic():
    assert has_frontend_files(json.dumps(GOOD))
    assert not has_frontend_files(json.dumps(_with("view_file", "")))
