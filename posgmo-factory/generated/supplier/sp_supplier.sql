CREATE TABLE dbo.Suppliers (
    supplierId INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    companyId INT NOT NULL,
    supplierName VARCHAR(200) NOT NULL,
    contactName VARCHAR(100) NULL,
    phone VARCHAR(20) NULL,
    email VARCHAR(100) NULL,
    address TEXT NULL,
    active VARCHAR(1) NOT NULL,
    created_At DATETIME DEFAULT GETDATE(),
    updated_at DATETIME DEFAULT GETDATE()
);
CREATE UNIQUE INDEX IX_Suppliers_companyId_supplierName ON dbo.Suppliers (companyId, supplierName);
CREATE INDEX IX_Suppliers_active ON dbo.Suppliers (active);

GO

CREATE OR ALTER PROCEDURE [dbo].[sp_suppliers]
    @pjsonfile VARCHAR(MAX)
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @Outputmessage NVARCHAR(MAX);

    BEGIN TRY
        IF ISJSON(@pjsonfile) = 0
        BEGIN
            SET @Outputmessage = JSON_QUERY('{\"error\": \"Invalid JSON format provided.\"}');
            GOTO Finish;
        END;

        DECLARE @action INT;
        SELECT @action = TRY_CONVERT(INT, JSON_VALUE(value, '$.action'))
        FROM OPENJSON(@pjsonfile, '$.suppliers');

        IF @action IS NULL
        BEGIN
            SET @Outputmessage = JSON_QUERY('{\"error\": \"Action is missing or invalid.\"}');
            GOTO Finish;
        END;

        DECLARE @payload TABLE (
            action INT,
            companyId INT,
            supplierId INT,
            supplierName VARCHAR(200),
            contactName VARCHAR(100),
            phone VARCHAR(20),
            email VARCHAR(100),
            address TEXT,
            active VARCHAR(1)
        );

        INSERT INTO @payload (action, companyId, supplierId, supplierName, contactName, phone, email, address, active)
        SELECT
            TRY_CONVERT(INT, JSON_VALUE(value, '$.action')),
            TRY_CONVERT(INT, JSON_VALUE(value, '$.companyId')),
            TRY_CONVERT(INT, JSON_VALUE(value, '$.supplierId')),
            JSON_VALUE(value, '$.supplierName'),
            JSON_VALUE(value, '$.contactName'),
            JSON_VALUE(value, '$.phone'),
            JSON_VALUE(value, '$.email'),
            JSON_VALUE(value, '$.address'),
            JSON_VALUE(value, '$.active')
        FROM OPENJSON(@pjsonfile, '$.suppliers');

        IF @action = 1 -- INSERT
        BEGIN
            -- Duplicate validation for supplierName within the same companyId
            IF EXISTS (SELECT 1 FROM dbo.Suppliers s JOIN @payload p ON s.companyId = p.companyId AND s.supplierName = p.supplierName WHERE p.action = 1)
            BEGIN
                SET @Outputmessage = JSON_QUERY('{\"error\": \"A supplier with this name already exists for this company.\"}');
                GOTO Finish;
            END;

            INSERT INTO dbo.Suppliers (companyId, supplierName, contactName, phone, email, address, active)
            SELECT p.companyId, p.supplierName, p.contactName, p.phone, p.email, p.address, p.active
            FROM @payload p
            WHERE p.action = 1;

            SET @Outputmessage = JSON_QUERY('{\"message\": \"Supplier created successfully.\"}');
        END
        ELSE IF @action = 2 -- UPDATE
        BEGIN
            -- Duplicate validation for supplierName (excluding the current supplier being updated)
            IF EXISTS (SELECT 1 FROM dbo.Suppliers s JOIN @payload p ON s.companyId = p.companyId AND s.supplierName = p.supplierName WHERE p.action = 2 AND s.supplierId <> p.supplierId)
            BEGIN
                SET @Outputmessage = JSON_QUERY('{\"error\": \"A different supplier with this name already exists for this company.\"}');
                GOTO Finish;
            END;

            UPDATE s
            SET
                s.supplierName = p.supplierName,
                s.contactName = p.contactName,
                s.phone = p.phone,
                s.email = p.email,
                s.address = p.address,
                s.active = p.active,
                s.updated_at = GETDATE()
            FROM dbo.Suppliers s
            INNER JOIN @payload p ON s.supplierId = p.supplierId
            WHERE p.action = 2;

            IF @@ROWCOUNT = 0
            BEGIN
                SET @Outputmessage = JSON_QUERY('{\"error\": \"Supplier not found or no changes made.\"}');
                GOTO Finish;
            END;

            SET @Outputmessage = JSON_QUERY('{\"message\": \"Supplier updated successfully.\"}');
        END
        ELSE IF @action = 3 -- DELETE
        BEGIN
            DELETE s
            FROM dbo.Suppliers s
            INNER JOIN @payload p ON s.supplierId = p.supplierId
            WHERE p.action = 3;

            IF @@ROWCOUNT = 0
            BEGIN
                SET @Outputmessage = JSON_QUERY('{\"error\": \"Supplier not found.\"}');
                GOTO Finish;
            END;

            SET @Outputmessage = JSON_QUERY('{\"message\": \"Supplier deleted successfully.\"}');
        END
        ELSE
        BEGIN
            SET @Outputmessage = JSON_QUERY('{\"error\": \"Invalid action specified.\"}');
            GOTO Finish;
        END;

        SELECT @Outputmessage AS result;

    END TRY
    BEGIN CATCH
        SET @Outputmessage = JSON_QUERY('{\"error\": \"' + ERROR_MESSAGE() + '\"}');
        SELECT @Outputmessage AS result;
    END CATCH;

