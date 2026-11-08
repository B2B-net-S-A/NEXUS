"""Silnik „System trzyma Nowych na 20” (decyzje Artura 23.10.2026).

Makiety: https://claude.ai/artifact/6qyrJf65QmsQdJteLZWVT2. Każda rekrutacja
w pracy ma mieć w kolumnie „Nowi” około ``TARGET`` osób. Brakujące dodaje
system — najlepsze osoby z puli nocnego przeglądu (``job_autofill_pool``,
każdy wynik) i z otwartych propozycji, bez blokady 12 h (bierze pierwszy,
kto ruszy kartę). Rekruterzy dodają dalej sami; ich osoby też się liczą.

Reguły, które łatwo cofnąć „przy okazji”:

* Rytm: dni robocze 7:00–19:00 (``BUSINESS_TZ``), pełny przebieg co
  ``FULL_PASS_EVERY``, a między nimi co tick rekrutacje, w których ktoś ruszył
  kartę od poprzedniego ticku (odrzucenie albo przesunięcie z „Nowych”).
* Zawsze do ``TARGET``, także poniżej progu propozycji (decyzja „zawsze 20”).
* System NIE dodaje: osób, które kiedykolwiek były w tej rekrutacji (także
  zamknięta karta i osoba usunięta z rekrutacji — archiwum
  ``candidate_stage_removals``), osób odrzuconych „na cały klient” w innej
  rekrutacji tego klienta (``autofill_feedback.whole_client``, 27.10.2026),
  pominiętych propozycji tej rekrutacji, osób,
  które dziś stoją na „Zatrudniony” gdziekolwiek, oraz każdego, przy kim bramka
  kwalifikacji mówi cokolwiek innego niż „brak przeciwwskazań” (ostrzeżenia
  o konflikcie z klientem zostawiamy człowiekowi). Off-limits u klienta:
  system nie zna odpowiedzi „sam się zgłosił”, więc pomija.
* Reguły z odrzuceń (decyzje Artura 25.10.2026, analiza 34 powodów i 1 557
  osób od systemu): znana „Stawka od” ponad ``BUDGET_HARD_OVER`` nad budżetem
  rekrutacji = nie dodaje (16 z 34 odrzuceń to „za droga” przy stawce, którą
  system znał; wśród osób wysłanych przez zespół takich jest 1,5%), do 25% nad
  budżetem = za osobami w budżecie i z nieznaną stawką (27.10.2026: próg
  25% → 15%, bo 15–25% szło dalej tak rzadko jak ponad 25%). Osoba, która według
  CV albo LinkedIna pracuje teraz u klienta tej rekrutacji, nie wchodzi —
  także przy wpisie CV bez dat (``client_off_limits.find_hit``
  z ``undated_counts``).
* Biuro i miasto (decyzja Artura 27.10.2026, analiza 133 odrzuceń): osoba,
  która według profilu przyjmie mniej dni w biurze, niż chce klient, chce
  wyłącznie zdalnie albo mieszka w innym mieście przy pracy z biurem, szła
  dalej o połowę rzadziej (18% wobec 36%) — wchodzi za resztą, nie odpada
  (7 z 39 takich osób poszło dalej). Co system wiedział (budżet, biuro,
  miasto), zapisuje ``entry_meta.cautions``; karta i panel to pokazują.
* Dojazd do biura (29.10.2026, 23–29.10: 102 osoby od systemu w 115
  rekrutacjach z biurem w Warszawie mieszkały ponad 100 km od każdego biura
  albo za granicą): miasto dalej niż ``OFFICE_FAR_KM`` od najbliższego biura
  rekrutacji z biurem (także hybryda bez liczby dni) = system nie dodaje;
  ``OFFICE_NEAR_KM``–``OFFICE_FAR_KM`` = ostrzeżenie z km, za resztą; bliżej
  = bez ostrzeżenia o mieście. Osoba, która sama wskazała miasto biura
  (profil, notatki, relokacja), i miasto spoza słownika — jak dotąd.
* „Nie szuka pracy” (decyzja Artura 28.10.2026): 9 z 44 odrzuceń, a ci sami
  ludzie czekali w „Nowych” innych rekrutacji. Profil „Nie szuka” bez daty
  albo z „Dostępny od” w przyszłości = system nie dodaje (``not_looking_now``).
* Inna rola niż rekrutacja (decyzja Artura 29.10.2026, 03.11.2026 domknięta
  w ``ranked_picks``): karta ląduje na tablicy bez człowieka, więc osoba z inną
  rolą jej nie dostaje, także przy ≥ 80% „musi mieć” i z otwartą propozycją.
  Propozycja zostaje w oknie z plakietką, tam decyduje rekruter.
* Wejście ``entry_source = "system"``, ``moved_by`` puste (dodał nie
  człowiek), ``entry_meta`` = migawka tego, co system wiedział: wynik,
  wymagania, „Stawka od”, dostępność. Z niej raport odróżnia błąd
  wyszukiwania od braku danych. Propozycji nie zamyka (``added`` stawia
  człowiek, 07.10.2026) — lista propozycji i tak pomija osoby w rekrutacji.
* Znamy tę osobę (decyzja Artura z 02.11.2026): kolejność dobierania to wynik
  plus punkty ``known_queue_points``; w ``entry_meta.score`` zostaje sam wynik.
  Co 5. miejsce należy do najlepszej osoby bez procesu (``with_fresh_slots``).
* Wpis „Praca w tle” (``job_automation``) po każdym dopełnieniu.
* Cel z tempa (decyzja Artura z 08.11.2026, ``NEW_COLUMN_TEMPO_TARGET_ENABLED``,
  raport https://claude.ai/artifact/HgCGsxN7Nk7ENGpb6iNg2B). Liczą się czekające
  karty od systemu, cel to 5, 10 albo 20 wg decyzji ludzi z 21 dni (``tempo_of``),
  przebieg raz rano, a w dzień po ruchu karty tylko gorące, nowe i P0. Osoba nowa
  w bazie zajmuje rano miejsce karty nietkniętej 7 dni, do ``FRESH_SWAPS_PER_DAY``
  na rekrutację. Reguła: ``rekrutacja-tablica/cel-kart-wg-tempa-i-miejsce-dla-swiezych.md``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Collection, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, union_all
from sqlalchemy.orm import aliased

from app.core.config import settings
from app.core.scheduling import (
    business_today,
    is_business_day,
    local_day_start_utc,
)
from app.models.activity import Activity
from app.models.autofill_feedback import AutofillFeedback
from app.models.candidate import AvailabilityStatus, Candidate
from app.models.candidate_stage_removal import CandidateStageRemoval
from app.models.job import Job, JobStatus
from app.models.job_autofill_pool import JobAutofillPool
from app.models.job_proposal import JobProposal
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage
from app.services import autofill_withdraw, candidate_claim
from app.services.board_stage_badges import board_column_for
from app.services.candidate_added_date import (
    AddedToBase,
    is_new_in_base,
    new_in_base_clause,
)
from app.services.job_proposals import proposal_threshold
from app.services.pipeline_latest import current_hired_stage_clause, latest_stage_ids
from app.services.request_work_state import IN_WORK_STATES

logger = logging.getLogger(__name__)

TARGET = 20
# Tyle kart ponad ``TARGET`` może dojść wyłącznie osobami nowymi w bazie
# (03.11.2026): 173 ze 189 rekrutacji miało pełne „Nowe”, więc świeża osoba
# czekała poza Tablicą. Kart nie zdejmujemy (wygaszanie odrzucone 28.10.2026).
FRESH_OVER_TARGET = 5
# Co które miejsce w „Nowych” należy do najlepszej osoby bez procesu (03.11.2026).
FRESH_EVERY = 5
FULL_PASS_EVERY = timedelta(minutes=15)
WORK_START_HOUR = 7
WORK_END_HOUR = 19
ACTIVITY_ENTITY = "job_automation"
ACTION = "new_column_autofill"
ENTRY_KIND = "autofill"
# Źródła propozycji, z których system dobiera obok puli. ``job_board`` to
# zgłoszenia z portali — te nigdy nie stają się kartą bez człowieka (0405).
_PROPOSAL_SOURCES = ("full_base", "new_cv")
# Zapas kandydatów ponad brak: część odpadnie na bramce kwalifikacji.
_PICK_HEADROOM = 3
# Ilu najlepszych przechodzi przez reguły z odrzuceń przed bramką — tyle, ile
# ma pula nocnego przeglądu, żeby osoba w budżecie z dalszego miejsca mogła
# wyprzedzić droższą (w top 20 wyniki różnią się średnio o 3,5 pkt).
_RULES_WINDOW = 150
# Stawka ponad tyle nad budżetem = system nie dodaje (25.10.2026: 25%;
# 27.10.2026: 15% — osoby 15–25% nad budżetem szły dalej w 12%, ponad 25%
# w 15%, a 0–15% w 40%, tyle co w budżecie).
BUDGET_HARD_OVER = Decimal("0.15")
# Miasto dalej niż tyle km (w linii prostej) od każdego biura rekrutacji =
# system nie dodaje; bliżej niż ``OFFICE_NEAR_KM`` = bez ostrzeżenia o mieście
# (29.10.2026). Od 100 km zaczyna się Łódź dla Warszawy (117 km).
OFFICE_FAR_KM = 100
OFFICE_NEAR_KM = 50
# „Stawka od” poniżej tej kwoty to błąd odczytu (na produkcji 0,6 zł/h), nie
# stawka — liczy się jak nieznana.
_MIN_PLAUSIBLE_RATE = Decimal("20")
# Cel kart od systemu wg tempa (08.11.2026, produkcja z 21 dni): 74 rekrutacje
# starsze niż 14 dni bez decyzji, a 22 zrobiły 67% wszystkich.
TEMPO_WINDOW_DAYS = 21
TEMPO_NEW_JOB_DAYS = 14
TEMPO_HOT_DECISIONS = 10
TEMPO_QUIET_TARGET = 5
TEMPO_MODERATE_TARGET = 10
TEMPO_HOT_TARGET = 20
# „Dodaj 10 kolejnych” przy kolumnie „Nowi”.
MORE_CARDS = 10
# Tyle kart dziennie może ustąpić osobom nowym w bazie w jednej rekrutacji.
FRESH_SWAPS_PER_DAY = 5


def enabled() -> bool:
    return bool(getattr(settings, "NEW_COLUMN_AUTOFILL_ENABLED", False))


def tempo_enabled() -> bool:
    return bool(getattr(settings, "NEW_COLUMN_TEMPO_TARGET_ENABLED", False))


def in_work_hours(now: datetime) -> bool:
    local = now.astimezone(ZoneInfo(settings.BUSINESS_TZ))
    return (
        is_business_day(now, settings.BUSINESS_TZ)
        and WORK_START_HOUR <= local.hour < WORK_END_HOUR
    )


# ── Ilu jest w „Nowych” ─────────────────────────────────────────────────────


async def new_column_counts(db, job_ids: list[int]) -> dict[int, int]:
    """Osoby w kolumnie „Nowi” Tablicy — ta sama reguła kolumny co Tablica."""
    if not job_ids:
        return {}
    latest = latest_stage_ids(job_ids=job_ids)
    rows = (
        await db.execute(
            select(
                CandidateStage.job_id,
                CandidateStage.stage,
                PipelineStageDef.name,
                PipelineStageDef.category,
                PipelineStageDef.terminal_type,
            )
            .outerjoin(
                PipelineStageDef, PipelineStageDef.id == CandidateStage.stage_def_id
            )
            .where(CandidateStage.id.in_(select(latest.c.latest_id)))
        )
    ).all()
    counts = dict.fromkeys(job_ids, 0)
    for job_id, stage, name, category, terminal_type in rows:
        column = board_column_for(
            name,
            getattr(stage, "value", stage),
            category=getattr(category, "value", category),
            terminal_type=getattr(terminal_type, "value", terminal_type),
        )
        if column == candidate_claim.NEW_COLUMN:
            counts[job_id] = counts.get(job_id, 0) + 1
    return counts


# ── Cel wg tempa ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Tempo:
    tier: str  # quiet | moderate | hot | new | p0
    target: int
    decisions: int

    @property
    def refills_during_day(self) -> bool:
        """Dopełnianie po ruchu karty: gorące, nowe i P0, reszta przyciskiem."""
        return self.target == TEMPO_HOT_TARGET


def tempo_of(decisions: int, *, new_job: bool, p0: bool) -> Tempo:
    """Cel kart od systemu. P0 i nowa rekrutacja mają 20 także bez decyzji."""
    if p0:
        return Tempo("p0", TEMPO_HOT_TARGET, decisions)
    if decisions >= TEMPO_HOT_DECISIONS:
        return Tempo("hot", TEMPO_HOT_TARGET, decisions)
    if new_job:
        return Tempo("new", TEMPO_HOT_TARGET, decisions)
    if decisions == 0:
        return Tempo("quiet", TEMPO_QUIET_TARGET, decisions)
    return Tempo("moderate", TEMPO_MODERATE_TARGET, decisions)


async def _new_column_decisions(
    db, job_ids: list[int], since: datetime
) -> dict[int, int]:
    """Decyzje ludzi: osoby, które człowiek wyprowadził z „Nowych” od ``since``.
    Te same stany „Nowych” co decyzja porcji (``review_batch._NEW_STAGES``)."""
    from app.services import review_batch

    stages = (
        select(
            CandidateStage.job_id,
            CandidateStage.candidate_id,
            CandidateStage.stage,
            CandidateStage.moved_by,
            CandidateStage.moved_at,
            func.lag(CandidateStage.stage, type_=CandidateStage.stage.type)
            .over(
                partition_by=(CandidateStage.job_id, CandidateStage.candidate_id),
                order_by=(CandidateStage.moved_at, CandidateStage.id),
            )
            .label("previous"),
        )
        .where(CandidateStage.job_id.in_(job_ids))
        .subquery()
    )
    rows = await db.execute(
        select(stages.c.job_id, func.count(func.distinct(stages.c.candidate_id)))
        .where(
            stages.c.moved_by.is_not(None),
            stages.c.moved_at >= since,
            stages.c.stage.not_in(review_batch._NEW_STAGES),
            stages.c.previous.in_(review_batch._NEW_STAGES),
        )
        .group_by(stages.c.job_id)
    )
    return {int(job_id): int(count) for job_id, count in rows.all()}


def _is_new_job(job: Job, now: datetime) -> bool:
    started = job.opened_at or job.created_at
    return started is not None and started >= now - timedelta(days=TEMPO_NEW_JOB_DAYS)


async def tempo_for_jobs(db, job_ids: list[int], now: datetime) -> dict[int, Tempo]:
    from app.services import job_p0

    if not job_ids:
        return {}
    jobs = (await db.scalars(select(Job).where(Job.id.in_(job_ids)))).all()
    decisions = await _new_column_decisions(
        db, job_ids, now - timedelta(days=TEMPO_WINDOW_DAYS)
    )
    return {
        job.id: tempo_of(
            decisions.get(job.id, 0),
            new_job=_is_new_job(job, now),
            p0=job_p0.is_active(job, now),
        )
        for job in jobs
    }


async def waiting_system_cards(db, job_id: int) -> int:
    """Czekające karty od systemu: zgłoszenia, osoby od zespołu i karty, które
    ktoś wziął, stoją poza celem."""
    from app.services import review_batch

    cards = await review_batch.pending_cards(db, job_ids=[job_id])
    return sum(1 for card in cards if not card.taken)


# ── Kogo dodać ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Pick:
    candidate_id: int
    score: float
    run_id: Optional[str]
    matched_must: tuple[str, ...]
    missing_must: tuple[str, ...]
    # Co przemawia przeciw, a system to wiedział (``_by_rules``) — migawka
    # ``entry_meta.cautions``.
    cautions: tuple[dict, ...] = ()
    # Weszła z pierwszeństwem „nowa w bazie” — migawka ``entry_meta.fresh_first``.
    fresh: bool = False


def _names(evidence: Optional[dict], key: str) -> tuple[str, ...]:
    values = (evidence or {}).get(key) or []
    return tuple(str(v) for v in values if isinstance(v, str) and v)


def not_looking_now():
    """Osoby z profilem „Nie szuka” bez daty albo z „Dostępny od” w przyszłości
    — rekruter usłyszał „nie szukam” (odrzucenie z datą, 28.10.2026)."""
    return select(Candidate.id).where(
        Candidate.availability_status == AvailabilityStatus.not_looking,
        or_(
            Candidate.availability_date.is_(None),
            Candidate.availability_date > business_today(),
        ),
    )


async def _other_role_ids(db, job: Optional[Job], candidate_ids: list[int]) -> set[int]:
    """Osoby z inną rolą niż rekrutacja, z samych kolumn tytułu (pełny wiersz
    kandydata niesie tekst CV)."""
    from types import SimpleNamespace

    from app.services.role_family import family_of, mismatches_for_job

    if job is None or family_of(job.title) is None or not candidate_ids:
        return set()
    rows = (
        await db.execute(
            select(
                Candidate.id,
                Candidate.cv_extracted_data["current_position"].label("position"),
                Candidate.linkedin_current_title,
                # `current_title` czyta tylko pierwszy wpis doświadczenia.
                Candidate.experience[0].label("latest_experience"),
            ).where(Candidate.id.in_(candidate_ids))
        )
    ).all()
    people = [
        SimpleNamespace(
            id=row.id,
            cv_extracted_data={"current_position": row.position},
            linkedin_current_title=row.linkedin_current_title,
            experience=[row.latest_experience] if row.latest_experience else None,
        )
        for row in rows
    ]
    return set(await mismatches_for_job(db, job, people))


async def ranked_picks(
    db,
    job_id: int,
    *,
    limit: int,
    new_in_base_at: Optional[datetime] = None,
    min_score: Optional[float] = None,
) -> list[Pick]:
    """Najlepsi z puli i otwartych propozycji, bez osób, których system nie
    dodaje (patrz docstring modułu, poza bramką kwalifikacji). Inna rola nie
    zajmuje miejsca w ``limit``, więc wiersze idą paczkami. Przy
    ``new_in_base_at`` tylko osoby nowe w bazie, a przy ``min_score`` od tego wyniku."""
    pool = select(
        JobAutofillPool.candidate_id.label("candidate_id"),
        JobAutofillPool.score.label("score"),
        JobAutofillPool.run_id.label("run_id"),
        JobAutofillPool.evidence.label("evidence"),
    ).where(JobAutofillPool.job_id == job_id)
    proposals = select(
        JobProposal.candidate_id.label("candidate_id"),
        JobProposal.score.label("score"),
        JobProposal.run_id.label("run_id"),
        JobProposal.evidence.label("evidence"),
    ).where(
        JobProposal.job_id == job_id,
        JobProposal.status == "proposed",
        JobProposal.source.in_(_PROPOSAL_SOURCES),
        JobProposal.score.is_not(None),
    )
    both = union_all(pool, proposals).subquery()
    ever_in_job = select(CandidateStage.candidate_id).where(
        CandidateStage.job_id == job_id
    )
    removed = select(CandidateStageRemoval.candidate_id).where(
        CandidateStageRemoval.job_id == job_id
    )
    # Osoba, która ustąpiła miejsca świeżym, może wrócić (08.11.2026), ale już
    # nie z pierwszeństwem „nowa w bazie”: inaczej zdejmowałaby następną kartę.
    if new_in_base_at is None:
        removed = removed.where(
            CandidateStageRemoval.reason.is_distinct_from(
                autofill_withdraw.FRESH_SEAT_REASON
            )
        )
    dismissed = select(JobProposal.candidate_id).where(
        JobProposal.job_id == job_id, JobProposal.status == "dismissed"
    )
    hired_now = select(CandidateStage.candidate_id).where(current_hired_stage_clause())
    # Odrzucenie „na cały klient” (27.10.2026): pracuje u klienta albo nie
    # chce do niego — żadna rekrutacja tego klienta tej osoby nie dostaje.
    rejected_job = aliased(Job)
    refused_client = (
        select(AutofillFeedback.candidate_id)
        .join(rejected_job, rejected_job.id == AutofillFeedback.job_id)
        .where(
            AutofillFeedback.whole_client.is_(True),
            rejected_job.client_id.is_not(None),
            rejected_job.client_id
            == select(Job.client_id).where(Job.id == job_id).scalar_subquery(),
        )
    )
    narrowing = []
    if new_in_base_at is not None:
        narrowing.append(
            both.c.candidate_id.in_(
                select(Candidate.id).where(
                    new_in_base_clause(Candidate, new_in_base_at)
                )
            )
        )
    if min_score is not None:
        narrowing.append(both.c.score >= min_score)
    rows = (
        await db.execute(
            select(both.c.candidate_id, both.c.score, both.c.run_id, both.c.evidence)
            .where(
                both.c.candidate_id.not_in(ever_in_job),
                both.c.candidate_id.not_in(removed),
                both.c.candidate_id.not_in(dismissed),
                both.c.candidate_id.not_in(hired_now),
                both.c.candidate_id.not_in(refused_client),
                both.c.candidate_id.not_in(not_looking_now()),
                *narrowing,
            )
            .order_by(both.c.score.desc(), both.c.candidate_id)
        )
    ).all()
    best: dict[int, Pick] = {}
    for candidate_id, score, run_id, evidence in rows:
        if candidate_id in best:
            continue  # wiersze idą od najlepszego wyniku — pierwszy wygrywa
        evidence = evidence or {}
        best[candidate_id] = Pick(
            candidate_id=int(candidate_id),
            score=float(score),
            run_id=run_id,
            matched_must=_names(evidence, "matched_must"),
            missing_must=_names(evidence, "missing_must"),
        )
    job = await db.get(Job, job_id)
    ordered = list(best.values())
    picks: list[Pick] = []
    for start in range(0, len(ordered), limit):
        page = ordered[start : start + limit]
        other_role = await _other_role_ids(db, job, [p.candidate_id for p in page])
        picks.extend(p for p in page if p.candidate_id not in other_role)
        if len(picks) >= limit:
            break
    return await _with_known_points(db, job_id, picks[:limit])


def has_fresh_first(
    meta: object, added: AddedToBase, *, threshold: float, now: datetime
) -> bool:
    """Karta od systemu z pierwszeństwem w kolejce: nowa w bazie, od progu, bez uwag."""
    if not settings.NEW_COLUMN_FRESH_FIRST_ENABLED or not isinstance(meta, dict):
        return False
    score = meta.get("score")
    return (
        isinstance(score, (int, float))
        and score >= threshold
        and not meta.get("cautions")
        and is_new_in_base(added, now)
    )


async def new_in_base_picks(db, job: Job, *, now: datetime) -> list[Pick]:
    """Osoby z pierwszeństwem „nowa w bazie”: od progu, po regułach i bez uwag."""
    if not settings.NEW_COLUMN_FRESH_FIRST_ENABLED:
        return []
    picks = await ranked_picks(
        db,
        job.id,
        limit=_RULES_WINDOW,
        new_in_base_at=now,
        min_score=await proposal_threshold(db),
    )
    return [
        replace(pick, fresh=True)
        for pick in await _by_rules(db, job, picks)
        if not pick.cautions
    ]


async def _with_known_points(db, job_id: int, picks: list[Pick]) -> list[Pick]:
    """Kolejność: wynik + „znamy tę osobę” (02.11.2026) + premia porcji. Procent
    bez zmian."""
    from app.services import review_batch_order
    from app.services.known_queue_points import facts_for

    client_id = await db.scalar(select(Job.client_id).where(Job.id == job_id))
    facts = await facts_for(
        db,
        job_id=job_id,
        client_id=client_id,
        candidate_ids=[p.candidate_id for p in picks],
        now=datetime.now(timezone.utc),
    )
    known = {cid: fact.points for cid, fact in facts.items()}
    bonus = await review_batch_order.pick_bonuses(db, job_id, picks)
    # Sortowanie stabilne: remis zostaje w kolejności wyniku.
    return sorted(
        picks,
        key=lambda p: (
            -(p.score + known.get(p.candidate_id, 0) + bonus.get(p.candidate_id, 0))
        ),
    )


def with_fresh_slots(
    picks: list[Pick], fresh: set[int], *, start: int = 0
) -> list[Pick]:
    """Co ``FRESH_EVERY``-te miejsce kolumny dla najlepszej osoby bez procesu.

    ``start`` to liczba kart już w kolumnie: przy dopełnianiu po jednej osobie
    miejsce liczy się dalej, inaczej nikt bez procesu by nie wszedł. Osoba
    z ostrzeżeniem nie przeskakuje. Odtworzenie 814 rekrutacji: R@20 nowych
    z 0,051 do 0,319, bez istotnej straty P@5, R@20, MRR i nDCG@10.
    """
    waiting = sorted(
        (p for p in picks if p.candidate_id in fresh and not p.cautions),
        key=lambda p: (-p.score, p.candidate_id),
    )
    out: list[Pick] = []
    used: set[int] = set()
    rest = iter(picks)
    while len(out) < len(picks):
        pick = None
        if (start + len(out) + 1) % FRESH_EVERY == 0:
            pick = next((p for p in waiting if p.candidate_id not in used), None)
        if pick is None:
            pick = next(p for p in rest if p.candidate_id not in used)
        out.append(pick)
        used.add(pick.candidate_id)
    return out


def budget_tier(candidate, budget_hourly: Optional[float]) -> Optional[int]:
    """``0`` = w budżecie, stawka nieznana albo brak budżetu; ``1`` = do
    ``BUDGET_HARD_OVER`` nad budżetem; ``None`` = system nie dodaje."""
    from app.services.candidate_rate_from import effective_rate
    from app.services.dealbreaker_filters import candidate_consents_below_min_rate

    rate, currency = effective_rate(candidate)
    return _rate_tier(
        rate,
        currency,
        consents=candidate_consents_below_min_rate(candidate),
        budget_hourly=budget_hourly,
    )


def _rate_tier(
    rate, currency, *, consents: bool, budget_hourly: Optional[float]
) -> Optional[int]:
    if budget_hourly is None or consents:
        return 0
    if rate is None or str(currency or "").strip().upper() != "PLN":
        return 0
    rate = Decimal(str(rate))
    budget = Decimal(str(budget_hourly))
    if rate < _MIN_PLAUSIBLE_RATE or rate <= budget:
        return 0
    if rate > budget * (1 + BUDGET_HARD_OVER):
        return None
    return 1


def budget_caution(rate, currency, *, budget_hourly: Optional[float]) -> Optional[dict]:
    """Znana stawka PLN ponad budżetem (w granicach ``BUDGET_HARD_OVER``)."""
    if budget_hourly is None or rate is None:
        return None
    if str(currency or "").strip().upper() != "PLN":
        return None
    rate = Decimal(str(rate))
    budget = Decimal(str(budget_hourly))
    if rate < _MIN_PLAUSIBLE_RATE or rate <= budget or budget <= 0:
        return None
    return {
        "key": "budget",
        "over_pct": int(((rate / budget - 1) * 100).quantize(Decimal("1"))),
        "rate": float(rate),
        "budget": float(budget),
    }


def office_km(person, office_tokens: frozenset[str]) -> Optional[int]:
    """Km z miasta osoby do najbliższego biura rekrutacji. ``None`` = nie
    wiemy (brak miasta, miasto spoza słownika) albo osoba sama wskazała miasto
    biura — w profilu, w notatkach z rozmowy albo jako kierunek relokacji."""
    from app.services.location_utils import (
        candidate_office_tokens,
        city_tokens,
        nearest_km,
        tokens_overlap,
    )

    if not office_tokens:
        return None
    if tokens_overlap(set(office_tokens), candidate_office_tokens(person)):
        return None
    home = city_tokens(person.location) | city_tokens(person.city)
    km = nearest_km(home, set(office_tokens))
    return None if km is None else round(km)


def office_cautions(
    person,
    *,
    office_days: Optional[int],
    office_tokens: frozenset[str],
    office_label: Optional[str],
    km: Optional[int] = None,
) -> list[dict]:
    """Biuro i miasto wg profilu — tymi samymi regułami co bramka wyszukiwania
    (``dealbreaker_filters``); nieznane przechodzi bez ostrzeżenia. Znane km
    (``office_km``) zastępuje porównanie nazw miasta."""
    from app.services.dealbreaker_filters import (
        candidate_consents_more_office_days,
        office_city_mismatch,
        office_days_exceeded,
        remote_only_refuses_office,
    )

    days = office_days if office_days and office_days > 0 else None
    out: list[dict] = []
    if days and not candidate_consents_more_office_days(person):
        if office_days_exceeded(person, days):
            out.append(
                {
                    "key": "office_days",
                    "candidate_days": person.max_onsite_days_per_week,
                    "required_days": days,
                }
            )
        elif remote_only_refuses_office(person):
            out.append({"key": "remote_only", "required_days": days})
    city = {
        "key": "office_city",
        "city": (person.city or person.location or "").strip()[:60] or None,
        "office": (office_label or "").strip()[:60] or None,
        "required_days": days,
    }
    if km is not None:
        if km > OFFICE_NEAR_KM:
            out.append({**city, "km": km})
    elif days and office_city_mismatch(person, office_tokens, required_days=days):
        out.append(city)
    return out


async def _by_rules(db, job: Job, picks: list[Pick]) -> list[Pick]:
    """Reguły z odrzuceń: bez osób daleko ponad budżetem, pracujących teraz
    u klienta i mieszkających dalej niż ``OFFICE_FAR_KM`` od biura; osoby
    trochę ponad budżetem za resztą (kolejność wyniku
    w obrębie poziomu zostaje), tak samo osoby z ostrzeżeniem o biurze albo
    mieście. Czyta tylko potrzebne kolumny — okno ma do ``_RULES_WINDOW``
    osób, a pełny wiersz kandydata niesie tekst CV."""
    from types import SimpleNamespace

    from app.services import client_off_limits
    from app.services.candidate_rate_from import (
        effective_currency_sql,
        effective_rate_sql,
    )
    from app.services.dealbreaker_filters import (
        dealbreaker_inputs_for_job,
        resolve_job_budget_hourly,
    )

    if not picks:
        return []
    columns = (
        Candidate.id,
        # „Stawka od” tą samą regułą co `effective_rate` (strażnik 0414).
        effective_rate_sql(Candidate).label("rate"),
        effective_currency_sql(Candidate).label("currency"),
        Candidate.accepts_below_min_rate,
        Candidate.linkedin_current_company,
        Candidate.experience,
        Candidate.name,
        Candidate.lastname,
        Candidate.max_onsite_days_per_week,
        Candidate.accepts_more_office_days,
        Candidate.preferences,
        Candidate.location,
        Candidate.city,
        Candidate.cv_extracted_data["_notes_insights"].label("notes_insights"),
    )
    people = {
        row.id: SimpleNamespace(
            **row._mapping,
            # `remote_only_refuses_office` czyta notatki z `cv_extracted_data`.
            cv_extracted_data={"_notes_insights": row.notes_insights},
        )
        for row in (
            await db.execute(
                select(*columns).where(
                    Candidate.id.in_([p.candidate_id for p in picks])
                )
            )
        ).all()
    }
    budget = resolve_job_budget_hourly(job)
    inputs = dealbreaker_inputs_for_job(job)
    office_label = getattr(job, "office_location", None) or job.location
    labels = (
        await client_off_limits.client_labels(db, job.client_id)
        if job.client_id
        else []
    )
    tiered: list[tuple[int, Pick]] = []
    for pick in picks:
        person = people.get(pick.candidate_id)
        if person is None:
            continue
        tier = _rate_tier(
            person.rate,
            person.currency,
            consents=person.accepts_below_min_rate is True,
            budget_hourly=budget,
        )
        if tier is None:
            continue
        if client_off_limits.find_hit(person, labels, undated_counts=True):
            continue
        km = office_km(person, inputs.office_tokens) if inputs.wants_office else None
        if km is not None and km > OFFICE_FAR_KM:
            continue
        cautions = [
            c
            for c in (
                budget_caution(person.rate, person.currency, budget_hourly=budget)
                if tier
                else None,
            )
            if c
        ]
        office = office_cautions(
            person,
            office_days=inputs.onsite_days_per_week,
            office_tokens=inputs.office_tokens,
            office_label=office_label,
            km=km,
        )
        cautions.extend(office)
        tiered.append(
            (tier + (1 if office else 0), replace(pick, cautions=tuple(cautions)))
        )
    # Sortowanie stabilne: w obrębie poziomu zostaje kolejność wyniku.
    tiered.sort(key=lambda item: item[0])
    return [pick for _, pick in tiered]


async def _allowed(db, job: Job, picks: list[Pick], now: datetime) -> list[Pick]:
    """Tylko „brak przeciwwskazań” i bez off-limits u klienta."""
    from app.services import client_off_limits
    from app.services.candidate_job_eligibility import EligibilityReason
    from app.services.pipeline_eligibility import (
        evaluate_candidates_for_job_with_verdicts,
    )

    if not picks:
        return []
    ids = [p.candidate_id for p in picks]
    candidates = {
        c.id: c
        for c in (
            await db.scalars(select(Candidate).where(Candidate.id.in_(ids)))
        ).all()
    }
    decisions, _verdicts = await evaluate_candidates_for_job_with_verdicts(
        db, job=job, candidate_ids=ids, now=now, candidates=candidates
    )
    eligible = [
        p
        for p in picks
        if p.candidate_id in candidates
        and decisions[p.candidate_id].reason_code is EligibilityReason.eligible
    ]
    off_limits = {
        person.candidate_id
        for person in await client_off_limits.people_needing_confirmation(
            db,
            job_id=job.id,
            candidates=[candidates[p.candidate_id] for p in eligible],
        )
    }
    return [p for p in eligible if p.candidate_id not in off_limits]


def entry_meta(pick: Pick, candidate: Candidate) -> dict:
    """Migawka tego, co system wiedział w chwili dodania (makieta A2)."""
    from app.services.candidate_rate_from import effective_rate

    rate, currency = effective_rate(candidate)
    availability = getattr(candidate, "availability_date", None)
    status = getattr(candidate, "availability_status", None)
    meta = {
        "kind": ENTRY_KIND,
        "score": round(pick.score, 2),
        "run_id": pick.run_id,
        "matched_must": list(pick.matched_must),
        "missing_must": list(pick.missing_must),
        "rate_from_hourly": float(rate) if rate is not None else None,
        "rate_currency": currency if rate is not None else None,
        "availability_date": availability.isoformat() if availability else None,
        "availability_status": getattr(status, "value", status),
        "cautions": [dict(c) for c in pick.cautions],
    }
    if pick.fresh:
        meta["fresh_first"] = True
    return meta


# ── Dopełnienie jednej rekrutacji ───────────────────────────────────────────


@dataclass(frozen=True)
class _Room:
    have: int
    missing: int
    fresh_room: int
    target: int
    min_score: Optional[float] = None


async def _room(
    db,
    job_id: int,
    *,
    now: datetime,
    batch: bool,
    extra: Optional[int],
    tempo: Optional[Tempo],
) -> Optional[_Room]:
    """Ile kart może dojść. ``None`` = porcja bez rekrutera."""
    from app.services import review_batch

    if batch:
        team = (await review_batch.recruiter_ids_for_jobs(db, [job_id])).get(job_id, [])
        if not team:
            return None
        min_score = (await review_batch.read_settings(db)).min_score
        # Liczą się tylko karty porcji (od progu, do 7 dni): stare i słabe
        # karty nie zajmują miejsca świeżym (08.11.2026).
        have = len(
            review_batch.batch_cards(
                await review_batch.pending_cards(db, job_ids=[job_id]), now, min_score
            )
        )
        target = tempo.target if tempo else review_batch.BATCH_SIZE
        missing = extra if extra is not None else target - have
        return _Room(have, missing, missing, target, min_score)
    if tempo is not None:
        have = await waiting_system_cards(db, job_id)
        missing = extra if extra is not None else tempo.target - have
        return _Room(have, missing, missing, tempo.target)
    have = (await new_column_counts(db, [job_id])).get(job_id, 0)
    missing = TARGET - have
    return _Room(have, missing, missing + FRESH_OVER_TARGET, TARGET)


async def _swaps_today(db, job_id: int, now: datetime) -> int:
    day = now.astimezone(ZoneInfo(settings.BUSINESS_TZ)).date()
    return int(
        await db.scalar(
            select(func.count(CandidateStageRemoval.id)).where(
                CandidateStageRemoval.job_id == job_id,
                CandidateStageRemoval.reason == autofill_withdraw.FRESH_SEAT_REASON,
                CandidateStageRemoval.removed_at
                >= local_day_start_utc(day, settings.BUSINESS_TZ),
            )
        )
        or 0
    )


async def fill_job(
    db,
    job_id: int,
    *,
    now: datetime,
    limit: Optional[int] = None,
    batch: bool = False,
    extra_for: Optional[int] = None,
    extra_cards: Optional[int] = None,
    swap: bool = False,
) -> list[int]:
    """Dopełnij „Nowych” do ``TARGET``, osobami nowymi w bazie także do
    ``TARGET + FRESH_OVER_TARGET`` (najwyżej ``limit`` osób naraz). Nowi w bazie
    wchodzą pierwsi. Zwraca id dodanych osób. Bez commitu.

    ``batch`` = porcja dnia (``review_batch``, 07.11.2026): liczą się tylko
    czekające karty od systemu, do ``review_batch.BATCH_SIZE`` od
    progu porcji (``BatchSettings.min_score``), wyłącznie w rekrutacji z rekruterem; karty
    dostają właścicieli. ``extra_for`` = „Dodaj 20 kolejnych” tej osoby.

    Przy ``NEW_COLUMN_TEMPO_TARGET_ENABLED`` cel to ``Tempo.target`` (także
    w porcji), a osoby nowe w bazie nie wchodzą ponad cel. ``extra_cards`` =
    tyle osób ponad cel z przycisku, ``swap`` = poranne miejsce dla świeżych,
    bez porcji: tam stara karta nie zajmuje miejsca, więc zamiana przekraczałaby cel."""
    from app.api.proposals_bulk import add_candidates_to_job
    from app.services import review_batch
    from app.services.known_queue_points import without_process

    job = await db.get(Job, job_id)
    if (
        job is None
        or job.status != JobStatus.published
        or job.work_state not in IN_WORK_STATES
    ):
        return []
    tempo: Optional[Tempo] = None
    if tempo_enabled():
        tempo = (await tempo_for_jobs(db, [job_id], now)).get(job_id)
    extra = extra_cards
    if extra is None and extra_for:
        extra = review_batch.BATCH_SIZE
    room = await _room(db, job_id, now=now, batch=batch, extra=extra, tempo=tempo)
    if room is None:
        return []
    have, missing, fresh_room, target = (
        room.have,
        room.missing,
        room.fresh_room,
        room.target,
    )
    min_score = room.min_score
    if limit is not None:
        missing = min(missing, limit)
        fresh_room = min(fresh_room, limit)
    fresh_room = max(fresh_room, 0)
    swap_room = 0
    if swap and not batch:
        swap_room = FRESH_SWAPS_PER_DAY - await _swaps_today(db, job_id, now)
        if limit is not None:
            swap_room = min(swap_room, limit - fresh_room)
        swap_room = max(swap_room, 0)
    chosen: list[Pick] = []
    spare: list[Pick] = []
    if fresh_room + swap_room > 0:
        fresh = await new_in_base_picks(db, job, now=now)
        if min_score is not None:
            # Porcja: próg panelu HoR może być niższy niż 65% porcji.
            fresh = [pick for pick in fresh if pick.score >= min_score]
        fresh = fresh[: (fresh_room + swap_room) * _PICK_HEADROOM + 10]
        allowed = await _allowed(db, job, fresh, now)
        chosen = allowed[:fresh_room]
        spare = allowed[fresh_room : fresh_room + swap_room]
    missing -= len(chosen)
    if missing > 0:
        taken = {pick.candidate_id for pick in chosen}
        picks = await _by_rules(
            db,
            job,
            await ranked_picks(db, job_id, limit=_RULES_WINDOW, min_score=min_score),
        )
        picks = [pick for pick in picks if pick.candidate_id not in taken]
        picks = with_fresh_slots(
            picks,
            await without_process(
                db, job_id=job_id, candidate_ids=[p.candidate_id for p in picks]
            ),
            start=have + len(chosen),
        )
        picks = picks[: missing * _PICK_HEADROOM + 10]
        chosen += (await _allowed(db, job, picks, now))[:missing]
    if spare:
        # Cel jest pełny, a nowi w bazie czekają: zdejmuje się tyle kart, ile
        # osób wejdzie. Awaria zapisu jednej osoby zostawia wolne miejsce do jutra.
        seats = await autofill_withdraw.plan_fresh_seats(db, job_id, now=now)
        gone = await autofill_withdraw.apply(
            db,
            seats[: len(spare)],
            reason=autofill_withdraw.FRESH_SEAT_REASON,
            check_budget=False,
        )
        chosen += spare[: len(gone)]
    if not chosen:
        if batch:
            await review_batch.assign_owners(db, job_id, now=now, only=extra_for)
        return []
    candidates = {
        c.id: c
        for c in (
            await db.scalars(
                select(Candidate).where(
                    Candidate.id.in_([p.candidate_id for p in chosen])
                )
            )
        ).all()
    }
    added: list[int] = []
    for pick in chosen:
        try:
            async with db.begin_nested():
                result = await add_candidates_to_job(
                    db,
                    job=job,
                    candidate_ids=[pick.candidate_id],
                    actor_user_id=None,
                    entry_source=candidate_claim.ENTRY_SYSTEM,
                    claim=False,
                    entry_meta=entry_meta(pick, candidates[pick.candidate_id]),
                    mark_proposals=False,
                )
        except Exception as exc:  # noqa: BLE001 — jedna osoba nie wywraca rekrutacji
            logger.warning(
                "[new_column_autofill] add failed job=%s candidate=%s: %s",
                job_id,
                pick.candidate_id,
                type(exc).__name__,
            )
            continue
        added.extend(result.added)
    if added:
        db.add(
            Activity(
                entity_type=ACTIVITY_ENTITY,
                entity_id=job_id,
                action=ACTION,
                user_id=None,
                details={
                    # `count` czyta „Praca w tle” (`_DETAIL_KEYS`).
                    "count": len(added),
                    "candidate_ids": added,
                    "had": have,
                    "target": target,
                },
            )
        )
        await db.flush()
    if batch:
        await review_batch.assign_owners(db, job_id, now=now, only=extra_for)
    return added


# ── Rytm ────────────────────────────────────────────────────────────────────


async def _jobs_in_work(db) -> list[int]:
    return [
        int(job_id)
        for (job_id,) in (
            await db.execute(
                select(Job.id)
                .where(
                    Job.status == JobStatus.published,
                    Job.work_state.in_(IN_WORK_STATES),
                )
                .order_by(Job.id)
            )
        ).all()
    ]


async def _jobs_touched_since(db, since: datetime) -> list[int]:
    """Rekrutacje w pracy, w których od ``since`` ktoś ruszył kartę."""
    return [
        int(job_id)
        for (job_id,) in (
            await db.execute(
                select(func.distinct(CandidateStage.job_id))
                .join(Job, Job.id == CandidateStage.job_id)
                .where(
                    CandidateStage.moved_at >= since,
                    CandidateStage.moved_by.is_not(None),
                    Job.status == JobStatus.published,
                    Job.work_state.in_(IN_WORK_STATES),
                )
            )
        ).all()
    ]


@dataclass
class _State:
    last_full_pass: Optional[datetime] = None
    last_tick: Optional[datetime] = None
    # Rekrutacje pełnego przebiegu, do których bezpiecznik jeszcze nie doszedł.
    pending: list[int] = field(default_factory=list)


def _budget() -> int:
    """Bezpiecznik (23.10.2026): najwyżej tyle dodań na tick. Każde dodanie
    pobiera CV z magazynu i zapisuje jego kopię, a pierwszy przebieg na
    produkcji to ok. 2–3 tys. osób — limit rozkłada to na kilkadziesiąt minut."""
    return max(1, int(getattr(settings, "NEW_COLUMN_AUTOFILL_MAX_PER_TICK", 100)))


_state = _State()


async def tick(*, now: Optional[datetime] = None) -> dict:
    """Jeden krok pętli. Każda rekrutacja w osobnej transakcji."""
    from app.core.database import AsyncSessionLocal

    from app.services import review_batch

    now = now or datetime.now(timezone.utc)
    if not enabled():
        return {"skipped": "disabled"}
    if not in_work_hours(now):
        _state.last_tick = None
        return {"skipped": "outside_hours"}
    if review_batch.enabled():
        return await _batch_tick(now)
    if tempo_enabled():
        return await _tempo_tick(now)
    full = not _state.pending and (
        _state.last_full_pass is None or now - _state.last_full_pass >= FULL_PASS_EVERY
    )
    async with AsyncSessionLocal() as db:
        touched = await _jobs_touched_since(db, _state.last_tick or now)
        if full:
            _state.pending = await _jobs_in_work(db)
            _state.last_full_pass = now
    _state.last_tick = now
    # Najpierw rekrutacje z ruchem karty (ktoś właśnie odrzucił), potem reszta
    # pełnego przebiegu — od miejsca, w którym bezpiecznik przerwał.
    job_ids = list(dict.fromkeys([*touched, *_state.pending]))
    budget = _budget()
    filled: dict[int, int] = {}
    done: set[int] = set()
    # Rekrutacja, przy której skończył się limit — mogła nie dojść do 20.
    cut_short: Optional[int] = None
    for job_id in job_ids:
        if budget <= 0:
            break
        done.add(job_id)
        async with AsyncSessionLocal() as db:
            try:
                added = await fill_job(db, job_id, now=now, limit=budget)
                await db.commit()
            except Exception as exc:  # noqa: BLE001 — jedna rekrutacja nie blokuje reszty
                await db.rollback()
                logger.warning(
                    "[new_column_autofill] job=%s failed: %s",
                    job_id,
                    type(exc).__name__,
                )
                continue
        if added:
            filled[job_id] = len(added)
            budget -= len(added)
            if budget <= 0:
                cut_short = job_id
    _state.pending = [j for j in _state.pending if j not in done or j == cut_short]
    return {
        "pass": "full" if full else "touched",
        "jobs": len(done),
        "pending": len(_state.pending),
        "filled": filled,
    }


# ── Porcja dnia (07.11.2026) ────────────────────────────────────────────────

BATCH_DAY_KEY = "review_batch_day"


async def _jobs_by_priority(db, now: datetime) -> list[int]:
    """Rekrutacje w pracy: P0, priorytet, potem nowsze (W8)."""
    from app.services import review_batch

    ids = await _jobs_in_work(db)
    jobs = (await db.scalars(select(Job).where(Job.id.in_(ids)))).all() if ids else []
    return [
        job.id
        for job in sorted(
            jobs, key=lambda j: (review_batch._priority_rank(j, now), -j.id)
        )
    ]


async def _day_plan(db, today: str, now: datetime) -> dict:
    """Plan dnia: P0, priorytet, potem nowsze rekrutacje (W8). Rekrutacje bez
    rekrutera czekają w ``no_team`` na pierwsze przypisanie (P12)."""
    from app.services import review_batch

    ordered = await _jobs_by_priority(db, now)
    teams = await review_batch.recruiter_ids_for_jobs(db, ordered)
    staffed = [job_id for job_id in ordered if teams.get(job_id)]
    return {
        "day": today,
        "pending": staffed,
        "rest": staffed,
        "no_team": [job_id for job_id in ordered if not teams.get(job_id)],
    }


async def _withdraw_stale(job_ids: list[int], now: datetime) -> None:
    """Pierwszy rekruter w rekrutacji: stare karty od systemu schodzą, żeby
    nie zaczynał od kart sprzed tygodni (P12). Tylko nietknięte."""
    from app.core.database import AsyncSessionLocal
    from app.services import autofill_withdraw

    for job_id in job_ids:
        async with AsyncSessionLocal() as db:
            try:
                planned = await autofill_withdraw.plan_batch_reset(
                    db, now=now, job_ids=[job_id]
                )
                await autofill_withdraw.apply(
                    db,
                    planned,
                    reason=autofill_withdraw.BATCH_RESET_REASON,
                    check_batch_reset=True,
                )
                await db.commit()
            except Exception as exc:  # noqa: BLE001 — dokładka porcji idzie mimo to
                await db.rollback()
                logger.warning(
                    "[review_batch] withdraw job=%s failed: %s",
                    job_id,
                    type(exc).__name__,
                )


async def _fill_round(
    job_ids: list[int],
    *,
    now: datetime,
    budget: int,
    cap: Optional[int],
    filled: dict[int, int],
    batch: bool = True,
    swap: Collection[int] = (),
) -> tuple[set[int], Optional[int], int]:
    """Jedna runda dopełniania. Zwraca: obsłużone, przerwaną limitem, budżet."""
    from app.core.database import AsyncSessionLocal

    done: set[int] = set()
    cut_short: Optional[int] = None
    for job_id in job_ids:
        if budget <= 0:
            break
        done.add(job_id)
        limit = budget if cap is None else min(budget, cap)
        async with AsyncSessionLocal() as db:
            try:
                added = await fill_job(
                    db,
                    job_id,
                    now=now,
                    limit=limit,
                    batch=batch,
                    swap=job_id in swap,
                )
                await db.commit()
            except Exception as exc:  # noqa: BLE001 — jedna rekrutacja nie blokuje reszty
                await db.rollback()
                logger.warning(
                    "[review_batch] job=%s failed: %s", job_id, type(exc).__name__
                )
                continue
        if added:
            filled[job_id] = filled.get(job_id, 0) + len(added)
            budget -= len(added)
            if budget <= 0:
                cut_short = job_id
    return done, cut_short, budget


async def _batch_tick(now: datetime) -> dict:
    """Porcja dnia: jeden przebieg dziennie po rekrutacjach w pracy, bez
    dopełniania po każdym ruchu karty. Postęp przebiegu siedzi w
    ``app_settings[BATCH_DAY_KEY]``, więc restart w ciągu dnia nie dokłada
    drugiej porcji w miejsce kart, o których już zdecydowano.

    Dwie rundy (W8): najpierw każda rekrutacja dostaje do ``FIRST_ROUND_CARDS``
    osób, potem resztę. Bezpiecznik dodań na tick zostaje, więc przy 100 na tick
    i ponad 20 rekrutacjach pierwsza runda trwa kilka ticków."""
    from app.core.database import AsyncSessionLocal
    from app.models.app_setting import AppSetting
    from app.services import review_batch, review_batch_levels

    today = business_today().isoformat()
    staffed: list[int] = []
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, BATCH_DAY_KEY)
        state = row.value if row is not None and isinstance(row.value, dict) else {}
        if state.get("day") != today:
            await review_batch_levels.roll_levels(db, now=now)
            state = await _day_plan(db, today, now)
            if row is None:
                db.add(AppSetting(key=BATCH_DAY_KEY, value=state))
            else:
                row.value = state
            await db.commit()
        waiting = [int(j) for j in state.get("no_team") or []]
        if waiting:
            teams = await review_batch.recruiter_ids_for_jobs(db, waiting)
            staffed = [j for j in waiting if teams.get(j)]
        if staffed:
            state = {
                "day": today,
                "pending": [*staffed, *(state.get("pending") or [])],
                "rest": [*staffed, *(state.get("rest") or [])],
                "no_team": [j for j in waiting if j not in staffed],
            }
            row = await db.get(AppSetting, BATCH_DAY_KEY)
            if row is not None:
                row.value = state
            await db.commit()
    if staffed:
        await _withdraw_stale(staffed, now)
    first = [int(j) for j in state.get("pending") or []]
    rest = [int(j) for j in state.get("rest") or []]
    if not first and not rest:
        # Rekrutacja założona w ciągu dnia dostaje porcję zaraz po pierwszym
        # przeglądzie (R6), a nie dopiero jutro rano.
        async with AsyncSessionLocal() as db:
            rest = await _jobs_without_batch(db)
        if not rest:
            return {
                "pass": "batch",
                "day": today,
                "jobs": 0,
                "pending": 0,
                "filled": {},
            }
    filled: dict[int, int] = {}
    done_first, cut_first, budget = await _fill_round(
        first,
        now=now,
        budget=_budget(),
        cap=review_batch.FIRST_ROUND_CARDS,
        filled=filled,
    )
    left_first = [j for j in first if j not in done_first or j == cut_first]
    done_rest: set[int] = set()
    cut_rest: Optional[int] = None
    # Reszta dopiero, gdy każda rekrutacja dostała swoje pierwsze osoby.
    if not left_first:
        done_rest, cut_rest, budget = await _fill_round(
            rest, now=now, budget=budget, cap=None, filled=filled
        )
    left_rest = [j for j in rest if j not in done_rest or j == cut_rest]
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, BATCH_DAY_KEY)
        if row is not None:
            row.value = {
                "day": today,
                "pending": left_first,
                "rest": left_rest,
                "no_team": [int(j) for j in state.get("no_team") or []],
            }
            await db.commit()
    return {
        "pass": "batch",
        "day": today,
        "jobs": len(done_first | done_rest),
        "pending": len(set(left_first) | set(left_rest)),
        "filled": filled,
    }


# ── Poranny przebieg wg tempa (08.11.2026) ──────────────────────────────────

TEMPO_DAY_KEY = "new_column_tempo_day"


async def _tempo_tick(now: datetime) -> dict:
    """Raz dziennie wszystkie rekrutacje w pracy z miejscem dla świeżych, potem
    co tick tylko gorące, nowe i P0 po ruchu karty. Postęp w
    ``app_settings[TEMPO_DAY_KEY]``, więc restart nie zaczyna przebiegu od nowa."""
    from app.core.database import AsyncSessionLocal
    from app.models.app_setting import AppSetting

    today = business_today().isoformat()
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, TEMPO_DAY_KEY)
        state = row.value if row is not None and isinstance(row.value, dict) else {}
        if state.get("day") != today:
            state = {"day": today, "pending": await _jobs_by_priority(db, now)}
            if row is None:
                db.add(AppSetting(key=TEMPO_DAY_KEY, value=state))
            else:
                row.value = state
            await db.commit()
        pending = [int(j) for j in state.get("pending") or []]
        touched = await _jobs_touched_since(db, _state.last_tick or now)
        tempo = await tempo_for_jobs(db, touched, now)
        hot = [j for j in touched if j in tempo and tempo[j].refills_during_day]
        # Rekrutacja założona w ciągu dnia dostaje karty po pierwszym
        # przeglądzie, a nie dopiero następnego ranka.
        first_cards = [] if pending else await _jobs_without_batch(db, need_team=False)
    _state.last_tick = now
    filled: dict[int, int] = {}
    done, cut_short, _ = await _fill_round(
        list(dict.fromkeys([*hot, *pending, *first_cards])),
        now=now,
        budget=_budget(),
        cap=None,
        filled=filled,
        batch=False,
        swap=pending,
    )
    left = [j for j in pending if j not in done or j == cut_short]
    if left != pending:
        async with AsyncSessionLocal() as db:
            row = await db.get(AppSetting, TEMPO_DAY_KEY)
            if row is not None:
                row.value = {"day": today, "pending": left}
                await db.commit()
    return {
        "pass": "tempo",
        "day": today,
        "jobs": len(done),
        "pending": len(left),
        "filled": filled,
    }


async def _jobs_without_batch(db, *, need_team: bool = True) -> list[int]:
    """Rekrutacje z ostatnich 2 dni, w pracy, z pulą i rekruterem, które nie
    dostały jeszcze żadnej karty od systemu (po pierwszym przeglądzie w dzień)."""
    from app.models.recruitment_process import RecruitmentProcess
    from app.services import review_batch

    rows = await db.execute(
        select(Job.id)
        .where(
            Job.created_at >= datetime.now(timezone.utc) - timedelta(days=2),
            Job.status == JobStatus.published,
            Job.work_state.in_(IN_WORK_STATES),
            select(JobAutofillPool.job_id)
            .where(JobAutofillPool.job_id == Job.id)
            .exists(),
            ~select(RecruitmentProcess.id)
            .where(
                RecruitmentProcess.job_id == Job.id,
                RecruitmentProcess.entry_source == candidate_claim.ENTRY_SYSTEM,
            )
            .exists(),
        )
        .order_by(Job.id)
    )
    ids = [int(job_id) for (job_id,) in rows.all()]
    if not need_team:
        return ids
    teams = await review_batch.recruiter_ids_for_jobs(db, ids) if ids else {}
    return [job_id for job_id in ids if teams.get(job_id)]
