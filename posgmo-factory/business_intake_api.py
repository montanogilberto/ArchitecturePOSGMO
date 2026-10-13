"""
Business Intake HTTP API — lets the GMO website call the Business Intake
agent (agents/business_intake/) with a written request or an audio note.

    POST /intake/analyze
      { "text": "...", "url": "https://their-business.com", "language": "es" }
        (or "audioBase64" + "audioMimeType" for an audio note)
      -> { "status": "ok", "need", "evidence", "analysis", "website", "cached" }
       | { "status": "needs_clarification", "need", "question", "cached" }
    GET  /health

Read-only: analysis only. Nothing is written and no construction is started.
Cost: a text request makes ONE model call; a repeated one is answered from
the cache with none (and does not count against the rate limit).

This endpoint is public (the website calls it from the browser) and every
call spends Gemini tokens, so it enforces: an origin allow-list (CORS), input
size limits, a per-IP hourly limit, and a timeout. The rate limit is
in-memory, i.e. per process — enough for one App Service instance, not a
substitute for a gateway if this is scaled out.

Run:
    uvicorn business_intake_api:app --port 8090
Env:
    GEMINI_API_KEY / GOOGLE_API_KEY       Gemini access (same as the rest of the factory)
    INTAKE_ALLOWED_ORIGINS                comma-separated website origins
                                          (default: http://localhost:8080,http://127.0.0.1:8080)
    INTAKE_ALLOW_LOCAL_ORIGINS            also accept localhost / local-network origins on any port and the
                                          native app (capacitor://localhost) — default true; set false in production
    INTAKE_RATE_LIMIT_PER_HOUR            requests per client IP per hour (default 20)
    SITE_FREE_TOKENS / SITE_REGISTERED_TOKENS   AI token allowance per visitor (default 40,000 / 400,000)
    SITE_ADMIN_KEY                        key for the lead follow-up admin (admin is off when unset)
    SITE_DATA_DIR                         where the visits/leads database lives (Azure: /home/data)
    FACTORY_INTAKE_MODEL                  model for both intake steps (default gemini-2.5-flash)
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import os
import time
from collections import defaultdict, deque
from typing import Literal

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from agents.business_intake.runner import IntakeError, analyze_business_need, lookup_cached  # noqa: E402
from site_commercial import store as site_store  # noqa: E402
from site_commercial.routes import allowance, router as site_router  # noqa: E402

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 2000
MAX_AUDIO_BYTES = 4_000_000          # ~2 minutes of 16 kHz mono WAV
TIMEOUT_SECONDS = 90
ALLOWED_AUDIO_TYPES = {
    "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3", "audio/ogg", "audio/webm",
    "audio/mp4", "audio/aac", "audio/flac", "audio/x-m4a",
}
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv(
        "INTAKE_ALLOWED_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080",
    ).split(",") if o.strip()
]
RATE_LIMIT_PER_HOUR = int(os.getenv("INTAKE_RATE_LIMIT_PER_HOUR", "20"))
# Development: also accept the website from this machine or the local network (any port),
# and the native iOS/Android app. Turn off in production with INTAKE_ALLOW_LOCAL_ORIGINS=false.
ALLOW_LOCAL_ORIGINS = os.getenv("INTAKE_ALLOW_LOCAL_ORIGINS", "true").lower() == "true"
LOCAL_ORIGINS_REGEX = (
    r"^(https?://(localhost|127\.0\.0\.1|\[::1\]|10(\.\d{1,3}){3}|192\.168(\.\d{1,3}){2}"
    r"|172\.(1[6-9]|2\d|3[01])(\.\d{1,3}){2})(:\d+)?|capacitor://localhost|ionic://localhost)$"
)

app = FastAPI(title="GMO Factory — Business Intake")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=LOCAL_ORIGINS_REGEX if ALLOW_LOCAL_ORIGINS else None,
    allow_methods=["POST", "GET", "PATCH"],
    allow_headers=["Content-Type", "X-Admin-Key"],
)
app.include_router(site_router)  # visit counter, token allowance, leads, lead follow-up

_calls: dict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip().split(":")[0]
    return request.client.host if request.client else "unknown"


def _check_rate_limit(ip: str) -> None:
    now = time.monotonic()
    window = _calls[ip]
    while window and now - window[0] > 3600:
        window.popleft()
    if len(window) >= RATE_LIMIT_PER_HOUR:
        raise HTTPException(status_code=429, detail="Too many analyses from this address. Try again later.")
    window.append(now)


class AnalyzeRequest(BaseModel):
    text: str = Field(default="", max_length=MAX_TEXT_CHARS)
    url: str = Field(default="", max_length=500, description="The business owner's website (optional).")
    visitorId: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,64}$",
                                  description="Anonymous browser id: counts this visitor's AI tokens.")
    audioBase64: str | None = None
    audioMimeType: str | None = None
    language: Literal["en", "es"] = "en"


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/intake/analyze")
async def analyze(req: AnalyzeRequest, request: Request) -> dict:
    audio: bytes | None = None
    mime = ""
    if req.audioBase64:
        mime = (req.audioMimeType or "").split(";")[0].strip().lower()
        if mime not in ALLOWED_AUDIO_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported audio type '{mime}'.")
        if len(req.audioBase64) > MAX_AUDIO_BYTES * 4 // 3 + 4:
            raise HTTPException(status_code=413, detail="Audio note is too long (about 2 minutes maximum).")
        try:
            audio = base64.b64decode(req.audioBase64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=400, detail="audioBase64 is not valid base64.")
    if not req.text.strip() and not audio:
        raise HTTPException(status_code=400, detail="Write your need or record an audio note.")
    url = req.url.strip()
    if url and not url.lower().startswith(("http://", "https://")):
        url = f"https://{url}"

    if not audio and (cached := lookup_cached(req.text, url, req.language)):
        # No model call: doesn't count against the rate limit or the token allowance.
        return {**cached, **({"allowance": allowance(req.visitorId)} if req.visitorId else {})}

    if req.visitorId and allowance(req.visitorId)["remaining"] <= 0:
        raise HTTPException(status_code=402, detail={"code": "token_limit", "allowance": allowance(req.visitorId)})

    _check_rate_limit(_client_ip(request))
    try:
        result = await asyncio.wait_for(
            analyze_business_need(text=req.text, audio=audio, audio_mime_type=mime, language=req.language, url=url),
            timeout=TIMEOUT_SECONDS,
        )
        if req.visitorId:
            site_store.add_tokens(req.visitorId, result.get("usage", {}).get("tokens", 0))
            result["allowance"] = allowance(req.visitorId)
        return result
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="The analysis took too long. Please try again.")
    except IntakeError as exc:
        logger.warning("business intake failed: %s", exc)
        raise HTTPException(status_code=502, detail="The Factory could not analyze this request. Please try again.")
