# marketingAd — finalized (Client Acquisition phase 1b)

PRD: `posgmo-factory/tests/prd_marketingAd.json` · Plan: POSVending `docs/plan-atribucion-adset-campana.md`

The factory run (`run_local_export.py`, `FACTORY_SQL_MODE=validate`, 2026-11-12) produced
`../artifacts.json` but its reviewer failed it (database 0: house SP conventions; DATETIME
instead of DATETIME2; no 2627 race handling; extra `active` column; response shape ≠ the
deployed `{"result":[{...}]}` contract). These files replace it, following the deployed
`marketingLeadAttribution` module. The generated frontend is NOT used (the PRD has no screens).

## Verified (2026-11-12)
- `smartloans_backend` worktree at 7530c91 + these files: `test_marketing_ads.py` (28),
  `test_marketing_attribution.py`, `test_public_route_lockdown.py` → **96 tests OK**.
  (`test_demand_signals.test_reads_mask_the_phone` already fails on 7530c91 without this change.)
- All SQL compiled and smoke-tested **on the live server inside one transaction, then rolled
  back** (table absent afterwards): backfill found 3 ads / 0 errors; action 1 idempotent;
  action 2 resolved / error-keeps-names / ad_not_found / unsupported_action / invalid_lookupStatus;
  company isolation; worker filter; leads list shows ad set + campaign for looked-up ads, never ctwaClid.
- Bug caught by that run and fixed: `ad_not_found` used ROLLBACK, which also undoes a caller's
  outer transaction (error 266) → now COMMIT (nothing changed).

## Apply (in order; DEV → QA → PROD, by PR)
1. **SQL** (per environment, review first — the local `.env` points at PROD):
   `sql/migrations/2026-11-12_marketingAds.sql` → `sql/sp_marketingAds.sql` →
   `sql/sp_marketingAds_all.sql` → `sql/sp_marketingLeadAttributions_all.sql`.
2. **Backend** (`smartloans_backend`, branch from `development`):
   copy `modules/`, `routes_/`, `docs_description/`, `sql/`, `tests/` into the repo and
   `git apply backend_existing_files.patch` (main.py router, whatsappCloud webhook call, test stub).
   The patch is made against `development` @ 7530c91 (which already includes the
   ad_referral-to-agent change); re-check it applies if `development` moved since.
3. **Backfill** once per environment: `sql/migrations/2026-11-12_marketingAds_backfill.sql`.
4. **Worker** (`smartloans_workers/workers`, repo montanogilberto/workers): written 2026-11-12,
   not committed — `marketingAdsSyncWorker/__init__.py`, timer `marketing_ads_sync_timer`
   (`0 */15 * * * *`) appended to `function_app.py`, tests `test/test_marketing_ads_sync.py` (17 OK;
   run by path: `venv/bin/python test/test_marketing_ads_sync.py`).
   Function App settings (never in code): `META_ADS_ACCESS_TOKEN` (system user, `ads_read` on
   GMO Ads only), `META_ADS_ACCOUNT_BY_COMPANY={"1":"act_2212661913013953"}`, `WORKER_KEY`
   (same as the backend), optional `META_GRAPH_VERSION` (v25.0), `MARKETING_ADS_MAX_ATTEMPTS` (5),
   `MARKETING_ADS_RESYNC_HOUR_UTC` (16). Deploy it only after the backend routes exist.
   A token rejected by Meta (190/102) stops the run and changes no ad; fix the token and the next
   run resumes.

Rollback: `sql/migrations/2026-11-12_marketingAds_ROLLBACK.sql` (after removing the webhook call
and restoring the previous `sp_marketingLeadAttributions_all`). Attribution rows are untouched.
