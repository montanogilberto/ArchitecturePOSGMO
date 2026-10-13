"""SQLite storage for visits, token usage and leads (one file, stdlib only).

The database lives in SITE_DATA_DIR (default posgmo-factory/data/). On Azure
App Service, point it at /home/data so it survives restarts and redeploys.
IP addresses are never stored raw — only a salted hash, to count abuse.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(os.getenv("SITE_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DB_PATH = DATA_DIR / "gmo_site.db"
VISIT_SESSION_MINUTES = 30
LEAD_STATUSES = ("new", "contacted", "qualified", "won", "lost")
_IP_SALT = os.getenv("SITE_IP_SALT", "gmo-ecosystem")

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS visits (
    visitId     INTEGER PRIMARY KEY AUTOINCREMENT,
    visitorId   TEXT NOT NULL,
    path        TEXT,
    language    TEXT,
    referrer    TEXT,
    ipHash      TEXT,
    created_At  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_visits_visitor ON visits (visitorId, created_At);
CREATE INDEX IF NOT EXISTS ix_visits_created ON visits (created_At);

CREATE TABLE IF NOT EXISTS tokenUsage (
    visitorId   TEXT PRIMARY KEY,
    tokensUsed  INTEGER NOT NULL DEFAULT 0,
    analyses    INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leads (
    leadId                  INTEGER PRIMARY KEY AUTOINCREMENT,
    fullName                TEXT NOT NULL,
    email                   TEXT,
    companyName             TEXT,
    phone                   TEXT,
    message                 TEXT,
    leadSource              TEXT NOT NULL,
    interestArea            TEXT,
    status                  TEXT NOT NULL DEFAULT 'new',
    notes                   TEXT,
    privacyConsentAccepted  INTEGER NOT NULL,
    visitorId               TEXT,
    language                TEXT,
    analysis                TEXT,
    ipHash                  TEXT,
    created_At              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_leads_status ON leads (status, created_At);
CREATE INDEX IF NOT EXISTS ix_leads_visitor ON leads (visitorId);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hash_ip(ip: str) -> str:
    return hashlib.sha256(f"{_IP_SALT}:{ip}".encode()).hexdigest()[:16]


def connection() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(_SCHEMA)
    return _conn


def reset_for_tests(path: Path) -> None:
    """Point the store at a fresh database file (tests only)."""
    global _conn, DB_PATH, DATA_DIR
    if _conn is not None:
        _conn.close()
    _conn, DATA_DIR, DB_PATH = None, path.parent, path


# ---------------------------------------------------------------- visits

def record_visit(visitor_id: str, path: str, language: str, referrer: str, ip: str) -> bool:
    """Counts a visit unless this visitor was already counted in the last 30 minutes.
    Returns True when a new visit was recorded."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=VISIT_SESSION_MINUTES)).isoformat(timespec="seconds")
    with _lock:
        db = connection()
        recent = db.execute("SELECT 1 FROM visits WHERE visitorId = ? AND created_At >= ? LIMIT 1", (visitor_id, cutoff)).fetchone()
        if recent:
            return False
        db.execute("INSERT INTO visits (visitorId, path, language, referrer, ipHash, created_At) VALUES (?, ?, ?, ?, ?, ?)",
                   (visitor_id, path[:200], language[:5], referrer[:300], hash_ip(ip), _now()))
        db.commit()
        return True


def visit_stats() -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    db = connection()
    total = db.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
    today_count = db.execute("SELECT COUNT(*) FROM visits WHERE created_At >= ?", (today,)).fetchone()[0]
    unique = db.execute("SELECT COUNT(DISTINCT visitorId) FROM visits").fetchone()[0]
    return {"total": total, "today": today_count, "uniqueVisitors": unique}


def visits_by_day(days: int = 30) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    rows = connection().execute(
        "SELECT substr(created_At, 1, 10) AS day, COUNT(*) AS visits, COUNT(DISTINCT visitorId) AS visitors "
        "FROM visits WHERE created_At >= ? GROUP BY day ORDER BY day", (since,)).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- tokens

