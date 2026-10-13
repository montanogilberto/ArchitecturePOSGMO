"""
Business Intake runner — the flow the website calls (via business_intake_api.py).

    request (+ optional website URL, or an audio note)
          |
          v
    answer cache              same question + same GMO_MODULES.md → cached answer, 0 model calls
          |
          v
    understanding_agent       ONLY for audio: transcribe (1 model call)
          |
          v
    website (optional)        read the owner's site — plain HTTP, no model
          |
          v
    gather_business_evidence  plain Python: GMO_MODULES.md, schema columns, draft PRDs
          |
          v
    analyst_agent             1 model call: how the company joins GMO — REUSE / CONFIGURE /
                              EXTEND / CREATE / INVESTIGATE, readiness per layer,
                              onboarding plan, onboarding readiness

So a text request costs ONE model call, a repeated one costs none.
Read-only end to end: no PRD is written, no construction runs, no database is
touched. Turning a developmentRequests line into a PRD is factory_agent.py's job,
started deliberately by a person.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Blob, Content, Part
from pydantic import BaseModel

from agents.business_intake import cache
from agents.business_intake.agent import analyst_agent, understanding_agent
from agents.business_intake.evidence import gather_business_evidence
from agents.business_intake.modules import modules_version, normalize
from agents.business_intake.schema import BusinessAnalysis, NormalizedNeed
from agents.business_intake.website import WebsiteError, fetch_website
from llm_usage import UsageTracker, format_summary

logger = logging.getLogger(__name__)
_APP = "business_intake"
_sessions = InMemorySessionService()


class IntakeError(RuntimeError):
    """The model returned nothing usable."""


async def _run(agent, parts: list[Part], schema: type[BaseModel], usage: UsageTracker) -> BaseModel:
    runner = Runner(agent=agent, app_name=_APP, session_service=_sessions)
    user_id = f"intake-{uuid.uuid4()}"
    session = await _sessions.create_session(app_name=_APP, user_id=user_id)
    async for event in runner.run_async(
        user_id=user_id, session_id=session.id, new_message=Content(role="user", parts=parts),
    ):
        usage.observe(event)
    final = await _sessions.get_session(app_name=_APP, user_id=user_id, session_id=session.id)
    await _sessions.delete_session(app_name=_APP, user_id=user_id, session_id=session.id)
    raw = final.state.get(agent.output_key) if final else None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise IntakeError(f"{agent.name} returned non-JSON output") from exc
    if not isinstance(raw, dict):
        raise IntakeError(f"{agent.name} returned no output")
    return schema.model_validate(raw)


def _tokens(usage: UsageTracker) -> int:
    total = usage.summary()["total"]
    return total["prompt"] + total["output"] + total["thoughts"]


def _cache_key(text: str, url: str, language: str) -> str:
    return cache.make_key(normalize(text), url.strip().lower(), language, modules_version())


def lookup_cached(text: str, url: str = "", language: str = "en") -> dict | None:
    """A previous answer to the same text request, or None. Never calls a model."""
    if not text.strip():
        return None
    hit = cache.get(_cache_key(text, url, language))
    return {**hit, "cached": True, "usage": {"tokens": 0}} if hit else None


async def analyze_business_need(
    text: str = "",
    audio: bytes | None = None,
    audio_mime_type: str = "",
    language: str = "en",
    url: str = "",
    use_experience: bool = False,
) -> dict:
    """Returns {"status": "ok", "need", "evidence", "analysis", "website", "cached"} or
    {"status": "needs_clarification", "need", "question", "cached"}.

    use_experience adds factory_experience search, which costs an embedding call — off by default."""
    if not text.strip() and not audio:
        raise ValueError("Provide text, audio, or both.")

    key = None if audio else _cache_key(text, url, language)
    if key and (hit := cache.get(key)):
        return {**hit, "cached": True, "usage": {"tokens": 0}}

    usage = UsageTracker()
    try:
        transcript = ""
        if audio:
            parts = [Part(inline_data=Blob(mime_type=audio_mime_type, data=audio)),
                     Part(text="The audio note above is the business owner describing their need.")]
            need: NormalizedNeed = await _run(understanding_agent, parts, NormalizedNeed, usage)
            if not need.isUnderstandable:
                return {"status": "needs_clarification", "need": {"transcript": need.transcript, "request": ""},
                        "question": need.clarifyingQuestion, "cached": False, "usage": {"tokens": _tokens(usage)}}
            transcript = need.transcript
            text = "\n".join(t for t in (text.strip(), need.transcript) if t)

        website = None
        if url.strip():
            try:
                website = await asyncio.to_thread(fetch_website, url)
            except WebsiteError as exc:
                website = {"url": url.strip(), "error": str(exc)}

        match_text = " ".join([text, (website or {}).get("title", ""), (website or {}).get("description", "")])
        evidence = gather_business_evidence(match_text, use_experience=use_experience)
        payload = {
            "language": language,
            "answerIn": "Spanish" if language == "es" else "English",
            "request": text,
            "website": {k: website[k] for k in ("url", "title", "description", "text") if k in website}
            if website and "error" not in website else None,
            "evidence": evidence,
        }
        analysis: BusinessAnalysis = await _run(
            analyst_agent, [Part(text=json.dumps(payload, ensure_ascii=False))], BusinessAnalysis, usage,
        )

        # PRD Builder gate, enforced in code as well as in the prompt: development
        # requests only when GMO itself must be extended; never for onboarding.
        if analysis.onboardingReadiness != "READY_AFTER_EXTENSION":
            analysis.developmentRequests = []

        if not analysis.understood:
            result = {"status": "needs_clarification", "need": {"transcript": transcript, "request": ""},
                      "question": analysis.businessQuestions[0] if analysis.businessQuestions else ""}
        else:
            result = {
                "status": "ok",
                "need": {"transcript": transcript, "request": analysis.restatedNeed},
                "evidence": {
                    "candidates": [{"name": m["name"], "evidenceLevel": m["evidenceLevel"], "readiness": m["readiness"]}
                                   for m in evidence["candidateModules"]],
                    "verifiedFacts": evidence["verifiedFacts"],
                    "assumptions": evidence["assumptions"],
                },
                "analysis": analysis.model_dump(exclude={"understood", "restatedNeed"}),
                "website": {k: website[k] for k in ("url", "title", "error") if k in website} if website else None,
            }
        if key:
            cache.put(key, result)
        return {**result, "cached": False, "usage": {"tokens": _tokens(usage)}}
    finally:
        logger.info("business intake usage:\n%s", format_summary(usage.summary()))
