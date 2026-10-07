"""Jeden formularz screeningu pary (kandydat, rekrutacja) — zapis i odczyt (0424).

Decyzje Artura D1–D10 z 07.10.2026 (makieta
https://claude.ai/artifact/TNGomEmwM6ehsbdPDSaaBi): arkusz pytań Championa,
ręczne pola karty rekomendacji i stawka kandydata to JEDEN formularz dla
Delivery Leada — z NEXUSA nic z niego nie idzie do klienta. Kontrakt API:
``docs/screening-form-contract.md``; czyste reguły (migawka, różnice, reguła
edycji): ``screening_form_rules.py``.

Zapis (``save``) to jedna transakcja, w tej kolejności:

1. formularz edytowalny (409 ``SCREENING_FORM_READ_ONLY``) i blokada 12 h
   (423 ``CANDIDATE_CLAIMED``);
2. blokada wiersza kandydata, potem wierszy etapów pary — kolejność jak
   ``candidate_rate_change.change_rate``;
3. wersja z formularza = najnowsza wersja pary, a odcisk stanu z formularza
   (``state_token``) = odcisk stanu pary pod blokadą (inaczej 409
   ``SCREENING_FORM_VERSION_CONFLICT``);
4. gdy nic się nie zmienia — koniec, bez notatki i bez wersji;
5. notatka z „Uzupełnij z notatki” jako zwykła notatka z rozmowy (HUMAN);
6. arkusz na NAJNOWSZY wiersz etapu (``humanize_origins`` → ``stamp_sheet``);
7. pola karty różne od wartości efektywnej (``save_manual``);
8. stawka przez ``change_rate(source="screening")`` — przed „Zweryfikowany”
   wpis bez powiadomień, potem jak każda zmiana stawki w procesie (0418);
   pole karty ``rate`` dostaje tekst tej stawki;
9. wersja ``baseline``/``external`` (stan sprzed zapisu, gdy różni się od
   ostatniej wersji — ślad starych tras i automatów), wersja zapisu
   i dziennik z samymi nazwami pól.

Maile (zmiana stawki) i oznaczenie wyników dopasowania idą po commicie,
w trasie (``api/screening_form.py``).

Zmiana zrobiona obok formularza (stara trasa, automat, Delivery Lead) po tym,
jak rekruter go otworzył, zmienia odcisk stanu (``screening_form_rules.
state_token``) — zapis dostaje 409, przeglądarka wczytuje nowy stan i zostawia
niezapisane zmiany w polach. Świadomy powrót do starej wartości przechodzi.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal, Mapping, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.note import Note, NoteType
from app.models.recommendation_card import RecommendationCard
from app.models.recruitment_pipeline import CandidateStage
from app.models.recruitment_process import RecruitmentProcess
from app.models.screening_form_version import ScreeningFormVersion
from app.models.user import User
from app.schemas.champion import (
    EXPERIENCE_ITEMS_MAX,
    SCREENING_ANSWERS_MAX,
    ExperienceCheck,
    ScreeningAnswerItem,
    ScreeningAnswers,
)
from app.services import candidate_claim, champion_view, note_kinds, screening_sheets
from app.services import candidate_rate_change as rate_change
from app.services import recommendation_cards as cards
from app.services import screening_form_rules as rules
from app.services.move_requirements import sheet_filled
from app.services.recommendation_card_assist import (
    NOTE_MAX_CHARS,
    note_text,
    phrase_language,
)
from app.services.screening_note_sync import humanize_origins

logger = logging.getLogger(__name__)

RATE_MAX = Decimal("1000000")
SOURCE_NAME_MAX = 200
VERSIONS_LIMIT = 200
NO_WRITE_MESSAGE = "Nie masz uprawnień do zapisu screeningu w tej rekrutacji."
VERSION_CONFLICT_MESSAGE = (
    "Ktoś zapisał ten formularz po tym, jak go otworzyłeś. Odśwież dane — "
    "Twoje niezapisane zmiany zostaną w polach."
)
STATE_CONFLICT_MESSAGE = (
    "Ktoś zmienił formularz w międzyczasie — wczytaliśmy nową wersję, Twoje "
    "zmiany zostały w polach."
)
NOT_APPLIED_MESSAGE = (
    "Zapis nie zmienił formularza — nic nie zapisaliśmy. Odśwież dane "
    "i spróbuj ponownie."
)
STATE_TOKEN_MAX = 128
UNDO_REFUSED_MESSAGE = (
    "Cofnąć można tylko swój ostatni zapis tego formularza — przywróć wersję "
    "z historii zmian."
)
_CURRENCY_RE = re.compile(r"[A-Za-z]{3}")
_CENT = Decimal("0.01")


def _invalid(message: str) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"code": "SCREENING_FORM_INVALID", "message": message},
    )


# ── Wejście zapisu ───────────────────────────────────────────────────────────


class SheetInput(BaseModel):
    """Arkusz z formularza — ``notes`` (stara „Notatka z arkusza”) przepisuje serwer."""

    answers: list[ScreeningAnswerItem] = Field(
        default_factory=list, max_length=SCREENING_ANSWERS_MAX
    )
    experience_checks: list[ExperienceCheck] = Field(
        default_factory=list, max_length=EXPERIENCE_ITEMS_MAX * 3
    )
    overall_fit: Literal["fit", "uncertain", "miss"] = "uncertain"
    internal_note: Optional[str] = Field(default=None, max_length=2000)
    clear_legacy_notes: bool = False


class CardOriginInput(BaseModel):
    origin: str = Field(max_length=20)
    keywords: Optional[str] = Field(default=None, max_length=cards.KEYWORDS_MAX)


class CardInput(BaseModel):
    fields: dict[str, Optional[str]] = Field(default_factory=dict)
    origins: Optional[dict[str, CardOriginInput]] = None


class RateInput(BaseModel):
    amount: Decimal
    unit: Literal["hourly", "daily", "monthly"] = "hourly"
    currency: str = Field(default="PLN", max_length=10)


class NoteImportInput(BaseModel):
    text: str = Field(min_length=1, max_length=NOTE_MAX_CHARS * 2)
    source_name: Optional[str] = Field(default=None, max_length=SOURCE_NAME_MAX)


class SaveInput(BaseModel):
    expected_version: int = Field(ge=0)
    # Odcisk stanu, z którego formularz wziął wartości (``ScreeningFormState``).
    state_token: str = Field(min_length=1, max_length=STATE_TOKEN_MAX)
    sheet: Optional[SheetInput] = None
    card: Optional[CardInput] = None
    rate: Optional[RateInput] = None
    note_import: Optional[NoteImportInput] = None


def validate_save(data: SaveInput, questions: Mapping[str, str]) -> None:
    """Odmowy 422 ``SCREENING_FORM_INVALID`` — przed jakimkolwiek zapisem."""
    if data.sheet is not None:
        for item in data.sheet.answers:
            if item.question_id.strip() not in questions:
                raise _invalid(
                    "Nie ma takiego pytania w Profilu Championa tej rekrutacji."
                )
    fields = data.card.fields if data.card is not None else {}
    for key, value in fields.items():
        if key == "rate":
            raise _invalid("Stawkę kandydata zapisuje pole stawki, nie pole karty.")
        if key not in rules.FORM_CARD_FIELDS:
            raise _invalid(f"Nieznane pole karty: {key[:100]}")
        if value is not None and len(value) > cards.max_length(key):
            raise _invalid(
                f"Pole „{cards.DISPLAY_LABELS[key]}” może mieć najwyżej "
                f"{cards.max_length(key)} znaków."
            )
    origins = (data.card.origins or {}) if data.card is not None else {}
    for key, origin in origins.items():
        if origin.origin not in cards.CARD_ORIGINS:
            raise _invalid("Nieznane pochodzenie pola karty.")
        if not (fields.get(key) or "").strip():
            raise _invalid("Pochodzenie dotyczy pola, którego nie ma w zapisie.")
        if origin.origin == "phrased" and key not in cards.PHRASABLE_FIELDS:
            raise _invalid(
                f"Pole „{cards.DISPLAY_LABELS.get(key, key)}” nie przyjmuje "
                "zdania z haseł."
            )
        if origin.origin in ("note_ai", "note_rule") and data.note_import is None:
            raise _invalid("Pole z notatki wymaga tekstu notatki, z której pochodzi.")
    if data.rate is not None:
        amount = data.rate.amount
        # Zakres PRZED zaokrągleniem: `quantize` kwoty typu 1e500 przekracza
        # precyzję kontekstu (InvalidOperation → 500 zamiast odmowy).
        if not amount.is_finite() or amount <= 0:
            raise _invalid("Stawka kandydata musi być większa od zera.")
        if amount > RATE_MAX:
            raise _invalid("Stawka kandydata jest za wysoka.")
        if amount.quantize(_CENT, ROUND_HALF_UP) <= 0:
            raise _invalid("Stawka kandydata musi być większa od zera.")
        if not _CURRENCY_RE.fullmatch(data.rate.currency.strip()):
            raise _invalid("Waluta stawki to trzy litery, np. PLN.")
    if data.note_import is not None:
        # Lustro dawnego `…/note/apply`: wyłączony odczyt notatki (404 na
        # trasach odczytu) nie zostawia notatek z jego pochodzeniem.
        if not settings.RECOMMENDATION_CARD_ASSIST_ENABLED:
            raise _invalid("Uzupełnianie formularza z notatki jest wyłączone.")
        if not note_text(data.note_import.text):
            raise _invalid("Notatka jest pusta.")


# ── Stan pary ────────────────────────────────────────────────────────────────


@dataclass
class PairState:
    """Czy formularz pary da się edytować i gdzie trafia zapis."""

    job: Job
    stages: list[CandidateStage]  # najnowszy pierwszy
    process: Optional[RecruitmentProcess]
    column: Optional[str]
    reason: Optional[str]

    @property
    def newest(self) -> Optional[CandidateStage]:
        return self.stages[0] if self.stages else None


async def _stage_rows(
    db: AsyncSession, *, candidate_id: int, job_id: int, lock: bool = False
) -> list[CandidateStage]:
    query = (
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return list((await db.scalars(query)).all())


async def pair_edit_state(
    db: AsyncSession,
    *,
    job: Job,
    candidate_id: int,
    stages: Optional[list[CandidateStage]] = None,
) -> PairState:
    """Reguła edycji pary: rekrutacja, proces (``load_process``), a para bez
    procesu — kolumna najnowszego wiersza etapu (``board_column_for``)."""
    rows = (
        stages
        if stages is not None
        else await _stage_rows(db, candidate_id=candidate_id, job_id=job.id)
    )
    process = await candidate_claim.load_process(
        db, candidate_id=candidate_id, job_id=job.id
    )
    column = await candidate_claim.stage_column(db, rows[0]) if rows else None
    reason = rules.read_only_reason(
        job_status=job.status,
        has_stage=bool(rows),
        process_status=process.status if process is not None else None,
        column=column,
    )
    return PairState(
        job=job, stages=rows, process=process, column=column, reason=reason
    )


def assert_pair_editable(state: PairState) -> None:
    if state.reason is None:
        return
    raise HTTPException(
        status_code=409,
        detail={
            "code": "SCREENING_FORM_READ_ONLY",
            "reason": state.reason,
            "message": rules.READ_ONLY_MESSAGES[state.reason],
        },
    )


async def _lock_pair(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> list[CandidateStage]:
    """Kandydat, potem wszystkie wiersze etapów pary — jak ``change_rate``."""
    locked = await db.scalar(
        select(Candidate.id).where(Candidate.id == candidate_id).with_for_update()
    )
    if locked is None:
        raise HTTPException(status_code=404, detail="Kandydat nie istnieje.")
    return await _stage_rows(db, candidate_id=candidate_id, job_id=job_id, lock=True)


@dataclass
class _Current:
    """Stan formularza pary: arkusz, karta i stawka kandydata."""

    sheet: Optional[dict[str, Any]]
    sheet_stage_id: Optional[int]
    card: Optional[RecommendationCard]
    fields: dict[str, Any]
    previous: dict[str, Any]
    started: Optional[datetime]
    rate: Optional[dict[str, Any]]

    def snapshot(self) -> dict[str, Any]:
        return rules.build_snapshot(
            sheet=self.sheet, card_fields=self.fields, rate=self.rate
        )


def _value(raw: object) -> Optional[str]:
    if raw is None:
        return None
    return str(getattr(raw, "value", raw))


async def _stage_rate(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> Optional[dict[str, Any]]:
    """Stawka kandydata pary — najnowsza niepusta (reguła ``pair_rates``)."""
    row = (
        await db.execute(
            select(
                CandidateStage.expected_rate_value,
                CandidateStage.expected_rate_unit,
                CandidateStage.expected_rate_currency,
                CandidateStage.moved_at,
            )
            .where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
                CandidateStage.expected_rate_value.isnot(None),
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return {
        "amount": row[0],
        "unit": _value(row[1]),
        "currency": (row[2] or "PLN").upper(),
        "at": row[3],
    }


async def _load_current(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    newest: Optional[CandidateStage],
    process: Optional[RecruitmentProcess],
    for_write: bool,
) -> _Current:
    sheet, source_id = (None, None)
    if newest is not None:
        sheet, source_id = await screening_sheets.latest_filled_sheet(
            db, newest, for_write=for_write
        )
    if not sheet_filled(sheet):
        sheet, source_id = None, None
    card = await cards.load_card(db, candidate_id=candidate_id, job_id=job_id)
    started = cards.attempt_started(process)
    fields, previous = cards.split_fields(
        card.fields_notes if card else {},
        card.fields_manual if card else {},
        attempt_started=started,
    )
    return _Current(
        sheet=sheet,
        sheet_stage_id=source_id,
        card=card,
        fields=fields,
        previous=previous,
        started=started,
        rate=await _stage_rate(db, candidate_id=candidate_id, job_id=job_id),
    )


@dataclass(frozen=True)
class _Head:
    version: int
    count: int
    last: Optional[ScreeningFormVersion]


def _pair_clause(candidate_id: int, job_id: int):  # noqa: ANN202
    return (
        ScreeningFormVersion.candidate_id == candidate_id,
        ScreeningFormVersion.job_id == job_id,
    )


async def _head(db: AsyncSession, *, candidate_id: int, job_id: int) -> _Head:
    last = await db.scalar(
        select(ScreeningFormVersion)
        .where(*_pair_clause(candidate_id, job_id))
        .order_by(ScreeningFormVersion.version_no.desc())
        .limit(1)
    )
    count = await db.scalar(
        select(func.count())
        .select_from(ScreeningFormVersion)
        .where(*_pair_clause(candidate_id, job_id))
    )
    return _Head(
        version=last.version_no if last is not None else 0,
        count=int(count or 0),
        last=last,
    )


async def _version_conflict(
    db: AsyncSession, head: _Head, *, message: str = VERSION_CONFLICT_MESSAGE
) -> HTTPException:
    """409 ``SCREENING_FORM_VERSION_CONFLICT``.

    Przy rozjeździe samego odcisku stanu (zmiana obok formularza, bez nowej
    wersji) autor ostatniej wersji nie jest autorem zmiany — ``saved_by_name``
    i ``saved_at`` są wtedy puste.
    """
    saved_by_name: Optional[str] = None
    saved_at: Optional[str] = None
    if head.last is not None and message == VERSION_CONFLICT_MESSAGE:
        saved_at = head.last.created_at.isoformat() if head.last.created_at else None
        if head.last.created_by is not None:
            author = await db.get(User, head.last.created_by)
            saved_by_name = author.name if author is not None else None
    return HTTPException(
        status_code=409,
        detail={
            "code": "SCREENING_FORM_VERSION_CONFLICT",
            "current_version": head.version,
            "saved_by_name": saved_by_name,
            "saved_at": saved_at,
            "message": message,
        },
    )


async def _visible_token(
    db: AsyncSession, *, current: _Current, newest: Optional[CandidateStage]
) -> str:
    """Odcisk stanu pary tak, jak liczy go ``GET`` (arkusz bez okna zapisu).

    ``current`` z zapisu czyta arkusz regułą okna zapisu (``for_write``) —
    odcisk porównujemy z tym, co widział rekruter, więc arkusz czytamy tu
    tak samo jak odczyt formularza.
    """
    sheet: Optional[dict[str, Any]] = None
    if newest is not None:
        sheet, _ = await screening_sheets.latest_filled_sheet(
            db, newest, for_write=False
        )
    if not sheet_filled(sheet):
        sheet = None
    return rules.state_token(
        rules.build_snapshot(sheet=sheet, card_fields=current.fields, rate=current.rate)
    )


async def _assert_state_token(
    db: AsyncSession,
    *,
    current: _Current,
    newest: Optional[CandidateStage],
    head: _Head,
    state_token: str,
) -> None:
    if await _visible_token(db, current=current, newest=newest) != state_token:
        raise await _version_conflict(db, head, message=STATE_CONFLICT_MESSAGE)


# ── Odczyt ───────────────────────────────────────────────────────────────────


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value else None


def _form_rate(amount: Any, unit: Optional[str], currency: Optional[str]) -> dict:
    return {
        "amount": float(amount),
        "unit": unit or "hourly",
        "currency": (currency or "PLN").upper(),
    }


def _rate_state(current: _Current) -> Optional[dict[str, Any]]:
    if current.rate is not None:
        rate = current.rate
        return {
            **_form_rate(rate["amount"], rate["unit"], rate["currency"]),
            "source": "stage",
            "at": _iso(rate["at"]),
        }
    card_rate = current.fields.get("rate")
    hourly = cards.card_rate_hourly(card_rate)
    if hourly is None:
        return None
    return {
        **_form_rate(hourly, "hourly", "PLN"),
        "source": "card",
        "at": (card_rate or {}).get("at"),
    }


async def _claim_state(
    db: AsyncSession, state: PairState, user: User
) -> Optional[dict[str, Any]]:
    """Blokada 12 h — tylko w „Nowych” i „Screeningu”, gdzie wiąże zespół."""
    if state.process is None or state.column not in candidate_claim.CLAIM_COLUMNS:
        return None
    claim = candidate_claim.claim_state(
        state.process, await candidate_claim.inactive_holders(db, [state.process])
    )
    if not claim.active(candidate_claim.utcnow()):
        return None
    holder = await db.get(User, claim.user_id)
    return {
        "user_id": claim.user_id,
        "user_name": holder.name if holder is not None else None,
        "until": claim.until.isoformat(),
        "mine": claim.user_id == user.id,
    }


async def load_state(
    db: AsyncSession,
    *,
    user: User,
    candidate: Candidate,
    job: Job,
    can_write: bool,
) -> dict[str, Any]:
    """Stan formularza pary — kształt ``ScreeningFormState`` z kontraktu."""
    from app.api.recommendation_cards import (  # noqa: PLC0415 — cykl api ↔ serwis
        attach_author_names,
        nationality_suggestion,
    )
    from app.api.recruitment_access import user_can_edit_rates  # noqa: PLC0415
    from app.services.candidate_rate_from import rate_summary  # noqa: PLC0415
    from app.services.screening_suggestions import (  # noqa: PLC0415
        suggestions_from_notes,
    )

    state = await pair_edit_state(db, job=job, candidate_id=candidate.id)
    newest = state.newest
    current = await _load_current(
        db,
        candidate_id=candidate.id,
        job_id=job.id,
        newest=newest,
        process=state.process,
        for_write=False,
    )
    head = await _head(db, candidate_id=candidate.id, job_id=job.id)
    questions = screening_sheets.question_texts(job.champion_profile)

    sheet = (
        screening_sheets.with_question_texts(current.sheet, questions)
        if current.sheet is not None
        else None
    )
    legacy_notes = str((current.sheet or {}).get("notes") or "").strip() or None

    fields = {
        key: dict(value) for key, value in current.fields.items() if key != "rate"
    }
    previous = {
        key: dict(value) for key, value in current.previous.items() if key != "rate"
    }
    await attach_author_names(db, fields)
    suggestions: dict[str, str] = {}
    if "nationality" not in current.fields:
        nationality = await nationality_suggestion(db, candidate, job.id)
        if nationality:
            suggestions["nationality"] = nationality
    present = dict(current.fields)
    if current.rate is not None and "rate" not in present:
        # Stawka stoi na wierszu etapu, nie na karcie — pole karty nie jest brakiem.
        present["rate"] = {"raw": "stawka z etapu"}

    sheet_answers = [
        item
        for item in (current.sheet or {}).get("answers") or []
        if isinstance(item, Mapping)
    ]
    note_items = cards.current_answers(
        current.card.note_answers if current.card else None,
        attempt_started=current.started,
    )
    merged = cards.attach_deal_breakers(
        cards.merge_questions(
            questions, sheet_answers, note_items["items"] if note_items else []
        ),
        champion_view.screening_questions(job.champion_profile),
        sheet_answers,
    )
    note_answers = [
        {
            "question_id": item["question_id"],
            "number": item["number"],
            "question": item["question"],
            "answer": item["answer"],
        }
        for item in merged
        if item.get("source") == "note" and item.get("question_id")
    ]

    can_edit_rate = user_can_edit_rates(user)
    card_hourly = cards.card_rate_hourly(current.fields.get("rate"))
    rate_from = rate_summary(candidate).get("rate_from_hourly")
    assist_enabled = bool(settings.RECOMMENDATION_CARD_ASSIST_ENABLED)
    editable = state.reason is None and can_write
    read_only_message = (
        rules.READ_ONLY_MESSAGES[state.reason]
        if state.reason is not None
        else None
        if can_write
        else NO_WRITE_MESSAGE
    )
    return {
        "candidate_id": candidate.id,
        "job_id": job.id,
        "version": head.version,
        "versions_count": head.count,
        "state_token": rules.state_token(current.snapshot()),
        "editable": editable,
        "read_only_reason": state.reason,
        "read_only_message": read_only_message,
        "stage_id": newest.id if newest is not None else None,
        "board_column": state.column,
        "process_state_version": (
            state.process.state_version if state.process is not None else 0
        ),
        "claim": await _claim_state(db, state, user),
        "champion_profile": champion_view.api_response(job.champion_profile),
        "sheet": sheet,
        "sheet_source_stage_id": current.sheet_stage_id,
        "legacy_notes": legacy_notes,
        "note_answers": note_answers,
        "card": {
            "fields": fields,
            "previous": previous,
            "suggestions": suggestions,
            "completeness": cards.completeness(present),
            "labels": cards.DISPLAY_LABELS,
            "editable_fields": list(rules.FORM_CARD_FIELDS),
        },
        "rate": _rate_state(current),
        "rate_hints": {
            "card": (
                _form_rate(card_hourly, "hourly", "PLN")
                if card_hourly is not None
                else None
            ),
            "rate_from": (
                _form_rate(rate_from, "hourly", "PLN")
                if rate_from is not None
                else None
            ),
        },
        "rate_change_notifies": state.column in rate_change.NOTIFY_COLUMNS,
        "can_edit_rate": can_edit_rate,
        "suggestions_from_notes": suggestions_from_notes(
            candidate, include_rate=can_edit_rate
        ),
        "assist_enabled": assist_enabled,
        "phrase_language": (await phrase_language(db, job) if assist_enabled else "pl"),
    }


async def list_versions(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> dict[str, Any]:
    """Historia formularza pary — od najnowszej wersji."""
    rows = (
        await db.scalars(
            select(ScreeningFormVersion)
            .where(*_pair_clause(candidate_id, job_id))
            .order_by(ScreeningFormVersion.version_no.desc())
            .limit(VERSIONS_LIMIT)
        )
    ).all()
    total = await db.scalar(
        select(func.count())
        .select_from(ScreeningFormVersion)
        .where(*_pair_clause(candidate_id, job_id))
    )
    author_ids = sorted({row.created_by for row in rows if row.created_by})
    names: dict[int, Optional[str]] = {}
    if author_ids:
        names = {
            row.id: row.name
            for row in (
                await db.execute(
                    select(User.id, User.name).where(User.id.in_(author_ids))
                )
            ).all()
        }
    return {
        "items": [
            {
                "version_no": row.version_no,
                "action": row.action,
                "source": row.source,
                "created_at": _iso(row.created_at),
                "created_by": row.created_by,
                "created_by_name": names.get(row.created_by)
                if row.created_by
                else None,
                "restored_from_version": row.restored_from_version,
                "note_id": row.note_id,
                "changes": list(row.changes or []),
            }
            for row in rows
        ],
        "total": int(total or 0),
    }


# ── Zapis ────────────────────────────────────────────────────────────────────


@dataclass
class SaveOutcome:
    saved_version: Optional[int] = None
    undo_to_version: Optional[int] = None
    changed: list[str] = field(default_factory=list)
    note_id: Optional[int] = None
    emails: list[Any] = field(default_factory=list)
    sheet_changed: bool = False
    rate_not_restored: bool = False
    # "managed_by_dl" (od „Zweryfikowany” stawką zarządza DL) albo
    # "not_in_version" (wersja nie miała stawki, a stawka jest — zostaje).
    rate_not_restored_reason: Optional[str] = None
    skipped_answers: list[str] = field(default_factory=list)


@dataclass
class _Target:
    """Stan, który ma zapisać aplikator (zapis formularza albo przywrócenie)."""

    sheet: Optional[ScreeningAnswers] = None
    card: dict[str, Optional[str]] = field(default_factory=dict)
    origins: dict[str, dict[str, Any]] = field(default_factory=dict)
    rate: Optional[dict[str, Any]] = None  # {amount: Decimal, unit, currency}
    # Przywracana wersja nie miała arkusza — zdejmij arkusz ze wszystkich
    # wierszy pary w oknie odczytu (pusty arkusz się nie zapisuje, więc inaczej
    # nie da się wrócić, a odczyt sięgnąłby po starszą kopię).
    clear_sheet: bool = False


def _target_sheet(data: SheetInput, previous: Optional[dict]) -> ScreeningAnswers:
    """Arkusz z formularza. ``notes`` zostaje z poprzedniego arkusza pary, chyba
    że rekruter przeniósł je do „Dlaczego ten kandydat” (``clear_legacy_notes``)."""
    answers: list[ScreeningAnswerItem] = []
    seen: set[str] = set()
    for item in data.answers:
        question_id = item.question_id.strip()
        if question_id in seen:
            continue
        seen.add(question_id)
        keywords = (item.keywords or "").strip() or None
        answers.append(
            ScreeningAnswerItem(
                question_id=question_id,
                response=item.response.strip(),
                deal_breaker_hit=item.deal_breaker_hit,
                origin=item.origin,
                keywords=keywords if item.origin in rules.KEYWORD_ORIGINS else None,
                skipped=item.skipped,
            )
        )
    notes = "" if data.clear_legacy_notes else str((previous or {}).get("notes") or "")
    return ScreeningAnswers(
        answers=answers,
        experience_checks=list(data.experience_checks),
        overall_fit=data.overall_fit,
        notes=notes,
        internal_note=(data.internal_note or "").strip() or None,
    )


def _rate_target(rate: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    if rate is None or rate.get("amount") is None:
        return None
    return {
        "amount": Decimal(str(rate["amount"])).quantize(_CENT, ROUND_HALF_UP),
        "unit": rate.get("unit") or "hourly",
        "currency": (str(rate.get("currency") or "PLN")).strip().upper(),
    }


def _same_rate(current: Optional[Mapping[str, Any]], target: Mapping[str, Any]) -> bool:
    if current is None:
        return False
    return rate_change.same_rate(
        current["amount"],
        current["unit"],
        current["currency"],
        target["amount"],
        target["unit"],
        target["currency"],
    )


async def _clear_pair_sheets(
    db: AsyncSession, *, newest: CandidateStage, stages: list[CandidateStage]
) -> None:
    """Zdejmij arkusz z każdego wiersza pary, z którego czyta formularz.

    Odczyt (``latest_filled_sheet``) sięga po najnowszy wypełniony arkusz
    pary z bieżącej próby — zdjęcie arkusza tylko z najnowszego wiersza
    pokazałoby po zapisie starszą kopię. Pętla zdejmuje kolejne źródła, aż
    oba okna (odczytu i zapisu) nie widzą żadnego arkusza; wiersze są już
    zablokowane (``_lock_pair``).
    """
    by_id = {row.id: row for row in stages}
    for for_write in (False, True):
        for _ in range(len(stages) + 1):
            sheet, source_id = await screening_sheets.latest_filled_sheet(
                db, newest, for_write=for_write
            )
            if not sheet_filled(sheet):
                break
            row = newest if source_id is None else by_id.get(source_id)
            if row is None:  # wiersz spoza blokady — nie zgadujemy
                break
            row.screening_answers = None
            await db.flush()


def _note_content(note_import: NoteImportInput) -> str:
    source = (note_import.source_name or "").strip()
    header = f"Notatka z rozmowy (plik: {source})" if source else "Notatka z rozmowy"
    return f"{header}\n\n{note_text(note_import.text)}"


def _version_row(
    *,
    candidate_id: int,
    job_id: int,
    state: PairState,
    number: int,
    action: str,
    snapshot: dict[str, Any],
    changes: list[rules.VersionChange],
    created_by: Optional[int],
    source: str = "form",
    note_id: Optional[int] = None,
    restored_from: Optional[int] = None,
) -> ScreeningFormVersion:
    process = state.process
    return ScreeningFormVersion(
        candidate_id=candidate_id,
        job_id=job_id,
        version_no=number,
        process_id=process.id if process is not None else None,
        stage_id=state.newest.id if state.newest is not None else None,
        note_id=note_id,
        created_by=created_by,
        attempt_no=process.attempt_no if process is not None else None,
        action=action,
        source=source,
        restored_from_version=restored_from,
        snapshot=snapshot,
        changes=[change.as_dict() for change in changes],
        # Jawnie, nie z bazy: odczyt domyślnej wartości po flushu w sesji
        # async to MissingGreenlet (lustro `change_rate`).
        created_at=datetime.now(timezone.utc),
    )


async def _apply(
    db: AsyncSession,
    *,
    user: User,
    candidate_id: int,
    job: Job,
    state: PairState,
    current: _Current,
    head: _Head,
    questions: Mapping[str, str],
    target: _Target,
    action: str,
    rate_reason: str,
    note_import: Optional[NoteImportInput] = None,
    restored_from: Optional[int] = None,
) -> SaveOutcome:
    """Wspólny aplikator zapisu i przywracania — patrz docstring modułu."""
    from app.api.recommendation_cards import after_card_save  # noqa: PLC0415
    from app.api.recruitment_access import user_can_edit_rates  # noqa: PLC0415

    pre = current.snapshot()

    sheet = target.sheet
    if sheet is not None and (
        not rules.sheet_has_content(sheet) or rules.sheets_equal(sheet, current.sheet)
    ):
        sheet = None

    clear_sheet = (
        target.clear_sheet
        and sheet is None
        and current.sheet is not None
        and state.newest is not None
    )

    card_changes: dict[str, Optional[str]] = {
        key: value
        for key, value in target.card.items()
        if rules.card_field_differs(current.fields, key, value)
    }

    rate_target = target.rate
    rate_changes = rate_target is not None and not _same_rate(current.rate, rate_target)
    if rate_changes and not user_can_edit_rates(user):
        raise HTTPException(
            status_code=403,
            detail="Nie możesz zmieniać stawki kandydata w tej rekrutacji.",
        )
    if rate_changes:
        rate_text = rate_change.format_rate(
            rate_target["amount"], rate_target["unit"], rate_target["currency"]
        )
        if rules.card_field_differs(current.fields, "rate", rate_text):
            card_changes["rate"] = rate_text

    outcome = SaveOutcome()
    if sheet is None and not clear_sheet and not card_changes and not rate_changes:
        return outcome

    now = datetime.now(timezone.utc)
    note: Optional[Note] = None
    if note_import is not None:
        # Zwykła notatka z rozmowy, NIE notatka-karta: projekcja kart (0413)
        # wpisałaby do karty także to, czego rekruter nie przyjął.
        note = Note(
            content=_note_content(note_import),
            note_type=NoteType.general,
            candidate_id=candidate_id,
            job_id=job.id,
            author_id=user.id,
            kind=note_kinds.HUMAN,
            # Pochodzenie trzyma rodzaj także po edycji treści (0421, Q3).
            external_source=note_kinds.CARD_ASSIST_SOURCE,
        )
        db.add(note)
        await db.flush()
        outcome.note_id = note.id

    newest = state.newest
    if sheet is not None and newest is not None:
        humanize_origins(sheet)
        screening_sheets.stamp_sheet(
            sheet,
            questions=questions,
            previous=current.sheet,
            user_id=user.id,
            now=now,
        )
        newest.screening_answers = sheet.model_dump(mode="json")
        # Statystyki zespołu liczą jeden screening na wiersz etapu — poprawka
        # arkusza po ruchu karty dalej nie jest nowym screeningiem.
        if current.sheet is None or state.column in candidate_claim.CLAIM_COLUMNS:
            db.add(
                Activity(
                    entity_type="candidate_stage",
                    entity_id=newest.id,
                    action="screening_answered",
                    user_id=user.id,
                    details={
                        "candidate_id": candidate_id,
                        "job_id": job.id,
                        "overall_fit": sheet.overall_fit,
                        "match_percent": sheet.match_percent(),
                        "source": "screening_form",
                    },
                )
            )
        await db.flush()
        outcome.sheet_changed = True
    elif clear_sheet and newest is not None:
        await _clear_pair_sheets(db, newest=newest, stages=state.stages)
        outcome.sheet_changed = True

    if card_changes:
        provenance: dict[str, dict[str, Any]] = {}
        for key, value in card_changes.items():
            origin = target.origins.get(key)
            if not origin or not (value or "").strip():
                continue
            entry: dict[str, Any] = {
                "origin": origin.get("origin"),
                "keywords": origin.get("keywords"),
            }
            if note is not None and origin.get("origin") in ("note_ai", "note_rule"):
                entry["note_id"] = note.id
            provenance[key] = entry
        card, changed = await cards.save_manual(
            db,
            candidate_id=candidate_id,
            job_id=job.id,
            changes=card_changes,
            user_id=user.id,
            now=now,
            attempt_started=current.started,
            provenance=provenance,
        )
        await after_card_save(
            db,
            card=card,
            changed=changed,
            user=user,
            source="screening_form",
            rate_change=False,
        )

    if rate_changes:
        result = await rate_change.change_rate(
            db,
            candidate_id=candidate_id,
            job_id=job.id,
            amount=rate_target["amount"],
            unit=rate_target["unit"],
            currency=rate_target["currency"],
            source="screening",
            reason=rate_reason,
            actor=user,
        )
        outcome.emails = list(result.emails)

    post = (
        await _load_current(
            db,
            candidate_id=candidate_id,
            job_id=job.id,
            newest=newest,
            process=state.process,
            for_write=True,
        )
    ).snapshot()
    order = list(questions)
    changes = rules.diff_snapshots(pre, post, questions=order)
    if not changes:
        # Coś zapisaliśmy (notatkę, arkusz, kartę, stawkę), a stan pary się nie
        # zmienił — cichy commit zostawiłby zapis bez wersji. Wyjątek cofa
        # transakcję (``get_db``).
        logger.error(
            "screening_form: zapis bez zmiany stanu pary kandydat=%s rekrutacja=%s "
            "(arkusz=%s karta=%s stawka=%s notatka=%s)",
            candidate_id,
            job.id,
            outcome.sheet_changed,
            bool(card_changes),
            rate_changes,
            note is not None,
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SCREENING_FORM_NOT_APPLIED",
                "message": NOT_APPLIED_MESSAGE,
            },
        )

    number = head.version
    if head.last is None:
        if rules.snapshot_has_content(pre):
            number += 1
            db.add(
                _version_row(
                    candidate_id=candidate_id,
                    job_id=job.id,
                    state=state,
                    number=number,
                    action="baseline",
                    snapshot=pre,
                    changes=rules.diff_snapshots(None, pre, questions=order),
                    created_by=None,
                )
            )
    elif not rules.snapshots_equal(head.last.snapshot, pre):
        number += 1
        db.add(
            _version_row(
                candidate_id=candidate_id,
                job_id=job.id,
                state=state,
                number=number,
                action="external",
                snapshot=pre,
                changes=rules.diff_snapshots(head.last.snapshot, pre, questions=order),
                created_by=None,
            )
        )
    outcome.undo_to_version = number or None
    number += 1
    source = "note_import" if note is not None else "form"
    db.add(
        _version_row(
            candidate_id=candidate_id,
            job_id=job.id,
            state=state,
            number=number,
            action=action,
            snapshot=post,
            changes=changes,
            created_by=user.id,
            source=source,
            note_id=note.id if note is not None else None,
            restored_from=restored_from,
        )
    )
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate_id,
            action="screening_form_saved",
            user_id=user.id,
            # Same nazwy pól — treść formularza (narodowość, stawka, red flags)
            # nie trafia do dziennika zdarzeń.
            details={
                "job_id": job.id,
                "version_no": number,
                "action": action,
                "source": source,
                "fields": rules.activity_fields(changes),
            },
        )
    )
    await db.flush()
    outcome.saved_version = number
    outcome.changed = [change.label for change in changes]
    return outcome


async def _prepare(
    db: AsyncSession,
    *,
    user: User,
    candidate: Candidate,
    job: Job,
    expected_version: int,
) -> tuple[PairState, _Head]:
    """Bramki i blokady wspólne dla zapisu i przywracania."""
    state = await pair_edit_state(db, job=job, candidate_id=candidate.id)
    assert_pair_editable(state)
    await candidate_claim.assert_can_act(db, process=state.process, user=user)
    stages = await _lock_pair(db, candidate_id=candidate.id, job_id=job.id)
    state = await pair_edit_state(db, job=job, candidate_id=candidate.id, stages=stages)
    assert_pair_editable(state)
    head = await _head(db, candidate_id=candidate.id, job_id=job.id)
    if expected_version != head.version:
        raise await _version_conflict(db, head)
    return state, head


async def save(
    db: AsyncSession,
    *,
    user: User,
    candidate: Candidate,
    job: Job,
    data: SaveInput,
) -> SaveOutcome:
    """Zapis formularza w jednej transakcji (bez commitu — robi go trasa)."""
    questions = screening_sheets.question_texts(job.champion_profile)
    validate_save(data, questions)
    state, head = await _prepare(
        db,
        user=user,
        candidate=candidate,
        job=job,
        expected_version=data.expected_version,
    )
    current = await _load_current(
        db,
        candidate_id=candidate.id,
        job_id=job.id,
        newest=state.newest,
        process=state.process,
        for_write=True,
    )
    await _assert_state_token(
        db,
        current=current,
        newest=state.newest,
        head=head,
        state_token=data.state_token,
    )
    origins = (data.card.origins or {}) if data.card is not None else {}
    target = _Target(
        sheet=(
            _target_sheet(data.sheet, current.sheet) if data.sheet is not None else None
        ),
        card=dict(data.card.fields) if data.card is not None else {},
        origins={key: value.model_dump() for key, value in origins.items()},
        rate=_rate_target(data.rate.model_dump() if data.rate is not None else None),
    )
    return await _apply(
        db,
        user=user,
        candidate_id=candidate.id,
        job=job,
        state=state,
        current=current,
        head=head,
        questions=questions,
        target=target,
        action="save",
        rate_reason="conversation",
        note_import=data.note_import,
    )


def _assert_undo_allowed(head: _Head, *, version_no: int, user: User) -> None:
    """„Cofnij” = wyłącznie własny OSTATNI zapis, do wersji tuż przed nim.

    Starsze wersje i cudze zapisy wracają przez „Przywróć” — z regułą stawki
    od „Zweryfikowany” (zmianą stawki zarządza wtedy Delivery Lead).
    """
    last = head.last
    if (
        last is None
        or version_no != head.version - 1
        or last.created_by is None
        or last.created_by != user.id
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SCREENING_FORM_UNDO_REFUSED",
                "message": UNDO_REFUSED_MESSAGE,
            },
        )


async def restore(
    db: AsyncSession,
    *,
    user: User,
    candidate: Candidate,
    job: Job,
    version_no: int,
    expected_version: int,
    state_token: str,
    mode: Literal["restore", "undo"],
) -> SaveOutcome:
    """Przywrócenie wersji jako NOWA wersja (``restore``/``undo``).

    Stawka wraca tylko przed „Zweryfikowany” — później zmianą stawki zarządza
    Delivery Lead (0418), więc ``restore`` jej nie cofa (``rate_not_restored``,
    powód ``managed_by_dl``). ``undo`` cofa wyłącznie WŁASNY ostatni zapis
    (``_assert_undo_allowed``) łącznie ze stawką, jako „poprawkę pomyłki”
    (``reason="typo"``) — poza kolumnami, w których podwyżka czeka na decyzję
    DL (``DECISION_COLUMNS``): tam idzie zwykłym powodem, więc zadanie dla DL
    powstaje jak przy każdej podwyżce. Wersja bez stawki nie zdejmuje stawki,
    która jest (``rate_not_restored``, powód ``not_in_version``). Wersja bez
    arkusza zdejmuje arkusz ze wszystkich wierszy pary w oknie odczytu
    (``_Target.clear_sheet``).
    """
    state, head = await _prepare(
        db,
        user=user,
        candidate=candidate,
        job=job,
        expected_version=expected_version,
    )
    if mode == "undo":
        _assert_undo_allowed(head, version_no=version_no, user=user)
    row = await db.scalar(
        select(ScreeningFormVersion).where(
            *_pair_clause(candidate.id, job.id),
            ScreeningFormVersion.version_no == version_no,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej wersji formularza.")
    questions = screening_sheets.question_texts(job.champion_profile)
    current = await _load_current(
        db,
        candidate_id=candidate.id,
        job_id=job.id,
        newest=state.newest,
        process=state.process,
        for_write=True,
    )
    await _assert_state_token(
        db,
        current=current,
        newest=state.newest,
        head=head,
        state_token=state_token,
    )
    plan = rules.restore_plan(
        row.snapshot or {}, current_sheet=current.sheet, questions=questions
    )
    try:
        sheet = ScreeningAnswers.model_validate(plan.sheet) if plan.sheet else None
    except ValidationError:
        raise HTTPException(
            status_code=409,
            detail="Ta wersja formularza ma nieprawidłowe dane — nie da się jej przywrócić.",
        ) from None
    target = _Target(
        sheet=sheet,
        card=dict(plan.card),
        origins=dict(plan.card_origins),
        rate=_rate_target(plan.rate),
        clear_sheet=plan.sheet is None,
    )
    reason = rules.rate_not_restored_reason(
        mode=mode,
        target_rate=target.rate,
        current_rate=current.rate,
        column=state.column,
        rate_differs=(
            target.rate is not None and not _same_rate(current.rate, target.rate)
        ),
    )
    if reason == rules.RATE_MANAGED_BY_DL:
        target.rate = None
    outcome = await _apply(
        db,
        user=user,
        candidate_id=candidate.id,
        job=job,
        state=state,
        current=current,
        head=head,
        questions=questions,
        target=target,
        action=mode,
        rate_reason=rules.restore_rate_reason(mode=mode, column=state.column),
        restored_from=version_no,
    )
    outcome.rate_not_restored = reason is not None
    outcome.rate_not_restored_reason = reason
    outcome.skipped_answers = list(plan.skipped_answers)
    return outcome


# ── Scalanie kandydatów ──────────────────────────────────────────────────────

# Wersje duplikatu przechodzą na ocalałego z numerami POWYŻEJ jego ostatniej
# wersji w tej samej rekrutacji — ogólny resolver unikalności skasowałby inaczej
# kolidujące wiersze, czyli historię. Podzapytania widzą stan sprzed UPDATE-u
# (migawka instrukcji), a nowe numery są rozłączne z numerami ocalałego.
_MERGE_VERSIONS_SQL = text(
    "UPDATE screening_form_versions AS dup SET "
    "candidate_id = :survivor, "
    "version_no = dup.version_no + COALESCE(("
    "SELECT max(kept.version_no) FROM screening_form_versions AS kept "
    "WHERE kept.candidate_id = :survivor AND kept.job_id = dup.job_id), 0), "
    "restored_from_version = dup.restored_from_version + COALESCE(("
    "SELECT max(kept.version_no) FROM screening_form_versions AS kept "
    "WHERE kept.candidate_id = :survivor AND kept.job_id = dup.job_id), 0) "
    "WHERE dup.candidate_id = :duplicate"
)


async def merge_versions(
    db: AsyncSession, *, survivor_id: int, duplicate_id: int
) -> int:
    """Scalanie kandydatów: historia formularza duplikatu zostaje w całości."""
    result = await db.execute(
        _MERGE_VERSIONS_SQL, {"survivor": survivor_id, "duplicate": duplicate_id}
    )
    return result.rowcount or 0
