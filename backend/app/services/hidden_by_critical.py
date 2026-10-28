"""Ukryci przez „musi mieć”, choć w CV jest coś bliskiego (28.10.2026).

Zgłoszenie rekrutera (rekrutacja IAM, krytyczne „SailPoint IIQ”): bramka
szukała „SailPoint IIQ” albo „IIQ”, a dobrzy kandydaci pisali „SailPoint
IdentityIQ” albo „SailPoint Identity Security Cloud”. Nocny przegląd ukrył
111 takich osób i nikt o tym nie wiedział. Sekcja pod „Propozycjami z bazy”
pokazuje je z cytatem z CV, a przycisk „„<wariant>” = <krytyczna>” dopisuje
wariant do słów wiersza krytycznej (zwykły zapis Championa, nocny przegląd
liczy go od następnej nocy). Makieta A: https://claude.ai/artifact/TBHtexa3vvyK76HW2vkSMS.

Reguły, które łatwo cofnąć „przy okazji”:

* **Źródło = najnowszy przegląd automatyczny rekrutacji z wynikami**
  (ten, z którego idą propozycje ``full_base``): wiersze ``eligible = false``
  z powodem ``missing_must``. Inne powody (budżet, biuro, tylko UoP) tu nie
  wchodzą — wariant nazwy by ich nie odblokował.
* **Brakujące krytyczne liczymy dziś** tą samą bramką co przegląd
  (``search_dealbreaker_inputs`` + ``missing_must_skills`` z dowodem z notatek),
  na bieżących wierszach Championa. Osoba, która po dopisaniu wariantu już
  przechodzi, wypada z sekcji od razu; do propozycji trafi z najbliższym
  przeglądem.
* **Bliskie słowo** (:func:`close_words`) to człon nazwy krytycznej albo jej
  wariantu z wiersza, który sam nie jest pełną nazwą: co najmniej
  ``CLOSE_WORD_MIN_LETTERS`` znaki, zaczyna się literą, nie jest ogólnym
  słowem z ``_GENERIC_WORDS``. „SailPoint IIQ” → „SailPoint” („IIQ” ma 3
  znaki i jest opcją samą w sobie); „Apache Kafka” → „Apache” (gdy „Kafka”
  jest opcją); „Kafka” → nic. Krytyczna z jednego słowa nie ma bliskich słów,
  więc nikogo tu nie pokazuje — wariant pisowni takiej nazwy to sprawa słownika.
* **Osoba wchodzi wyłącznie ze śladem**: bliskie słowo stoi w profilu, CV albo
  notatce-dowodzie (te same teksty, które czyta bramka: ``profile_text``,
  ``cv_text``, ``EVIDENCE_NOTE_TYPES``) jako całe słowo. Bez śladu — nie ma
  jej w sekcji, choćby była ukryta tym samym wymaganiem.
* **Cytat to podgląd, nie zapis**: ``must_text_evidence.word_snippet`` liczy go
  przy każdym odczycie (do ``SNIPPET_CHARS`` znaków). Nie trafia do
  ``job_proposals.evidence`` (tam wyłącznie nazwy wymagań i liczby).
* **Widoczność jak skrzynka**: bez osób w rekrutacji, z globalnej czarnej listy
  i z jakąkolwiek żywą propozycją tej rekrutacji (otwartą, pominiętą, dodaną).
* **Koszt**: zawężenie w SQL (``ILIKE`` po CV z indeksem trigramowym, profilu
  i notatkach), potem najwyżej ``SCAN_MAX`` osób sprawdzanych w Pythonie;
  ``truncated`` mówi, że ukrytych ze śladem może być więcej.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from sqlalchemy import Text, cast, exists, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_search_run import CandidateSearchResult, CandidateSearchRun
from app.models.job_proposal import JobProposal
from app.models.note import Note
from app.models.recruitment_pipeline import CandidateStage

CLOSE_WORD_MIN_LETTERS = 4
SNIPPET_CHARS = 40
SCAN_MAX = 300
# Ogólne człony nazw technologii: same w CV nie mówią nic o krytycznej
# („Server” z „SQL Server”, „Cloud” z „Google Cloud”).
_GENERIC_WORDS = frozenset(
    {
        "admin",
        "administration",
        "analytics",
        "apps",
        "application",
        "applications",
        "basic",
        "boot",
        "cloud",
        "core",
        "data",
        "database",
        "design",
        "developer",
        "development",
        "engine",
        "engineer",
        "engineering",
        "enterprise",
        "framework",
        "identity",
        "management",
        "manager",
        "platform",
        "security",
        "server",
        "service",
        "services",
        "studio",
        "suite",
        "system",
        "systems",
        "testing",
        "tools",
        "version",
        # Parasole producentów: „Microsoft” z „Microsoft Dynamics 365” stoi
        # w co drugim CV i nic nie mówi o tej technologii.
        "amazon",
        "apache",
        "azure",
        "google",
        "microsoft",
        "oracle",
    }
)
_TOKEN = re.compile(r"[^\W\d_][\w+#]*")


def close_words(
    label: str, options: Optional[Mapping[str, Sequence[str]]] = None
) -> tuple[str, ...]:
    """Bliskie słowa krytycznej (reguła w docstringu modułu), w pisowni nazwy."""
    from app.services.must_gate_terms import requirement_with_options

    requirement = requirement_with_options(label, options)
    names = tuple(requirement.options) if requirement else (label,)
    full = {name.strip().casefold() for name in names}
    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        for token in _TOKEN.findall(name):
            key = token.casefold()
            if (
                len(token) < CLOSE_WORD_MIN_LETTERS
                or key in full
                or key in _GENERIC_WORDS
                or key in seen
            ):
                continue
            seen.add(key)
            out.append(token)
    return tuple(out)


@dataclass(frozen=True)
class HiddenPerson:
    candidate: Candidate
    # Krytyczna, której bramce brakuje, i bliskie słowo z jej nazwy.
    critical: str
    word: str
    # „…Onboarding applications to Sailpoint IdentityIQ…” — podgląd z tekstu.
    snippet: str
    # `profile` / `cv` / `note` — skąd cytat (`must_text_evidence.SOURCE_*`).
    source: str


@dataclass(frozen=True)
class CloseVariant:
    """Przycisk „„<word>” = <critical>” i ile osób z sekcji ma to słowo."""

    critical: str
    word: str
    people: int


@dataclass
class HiddenSection:
    run_id: Optional[str] = None
    people: list[HiddenPerson] = field(default_factory=list)
    variants: list[CloseVariant] = field(default_factory=list)
    # Krytyczne z bliskimi słowami — tym szukaliśmy w CV.
    searched: dict[str, tuple[str, ...]] = field(default_factory=dict)
    truncated: bool = False


async def _newest_auto_run(db: AsyncSession, job_id: int) -> Optional[str]:
    """Najnowszy przegląd automatyczny z wynikami (jak publikacja propozycji)."""
    from app.services import candidate_search_store as store

    return await db.scalar(
        select(CandidateSearchRun.id)
        .where(
            CandidateSearchRun.job_id == job_id,
            store.auto_origin_clause(),
            CandidateSearchRun.state.in_(store.RESULT_STATES),
        )
        .order_by(CandidateSearchRun.created_at.desc())
        .limit(1)
    )


def _ilike_any(column, words: Sequence[str]):
    return or_(*(column.ilike(f"%{word}%") for word in words))


async def _candidate_ids_with_trace(
    db: AsyncSession, *, job_id: int, run_id: str, words: Sequence[str]
) -> list[int]:
    """Ukryci przez „musi mieć” tego przeglądu, w których tekstach stoi któreś
    słowo (zawężenie bez granic słowa — decyduje :func:`_find`)."""
    from app.services.must_text_evidence import EVIDENCE_NOTE_TYPES
    from app.services import note_kinds

    row = CandidateSearchResult
    in_text = or_(
        _ilike_any(Candidate.raw_cv_text, words),
        _ilike_any(cast(Candidate.experience, Text), words),
        _ilike_any(cast(Candidate.skills, Text), words),
        _ilike_any(cast(Candidate.verified_tech, Text), words),
        _ilike_any(cast(Candidate.tags, Text), words),
        _ilike_any(cast(Candidate.cv_extracted_data, Text), words),
        exists(
            select(literal(1)).where(
                Note.candidate_id == Candidate.id,
                Note.source_deleted_at.is_(None),
                cast(Note.note_type, Text).in_(EVIDENCE_NOTE_TYPES),
                note_kinds.ai_readable_clause(),
                _ilike_any(Note.content, words),
            )
        ),
    )
    rows = await db.scalars(
        select(row.candidate_id)
        .join(Candidate, Candidate.id == row.candidate_id)
        .where(
            row.run_id == run_id,
            row.eligible.is_(False),
            row.exclusion_reasons.contains(["missing_must"]),
            Candidate.status != CandidateStatus.blacklisted,
            ~exists(
                select(literal(1)).where(
                    CandidateStage.job_id == job_id,
                    CandidateStage.candidate_id == row.candidate_id,
                )
            ),
            ~exists(
                select(literal(1)).where(
                    JobProposal.job_id == job_id,
                    JobProposal.candidate_id == row.candidate_id,
                    JobProposal.status != "expired",
                )
            ),
            in_text,
        )
        .order_by(row.candidate_id.desc())
        .limit(SCAN_MAX + 1)
    )
    return list(rows.all())


def _find(
    word: str, texts: Sequence[tuple[str, str]]
) -> Optional[tuple[str, str, str]]:
    """Pierwszy tekst, w którym słowo stoi jako całe słowo: (źródło, cytat,
    pisownia z tekstu — „Sailpoint”, „SailPoint”)."""
    from app.services.must_text_evidence import word_snippet

    for source, text in texts:
        snippet = word_snippet(word, text, chars=SNIPPET_CHARS)
        if snippet:
            surface = re.search(re.escape(word), snippet, re.IGNORECASE)
            return source, snippet, surface.group(0) if surface else word
    return None


def _spelling_rank(spelling: str, spellings: Mapping[str, int]) -> tuple:
    """Najczęstsza pisownia; przy remisie ta z większą liczbą wielkich liter
    („SailPoint” przed „Sailpoint” — tak piszą nazwę producenci)."""
    return (spellings[spelling], sum(c.isupper() for c in spelling), spelling)


async def hidden_by_critical(db: AsyncSession, job) -> HiddenSection:
    """Sekcja „Ukryci przez »musi mieć«” rekrutacji (reguły w docstringu modułu)."""
    from app.services.dealbreaker_filters import missing_must_skills
    from app.services.must_text_evidence import (
        SOURCE_CV,
        SOURCE_NOTE,
        SOURCE_PROFILE,
        attach_gate_evidence,
        cv_text,
        load_note_texts_with_words,
        profile_text,
    )
    from app.services.requirement_contract import search_dealbreaker_inputs

    section = HiddenSection()
    run_id = await _newest_auto_run(db, job.id)
    if run_id is None:
        return section
    section.run_id = run_id
    inputs = search_dealbreaker_inputs(job)
    labels = tuple(inputs.must_skills or ())
    options = inputs.gate_options
    section.searched = {
        label: words for label in labels if (words := close_words(label, options))
    }
    all_words = sorted(
        {w for words in section.searched.values() for w in words}, key=str.casefold
    )
    if not all_words:
        return section
    ids = await _candidate_ids_with_trace(
        db, job_id=job.id, run_id=run_id, words=all_words
    )
    section.truncated = len(ids) > SCAN_MAX
    ids = ids[:SCAN_MAX]
    if not ids:
        return section
    candidates = list(
        (await db.scalars(select(Candidate).where(Candidate.id.in_(ids)))).all()
    )
    await attach_gate_evidence(db, candidates, labels, options=options)
    notes = await load_note_texts_with_words(db, ids, all_words)
    by_id = {c.id: c for c in candidates}
    # (krytyczna, słowo bez wielkości liter) → pisownia z tekstów → ile osób.
    variant_people: dict[tuple[str, str], dict[str, int]] = {}
    for candidate_id in ids:
        candidate = by_id.get(candidate_id)
        if candidate is None:
            continue
        missing = missing_must_skills(
            candidate,
            labels,
            include_unknown=inputs.exclude_unknown_skill_evidence,
            verification_job_id=inputs.verification_job_id,
            verification_fingerprint=inputs.verification_fingerprint,
            options=options,
        )
        texts = [
            (SOURCE_PROFILE, profile_text(candidate)),
            (SOURCE_CV, cv_text(candidate)),
            *((SOURCE_NOTE, text) for text in notes.get(candidate_id, ())),
        ]
        first: Optional[HiddenPerson] = None
        for label in missing:
            for word in section.searched.get(label, ()):
                found = _find(word, texts)
                if found is None:
                    continue
                source, snippet, surface = found
                spellings = variant_people.setdefault((label, word.casefold()), {})
                spellings[surface] = spellings.get(surface, 0) + 1
                if first is None:
                    first = HiddenPerson(
                        candidate=candidate,
                        critical=label,
                        word=surface,
                        snippet=snippet,
                        source=source,
                    )
        if first is not None:
            section.people.append(first)
    # Wariant trafia do wiersza w najczęstszej pisowni z CV („SailPoint”),
    # nie w kanonicznej z bramki („sailpoint”).
    section.variants = sorted(
        (
            CloseVariant(
                critical=label,
                word=max(spellings, key=lambda s: _spelling_rank(s, spellings)),
                people=sum(spellings.values()),
            )
            for (label, _key), spellings in variant_people.items()
        ),
        key=lambda v: (-v.people, v.critical, v.word.casefold()),
    )
    return section
