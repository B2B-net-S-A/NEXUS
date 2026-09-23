"""„Z historii klienta” — sekcja 8 profilu Championa, blok maszynowy.

Luna (klucz `champion_draft`) streszcza, za co ten klient odrzucał kandydatów
i co zniechęcało kandydatów, z danych, które NEXUS już ma:

* werdykty hiring managera (`interview_feedback`, `client_side`),
* odrzucenia z pipeline'u po wysłaniu CV (`candidate_stages`, powód + notatka),
* zastrzeżenia kandydatów po rozmowach (`interview_feedback`, `candidate_side`).

Pytania, które klient zadawał na rozmowach (bank `client_debrief`), idą do
bloku DOSŁOWNIE, bez modelu.

Zasady, które łatwo cofnąć:

* **AI to dodatek, nigdy bramka.** Awaria modelu zapisuje `status="failed"`
  z komunikatem; nic nie rzuca do wołającego tworzenie rekrutacji.
* **Bez nazwisk.** Imiona i nazwiska kandydatów z tych samych wierszy są
  wycinane z tekstu PRZED wysłaniem do modelu, notatki są przycinane, a prompt
  zabrania wymieniania osób. To obrona w głąb, nie gwarancja — dlatego blok
  widzi wyłącznie zespół (publiczna karta i strona kariery go nie czytają).
* **Płacimy tylko za zmianę.** `inputs_hash` (dane + wersja promptu + model)
  równy zapisanemu = zwracamy zapisany blok bez wywołania modelu.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.candidate import Candidate
from app.models.interview_feedback import (
    FeedbackSource,
    InterviewDecision,
    InterviewFeedback,
)
from app.models.job import Job
from app.models.pipeline_template import RejectionReason
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services.champion_client_context import debrief_questions

logger = logging.getLogger(__name__)

WINDOW_DAYS = 548
MIN_EVENTS = 3
MAX_EVENTS_PER_KIND = 40
NOTE_CAP = 300
TOO_LITTLE = "Za mało historii u tego klienta, żeby wyciągnąć wnioski."
FAILED = "Nie udało się podsumować historii klienta — spróbuj „Odśwież”."

# Etapy, na których kandydat był już u klienta — odrzucenie wcześniej to
# decyzja rekrutera, nie klienta.
_CLIENT_FACING = (
    PipelineStage.cv_sent,
    PipelineStage.client_interview,
    PipelineStage.acceptance,
    PipelineStage.negotiation,
)


def _cap(value: Any, limit: int = NOTE_CAP) -> str:
    return re.sub(r"\s+", " ", value).strip()[:limit] if isinstance(value, str) else ""


def scrub_names(text: str, names: set[str]) -> str:
    """Zamienia znane imiona/nazwiska kandydatów na „[kandydat]”."""
    if not text or not names:
        return text
    pattern = re.compile(
        r"(?<!\w)(?:"
        + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
        + r")(?!\w)",
        re.IGNORECASE,
    )
    return pattern.sub("[kandydat]", text)


async def collect_history(db: AsyncSession, client_id: int) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    client_jobs = select(Job.id).where(Job.client_id == client_id)

    hm_rows = (
        await db.execute(
            select(
                InterviewFeedback.candidate_id,
                InterviewFeedback.decision,
                InterviewFeedback.concerns,
                InterviewFeedback.feedback_summary,
                RejectionReason.name,
                Job.title,
            )
            .join(Job, Job.id == InterviewFeedback.job_id)
            .outerjoin(
                RejectionReason,
                RejectionReason.id == InterviewFeedback.rejection_reason_id,
            )
            .where(
                InterviewFeedback.job_id.in_(client_jobs),
                InterviewFeedback.feedback_source == FeedbackSource.client_side,
                InterviewFeedback.created_at >= since,
            )
            .order_by(InterviewFeedback.id.desc())
            .limit(MAX_EVENTS_PER_KIND)
        )
    ).all()

    earlier = aliased(CandidateStage)
    rejection_rows = (
        await db.execute(
            select(
                CandidateStage.candidate_id,
                RejectionReason.name,
                CandidateStage.rejection_note,
                Job.title,
            )
            .join(Job, Job.id == CandidateStage.job_id)
            .outerjoin(
                RejectionReason,
                RejectionReason.id == CandidateStage.rejection_reason_id,
            )
            .where(
                CandidateStage.job_id.in_(client_jobs),
                CandidateStage.stage == PipelineStage.rejected,
                CandidateStage.created_at >= since,
                exists().where(
                    and_(
                        earlier.candidate_id == CandidateStage.candidate_id,
                        earlier.job_id == CandidateStage.job_id,
                        earlier.stage.in_(_CLIENT_FACING),
                    )
                ),
            )
            .order_by(CandidateStage.id.desc())
            .limit(MAX_EVENTS_PER_KIND)
        )
    ).all()

    candidate_side_rows = (
        await db.execute(
            select(
                InterviewFeedback.candidate_id,
                InterviewFeedback.concerns,
                InterviewFeedback.acceptance_condition,
            )
            .where(
                InterviewFeedback.job_id.in_(client_jobs),
                InterviewFeedback.feedback_source == FeedbackSource.candidate_side,
                InterviewFeedback.created_at >= since,
            )
            .order_by(InterviewFeedback.id.desc())
            .limit(MAX_EVENTS_PER_KIND)
        )
    ).all()

    candidate_ids = {
        row[0]
        for rows in (hm_rows, rejection_rows, candidate_side_rows)
        for row in rows
    }
    names: set[str] = set()
    if candidate_ids:
        for first, last in (
            await db.execute(
                select(Candidate.name, Candidate.lastname).where(
                    Candidate.id.in_(candidate_ids)
                )
            )
        ).all():
            for part in (first, last):
                if (
                    isinstance(part, str)
                    and len(part.strip()) >= 3
                    and part.strip() != "?"
                ):
                    names.add(part.strip())

    def clean(value: Any) -> str:
        return scrub_names(_cap(value), names)

    hiring_manager = [
        {
            "role": _cap(title, 120),
            "decision": decision.value
            if isinstance(decision, InterviewDecision)
            else decision,
            "reason": _cap(reason, 100),
            "concerns": clean(concerns),
            "summary": clean(summary),
        }
        for _cid, decision, concerns, summary, reason, title in hm_rows
    ]
    rejections = [
        {"role": _cap(title, 120), "reason": _cap(reason, 100), "note": clean(note)}
        for _cid, reason, note, title in rejection_rows
    ]
    candidate_side = [
        {"concerns": clean(concerns), "condition": clean(condition)}
        for _cid, concerns, condition in candidate_side_rows
        if (concerns or condition)
    ]
    return {
        "hiring_manager": [
            h for h in hiring_manager if any(v for k, v in h.items() if k != "role")
        ],
        "rejections_after_cv": rejections,
        "candidate_concerns": candidate_side,
    }


def _event_count(history: dict[str, Any]) -> int:
    return sum(len(v) for v in history.values() if isinstance(v, list))


def _hash(history: dict[str, Any], questions: list[str], model: str) -> str:
    from app.services.llm_prompts import CHAMPION_CLIENT_HISTORY

    payload = json.dumps(
        {
            "h": history,
            "q": questions,
            "v": CHAMPION_CLIENT_HISTORY.version,
            "m": model,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _items(raw: Any) -> list[dict[str, Any]]:
    data = raw if isinstance(raw, dict) else {}
    out: list[dict[str, Any]] = []
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        text = _cap(item.get("text"), 600)
        if not text:
            continue
        topic = item.get("topic")
        count = item.get("basis_count")
        out.append(
            {
                "topic": topic
                if topic in ("rejections", "needs", "process", "pitch", "other")
                else "other",
                "text": text,
                "basis_count": count if isinstance(count, int) and count >= 0 else None,
            }
        )
        if len(out) >= 6:
            break
    return out


async def summarize_client_history(
    db: AsyncSession,
    *,
    client_id: int,
    role: str,
    stored: Optional[dict[str, Any]] = None,
    user_id: Optional[int] = None,
) -> dict[str, Any]:
    """Nowy blok `client_history` (słownik w kształcie `ClientHistorySummary`)."""
    from app.models.ai_feature import AIFeatureKey
    from app.services.ai_models import model_for
    from app.services.champion_draft_service import _call_claude_json
    from app.services.llm_prompts import CHAMPION_CLIENT_HISTORY
    from app.services.prompt_fencing import json_for_prompt

    model = model_for(AIFeatureKey.champion_draft)
    history = await collect_history(db, client_id)
    questions = await debrief_questions(db, client_id)
    inputs_hash = _hash(history, questions, model)
    now = datetime.now(timezone.utc).isoformat()
    stored = stored or {}
    if stored.get("status") == "ready" and stored.get("inputs_hash") == inputs_hash:
        return {**stored, "debrief_questions": questions}

    events = _event_count(history)
    base = {
        "debrief_questions": questions,
        "event_count": events,
        "generated_at": now,
        "inputs_hash": inputs_hash,
        "model": None,
    }
    if events < MIN_EVENTS:
        return {**base, "status": "ready", "items": [], "message": TOO_LITTLE}
    from app.services.ai_quota import ai_feature

    try:
        # Zużycie liczone tylko wtedy, gdy model naprawdę jest wołany.
        async with ai_feature(db, AIFeatureKey.champion_draft, user_id=user_id):
            await db.commit()
            raw = await _call_claude_json(
                prompt=CHAMPION_CLIENT_HISTORY.render(
                    role=_cap(role, 200) or "nie podano",
                    history=json_for_prompt(history),
                ),
                system_prompt=CHAMPION_CLIENT_HISTORY.system_prompt or "",
                model=model,
                max_tokens=2000,
            )
    except Exception:  # noqa: BLE001 — AI to dodatek, nigdy bramka
        logger.warning("champion_client_history: model call failed", exc_info=True)
        return {
            **base,
            "status": "failed",
            "items": list(stored.get("items") or []),
            "inputs_hash": None,
            "message": FAILED,
        }
    items = _items(raw)
    return {
        **base,
        "status": "ready",
        "items": items,
        "model": model,
        "message": None if items else TOO_LITTLE,
    }
