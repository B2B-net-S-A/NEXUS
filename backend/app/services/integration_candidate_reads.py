"""Odczyty kandydatów dla API integracyjnego v1 (``api/integrations_v1/candidates``).

Zapytania i projekcje bez żądania i bez użytkownika — o tym, co widzi klucz,
decydują scope'y (``candidates:contact``, ``candidates:cv``) i poziom kwot
(``common.amount_level``), które trasa przekazuje tu jawnie.

Reguły, które łatwo cofnąć:

* Lista NIE woła ``list_candidates`` ekranu (wymaga żądania i osoby, a przy
  ``q`` robi wyszukiwanie semantyczne). Filtry, które ekran ma wspólne z
  wyszukiwarką (miasto, kategoria kompetencji, dostępność), biorą predykat
  z ``candidate_search_predicates`` — lokalna kopia to powrót do rozjazdów
  z 07.2026.
* Scalony duplikat i osoba usunięta (RODO) nie mają wiersza w ``candidates``
  (``candidate_merge`` i usuwanie kasują go SQL-em), więc lista ich nie widzi
  bez osobnego warunku. Kwarantanna tożsamości dotyczy ŹRÓDEŁ (plik, wskaźnik
  CV, notatka), nie osoby: plik, tekst CV i notatka uznane za cudze nie
  wychodzą przez API (fail-closed, jak generator CV i fakty dla AI).
* Narodowość z karty rekomendacji nie wychodzi nigdy (strażnik
  ``test_only_listed_modules_read_recommendation_cards``). Stawka kandydata to
  koszt — tylko przy ``show_costs``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, selectinload

from app.core.scheduling import business_today
from app.models.candidate import AvailabilityStatus, Candidate
from app.models.candidate_document import CandidateDocument
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.note import SYSTEM_NOTE_SOURCE, Note
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User
from app.schemas.candidate import EmploymentMarker
from app.services import candidate_claim, screening_sheets
from app.services import candidate_search_predicates as predicates
from app.services import recommendation_cards as cards
from app.services.candidate_added_date import added_to_base_of
from app.services.candidate_identity_quarantine import (
    source_is_eligible_clause,
    source_is_quarantined_clause,
)
from app.services.candidate_rate_from import rate_summary, this_job_rates
from app.services.client_identity import client_display_name_expression
from app.services.cv_enrichment import NON_CV_EXTRACTED_KEYS
from app.services.employment_marker import load_employment_markers
from app.services.integration_actor import VIA_PREFIX
from app.services.polish_ilike import polish_folded_ilike

#: Id w ``?ids=`` — tyle, ile jedna strona listy mieści bez kolejnego żądania.
MAX_IDS = 200
#: Słowa frazy ``q`` po imieniu i nazwisku; dalsze są pomijane.
MAX_NAME_TOKENS = 5
INT4_MAX = 2_147_483_647

#: Etapy końcowe — osoba jest w rekrutacji, ale proces się dla niej skończył.
_ENDED_STAGES = frozenset(
    {PipelineStage.rejected, PipelineStage.withdrawn, PipelineStage.hired}
)
#: Pola karty, które nigdy nie wychodzą przez API (narodowość — strażnik kart).
_CARD_NEVER = frozenset({"nationality"})
#: Pole karty z kwotą kosztu (stawka kandydata).
_CARD_COST_FIELDS = frozenset({"rate"})


# ── Lista ────────────────────────────────────────────────────────────────────


class InvalidIds(ValueError):
    """``?ids=`` spoza kształtu „lista liczb po przecinku, najwyżej 200”."""


def parse_ids(raw: Optional[str]) -> list[int]:
    """``"3, 1,3"`` → ``[1, 3]``. Pusta wartość = brak filtra (``[]``).

    Tylko cyfry ASCII: ``"１"`` (cyfra pełnej szerokości) przechodzi
    ``str.isdigit`` i ``int()``, a nie jest identyfikatorem z naszej bazy.
    """
    if raw is None:
        return []
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if len(parts) > MAX_IDS:
        raise InvalidIds(f"Najwyżej {MAX_IDS} identyfikatorów w ids.")
    out: set[int] = set()
    for part in parts:
        if not (part.isascii() and part.isdigit()):
            raise InvalidIds(f"Nieprawidłowy identyfikator w ids: {part[:20]!r}.")
        value = int(part)
        if value < 1 or value > INT4_MAX:
            raise InvalidIds(f"Identyfikator spoza zakresu w ids: {part[:20]!r}.")
        out.add(value)
    return sorted(out)


def looks_like_email(phrase: str) -> bool:
    return "@" in phrase


def name_tokens(phrase: str) -> list[str]:
    return phrase.split()[:MAX_NAME_TOKENS]


@dataclass(frozen=True)
class CandidateListFilters:
    """Filtry ``GET /candidates``. ``email`` ustawia trasa wyłącznie dla klucza
    z ``candidates:contact`` — bez niego e-mail nie może nawet potwierdzić,
    że osoba jest w bazie."""

    name: Optional[str] = None
    email: Optional[str] = None
    updated_since: Optional[datetime] = None
    ids: tuple[int, ...] = ()
    competence_category_id: Optional[int] = None
    availability: tuple[AvailabilityStatus, ...] = ()
    city: Optional[str] = None


def candidate_list_conditions(filters: CandidateListFilters) -> list[ColumnElement]:
    conditions: list[ColumnElement] = []
    if filters.email:
        conditions.append(func.lower(Candidate.email) == filters.email.strip().lower())
    if filters.name:
        conditions.extend(
            or_(
                polish_folded_ilike(Candidate.name, token),
                polish_folded_ilike(Candidate.lastname, token),
            )
            for token in name_tokens(filters.name)
        )
    if filters.updated_since is not None:
        conditions.append(Candidate.updated_at >= filters.updated_since)
    if filters.ids:
        conditions.append(Candidate.id.in_(list(filters.ids)))
    if filters.competence_category_id is not None:
        # Kategoria główna albo poboczna — ta sama reguła co filtr listy (v2).
        clause = predicates.competence_category_clause(
            [filters.competence_category_id], predicates.semantics_for("list", 2)
        )
        if clause is not None:
            conditions.append(clause)
    availability = predicates.availability_clause(list(filters.availability))
    if availability is not None:
        conditions.append(availability)
    if filters.city and filters.city.strip():
        conditions.extend(predicates.city_match_clauses([filters.city.strip()]))
    return conditions


_LIST_COLUMNS = (
    Candidate.id,
    Candidate.name,
    Candidate.lastname,
    Candidate.city,
    Candidate.country,
    Candidate.region,
    Candidate.competence_category_id,
    Candidate.status,
    Candidate.availability_status,
    Candidate.availability_date,
    Candidate.created_at,
    Candidate.source_created_at,
    Candidate.external_source,
    Candidate.updated_at,
)


async def list_candidates_page(
    db: AsyncSession,
    filters: CandidateListFilters,
    *,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    """Strona listy (bez ``raw_cv_text`` i JSONB-ów — same kolumny listy)."""
    conditions = candidate_list_conditions(filters)
    total = (
        await db.scalar(select(func.count()).select_from(Candidate).where(*conditions))
    ) or 0
    rows = (
        await db.execute(
            select(*_LIST_COLUMNS)
            .where(*conditions)
            .order_by(Candidate.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return [list_item(row) for row in rows], int(total)


def list_item(row: Any) -> dict[str, Any]:
    added = added_to_base_of(row)
    return {
        "id": row.id,
        "first_name": row.name,
        "last_name": row.lastname,
        "city": row.city,
        "country": row.country,
        "region": row.region,
        "competence_category_id": row.competence_category_id,
        "status": enum_value(row.status),
        "availability_status": enum_value(row.availability_status),
        "availability_date": row.availability_date,
        "added_to_base_at": added.at,
        "added_to_base_exact": added.exact,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


# ── Profil ───────────────────────────────────────────────────────────────────


async def load_candidate(db: AsyncSession, candidate_id: int) -> Optional[Candidate]:
    """Kandydat z kategorią kompetencji, bez tekstu i bajtów CV."""
    return await db.scalar(
        select(Candidate)
        .options(
            selectinload(Candidate.competence_category_ref),
            defer(Candidate.raw_cv_text),
            defer(Candidate.cv_file_content),
        )
        .where(Candidate.id == candidate_id)
    )


async def candidate_exists(db: AsyncSession, candidate_id: int) -> bool:
    return bool(
        await db.scalar(select(Candidate.id).where(Candidate.id == candidate_id))
    )


def skills_out(raw: Any) -> list[dict[str, Any]]:
    """Umiejętności jako ``[{name, level, years}]`` — JSONB bywa listą napisów
    albo słowników (import, odczyt CV, ręczna edycja)."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append({"name": item.strip(), "level": None, "years": None})
        elif isinstance(item, Mapping):
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            level = item.get("level")
            years = item.get("years")
            out.append(
                {
                    "name": name,
                    "level": str(level) if isinstance(level, str) and level else None,
                    "years": years
                    if isinstance(years, (int, float)) and not isinstance(years, bool)
                    else None,
                }
            )
    return out


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def work_preferences(candidate: Any) -> dict[str, Any]:
    """Tryb pracy i forma współpracy. Z ``preferences`` tylko tryby i formy
    umów — reszta klucza (wykluczeni klienci, wycofane stawki miesięczne)
    jest wewnętrzna."""
    prefs = candidate.preferences if isinstance(candidate.preferences, dict) else {}
    return {
        "work_modes": _str_list(prefs.get("remote_modes")),
        "contract_types": _str_list(prefs.get("contract_types")),
        "max_onsite_days_per_week": candidate.max_onsite_days_per_week,
        "b2b_willingness": candidate.b2b_willingness,
        "work_time_preference": candidate.work_time_preference,
    }


