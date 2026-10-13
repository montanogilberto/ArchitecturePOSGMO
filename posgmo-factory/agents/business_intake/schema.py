"""
Business Intake schemas.

NormalizedNeed  — output of the understanding step, used ONLY for audio notes
                  (transcribes them; text requests skip this model call).
BusinessAnalysis — output of the analysis step, returned to the website.
"""
from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field


class NormalizedNeed(BaseModel):
    transcript: str = Field(
        default="",
        description="Verbatim transcript of the audio note in its original language. "
                    "Empty string when the input was text only.",
    )
    detectedLanguage: str = Field(description="ISO 639-1 code of the speaker's language, e.g. 'es' or 'en'.")
    request: str = Field(
        description="The business need restated in clear English, 1-3 sentences, in the "
                    "speaker's own terms — no solution design yet.",
    )
    businessType: str = Field(description="Short English label for the kind of business, e.g. 'Law firm'.")
    domainTerms: List[str] = Field(
        default_factory=list,
        description="2-8 English singular camelCase entity/process terms the need touches, "
                    "e.g. ['client', 'legalCase', 'followUp', 'hearing']. Used to search the "
                    "existing schema, so prefer the words a database table would use.",
    )
    isUnderstandable: bool = Field(
        description="False only if the business need cannot be determined at all "
                    "(silence, noise, a single unrelated word).",
    )
    clarifyingQuestion: str = Field(
        default="",
        description="Only when isUnderstandable is false: ONE short question, in the "
                    "speaker's language, asking what they need.",
    )


Basis = Literal["verified", "inferred", "unknown"]
Layer = Literal["database", "backend", "frontend", "mobile", "web", "agents", "notifications", "security"]
LayerStatus = Literal["AVAILABLE", "PARTIAL", "MISSING", "UNKNOWN"]
Decision = Literal["REUSE", "CONFIGURE", "EXTEND", "CREATE", "INVESTIGATE", "NOT_APPLICABLE"]
OnboardingReadiness = Literal[
    "READY",
    "READY_WITH_CONFIGURATION",
    "READY_AFTER_EXTENSION",
    "NEEDS_BUSINESS_CLARIFICATION",
    "NEEDS_REPOSITORY_INVESTIGATION",
    "NEEDS_BOTH",
]


class Placement(BaseModel):
    application: str = Field(description="'POS GMO', 'SmartLoans', 'Arcade / Casino' (the company joins it as a tenant).")
    asCompany: bool = Field(description="True: the business operates as a company (tenant) inside GMO.")
    explanation: str


class WorkflowStep(BaseModel):
    step: str
    basis: Basis = Field(description="verified = the owner said it; inferred = typical for this business, not confirmed; unknown.")


class RequiredCapability(BaseModel):
    capability: str
    basis: Basis
    decision: Decision


class ExistingCapability(BaseModel):
    """REUSE or CONFIGURE: usable by the company now, possibly after configuration."""
    capability: str
    evidence: str = Field(description="Implementation evidence: verified routes / stored procedures / tables / app files.")
    mobile: LayerStatus = Field(description="Copy from the evidence readiness; never AVAILABLE without evidence.")
    web: LayerStatus
    backend: LayerStatus
    database: LayerStatus = "UNKNOWN"
    configurationRequired: str = Field(default="", description="Company-specific setup needed, or empty.")


class ConfigurationItem(BaseModel):
    capability: str
    setting: str = Field(description="What the company sets up, without development.")
    why: str


class ExtendItem(BaseModel):
    capability: str
    existing: str = Field(description="What exists today and who owns it.")
    extension: str = Field(description="What must be added to the GMO capability (for every company, not just this one).")
    reason: str
    affectedAreas: List[Layer] = Field(default_factory=list)


class InvestigateItem(BaseModel):
    capability: str
    knownEvidence: str
    unknowns: str
    inspect: str = Field(description="What must be inspected in the repositories to decide.")
    possibleOutcomes: str = Field(description="e.g. 'REUSE if X, CONFIGURE if Y, EXTEND if Z'.")


class CreateItem(BaseModel):
    """A NEW GMO capability (ecosystem-level), never a company-specific application."""
    capability: str
    suggestedModule: str = Field(description="camelCase singular module name, e.g. 'legalCase'.")
    whyNotReuse: str = Field(description="Why reuse, configuration or extension is not possible.")
    scope: str
    layers: List[Layer] = Field(default_factory=list)


class NotApplicableItem(BaseModel):
    capability: str
    reason: str


class Infrastructure(BaseModel):
    """Default answer is NO for all: the company uses GMO's existing apps and infrastructure."""
    newWebsite: bool = False
    newMobileApp: bool = False
    newBackend: bool = False
    newDatabase: bool = False
    newDeployment: bool = False
    newHosting: bool = False
    explanation: str = ""


class DevelopmentRequest(BaseModel):
    type: Literal["EXTEND_CAPABILITY", "NEW_CAPABILITY"]
    request: str = Field(description="One English line for the PRD Builder, about a GMO capability (never a company app).")


class BusinessAnalysis(BaseModel):
    understood: bool = Field(
        default=True,
        description="False only if no business need can be determined at all (noise, an unrelated phrase). "
                    "Then put ONE question in businessQuestions and leave the other lists empty.",
    )
    restatedNeed: str = Field(default="", description="The business need restated in clear English, 1-2 sentences.")
    summary: str = Field(description="Business understanding: what the owner wants, without inventing requirements.")
    businessType: str
    placement: Placement
    onboarding: str = Field(description="Recommended GMO onboarding: how this company operates inside the existing GMO ecosystem.")
    workflow: List[WorkflowStep] = Field(default_factory=list)
    requiredCapabilities: List[RequiredCapability] = Field(default_factory=list)
    existingCapabilities: List[ExistingCapability] = Field(default_factory=list)
    configuration: List[ConfigurationItem] = Field(default_factory=list)
    extend: List[ExtendItem] = Field(default_factory=list)
    create: List[CreateItem] = Field(default_factory=list)
    investigate: List[InvestigateItem] = Field(default_factory=list)
    notApplicable: List[NotApplicableItem] = Field(default_factory=list)
    businessQuestions: List[str] = Field(
        default_factory=list,
        description="Only high-impact questions (at most 3, most important first).",
    )
    mobileExperience: str = Field(description="How the company uses the existing GMO Android/iOS app.")
    webExperience: str = Field(description="How the company uses the existing GMO web operations platform.")
    infrastructure: Infrastructure = Field(default_factory=Infrastructure)
    risks: List[str] = Field(default_factory=list)
    companyIsolation: str = Field(description="The companyId tenant boundary.")
    onboardingReadiness: OnboardingReadiness
    onboardingPlan: List[str] = Field(
        default_factory=list,
        description="Ordered steps to get the company operating: register, activate modules, configure, invite users…",
    )
    developmentRequests: List[DevelopmentRequest] = Field(
        default_factory=list,
        description="Only when onboardingReadiness is READY_AFTER_EXTENSION: GMO development needed. Otherwise empty.",
    )
    factoryRecommendation: str = Field(description="The smallest viable path to get this company operating inside GMO.")
