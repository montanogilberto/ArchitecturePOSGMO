"""Review Fixer — deterministic fixes driven by reviewer error list."""
from __future__ import annotations

import json
import re

from google.adk.tools.tool_context import ToolContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load(key: str, tool_context: ToolContext) -> dict:
    raw = tool_context.state.get(key, "{}")
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (json.JSONDecodeError, TypeError):
        return {}


def _save(key: str, value: dict, tool_context: ToolContext) -> None:
    tool_context.state[key] = json.dumps(value)


# ---------------------------------------------------------------------------
# Frontend fixes
# ---------------------------------------------------------------------------

def _fix_auth_context(content: str) -> str:
    """Replace AuthContext usage with useUser hook."""
    # Remove AuthContext import lines
    content = re.sub(
        r"import\s+\{[^}]*AuthContext[^}]*\}\s+from\s+['\"][^'\"]+['\"];\n?",
        "",
        content,
    )
    content = re.sub(
        r"import\s+AuthContext\s+from\s+['\"][^'\"]+['\"];\n?",
        "",
        content,
    )
    # Replace useContext(AuthContext) patterns
    content = re.sub(
        r"const\s+\{([^}]+)\}\s*=\s*useContext\s*\(\s*AuthContext\s*\);?",
        lambda m: (
            "import { useUser } from '../components/UserContext';\n"
            "const { companyId, userId, roleCode, username } = useUser();"
        ),
        content,
    )
    # Add useUser import if not already present
    if "useUser" not in content:
        content = "import { useUser } from '../components/UserContext';\n" + content
    # Fix user?.companyId → companyId (useUser exposes it directly)
    content = content.replace("user?.companyId", "companyId")
    content = content.replace("user.companyId", "companyId")
    return content


def _fix_truncated_tags(content: str) -> str:
    """Detect and complete truncated JSX closing tags like </IonCar."""
    # Find </Word that is not followed by > (possibly with more chars then >)
    # Pattern: </ then word chars that don't end with >
    def _complete_tag(m: re.Match) -> str:
        partial = m.group(1)
        # Try to find the full tag name by looking for opened tags
        full_tags = re.findall(r"<(Ion\w+|[A-Z]\w*)", content)
        for tag in reversed(full_tags):
            if tag.startswith(partial):
                return f"</{tag}>"
        return m.group(0)  # leave unchanged if we can't determine

    content = re.sub(r"</(Ion\w{2,20}?)(?=[^a-zA-Z>]|$)", _complete_tag, content)
    return content


def _fix_catch_any(content: str) -> str:
    """Replace catch (err: any) with properly typed catch."""
    content = re.sub(
        r"catch\s*\(\s*(\w+)\s*:\s*any\s*\)",
        r"catch (\1)",
        content,
    )
    return content


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def apply_review_fixes(tool_context: ToolContext) -> dict:
    """
    Reads review_result.issues, applies deterministic fixes to artifacts,
    and writes corrected versions back to session state.
    """
    review = _load("review_result", tool_context)
    issues = review.get("issues", [])
    errors = [i for i in issues if i.get("severity") == "error"]

    if not errors:
        return {"fixed": [], "skipped": [], "note": "no errors to fix"}

    frontend = _load("frontend_artifacts", tool_context)
    fixed: list[str] = []
    skipped: list[str] = []

    fe_dirty = False

    for issue in errors:
        artifact = issue.get("artifact", "")
        message  = issue.get("message", "")
        msg_lo   = message.lower()

        if artifact == "frontend":
            page = frontend.get("page_file", {})
            content = page.get("content", "")
            if not content:
                skipped.append(f"[frontend] no page_file content — {message}")
                continue

            original = content

            if "authcontext" in msg_lo or "usecontext(authcontext)" in msg_lo or "user?.companyid" in msg_lo:
                content = _fix_auth_context(content)

            if "truncat" in msg_lo or "closing tag" in msg_lo or "</ion" in msg_lo.replace(" ", ""):
                content = _fix_truncated_tags(content)

            if "catch" in msg_lo and "any" in msg_lo:
                content = _fix_catch_any(content)

            if content != original:
                frontend["page_file"]["content"] = content
                fe_dirty = True
                fixed.append(f"[frontend] {message}")
            else:
                skipped.append(f"[frontend] no pattern matched — {message}")

        else:
            skipped.append(f"[{artifact}] manual fix required — {message}")

    if fe_dirty:
        _save("frontend_artifacts", frontend, tool_context)

    print(
        f"[review_fixer] fixed={len(fixed)} skipped={len(skipped)}",
        flush=True,
    )
    return {"fixed": fixed, "skipped": skipped}
