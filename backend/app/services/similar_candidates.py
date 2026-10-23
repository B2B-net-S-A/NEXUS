"""Podobni kandydaci — zakładka „Podobni” na profilu kandydata (22.10.2026).

Decyzja Artura: podobny ≠ pasujący. Kolejność to kosinus wektorów CV
w Qdrancie (ten sam indeks co wyszukiwanie), bez żadnej rekrutacji. Obok stoi
dowód, który rekruter sprawdzi sam: wspólne umiejętności (kanoniczne nazwy,
ta sama reguła co silnik — ``candidate_known_skill_names``).

Możliwy duplikat (pomiar na produkcji 22.10.2026): para z kosinusem
≥ ``DUPLICATE_MIN``, w której obie osoby mają CV, w 13 z 13 przypadków była
tą samą osobą (imię i nazwisko, telefon, LinkedIn albo ten sam plik CV) —
zawsze z innym e-mailem, więc reguła „ta sama osoba = ten sam e-mail” jej nie
łapie. Znacznik wymaga kosinusa i co najmniej jednego sygnału tożsamości;
nic nie scala samo — „Scal…” otwiera zwykłe okno scalania.

Osoba bez CV i bez umiejętności (``is_thin_profile``) ma wektor zbudowany
z samych pól formalnych; wszystkie takie wektory są sobie „bardzo podobne”
(0,90–0,95). Taka osoba nie ma listy (``no_cv``) i nie trafia na listy innych.

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
from app.models.candidate_document import CandidateDocument
from app.services.candidate_identity_quarantine import normalize_person_name_part
from app.services.candidate_rate_from import effective_rate
from app.services.dedup_service import _phone_keys
from app.services.embedding_service import nearest_candidates
from app.services.my_people import active_process_counts
from app.services.scoring_service import (
    candidate_known_skill_names,
    canonical_skill_names,
)

#: Ilu najbliższych pytamy Qdranta; filtry zakładki działają w tej puli.
POOL_SIZE = 200
PAGE_MAX = 50
#: Progi stopni podobieństwa (kosinus) z pomiaru na produkcji 22.10.2026:
#: 68 924 wektory, 80 losowych osób × 20 najbliższych. Kosinus jest ściśnięty
#: (p25 0,70 · mediana 0,73 · p90 0,79), więc 0,78 ≈ górne 13% sąsiadów,
#: 0,73 = mediana. Zmiana progu nie zmienia kolejności, tylko podpis.
VERY_SIMILAR_MIN = 0.78
SIMILAR_MIN = 0.73
#: Od tego kosinusu para z sygnałem tożsamości to „Możliwy duplikat”. Pomiar
#: 22.10.2026 (200 osób × 20 najbliższych): ≥ 0,90 i obie z CV — 13/13 ta sama
#: osoba; 0,85–0,90 — już tylko 4/15.
DUPLICATE_MIN = 0.90
#: Poniżej tylu znaków tekstu CV (i bez umiejętności) nie ma z czym porównać.
#: Na produkcji 3 306 takich profili, 3 298 z wektorem.
THIN_CV_CHARS = 200
#: Ile umiejętności „tylko u jednego” pokazuje porównanie.
ONLY_SKILLS_CAP = 12

Level = Literal["very", "similar", "partial"]
Status = Literal["ok", "no_vector", "no_cv", "unavailable"]
DuplicateSignal = Literal["name", "phone", "linkedin", "cv_file"]


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


def is_thin_profile(candidate) -> bool:
    """Bez tekstu CV i bez umiejętności — wektor z samych pól formalnych."""
    text_len = len((getattr(candidate, "raw_cv_text", None) or "").strip())
    return text_len < THIN_CV_CHARS and not candidate_known_skill_names(candidate)


def _name_key(candidate) -> Optional[frozenset[str]]:
    """Imię i nazwisko bez wielkości liter i znaków; kolejność bez znaczenia."""
    parts = (
        normalize_person_name_part(getattr(candidate, "name", None)),
        normalize_person_name_part(getattr(candidate, "lastname", None)),
    )
    return frozenset(parts) if all(parts) else None


def duplicate_signals(
    source, other, score: float, *, same_cv_file: bool = False
) -> tuple[DuplicateSignal, ...]:
    """Sygnały, że to ta sama osoba — puste poniżej ``DUPLICATE_MIN``."""
    if score < DUPLICATE_MIN:
        return ()
    signals: list[DuplicateSignal] = []
    name = _name_key(source)
    if name is not None and name == _name_key(other):
        signals.append("name")
    if set(_phone_keys(getattr(source, "phone", None))) & set(
        _phone_keys(getattr(other, "phone", None))
    ):
        signals.append("phone")
    slug = getattr(source, "linkedin_slug", None)
    if slug and slug == getattr(other, "linkedin_slug", None):
        signals.append("linkedin")
    if same_cv_file:
        signals.append("cv_file")
    return tuple(signals)


async def shared_cv_files(
    db: AsyncSession, source_id: int, candidate_ids: Sequence[int]
) -> set[int]:
    """Osoby z ``candidate_ids``, które mają ten sam plik (SHA) co osoba źródłowa."""
    if not candidate_ids:
        return set()
    active = CandidateDocument.source_deleted_at.is_(None)
    source_files = (
        select(CandidateDocument.content_sha256)
        .where(
            CandidateDocument.candidate_id == source_id,
            CandidateDocument.content_sha256.is_not(None),
            active,
        )
        .scalar_subquery()
    )
    rows = await db.execute(
        select(CandidateDocument.candidate_id)
        .where(
            CandidateDocument.candidate_id.in_(list(candidate_ids)),
            CandidateDocument.content_sha256.in_(source_files),
            active,
        )
        .distinct()
    )
    return {int(candidate_id) for candidate_id in rows.scalars().all()}


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
    duplicate_signals: tuple[DuplicateSignal, ...] = ()


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
    zaproponujemy (bramka dodania ją odrzuca). Profile bez CV i umiejętności
    odpadają (patrz :func:`is_thin_profile`). Możliwy duplikat zostaje mimo
    filtrów — filtry mówią o przydatności do rekrutacji, a duplikat to porządek
    w bazie.
    """
    if is_thin_profile(source):
        return SimilarResult("no_cv", [], 0)
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
    by_id = {
        candidate.id: candidate
        for candidate in loaded
        if not is_thin_profile(candidate)
    }
    active = await active_process_counts(db, list(by_id))
    same_file = await shared_cv_files(
        db,
        source.id,
        [cid for cid, score in hits if cid in by_id and score >= DUPLICATE_MIN],
    )
    signals = {
        candidate_id: duplicate_signals(
            source,
            by_id[candidate_id],
            score,
            same_cv_file=candidate_id in same_file,
        )
        for candidate_id, score in hits
        if candidate_id in by_id
    }
    kept = [
        (by_id[candidate_id], score)
        for candidate_id, score in hits
        if candidate_id in by_id
        and (
            signals[candidate_id]
            or passes_filters(by_id[candidate_id], filters, active.get(candidate_id, 0))
        )
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
                duplicate_signals=signals[candidate.id],
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
