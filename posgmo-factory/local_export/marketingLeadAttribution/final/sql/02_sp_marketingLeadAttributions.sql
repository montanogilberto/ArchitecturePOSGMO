CREATE OR ALTER PROC [dbo].[sp_marketingLeadAttributions] (@pjsonfile VARCHAR(MAX))
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @Outputmessage NVARCHAR(MAX) = '{
      "result": [
        { "value": "", "msg": "", "error": "" }
      ]
    }';

    DECLARE @action INT;
    DECLARE @companyId INT;
    DECLARE @channelId INT;
    DECLARE @customerPhone NVARCHAR(20);
    DECLARE @provider NVARCHAR(20);
    DECLARE @conversionChannel NVARCHAR(20);
    DECLARE @externalEventId NVARCHAR(128);
    DECLARE @sourceType NVARCHAR(20);
    DECLARE @sourceId NVARCHAR(64);
    DECLARE @ctwaClid NVARCHAR(512);
    DECLARE @headline NVARCHAR(255);
    DECLARE @body NVARCHAR(1000);
    DECLARE @sourceUrl NVARCHAR(500);
    DECLARE @mediaType NVARCHAR(20);
    DECLARE @rawReferral NVARCHAR(MAX);
    DECLARE @referredAt DATETIME2;

    DECLARE @resolvedClientId INT = NULL;
    DECLARE @resolvedIsNewLead BIT = 0;
    DECLARE @existingMarketingLeadAttributionId INT;

    BEGIN TRY
        BEGIN TRANSACTION;

        SELECT
            @action             = TRY_CONVERT(INT, JSON_VALUE(value, '$.action')),
            @companyId          = TRY_CONVERT(INT, JSON_VALUE(value, '$.companyId')),
            @channelId          = TRY_CONVERT(INT, JSON_VALUE(value, '$.channelId')),
            @customerPhone      = JSON_VALUE(value, '$.customerPhone'),
            @provider           = JSON_VALUE(value, '$.provider'),
            @conversionChannel  = JSON_VALUE(value, '$.conversionChannel'),
            @externalEventId    = JSON_VALUE(value, '$.externalEventId'),
            @sourceType         = JSON_VALUE(value, '$.sourceType'),
            @sourceId           = JSON_VALUE(value, '$.sourceId'),
            @ctwaClid           = JSON_VALUE(value, '$.ctwaClid'),
            @headline           = LEFT(JSON_VALUE(value, '$.headline'), 255),
            @body               = LEFT(JSON_VALUE(value, '$.body'), 1000),
            @sourceUrl          = LEFT(JSON_VALUE(value, '$.sourceUrl'), 500),
            @mediaType          = JSON_VALUE(value, '$.mediaType'),
            @rawReferral        = JSON_QUERY(value, '$.rawReferral'),
            @referredAt         = TRY_CONVERT(DATETIME2, JSON_VALUE(value, '$.referredAt'))
        FROM OPENJSON(@pjsonfile, '$.marketingLeadAttributions');

        SET @referredAt = ISNULL(@referredAt, SYSUTCDATETIME());

        -- Only action 1 (INSERT) is supported
        IF ISNULL(@action, 0) <> 1
        BEGIN
            SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.result[0].error', '1');
            SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.result[0].msg', 'unsupported_action');
            COMMIT TRANSACTION;
            GOTO Finish;
        END;

        -- Validate channelId for the given companyId
        IF @channelId IS NOT NULL AND NOT EXISTS (SELECT 1 FROM dbo.whatsappChannels WHERE channelId = @channelId AND companyId = @companyId)
        BEGIN
            SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.result[0].error', '1');
            SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.result[0].msg', 'channel_not_in_company');
            COMMIT TRANSACTION;
            GOTO Finish;
        END;

        -- Check for existing entry (idempotency)
        SELECT @existingMarketingLeadAttributionId = marketingLeadAttributionId
        FROM dbo.marketingLeadAttributions WITH (UPDLOCK, HOLDLOCK)
        WHERE companyId = @companyId
          AND provider = @provider
          AND externalEventId = @externalEventId;

        IF @existingMarketingLeadAttributionId IS NOT NULL
        BEGIN
            SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.result[0].value', CAST(@existingMarketingLeadAttributionId AS NVARCHAR(MAX)));
            SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.result[0].msg', 'Existing record found, no new insert.');
            COMMIT TRANSACTION;
            GOTO Finish;
        END;

        -- Resolve clientId
        -- Normalize customerPhone to last 10 digits
        DECLARE @normalizedCustomerPhone NVARCHAR(10) = RIGHT(REPLACE(REPLACE(REPLACE(@customerPhone,'+',''),' ',''),'-',''),10);

        SELECT TOP 1 @resolvedClientId = c.clientId
        FROM dbo.clients c
        WHERE RIGHT(REPLACE(REPLACE(REPLACE(c.cellphone,'+',''),' ',''),'-',''),10) = @normalizedCustomerPhone
          AND c.companyId = @companyId
          AND ISNULL(c.first_name, N'') <> N'Desconocido' -- Exclude placeholder client
        ORDER BY c.clientId;

        -- Resolve isNewLead
        -- isNewLead is 1 if (no resolvedClientId AND no whatsappConversations for this company/phone AND no earlier marketingLeadAttributions for this company/phone)
        IF @resolvedClientId IS NULL
           AND NOT EXISTS (
               SELECT 1 FROM dbo.whatsappConversations wc
               JOIN dbo.whatsappChannels wch ON wc.channelId = wch.channelId
               WHERE wch.companyId = @companyId AND wc.customerPhone = @customerPhone
           )
           AND NOT EXISTS (
               SELECT 1 FROM dbo.marketingLeadAttributions mla
               WHERE mla.companyId = @companyId AND mla.customerPhone = @customerPhone
           )
        BEGIN
            SET @resolvedIsNewLead = 1;
        END
        ELSE
        BEGIN
            SET @resolvedIsNewLead = 0;
        END;

        -- Perform INSERT
        INSERT INTO dbo.marketingLeadAttributions (
            companyId, provider, conversionChannel, channelId, customerPhone, clientId,
            isNewLead, externalEventId, sourceType, sourceId, ctwaClid, headline,
            body, sourceUrl, mediaType, rawReferral, referredAt, created_At
        )
        VALUES (
            @companyId, @provider, @conversionChannel, @channelId, @customerPhone, @resolvedClientId,
            @resolvedIsNewLead, @externalEventId, @sourceType, @sourceId, @ctwaClid, @headline,
            @body, @sourceUrl, @mediaType, @rawReferral, @referredAt, SYSUTCDATETIME()
        );

        SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.result[0].value', CAST(SCOPE_IDENTITY() AS NVARCHAR(MAX)));
        SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.result[0].msg', 'Inserted Successfully');

        COMMIT TRANSACTION;

    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0
            ROLLBACK TRANSACTION;

        DECLARE @ErrorMessage NVARCHAR(MAX) = ERROR_MESSAGE();
        DECLARE @ErrorState INT = ERROR_STATE();
        DECLARE @ErrorSeverity INT = ERROR_SEVERITY();
        DECLARE @ErrorNumber INT = ERROR_NUMBER();

        -- Handle UNIQUE constraint violation specifically for idempotency
        IF @ErrorNumber IN (2627, 2601) -- Unique constraint violation
        BEGIN
            -- Attempt to retrieve the existing ID in case of a race condition
            SELECT @existingMarketingLeadAttributionId = marketingLeadAttributionId
            FROM dbo.marketingLeadAttributions
            WHERE companyId = @companyId
              AND provider = @provider
              AND externalEventId = @externalEventId;

            IF @existingMarketingLeadAttributionId IS NOT NULL
            BEGIN
                SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.result[0].value', CAST(@existingMarketingLeadAttributionId AS NVARCHAR(MAX)));
                SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.result[0].msg', 'Duplicate record attempted, existing ID returned.');
            END
            ELSE
            BEGIN
                -- If we couldn't find it, something else is wrong or it's a different unique constraint
                SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.result[0].error', '1');
                SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.result[0].msg', @ErrorMessage);
            END
        END
        ELSE
        BEGIN
            SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.result[0].error', '1');
            SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.result[0].msg', @ErrorMessage);
        END;

    END CATCH;

Finish:
    SELECT
        JSON_VALUE(value,'$.value') AS value,
        JSON_VALUE(value,'$.msg')   AS msg,
        JSON_VALUE(value,'$.error') AS error
    FROM OPENJSON(@Outputmessage,'$.result');
END;
GO