-- ============================================================
-- Client Acquisition phase 1b: ad → ad set / campaign lookups.
--   action 1 = ensure a 'pending' row (idempotent). Called in-process by the
--              WhatsApp webhook and by the backfill.
--   action 2 = write a lookup result on an EXISTING row (worker only, through
--              POST /marketingAds with the worker key). Never inserts.
-- No delete. companyId always comes from the caller's attribution/channel.
-- Table: sql/migrations/2026-11-12_marketingAds.sql (run it first)
-- ============================================================
CREATE OR ALTER PROC [dbo].[sp_marketingAds] (@pjsonfile VARCHAR(MAX))
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @error NVARCHAR(MAX) = NULL;
    DECLARE @id INT = NULL;
    DECLARE @resultStatus NVARCHAR(20) = NULL;

    DECLARE @action INT;
    DECLARE @companyId INT;
    DECLARE @provider NVARCHAR(20);
    DECLARE @adId NVARCHAR(64);
    DECLARE @lookupStatus NVARCHAR(20);
    DECLARE @adName NVARCHAR(255);
    DECLARE @adsetId NVARCHAR(64);
    DECLARE @adsetName NVARCHAR(255);
    DECLARE @campaignId NVARCHAR(64);
    DECLARE @campaignName NVARCHAR(255);
    DECLARE @adAccountId NVARCHAR(64);
    DECLARE @lastError NVARCHAR(255);

    BEGIN TRY
        SELECT
            @action       = TRY_CONVERT(INT, JSON_VALUE(value, '$.action')),
            @companyId    = TRY_CONVERT(INT, JSON_VALUE(value, '$.companyId')),
            @provider     = JSON_VALUE(value, '$.provider'),
            @adId         = LTRIM(RTRIM(JSON_VALUE(value, '$.adId'))),
            @lookupStatus = JSON_VALUE(value, '$.lookupStatus'),
            @adName       = LEFT(JSON_VALUE(value, '$.adName'), 255),
            @adsetId      = LEFT(JSON_VALUE(value, '$.adsetId'), 64),
            @adsetName    = LEFT(JSON_VALUE(value, '$.adsetName'), 255),
            @campaignId   = LEFT(JSON_VALUE(value, '$.campaignId'), 64),
            @campaignName = LEFT(JSON_VALUE(value, '$.campaignName'), 255),
            @adAccountId  = LEFT(JSON_VALUE(value, '$.adAccountId'), 64),
            @lastError    = LEFT(JSON_VALUE(value, '$.lastError'), 255)
        FROM OPENJSON(@pjsonfile, '$.marketingAds');

        -- Validation happens before any transaction opens, so GOTO never leaves one open.
        IF ISNULL(@action, 0) NOT IN (1, 2)
        BEGIN
            SET @error = N'unsupported_action';
            GOTO Finish;
        END;

        IF @companyId IS NULL OR @provider IS NULL OR NULLIF(@adId, N'') IS NULL
        BEGIN
            SET @error = N'companyId, provider and adId are required';
            GOTO Finish;
        END;

        IF @action = 2 AND ISNULL(@lookupStatus, N'') NOT IN (N'resolved', N'not_found', N'forbidden', N'error')
        BEGIN
            SET @error = N'invalid_lookupStatus';
            GOTO Finish;
        END;

        BEGIN TRANSACTION;

        IF @action = 1
        BEGIN
            SELECT @id = marketingAdId, @resultStatus = lookupStatus
            FROM dbo.marketingAds WITH (UPDLOCK, HOLDLOCK)
            WHERE companyId = @companyId AND provider = @provider AND adId = @adId;

            IF @id IS NULL
            BEGIN
                INSERT INTO dbo.marketingAds (companyId, provider, adId, lookupStatus, lookupAttempts, created_At)
                VALUES (@companyId, @provider, @adId, N'pending', 0, SYSUTCDATETIME());
                SET @id = SCOPE_IDENTITY();
                SET @resultStatus = N'pending';
            END;
        END
        ELSE
        BEGIN
            UPDATE dbo.marketingAds
            SET lookupStatus   = @lookupStatus,
                lookupAttempts = lookupAttempts + 1,
                lastSyncedAt   = SYSUTCDATETIME(),
                updated_at     = SYSUTCDATETIME(),
                -- 'resolved' writes the lookup; 'not_found'/'forbidden' clear it (never
                -- keep names of an ad that is gone or belongs to another account);
                -- 'error' is transient and keeps whatever was resolved before.
                adName       = CASE @lookupStatus WHEN N'resolved' THEN @adName       WHEN N'error' THEN adName       ELSE NULL END,
                adsetId      = CASE @lookupStatus WHEN N'resolved' THEN @adsetId      WHEN N'error' THEN adsetId      ELSE NULL END,
                adsetName    = CASE @lookupStatus WHEN N'resolved' THEN @adsetName    WHEN N'error' THEN adsetName    ELSE NULL END,
                campaignId   = CASE @lookupStatus WHEN N'resolved' THEN @campaignId   WHEN N'error' THEN campaignId   ELSE NULL END,
                campaignName = CASE @lookupStatus WHEN N'resolved' THEN @campaignName WHEN N'error' THEN campaignName ELSE NULL END,
                adAccountId  = CASE @lookupStatus WHEN N'resolved' THEN @adAccountId  WHEN N'error' THEN adAccountId  ELSE NULL END,
                lastError    = CASE @lookupStatus WHEN N'resolved' THEN NULL ELSE @lastError END,
                @id          = marketingAdId
            WHERE companyId = @companyId AND provider = @provider AND adId = @adId;

            IF @id IS NULL
            BEGIN
                -- The UPDATE matched nothing, so nothing changed: COMMIT, never
                -- ROLLBACK here (a ROLLBACK would also undo the caller's transaction).
                COMMIT TRANSACTION;
                SET @error = N'ad_not_found';
                GOTO Finish;
            END;
            SET @resultStatus = @lookupStatus;
        END;

        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0
            ROLLBACK TRANSACTION;

        -- A concurrent action 1 for the same ad inserted it first: same as "exists".
        IF ERROR_NUMBER() IN (2627, 2601) AND @action = 1
        BEGIN
            SELECT @id = marketingAdId, @resultStatus = lookupStatus
            FROM dbo.marketingAds
            WHERE companyId = @companyId AND provider = @provider AND adId = @adId;
            IF @id IS NULL
                SET @error = ERROR_MESSAGE();
        END
        ELSE
        BEGIN
            SET @error = ERROR_MESSAGE();
        END;
    END CATCH;

Finish:
    IF @error IS NOT NULL
        SELECT ('{"error":"' + REPLACE(@error, '"', '''') + '"}') AS jsonResult;
    ELSE
        SELECT ('{"result":[{"marketingAds":[{"marketingAdId":' + CAST(@id AS VARCHAR(12))
                + ',"lookupStatus":"' + @resultStatus + '"}]}]}') AS jsonResult;
END;
GO
