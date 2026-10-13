"""
GMO module knowledge — read from Product/GMO_MODULES.md (no LLM).

That Markdown file is the human-maintained list of what GMO already has and
how each module is wired (frontend → backend → database, or the agent
endpoint). Matching a request to modules is plain keyword matching, so the
Business Intake agent knows "what exists" before spending a model call, and
the model only receives the modules that matter plus a one-line index of
the rest.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

MODULES_MD = Path(__file__).resolve().parents[3] / "Product" / "GMO_MODULES.md"
_FIELDS = ("id", "kind", "keywords", "does", "frontend", "backend", "database", "agents",
           "domain", "owner", "mobile", "web", "configuration", "dependencies")
_WIRING = ("frontend", "backend", "database", "agents")


@dataclass
class Module:
    name: str
    application: str
    id: str = ""
    kind: str = "module"
    does: str = ""
    keywords: List[str] = field(default_factory=list)
    wiring: Dict[str, str] = field(default_factory=dict)
    registry: Dict[str, str] = field(default_factory=dict)   # domain, owner, mobile, web, configuration, dependencies

    def as_evidence(self) -> dict:
        return {"id": self.id, "name": self.name, "application": self.application, "kind": self.kind,
                "does": self.does, "wiring": self.wiring, **self.registry}

    def index_line(self) -> str:
        return f"{self.name} ({self.application}, {self.kind}): {self.does}"


def normalize(text: str) -> str:
    """Lowercase, no accents, single spaces — so 'Préstamo' matches 'prestamo'."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def parse_modules(markdown: str) -> List[Module]:
    modules: List[Module] = []
    application = ""
    current: Module | None = None
    for raw in markdown.splitlines():
        line = raw.strip()
        if line.startswith("## ") and not line.startswith("### "):
            application = line[3:].split("—")[0].strip()
            current = None
        elif line.startswith("### "):
            current = Module(name=line[4:].strip(), application=application)
            modules.append(current)
        elif current and line.startswith("- ") and ":" in line:
            key, value = (part.strip() for part in line[2:].split(":", 1))
            if key not in _FIELDS:
                continue
            if key == "keywords":
                current.keywords = [k.strip() for k in value.split(",") if k.strip()]
            elif key in ("id", "kind", "does"):
                setattr(current, key, value)
            elif key in _WIRING:
                current.wiring[key] = value
            else:
                current.registry[key] = value
    return [m for m in modules if m.id and m.application and m.application.lower() != "format"]


_cache: dict = {"mtime": None, "modules": [], "version": ""}


def load_modules() -> List[Module]:
    """Parsed GMO_MODULES.md, re-read automatically when the file changes."""
    mtime = MODULES_MD.stat().st_mtime
    if _cache["mtime"] != mtime:
        text = MODULES_MD.read_text(encoding="utf-8")
        _cache.update(mtime=mtime, modules=parse_modules(text), version=hashlib.sha256(text.encode()).hexdigest()[:12])
    return _cache["modules"]


def modules_version() -> str:
    """Changes whenever GMO_MODULES.md changes (used to invalidate cached answers)."""
    load_modules()
    return _cache["version"]


def match_modules(text: str) -> List[Module]:
    """Modules whose keywords appear in the text (whole-word, accent- and case-insensitive)."""
    haystack = f" {normalize(text)} "
    found = []
    for module in load_modules():
        if any(f" {normalize(k)} " in haystack for k in module.keywords if normalize(k)):
            found.append(module)
    return found
