"""Talent Radar — score the candidate base against an ad-hoc request.

Paste a client request (or a Champion profile) and get a ranked list of people,
without creating a Job. The mirror image of ``cv_match_preview`` (CV in → jobs
out); here it is a role in → candidates out. Nothing is persisted.

Everything below the composition already existed — retrieval, scoring, the
eligibility filter, the batched per-job context. This module is the glue, which
is why it is small.

Two constraints are deliberate and load-bearing:

**A client is mandatory.** ``partition_eligible_candidates`` evaluates the
client blacklist, NDA, competitor conflicts, current employment and the
hiring-manager veto *by ``job.client_id``*. An ad-hoc search without a client
cannot run those checks — they would not fail, they would silently pass, which
is exactly the gap found in ``/ai-matches`` on 2026-08-11. Rather than surface
an unchecked list, the module refuses to answer without a client. Since
17.09.2026 client conflicts are warnings: the candidate stays in the ranking
with a badge (``RadarResult.eligibility_by_id``); only the global blacklist and
a hiring-manager veto remove someone.

**No LLM call.** Free-text requests are fed to the engine as the job narrative;
``_score_skills`` already derives implicit must-skills from the JD text or the
Champion profile when ``must_skills`` is empty. So the module costs one Voyage
query embedding and nothing else — no quota gate, no per-search spend.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.client import Client
from app.services.canonical_text import build_job_query_variants

if TYPE_CHECKING:
    # Wyłącznie dla adnotacji typu (`dealbreaker_inputs_for_radar`) — realny
    # import jest LOKALNY (w ciele funkcji), zgodnie z konwencją tego modułu
    # (leniwe importy trzymają koszt załadowania modułu niskim).
    from app.services.dealbreaker_filters import DealbreakerInputs
from app.services.retrieval_pool import retrieve_candidate_pool
from app.services.embedding_service import (
    _build_job_text,
)
from app.services.pipeline_eligibility import partition_eligible_candidates
from app.services.scoring_service import (
    ScoreBreakdown,
    WeightProfile,
    rank_candidates_for_job,
)

logger = logging.getLogger(__name__)


# Radar nie ma pipeline'u ani widełek, więc dwie warstwy nie mają czego oceniać
# i dawały wszystkim to samo: `champion_fit` zwracał stałe 6,5/10 („brak
# screeningu") dla KAŻDEGO kandydata, a `availability` ma budżet 0 już
# w domyślnym profilu. Warstwa, która nie różnicuje, nie rankuje — tylko
# podnosi podłogę i zbija wyniki w wąski przedział (zmierzone na prodzie:
# wszystkie top-20 między 74 a 79).
#
# Dziesięć punktów po `champion_fit` idzie do warstwy semantycznej, bo to
# JEDYNY sygnał, który w radarze naprawdę różnicuje kandydatów — pozostałe
# (skills, lokalizacja, stawka) mają na wklejonym requeście rzadkie pokrycie.
#
# Profil MUSI sumować się do 100: przy wyłączonej renormalizacji (domyślnej)
# wyzerowana warstwa nie znika z mianownika, tylko oddaje zero punktów — bez
# rozdzielenia jej budżetu każdy wynik radaru spadłby o 6,5 względem
# dzisiejszego, co wyglądałoby jak regres jakości.
#
# Renormalizacja NIE jest tu alternatywą: to flaga globalna i siedzi
# w `_SCORING_CACHE_INPUTS`, więc jej flip unieważniłby cały cache score'ów
# `/recommendations` — cena nieproporcjonalna do zmiany w jednym ekranie.
RADAR_PROFILE = WeightProfile(
    id=-1,
    name="talent_radar",
    semantic=70.0,
    skills=10.0,
    salary=15.0,
    location=5.0,
    availability=0.0,
    champion_fit=0.0,
)


class TalentRadarError(ValueError):
    """Input the caller can fix — surfaced as 4xx, never as a 500."""


@dataclass(frozen=True)
class RadarQuery:
    """What to search for. Exactly one of `text` / `champion_profile` is required."""

    client_id: int
    text: Optional[str] = None
    champion_profile: Optional[dict[str, Any]] = None
    title: Optional[str] = None
    location: Optional[str] = None
    top_k: int = 20
    min_score: Optional[float] = None
    # Dealbreaker-switche: radar nie ma oferty, więc budżet PLN/h podaje
    # wprost rekruter — i sama jego obecność aktywuje twardy sufit (decyzja
    # produktowa 19.08). Nieznana stawka/preferencja kandydata PRZECHODZI.
    budget_hourly_max: Optional[float] = None
    exclude_remote_only: bool = False
    # Rubryki 0278: dni w biurze / tydzień i miasto biura, podane WPROST przez
    # rekrutera (radar nie ma kolumn oferty do fallbacku). `onsite_days_per_week`
    # aktywuje dealbreakery dni/miasta TYLKO gdy > 0 — patrz
    # `dealbreaker_inputs_for_radar`.
    onsite_days_per_week: Optional[int] = None
    office_location: Optional[str] = None
    # Wymagania podane WPROST (front bierze je z `parse-champion`). Puste =
    # dotychczasowe zachowanie: `_score_skills` wywodzi must regexem z profilu
    # Championa albo z prozy. `list`, nie `tuple`, mimo `frozen=True`:
    # dataclass zabrania tylko mutowalnej wartości DOMYŚLNEJ, a `None` nią nie
    # jest — i tak `champion_profile: Optional[dict]` obok czyni ten rekord
    # niehaszowalnym.
    must_skills: Optional[list[str]] = None
    nice_skills: Optional[list[str]] = None
    requirements_reviewed: bool = False
    matching_requirements: Optional[dict] = None


@dataclass
class RadarResult:
    breakdowns: list[ScoreBreakdown]
    pool_size: int
    eligible_size: int
    degraded: bool
    reason: Optional[str] = None
    hidden: dict[str, int] = field(default_factory=dict)
    # `ScoreBreakdown` carries `candidate_id` and nothing else about the person.
    # A search that answers with opaque integers is not a search a recruiter can
    # read, and making the browser resolve each id would be an N+1 over the
    # network on a list this endpoint already holds in memory.
    candidates_by_id: dict[int, Any] = field(default_factory=dict)
    # Eligibility badge per returned candidate (``eligibility_annotation``) —
    # client conflict / current employment / excluded client. Absent = clean.
    eligibility_by_id: dict[int, dict] = field(default_factory=dict)

    def as_meta(self) -> dict[str, Any]:
        return {
            "pool_size": self.pool_size,
            "eligible_size": self.eligible_size,
            "returned": len(self.breakdowns),
            "degraded": self.degraded,
            "reason": self.reason,
            "hidden": self.hidden,
        }


def shape_radar_candidate(candidate: Any) -> dict[str, Any]:
    """Identity fields a result row needs — and no more.

    Mirrors `_shape_seek_candidate` in `recommendations.py`, minus `email`.
    A ranked list is a triage surface: the recruiter reads it to decide whom to
    open. Contact details belong on the profile behind that click, so shipping
    them in every search response would widen the exposure of personal data
    without changing a single decision made on this screen.
    """

    availability = getattr(candidate, "availability_status", None)
    return {
        "id": candidate.id,
        "name": candidate.name,
        "lastname": candidate.lastname,
        "location": getattr(candidate, "location", None),
        "competence_category": getattr(candidate, "competence_category", None),
        "years_it_experience": getattr(candidate, "years_it_experience", None),
        "availability_status": availability.value if availability else None,
        "champion": bool(getattr(candidate, "champion", False)),
        "avatar_url": getattr(candidate, "avatar_url", None),
    }


# Sufity dla wymagań przychodzących z zewnątrz. Liczba pozycji jest twarda
# (dłuższa lista odbija się 422 w modelu requestu), pojedyncza nazwa jest
# PRZYCINANA, nie odrzucana: jeden gadatliwy punkt z dokumentu nie może
# wywalić całego wyszukiwania, a przycięty i tak przechodzi przez mapę aliasów.
_MAX_RADAR_SKILLS = 50
_MAX_RADAR_SKILL_LEN = 100


def normalize_skill_names(raw: Any) -> list[str]:
    """`[{"name": "Python"}, "python ", …]` → `["Python"]` — bez duplikatów.

    Przyjmuje oba kształty, bo z jednej strony stoi wyjście parsera profilu
    (lista dictów), a z drugiej ciało requestu (lista nazw — klient może je
    POST-ować wprost, więc normalizacja musi zajść też tam).

    Zachowuje ORYGINALNĄ wielkość liter (nazwy wracają do interfejsu), ale
    dedupe idzie po `casefold()`. Odpowiednik ze scoringu lowercase'uje, więc
    do warstwy prezentacji się nie nadaje.
    """
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        name = item.get("name") if isinstance(item, dict) else item
        if not isinstance(name, str):
            continue
        name = name.strip()[:_MAX_RADAR_SKILL_LEN].strip()
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        out.append(name)
        if len(out) >= _MAX_RADAR_SKILLS:
            break
    return out


def _structured_skills(names: Optional[list[str]]) -> Optional[list[dict]]:
    """Explicit requirements must survive transport regardless of rollout flags."""
    return [{"name": n, "level": None} for n in names or ()] or None


def build_ephemeral_job(query: RadarQuery) -> SimpleNamespace:
    """A Job-shaped object that is never persisted.

    Every attribute the scoring and embedding paths touch is set explicitly.
    A `SimpleNamespace` rather than an unsaved ORM `Job` on purpose: an unsaved
    instance still carries relationship descriptors that can trigger a lazy load
    on attribute access, which in async SQLAlchemy raises `MissingGreenlet`
    rather than returning a default.

    `id=None` is meaningful, not a placeholder: `build_job_scoring_context`
    filters `CandidateStage.job_id == job.id`, so a None id yields no screening
    rows — correct, because an ad-hoc search has no pipeline history to read.
    """
    return SimpleNamespace(
        id=None,
        client_id=query.client_id,
        title=(query.title or "").strip() or None,
        description=(query.text or "").strip() or None,
        requirements=None,
        champion_profile=query.champion_profile or None,
        # Kształt 1:1 z `jobs.must_skills` (`[{"name": str, "level": None}]` —
        # tak pisze importer Championów), bo ten sam obiekt czyta
        # `_build_job_text` i `build_job_query_variants`.
        # Puste (albo flaga OFF) → `None` → `_score_skills` wraca do wywodzenia
        # must z profilu Championa, a potem z prozy, więc wklejony request jest
        # dalej oceniany po swojej treści, a nie po pustej liście.
        must_skills=_structured_skills(query.must_skills),
        nice_skills=_structured_skills(query.nice_skills),
        requirements_reviewed=query.requirements_reviewed,
        location=(query.location or "").strip() or None,
        office_location=(query.office_location or "").strip() or None,
        exclude_remote_only=query.exclude_remote_only,
        remote_policy=None,
        # Rubryki 0278: radar nie ma kolumny `onsite_days_per_week`, ale
        # niesie ją tu POD PRZYSZŁY strażnik AST (`test_ephemeral_job_sets_
        # every_attribute_the_scoring_path_reads`) — gdyby scoring kiedyś
        # zaczął czytać `job.onsite_days_per_week`, oferta efemeryczna go nie
        # zgubi. `dealbreaker_inputs_for_radar` czyta ten sygnał wprost z
        # `RadarQuery`, nie stąd.
        onsite_days_per_week=query.onsite_days_per_week,
        matching_requirements=query.matching_requirements,
        rate_budget_hourly=query.budget_hourly_max,
        salary_min=None,
        salary_max=None,
        deadline=None,
        seniority=None,
        subcategory=None,
        industry=None,
        embedding_id=None,
        # Zapytanie ad hoc nie ma hiring managera, więc nie ma czyjego weta
        # sprawdzać — ale `load_manager_rejections` czyta to pole ZANIM sprawdzi,
        # czy jest puste (`hiring_manager_verdicts.py:120`), a `SimpleNamespace`
        # nie ma domyślnych atrybutów. Bez tej linii każde wyszukanie, które
        # zwróciło choć jednego kandydata, kończyło się `AttributeError` w
        # `filter_eligible_candidates` → 500. Pusta pula (degradacja retrievalu)
        # wychodziła wcześniej, więc awaria nie pokazywała się na ścieżce
        # „Qdrant leży" — tylko na tej, która miała działać.
        hiring_manager_contact_id=None,
        # `None` = „nie tnij" przy wywodzeniu umiejętności z prozy. Prawdziwa
        # oferta nie ma tego atrybutu i zachowuje sufit 4000 znaków; tutaj
        # request wklejony przez rekrutera bywa mailem z wymaganiami na końcu.
        skill_scan_cap=None,
    )


async def _load_candidates(
    db: AsyncSession, candidate_ids: Sequence[int]
) -> list[Candidate]:
    if not candidate_ids:
        return []
    rows = (
        (await db.execute(select(Candidate).where(Candidate.id.in_(candidate_ids))))
        .scalars()
        .all()
    )
    by_id = {c.id: c for c in rows}
    # Preserve retrieval order; a missing row means the vector outlived its
    # candidate (there are ~1 900 such orphans in Qdrant) and is skipped.
    return [by_id[cid] for cid in candidate_ids if cid in by_id]


def dealbreaker_inputs_for_radar(query: RadarQuery) -> DealbreakerInputs:
    """Rubryki 0278 dla UNA wyszukiwania radaru — z pól `RadarQuery` wprost.

    W odróżnieniu od `dealbreaker_filters.dealbreaker_inputs_for_job` (oferty
    prawdziwe, z fallbackiem do Championa za flagą), radar nie ma kolumn ani
    profilu Championa do odpytania — rekruter wpisuje budżet/must/dni/miasto
    wprost w formularzu, więc konstrukcja jest prostym przepisaniem pól.

    `wants_office = query.exclude_remote_only or dni > 0`: istniejący
    przełącznik „wyklucz tylko-zdalnych" ORAZ nowe pole dni w biurze OBA
    uzbrajają AUTO-wykluczanie „wyłącznie zdalnie" w `apply_dealbreakers` —
    rekruter, który wpisał wymaganą liczbę dni, nie musi PONADTO zaznaczać
    osobnego checkboxa, żeby dostać spójny wynik.
    """
    from app.services.dealbreaker_filters import (
        OFFICE_CITY_HARD_MIN_DAYS,
        DealbreakerInputs,
        gate_eligible_must_skills,
    )
    from app.services.location_utils import location_tokens
    from app.services.scoring_service import job_explicit_must_skills

    days = query.onsite_days_per_week
    office_tokens = frozenset(location_tokens(query.office_location))
    wants_office = bool(query.exclude_remote_only) or bool(days and days > 0)
    # Radar nie zna trybu pracy: ukrywa przy zaznaczonym „wyklucz tylko
    # zdalnych” albo od 4 dni w biurze, przy 1–3 dniach — plakietka.
    remote_only_hides = bool(query.exclude_remote_only) or bool(
        days and days >= OFFICE_CITY_HARD_MIN_DAYS
    )

    from app.services.critical_skills import effective_critical, gate_mode

    ephemeral = build_ephemeral_job(query)
    eligible = tuple(gate_eligible_must_skills(job_explicit_must_skills(ephemeral)))
    critical_source = None
    if gate_mode() == "critical":
        # Radar nie ma profilu Championa, więc działa podpowiedź z historii
        # (30.09.2026) — ta sama reguła co w rekrutacji bez decyzji DL.
        resolution = effective_critical(ephemeral)
        must = tuple(m for m in eligible if m in set(resolution.labels))
        critical_source = resolution.source
    else:
        must = eligible
    return DealbreakerInputs(
        budget_hourly=query.budget_hourly_max,
        must_skills=must,
        must_skills_ignored=tuple(m for m in eligible if m not in set(must)),
        critical_source=critical_source,
        evidence_labels=eligible,
        onsite_days_per_week=days,
        office_tokens=office_tokens,
        wants_office=wants_office,
        remote_only_hides=remote_only_hides,
    )


DEALBREAKER_CHUNK = 64


async def _apply_dealbreakers_yielding(
    candidates: list, *, inputs, **switches: Any
) -> Any:
    """`apply_dealbreakers` w paczkach, z oddaniem pętli zdarzeń między nimi.

    Runda 9 (R9-N5-1): pula radaru to do `MATCH_POOL_SIZE` kandydatów, a filtr
    (w tym bramka must-have po umiejętnościach) jest czystym CPU. Decyzja
    o kandydacie nie zależy od innych kandydatów, więc wynik paczek złożony
    w kolejności jest identyczny z jednym wywołaniem na całej liście.

    ``switches`` (``exclude_*``) przechodzą bez zmian — runda 10 (R10-V2-10):
    ścieżka kanoniczna (``matching._gate_and_dealbreakers``) filtruje tę samą
    pulę z przełącznikami.
    """
    from dataclasses import fields

    from app.services.dealbreaker_filters import DealbreakerResult, apply_dealbreakers

    merged = DealbreakerResult()
    counters = [
        f.name for f in fields(DealbreakerResult) if f.name.startswith("hidden_")
    ]
    for start in range(0, len(candidates), DEALBREAKER_CHUNK):
        if start:
            await asyncio.sleep(0)
        part = apply_dealbreakers(
            candidates[start : start + DEALBREAKER_CHUNK], inputs=inputs, **switches
        )
        merged.kept.extend(part.kept)
        merged.exclusion_reasons.update(part.exclusion_reasons)
        for name in counters:
            setattr(merged, name, getattr(merged, name) + getattr(part, name))
    return merged


async def search(db: AsyncSession, query: RadarQuery) -> RadarResult:
    """Rank the candidate base against an ad-hoc role. Persists nothing."""
    if not query.text and not query.champion_profile:
        raise TalentRadarError(
            "Podaj treść zapytania albo profil Championa — bez tego nie ma czego szukać."
        )
    client = await db.scalar(select(Client).where(Client.id == query.client_id))
    if client is None:
        # Not a formality: without a real client the NDA / competitor / veto
        # annotations below have nothing to evaluate against.
        raise TalentRadarError(
            "Wskaż klienta — bez niego nie da się sprawdzić NDA, konfliktów "
            "konkurencyjnych ani weta hiring managera."
        )

    job = build_ephemeral_job(query)
    from app.services.champion_intake import enforce_operation

    enforce_operation(job, "search", force=True)
    # `max_field_chars=None` — radar embeduje CAŁY wklejony request. Domyślne
    # 1200 znaków sprawiało, że mail z wymaganiami na końcu był rankowany po
    # akapicie grzeczności (zmierzone: `must 1/2`, podobieństwo 0,65 zamiast
    # 0,73). Sufit realny daje `max_length=20_000` w modelu żądania — około
    # 7 tys. tokenów, jedna piąta okna modelu embeddingów.
    query_text = _build_job_text(job, max_field_chars=None)
    if not query_text.strip():
        raise TalentRadarError("Zapytanie jest puste po normalizacji.")

    # C12: terminy dla nogi BM25 (dokument w roli tsquery = zero trafień
    # zawsze). Oferta efemeryczna nie ma `must_skills`, więc terminy przyjdą
    # z profilu/prozy Championa przez taksonomię — czyta wyłącznie atrybuty,
    # które `build_ephemeral_job` już ustawia. To zmiana CZŁONKOSTWA puli,
    # aktywna tylko przy `HYBRID_POOL_ENABLED=true`, i NIE jest tą zmianą
    # rankingu radaru, która ma własną flagę (tamta dotyczy `_score_skills`).
    from app.services.hybrid_search import build_job_bm25_query, build_job_must_groups

    # `raise_on_error=True` rozdziela dwa stany, które do tej pory wyglądały
    # identycznie: AWARIĘ dostawcy i zdrowe zapytanie bez trafień. Przy
    # domyślnym połykaniu błędu oba dawały pustą listę, więc radar raportował
    # `semantic_unavailable` także wtedy, gdy retrieval działał — a to znaczy,
    # że baner awarii przestaje cokolwiek znaczyć. `/ai-matches` rozróżnia je
    # od 08.2026 (`no_semantic_hits`); tu doganiamy tamten kontrakt.
    from app.services.embedding_service import SemanticSearchUnavailable
    from app.services.dealbreaker_filters import DealbreakerResult

    try:
        hits = await retrieve_candidate_pool(
            db,
            query_text,
            top_k=settings.MATCH_POOL_SIZE,
            raise_on_error=True,
            query_variants=build_job_query_variants(job, query_text),
            bm25_query=build_job_bm25_query(job),
            # 0278: oferta efemeryczna nie ma `must_skills`, chyba że rekruter
            # podał je wprost (`RadarQuery.must_skills`, za osobną flagą) —
            # `build_job_must_groups` czyta wtedy dokładnie ten atrybut.
            # No-op, dopóki `STRUCTURED_POOL_ENABLED` jest wyłączona.
            must_groups=build_job_must_groups(job),
        )
    except SemanticSearchUnavailable as exc:
        logger.warning("[talent-radar] retrieval niedostępny: %s", exc)
        return RadarResult(
            breakdowns=[],
            pool_size=0,
            eligible_size=0,
            degraded=True,
            reason="semantic_unavailable",
            # Pięć kluczy, choćby zerowych — pustka bez wyjaśnienia czyta się
            # jak utrata danych (reguła „awaria ≠ pustka").
            hidden=DealbreakerResult().hidden_meta(),
        )
    if not hits:
        # Zdrowe zapytanie, zero trafień. NIE jest to awaria — interfejs ma
        # powiedzieć „nikt nie pasuje", a nie „nie wiemy".
        return RadarResult(
            breakdowns=[],
            pool_size=0,
            eligible_size=0,
            degraded=False,
            reason="no_semantic_hits",
            hidden=DealbreakerResult().hidden_meta(),
        )

    similarity_map = {h["candidate_id"]: h["score"] for h in hits}
    candidates = await _load_candidates(db, list(similarity_map))
    pool_size = len(candidates)

    candidates, eligibility_by_id = await partition_eligible_candidates(
        db, job=job, candidates=candidates, now=datetime.now(timezone.utc)
    )
    eligible_size = len(candidates)

    # Dealbreaker-switche: twarde ukrywanie na życzenie, liczniki do meta —
    # ukrywanie nigdy nie jest ciche (reguła „awaria ≠ pustka"). Rubryki 0278
    # (must/dni/miasto) i AUTO `exclude_remote_only` (z `wants_office`) liczone
    # RAZEM przez `dealbreaker_inputs_for_radar` — bez jawnego
    # `exclude_remote_only=` tutaj, bo `inputs.wants_office` już go niesie.
    radar_inputs = dealbreaker_inputs_for_radar(query)
    from app.services.must_text_evidence import attach_gate_evidence

    await attach_gate_evidence(db, candidates, radar_inputs.gate_evidence_labels)
    dealbreakers = await _apply_dealbreakers_yielding(candidates, inputs=radar_inputs)
    candidates = dealbreakers.kept

    # `rank_candidates_for_job`, NOT `bulk_get_or_compute`: the score cache is
    # keyed by (candidate, job, profile) and this job has no id, so caching would
    # either collide across unrelated searches or crash on the null key.
    breakdowns = await rank_candidates_for_job(
        job, candidates, db, similarity_map=similarity_map, profile=RADAR_PROFILE
    )

    threshold = (
        query.min_score
        if query.min_score is not None
        else settings.RECOMMENDATION_MIN_SCORE
    )
    ranked = [b for b in breakdowns if b.total >= threshold][: query.top_k]
    hidden_meta = dealbreakers.hidden_meta()

    # Only the rows that survived ranking — the eligible pool can be a thousand
    # wide, and shipping all of it would undo the trimming done above.
    kept = {b.candidate_id for b in ranked}
    return RadarResult(
        breakdowns=ranked,
        pool_size=pool_size,
        eligible_size=eligible_size,
        degraded=False,
        hidden=hidden_meta,
        candidates_by_id={c.id: c for c in candidates if c.id in kept},
        eligibility_by_id={
            cid: ann for cid, ann in eligibility_by_id.items() if cid in kept
        },
    )


async def canonical_search(
    db: AsyncSession, query: RadarQuery, *, user_id: Optional[int]
) -> RadarResult:
    """Szybki ranking pod request tą samą miarą co ekran Radaru (Jarvis).

    Runda 9 (R9-N5-4): narzędzie Jarvisa wołało legacy `search` (profil
    `RADAR_PROFILE`, próg `RECOMMENDATION_MIN_SCORE`, dealbreakery z pól
    radaru), a ekran od #1428 pokazuje pełny przegląd z KANONICZNYM fitem
    i polityką must-have `search_dealbreaker_inputs`. Ta sama osoba miała
    więc inną liczbę w czacie i na ekranie. Tu: ten sam kontekst żądania
    (`build_request_context` + profil wag osoby), ta sama bramka
    (`_gate_and_dealbreakers` na `context.as_job()`, jak worker przeglądu)
    i `canonical_fit.score_candidates`. Różnica względem ekranu jest jedna
    i świadoma: ocenia pulę `MATCH_POOL_SIZE` najbliższych, nie całą bazę
    (pełny przegląd trwa ~3 min). ``breakdowns`` niesie ``CanonicalFit``;
    niezmierzony wynik odpada (nigdy 0).
    """
    from app.api.matching import _gate_and_dealbreakers
    from app.services.canonical_fit import score_candidates
    from app.services.champion_intake import enforce_operation
    from app.services.dealbreaker_filters import DealbreakerResult
    from app.services.embedding_service import SemanticSearchUnavailable
    from app.services.hybrid_search import build_job_bm25_query, build_job_must_groups
    from app.services.request_matching_context import build_request_context
    from app.services.requirement_contract import search_dealbreaker_inputs
    from app.services.scoring_service import resolve_active_profile

    if not query.text and not query.champion_profile:
        raise TalentRadarError(
            "Podaj treść zapytania albo profil Championa — bez tego nie ma czego szukać."
        )
    if await db.scalar(select(Client.id).where(Client.id == query.client_id)) is None:
        raise TalentRadarError(
            "Wskaż klienta — bez niego nie da się sprawdzić NDA, konfliktów "
            "konkurencyjnych ani weta hiring managera."
        )
    job = build_ephemeral_job(query)
    enforce_operation(job, "search", force=True)
    profile = await resolve_active_profile(
        db, user_id=user_id, client_id=query.client_id
    )
    context = build_request_context(job, profile)
    target = context.as_job()
    empty_hidden = DealbreakerResult().hidden_meta()
    try:
        hits = await retrieve_candidate_pool(
            db,
            context.query_text,
            top_k=settings.MATCH_POOL_SIZE,
            raise_on_error=True,
            # Kolejność i tak nadpisuje kanoniczny fit (jak `/ai-matches`).
            use_rerank=False,
            # 0278: jawne must-have oferty efemerycznej i noga BM25 — jak
            # ścieżka legacy, żeby pula była ta sama, a różnił się tylko wynik.
            query_variants=build_job_query_variants(job, context.query_text),
            bm25_query=build_job_bm25_query(job),
            must_groups=build_job_must_groups(job),
        )
    except SemanticSearchUnavailable as exc:
        logger.warning("[talent-radar] retrieval niedostępny: %s", exc)
        return RadarResult(
            breakdowns=[],
            pool_size=0,
            eligible_size=0,
            degraded=True,
            reason="semantic_unavailable",
            hidden=empty_hidden,
        )
    if not hits:
        return RadarResult(
            breakdowns=[],
            pool_size=0,
            eligible_size=0,
            degraded=False,
            reason="no_semantic_hits",
            hidden=empty_hidden,
        )
    candidates = await _load_candidates(db, [h["candidate_id"] for h in hits])
    kept, annotations, hidden, _, _ = await _gate_and_dealbreakers(
        db,
        job=target,
        ordered=candidates,
        now=datetime.now(timezone.utc),
        inputs=search_dealbreaker_inputs(target),
    )
    fits = await score_candidates(db, context, kept)
    measured = [f for f in fits if f.fit_score is not None]
    ranked = [
        f for f in measured if query.min_score is None or f.fit_score >= query.min_score
    ][: query.top_k]
    returned = {f.breakdown.candidate_id for f in ranked}
    blind = bool(kept) and not measured
    return RadarResult(
        breakdowns=ranked,
        pool_size=len(candidates),
        eligible_size=len(kept),
        # Pula była, ale nikogo nie zmierzono = brak wektora zapytania.
        degraded=blind,
        reason="semantic_unavailable" if blind else None,
        hidden=hidden,
        candidates_by_id={c.id: c for c in kept if c.id in returned},
        eligibility_by_id={
            cid: ann for cid, ann in annotations.items() if cid in returned
        },
    )