Finish:
    SELECT @Outputmessage AS result;
END;

GO

CREATE OR ALTER PROCEDURE [dbo].[sp_suppliers_all]
    @pjsonfile VARCHAR(MAX)
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @companyId INT;

    SELECT @companyId = TRY_CONVERT(INT, JSON_VALUE(value, '$.companyId'))
    FROM OPENJSON(@pjsonfile, '$.suppliers');

    SELECT
        s.supplierId,
        s.companyId,
        s.supplierName,
        ISNULL(s.contactName, '') AS contactName,
        ISNULL(s.phone, '') AS phone,
        ISNULL(s.email, '') AS email,
        ISNULL(s.address, '') AS address,
        s.active,
        CONVERT(VARCHAR(30), s.created_At, 126) AS created_At,
        ISNULL(CONVERT(VARCHAR(30), s.updated_at, 126), '') AS updated_at
    FROM dbo.Suppliers s
    WHERE s.companyId = @companyId
    FOR JSON AUTO, ROOT('suppliers');
END;

GO

CREATE OR ALTER PROCEDURE [dbo].[sp_suppliers_one]
    @pjsonfile VARCHAR(MAX)
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @supplierId INT;
    DECLARE @companyId INT;

    SELECT
        @supplierId = TRY_CONVERT(INT, JSON_VALUE(value, '$.supplierId')),
        @companyId = TRY_CONVERT(INT, JSON_VALUE(value, '$.companyId'))
    FROM OPENJSON(@pjsonfile, '$.suppliers');

    SELECT
        s.supplierId,
        s.companyId,
        s.supplierName,
        ISNULL(s.contactName, '') AS contactName,
        ISNULL(s.phone, '') AS phone,
        ISNULL(s.email, '') AS email,
        ISNULL(s.address, '') AS address,
        s.active,
        CONVERT(VARCHAR(30), s.created_At, 126) AS created_At,
        ISNULL(CONVERT(VARCHAR(30), s.updated_at, 126), '') AS updated_at
    FROM dbo.Suppliers s
    WHERE s.supplierId = @supplierId AND s.companyId = @companyId
    FOR JSON AUTO, ROOT('suppliers');
END;
