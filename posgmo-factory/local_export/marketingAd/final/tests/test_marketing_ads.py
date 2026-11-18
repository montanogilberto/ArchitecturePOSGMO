"""
Client Acquisition, phase 1b: the ad set and campaign behind each WhatsApp lead.

Meta's referral carries only the ad id. The webhook leaves the ad 'pending';
marketingAdsSyncWorker resolves it later through the worker-key routes.
No database / no Meta / no agent: everything external is stubbed. The SQL tests
read the scripts as text: they pin the rules down, they do not execute them.

Run:  venv/bin/python -m unittest tests/test_marketing_ads.py -v
"""
import json
import os
import re
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)  # routes read ./docs_description at import

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import modules.marketingAds as ads  # noqa: E402
import modules.whatsappCloud as wc  # noqa: E402
import routes_.marketingAd as ads_routes  # noqa: E402
import security.worker_key as worker_key  # noqa: E402

KEY = "test-worker-key"
LAUNDRY = {"channelId": 2, "companyId": 1, "branchId": None, "phoneNumberId": "111", "botEnabled": True}
OTHER = {"channelId": 9, "companyId": 2, "branchId": 4, "phoneNumberId": "222", "botEnabled": True}
CHANNELS = {"111": LAUNDRY, "222": OTHER}
AD_ID = "120248369825700137"  # larger than INT: must stay text end to end
REFERRAL = {"source_type": "ad", "source_id": AD_ID, "ctwa_clid": "ARAkLkA8rmlFeiCktEJQ"}


def _message(referral=REFERRAL, wamid="wamid.A"):
    msg = {"from": "5216621234567", "id": wamid, "timestamp": "1762300000", "type": "text",
           "text": {"body": "Hola"}}
    if referral is not None:
        msg["referral"] = referral
    return msg


def _payload(*messages, phone_number_id="111"):
    return {"entry": [{"changes": [{"field": "messages", "value": {
        "metadata": {"phone_number_id": phone_number_id},
        "contacts": [{"wa_id": "5216621234567", "profile": {"name": "Ana"}}],
        "messages": list(messages),
    }}]}]}


def _sql(name):
    with open(os.path.join(ROOT, "sql", name), encoding="utf-8") as f:
        return f.read()


class WebhookPendingAdTest(unittest.TestCase):
    """AT1, AT3: a lead leaves its ad pending; a failure never costs the reply."""

    def setUp(self):
        wc._seen_messages.clear()
        self.calls = []
        self.record = mock.Mock(side_effect=lambda *_: self.calls.append("record") or 1)
        self.ensure = mock.Mock(side_effect=lambda *_: self.calls.append("ensure") or 5)
        self.reply_to = mock.Mock(side_effect=lambda *a, **k: self.calls.append("agent") or "¡Hola!")
        self.send_text = mock.Mock()
        for p in [
            mock.patch.object(wc.whatsappChannels, "get_channel", side_effect=CHANNELS.get),
            mock.patch.object(wc.marketingLeadAttributions, "record_referral", self.record),
            mock.patch.object(wc.marketingAds, "ensure_pending", self.ensure),
            mock.patch.object(wc.clientContactPreferences, "handle_keyword", return_value=None),
            mock.patch.object(wc.whatsappReservations, "reply_to", self.reply_to),
            mock.patch.object(wc, "log_message_to_database"),
            mock.patch.object(wc, "send_text", self.send_text),
        ]:
            p.start()
            self.addCleanup(p.stop)

    def _ad(self):
        return self.ensure.call_args.args[0]["marketingAds"][0]

    def test_a_lead_leaves_its_ad_pending(self):
        wc.handle_webhook(_payload(_message()))
        self.assertEqual(self._ad(), {"action": 1, "companyId": 1, "provider": "meta", "adId": AD_ID})

    def test_after_the_attribution_and_before_the_agent(self):
        wc.handle_webhook(_payload(_message()))
        self.assertEqual(self.calls, ["record", "ensure", "agent"])

    def test_company_comes_from_the_channel(self):
        wc.handle_webhook(_payload(_message(), phone_number_id="222"))
        self.assertEqual(self._ad()["companyId"], 2)

    def test_a_numeric_ad_id_is_sent_as_text(self):
        wc.handle_webhook(_payload(_message(referral={"source_id": 120248369825700137})))
        self.assertEqual(self._ad()["adId"], AD_ID)

    def test_no_referral_or_no_ad_id_leaves_nothing_pending(self):
        wc.handle_webhook(_payload(_message(referral=None)))
        wc.handle_webhook(_payload(_message(referral={"source_type": "post"}, wamid="wamid.B")))
        self.ensure.assert_not_called()
        self.assertEqual(self.send_text.call_count, 2)

    def test_a_failed_pending_save_still_answers_and_keeps_the_attribution(self):
        self.ensure.side_effect = RuntimeError("db down")
        wc.handle_webhook(_payload(_message()))
        self.record.assert_called_once()
        self.send_text.assert_called_once()

    def test_a_failed_attribution_skips_the_pending_ad_and_still_answers(self):
        self.record.side_effect = RuntimeError("db down")
        wc.handle_webhook(_payload(_message()))
        self.ensure.assert_not_called()
        self.send_text.assert_called_once()


