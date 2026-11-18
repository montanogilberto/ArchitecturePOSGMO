CREATE TABLE FactoryRunUsages (
    factoryRunUsageId INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    factoryRunRef NVARCHAR(50) NOT NULL,
    promptTokens INT NOT NULL,
    completionTokens INT NOT NULL,
    totalTokens INT NOT NULL,
    costUSD DECIMAL(10,2) NOT NULL,
    modelName NVARCHAR(100) NOT NULL,
    timestamp DATETIME NOT NULL,
    created_At DATETIME NOT NULL,
    updated_at DATETIME
);
GO

CREATE OR ALTER PROCEDURE sp_factoryRunUsages
    @pjsonfile NVARCHAR(MAX)
AS
BEGIN
    SET NOCOUNT ON;

    -- Temp table to hold JSON values
    DECLARE @tempFactoryRunUsages TABLE (
        action INT,
        factoryRunUsageId INT,
        factoryRunRef NVARCHAR(50),
        promptTokens INT,
        completionTokens INT,
        totalTokens INT,
        costUSD DECIMAL(10,2),
        modelName NVARCHAR(100),
        timestamp DATETIME
    );

    -- Insert parsed JSON into temp table
    INSERT INTO @tempFactoryRunUsages (action, factoryRunUsageId, factoryRunRef, promptTokens, completionTokens, totalTokens, costUSD, modelName, timestamp)
    SELECT
        JSON_VALUE(value, '$.action'),
        JSON_VALUE(value, '$.factoryRunUsageId'),
        JSON_VALUE(value, '$.factoryRunRef'),
        JSON_VALUE(value, '$.promptTokens'),
        JSON_VALUE(value, '$.completionTokens'),
        JSON_VALUE(value, '$.totalTokens'),
        JSON_VALUE(value, '$.costUSD'),
        JSON_VALUE(value, '$.modelName'),
        JSON_VALUE(value, '$.timestamp')
    FROM OPENJSON(@pjsonfile, '$.factoryRunUsages');

    -- Update records (action = 2)
    UPDATE fru
    SET
        factoryRunRef = t.factoryRunRef,
        promptTokens = t.promptTokens,
        completionTokens = t.completionTokens,
        totalTokens = t.totalTokens,
        costUSD = t.costUSD,
        modelName = t.modelName,
        timestamp = t.timestamp,
        updated_at = GETUTCDATE()
    FROM FactoryRunUsages fru
    INNER JOIN @tempFactoryRunUsages t ON fru.factoryRunUsageId = t.factoryRunUsageId
    WHERE t.action = 2;

    -- Insert records (action = 1)
    INSERT INTO FactoryRunUsages (factoryRunRef, promptTokens, completionTokens, totalTokens, costUSD, modelName, timestamp, created_At, updated_at)
    SELECT
        t.factoryRunRef,
        t.promptTokens,
        t.completionTokens,
        t.totalTokens,
        t.costUSD,
        t.modelName,
        t.timestamp,
        GETUTCDATE(),
        NULL
    FROM @tempFactoryRunUsages t
    WHERE t.action = 1;

    -- Delete records (action = 3)
    DELETE fru
    FROM FactoryRunUsages fru
    INNER JOIN @tempFactoryRunUsages t ON fru.factoryRunUsageId = t.factoryRunUsageId
    WHERE t.action = 3;

    -- Return JSON response for affected records (e.g., newly inserted ID or updated record) -
    -- For simplicity, let's return a success message or the ID of the affected record if it's an insert.
    SELECT '{"message": "Operation completed successfully"}' AS JSON_Result;
END;
GO

CREATE OR ALTER PROCEDURE sp_factoryRunUsages_all
    @pjsonfile NVARCHAR(MAX)
AS
BEGIN
    SET NOCOUNT ON;

    SELECT
        factoryRunUsageId,
        factoryRunRef,
        promptTokens,
        completionTokens,
        totalTokens,
        costUSD,
        modelName,
        timestamp,
        created_At,
        updated_at
    FROM FactoryRunUsages
    FOR JSON PATH;
END;
GO

CREATE OR ALTER PROCEDURE sp_factoryRunUsages_one
    @pjsonfile NVARCHAR(MAX)
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @factoryRunUsageId INT;

    SELECT @factoryRunUsageId = JSON_VALUE(value, '$.factoryRunUsageId')
    FROM OPENJSON(@pjsonfile, '$.factoryRunUsages');

    SELECT
        factoryRunUsageId,
        factoryRunRef,
        promptTokens,
        completionTokens,
        totalTokens,
        costUSD,
        modelName,
        timestamp,
        created_At,
        updated_at
    FROM FactoryRunUsages
    WHERE factoryRunUsageId = @factoryRunUsageId
    FOR JSON PATH, WITHOUT_ARRAY_WRAPPER;
END;
GO