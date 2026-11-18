-- =============================================================================
-- One-time backfill: a 'pending' marketingAds row for every ad that already
-- brought a lead before phase 1b was deployed. Goes through sp_marketingAds
-- action 1 (idempotent), so it is safe to re-run and creates no duplicates.
-- Run AFTER sp_marketingAds.sql; the worker then resolves the pending rows.
-- Prints only counts: no phones, no referral content.
-- =============================================================================
SET NOCOUNT ON;

DECLARE @companyId INT, @provider NVARCHAR(20), @sourceId NVARCHAR(64), @json VARCHAR(MAX);
DECLARE @result TABLE (jsonResult NVARCHAR(MAX));
DECLARE @done INT = 0;

DECLARE ads CURSOR LOCAL FAST_FORWARD FOR
    SELECT DISTINCT companyId, provider, sourceId
    FROM dbo.marketingLeadAttributions
    WHERE sourceId IS NOT NULL AND LTRIM(RTRIM(sourceId)) <> N'';

OPEN ads;
FETCH NEXT FROM ads INTO @companyId, @provider, @sourceId;
WHILE @@FETCH_STATUS = 0
BEGIN
    SET @json = (SELECT 1 AS [action], @companyId AS companyId, @provider AS provider, @sourceId AS adId
                 FOR JSON PATH, ROOT('marketingAds'));
    INSERT INTO @result (jsonResult) EXEC [dbo].[sp_marketingAds] @pjsonfile = @json;
    SET @done += 1;
    FETCH NEXT FROM ads INTO @companyId, @provider, @sourceId;
END;
CLOSE ads;
DEALLOCATE ads;

SELECT @done AS adsProcessed,
       SUM(CASE WHEN jsonResult LIKE '{"error"%' THEN 1 ELSE 0 END) AS errors
FROM @result;
GO
