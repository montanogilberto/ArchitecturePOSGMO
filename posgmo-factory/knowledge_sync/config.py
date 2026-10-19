"""Where the product repos live. Override per machine in posgmo-factory/.env."""
from __future__ import annotations

import os
from pathlib import Path

FACTORY_ROOT = Path(__file__).resolve().parent.parent      # posgmo-factory/
KNOWLEDGE_ROOT = FACTORY_ROOT.parent                        # Agent_POSGMO/ (same as mcp_server)

_HOME = Path.home()
_DEFAULTS = {
    "frontend": _HOME / "PycharmProjects/POSVendingV2/POSVending",
    "backend": _HOME / "PycharmProjects/pythonProject/smartloans_backend",
    "agents": _HOME / "LoanAgents_SmartLoans",
}
_ENV = {
    "frontend": "POS_FRONTEND_REPO_PATH",
    "backend": "BACKEND_REPO_PATH",
    "agents": "AGENTS_REPO_PATH",
}


def repo_paths() -> dict[str, Path]:
    """{"frontend"|"backend"|"agents": Path} — env var wins over the default."""
    return {k: Path(os.getenv(_ENV[k]) or _DEFAULTS[k]).expanduser() for k in _DEFAULTS}
