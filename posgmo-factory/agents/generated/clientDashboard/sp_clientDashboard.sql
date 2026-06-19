
CREATE TABLE [dbo].[ClientDashboards] (
    [clientDashboardId] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    [companyId] INT NOT NULL,
    [clientId] INT NOT NULL,
    [availableCredit] DECIMAL(10,2),
    [activeLoanBalance] DECIMAL(10,2),
    [nextPaymentAmount] DECIMAL(10,2),
    [nextPaymentDate] DATETIME,
    [activityDate] DATETIME,
    [activityType] NVARCHAR(255),
    [description] NVARCHAR(MAX),
    [amount] DECIMAL(10,2),
    [loanNumber] NVARCHAR(255),
    [loanAmount] DECIMAL(10,2),
    [remainingBalance] DECIMAL(10,2),
    [status] NVARCHAR(50),
    [created_At] DATETIME NOT NULL DEFAULT GETDATE(),
    [updated_at] DATETIME
);
CREATE INDEX IX_ClientDashboards_companyId ON [dbo].[ClientDashboards] (companyId);
CREATE INDEX IX_ClientDashboards_clientId ON [dbo].[ClientDashboards] (clientId);
CREATE INDEX IX_ClientDashboards_activityDate ON [dbo].[ClientDashboards] (activityDate);
CREATE INDEX IX_ClientDashboards_nextPaymentDate ON [dbo].[ClientDashboards] (nextPaymentDate);
CREATE INDEX IX_ClientDashboards_status ON [dbo].[ClientDashboards] (status);

GO