class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=()):
        self.conn.statements.append((sql, params))

    def fetchall(self):
        return self.conn.rows


class _FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []
        self.closed = False

    def cursor(self):
        return _FakeCursor(self)

    def close(self):
        self.closed = True


def _rows(obj, split=None):
    text = json.dumps(obj)
    if split:  # SQL Server splits long JSON across rows
        return [(text[:split],), (text[split:],)]
    return [(text,)]


OK = {"result": [{"marketingAds": [{"marketingAdId": 5, "lookupStatus": "pending"}]}]}


class EnsurePendingTest(unittest.TestCase):
    def _run(self, rows, payload=None):
        self.conn = _FakeConnection(rows)
        with mock.patch.object(ads, "connection", return_value=self.conn):
            return ads.ensure_pending(payload or {"marketingAds": [{"action": 1, "companyId": 1,
                                                                    "provider": "meta", "adId": AD_ID}]})

    def test_returns_the_id_and_closes_the_connection(self):
        self.assertEqual(self._run(_rows(OK)), 5)
        self.assertTrue(self.conn.closed)

    def test_runs_only_the_ads_procedure_with_the_id_as_text(self):
        self._run(_rows(OK))
        self.assertEqual(len(self.conn.statements), 1)
        sql, params = self.conn.statements[0]
        self.assertEqual(sql, "EXEC [dbo].[sp_marketingAds] @pjsonfile = %s")
        self.assertEqual(json.loads(params[0])["marketingAds"][0]["adId"], AD_ID)

    def test_joins_split_rows(self):
        self.assertEqual(self._run(_rows(OK, split=10)), 5)

    def test_an_sp_error_raises_and_closes_the_connection(self):
        with self.assertRaisesRegex(RuntimeError, "unsupported_action"):
            self._run(_rows({"error": "unsupported_action"}))
        self.assertTrue(self.conn.closed)


class WorkerRoutesTest(unittest.TestCase):
    """AT8: both routes need the worker key; HTTP codes for the worker."""

    def setUp(self):
        self.key = mock.patch.object(worker_key, "WORKER_KEY", KEY)
        self.key.start()
        self.addCleanup(self.key.stop)
        app = FastAPI()
        app.include_router(ads_routes.router)
        self.client = TestClient(app)

    def _post(self, path, body, rows, key=KEY):
        self.conn = _FakeConnection(rows)
        headers = {"X-Worker-Key": key} if key else {}
        with mock.patch.object(ads, "connection", return_value=self.conn):
            return self.client.post(path, json=body, headers=headers)

    def test_both_routes_reject_a_missing_or_wrong_key(self):
        for path in ("/marketingAds", "/all_marketingAds"):
            for key in (None, "wrong"):
                with self.subTest(path=path, key=key):
                    r = self._post(path, {"marketingAds": [{"companyId": 1}]}, _rows(OK), key=key)
                    self.assertEqual(r.status_code, 403)
                    self.assertEqual(self.conn.statements, [])

    def test_a_resolved_lookup_is_written(self):
        body = {"marketingAds": [{"action": 2, "companyId": 1, "provider": "meta", "adId": AD_ID,
                                  "lookupStatus": "resolved", "adsetId": "120248369825720137"}]}
        r = self._post("/marketingAds", body, _rows({"result": [{"marketingAds": [
            {"marketingAdId": 5, "lookupStatus": "resolved"}]}]}))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(json.loads(self.conn.statements[0][1][0]), body)

    def test_an_unknown_ad_is_404(self):
        r = self._post("/marketingAds", {"marketingAds": [{"action": 2, "companyId": 1, "provider": "meta",
                                                           "adId": "1", "lookupStatus": "resolved"}]},
                       _rows({"error": "ad_not_found"}))
        self.assertEqual(r.status_code, 404)

    def test_unsupported_or_missing_action_never_reaches_the_db(self):
        for body in ({"marketingAds": [{"action": 3}]}, {"marketingAds": [{}]}, {}):
            with self.subTest(body=body):
                r = self._post("/marketingAds", body, _rows(OK))
                self.assertEqual(r.status_code, 400)
                self.assertEqual(self.conn.statements, [])

    def test_the_list_returns_the_procedure_result(self):
        listing = {"result": [{"marketingAds": [{"marketingAdId": 5, "adId": AD_ID, "lookupStatus": "pending"}]}]}
        r = self._post("/all_marketingAds", {"marketingAds": [{"companyId": 1, "lookupStatuses": ["pending"]}]},
                       _rows(listing, split=20))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), listing)
        self.assertIn("sp_marketingAds_all", self.conn.statements[0][0])


