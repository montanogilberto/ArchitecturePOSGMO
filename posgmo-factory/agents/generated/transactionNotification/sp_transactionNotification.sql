CREATE TABLE [dbo].[transactionNotifications] (
  transactionNotificationId INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
  companyId INT NOT NULL,
  clientId INT NOT NULL,
  transactionId INT NOT NULL,
  movementType NVARCHAR(30) NOT NULL,
  channel NVARCHAR(20) NOT NULL,
  status NVARCHAR(20) NOT NULL,
  recipientEmail NVARCHAR(200),
  subject NVARCHAR(200),
  messageBody NVARCHAR(MAX),
  amount DECIMAL(18,2) NOT NULL,
  currency NVARCHAR(3) NOT NULL,
  stripeReference NVARCHAR(100),
  bankName NVARCHAR(100),
  bankLast4 NVARCHAR(4),
  sentAt DATETIME,
  confirmedAt DATETIME,
  failureReason NVARCHAR(500),
  created_At DATETIME NOT NULL DEFAULT GETDATE(),
  updated_at DATETIME,
  FOREIGN KEY (companyId) REFERENCES companies(companyId),
  FOREIGN KEY (clientId) REFERENCES clients(clientId),
  FOREIGN KEY (transactionId) REFERENCES stripeTransactions(transactionId),
  FOREIGN KEY (status) REFERENCES transactionNotifications_status(statusCode)
);
GO
CREATE OR ALTER PROCEDURE [dbo].[sp_transactionNotifications]
    @pjsonfile NVARCHAR(MAX)
AS
BEGIN
    SET NOCOUNT ON;

    -- Temp table to hold JSON data
    CREATE TABLE #transactionNotifications (
        action INT,
        transactionNotificationId INT,
        companyId INT,
        clientId INT,
        transactionId INT,
        movementType NVARCHAR(30),
        channel NVARCHAR(20),
        status NVARCHAR(20),
        recipientEmail NVARCHAR(200),
        subject NVARCHAR(200),
        messageBody NVARCHAR(MAX),
        amount DECIMAL(18,2),
        currency NVARCHAR(3),
        stripeReference NVARCHAR(100),
        bankName NVARCHAR(100),
        bankLast4 NVARCHAR(4),
        sentAt DATETIME,
        confirmedAt DATETIME,
        failureReason NVARCHAR(500)
    );

    -- Insert data from JSON into temp table
    INSERT INTO #transactionNotifications (
        action, transactionNotificationId, companyId, clientId, transactionId,
        movementType, channel, status, recipientEmail, subject, messageBody,
        amount, currency, stripeReference, bankName, bankLast4, sentAt,
        confirmedAt, failureReason
    )
    SELECT
        JSON_VALUE(j.value, '$.action'),
        JSON_VALUE(j.value, '$.transactionNotificationId'),
        JSON_VALUE(j.value, '$.companyId'),
        JSON_VALUE(j.value, '$.clientId'),
        JSON_VALUE(j.value, '$.transactionId'),
        JSON_VALUE(j.value, '$.movementType'),
        JSON_VALUE(j.value, '$.channel'),
        JSON_VALUE(j.value, '$.status'),
        JSON_VALUE(j.value, '$.recipientEmail'),
        JSON_VALUE(j.value, '$.subject'),
        JSON_VALUE(j.value, '$.messageBody'),
        JSON_VALUE(j.value, '$.amount'),
        JSON_VALUE(j.value, '$.currency'),
        JSON_VALUE(j.value, '$.stripeReference'),
        JSON_VALUE(j.value, '$.bankName'),
        JSON_VALUE(j.value, '$.bankLast4'),
        JSON_VALUE(j.value, '$.sentAt'),
        JSON_VALUE(j.value, '$.confirmedAt'),
        JSON_VALUE(j.value, '$.failureReason')
    FROM OPENJSON(@pjsonfile, '$.transactionNotifications') AS j;

    -- Action 1: INSERT
    INSERT INTO [dbo].[transactionNotifications] (
        companyId, clientId, transactionId, movementType, channel, status,
        recipientEmail, subject, messageBody, amount, currency, stripeReference,
        bankName, bankLast4, sentAt, confirmedAt, failureReason, created_At
    )
    SELECT
        t.companyId, t.clientId, t.transactionId, t.movementType, t.channel,
        t.status, t.recipientEmail, t.subject, t.messageBody, t.amount,
        t.currency, t.stripeReference, t.bankName, t.bankLast4, t.sentAt,
        t.confirmedAt, t.failureReason, GETDATE()
    FROM #transactionNotifications AS t
    WHERE t.action = 1;

    -- Action 2: UPDATE
    UPDATE tn
    SET
        companyId = ISNULL(t.companyId, tn.companyId),
        clientId = ISNULL(t.clientId, tn.clientId),
        transactionId = ISNULL(t.transactionId, tn.transactionId),
        movementType = ISNULL(t.movementType, tn.movementType),
        channel = ISNULL(t.channel, tn.channel),
        status = ISNULL(t.status, tn.status),
        recipientEmail = ISNULL(t.recipientEmail, tn.recipientEmail),
        subject = ISNULL(t.subject, tn.subject),
        messageBody = ISNULL(t.messageBody, tn.messageBody),
        amount = ISNULL(t.amount, tn.amount),
        currency = ISNULL(t.currency, tn.currency),
        stripeReference = ISNULL(t.stripeReference, tn.stripeReference),
        bankName = ISNULL(t.bankName, tn.bankName),
        bankLast4 = ISNULL(t.bankLast4, tn.bankLast4),
        sentAt = ISNULL(t.sentAt, tn.sentAt),
        confirmedAt = ISNULL(t.confirmedAt, tn.confirmedAt),
        failureReason = ISNULL(t.failureReason, tn.failureReason),
        updated_at = GETDATE()
    FROM [dbo].[transactionNotifications] AS tn
    INNER JOIN #transactionNotifications AS t
        ON tn.transactionNotificationId = t.transactionNotificationId
    WHERE t.action = 2;

    -- Action 3: DELETE
    DELETE tn
    FROM [dbo].[transactionNotifications] AS tn
    INNER JOIN #transactionNotifications AS t
        ON tn.transactionNotificationId = t.transactionNotificationId
    WHERE t.action = 3;

    -- Return the modified records
    SELECT (
        SELECT tn.*
        FROM [dbo].[transactionNotifications] AS tn
        INNER JOIN #transactionNotifications AS t
            ON tn.transactionNotificationId = t.transactionNotificationId
        WHERE t.action IN (1, 2)
        FOR JSON PATH
    ) AS jsonResult;

    DROP TABLE #transactionNotifications;