CREATE PROCEDURE [dbo].[sp_ClientDashboards]
    @pjsonfile VARCHAR(MAX)
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @Outputmessage VARCHAR(MAX);
    BEGIN TRY
        -- Temporary table to hold the parsed JSON data
        DECLARE @payload TABLE (
            action INT,
            clientDashboardId INT,
            companyId INT,
            clientId INT,
            availableCredit DECIMAL(10,2),
            activeLoanBalance DECIMAL(10,2),
            nextPaymentAmount DECIMAL(10,2),
            nextPaymentDate DATETIME,
            activityDate DATETIME,
            activityType NVARCHAR(255),
            description NVARCHAR(MAX),
            amount DECIMAL(10,2),
            loanNumber NVARCHAR(255),
            loanAmount DECIMAL(10,2),
            remainingBalance DECIMAL(10,2),
            status NVARCHAR(50)
        );

        INSERT INTO @payload (
            action, clientDashboardId, companyId, clientId, availableCredit, activeLoanBalance,
            nextPaymentAmount, nextPaymentDate, activityDate, activityType, description,
            amount, loanNumber, loanAmount, remainingBalance, status
        )
        SELECT
            TRY_CONVERT(INT, JSON_VALUE(value, '$.action')),
            TRY_CONVERT(INT, JSON_VALUE(value, '$.clientDashboardId')),
            TRY_CONVERT(INT, JSON_VALUE(value, '$.companyId')),
            TRY_CONVERT(INT, JSON_VALUE(value, '$.clientId')),
            TRY_CONVERT(DECIMAL(10,2), JSON_VALUE(value, '$.availableCredit')),
            TRY_CONVERT(DECIMAL(10,2), JSON_VALUE(value, '$.activeLoanBalance')),
            TRY_CONVERT(DECIMAL(10,2), JSON_VALUE(value, '$.nextPaymentAmount')),
            TRY_CONVERT(DATETIME, JSON_VALUE(value, '$.nextPaymentDate')),
            TRY_CONVERT(DATETIME, JSON_VALUE(value, '$.activityDate')),
            JSON_VALUE(value, '$.activityType'),
            JSON_VALUE(value, '$.description'),
            TRY_CONVERT(DECIMAL(10,2), JSON_VALUE(value, '$.amount')),
            JSON_VALUE(value, '$.loanNumber'),
            TRY_CONVERT(DECIMAL(10,2), JSON_VALUE(value, '$.loanAmount')),
            TRY_CONVERT(DECIMAL(10,2), JSON_VALUE(value, '$.remainingBalance')),
            JSON_VALUE(value, '$.status')
        FROM OPENJSON(@pjsonfile, '$.clientDashboards');

        -- Action 1: INSERT
        IF EXISTS (SELECT 1 FROM @payload WHERE action = 1)
        BEGIN
            INSERT INTO [dbo].[ClientDashboards] (
                companyId, clientId, availableCredit, activeLoanBalance, nextPaymentAmount,
                nextPaymentDate, activityDate, activityType, description, amount,
                loanNumber, loanAmount, remainingBalance, status, created_At, updated_at
            )
            SELECT
                p.companyId, p.clientId, p.availableCredit, p.activeLoanBalance, p.nextPaymentAmount,
                p.nextPaymentDate, p.activityDate, p.activityType, p.description, p.amount,
                p.loanNumber, p.loanAmount, p.remainingBalance, p.status, GETDATE(), NULL
            FROM @payload p
            WHERE p.action = 1;

            SET @Outputmessage = (SELECT 'ClientDashboard(s) inserted successfully.' AS msg FOR JSON PATH);
        END;

        -- Action 2: UPDATE
        IF EXISTS (SELECT 1 FROM @payload WHERE action = 2)
        BEGIN
            UPDATE cd
            SET
                cd.companyId = ISNULL(p.companyId, cd.companyId),
                cd.clientId = ISNULL(p.clientId, cd.clientId),
                cd.availableCredit = ISNULL(p.availableCredit, cd.availableCredit),
                cd.activeLoanBalance = ISNULL(p.activeLoanBalance, cd.activeLoanBalance),
                cd.nextPaymentAmount = ISNULL(p.nextPaymentAmount, cd.nextPaymentAmount),
                cd.nextPaymentDate = ISNULL(p.nextPaymentDate, cd.nextPaymentDate),
                cd.activityDate = ISNULL(p.activityDate, cd.activityDate),
                cd.activityType = ISNULL(p.activityType, cd.activityType),
                cd.description = ISNULL(p.description, cd.description),
                cd.amount = ISNULL(p.amount, cd.amount),
                cd.loanNumber = ISNULL(p.loanNumber, cd.loanNumber),
                cd.loanAmount = ISNULL(p.loanAmount, cd.loanAmount),
                cd.remainingBalance = ISNULL(p.remainingBalance, cd.remainingBalance),
                cd.status = ISNULL(p.status, cd.status),
                cd.updated_at = GETDATE()
            FROM [dbo].[ClientDashboards] cd
            INNER JOIN @payload p ON cd.clientDashboardId = p.clientDashboardId
            WHERE p.action = 2;

            SET @Outputmessage = (SELECT 'ClientDashboard(s) updated successfully.' AS msg FOR JSON PATH);
        END;

        -- Action 3: DELETE
        IF EXISTS (SELECT 1 FROM @payload WHERE action = 3)
        BEGIN
            DELETE cd
            FROM [dbo].[ClientDashboards] cd
            INNER JOIN @payload p ON cd.clientDashboardId = p.clientDashboardId
            WHERE p.action = 3;

            SET @Outputmessage = (SELECT 'ClientDashboard(s) deleted successfully.' AS msg FOR JSON PATH);
        END;

        SELECT @Outputmessage AS value;

    END TRY
    BEGIN CATCH
        SET @Outputmessage = (SELECT
            ERROR_NUMBER() AS ErrorNumber,
            ERROR_SEVERITY() AS ErrorSeverity,
            ERROR_STATE() AS ErrorState,
            ERROR_PROCEDURE() AS ErrorProcedure,
            ERROR_LINE() AS ErrorLine,
            ERROR_MESSAGE() AS ErrorMessage
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER);
        SELECT @Outputmessage AS error;
    END CATCH;
END;

GO