class SqlRulesTest(unittest.TestCase):
    """The scripts' rules, read as text (AT2, AT4-AT7, AT9-AT12)."""

    @classmethod
    def setUpClass(cls):
        cls.table = _sql("migrations/2026-11-12_marketingAds.sql")
        cls.sp = _sql("sp_marketingAds.sql")
        cls.all = _sql("sp_marketingAds_all.sql")
        cls.leads = _sql("sp_marketingLeadAttributions_all.sql")
        cls.backfill = _sql("migrations/2026-11-12_marketingAds_backfill.sql")

    def test_one_row_per_company_provider_ad(self):
        self.assertRegex(self.table, r"UNIQUE NONCLUSTERED \(companyId, provider, adId\)")

    def test_ids_are_text_and_times_are_utc_datetime2(self):
        for col in ("adId", "adsetId", "campaignId", "adAccountId"):
            self.assertRegex(self.table, rf"\b{col}\s+NVARCHAR\(64\)", col)
        for col in ("lastSyncedAt", "created_At", "updated_at"):
            self.assertRegex(self.table, rf"\b{col}\s+DATETIME2\b", col)
        self.assertNotIn("GETDATE", self.table + self.sp)

    def test_no_foreign_key_to_attributions_or_users(self):
        self.assertNotRegex(self.table, r"REFERENCES\s+dbo\.(marketingLeadAttributions|users)\b")

    def test_action_1_is_idempotent_and_race_safe(self):
        self.assertIn("WITH (UPDLOCK, HOLDLOCK)", self.sp)
        self.assertIn("IN (2627, 2601) AND @action = 1", self.sp)

    def test_action_2_never_inserts(self):
        update_branch = self.sp.split("ELSE\n        BEGIN\n            UPDATE", 1)[1]
        self.assertNotIn("INSERT", update_branch.split("COMMIT TRANSACTION", 1)[0])
        self.assertIn("'ad_not_found'", self.sp)

    def test_error_keeps_resolved_data_and_gone_ads_are_cleared(self):
        for col in ("adName", "adsetId", "adsetName", "campaignId", "campaignName", "adAccountId"):
            self.assertRegex(self.sp, rf"{col}\s+= CASE @lookupStatus WHEN N'resolved' THEN @{col}\s+"
                                      rf"WHEN N'error' THEN {col}\s+ELSE NULL END", col)

    def test_only_two_actions_and_no_delete(self):
        self.assertIn("NOT IN (1, 2)", self.sp)
        self.assertNotRegex(self.sp, r"(?i)DELETE\s+FROM")

    def test_no_transaction_is_left_open_by_a_goto(self):
        # Validation GOTOs come before BEGIN TRANSACTION; the one inside commits first (it changed nothing).
        before, inside = self.sp.split("BEGIN TRANSACTION;", 1)
        self.assertEqual(len(re.findall(r"GOTO Finish", inside.split("END TRY")[0])), 1)
        self.assertRegex(inside, r"COMMIT TRANSACTION;\s+SET @error = N'ad_not_found';\s+GOTO Finish;")

    def test_list_is_scoped_capped_and_oldest_first(self):
        self.assertIn("WHERE ma.companyId = @companyId", self.all)
        self.assertIn("TOP 200", self.all)
        self.assertIn("ORDER BY ma.created_At, ma.marketingAdId", self.all)

    def test_leads_join_looked_up_ads_of_the_same_company(self):
        # 'error' keeps the last good lookup, so a transient Meta failure doesn't hide the ad set.
        self.assertRegex(self.leads, r"LEFT JOIN dbo\.marketingAds ma\s+ON ma\.companyId = @companyId\s+"
                                     r"AND ma\.provider = t\.provider\s+AND ma\.adId = t\.sourceId\s+"
                                     r"(--[^\n]*\n\s+)?AND ma\.lookupStatus IN \(N'resolved', N'error'\)")
        for col in ("adName", "adsetId", "adsetName", "campaignId", "campaignName"):
            self.assertIn(f"ma.{col}", self.leads)

    def test_leads_still_never_return_the_click_id(self):
        body = self.leads.split("CREATE OR ALTER PROC", 1)[1]  # the header comment may name them
        self.assertNotIn("ctwaClid", body)
        self.assertNotIn("rawReferral", body)

    def test_backfill_goes_through_the_procedure(self):
        self.assertIn("EXEC [dbo].[sp_marketingAds]", self.backfill)
        self.assertNotRegex(self.backfill, r"(?i)INSERT\s+INTO\s+dbo\.marketingAds")


if __name__ == "__main__":
    unittest.main()
