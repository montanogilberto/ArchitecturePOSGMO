CREATE TABLE [dbo].[Suppliers] (
    supplierId    INT            IDENTITY (1, 1) NOT NULL,
    companyId     INT            NOT NULL,
    supplierName  VARCHAR (200)  NOT NULL,
    contactName   VARCHAR (100)  NULL,
    phone         VARCHAR (20)   NULL,
    email         VARCHAR (100)  NULL,
    address       TEXT           NULL,
    active        VARCHAR (1)    NOT NULL,
    created_At    DATETIME       DEFAULT (GETDATE()) NULL,
    updated_at    DATETIME       DEFAULT (GETDATE()) NULL,
    PRIMARY KEY CLUSTERED (supplierId ASC)
);

GO

CREATE NONCLUSTERED INDEX IX_Suppliers_companyId
ON [dbo].[Suppliers] (companyId);
GO

CREATE NONCLUSTERED INDEX IX_Suppliers_supplierName
ON [dbo].[Suppliers] (supplierName);
GO

CREATE NONCLUSTERED INDEX IX_Suppliers_email
ON [dbo].[Suppliers] (email);
GO

CREATE NONCLUSTERED INDEX IX_Suppliers_active
ON [dbo].[Suppliers] (active);
GO

CREATE OR ALTER PROCEDURE [dbo].[sp_suppliers]
    @pjsonfile VARCHAR(MAX)
AS
BEGIN
    SET NOCOUNT ON;

    -- Temporary table to hold JSON data
    DECLARE @payload TABLE (
        action INT,
        supplierId INT,
        companyId INT,
        supplierName VARCHAR(200),
        contactName VARCHAR(100),
        phone VARCHAR(20),
        email VARCHAR(100),
        address TEXT,
        active VARCHAR(1)
    );

    -- Insert data from JSON into the payload table
    INSERT INTO @payload (action, supplierId, companyId, supplierName, contactName, phone, email, address, active)
    SELECT
        JSON_VALUE(value, '$.action'),
        JSON_VALUE(value, '$.supplierId'),
        JSON_VALUE(value, '$.companyId'),
        JSON_VALUE(value, '$.supplierName'),
        JSON_VALUE(value, '$.contactName'),
        JSON_VALUE(value, '$.phone'),
        JSON_VALUE(value, '$.email'),
        JSON_VALUE(value, '$.address'),
        JSON_VALUE(value, '$.active')
    FROM OPENJSON(@pjsonfile, '$.suppliers');

    -- Declare a variable to hold the output message
    DECLARE @OutputMessage NVARCHAR(MAX);

    BEGIN TRY
        BEGIN TRANSACTION;

        -- Action 1: INSERT
        IF EXISTS (SELECT 1 FROM @payload WHERE action = 1)
        BEGIN
            -- Validate for duplicate supplierName within the same company
            IF EXISTS (SELECT p.supplierName, p.companyId FROM @payload AS p WHERE p.action = 1 AND EXISTS (SELECT 1 FROM dbo.Suppliers AS s WHERE s.supplierName = p.supplierName AND s.companyId = p.companyId))
            BEGIN
                SET @OutputMessage = (SELECT '{"status": "error", "message": "A supplier with this name already exists for this company."}' FOR JSON PATH, WITHOUT_ARRAY_WRAPPER);
                THROW 50000, 'Duplicate supplier name', 1;
            END;

            INSERT INTO dbo.Suppliers (companyId, supplierName, contactName, phone, email, address, active, created_At, updated_at)
            SELECT
                p.companyId,
                p.supplierName,
                p.contactName,
                p.phone,
                p.email,
                p.address,
                p.active,
                GETDATE(),
                GETDATE()
            FROM @payload AS p
            WHERE p.action = 1;

            SET @OutputMessage = (SELECT '{"status": "success", "message": "Supplier(s) inserted successfully."}' FOR JSON PATH, WITHOUT_ARRAY_WRAPPER);
        END;

        -- Action 2: UPDATE
        IF EXISTS (SELECT 1 FROM @payload WHERE action = 2)
        BEGIN
            -- Validate if supplier exists
            IF NOT EXISTS (SELECT 1 FROM @payload AS p JOIN dbo.Suppliers AS s ON p.supplierId = s.supplierId WHERE p.action = 2)
            BEGIN
                SET @OutputMessage = (SELECT '{"status": "error", "message": "Supplier not found for update."}' FOR JSON PATH, WITHOUT_ARRAY_WRAPPER);
                THROW 50000, 'Supplier not found', 1;
            END;

            -- Validate for duplicate supplierName within the same company, excluding the current supplier being updated
            IF EXISTS (SELECT p.supplierName, p.companyId FROM @payload AS p WHERE p.action = 2 AND EXISTS (SELECT 1 FROM dbo.Suppliers AS s WHERE s.supplierName = p.supplierName AND s.companyId = p.companyId AND s.supplierId <> p.supplierId))
            BEGIN
                SET @OutputMessage = (SELECT '{"status": "error", "message": "Another supplier with this name already exists for this company."}' FOR JSON PATH, WITHOUT_ARRAY_WRAPPER);
                THROW 50000, 'Duplicate supplier name', 1;
            END;

            UPDATE s
            SET
                s.supplierName = ISNULL(p.supplierName, s.supplierName),
                s.contactName = ISNULL(p.contactName, s.contactName),
                s.phone = ISNULL(p.phone, s.phone),
                s.email = ISNULL(p.email, s.email),
                s.address = ISNULL(p.address, s.address),
                s.active = ISNULL(p.active, s.active),
                s.updated_at = GETDATE()
            FROM dbo.Suppliers AS s
            JOIN @payload AS p ON s.supplierId = p.supplierId
            WHERE p.action = 2;

            SET @OutputMessage = (SELECT '{"status": "success", "message": "Supplier(s) updated successfully."}' FOR JSON PATH, WITHOUT_ARRAY_WRAPPER);
        END;

        -- Action 3: DELETE
        IF EXISTS (SELECT 1 FROM @payload WHERE action = 3)
        BEGIN
            -- Validate if supplier exists
            IF NOT EXISTS (SELECT 1 FROM @payload AS p JOIN dbo.Suppliers AS s ON p.supplierId = s.supplierId WHERE p.action = 3)
            BEGIN
                SET @OutputMessage = (SELECT '{"status": "error", "message": "Supplier not found for deletion."}' FOR JSON PATH, WITHOUT_ARRAY_WRAPPER);
                THROW 50000, 'Supplier not found', 1;
            END;

            DELETE s
            FROM dbo.Suppliers AS s
            JOIN @payload AS p ON s.supplierId = p.supplierId
            WHERE p.action = 3;

            SET @OutputMessage = (SELECT '{"status": "success", "message": "Supplier(s) deleted successfully."}' FOR JSON PATH, WITHOUT_ARRAY_WRAPPER);
        END;

        COMMIT TRANSACTION;

        SELECT @OutputMessage AS jsonResult;

    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0
            ROLLBACK TRANSACTION;

        -- Return error message as JSON
        SET @OutputMessage = (SELECT '{"status": "error", "message": "' + ERROR_MESSAGE() + '"}' FOR JSON PATH, WITHOUT_ARRAY_WRAPPER);
        SELECT @OutputMessage AS jsonResult;
    END CATCH;

    RETURN 0;
