CREATE TABLE [dbo].[marketingLeadAttributions] (
    marketingLeadAttributionId INT IDENTITY(1,1) NOT NULL,
    companyId INT NOT NULL,
    provider NVARCHAR(20) NOT NULL,
    conversionChannel NVARCHAR(20) NOT NULL,
    channelId INT NULL,
    customerPhone NVARCHAR(20) NOT NULL,
    clientId INT NULL,
    isNewLead BIT NOT NULL,
    externalEventId NVARCHAR(128) NOT NULL,
    sourceType NVARCHAR(20) NULL,
    sourceId NVARCHAR(64) NULL,
    ctwaClid NVARCHAR(512) NULL,
    headline NVARCHAR(255) NULL,
    body NVARCHAR(1000) NULL,
    sourceUrl NVARCHAR(500) NULL,
    mediaType NVARCHAR(20) NULL,
    rawReferral NVARCHAR(MAX) NULL,
    referredAt DATETIME2 NOT NULL,
    created_At DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at DATETIME2 NULL,
    CONSTRAINT PK_marketingLeadAttributions PRIMARY KEY CLUSTERED (marketingLeadAttributionId),
    CONSTRAINT FK_marketingLeadAttributions_companies FOREIGN KEY (companyId) REFERENCES dbo.companies(companyId),
    CONSTRAINT FK_marketingLeadAttributions_whatsappChannels FOREIGN KEY (channelId) REFERENCES dbo.whatsappChannels(channelId),
    CONSTRAINT FK_marketingLeadAttributions_clients FOREIGN KEY (clientId) REFERENCES dbo.clients(clientId),
    CONSTRAINT UQ_marketingLeadAttributions_CompanyProviderExternalEvent UNIQUE NONCLUSTERED (companyId, provider, externalEventId),
    CONSTRAINT CK_marketingLeadAttributions_Provider CHECK (provider IN ('meta')),
    CONSTRAINT CK_marketingLeadAttributions_ConversionChannel CHECK (conversionChannel IN ('whatsapp')),
    CONSTRAINT CK_marketingLeadAttributions_ConversionChannel_ChannelId CHECK (conversionChannel <> 'whatsapp' OR channelId IS NOT NULL),
    CONSTRAINT CK_marketingLeadAttributions_RawReferral_IsJson CHECK (rawReferral IS NULL OR ISJSON(rawReferral) = 1)
);
GO

CREATE NONCLUSTERED INDEX IX_marketingLeadAttributions_channelId ON dbo.marketingLeadAttributions (channelId);
GO
CREATE NONCLUSTERED INDEX IX_marketingLeadAttributions_clientId ON dbo.marketingLeadAttributions (clientId);
GO
CREATE NONCLUSTERED INDEX IX_marketingLeadAttributions_CompanyReferredAt ON dbo.marketingLeadAttributions (companyId, referredAt DESC);
GO
CREATE NONCLUSTERED INDEX IX_marketingLeadAttributions_CompanySourceIdReferredAt ON dbo.marketingLeadAttributions (companyId, sourceId, referredAt DESC);
GO
CREATE NONCLUSTERED INDEX IX_marketingLeadAttributions_CompanyCustomerPhone ON dbo.marketingLeadAttributions (companyId, customerPhone);
GO