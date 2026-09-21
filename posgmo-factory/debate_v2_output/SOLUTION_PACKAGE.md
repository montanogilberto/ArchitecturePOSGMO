# Solution Package

_Generated 2026-09-19T01:47:15+00:00 — agentic debate spike (Phase 2-7), not the production factory._

## 1. Problem Statement

> Add one-time-use enforcement for per-client promotion codes. Context: (1) Promotion codes today are generic strings (e.g. '2X1'), not unique per client; an existing stored procedure sp_income_apply_promo (called via POST /income/apply-promo) already validates that a code exists and is active, and computes/applies the discount to an income row — that promotions/codes definition table is outside this PRD's scope. (2) There is currently NO mechanism tying a promotion code to a specific client or tracking usage — nothing stops the same client reusing the same code forever. (3) The '2X1 welcome coupon on first purchase' is currently enforced ONLY client-side in the POS Cart page as a heuristic (offered when the client's posRewardBalances.lifetimeEarned is zero) — trivially bypassed by calling the backend directly. (4) Promotion codes are generic/shared, not per-client-unique strings; usage must be tracked per (companyId, clientId, promotionCode). (5) clientId availability inside sp_income_apply_promo: sp_income_apply_promo's own payload is only { incomeId, companyId, code, userId } with no clientId parameter, BUT the existing dbo.income table already stores clientId on every row (set at insert time by the existing POST /income endpoint, which always requires clientId). Since sp_income_apply_promo already receives incomeId, it can read clientId directly off the dbo.income row for that incomeId (e.g. SELECT clientId FROM dbo.income WHERE incomeId = @incomeId) — no new parameter needs to be added to the apply-promo API contract. That looked-up clientId is what gets passed into the new sp_promotionRedemptions_redeem call inside the same transaction. The fix: a new promotionRedemptions ledger table with a filtered unique index on (companyId, clientId, promotionCode) WHERE status='applied', with redeem/check-eligibility/reverse endpoints, wired into sp_income_apply_promo as a manual follow-up so it becomes the actual database-level one-time-use gate.

## 2. Existing-System / Reuse Map