END;
GO
CREATE OR ALTER PROCEDURE [dbo].[sp_transactionNotifications_all]
    @pjsonfile NVARCHAR(MAX)
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @companyId INT;
    DECLARE @transactionId INT;
    DECLARE @status NVARCHAR(20);
    DECLARE @channel NVARCHAR(20);
    DECLARE @clientId INT;

    SELECT
        @companyId = JSON_VALUE(@pjsonfile, '$.transactionNotifications[0].companyId'),
        @transactionId = JSON_VALUE(@pjsonfile, '$.transactionNotifications[0].transactionId'),
        @status = JSON_VALUE(@pjsonfile, '$.transactionNotifications[0].status'),
        @channel = JSON_VALUE(@pjsonfile, '$.transactionNotifications[0].channel'),
        @clientId = JSON_VALUE(@pjsonfile, '$.transactionNotifications[0].clientId')
    ;

    SELECT tn.*
    FROM [dbo].[transactionNotifications] AS tn
    WHERE
        tn.companyId = @companyId
        AND (@transactionId IS NULL OR tn.transactionId = @transactionId)
        AND (@status IS NULL OR tn.status = @status)
        AND (@channel IS NULL OR tn.channel = @channel)
        AND (@clientId IS NULL OR tn.clientId = @clientId)
    FOR JSON PATH;
END;
GO
CREATE OR ALTER PROCEDURE [dbo].[sp_transactionNotifications_one]
    @pjsonfile NVARCHAR(MAX)
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @companyId INT;
    DECLARE @transactionNotificationId INT;

    SELECT
        @companyId = JSON_VALUE(@pjsonfile, '$.companyId'),
        @transactionNotificationId = JSON_VALUE(@pjsonfile, '$.transactionNotificationId')
    ;

    SELECT tn.*
    FROM [dbo].[transactionNotifications] AS tn
    WHERE tn.companyId = @companyId
      AND tn.transactionNotificationId = @transactionNotificationId
    FOR JSON PATH, WITHOUT_ARRAY_WRAPPER;
END;
GO