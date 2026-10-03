"""Podpowiedzi w arkuszu screeningu z wcześniejszych rozmów kandydata.

Pipeline v4 (decyzja Artura 23.09.2026) dał je osobom przepiętym z podobnej
rekrutacji (`RecruitmentProcess.reassign_from_job_id`, a dla procesów sprzed
0352 — propozycja `source='reassign'`). Od 02.10.2026 dostaje je KAŻDA osoba,
która odpowiadała już na pytania screeningowe w innej rekrutacji: rekruter
nie pyta trzeci raz o to samo. Luna (`AIFeatureKey.screening_reassign_suggest`,
F21) dopasowuje wcześniejsze odpowiedzi do pytań NOWEJ rekrutacji.

Materiał:

* odpowiedzi z najwyżej ``MAX_EARLIER_CONVERSATIONS`` innych rozmów tej osoby
  (przy przepięciu rekrutacja źródłowa jest pierwsza); odpowiedzi pominięte
  i przeniesione wcześniej z podpowiedzi nie są materiałem,
* notatki rekruterów — WYŁĄCZNIE przy przepięciu i tylko z dwóch rekrutacji
  przepięcia. Osoba bez przepięcia dostaje same odpowiedzi.

Zasady:

* AI to podpowiedź, nigdy bramka — każda awaria modelu, kwoty albo parsowania
  daje ``available: false`` z komunikatem, nigdy 5xx. Rekruter wypełnia
  arkusz ręcznie jak dotąd.
* Model tylko WSKAZUJE, która wcześniejsza odpowiedź pasuje do pytania.
  Podpowiedź z odpowiedzi niesie tę odpowiedź DOSŁOWNIE, z rekrutacją,
  klientem i datą rozmowy. Cytat nieobecny w odpowiedziach ani w notatkach
  (także cytat z treści pytania) odpada, tak samo jak podpowiedź do pytania
  spoza listy tej rekrutacji.
* Kwoty: rola bez prawa do stawek (`user_can_edit_rates`) nie dostaje kwot
  w materiałach wysłanych do modelu, a podpowiedź, w której została
  zamaskowana kwota, odpada — „[kwota ukryta]” nie jest odpowiedzią.
* Nic tu nie zapisuje się w bazie poza telemetrią AI (`ai_feature`).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.recruitment_access import job_read_scope_clause, user_can_edit_rates
from app.models.ai_feature import AIFeatureKey
from app.models.job import Job
from app.models.job_proposal import JobProposal
from app.models.recruitment_pipeline import CandidateStage
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User
from app.services import note_kinds, screening_sheets
from app.services.ai_models import fallbacks_for, model_for
from app.services.ai_quota import ai_feature
from app.services.llm_prompts import SCREENING_REASSIGN_SUGGEST
from app.services.notes_insights_extractor import build_notes_blob
from app.services.prompt_fencing import fence, json_for_prompt, neutralize_tags

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.screening_reassign_suggest
# Najwyżej tyle notatek (z dwóch rekrutacji przepięcia) idzie do modelu.
NOTES_ROW_LIMIT = 20

# Najwyżej tyle innych rozmów tej osoby idzie do modelu (najnowsze pierwsze).
MAX_EARLIER_CONVERSATIONS = 3

MSG_NO_EARLIER = (
    "Ta osoba nie ma wcześniejszych rozmów screeningowych — nie ma z czego "
    "podpowiedzieć odpowiedzi."
)
MSG_NO_QUESTIONS = "Ta rekrutacja nie ma pytań screeningowych w profilu Championa."
MSG_NO_MATERIAL = (
    "Z wcześniejszych rozmów nie ma ani odpowiedzi ze screeningu, ani notatek "
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
# Ciąg cyfr i separatorów jest ograniczony: wzorzec bez limitu cofał się
# kwadratowo na długim ciągu cyfr bez waluty (1 s na 6 KB), a maskowanie
# biegnie na pętli zdarzeń. Realna kwota mieści się w limicie z zapasem.
_MONEY_RE = re.compile(
    r"\d[\d\s.,]{0,30}(?:"
    r"(?:zł|zl|pln|złotych|eur|euro|€|usd|\$)(?:\s*/\s*(?:h|godz\.?|md|dzień|dzien|mc|mies\.?))?"
    r"|k\b(?:\s*(?:zł|zl|pln))?"
    r"|/\s*(?:h|godz\.?|md)\b"
    r")",
    re.IGNORECASE,
)

NOTES_CHAR_LIMIT = 6000
ANSWER_CHAR_LIMIT = 1500
# Najwyżej tyle znaków wcześniejszych pytań i odpowiedzi razem idzie do
# modelu — trzy rozmowy z długimi arkuszami nie rozdymają promptu.
EARLIER_ANSWERS_CHAR_LIMIT = 12_000
QUESTION_CHAR_LIMIT = 500
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


@dataclass(frozen=True)
class EarlierAnswer:
    """Odpowiedź z wcześniejszej rozmowy — materiał i źródło podpowiedzi."""

    question: str
    answer: str
    job_id: int
    job_title: str
    client_name: Optional[str]
    date: Optional[str]

    def source_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_title": self.job_title,
            "client_name": self.client_name,
            "date": self.date,
        }


@dataclass(frozen=True)
class SuggestionContext:
    """Z czego Luna może podpowiadać w arkuszu pary (kandydat, rekrutacja)."""

    # „reassign” — osoba przepięta (dochodzą notatki dwóch rekrutacji);
    # „history” — wcześniejsze rozmowy w innych rekrutacjach.
    kind: str
    answers: list[EarlierAnswer]
    conversations: int
    reassign: Optional[ReassignContext] = None


def mask_money(text: str) -> str:
    """Zamaskuj kwoty w tekście (rola bez prawa do stawek)."""
    return _MONEY_RE.sub(MONEY_MASK, text or "")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().casefold()


def _unavailable(message: str, ctx: Optional[SuggestionContext] = None) -> dict:
    reassign = ctx.reassign if ctx else None
    return {
        "available": False,
        "message": message,
        "kind": ctx.kind if ctx else None,
        "source": reassign.source_dict() if reassign else None,
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


def _answer_pairs(
    screening_answers: Any, *, include_suggested: bool = True
) -> list[dict[str, str]]:
    """Pary pytanie–odpowiedź z arkusza (z uzupełnionym ``question_text``).

    Bez pustych i pominiętych. ``include_suggested=False`` zdejmuje też
    odpowiedzi przeniesione z podpowiedzi — to kopie, a ich źródłem jest
    rozmowa, w której kandydat naprawdę odpowiedział.
    """

    if not isinstance(screening_answers, dict):
        return []
    pairs: list[dict[str, str]] = []
    for item in screening_answers.get("answers") or []:
        if not isinstance(item, dict) or item.get("skipped"):
            continue
        if not include_suggested and item.get("origin") == "reassign_suggested":
            continue
        answer = str(item.get("response") or "").strip()
        if not answer:
            continue
        question = str(item.get("question_text") or "").strip()
        pairs.append(
            {
                "question": question[:QUESTION_CHAR_LIMIT],
                "answer": answer[:ANSWER_CHAR_LIMIT],
            }
        )
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
        screening_sheets.with_question_texts(
            raw_answers, screening_sheets.question_texts(source_job.champion_profile)
        )
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
    answers: Sequence[EarlierAnswer],
    notes: str,
    include_rates: bool,
) -> list[dict[str, Any]]:
    """Odsiej podpowiedzi, którym nie da się ufać.

    Odpada: pytanie spoza tej rekrutacji, cytat krótszy niż 3 znaki albo
    nieobecny w odpowiedziach ani w notatkach (halucynacja, także cytat
    z treści pytania) i podpowiedź, w której została zamaskowana kwota.
    Najwyżej jedna podpowiedź na pytanie — wygrywa pierwsza.

    Podpowiedź z wcześniejszej odpowiedzi niesie tę odpowiedź dosłownie
    i jej źródło; model wskazuje ją numerem (``source_ref``: „A1”), a bez
    numeru liczy się tylko cytat pasujący do DOKŁADNIE jednej odpowiedzi.
    """
    items = parsed.get("suggestions") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        return []
    by_ref = {f"A{n}": answer for n, answer in enumerate(answers, 1)}
    notes_haystack = _normalize(notes)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("question_id") or "").strip()
        if qid not in question_ids or qid in seen:
            continue
        quote = str(item.get("source_quote") or "").strip()
        if len(quote) < QUOTE_MIN_CHARS:
            continue
        needle = _normalize(quote)
        earlier = by_ref.get(str(item.get("source_ref") or "").strip().upper())
        if earlier is not None and needle not in _normalize(earlier.answer):
            earlier = None
        if earlier is None:
            matches = [a for a in answers if needle in _normalize(a.answer)]
            earlier = matches[0] if len(matches) == 1 else None
        if earlier is not None:
            text, kind = earlier.answer, "answer"
        elif needle in notes_haystack:
            text, kind = str(item.get("text") or "").strip(), "note"
            if not include_rates:
                text = mask_money(text)
        else:
            continue
        if not text or MONEY_MASK in text:
            continue
        confidence = item.get("confidence")
        out.append(
            {
                "question_id": qid,
                "text": text[:SUGGESTION_TEXT_LIMIT],
                "source_kind": kind,
                "source_quote": quote,
                "confidence": confidence if confidence in _CONFIDENCES else "low",
                "source": earlier.source_dict() if earlier else None,
                "source_question": (earlier.question or None) if earlier else None,
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
                f"AND {note_kinds.ai_readable_sql()} "
                "ORDER BY created_at DESC LIMIT :lim"
            ),
            {"c": candidate_id, "jobs": list(job_ids), "lim": NOTES_ROW_LIMIT},
        )
    ).all()
    return build_notes_blob(list(rows))


def _earlier_answers(conversations: Sequence[dict]) -> list[EarlierAnswer]:
    """Odpowiedzi z wcześniejszych rozmów w kolejności rozmów, do limitu znaków.

    Limit obejmuje pytania i odpowiedzi razem; po jego przekroczeniu kolejne
    odpowiedzi nie idą do modelu (rozmowy są już ułożone od najważniejszej).
    """
    answers: list[EarlierAnswer] = []
    budget = EARLIER_ANSWERS_CHAR_LIMIT
    for conversation in conversations:
        answered_at = conversation["answered_at"]
        for pair in _answer_pairs(conversation, include_suggested=False):
            budget -= len(pair["question"]) + len(pair["answer"])
            if budget < 0:
                return answers
            answers.append(
                EarlierAnswer(
                    question=pair["question"],
                    answer=pair["answer"],
                    job_id=conversation["job_id"],
                    job_title=conversation["job_title"]
                    or f"Rekrutacja #{conversation['job_id']}",
                    client_name=conversation["client_name"],
                    date=answered_at.date().isoformat() if answered_at else None,
                )
            )
    return answers


async def suggestion_context(
    db: AsyncSession, *, candidate_id: int, job_id: int, user: User
) -> Optional[SuggestionContext]:
    """Wcześniejsze rozmowy tej osoby, z których Luna może podpowiadać.

    ``None`` = osoba nie przyszła z przepięcia i nie ma arkusza w żadnej innej
    rekrutacji. Rozmowy z innych rekrutacji są zawężone zakresem odczytu
    wołającego (jak karta w profilu); rekrutację źródłową przepięcia widzi
    każdy, kto pracuje nad docelową (decyzja Artura 23.09.2026).
    """
    reassign = await reassign_context(db, candidate_id=candidate_id, job_id=job_id)
    scope = job_read_scope_clause(user, CandidateStage.job_id)
    if reassign is not None:
        scope = or_(CandidateStage.job_id == reassign.source_job_id, scope)
    conversations = await screening_sheets.candidate_conversations(
        db, candidate_id=candidate_id, job_scope=scope, exclude_job_id=job_id
    )
    if reassign is not None:
        # Rekrutacja źródłowa pierwsza — stamtąd osoba przyszła.
        conversations.sort(key=lambda c: c["job_id"] != reassign.source_job_id)
    conversations = conversations[:MAX_EARLIER_CONVERSATIONS]
    if reassign is None and not conversations:
        return None
    answers = _earlier_answers(conversations)
    return SuggestionContext(
        kind="reassign" if reassign is not None else "history",
        answers=answers,
        conversations=len(conversations),
        reassign=reassign,
    )


def _answers_block(answers: Sequence[EarlierAnswer]) -> str:
    """Odpowiedzi ponumerowane „[A1]…” — model wskazuje źródło numerem."""
    blocks = []
    for n, answer in enumerate(answers, 1):
        head = f"[A{n}] Rekrutacja: {answer.job_title}"
        if answer.date:
            head += f" · rozmowa {answer.date}"
        question = f"P: {answer.question}\n" if answer.question else ""
        blocks.append(f"{head}\n{question}O: {answer.answer}")
    return "\n\n".join(blocks)


async def suggest_answers(
    db: AsyncSession, *, stage: CandidateStage, user: User
) -> dict:
    """Podpowiedzi Luny dla arkusza screeningu karty ``stage``.

    Zwraca ``{"available", "message", "kind", "source", "suggestions"}``; nigdy
    nie rzuca z powodu modelu — awaria to ``available: false`` z komunikatem.
    """
    candidate_id = stage.candidate_id
    job_id = stage.job_id
    user_id = user.id
    include_rates = user_can_edit_rates(user)

    ctx = await suggestion_context(
        db, candidate_id=candidate_id, job_id=job_id, user=user
    )
    if ctx is None:
        return _unavailable(MSG_NO_EARLIER)

    target_job = await db.get(Job, job_id)
    questions = [
        {"id": question_id, "question": question}
        for question_id, question in screening_sheets.question_texts(
            target_job.champion_profile if target_job else None
        ).items()
    ]
    if not questions:
        return _unavailable(MSG_NO_QUESTIONS, ctx)

    notes = ""
    if ctx.reassign is not None:
        # Notatki idą wyłącznie przy przepięciu i tylko z dwóch rekrutacji
        # przepięcia; sama historia rozmów ich nie wciąga.
        notes = (
            await _job_scoped_notes(
                db,
                candidate_id=candidate_id,
                job_ids=(ctx.reassign.source_job_id, job_id),
            )
        )[:NOTES_CHAR_LIMIT]
    answers = ctx.answers
    if not include_rates:
        notes = mask_money(notes)
        answers = [
            EarlierAnswer(
                question=mask_money(a.question),
                answer=mask_money(a.answer),
                job_id=a.job_id,
                job_title=a.job_title,
                client_name=a.client_name,
                date=a.date,
            )
            for a in answers
        ]
    if not answers and not notes.strip():
        return _unavailable(MSG_NO_MATERIAL, ctx)

    target_title = (target_job.title if target_job else None) or f"Rekrutacja #{job_id}"
    prompt = SCREENING_REASSIGN_SUGGEST.render(
        previous_screening=fence(
            "previous_screening", _answers_block(answers) or "(brak odpowiedzi)"
        ),
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
        answers=answers,
        notes=notes,
        include_rates=include_rates,
    )
    return {
        "available": True,
        "message": None if suggestions else MSG_NOTHING_MATCHED,
        "kind": ctx.kind,
        "source": ctx.reassign.source_dict() if ctx.reassign else None,
        "suggestions": suggestions,
    }


def context_payload(ctx: Optional[SuggestionContext]) -> dict:
    """Odpowiedź `GET …/reassign-context` — bez wywołania modelu."""
    if ctx is None:
        return {
            "available": False,
            "kind": None,
            "source": None,
            "previous_answers_count": 0,
            "earlier_conversations": 0,
        }
    return {
        "available": True,
        "kind": ctx.kind,
        "source": ctx.reassign.source_dict() if ctx.reassign else None,
        "previous_answers_count": len(ctx.answers),
        "earlier_conversations": ctx.conversations,
    }
