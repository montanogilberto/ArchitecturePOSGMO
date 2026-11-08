"""feature_registry — deterministic, zero-LLM.

Every generated module must register itself in the module/feature registry
(dbo.uiFeatures + dbo.roleUiFeatures). Before 2026-11-07 the factory only
patched the frontend fallbacks (Setting.tsx MODULES, rolePermissions ROLE_UI),
which GET /roles overwrites on every app start — so every factory module
shipped invisible until someone hand-wrote a grant migration.

This stage reads what frontend_agent already decided (app_patches,
setting_patch, rolePermissions_patch) and appends one
`EXEC dbo.sp_uiFeatures_register` call to database_artifacts as
`feature_registration`. The PR agent concatenates it into
sql_logic/sp_{module}.sql, so running the module's SQL also registers it.

The SP is idempotent and never revokes (backend sql/sp_uiFeatures.sql).
"""
from __future__ import annotations

import json
import re
from typing import Any

# Sections /setting renders; anything else falls back to "Administración".
SETTING_SECTIONS = ("POS", "Catálogo", "Mensajes", "Administración", "IOT", "Entretenimiento")
DEFAULT_SECTION = "Administración"
DEFAULT_ICON = "settingsOutline"
STAFF_ROLES = ("admin", "manager", "employee", "business", "viewer")
_SAFE_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,49}$")
_ICON = re.compile(r"^[a-z][A-Za-z0-9]{0,49}$")
_ROUTE_IN_PRIVATE_ROUTE = re.compile(r'path=\{?["\']([^"\']+)["\']')


def _load(state: Any, key: str) -> dict:
    raw = state.get(key, "{}")
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    raw = raw.strip()
    if raw.startswith("```"):
        raw = "\n".join(l for l in raw.splitlines() if not l.strip().startswith("```")).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _sql_str(value: str) -> str:
    """N'...' literal with quotes escaped."""
    return "N'" + value.replace("'", "''") + "'"


def build_registration(frontend: dict, module: str = "", module_title: str = "") -> dict | None:
    """The sp_uiFeatures_register payload for this module, or None when the
    frontend artifacts carry no usable feature code."""
    app = frontend.get("app_patches") or {}
    setting = frontend.get("setting_patch") or {}
    perms = frontend.get("rolePermissions_patch") or {}

    code = str(app.get("canAccess_key") or setting.get("code") or "").strip().strip("'\"")
    if not _SAFE_CODE.match(code):
        return None

    label = str(setting.get("label") or app.get("menu_label") or "").strip() or None
    section = str(setting.get("section") or app.get("menu_section") or "").strip()
    section = section if section in SETTING_SECTIONS else DEFAULT_SECTION
    icon = str(setting.get("icon") or "").strip()
    icon = icon if _ICON.match(icon) else DEFAULT_ICON

    route = None
    m = _ROUTE_IN_PRIVATE_ROUTE.search(str(app.get("private_route") or ""))
    if m and m.group(1).startswith("/"):
        route = m.group(1)

    roles = [str(r).strip().lower() for r in (perms.get("roles_to_add") or []) if str(r).strip()]
    roles = [r for r in roles if r in STAFF_ROLES]
    if "admin" not in roles:
        roles.insert(0, "admin")  # same rule the frontend prompt states: always admin

    return {
        "featureCode": code,
        "displayName": module_title or module or code,
        "label": label,
        "section": section,
        "icon": icon,
        "route": route,
        "roles": roles,
    }


def registration_sql(payload: dict) -> str:
    body = json.dumps({"uiFeatures": [payload]}, ensure_ascii=False)
    return (
        f"-- Register '{payload['featureCode']}' in the module/feature registry so /setting\n"
        "-- and GET /roles show it (posgmo-factory feature_registry stage).\n"
        f"EXEC [dbo].[sp_uiFeatures_register] @pjsonfile = {_sql_str(body)};\n"
        "GO\n"
    )


def run_feature_registry(tool_context: Any) -> dict:
    state = tool_context.state
    frontend = _load(state, "frontend_artifacts")
    db = _load(state, "database_artifacts")
    payload = build_registration(frontend, str(state.get("module") or ""), str(state.get("Module") or ""))
    if payload is None:
        report = {"status": "skipped", "reason": "frontend_artifacts has no valid canAccess_key"}
    else:
        db["feature_registration"] = registration_sql(payload)
        state["database_artifacts"] = json.dumps(db)
        report = {"status": "registered", "featureCode": payload["featureCode"],
                  "section": payload["section"], "roles": payload["roles"]}
    state["feature_registry_report"] = json.dumps(report)
    return report