CREATE PROCEDURE [dbo].[sp_ClientDashboards_all]
    @pjsonfile VARCHAR(MAX) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @companyId INT;

    IF @pjsonfile IS NOT NULL
    BEGIN
        SELECT @companyId = TRY_CONVERT(INT, JSON_VALUE(value, '$.companyId'))
        FROM OPENJSON(@pjsonfile, '$.clientDashboards')
        WHERE JSON_VALUE(value, '$.companyId') IS NOT NULL;
    END;

    SELECT
        cd.clientDashboardId,
        cd.companyId,
        cd.clientId,
        ISNULL(cd.availableCredit, 0) AS availableCredit,
        ISNULL(cd.activeLoanBalance, 0) AS activeLoanBalance,
        ISNULL(cd.nextPaymentAmount, 0) AS nextPaymentAmount,
        ISNULL(CONVERT(VARCHAR(30), cd.nextPaymentDate, 126), '') AS nextPaymentDate,
        ISNULL(CONVERT(VARCHAR(30), cd.activityDate, 126), '') AS activityDate,
        ISNULL(cd.activityType, '') AS activityType,
        ISNULL(cd.description, '') AS description,
        ISNULL(cd.amount, 0) AS amount,
        ISNULL(cd.loanNumber, '') AS loanNumber,
        ISNULL(cd.loanAmount, 0) AS loanAmount,
        ISNULL(cd.remainingBalance, 0) AS remainingBalance,
        ISNULL(cd.status, '') AS status,
        CONVERT(VARCHAR(30), cd.created_At, 126) AS created_At,
        ISNULL(CONVERT(VARCHAR(30), cd.updated_at, 126), '') AS updated_at
    FROM [dbo].[ClientDashboards] cd
    WHERE (@companyId IS NULL OR cd.companyId = @companyId)
    FOR JSON AUTO, ROOT('clientDashboards');
END;

GO

CREATE PROCEDURE [dbo].[sp_ClientDashboards_one]
    @pjsonfile VARCHAR(MAX)
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @clientDashboardId INT;
    DECLARE @companyId INT;

    SELECT
        @clientDashboardId = TRY_CONVERT(INT, JSON_VALUE(value, '$.clientDashboardId')),
        @companyId = TRY_CONVERT(INT, JSON_VALUE(value, '$.companyId'))
    FROM OPENJSON(@pjsonfile, '$.clientDashboards')
    WHERE JSON_VALUE(value, '$.clientDashboardId') IS NOT NULL
      AND JSON_VALUE(value, '$.companyId') IS NOT NULL;

    SELECT
        cd.clientDashboardId,
        cd.companyId,
        cd.clientId,
        ISNULL(cd.availableCredit, 0) AS availableCredit,
        ISNULL(cd.activeLoanBalance, 0) AS activeLoanBalance,
        ISNULL(cd.nextPaymentAmount, 0) AS nextPaymentAmount,
        ISNULL(CONVERT(VARCHAR(30), cd.nextPaymentDate, 126), '') AS nextPaymentDate,
        ISNULL(CONVERT(VARCHAR(30), cd.activityDate, 126), '') AS activityDate,
        ISNULL(cd.activityType, '') AS activityType,
        ISNULL(cd.description, '') AS description,
        ISNULL(cd.amount, 0) AS amount,
        ISNULL(cd.loanNumber, '') AS loanNumber,
        ISNULL(cd.loanAmount, 0) AS loanAmount,
        ISNULL(cd.remainingBalance, 0) AS remainingBalance,
        ISNULL(cd.status, '') AS status,
        CONVERT(VARCHAR(30), cd.created_At, 126) AS created_At,
        ISNULL(CONVERT(VARCHAR(30), cd.updated_at, 126), '') AS updated_at
    FROM [dbo].[ClientDashboards] cd
    WHERE cd.clientDashboardId = @clientDashboardId AND cd.companyId = @companyId
    FOR JSON AUTO, ROOT('clientDashboards');
END;
