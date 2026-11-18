"""Frontend/customer_app_modules.json — curated breakdown of the customer app.

It's hand-written, so these checks keep it honest against the synced knowledge:
every endpoint must exist in Backend/backend_routes.json.json (unless marked
pending), and every reference inside the file must resolve.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.server import KNOWLEDGE_ROOT, get_customer_app_modules

DATA = json.loads((KNOWLEDGE_ROOT / "Frontend/customer_app_modules.json").read_text(encoding="utf-8"))
MODULES = DATA["modules"]
KEYS = {m["key"] for m in MODULES}


def _live_route_paths() -> set[str]:
    routes = json.loads((KNOWLEDGE_ROOT / "Backend/backend_routes.json.json").read_text(encoding="utf-8"))["routes"]
    return {r["path"] for r in routes if not r.get("stale")}


def test_module_keys_are_unique():
    assert len(KEYS) == len(MODULES)


def test_every_module_has_the_onboarding_fields():
    required = {"key", "featureKey", "name", "status", "route", "requiresLogin", "purpose",
                "frontend", "endpoints", "tables", "dependsOn", "perCompanyData", "hardcodedToday", "rules"}
    for m in MODULES:
        assert required <= m.keys(), f"{m.get('key')} is missing {required - m.keys()}"
        assert m["status"] in {"live", "pending_backend"}


def test_depends_on_points_at_known_modules():
    for m in MODULES:
        assert set(m["dependsOn"]) <= KEYS, f"{m['key']} depends on an unknown module"


def test_endpoints_exist_in_backend_routes_unless_pending():
    live = _live_route_paths()
    missing = [(m["key"], e["path"]) for m in MODULES for e in m["endpoints"]
               if not e.get("pending") and e["path"] not in live]
    assert not missing, f"not in backend_routes (mark pending or fix the path): {missing}"


def test_pending_endpoint_means_pending_module():
    for m in MODULES:
        if any(e.get("pending") for e in m["endpoints"]):
            assert m["status"] == "pending_backend", m["key"]


def test_tool_returns_whole_file_by_default():
    result = get_customer_app_modules()
    assert {"deliveryModels", "featureFlags", "modules", "companyOnboarding"} <= result.keys()


def test_tool_filters_one_module_case_insensitively():
    result = get_customer_app_modules("Reservations")
    assert result["module"]["key"] == "reservations"
    assert result["deliveryModels"]


def test_tool_unknown_key_lists_known_keys():
    result = get_customer_app_modules("nope")
    assert "error" in result
    assert "wallet" in result["known"]
