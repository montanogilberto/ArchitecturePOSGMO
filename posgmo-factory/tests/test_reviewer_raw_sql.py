"""
Reviewer's raw-SQL check -- rewritten after a 2026-09-23 audit of
smartloans_backend found 23 raw SQL statements in modules/; the old rule
flagged only 7 of them.

The old rule was `re.findall(r'cursor\\.execute\\s*\\(\\s*["\\'](?!EXEC)', ...)`:
it only fired when the cursor variable was literally named `cursor`. The
other 16 real violations all used `cur.execute(...)`. It also missed SQL held in a
variable and f-strings. The fixtures below are the real shapes from that
audit (modules/stripe_payments.py, mercadolibre.py, rewardBenefits.py, ...).

Both directions are tested: every real violation shape must be caught, and
the legitimate patterns every generated module uses (EXEC calls, docstrings
that describe SQL, route summaries with the word "select") must not be.
"""
from agents.reviewer.raw_sql import find_raw_sql
from agents.reviewer.rules import _check_backend


def _kinds(src: str) -> list[str]:
    return [h.kind for h in find_raw_sql(src)]


# ── Must be caught ─────────────────────────────────────────────────────────

def test_cur_execute_select_is_caught():
    """stripe_payments.py::_client_contact -- the case that started the audit;
    invisible to the old rule because the variable is `cur`."""
    src = '''
def _client_contact(client_id):
    conn = connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT email, first_name, last_name FROM dbo.clients WHERE clientId = %s",
        (client_id,))
    return cur.fetchone()
'''
    assert _kinds(src) == ["execute_literal"]


def test_triple_quoted_insert_is_caught():
    """mercadolibre.py::save_oauth_state -- a WRITE, via `cur`."""
    src = '''
def save_oauth_state(state, code_verifier):
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO dbo.ml_oauth_states (state, code_verifier)
            VALUES (%s, %s)
            """,
            (state, code_verifier),
        )
'''
    assert _kinds(src) == ["execute_literal"]


def test_implicitly_concatenated_literal_is_caught():
    """rewardBenefits.py::_rule -- two adjacent literals are one ast.Constant."""
    src = '''
def _rule(company_id, rule_type):
    cur = connection().cursor()
    cur.execute(
        "SELECT TOP 1 ruleId, pointsPerUnit, maxPointsPerTx FROM rewardRules "
        "WHERE companyId = %s AND ruleType = %s AND isActive = 1 ORDER BY ruleId",
        (company_id, rule_type),
    )
'''
    assert _kinds(src) == ["execute_literal"]


def test_sql_held_in_a_variable_is_caught():
    src = '''
QUERY = "SELECT TOP 1 userId FROM users WHERE clientId = %s"

def resolve(cursor, client_id):
    cursor.execute(QUERY, (client_id,))
'''
    hits = find_raw_sql(src)
    assert [h.kind for h in hits] == ["sql_literal"]
    assert hits[0].line == 2


def test_fstring_sql_is_caught():
    src = '''
def load(cursor, table, cols):
    cursor.execute(f"SELECT {cols} FROM dbo.{table}")
'''
    assert _kinds(src) == ["execute_literal"]


def test_lowercase_sql_straight_into_execute_is_caught():
    src = 'def f(db):\n    db.execute("update dbo.ml_tokens set access_token = %s", ("x",))\n'
    assert _kinds(src) == ["execute_literal"]


def test_executemany_is_caught():
    src = 'def f(c, rows):\n    c.executemany("INSERT INTO dbo.t (a) VALUES (%s)", rows)\n'
    assert _kinds(src) == ["execute_literal"]


def test_unparseable_source_falls_back_to_regex():
    """Generated content can be mid-repair; a SyntaxError must not silence the check."""
    src = 'def broken(:\n    cur.execute("DELETE FROM dbo.t WHERE id = %s", (1,))\n'
    assert _kinds(src) == ["execute_literal"]


# ── Must NOT be caught ─────────────────────────────────────────────────────

def test_exec_calls_are_clean():
    src = '''
def things_sp(json_file):
    conn = connection()
    cursor = conn.cursor()
    cursor.execute("EXEC sp_things @pjsonfile = %s", (json.dumps(json_file),))
    cur = conn.cursor()
    cur.execute("EXEC [dbo].[sp_things_all] @pjsonfile = %s", ("{}",))
    cur.execute(f"EXEC [dbo].[{sp_name}] @pjsonfile = %s", ("{}",))
    cur.execute(\'\'\'
        EXEC sp_things_one @pjsonfile = %s
    \'\'\', ("{}",))
'''
    assert find_raw_sql(src) == []


def test_docstring_describing_sql_is_clean():
    src = '''
def _resolve(cursor, client_id):
    """Old code did `SELECT TOP 1 userId FROM users WHERE clientId = %s`;
    now sp_pushNotifications_resolveUsers does it."""
    cursor.execute("EXEC sp_pushNotifications_resolveUsers @pjsonfile = %s", ("{}",))
'''
    assert find_raw_sql(src) == []


def test_prose_with_the_word_select_is_clean():
    """routes_/utils.py route summaries -- lowercase prose, not SQL."""
    src = '''
@router.get("/tables", summary="select information about the all tables")
def tables():
    return "select all information from the table"
'''
    assert find_raw_sql(src) == []


def test_comment_with_sql_is_clean():
    src = '# SELECT TOP 1 userId FROM users WHERE clientId = %s\nx = 1\n'
    assert find_raw_sql(src) == []


# ── Wired into the reviewer ────────────────────────────────────────────────

def _backend_raw_sql_issues(module_content: str) -> list[str]:
    be = {
        "module_file": {"path": "modules/things.py", "content": module_content},
        "route_file": {"path": "routes_/thing.py", "content": ""},
    }
    issues = _check_backend(be, {"module": "thing"}, {})
    return [i.message for i in issues if "Raw SQL" in i.message]


def test_reviewer_flags_cur_execute():
    msgs = _backend_raw_sql_issues(
        'def f(conn):\n    cur = conn.cursor()\n'
        '    cur.execute("SELECT cellphone FROM dbo.clients WHERE clientId = %s", (1,))\n'
    )
    assert len(msgs) == 1
    assert "line 3" in msgs[0] and "dbo.clients" in msgs[0]


def test_reviewer_one_issue_per_site():
    msgs = _backend_raw_sql_issues(
        'def f(cur):\n'
        '    cur.execute("SELECT 1 FROM users WHERE userId = %s", (1,))\n'
        '    cur.execute("SELECT TOP 1 userId FROM users WHERE clientId = %s", (1,))\n'
    )
    assert len(msgs) == 2


def test_reviewer_clean_module_has_no_raw_sql_issue():
    assert _backend_raw_sql_issues(
        'def things_sp(json_file):\n'
        '    cursor.execute("EXEC sp_things @pjsonfile = %s", (json.dumps(json_file),))\n'
    ) == []