def contact_fields(candidate: Any, *, visible: bool) -> dict[str, Any]:
    """E-mail, telefon, LinkedIn i dane firmy — ``None`` bez ``candidates:contact``."""
    keys = ("email", "phone", "linkedin", "nip", "regon", "legal_name")
    return {
        "contact_redacted": not visible,
        **{key: getattr(candidate, key) if visible else None for key in keys},
    }


def profile_rates(candidate: Any, *, show_costs: bool) -> dict[str, Any]:
    """Stawka kandydata (koszt) — wyłącznie przez ``rate_summary``.

    „Stawka od” (najniższa z 18 miesięcy; przed przeliczeniem stawka profilu
    w PLN) i najnowsza obserwacja. Pola ``expected_rate_hourly`` nie czytamy
    wprost: strażnik ``test_rate_from_readers_guard`` — filtry, AI i budżety
    porównują z „Stawką od”, a integracja ma widzieć tę samą liczbę.
    """
    if not show_costs:
        return {
            "costs_redacted": True,
            "rate_from_hourly": None,
            "rate_from_at": None,
            "rate_latest_hourly": None,
            "rate_latest_at": None,
        }
    summary = rate_summary(candidate)
    return {
        "costs_redacted": False,
        "rate_from_hourly": summary["rate_from_hourly"],
        "rate_from_at": summary["rate_from_at"],
        "rate_latest_hourly": summary["rate_latest_hourly"],
        "rate_latest_at": summary["rate_latest_at"],
    }