**Verified facts:**
- 1 draft PRD file(s) already exist for 'client': prd_clientFollowUp.json. (`repo:posgmo-factory/tests/`)
- No generated output exists yet for 'client' in generated/, local_export/, or pr_export/. (`repo:posgmo-factory/{generated,local_export,pr_export}/`)
- 'client' is mentioned in the architecture knowledge base: Backend/backend_routes.json.json, Backend/backend_authentication.json (2).json, Backend/backend_models.json.json, Backend/backend_business_domains.json.json, Backend/backend_stored_procedures.json.json, Backend/backend_authentication.json.json, Backend/backend_ai_features.json.json, Backend/backend_database.json.json, Frontend/frontend_api_contracts.json.json, Frontend/frontend_modules.json.json, Frontend/frontend_routes.json.json, Frontend/frontend_ui_patterns.json.json, Frontend/frontend_components.json.json, Frontend/frontend_knowledge.json, Database/ER_Diagram.csv, Database/structure_database.csv, Database/sql_tables.json. (`knowledge:Backend/backend_routes.json.json,Backend/backend_authentication.json (2).json,Backend/backend_models.json.json,Backend/backend_business_domains.json.json,Backend/backend_stored_procedures.json.json,Backend/backend_authentication.json.json,Backend/backend_ai_features.json.json,Backend/backend_database.json.json,Frontend/frontend_api_contracts.json.json,Frontend/frontend_modules.json.json,Frontend/frontend_routes.json.json,Frontend/frontend_ui_patterns.json.json,Frontend/frontend_components.json.json,Frontend/frontend_knowledge.json,Database/ER_Diagram.csv,Database/structure_database.csv,Database/sql_tables.json`)
- 3 real table(s) matching 'client' exist in the schema snapshot: ClientFaceRecognitions, clientWallets, clients. (`repo:Database/structure_database.csv`)
- Parent table 'clients' exists in the schema; it already has 0 child table(s) via FK. (`repo:Database/sql_relationships.json`)
- Parent table 'companies' exists in the schema; it already has 2 child table(s) via FK. (`repo:Database/sql_relationships.json`)
- No generated output exists yet for 'income' in generated/, local_export/, or pr_export/. (`repo:posgmo-factory/{generated,local_export,pr_export}/`)
- 'income' is mentioned in the architecture knowledge base: Backend/backend_stored_procedures.json (2).json, Backend/backend_routes.json.json, Backend/backend_authentication.json (2).json, Backend/backend_business_domains.json.json, Backend/backend_stored_procedures.json.json, Backend/backend_schemas.json.json, Frontend/frontend_api_contracts.json.json, Frontend/frontend_modules.json.json, Frontend/frontend_routes.json.json, Frontend/frontend_ui_patterns.json.json, Frontend/frontend_components.json.json, Frontend/frontend_knowledge.json, Database/ER_Diagram.csv, Database/structure_database.csv, Database/sql_tables.json, Database/sql_relationships.json. (`knowledge:Backend/backend_stored_procedures.json (2).json,Backend/backend_routes.json.json,Backend/backend_authentication.json (2).json,Backend/backend_business_domains.json.json,Backend/backend_stored_procedures.json.json,Backend/backend_schemas.json.json,Frontend/frontend_api_contracts.json.json,Frontend/frontend_modules.json.json,Frontend/frontend_routes.json.json,Frontend/frontend_ui_patterns.json.json,Frontend/frontend_components.json.json,Frontend/frontend_knowledge.json,Database/ER_Diagram.csv,Database/structure_database.csv,Database/sql_tables.json,Database/sql_relationships.json`)
- 3 real table(s) matching 'income' exist in the schema snapshot: income, incomeDetailOptions, incomeDetails. (`repo:Database/structure_database.csv`)
- 5 draft PRD file(s) already exist for 'reward': prd_posRewardBalance.json, prd_posRewardCatalogItem.json, prd_posRewardProductRate.json, prd_posRewardRedemption.json, prd_posRewardTransaction.json. (`repo:posgmo-factory/tests/`)
- prd_posRewardBalance.json description explicitly calls out an existing/adjacent concept: "Materialized current POS loyalty points balance per client — a projection over posRewardTransactions, kept in sync transactionally by the same stored procedures that insert ledger rows (sp_posRewardTransactions_earnFromTicket, sp_posRewardTransactions_adjust, sp_posRewardRedemptions_redeem). Never written directly by the frontend. Fully separate from the existing loan-behavior rewardBalances table — no shared key, no conversion." (`repo:posgmo-factory/tests/prd_posRewardBalance.json`)
- prd_posRewardProductRate.json description explicitly calls out an existing/adjacent concept: "Configurable POS loyalty points earned per unit sold, for a given product. Companion table to products — does not alter the existing products table, which stays fully owned by the products module. One active rate row per productId+companyId; companyId is auto-injected. Read server-side by sp_posRewardTransactions_earnFromTicket when a ticket is finalized — never trusted from the frontend." (`repo:posgmo-factory/tests/prd_posRewardProductRate.json`)
- prd_posRewardTransaction.json description explicitly calls out an existing/adjacent concept: "Immutable POS loyalty points ledger — one INSERT-only row per points event (earn from a completed POS ticket, redemption against the reward catalog, manual admin adjustment). posRewardBalances is a materialized projection over this ledger, updated transactionally by the same SP that inserts a row here. Corrections are new ADJUSTMENT entries, never UPDATEs — a client's point history must always be traceable back to a specific ticket or redemption. Logically and structurally separate from the existing loan-behavior rewardTransactions table and from any arcade chip ledger: no FK, no shared endpoint, and no function anywhere converts between them." (`repo:posgmo-factory/tests/prd_posRewardTransaction.json`)
- No generated output exists yet for 'reward' in generated/, local_export/, or pr_export/. (`repo:posgmo-factory/{generated,local_export,pr_export}/`)
- No table matching 'reward' exists in the current schema snapshot (119 tables checked) — any PRD text claiming an existing same-domain table should be treated as unverified against this source. (`repo:Database/structure_database.csv`)
- Parent table 'clients' exists in the schema; it already has 0 child table(s) via FK. (`repo:Database/sql_relationships.json`)
- Parent table 'companies' exists in the schema; it already has 2 child table(s) via FK. (`repo:Database/sql_relationships.json`)
- Parent table 'products' exists in the schema; it already has 0 child table(s) via FK. (`repo:Database/sql_relationships.json`)

