"""knowledge_sync: merge rules (curated knowledge is never lost) and the
deterministic extractors, against tiny fixture repos — no real repo, no DB."""
from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

from knowledge_sync import extractors
from knowledge_sync.sync import merge


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------

def test_merge_refreshes_extracted_fields_and_keeps_curated_ones():
    existing = [{"path": "/expense", "file": "routes_/old.py", "tags": ["Curated tag"]}]
    extracted = [{"path": "/expense", "file": "routes_/expenses.py", "tags": ["expenses"], "methods": ["POST"]}]
    merged, diff = merge(existing, extracted, "path", refresh=("file", "methods"))
    assert merged == [{"path": "/expense", "file": "routes_/expenses.py", "tags": ["Curated tag"],
                       "methods": ["POST"]}]
    assert diff["added"] == [] and diff["stale"] == []


def test_merge_adds_new_entries_and_marks_vanished_ones_stale_not_deleted():
    existing = [{"name": "sp_gone", "parameters": []}]
    extracted = [{"name": "sp_new", "parameters": ["@pjsonfile"]}]
    merged, diff = merge(existing, extracted, "name", refresh=("parameters",))
    assert {"name": "sp_gone", "parameters": [], "stale": True} in merged
    assert {"name": "sp_new", "parameters": ["@pjsonfile"], "source": "knowledge_sync"} in merged
    assert diff["added"] == ["sp_new"] and diff["stale"] == ["sp_gone"]


def test_merge_revives_a_stale_entry_that_reappears():
    merged, diff = merge([{"name": "sp_x", "stale": True}], [{"name": "sp_x"}], "name", refresh=())
    assert merged == [{"name": "sp_x"}] and diff["revived"] == ["sp_x"]


def test_merge_detects_a_moved_file_and_keeps_its_curated_description():
    existing = [{"filePath": "src/components/Receipt.tsx", "componentName": "Receipt",
                 "description": "curated"}]
    extracted = [{"filePath": "src/components/pos/Receipt.tsx", "componentName": "Receipt", "folder": "pos"}]
    merged, diff = merge(existing, extracted, "filePath", refresh=("folder",), rename_key="componentName")
    assert merged == [{"filePath": "src/components/pos/Receipt.tsx", "componentName": "Receipt",
                       "description": "curated", "folder": "pos"}]
    assert diff["moved"] and not diff["added"] and not diff["stale"]


def test_merge_ambiguous_move_is_not_guessed():
    existing = [{"filePath": "src/components/Card.tsx", "componentName": "Card"}]
    extracted = [{"filePath": "src/components/a/Card.tsx", "componentName": "Card"},
                 {"filePath": "src/components/b/Card.tsx", "componentName": "Card"}]
    _, diff = merge(existing, extracted, "filePath", refresh=(), rename_key="componentName")
    assert diff["moved"] == [] and diff["stale"] == ["src/components/Card.tsx"]


def test_merge_covered_entry_stays_alive():
    existing = [{"path": "/stripe", "file": "routes_/stripe_payments.py"}]
    extracted = [{"path": "/stripe/payment-intents", "file": "routes_/stripe_payments.py"}]
    merged, diff = merge(existing, extracted, "path", refresh=(),
                         covered=lambda old, found: any(p.startswith(old["path"] + "/") for p in found))
    assert "stale" not in merged[0] and diff["stale"] == []


# ---------------------------------------------------------------------------
# extractors (fixture repos)
# ---------------------------------------------------------------------------

def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text), encoding="utf-8")


@pytest.fixture
def backend(tmp_path):
    _write(tmp_path, "routes_/inventory.py", '''
        from fastapi import APIRouter
        router = APIRouter(prefix="/inventory", tags=["Inventory"])

        @router.get("/stock")
        def stock(): ...

        @router.post(
            "/adjust", summary="multi-line decorator")
        def adjust(): ...
    ''')
    _write(tmp_path, "routes_/plain.py", '''
        from fastapi import APIRouter
        router = APIRouter()

        @router.post("/plain")
        def plain_post(): ...

        @router.get("/plain")
        def plain_get(): ...
    ''')
    _write(tmp_path, "modules/inventory.py", 'cursor.execute("EXEC [dbo].[sp_inventory_adjust] @pjsonfile = %s")\n')
    return tmp_path


def test_backend_routes_apply_prefix_methods_and_default_tags(backend):
    routes = {r["path"]: r for r in extractors.backend_routes(backend)}
    assert set(routes) == {"/inventory/stock", "/inventory/adjust", "/plain"}
    assert routes["/inventory/adjust"]["tags"] == ["Inventory"]
    assert routes["/plain"]["methods"] == ["POST", "GET"]
    assert routes["/plain"]["tags"] == ["plain"] and routes["/plain"]["file"] == "routes_/plain.py"


