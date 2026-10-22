"""Podobni kandydaci — zakładka „Podobni” na profilu kandydata (22.10.2026).

Decyzja Artura: podobny ≠ pasujący. Kolejność to kosinus wektorów CV
w Qdrancie (ten sam indeks co wyszukiwanie), bez żadnej rekrutacji. Obok stoi
dowód, który rekruter sprawdzi sam: wspólne umiejętności (kanoniczne nazwy,
ta sama reguła co silnik — ``candidate_known_skill_names``).

Sprawdzenie pod rekrutację to osobny krok (:func:`critical_check`): ta sama
bramka umiejętności krytycznych co wyszukiwanie — krytyczne z wyboru Delivery
Leada (``effective_critical``), słowa ich wierszy (``critical_gate_options``)
i dowód w profilu, CV albo notatkach (``must_text_evidence``). Brak krytycznej
jest ostrzeżeniem z powodem, nie blokadą: dodanie mimo to wymaga zdania, które
trafia na kartę jako notatka (``proposals_bulk``, źródło ``similar_candidates``).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import AvailabilityStatus, Candidate, CandidateStatus
from app.services.candidate_rate_from import effective_rate
from app.services.embedding_service import nearest_candidates
from app.services.my_people import active_process_counts
from app.services.scoring_service import (
    candidate_known_skill_names,
    canonical_skill_names,
)

#: Ilu najbliższych pytamy Qdranta; filtry zakładki działają w tej puli.
POOL_SIZE = 200
PAGE_MAX = 50
#: Progi stopni podobieństwa (kosinus). Do potwierdzenia pomiarem na danych
#: z produkcji — zmiana progu nie zmienia kolejności, tylko podpis.
VERY_SIMILAR_MIN = 0.80
SIMILAR_MIN = 0.70
#: Ile umiejętności „tylko u jednego” pokazuje porównanie.
ONLY_SKILLS_CAP = 12

Level = Literal["very", "similar", "partial"]
Status = Literal["ok", "no_vector", "unavailable"]


def similarity_level(score: float) -> Level:
    if score >= VERY_SIMILAR_MIN:
        return "very"
    if score >= SIMILAR_MIN:
        return "similar"
    return "partial"


def ordered_skills(candidate) -> list[str]:
    """Umiejętności osoby (bez tagów), najpierw w kolejności z profilu."""
    known = candidate_known_skill_names(candidate)
    head = [
        name
        for name in canonical_skill_names(getattr(candidate, "skills", None))
        if name in known
    ]
    return head + sorted(known - set(head))


@dataclass(frozen=True)
class SkillOverlap:
    shared: tuple[str, ...]
    only_source: tuple[str, ...]
    only_other: tuple[str, ...]


def skill_overlap(source: Sequence[str], other: Sequence[str]) -> SkillOverlap:
    """Wspólne w kolejności osoby źródłowej; reszta przycięta do ``ONLY_SKILLS_CAP``."""
    other_set = set(other)
    source_set = set(source)
    return SkillOverlap(
        shared=tuple(s for s in source if s in other_set),
        only_source=tuple(s for s in source if s not in other_set)[:ONLY_SKILLS_CAP],
        only_other=tuple(s for s in other if s not in source_set)[:ONLY_SKILLS_CAP],
    )


@dataclass(frozen=True)
class SimilarFilters:
    #: Bez osób z „Nie szuka” (domyślnie włączone na zakładce).
    hide_not_looking: bool = True
    #: Bez osób w toku w opublikowanej rekrutacji.
    without_process: bool = False
    #: Stawka do (PLN/h). Osoba bez stawki zostaje — filtr nie zgaduje.
    rate_max: Optional[Decimal] = None
    #: Fragment miasta albo lokalizacji, bez wielkości liter.
    city: Optional[str] = None


def passes_filters(candidate, filters: SimilarFilters, active_processes: int) -> bool:
    if (
        filters.hide_not_looking
        and getattr(candidate, "availability_status", None)
        == AvailabilityStatus.not_looking
    ):
        return False
    if filters.without_process and active_processes > 0:
        return False
    if filters.rate_max is not None:
        amount, currency = effective_rate(candidate)
        if (
            amount is not None
            and (currency or "PLN") == "PLN"
            and Decimal(amount) > filters.rate_max
        ):
            return False
    needle = (filters.city or "").strip().casefold()
    if needle:
        places = " ".join(
            str(value)
            for value in (
                getattr(candidate, "city", None),
                getattr(candidate, "location", None),
            )
            if value
        ).casefold()
        if needle not in places:
            return False
    return True


@dataclass(frozen=True)
class SimilarRow:
    candidate: Candidate
    score: float
    level: Level
    overlap: SkillOverlap
    active_processes: int


@dataclass(frozen=True)
class SimilarResult:
    status: Status
    rows: list[SimilarRow]
    total: int


async def find_similar(
    db: AsyncSession,
    source: Candidate,
    filters: SimilarFilters,
    *,
    offset: int = 0,
    limit: int = PAGE_MAX,
) -> SimilarResult:
    """Strona podobnych osób z puli ``POOL_SIZE`` najbliższych w Qdrancie.

    Globalna czarna lista nigdy się nie pokazuje — takiej osoby i tak nie
    zaproponujemy (bramka dodania ją odrzuca).
    """
    found = await nearest_candidates(source.id, limit=POOL_SIZE)
    if found is None:
        return SimilarResult("unavailable", [], 0)
    has_vector, hits = found
    if not has_vector:
        return SimilarResult("no_vector", [], 0)
    ids = [candidate_id for candidate_id, _score in hits]
    if not ids:
        return SimilarResult("ok", [], 0)
    loaded = (
        (
            await db.execute(
                select(Candidate).where(
                    Candidate.id.in_(ids),
                    Candidate.status != CandidateStatus.blacklisted,
                )
            )
        )
        .scalars()
        .all()
    )
    by_id = {candidate.id: candidate for candidate in loaded}
    active = await active_process_counts(db, list(by_id))
    kept = [
        (by_id[candidate_id], score)
        for candidate_id, score in hits
        if candidate_id in by_id
        and passes_filters(by_id[candidate_id], filters, active.get(candidate_id, 0))
    ]
    source_skills = ordered_skills(source)
    page = kept[offset : offset + limit]
    return SimilarResult(
        "ok",
        [
            SimilarRow(
                candidate=candidate,
                score=round(score, 4),
                level=similarity_level(score),
                overlap=skill_overlap(source_skills, ordered_skills(candidate)),
                active_processes=active.get(candidate.id, 0),
            )
            for candidate, score in page
        ],
        len(kept),
    )


# ── Sprawdzenie pod rekrutację ────────────────────────────────────────────

CriticalStatus = Literal["met", "missing", "unknown"]


@dataclass(frozen=True)
class CriticalItem:
    label: str
    status: CriticalStatus
    #: Gdzie stoi: ``profile`` / ``cv`` / ``note`` (``must_text_evidence``).
    sources: tuple[str, ...]


def critical_items(
    candidate,
    labels: Sequence[str],
    *,
    options,
    note_texts: Sequence[str] = (),
) -> list[CriticalItem]:
    """Wynik każdej krytycznej dla jednej osoby.

    ``unknown`` = krytyczna, której nie da się sprawdzić słowem (zdanie,
    branża bez słownika) — rekruter ocenia sam; nigdy nie liczy się jako brak.
    """
    from app.services.must_text_evidence import mention_sources

    found = mention_sources(candidate, labels, note_texts=note_texts, options=options)
    items: list[CriticalItem] = []
    for label in labels:
        sources = found.get(label)
        if sources is None:
            items.append(CriticalItem(label, "unknown", ()))
        else:
            items.append(CriticalItem(label, "met" if sources else "missing", sources))
    return items


def missing_labels(items: Sequence[CriticalItem]) -> list[str]:
    return [item.label for item in items if item.status == "missing"]


async def critical_check(
    db: AsyncSession, job, candidates: Sequence[Candidate]
) -> dict[int, list[CriticalItem]]:
    """``{kandydat: [krytyczne…]}`` — pusta lista, gdy rekrutacja ich nie ma."""
    from app.services.critical_skills import critical_gate_options, effective_critical
    from app.services.must_text_evidence import load_evidence_note_texts

    labels = list(effective_critical(job).labels)
    if not labels:
        return {candidate.id: [] for candidate in candidates}
    options = critical_gate_options(job)
    notes = await load_evidence_note_texts(
        db, [candidate.id for candidate in candidates], labels, options=options
    )
    return {
        candidate.id: critical_items(
            candidate,
            labels,
            options=options,
            note_texts=notes.get(candidate.id, ()),
        )
        for candidate in candidates
    }


def note_for_missing(missing: Sequence[str], reason: str) -> str:
    """Notatka na karcie przy dodaniu mimo braku krytycznej."""
    return f"Do sprawdzenia: {', '.join(missing)} — {reason.strip()}"
