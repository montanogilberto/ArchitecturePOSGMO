CREATE OR ALTER PROC [dbo].[sp_marketingLeadAttributions_all] (@pjsonfile VARCHAR(MAX))
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRY
        DECLARE @companyId    INT          = TRY_CONVERT(INT,  JSON_VALUE(@pjsonfile, '$.marketingLeadAttributions[0].companyId'));
        DECLARE @startDate    DATE         = TRY_CONVERT(DATE, JSON_VALUE(@pjsonfile, '$.marketingLeadAttributions[0].startDate'));
        DECLARE @endDate      DATE         = TRY_CONVERT(DATE, JSON_VALUE(@pjsonfile, '$.marketingLeadAttributions[0].endDate'));
        DECLARE @sourceId     NVARCHAR(64) =                   JSON_VALUE(@pjsonfile, '$.marketingLeadAttributions[0].sourceId');
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
                   marketingLeadAttributionId, provider, conversionChannel, channelId, customerPhone, clientId,
                   isNewLead, touchNumber, sourceType, sourceId, headline, sourceUrl, mediaType,
                   CONVERT(NVARCHAR(19), referredAt, 126) AS referredAt
            FROM touches
            WHERE referredAt >= @fromUtc AND referredAt < @toUtc
              AND (@sourceId IS NULL OR sourceId = @sourceId)
              AND (@onlyNewLeads = 0 OR isNewLead = 1)
            ORDER BY touches.referredAt DESC
            FOR JSON PATH, INCLUDE_NULL_VALUES
        );
        SELECT ('{"result":[{"marketingLeadAttributions":' + ISNULL(@listJson, '[]') + '}]}') AS jsonResult;
    END TRY
    BEGIN CATCH
        SELECT ('{"error":"' + REPLACE(ERROR_MESSAGE(), '"', '''') + '"}') AS jsonResult;
    END CATCH
END;
GO