async def active_recruitments(
    db: AsyncSession, candidate_id: int
) -> list[dict[str, Any]]:
    """Rekrutacje osoby — najnowszy etap pary, bez rekrutacji zamkniętych.

    Ta sama reguła co kolumna „Rekrutacje” listy kandydatów (etapy końcowe
    zostają, ``in_progress`` je odróżnia) i ten sam remis ``(moved_at, id)``
    co ``pipeline_latest``.
    """
    latest = (
        select(
            CandidateStage.job_id,
            CandidateStage.stage,
            CandidateStage.moved_at,
        )
        .where(CandidateStage.candidate_id == candidate_id)
        .distinct(CandidateStage.job_id)
        .order_by(
            CandidateStage.job_id,
            CandidateStage.moved_at.desc(),
            CandidateStage.id.desc(),
        )
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                latest.c.job_id,
                latest.c.stage,
                latest.c.moved_at,
                Job.title,
                Job.client_id,
                client_display_name_expression().label("client_name"),
            )
            .select_from(latest)
            .join(Job, Job.id == latest.c.job_id)
            .outerjoin(Client, Client.id == Job.client_id)
            .where(Job.status != JobStatus.closed)
            .order_by(latest.c.moved_at.desc(), latest.c.job_id)
        )
    ).all()
    return [
        {
            "job_id": row.job_id,
            "job_title": row.title,
            "client_id": row.client_id,
            "client_name": row.client_name,
            "stage": enum_value(row.stage),
            "in_progress": row.stage not in _ENDED_STAGES,
            "moved_at": row.moved_at,
        }
        for row in rows
    ]


