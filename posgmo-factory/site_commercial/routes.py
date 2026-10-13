"""
Website commercial endpoints (mounted by business_intake_api.py under /site).

Public (the website calls these from the browser):
    POST /site/visit                count a visit (once per visitor per 30 min)
    GET  /site/stats                visit counter for the footer
    GET  /site/usage?visitorId=     the visitor's AI token allowance (token bar)
    POST /site/leads                mini registration ("ask_factory") or contact form ("contact_form")

GMO team only (header X-Admin-Key = SITE_ADMIN_KEY; disabled when it is unset):
    GET   /site/admin/overview      visits, tokens and leads at a glance
    GET   /site/admin/leads         leads to follow up (?status=new|contacted|qualified|won|lost)
    PATCH /site/admin/leads/{id}    change a lead's status / notes

Token allowance: each visitor (anonymous browser id) gets SITE_FREE_TOKENS of
AI analysis; registering raises it to SITE_REGISTERED_TOKENS. The anonymous id
lives in the browser and can be reset, so this is a soft limit — the per-IP
rate limit in business_intake_api.py is the hard one.
"""
from __future__ import annotations

import hmac
import os
import re
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from site_commercial import store

FREE_TOKENS = int(os.getenv("SITE_FREE_TOKENS", "40000"))
REGISTERED_TOKENS = int(os.getenv("SITE_REGISTERED_TOKENS", "400000"))
MAX_LEADS_PER_IP_PER_HOUR = 10
_VISITOR_ID = r"^[A-Za-z0-9_-]{8,64}$"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

router = APIRouter(prefix="/site")


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip().split(":")[0]
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------- tokens (also used by /intake/analyze)

def allowance(visitor_id: str) -> dict:
    registered = store.is_registered(visitor_id)
    limit = REGISTERED_TOKENS if registered else FREE_TOKENS
    used = store.tokens_used(visitor_id)
    return {"used": used, "allowance": limit, "remaining": max(0, limit - used), "registered": registered}


# ---------------------------------------------------------------- visits

class VisitIn(BaseModel):
    visitorId: str = Field(pattern=_VISITOR_ID)
    path: str = Field(default="/", max_length=200)
    language: str = Field(default="en", max_length=5)
    referrer: str = Field(default="", max_length=300)


@router.post("/visit")
def visit(v: VisitIn, request: Request) -> dict:
    counted = store.record_visit(v.visitorId, v.path, v.language, v.referrer, client_ip(request))
    return {"counted": counted, **store.visit_stats()}


@router.get("/stats")
def stats() -> dict:
    return store.visit_stats()


@router.get("/usage")
def usage(visitorId: str) -> dict:
    if not re.match(_VISITOR_ID, visitorId):
        raise HTTPException(status_code=400, detail="Invalid visitorId.")
    return allowance(visitorId)


# ---------------------------------------------------------------- leads

class AnalysisSummary(BaseModel):
    businessType: str = Field(default="", max_length=120)
    readiness: str = Field(default="", max_length=60)
    summary: str = Field(default="", max_length=1500)


class LeadIn(BaseModel):
    visitorId: str | None = Field(default=None, pattern=_VISITOR_ID)
    fullName: str = Field(min_length=2, max_length=120)
    email: str = Field(default="", max_length=160)
    phone: str = Field(default="", max_length=30)
    companyName: str = Field(default="", max_length=160)
    interestArea: str = Field(default="", max_length=120)
    message: str = Field(default="", max_length=2000)
    leadSource: Literal["ask_factory", "contact_form"]
    language: Literal["en", "es"] = "en"
    privacyConsentAccepted: bool
    analysis: AnalysisSummary | None = None
    website: str = Field(default="", max_length=200, description="Honeypot: real people leave it empty.")

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip()
        if v and not _EMAIL.match(v):
            raise ValueError("Invalid email.")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        v = v.strip()
        if v and len(re.sub(r"\D", "", v)) < 8:
            raise ValueError("Invalid phone.")
        return v


@router.post("/leads")
def create_lead(lead: LeadIn, request: Request) -> dict:
    if lead.website:  # bot filled the hidden field: pretend success, store nothing
        return {"ok": True}
    if not lead.privacyConsentAccepted:
        raise HTTPException(status_code=400, detail="Consent is required.")
    if not lead.email and not lead.phone:
        raise HTTPException(status_code=400, detail="An email or a phone number is required.")
    if lead.leadSource == "contact_form" and not lead.message.strip():
        raise HTTPException(status_code=400, detail="Write a message.")
    ip = client_ip(request)
    if store.recent_leads_from_ip(ip) >= MAX_LEADS_PER_IP_PER_HOUR:
        raise HTTPException(status_code=429, detail="Too many submissions. Try again later.")

    data = lead.model_dump(exclude={"analysis", "website"})
    data["privacyConsentAccepted"] = 1
    lead_id = store.create_lead(data, lead.analysis.model_dump() if lead.analysis else None, ip)
    response: dict = {"ok": True, "leadId": lead_id}
    if lead.visitorId:
        response["usage"] = allowance(lead.visitorId)
    return response


# ---------------------------------------------------------------- admin (lead follow-up)

def _require_admin(key: str | None) -> None:
    expected = os.getenv("SITE_ADMIN_KEY", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Admin is disabled: set SITE_ADMIN_KEY on the server.")
    if not key or not hmac.compare_digest(key, expected):
        raise HTTPException(status_code=401, detail="Wrong admin key.")


@router.get("/admin/overview")
def admin_overview(x_admin_key: str | None = Header(default=None)) -> dict:
    _require_admin(x_admin_key)
    return {
        "visits": store.visit_stats(),
        "visitsByDay": store.visits_by_day(30),
        "tokens": store.token_totals(),
        "leads": store.lead_counts(),
        "limits": {"freeTokens": FREE_TOKENS, "registeredTokens": REGISTERED_TOKENS},
    }


@router.get("/admin/leads")
def admin_leads(status: str | None = None, x_admin_key: str | None = Header(default=None)) -> dict:
    _require_admin(x_admin_key)
    if status and status not in store.LEAD_STATUSES:
        raise HTTPException(status_code=400, detail="Unknown status.")
    return {"leads": store.list_leads(status)}


class LeadUpdate(BaseModel):
    status: Literal["new", "contacted", "qualified", "won", "lost"] | None = None
    notes: str | None = Field(default=None, max_length=4000)


@router.patch("/admin/leads/{lead_id}")
def admin_update_lead(lead_id: int, update: LeadUpdate, x_admin_key: str | None = Header(default=None)) -> dict:
    _require_admin(x_admin_key)
    if not store.update_lead(lead_id, update.status, update.notes):
        raise HTTPException(status_code=404, detail="Lead not found or nothing to change.")
    return {"ok": True}
