-- =============================================================================
-- dbo.marketingAds — the ad set and campaign behind each attributed lead
-- (Client Acquisition, phase 1b)
-- =============================================================================
-- WHY: Meta's Click-to-WhatsApp referral carries only the AD id (stored as
--      marketingLeadAttributions.sourceId), never the ad set or campaign. This
--      dimension maps each ad to them so leads can be compared per offer.
-- WHAT: one row per (companyId, provider, adId). Joined to the attributions by
--       (companyId, provider, sourceId = adId); no FK, attribution rows stay
--       immutable.
-- Writers: modules/whatsappCloud._record_ad_referral (action 1, pending) and
--          smartloans_workers marketingAdsSyncWorker (action 2, via
--          POST /marketingAds) → sql/sp_marketingAds.sql
-- Readers: POST /all_marketingAds, and sp_marketingLeadAttributions_all (join)
-- Run order: this file → sp_marketingAds.sql → sp_marketingAds_all.sql
--            → sp_marketingLeadAttributions_all.sql → deploy the backend
--            → 2026-11-12_marketingAds_backfill.sql → deploy the worker.
-- Safe to re-run. ROLLBACK: 2026-11-12_marketingAds_ROLLBACK.sql
-- =============================================================================

IF OBJECT_ID(N'dbo.marketingAds', N'U') IS NULL
CREATE TABLE [dbo].[marketingAds] (
    marketingAdId   INT IDENTITY(1,1) NOT NULL,
    companyId       INT NOT NULL,
    provider        NVARCHAR(20) NOT NULL,
    adId            NVARCHAR(64) NOT NULL,
    adName          NVARCHAR(255) NULL,
    adsetId         NVARCHAR(64) NULL,
    adsetName       NVARCHAR(255) NULL,
    campaignId      NVARCHAR(64) NULL,
    campaignName    NVARCHAR(255) NULL,
    adAccountId     NVARCHAR(64) NULL,
    lookupStatus    NVARCHAR(20) NOT NULL CONSTRAINT DF_marketingAds_lookupStatus DEFAULT N'pending',
    lookupAttempts  INT NOT NULL CONSTRAINT DF_marketingAds_lookupAttempts DEFAULT 0,
    lastError       NVARCHAR(255) NULL,
    lastSyncedAt    DATETIME2 NULL,
    created_At      DATETIME2 NOT NULL CONSTRAINT DF_marketingAds_created_At DEFAULT SYSUTCDATETIME(),
    updated_at      DATETIME2 NULL,
    CONSTRAINT PK_marketingAds PRIMARY KEY CLUSTERED (marketingAdId),
    CONSTRAINT FK_marketingAds_companies FOREIGN KEY (companyId) REFERENCES dbo.companies(companyId),
    CONSTRAINT UQ_marketingAds_CompanyProviderAd UNIQUE NONCLUSTERED (companyId, provider, adId),
    CONSTRAINT CK_marketingAds_Provider CHECK (provider IN ('meta')),
    CONSTRAINT CK_marketingAds_LookupStatus CHECK (lookupStatus IN ('pending', 'resolved', 'not_found', 'forbidden', 'error')),
    CONSTRAINT CK_marketingAds_LookupAttempts CHECK (lookupAttempts >= 0)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_marketingAds_CompanyAdset' AND object_id = OBJECT_ID(N'dbo.marketingAds'))
    CREATE NONCLUSTERED INDEX IX_marketingAds_CompanyAdset ON dbo.marketingAds (companyId, adsetId);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_marketingAds_CompanyCampaign' AND object_id = OBJECT_ID(N'dbo.marketingAds'))
    CREATE NONCLUSTERED INDEX IX_marketingAds_CompanyCampaign ON dbo.marketingAds (companyId, campaignId);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_marketingAds_CompanyLookup' AND object_id = OBJECT_ID(N'dbo.marketingAds'))
    CREATE NONCLUSTERED INDEX IX_marketingAds_CompanyLookup ON dbo.marketingAds (companyId, lookupStatus, lookupAttempts);
GO