async def employment_marker(
    db: AsyncSession, candidate_id: int
) -> Optional[EmploymentMarker]:
    """Znacznik „Pracuje u nas” — ta sama reguła co każdy ekran."""
    markers = await load_employment_markers(db, [candidate_id], today=business_today())
    return markers.get(candidate_id)


def added_to_base(candidate: Any) -> dict[str, Any]:
    added = added_to_base_of(candidate)
    return {"added_to_base_at": added.at, "added_to_base_exact": added.exact}


# ── Pliki i tekst CV ─────────────────────────────────────────────────────────


def eligible_document_conditions(candidate_id: int) -> tuple[ColumnElement, ...]:
    """Plik osoby, który nie został usunięty z profilu ani uznany za cudzy."""
    return (
        CandidateDocument.candidate_id == candidate_id,
        CandidateDocument.source_deleted_at.is_(None),
        source_is_eligible_clause(
            candidate_id_column=CandidateDocument.candidate_id,
            source_id_column=CandidateDocument.id,
            source_kind="document",
        ),
    )


async def list_documents(
    db: AsyncSession, candidate_id: int
) -> list[CandidateDocument]:
    """Kolejność jak na ekranie: główne CV, potem najnowsze."""
    return list(
        (
            await db.scalars(
                select(CandidateDocument)
                .where(*eligible_document_conditions(candidate_id))
                .order_by(
                    CandidateDocument.is_primary.desc(),
                    func.coalesce(
                        CandidateDocument.uploaded_at, CandidateDocument.created_at
                    ).desc(),
                    CandidateDocument.id.desc(),
                )
            )
        ).all()
    )


async def load_document(
    db: AsyncSession, candidate_id: int, document_id: int
) -> Optional[CandidateDocument]:
    return await db.scalar(
        select(CandidateDocument).where(
            CandidateDocument.id == document_id,
            *eligible_document_conditions(candidate_id),
        )
    )


def public_cv_extracted(data: Any) -> Optional[dict[str, Any]]:
    """Odczyt CV bez kluczy spoza CV.

    Odpadają klucze techniczne (``_…``: fakty z notatek ze stawką kandydata,
    znaczniki blokad, pochodzenie pól), pola własne Traffita (``traffit_…``
    — treść nieznana, bywają kwoty) i pochodzenie importu.
    """
    if not isinstance(data, dict):
        return None
    return {
        key: value
        for key, value in data.items()
        if not str(key).startswith(("_", "traffit_"))
        and key not in NON_CV_EXTRACTED_KEYS
    }


def projected_document_id(data: Any) -> Optional[int]:
    """Plik, z którego pochodzi bieżący odczyt CV (``cv_highlights``)."""
    if not isinstance(data, dict):
        return None
    highlights = data.get("cv_highlights")
    if not isinstance(highlights, dict):
        return None
    value = highlights.get("source_document_id")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