**Unverified assumptions (flagged, not relied upon as fact):**
- No draft PRD files found under tests/ matching 'income' — assuming no prior design work exists (unverified: naming could differ).
- 'reward' is not documented in any Backend/Frontend/Database knowledge file — assuming it is not an established business domain yet (unverified: the knowledge base may simply be incomplete).
- Parent table 'posRewardCatalogItem' referenced by a draft PRD was NOT found in the schema snapshot — unverified: either a naming mismatch or the table does not exist yet.

## 3. Participants

- **product_owner** (product_owner)
- **architect** (architect)
- **domain_expert** (domain_expert)
- **critic** (critic)
- **ux_expert** (ux_expert)

## 4. Candidate Solutions (independent, blind proposals)

### product_owner
> The proposed solution to enforce one-time-use for promotion codes by tracking redemptions per client within the `sp_income_apply_promo` workflow is essential to meet business requirements and prevent abuse.

- confidence: 0.95
- evidence: There is currently NO mechanism tying a promotion code to a specific client or tracking usage — nothing stops the same client reusing the same code forever.
- evidence: The '2X1 welcome coupon on first purchase' is currently enforced ONLY client-side in the POS Cart page as a heuristic (offered when the client's posRewardBalances.lifetimeEarned is zero) — trivially bypassed by calling the backend directly.
- evidence: Promotion codes are generic/shared, not per-client-unique strings; usage must be tracked per (companyId, clientId, promotionCode).
- evidence: clientId availability inside sp_income_apply_promo: sp_income_apply_promo's own payload is only { incomeId, companyId, code, userId } with no clientId parameter, BUT the existing dbo.income table already stores clientId on every row (set at insert time by the existing POST /income endpoint, which always requires clientId). Since sp_income_apply_promo already receives incomeId, it can read clientId directly off the dbo.income row for that incomeId (e.g. SELECT clientId FROM dbo.income WHERE incomeId = @incomeId) — no new parameter needs to be added to the apply-promo API contract.
- evidence: 3 real table(s) matching 'income' exist in the schema snapshot: income, incomeDetailOptions, incomeDetails.
- evidence: Parent table 'clients' exists in the schema; it already has 0 child table(s) via FK.
- evidence: Parent table 'companies' exists in the schema; it already has 2 child table(s) via FK.

### architect
> The proposed one-time-use enforcement for promotion codes should be implemented as a new, dedicated 'Promotion Redemptions' module, encapsulating the new ledger table and its associated stored procedures.

- confidence: 0.90
- evidence: Promotion codes are generic/shared, not per-client-unique strings; usage must be tracked per (companyId, clientId, promotionCode).
- evidence: The fix: a new promotionRedemptions ledger table with a filtered unique index on (companyId, clientId, promotionCode) WHERE status='applied', with redeem/check-eligibility/reverse endpoints, wired into sp_income_apply_promo as a manual follow-up so it becomes the actual database-level one-time-use gate.
- evidence: prd_posRewardTransaction.json description explicitly calls out an existing/adjacent concept: "Immutable POS loyalty points ledger — one INSERT-only row per points event (earn from a completed POS ticket, redemption against the reward catalog, manual admin adjustment). posRewardBalances is a materialized projection over this ledger, updated transactionally by the same SP that inserts a row here. Corrections are new ADJUSTMENT entries, never UPDATEs — a client's point history must always be traceable back to a specific ticket or redemption. Logically and structurally separate from the existing loan-behavior rewardTransactions table and from any arcade chip ledger: no FK, no shared endpoint, and no function anywhere converts between them."

## 5. Debate Summary

- **domain_expert** challenged **architect**: The proposal to implement 'Promotion Redemptions' as a new, dedicated module might over-segment the domain by creating a parallel concept for redemption tracking.
  - While promotion codes are distinct from POS loyalty points, the core business concept of 'redemption' and 'ledgering usage' is fundamentally similar to the existing `posRewardRedemption` and `posRewardTransaction` concepts. Creating a completely new top-level module for 'Promotion Redemptions' risks establishing a fragmented domain model where a more generalized 'Redemptions' or 'Promotions' domain could encompass various types of redemption mechanisms.
- **critic** challenged **product_owner**: The product owner's claim that the proposed solution, specifically embedding the `clientId` lookup and new redemption logic directly within `sp_income_apply_promo`, is 'essential' might overlook the architectural risks of increasing complexity and coupling in a critical stored procedure.
  - While the business requirement for one-time-use enforcement is clear, the proposed method of having `sp_income_apply_promo` perform a `clientId` lookup and then call a new redemption procedure adds responsibilities to an existing, critical stored procedure. This increases its complexity, couples discount application tightly with promotion redemption, and potentially violates the Single Responsibility Principle.
- **ux_expert** challenged **product_owner**: The product owner's proposal, while addressing the backend enforcement of one-time-use promotion codes, critically omits any consideration for the user interaction model, which is essential for a successful implementation given the existing 'trivially bypassed' client-side heuristic.
  - Simply shifting enforcement to the backend without designing how users will discover, apply, and receive clear feedback on these codes within an embedded flow (like the POS Cart) will lead to a poor user experience and potential confusion, undermining the value of the backend fix. The interaction model needs explicit design to ensure usability.
- **architect** defended original position
  - Promotion codes are generic discount strings tracked per client, distinct from POS loyalty points which are a managed currency with their own ledger. Creating a dedicated module for promotion code redemptions prevents over-generalization and maintains clear domain boundaries, consistent with how `posRewardTransaction` specifically tracks POS loyalty points rather than a generic redemption concept.
- **product_owner** revised to: The enforcement of one-time-use promotion codes requires a two-pronged approach: robust, transactional backend validation within sp_income_apply_promo to prevent abuse, coupled with essential frontend updates to guide users and provide clear feedback on promotion eligibility and redemption status.
  - While embedding redemption logic within `sp_income_apply_promo` increases its responsibilities, it is critical for ensuring atomic, database-level enforcement and preventing race conditions for one-time-use codes, leveraging existing `clientId` data. However, the `ux_expert` is correct that backend changes alone are insufficient; a corresponding update to the client-side POS Cart is necessary to provide a coherent user experience, communicate eligibility, and prevent user confusion, especially given the existing client-side heuristic.

## 6. Comparison

- ` 9.8` — The enforcement of one-time-use promotion codes requires a two-pronged approach: robust, transactional backend validation within sp_income_apply_promo to prevent abuse, coupled with essential frontend updates to guide users and provide clear feedback on promotion eligibility and redemption status.
- ` 8.5` — The proposed 'Promotion Redemptions' module should remain a new, dedicated module due to the distinct nature of promotion codes versus loyalty points, aligning with existing patterns of domain-specific ledgering.

## 7. Decision

**Selected:** The enforcement of one-time-use promotion codes requires a two-pronged approach: robust, transactional backend validation within sp_income_apply_promo to prevent abuse, coupled with essential frontend updates to guide users and provide clear feedback on promotion eligibility and redemption status.

**Rationale:** While embedding redemption logic within `sp_income_apply_promo` increases its responsibilities, it is critical for ensuring atomic, database-level enforcement and preventing race conditions for one-time-use codes, leveraging existing `clientId` data. However, the `ux_expert` is correct that backend changes alone are insufficient; a corresponding update to the client-side POS Cart is necessary to provide a coherent user experience, communicate eligibility, and prevent user confusion, especially given the existing client-side heuristic.

**Confidence:** 0.95

**Evidence:**
- Promotion codes today are generic strings (e.g. '2X1'), not unique per client; an existing stored procedure sp_income_apply_promo (called via POST /income/apply-promo) already validates that a code exists and is active, and computes/applies the discount to an income row — that promotions/codes definition table is outside this PRD's scope.
- There is currently NO mechanism tying a promotion code to a specific client or tracking usage — nothing stops the same client reusing the same code forever.
- The '2X1 welcome coupon on first purchase' is currently enforced ONLY client-side in the POS Cart page as a heuristic (offered when the client's posRewardBalances.lifetimeEarned is zero) — trivially bypassed by calling the backend directly.
- sp_income_apply_promo's own payload is only { incomeId, companyId, code, userId } with no clientId parameter, BUT the existing dbo.income table already stores clientId on every row (set at insert time by the existing POST /income endpoint, which always requires clientId). Since sp_income_apply_promo already receives incomeId, it can read clientId directly off the dbo.income row for that incomeId (e.g. SELECT clientId FROM dbo.income WHERE incomeId = @incomeId) — no new parameter needs to be added to the apply-promo API contract. That looked-up clientId is what gets passed into the new sp_promotionRedemptions_redeem call inside the same transaction.
- The fix: a new promotionRedemptions ledger table with a filtered unique index on (companyId, clientId, promotionCode) WHERE status='applied', with redeem/check-eligibility/reverse endpoints, wired into sp_income_apply_promo as a manual follow-up so it becomes the actual database-level one-time-use gate.

## 8. Rejected Alternatives

- **The proposed solution to enforce one-time-use for promotion codes by tracking redemptions per client within the `sp_income_apply_promo` workflow is essential to meet business requirements and prevent abuse.** (proposed by product_owner)
  - Reason: Superseded by product_owner's own rebuttal after challenge(s).
- **The proposed 'Promotion Redemptions' module should remain a new, dedicated module due to the distinct nature of promotion codes versus loyalty points, aligning with existing patterns of domain-specific ledgering.** (proposed by architect)
  - Reason: Lower-confidence alternative not selected (0.90 vs 0.95).

## 9. Risks / Open Questions

- (product_owner) Potential performance impact on `sp_income_apply_promo` due to the added ledger lookup and write operations.
- (product_owner) Complexity in handling `reverse` operations for redemptions if an `income` transaction is subsequently cancelled or modified, requiring a corresponding ledger entry reversal.
- (architect) Ensuring transactional integrity between the existing `sp_income_apply_promo` logic and the new `sp_promotionRedemptions_redeem` call within a single database transaction.
- (architect) Potential for increased complexity in deployment and maintenance due to the introduction of a new module with its own data model and stored procedures.
- (architect) Careful design needed to prevent circular dependencies if the new module's components were to inadvertently depend on the `income` module for non-orchestration purposes.
- (domain_expert) Proliferation of distinct, but conceptually similar, modules for different types of rewards/promotions, leading to increased maintenance overhead and potential for inconsistent patterns.
- (domain_expert) Difficulty in implementing cross-promotion or combined reward strategies in the future if redemption logic is too siloed.
- (critic) Increased complexity and maintenance burden for `sp_income_apply_promo`.
- (critic) Tighter coupling between the core discount application logic and the new promotion redemption tracking.
- (critic) Potential for performance degradation due to an additional lookup within a critical transaction.
- (critic) Violation of the Single Responsibility Principle for `sp_income_apply_promo`.
- (ux_expert) Poor user experience if the interaction model for applying codes is not explicitly designed.
- (ux_expert) Increased user frustration if eligibility or redemption status is not clearly communicated.
- (ux_expert) Potential for increased support calls due to user confusion about promotion code validity.
- (ux_expert) Missed opportunity to improve the overall promotion application flow beyond just backend validation.
- (product_owner) Increased complexity and coupling within sp_income_apply_promo due to added responsibilities.
- (product_owner) Potential for poor user experience and confusion if frontend updates are not adequately designed and implemented alongside backend changes.

## 10. Next Step

This package records WHY a solution was selected. Generating the actual
database/backend/frontend artifacts is the existing deterministic factory's
job (`orchestrator.py`) — this debate does not do that (see acceptance
criterion #10 in the Phase 2-7 design notes).