def test_sp_module_bindings(backend):
    assert extractors.sp_module_bindings(backend) == {"sp_inventory_adjust": "modules/inventory.py"}


@pytest.fixture
def frontend(tmp_path):
    _write(tmp_path, "src/App.tsx", '''
        import InventoryPage from './pages/inventory/InventoryPage';
        const Lazy = React.lazy(() => import('./pages/inventory/LazyPage'));
        <PrivateRoute exact path="/inventory" feature="inventory" component={InventoryPage} />
        <Route exact path="/old" render={() => <Redirect to="/inventory" />} />
        <Route path="/lazy" component={Lazy} />
    ''')
    _write(tmp_path, "src/pages/inventory/InventoryPage.tsx", "export default () => null;\n")
    _write(tmp_path, "src/pages/inventory/LazyPage.tsx", "export default () => null;\n")
    _write(tmp_path, "src/pages/inventory/Stock/StockView.tsx", "")
    _write(tmp_path, "src/pages/inventory/Stock/StockLogic.ts", "")
    _write(tmp_path, "src/pages/inventory/Legacy/Legacy.tsx", "")
    _write(tmp_path, "src/components/ui/StockBadge.tsx", '''
        interface StockBadgeProps {
          qty: number;
          label?: string; // optional
        }
    ''')
    return tmp_path


def test_frontend_routes_resolve_components_auth_and_redirects(frontend):
    routes = {r["path"]: r for r in extractors.frontend_routes(frontend)}
    assert routes["/inventory"] == {"path": "/inventory", "component": "src/pages/inventory/InventoryPage.tsx",
                                    "authenticated": True, "feature": "inventory"}
    assert routes["/old"]["component"] == "redirect"
    assert routes["/lazy"]["component"] == "src/pages/inventory/LazyPage.tsx"
    assert routes["/lazy"]["authenticated"] is False


def test_frontend_features_detect_mvvm(frontend):
    feats = {f["feature"]: f for f in extractors.frontend_features(frontend)}
    assert feats["Stock"]["mvvm"] is True and feats["Legacy"]["mvvm"] is False


def test_frontend_components_parse_props(frontend):
    [comp] = extractors.frontend_components(frontend)
    assert comp["componentName"] == "StockBadge" and comp["folder"] == "ui"
    assert comp["props"] == [{"name": "qty", "type": "number", "required": True},
                             {"name": "label", "type": "string", "required": False}]


def test_agents_catalog_reads_agent_definition(tmp_path):
    _write(tmp_path, "agents/pos_inventory_support/agent.py", '''
        from google.adk.agents import Agent
        from google.adk.tools import FunctionTool
        pos_inventory_support_agent = Agent(
            name="pos_inventory_support_agent",
            model="gemini-2.5-flash",
            description="Explains stock.",
            tools=[FunctionTool(func=get_stock), FunctionTool(func=propose_action)],
        )
    ''')
    [agent] = extractors.agents_catalog(tmp_path)
    assert agent["name"] == "pos_inventory_support_agent"
    assert agent["tools"] == ["get_stock", "propose_action"] and agent["proposes_writes"] is True


def test_backend_modules_link_routes_sps_and_observability(backend):
    _write(backend, "routes_/inventoryRoute.py", "from modules.inventory import adjust\n")
    _write(backend, "modules/plain.py", "x = 1\n")
    mods = {m["module"]: m for m in extractors.backend_modules(backend)}
    assert mods["inventory"]["routeFiles"] == ["routes_/inventoryRoute.py"]
    assert mods["inventory"]["storedProcedures"] == ["sp_inventory_adjust"]
    assert mods["plain"]["observable"] is False and mods["plain"]["routeFiles"] == []


def test_firmware_catalog_lists_calls_and_never_reads_config(tmp_path):
    _write(tmp_path, "esp32/api.py", 'net.post("/laundryDevices/quote", {})\nnet.post(\n  "/laundryDevices/balance", {})\n')
    _write(tmp_path, "esp32/config.py", 'DEVICE_KEY = "secret"\nnet.post("/leak", {})\n')
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-f", "esp32"], check=True)  # worst case: config tracked
    catalog = extractors.firmware_catalog(tmp_path)
    assert catalog == [{"file": "esp32/api.py",
                        "backendCalls": ["POST /laundryDevices/balance", "POST /laundryDevices/quote"]}]
