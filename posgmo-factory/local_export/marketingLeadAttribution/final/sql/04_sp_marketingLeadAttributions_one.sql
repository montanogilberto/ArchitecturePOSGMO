CREATE OR ALTER PROC [dbo].[sp_marketingLeadAttributions_one] (@pjsonfile VARCHAR(MAX))
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRY
        DECLARE @companyId INT = TRY_CONVERT(INT, JSON_VALUE(@pjsonfile, '$.marketingLeadAttributions[0].companyId'));
        DECLARE @id        INT = TRY_CONVERT(INT, JSON_VALUE(@pjsonfile, '$.marketingLeadAttributions[0].marketingLeadAttributionId'));

        IF @companyId IS NULL OR @id IS NULL
        BEGIN
            SELECT '{"error":"companyId and marketingLeadAttributionId are required"}' AS jsonResult;
            RETURN;
        END

        DECLARE @oneJson NVARCHAR(MAX) = (
            SELECT marketingLeadAttributionId, provider, conversionChannel, channelId, customerPhone, clientId,
                   isNewLead, sourceType, sourceId, headline, body, sourceUrl, mediaType,
                   JSON_QUERY(JSON_MODIFY(rawReferral, '$.ctwa_clid', NULL)) AS rawReferral,
                   CONVERT(NVARCHAR(19), referredAt, 126) AS referredAt
            FROM dbo.marketingLeadAttributions
            WHERE marketingLeadAttributionId = @id AND companyId = @companyId
            FOR JSON PATH, INCLUDE_NULL_VALUES
        );
        SELECT ('{"result":[{"marketingLeadAttributions":' + ISNULL(@oneJson, '[]') + '}]}') AS jsonResult;
    END TRY
    BEGIN CATCH
        SELECT ('{"error":"' + REPLACE(ERROR_MESSAGE(), '"', '''') + '"}') AS jsonResult;
    END CATCH
END;
GO