END;

GO

CREATE OR ALTER PROCEDURE [dbo].[sp_suppliers_all]
    @pjsonfile VARCHAR(MAX)
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @companyId INT;

    SELECT @companyId = JSON_VALUE(value, '$.companyId')
    FROM OPENJSON(@pjsonfile, '$.plural');

    SELECT
        supplierId,
        companyId,
        supplierName,
        ISNULL(contactName, '') AS contactName,
        ISNULL(phone, '') AS phone,
        ISNULL(email, '') AS email,
        ISNULL(address, '') AS address,
        active,
        CONVERT(VARCHAR(30), created_At, 126) AS created_At,
        ISNULL(CONVERT(VARCHAR(30), updated_at, 126), '') AS updated_at
    FROM dbo.Suppliers
    WHERE companyId = @companyId
    FOR JSON AUTO, ROOT('suppliers');

    RETURN 0;
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
        @supplierId = JSON_VALUE(@pjsonfile, '$.supplierId'),
        @companyId = JSON_VALUE(@pjsonfile, '$.companyId');

    SELECT
        supplierId,
        companyId,
        supplierName,
        ISNULL(contactName, '') AS contactName,
        ISNULL(phone, '') AS phone,
        ISNULL(email, '') AS email,
        ISNULL(address, '') AS address,
        active,
        CONVERT(VARCHAR(30), created_At, 126) AS created_At,
        ISNULL(CONVERT(VARCHAR(30), updated_at, 126), '') AS updated_at
    FROM dbo.Suppliers
    WHERE supplierId = @supplierId AND companyId = @companyId
    FOR JSON AUTO, ROOT('suppliers');

    RETURN 0;
END;