def is_registered(visitor_id: str) -> bool:
    return connection().execute("SELECT 1 FROM leads WHERE visitorId = ? LIMIT 1", (visitor_id,)).fetchone() is not None


def tokens_used(visitor_id: str) -> int:
    row = connection().execute("SELECT tokensUsed FROM tokenUsage WHERE visitorId = ?", (visitor_id,)).fetchone()
    return row[0] if row else 0


def add_tokens(visitor_id: str, tokens: int) -> None:
    with _lock:
        db = connection()
        db.execute(
            "INSERT INTO tokenUsage (visitorId, tokensUsed, analyses, updated_at) VALUES (?, ?, 1, ?) "
            "ON CONFLICT(visitorId) DO UPDATE SET tokensUsed = tokensUsed + excluded.tokensUsed, "
            "analyses = analyses + 1, updated_at = excluded.updated_at",
            (visitor_id, max(0, int(tokens)), _now()))
        db.commit()


def token_totals() -> dict:
    row = connection().execute("SELECT COALESCE(SUM(tokensUsed), 0), COALESCE(SUM(analyses), 0), COUNT(*) FROM tokenUsage").fetchone()
    return {"tokens": row[0], "analyses": row[1], "visitorsWithAnalyses": row[2]}


# ---------------------------------------------------------------- leads

_LEAD_FIELDS = ("fullName", "email", "companyName", "phone", "message", "leadSource", "interestArea",
                "privacyConsentAccepted", "visitorId", "language")


def create_lead(lead: dict, analysis: dict | None, ip: str) -> int:
    now = _now()
    values = [lead.get(f) for f in _LEAD_FIELDS]
    with _lock:
        db = connection()
        cur = db.execute(
            f"INSERT INTO leads ({', '.join(_LEAD_FIELDS)}, analysis, ipHash, status, created_At, updated_at) "
            f"VALUES ({', '.join('?' * len(_LEAD_FIELDS))}, ?, ?, 'new', ?, ?)",
            (*values, json.dumps(analysis, ensure_ascii=False) if analysis else None, hash_ip(ip), now, now))
        db.commit()
        return cur.lastrowid


def recent_leads_from_ip(ip: str, minutes: int = 60) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    return connection().execute("SELECT COUNT(*) FROM leads WHERE ipHash = ? AND created_At >= ?",
                                (hash_ip(ip), cutoff)).fetchone()[0]


def list_leads(status: str | None = None, limit: int = 500) -> list[dict]:
    sql = "SELECT * FROM leads"
    args: tuple = ()
    if status:
        sql += " WHERE status = ?"
        args = (status,)
    rows = connection().execute(sql + " ORDER BY created_At DESC LIMIT ?", (*args, limit)).fetchall()
    leads = []
    for r in rows:
        lead = dict(r)
        lead.pop("ipHash", None)
        lead["privacyConsentAccepted"] = bool(lead["privacyConsentAccepted"])
        lead["analysis"] = json.loads(lead["analysis"]) if lead["analysis"] else None
        lead["tokensUsed"] = tokens_used(lead["visitorId"]) if lead["visitorId"] else 0
        leads.append(lead)
    return leads


def update_lead(lead_id: int, status: str | None, notes: str | None) -> bool:
    sets, args = [], []
    if status is not None:
        sets.append("status = ?"); args.append(status)
    if notes is not None:
        sets.append("notes = ?"); args.append(notes)
    if not sets:
        return False
    with _lock:
        db = connection()
        cur = db.execute(f"UPDATE leads SET {', '.join(sets)}, updated_at = ? WHERE leadId = ?", (*args, _now(), lead_id))
        db.commit()
        return cur.rowcount > 0


def lead_counts() -> dict:
    rows = connection().execute("SELECT status, COUNT(*) FROM leads GROUP BY status").fetchall()
    counts = dict.fromkeys(LEAD_STATUSES, 0)
    counts.update({r[0]: r[1] for r in rows})
    by_source = connection().execute("SELECT leadSource, COUNT(*) FROM leads GROUP BY leadSource").fetchall()
    return {"byStatus": counts, "bySource": {r[0]: r[1] for r in by_source}, "total": sum(counts.values())}
