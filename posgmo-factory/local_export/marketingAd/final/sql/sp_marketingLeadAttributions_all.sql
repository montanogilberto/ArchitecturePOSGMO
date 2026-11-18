-- ============================================================
-- Client Acquisition: a company's ad clicks, newest first, max 200.
-- Never returns ctwaClid or rawReferral. POST /all_marketingLeadAttributions.
-- Phase 1b (2026-11-12): each click also carries its ad, ad set and campaign
-- from dbo.marketingAds once the worker resolved that ad (kept through a later
-- transient 'error'); NULL until then or after 'not_found'/'forbidden', and
-- an unresolved click is still listed. New optional filters: adsetId, campaignId.
-- Tables: sql/migrations/2026-11-04_marketingLeadAttributions.sql and
--         sql/migrations/2026-11-12_marketingAds.sql (run both first)
-- ============================================================
CREATE OR ALTER PROC [dbo].[sp_marketingLeadAttributions_all] (@pjsonfile VARCHAR(MAX))
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRY
        DECLARE @companyId    INT          = TRY_CONVERT(INT,  JSON_VALUE(@pjsonfile, '$.marketingLeadAttributions[0].companyId'));
        DECLARE @startDate    DATE         = TRY_CONVERT(DATE, JSON_VALUE(@pjsonfile, '$.marketingLeadAttributions[0].startDate'));
        DECLARE @endDate      DATE         = TRY_CONVERT(DATE, JSON_VALUE(@pjsonfile, '$.marketingLeadAttributions[0].endDate'));
        DECLARE @sourceId     NVARCHAR(64) =                   JSON_VALUE(@pjsonfile, '$.marketingLeadAttributions[0].sourceId');
        DECLARE @adsetId      NVARCHAR(64) =                   JSON_VALUE(@pjsonfile, '$.marketingLeadAttributions[0].adsetId');
        DECLARE @campaignId   NVARCHAR(64) =                   JSON_VALUE(@pjsonfile, '$.marketingLeadAttributions[0].campaignId');
        DECLARE @onlyNewLeads BIT          = ISNULL(TRY_CONVERT(BIT, JSON_VALUE(@pjsonfile, '$.marketingLeadAttributions[0].onlyNewLeads')), 0);

        IF @companyId IS NULL
        BEGIN
            SELECT '{"error":"companyId is required"}' AS jsonResult;
            RETURN;
        END

        -- Hermosillo is a fixed UTC-7 with no DST.
        DECLARE @today DATE = CAST(DATEADD(HOUR, -7, SYSUTCDATETIME()) AS DATE);
        SET @endDate   = ISNULL(@endDate, @today);
        SET @startDate = ISNULL(@startDate, DATEADD(DAY, -30, @today));
        DECLARE @fromUtc DATETIME2 = DATEADD(HOUR, 7, CAST(@startDate AS DATETIME2));
        DECLARE @toUtc   DATETIME2 = DATEADD(HOUR, 7, DATEADD(DAY, 1, CAST(@endDate AS DATETIME2)));

        DECLARE @listJson NVARCHAR(MAX);
        -- touchNumber counts every click of the customer, not just the filtered period.
        WITH touches AS (
            SELECT marketingLeadAttributionId, provider, conversionChannel, channelId, customerPhone, clientId,
                   isNewLead, sourceType, sourceId, headline, sourceUrl, mediaType, referredAt,
                   ROW_NUMBER() OVER (PARTITION BY customerPhone ORDER BY referredAt, marketingLeadAttributionId) AS touchNumber
            FROM dbo.marketingLeadAttributions
            WHERE companyId = @companyId
        )
        SELECT @listJson = (
            SELECT TOP 200
                   t.marketingLeadAttributionId, t.provider, t.conversionChannel, t.channelId, t.customerPhone, t.clientId,
                   t.isNewLead, t.touchNumber, t.sourceType, t.sourceId, t.headline, t.sourceUrl, t.mediaType,
                   ma.adName, ma.adsetId, ma.adsetName, ma.campaignId, ma.campaignName,
                   CONVERT(NVARCHAR(19), t.referredAt, 126) AS referredAt
            FROM touches t
            LEFT JOIN dbo.marketingAds ma
                   ON ma.companyId = @companyId
                  AND ma.provider = t.provider
                  AND ma.adId = t.sourceId
                  -- 'error' is a transient retry that keeps the last good lookup
                  AND ma.lookupStatus IN (N'resolved', N'error')
            WHERE t.referredAt >= @fromUtc AND t.referredAt < @toUtc
              AND (@sourceId IS NULL OR t.sourceId = @sourceId)
              AND (@adsetId IS NULL OR ma.adsetId = @adsetId)
              AND (@campaignId IS NULL OR ma.campaignId = @campaignId)
              AND (@onlyNewLeads = 0 OR t.isNewLead = 1)
            ORDER BY t.referredAt DESC
            FOR JSON PATH, INCLUDE_NULL_VALUES
        );
        SELECT ('{"result":[{"marketingLeadAttributions":' + ISNULL(@listJson, '[]') + '}]}') AS jsonResult;
    END TRY
    BEGIN CATCH
        SELECT ('{"error":"' + REPLACE(ERROR_MESSAGE(), '"', '''') + '"}') AS jsonResult;
    END CATCH
END;
GO
