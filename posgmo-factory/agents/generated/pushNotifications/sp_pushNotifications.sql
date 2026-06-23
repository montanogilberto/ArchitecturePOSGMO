CREATE TABLE dbo.PushNotifications (
    pushNotificationId INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    companyId INT NOT NULL,
    title NVARCHAR(200) NOT NULL,
    message NVARCHAR(1000) NOT NULL,
    notificationType NVARCHAR(50) NOT NULL,
    priority NVARCHAR(20) NOT NULL,
    targetType NVARCHAR(50) NOT NULL,
    targetUserId INT NULL,
    targetRoleId INT NULL,
    targetCompanyId INT NULL,
    navigationRoute NVARCHAR(250) NULL,
    isRead BIT NOT NULL,
    isSent BIT NOT NULL,
    sentAt DATETIME NULL,
    scheduledAt DATETIME NULL,
    payloadJson NVARCHAR(MAX) NULL,
    created_At DATETIME NOT NULL DEFAULT GETDATE(),
    updated_at DATETIME NULL,
    CONSTRAINT FK_PushNotifications_Companies FOREIGN KEY (companyId) REFERENCES dbo.companies (companyId),
    CONSTRAINT FK_PushNotifications_Users FOREIGN KEY (targetUserId) REFERENCES dbo.users (userId),
    CONSTRAINT FK_PushNotifications_Roles FOREIGN KEY (targetRoleId) REFERENCES dbo.roles (roleId)
);

CREATE INDEX IX_PushNotifications_CompanyId ON dbo.PushNotifications (companyId);
CREATE INDEX IX_PushNotifications_TargetUserId ON dbo.PushNotifications (targetUserId);
CREATE INDEX IX_PushNotifications_TargetRoleId ON dbo.PushNotifications (targetRoleId);
CREATE INDEX IX_PushNotifications_TargetCompanyId ON dbo.PushNotifications (targetCompanyId);
CREATE INDEX IX_PushNotifications_NotificationType ON dbo.PushNotifications (notificationType);
CREATE INDEX IX_PushNotifications_Priority ON dbo.PushNotifications (priority);
CREATE INDEX IX_PushNotifications_TargetType ON dbo.PushNotifications (targetType);
CREATE INDEX IX_PushNotifications_IsRead ON dbo.PushNotifications (isRead);
CREATE INDEX IX_PushNotifications_IsSent ON dbo.PushNotifications (isSent);
CREATE INDEX IX_PushNotifications_SentAt ON dbo.PushNotifications (sentAt);
CREATE INDEX IX_PushNotifications_ScheduledAt ON dbo.PushNotifications (scheduledAt);
GO
CREATE PROCEDURE dbo.sp_pushNotifications
    @pjsonfile VARCHAR(MAX)
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @Outputmessage VARCHAR(MAX);
    DECLARE @companyId INT;

    -- Create a temporary table to hold the parsed JSON data
    DECLARE @payload TABLE (
        action INT,
        pushNotificationId INT,
        companyId INT,
        title NVARCHAR(200),
        message NVARCHAR(1000),
        notificationType NVARCHAR(50),
        priority NVARCHAR(20),
        targetType NVARCHAR(50),
        targetUserId INT,
        targetRoleId INT,
        targetCompanyId INT,
        navigationRoute NVARCHAR(250),
        isRead BIT,
        isSent BIT,
        sentAt DATETIME,
        scheduledAt DATETIME,
        payloadJson NVARCHAR(MAX)
    );

    -- Insert data from JSON into the temporary table
    INSERT INTO @payload (
        action,
        pushNotificationId,
        companyId,
        title,
        message,
        notificationType,
        priority,
        targetType,
        targetUserId,
        targetRoleId,
        targetCompanyId,
        navigationRoute,
        isRead,
        isSent,
        sentAt,
        scheduledAt,
        payloadJson
    )
    SELECT
        TRY_CONVERT(INT, JSON_VALUE(value, '$.action')),
        JSON_VALUE(value, '$.pushNotificationId'),
        JSON_VALUE(value, '$.companyId'),
        JSON_VALUE(value, '$.title'),
        JSON_VALUE(value, '$.message'),
        JSON_VALUE(value, '$.notificationType'),
        JSON_VALUE(value, '$.priority'),
        JSON_VALUE(value, '$.targetType'),
        JSON_VALUE(value, '$.targetUserId'),
        JSON_VALUE(value, '$.targetRoleId'),
        JSON_VALUE(value, '$.targetCompanyId'),
        JSON_VALUE(value, '$.navigationRoute'),
        JSON_VALUE(value, '$.isRead'),
        JSON_VALUE(value, '$.isSent'),
        JSON_VALUE(value, '$.sentAt'),
        JSON_VALUE(value, '$.scheduledAt'),
        JSON_VALUE(value, '$.payloadJson')
    FROM OPENJSON(@pjsonfile, '$.pushNotifications');

    SELECT @companyId = companyId FROM @payload;

    -- Validate companyId for all operations
    IF NOT EXISTS (SELECT 1 FROM dbo.companies WHERE companyId = @companyId)
    BEGIN
        SET @Outputmessage = JSON_MODIFY('{}', '$.status', 'error');
        SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.message', 'Invalid companyId provided.');
        SELECT @Outputmessage AS Outputmessage;
        GOTO Finish;
    END;

    -- Action 1: INSERT
    IF EXISTS (SELECT 1 FROM @payload WHERE action = 1)
    BEGIN
        INSERT INTO dbo.PushNotifications (
            companyId,
            title,
            message,
            notificationType,
            priority,
            targetType,
            targetUserId,
            targetRoleId,
            targetCompanyId,
            navigationRoute,
            isRead,
            isSent,
            sentAt,
            scheduledAt,
            payloadJson,
            created_At
        )
        SELECT
            p.companyId,
            p.title,
            p.message,
            p.notificationType,
            p.priority,
            p.targetType,
            p.targetUserId,
            p.targetRoleId,
            p.targetCompanyId,
            p.navigationRoute,
            ISNULL(p.isRead, 0), -- Default to 0 if not provided
            ISNULL(p.isSent, 0), -- Default to 0 if not provided
            p.sentAt,
            p.scheduledAt,
            p.payloadJson,
            GETDATE()
        FROM @payload p
        WHERE p.action = 1;

        SET @Outputmessage = JSON_MODIFY('{}', '$.status', 'success');
        SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.message', 'PushNotification(s) inserted successfully.');
        SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.pushNotificationId', CAST(SCOPE_IDENTITY() AS VARCHAR(20)));
    END;

    -- Action 2: UPDATE
    IF EXISTS (SELECT 1 FROM @payload WHERE action = 2)
    BEGIN
        UPDATE pn
        SET
            pn.title = p.title,
            pn.message = p.message,
            pn.notificationType = p.notificationType,
            pn.priority = p.priority,
            pn.targetType = p.targetType,
            pn.targetUserId = p.targetUserId,
            pn.targetRoleId = p.targetRoleId,
            pn.targetCompanyId = p.targetCompanyId,
            pn.navigationRoute = p.navigationRoute,
            pn.isRead = p.isRead,
            pn.isSent = p.isSent,
            pn.sentAt = p.sentAt,
            pn.scheduledAt = p.scheduledAt,
            pn.payloadJson = p.payloadJson,
            pn.updated_at = GETDATE()
        FROM dbo.PushNotifications pn
        INNER JOIN @payload p ON pn.pushNotificationId = p.pushNotificationId
        WHERE p.action = 2 AND pn.companyId = p.companyId;

        SET @Outputmessage = JSON_MODIFY('{}', '$.status', 'success');
        SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.message', 'PushNotification(s) updated successfully.');
    END;

    -- Action 3: DELETE
    IF EXISTS (SELECT 1 FROM @payload WHERE action = 3)
    BEGIN
        DELETE pn
        FROM dbo.PushNotifications pn
        INNER JOIN @payload p ON pn.pushNotificationId = p.pushNotificationId
        WHERE p.action = 3 AND pn.companyId = p.companyId;

        SET @Outputmessage = JSON_MODIFY('{}', '$.status', 'success');
        SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.message', 'PushNotification(s) deleted successfully.');
    END;

    SELECT @Outputmessage AS Outputmessage;

    Finish:
END;
GO
CREATE PROCEDURE dbo.sp_pushNotifications_all
    @pjsonfile VARCHAR(MAX)
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @companyId INT;

    SELECT @companyId = JSON_VALUE(value, '$.companyId')
    FROM OPENJSON(@pjsonfile, '$.pushNotifications');

    SELECT
        pushNotificationId,
        companyId,
        title,
        message,
        notificationType,
        priority,
        targetType,
        targetUserId,
        targetRoleId,
        targetCompanyId,
        navigationRoute,
        isRead,
        isSent,
        ISNULL(CONVERT(VARCHAR(30), sentAt, 126), '') AS sentAt,
        ISNULL(CONVERT(VARCHAR(30), scheduledAt, 126), '') AS scheduledAt,
        payloadJson,
        CONVERT(VARCHAR(30), created_At, 126) AS created_At,
        ISNULL(CONVERT(VARCHAR(30), updated_at, 126), '') AS updated_at
    FROM dbo.PushNotifications
    WHERE companyId = @companyId
    FOR JSON AUTO, ROOT('pushNotifications');
END;
GO
CREATE PROCEDURE dbo.sp_pushNotifications_one
    @pjsonfile VARCHAR(MAX)
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @pushNotificationId INT;
    DECLARE @companyId INT;

    SELECT
        @pushNotificationId = JSON_VALUE(value, '$.pushNotificationId'),
        @companyId = JSON_VALUE(value, '$.companyId')
    FROM OPENJSON(@pjsonfile);

    SELECT
        pushNotificationId,
        companyId,
        title,
        message,
        notificationType,
        priority,
        targetType,
        targetUserId,
        targetRoleId,
        targetCompanyId,
        navigationRoute,
        isRead,
        isSent,
        ISNULL(CONVERT(VARCHAR(30), sentAt, 126), '') AS sentAt,
        ISNULL(CONVERT(VARCHAR(30), scheduledAt, 126), '') AS scheduledAt,
        payloadJson,
        CONVERT(VARCHAR(30), created_At, 126) AS created_At,
        ISNULL(CONVERT(VARCHAR(30), updated_at, 126), '') AS updated_at
    FROM dbo.PushNotifications
    WHERE pushNotificationId = @pushNotificationId AND companyId = @companyId
    FOR JSON AUTO, ROOT('pushNotifications');
END;