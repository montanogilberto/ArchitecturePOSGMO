-- =============================================================================
-- ROLLBACK of 2026-11-12_marketingAds.sql
-- =============================================================================
-- Run order: first stop marketingAdsSyncWorker and deploy a backend whose
-- webhook no longer calls marketingAds.ensure_pending, then restore the previous
-- sp_marketingLeadAttributions_all (git history), then this file.
-- Drops the ad lookups only; dbo.marketingLeadAttributions is untouched, and
-- every lookup can be rebuilt from it with the backfill. Safe to re-run.
-- =============================================================================

DROP PROCEDURE IF EXISTS [dbo].[sp_marketingAds_all];
DROP PROCEDURE IF EXISTS [dbo].[sp_marketingAds];
DROP TABLE IF EXISTS [dbo].[marketingAds];
GO
