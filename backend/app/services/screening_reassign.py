"""Przepięcie: podpowiedzi odpowiedzi screeningu z poprzedniej rekrutacji.

Pipeline v4 (decyzja Artura 23.09.2026). Osoba przepięta z podobnej rekrutacji
(`RecruitmentProcess.reassign_from_job_id`, a dla procesów sprzed 0352 —
propozycja `source='reassign'`) odpowiadała już na pytania screeningowe
tamtej rekrutacji. Luna (`AIFeatureKey.screening_reassign_suggest`, F21)
dopasowuje te odpowiedzi i notatki rekruterów do pytań NOWEJ rekrutacji.

Zasady:

* AI to podpowiedź, nigdy bramka — każda awaria modelu, kwoty albo parsowania
  daje ``available: false`` z komunikatem, nigdy 5xx. Rekruter wypełnia
  arkusz ręcznie jak dotąd.
* Model nie może wymyślić faktu: podpowiedź bez cytatu obecnego DOSŁOWNIE
  w materiałach (po normalizacji białych znaków i wielkości liter) odpada,
  tak samo jak podpowiedź do pytania spoza listy tej rekrutacji.
* Kwoty: rola bez prawa do stawek (`user_can_edit_rates`) nie dostaje kwot ani
  w materiałach wysłanych do modelu, ani w podpowiedziach — maskujemy je
  PRZED wysłaniem, więc cytat z kwotą nie ma skąd się wziąć.
* Nic tu nie zapisuje się w bazie poza telemetrią AI (`ai_feature`).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import text

from app.api.recruitment_access import user_can_edit_rates
from app.models.ai_feature import AIFeatureKey
from app.models.job import Job
from app.models.job_proposal import JobProposal
from app.models.recruitment_pipeline import CandidateStage
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User
from app.services import champion_view
from app.services.ai_models import fallbacks_for, model_for
from app.services.ai_quota import ai_feature
from app.services.llm_prompts import SCREENING_REASSIGN_SUGGEST
from app.services.notes_insights_extractor import build_notes_blob
from app.services.prompt_fencing import fence, json_for_prompt, neutralize_tags

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.screening_reassign_suggest
# Najwyżej tyle notatek (z dwóch rekrutacji przepięcia) idzie do modelu.
NOTES_ROW_LIMIT = 20

MSG_NOT_REASSIGNED = (
    "Ta osoba nie przyszła z przepięcia — nie ma poprzedniej rekrutacji, "
    "z której Luna mogłaby podpowiedzieć odpowiedzi."
)
MSG_NO_QUESTIONS = "Ta rekrutacja nie ma pytań screeningowych w profilu Championa."
MSG_NO_MATERIAL = (
    "Z poprzedniej rekrutacji nie ma ani odpowiedzi ze screeningu, ani notatek "
    "— uzupełnij odpowiedzi ręcznie."
)
MSG_MODEL_FAILED = "Luna nie odpowiedziała — uzupełnij odpowiedzi ręcznie."
MSG_NOTHING_MATCHED = (
    "Luna nie znalazła w materiałach odpowiedzi na pytania tej rekrutacji — "
    "uzupełnij je ręcznie."
)

MONEY_MASK = "[kwota ukryta]"
# Kwoty z walutą albo stawką za jednostkę czasu („150 zł/h", „1 200 PLN",
# „25k", „150/h"). Zbyt szeroko jest bezpieczniej niż zbyt wąsko: rola bez
# prawa do stawek dostaje najwyżej zamaskowaną liczbę, która kwotą nie była.
_MONEY_RE = re.compile(
    r"\d[\d\s.,]*\s*(?:"
    r"(?:zł|zl|pln|złotych|eur|euro|€|usd|\$)(?:\s*/\s*(?:h|godz\.?|md|dzień|dzien|mc|mies\.?))?"
    r"|k\b(?:\s*(?:zł|zl|pln))?"
    r"|/\s*(?:h|godz\.?|md)\b"
    r")",
    re.IGNORECASE,
)

NOTES_CHAR_LIMIT = 6000
ANSWER_CHAR_LIMIT = 1500
SUGGESTION_TEXT_LIMIT = 1000
QUOTE_MIN_CHARS = 3
_CONFIDENCES = ("high", "medium", "low")
_SOURCE_KINDS = ("answer", "note")


@dataclass(frozen=True)
class ReassignContext:
    """Skąd osoba przyszła i co odpowiedziała w tamtym screeningu."""

    source_job_id: int
    source_job_title: str
    date: Optional[str]
    # [{"question": str, "answer": str}] — tylko niepuste, niepominięte.
    answers: list[dict[str, str]] = field(default_factory=list)

    def source_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.source_job_id,
            "job_title": self.source_job_title,
            "date": self.date,
        }


def mask_money(text: str) -> str:
    """Zamaskuj kwoty w tekście (rola bez prawa do stawek)."""
    return _MONEY_RE.sub(MONEY_MASK, text or "")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().casefold()


def _unavailable(message: str, ctx: Optional[ReassignContext] = None) -> dict:
    return {
        "available": False,
        "message": message,
        "source": ctx.source_dict() if ctx else None,
        "suggestions": [],
    }


async def _source_job_id(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> tuple[Optional[int], Optional[str]]:
    """Rekrutacja źródłowa przepięcia + data (ISO) z propozycji, jeśli jest."""
    process_source = await db.scalar(
        select(RecruitmentProcess.reassign_from_job_id)
        .where(
            RecruitmentProcess.candidate_id == candidate_id,
            RecruitmentProcess.job_id == job_id,
        )
        .order_by(RecruitmentProcess.id.desc())
        .limit(1)
    )
    evidence = await db.scalar(
        select(JobProposal.evidence).where(
            JobProposal.job_id == job_id,
            JobProposal.candidate_id == candidate_id,
            JobProposal.source == "reassign",
        )
    )
    reassign = (evidence or {}).get("reassign") if isinstance(evidence, dict) else None
    reassign = reassign if isinstance(reassign, dict) else {}
    proposal_source = reassign.get("job_id")
    sent_at = reassign.get("sent_at")
    source = process_source or (
        int(proposal_source) if isinstance(proposal_source, int) else None
    )
    # Data z propozycji opisuje TĘ rekrutację źródłową — przy innej jej nie bierzemy.
    date = sent_at if isinstance(sent_at, str) and source == proposal_source else None
    return source, date


def _answer_pairs(screening_answers: Any, questions: list) -> list[dict[str, str]]:
    if not isinstance(screening_answers, dict):
        return []
    q_by_id = {
        str(q.get("id") or "").strip(): str(q.get("question") or "").strip()
        for q in questions
        if isinstance(q, dict)
    }
    pairs: list[dict[str, str]] = []
    for item in screening_answers.get("answers") or []:
        if not isinstance(item, dict) or item.get("skipped"):
            continue
        answer = str(item.get("response") or "").strip()
        if not answer:
            continue
        question = q_by_id.get(str(item.get("question_id") or "").strip(), "")
        pairs.append({"question": question, "answer": answer[:ANSWER_CHAR_LIMIT]})
    return pairs


async def reassign_context(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> Optional[ReassignContext]:
    """Kontekst przepięcia dla pary (kandydat, rekrutacja) albo ``None``.

    Źródło: najnowszy proces pary (`reassign_from_job_id`), a gdy go nie ma —
    propozycja przepięcia (`evidence.reassign.job_id`). Odpowiedzi to
    najnowszy arkusz screeningu tej osoby w rekrutacji źródłowej.
    """
    source_id, date = await _source_job_id(db, candidate_id=candidate_id, job_id=job_id)
    if source_id is None or source_id == job_id:
        return None
    source_job = await db.get(Job, source_id)
    if source_job is None:
        return None
    stage_row = (
        await db.execute(
            select(CandidateStage.screening_answers)
            .where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == source_id,
                CandidateStage.screening_answers.is_not(None),
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )
    ).first()
    raw_answers = stage_row[0] if stage_row else None
    answers = _answer_pairs(
        raw_answers, champion_view.screening_questions(source_job.champion_profile)
    )
    if date is None and isinstance(raw_answers, dict):
        answered_at = raw_answers.get("answered_at")
        if isinstance(answered_at, str) and answered_at:
            date = answered_at[:10]
    return ReassignContext(
        source_job_id=source_id,
        source_job_title=source_job.title or f"Rekrutacja #{source_id}",
        date=date,
        answers=answers,
    )


def _call_model(system: str, prompt: str) -> str:
    """Jedno wywołanie modelu (w wątku). Osobna funkcja — testy ją podmieniają."""
    from app.services.claude_client import call_claude_text  # noqa: PLC0415

    return call_claude_text(
        model=model_for(FEATURE),
        fallback_models=fallbacks_for(FEATURE),
        max_tokens=2000,
        thinking={"type": "disabled"},
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )


def _parse_json(raw: str) -> Any:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def validate_suggestions(
    parsed: Any,
    *,
    question_ids: set[str],
    material: str,
    include_rates: bool,
) -> list[dict[str, str]]:
    """Odsiej podpowiedzi, którym nie da się ufać.

    Odpada: pytanie spoza tej rekrutacji, pusta odpowiedź, cytat krótszy niż
    3 znaki albo nieobecny w materiałach (halucynacja). Najwyżej jedna
    podpowiedź na pytanie — wygrywa pierwsza.
    """
    items = parsed.get("suggestions") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        return []
    haystack = _normalize(material)
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("question_id") or "").strip()
        if qid not in question_ids or qid in seen:
            continue
        text = str(item.get("text") or "").strip()
        quote = str(item.get("source_quote") or "").strip()
        if not text or len(quote) < QUOTE_MIN_CHARS:
            continue
        if _normalize(quote) not in haystack:
            continue
        if not include_rates:
            text = mask_money(text)
        kind = item.get("source_kind")
        confidence = item.get("confidence")
        out.append(
            {
                "question_id": qid,
                "text": text[:SUGGESTION_TEXT_LIMIT],
                "source_kind": kind if kind in _SOURCE_KINDS else "note",
                "source_quote": quote,
                "confidence": confidence if confidence in _CONFIDENCES else "low",
            }
        )
        seen.add(qid)
    return out


async def _job_scoped_notes(
    db: AsyncSession, *, candidate_id: int, job_ids: tuple[int, int]
) -> str:
    """Notatki kandydata WYŁĄCZNIE z tych dwóch rekrutacji (źródłowej
    i docelowej) — nie ze wszystkich jego procesów. Notatka z niezwiązanej
    rekrutacji (negocjacje, sprawy osobiste) nie może trafić do modelu ani
    wrócić w cytacie podpowiedzi."""

    rows = (
        await db.execute(
            text(
                "SELECT id, updated_at, "
                "(created_at AT TIME ZONE 'Europe/Warsaw')::date AS d, "
                "content FROM notes "
                "WHERE candidate_id = :c AND job_id = ANY(:jobs) "
                "ORDER BY created_at DESC LIMIT :lim"
            ),
            {"c": candidate_id, "jobs": list(job_ids), "lim": NOTES_ROW_LIMIT},
        )
    ).all()
    return build_notes_blob(list(rows))


async def suggest_answers(
    db: AsyncSession, *, stage: CandidateStage, user: User
) -> dict:
    """Podpowiedzi Luny dla arkusza screeningu karty ``stage``.

    Zwraca ``{"available", "message", "source", "suggestions"}``; nigdy nie
    rzuca z powodu modelu — awaria to ``available: false`` z komunikatem.
    """
    candidate_id = stage.candidate_id
    job_id = stage.job_id
    user_id = user.id
    include_rates = user_can_edit_rates(user)

    # Podpowiedź widzi każdy, kto pracuje nad rekrutacją DOCELOWĄ — także bez
    # dostępu do źródłowej (decyzja Artura 23.09.2026). Notatki i tak idą
    # wyłącznie z tych dwóch rekrutacji, a kwoty są maskowane rolom bez stawek.
    ctx = await reassign_context(db, candidate_id=candidate_id, job_id=job_id)
    if ctx is None:
        return _unavailable(MSG_NOT_REASSIGNED)

    target_job = await db.get(Job, job_id)
    questions = [
        {
            "id": str(q.get("id")).strip(),
            "question": str(q.get("question") or "").strip(),
        }
        for q in champion_view.screening_questions(
            target_job.champion_profile if target_job else None
        )
        if isinstance(q, dict) and str(q.get("id") or "").strip() and q.get("question")
    ]
    if not questions:
        return _unavailable(MSG_NO_QUESTIONS, ctx)

    notes = (
        await _job_scoped_notes(
            db, candidate_id=candidate_id, job_ids=(ctx.source_job_id, job_id)
        )
    )[:NOTES_CHAR_LIMIT]
    previous = "\n\n".join(
        f"P: {a['question']}\nO: {a['answer']}"
        if a["question"]
        else f"O: {a['answer']}"
        for a in ctx.answers
    )
    if not include_rates:
        notes = mask_money(notes)
        previous = mask_money(previous)
    if not previous.strip() and not notes.strip():
        return _unavailable(MSG_NO_MATERIAL, ctx)

    target_title = (target_job.title if target_job else None) or f"Rekrutacja #{job_id}"
    prompt = SCREENING_REASSIGN_SUGGEST.render(
        source_job_title=neutralize_tags(ctx.source_job_title),
        previous_screening=fence("previous_screening", previous or "(brak odpowiedzi)"),
        candidate_notes=fence("candidate_notes", notes or "(brak notatek)"),
        target_job_title=neutralize_tags(target_title),
        new_questions=fence("new_questions", json_for_prompt(questions)),
    )

    try:
        async with ai_feature(db, FEATURE, user_id=user_id):
            # Zwolnij połączenie z puli na czas wywołania modelu (kilka sekund).
            await db.commit()
            raw = await run_in_threadpool(
                _call_model, SCREENING_REASSIGN_SUGGEST.system_prompt or "", prompt
            )
        parsed = _parse_json(raw)
    except Exception as exc:  # noqa: BLE001 — AI to podpowiedź, nigdy bramka
        logger.warning(
            "screening_reassign: suggestion failed stage=%s job=%s (%s)",
            stage.id,
            job_id,
            type(exc).__name__,
        )
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            logger.warning("screening_reassign: rollback after failure failed")
        return _unavailable(MSG_MODEL_FAILED, ctx)

    suggestions = validate_suggestions(
        parsed,
        question_ids={q["id"] for q in questions},
        material=f"{previous}\n\n{notes}",
        include_rates=include_rates,
    )
    return {
        "available": True,
        "message": None if suggestions else MSG_NOTHING_MATCHED,
        "source": ctx.source_dict(),
        "suggestions": suggestions,
    }


def context_payload(ctx: Optional[ReassignContext]) -> dict:
    """Odpowiedź `GET …/reassign-context` — bez wywołania modelu."""
    if ctx is None:
        return {"available": False, "source": None, "previous_answers_count": 0}
    return {
        "available": True,
        "source": ctx.source_dict(),
        "previous_answers_count": len(ctx.answers),
    }
