-- ============================================================
-- Client Acquisition phase 1b: a company's ad lookups, oldest first, max 200.
-- Used by marketingAdsSyncWorker (pending/error rows, daily re-sync) and to
-- verify the pilot. POST /all_marketingAds (worker key). No personal data.
-- Table: sql/migrations/2026-11-12_marketingAds.sql (run it first)
-- ============================================================
CREATE OR ALTER PROC [dbo].[sp_marketingAds_all] (@pjsonfile VARCHAR(MAX))
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRY
        DECLARE @companyId      INT           = TRY_CONVERT(INT,       JSON_VALUE(@pjsonfile, '$.marketingAds[0].companyId'));
        DECLARE @maxAttempts    INT           = TRY_CONVERT(INT,       JSON_VALUE(@pjsonfile, '$.marketingAds[0].maxAttempts'));
        DECLARE @syncedBefore   DATETIME2     = TRY_CONVERT(DATETIME2, JSON_VALUE(@pjsonfile, '$.marketingAds[0].syncedBefore'));
        DECLARE @adsetId        NVARCHAR(64)  =                        JSON_VALUE(@pjsonfile, '$.marketingAds[0].adsetId');
        DECLARE @campaignId     NVARCHAR(64)  =                        JSON_VALUE(@pjsonfile, '$.marketingAds[0].campaignId');
        DECLARE @statusesJson   NVARCHAR(MAX) =                        JSON_QUERY(@pjsonfile, '$.marketingAds[0].lookupStatuses');

        IF @companyId IS NULL
        BEGIN
            SELECT '{"error":"companyId is required"}' AS jsonResult;
            RETURN;
        END

        DECLARE @statuses TABLE (lookupStatus NVARCHAR(20) PRIMARY KEY);
        IF @statusesJson IS NOT NULL
            INSERT INTO @statuses (lookupStatus)
            SELECT DISTINCT LEFT([value], 20) FROM OPENJSON(@statusesJson) WHERE [value] IS NOT NULL;
        DECLARE @filterStatuses BIT = CASE WHEN EXISTS (SELECT 1 FROM @statuses) THEN 1 ELSE 0 END;

        DECLARE @listJson NVARCHAR(MAX);
        SELECT @listJson = (
            SELECT TOP 200
                   marketingAdId, provider, adId, adName, adsetId, adsetName, campaignId, campaignName,
                   adAccountId, lookupStatus, lookupAttempts, lastError,
                   CONVERT(NVARCHAR(19), lastSyncedAt, 126) AS lastSyncedAt
            FROM dbo.marketingAds ma
            WHERE ma.companyId = @companyId
              AND (@filterStatuses = 0 OR ma.lookupStatus IN (SELECT lookupStatus FROM @statuses))
              AND (@maxAttempts IS NULL OR ma.lookupAttempts < @maxAttempts)
              AND (@syncedBefore IS NULL OR ma.lastSyncedAt IS NULL OR ma.lastSyncedAt < @syncedBefore)
              AND (@adsetId IS NULL OR ma.adsetId = @adsetId)
              AND (@campaignId IS NULL OR ma.campaignId = @campaignId)
            ORDER BY ma.created_At, ma.marketingAdId
            FOR JSON PATH, INCLUDE_NULL_VALUES
        );
        SELECT ('{"result":[{"marketingAds":' + ISNULL(@listJson, '[]') + '}]}') AS jsonResult;
    END TRY
    BEGIN CATCH
        SELECT ('{"error":"' + REPLACE(ERROR_MESSAGE(), '"', '''') + '"}') AS jsonResult;
    END CATCH
END;
GO