async def cv_text_quarantined(
    db: AsyncSession, candidate_id: int, extracted: Any
) -> bool:
    """Czy tekst i odczyt CV mogą pochodzić z CV innej osoby.

    Odczyt z pliku: liczy się kwarantanna tego pliku. Bez pliku-źródła tekst
    pochodzi ze wskaźnika CV na kandydacie (``legacy_cv``). Kwarantanna sama
    czyści tekst, którego źródło jest pewne — tu zamykamy przypadek, gdy
    pochodzenia nie da się ustalić (fail-closed).
    """
    document_id = projected_document_id(extracted)
    if document_id is not None:
        clause = source_is_quarantined_clause(
            candidate_id_column=candidate_id,
            source_id_column=document_id,
            source_kind="document",
        )
    else:
        clause = source_is_quarantined_clause(
            candidate_id_column=candidate_id,
            source_id_column=candidate_id,
            source_kind="legacy_cv",
        )
    return bool(await db.scalar(select(clause)))


async def load_cv_text(db: AsyncSession, candidate_id: int) -> Optional[Any]:
    """``(raw_cv_text, cv_extracted_data, cv_language, cv_parsed_at)`` albo ``None``."""
    return (
        await db.execute(
            select(
                Candidate.raw_cv_text,
                Candidate.cv_extracted_data,
                Candidate.cv_language,
                Candidate.cv_parsed_at,
            ).where(Candidate.id == candidate_id)
        )
    ).first()


# ── Notatki ──────────────────────────────────────────────────────────────────


def eligible_note_conditions() -> tuple[ColumnElement, ...]:
    """Notatka nieusunięta u źródła i nie uznana za notatkę o innej osobie —
    ta sama reguła co fakty z notatek dla AI."""
    return (
        Note.source_deleted_at.is_(None),
        source_is_eligible_clause(
            candidate_id_column=Note.candidate_id,
            source_id_column=Note.id,
            source_kind="note",
        ),
    )


def note_author(
    author_name: Optional[str],
    *,
    source_ref: Optional[str],
    external_source: Optional[str],
) -> tuple[Optional[str], str]:
    """``(podpis, rodzaj autora)``: ``user`` | ``integration`` | ``system`` | ``none``.

    Notatka zapisana kluczem API nie ma osoby (``author_id`` NULL); podpis
    „Integracja: <konto>” bierzemy ze stempla ``source_ref``
    (``integration:<slug>``).
    """
    if author_name:
        return author_name, "user"
    if source_ref and source_ref.startswith(VIA_PREFIX):
        slug = source_ref[len(VIA_PREFIX) :].strip()
        return (f"Integracja: {slug}" if slug else "Integracja"), "integration"
    if external_source == SYSTEM_NOTE_SOURCE:
        return None, "system"
    return None, "none"


# ── Screening i karta rekomendacji ───────────────────────────────────────────


async def latest_pair_stage(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> Optional[CandidateStage]:
    """Bieżący wiersz pary (karta na Tablicy) — remis ``(moved_at, id)``."""
    return await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )


def _moment(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _text(value: Any) -> Optional[str]:
    return value if isinstance(value, str) else None


def screening_sheet_out(
    sheet: Any, *, user_names: Mapping[int, str]
) -> Optional[dict[str, Any]]:
    """Arkusz screeningu w stałym kształcie v1 (surowy JSONB bywa sprzed 09.2026).

    Bez ``keywords`` (hasła rekrutera, z których powstało zdanie) — to zapis
    roboczy, nie odpowiedź kandydata.
    """
    if not isinstance(sheet, Mapping) or not sheet:
        return None
    answers = [
        {
            "question_id": str(item.get("question_id") or ""),
            "question_text": _text(item.get("question_text")),
            "response": _text(item.get("response")) or "",
            "deal_breaker_hit": bool(item.get("deal_breaker_hit")),
            "skipped": bool(item.get("skipped")),
            "origin": _text(item.get("origin")),
        }
        for item in sheet.get("answers") or []
        if isinstance(item, Mapping)
    ]
    checks = [
        {
            "kind": _text(item.get("kind")),
            "name": _text(item.get("name")) or "",
            "status": _text(item.get("status")),
            "note": _text(item.get("note")) or "",
        }
        for item in sheet.get("experience_checks") or []
        if isinstance(item, Mapping)
    ]
    answered_by = sheet.get("answered_by")
    return {
        "answers": answers,
        "experience_checks": checks,
        "overall_fit": _text(sheet.get("overall_fit")),
        "notes": _text(sheet.get("notes")),
        "internal_note": _text(sheet.get("internal_note")),
        "answered_at": _moment(sheet.get("answered_at")),
        "answered_by_name": user_names.get(answered_by)
        if isinstance(answered_by, int)
        else None,
    }


async def user_names(db: AsyncSession, ids: Sequence[Any]) -> dict[int, str]:
    wanted = {i for i in ids if isinstance(i, int) and not isinstance(i, bool)}
    if not wanted:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(wanted)))
    return {row.id: row.name for row in rows}


async def screening_sheet(
    db: AsyncSession, stage: CandidateStage, job: Job
) -> Optional[dict[str, Any]]:
    """Arkusz pary jak na ekranie (``GET /pipeline/stages/{id}/screening``):
    arkusz etapu albo najnowszy wypełniony z bieżącej próby, z tekstem pytań
    uzupełnionym z Profilu Championa."""
    answers, _source_stage_id = await screening_sheets.latest_filled_sheet(db, stage)
    answers = screening_sheets.with_question_texts(
        answers, screening_sheets.question_texts(job.champion_profile)
    )
    names = await user_names(
        db, [answers.get("answered_by")] if isinstance(answers, Mapping) else []
    )
    return screening_sheet_out(answers, user_names=names)


def card_fields(
    current: Mapping[str, Any], *, show_costs: bool
) -> list[dict[str, Any]]:
    """Pola bieżącej próby karty: bez narodowości, stawka tylko przy kosztach.

    Bez ``by`` (id konta autora) — podpis pola to źródło (notatka / NEXUS)
    i data.
    """
    out: list[dict[str, Any]] = []
    for key in sorted(current, key=_card_order):
        if key in _CARD_NEVER or (key in _CARD_COST_FIELDS and not show_costs):
            continue
        value = current[key]
        if not isinstance(value, Mapping):
            continue
        out.append(
            {
                "key": key,
                "label": cards.DISPLAY_LABELS.get(key, key),
                "text": str(value.get("raw") or ""),
                "source": _text(value.get("source")),
                "at": _moment(value.get("at")),
            }
        )
    return out


def _card_order(key: str) -> tuple[int, str]:
    order = cards.EDITABLE_FIELDS
    return (order.index(key) if key in order else len(order), key)


async def recommendation_card(
    db: AsyncSession, *, candidate_id: int, job_id: int, show_costs: bool
) -> Optional[dict[str, Any]]:
    """Karta rekomendacji pary — bieżąca próba procesu, jak ``GET
    /recommendation-cards`` ekranu (bez podpowiedzi z poprzedniej próby)."""
    card = await cards.load_card(db, candidate_id=candidate_id, job_id=job_id)
    if card is None:
        return None
    process = await candidate_claim.load_process(
        db, candidate_id=candidate_id, job_id=job_id
    )
    current, _previous = cards.split_fields(
        card.fields_notes or {},
        card.fields_manual or {},
        attempt_started=cards.attempt_started(process),
    )
    stage_rate = bool(await cards.stage_rate_pairs(db, [(candidate_id, job_id)]))
    state = cards.completeness(cards.with_stage_rate(current, stage_rate))
    return {
        "fields": card_fields(current, show_costs=show_costs),
        "completeness": {
            "status": state["status"],
            "filled": state["filled"],
            "total": state["total"],
            "missing": list(state["missing"]),
        },
        "updated_at": card.updated_at,
    }


async def pair_candidate_rate(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> Optional[dict[str, Any]]:
    """Stawka kandydata podana w TEJ rekrutacji (karta albo okno
    „Zweryfikowany”) — ``{amount, raw, at, source}``, ta sama liczba co
    „W tej rekrutacji” obok „Stawki od” na ekranie."""
    return (await this_job_rates(db, job_id, [candidate_id])).get(candidate_id)


# ── Wspólne ──────────────────────────────────────────────────────────────────


def enum_value(value: Any) -> Any:
    return getattr(value, "value", value)
