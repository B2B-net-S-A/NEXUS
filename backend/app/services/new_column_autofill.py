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
  ``candidate_stage_removals``), pominiętych propozycji tej rekrutacji, osób,
  które dziś stoją na „Zatrudniony” gdziekolwiek, oraz każdego, przy kim bramka
  kwalifikacji mówi cokolwiek innego niż „brak przeciwwskazań” (ostrzeżenia
  o konflikcie z klientem zostawiamy człowiekowi). Off-limits u klienta:
  system nie zna odpowiedzi „sam się zgłosił”, więc pomija.
* Reguły z odrzuceń (decyzje Artura 25.10.2026, analiza 34 powodów i 1 557
  osób od systemu): znana „Stawka od” ponad ``BUDGET_HARD_OVER`` nad budżetem
  rekrutacji = nie dodaje (16 z 34 odrzuceń to „za droga” przy stawce, którą
  system znał; wśród osób wysłanych przez zespół takich jest 1,5%), do 25% nad
  budżetem = za osobami w budżecie i z nieznaną stawką. Osoba, która według
  CV albo LinkedIna pracuje teraz u klienta tej rekrutacji, nie wchodzi —
  także przy wpisie CV bez dat (``client_off_limits.find_hit``
  z ``undated_counts``).
* Wejście ``entry_source = "system"``, ``moved_by`` puste (dodał nie
  człowiek), ``entry_meta`` = migawka tego, co system wiedział: wynik,
  wymagania, „Stawka od”, dostępność. Z niej raport odróżnia błąd
  wyszukiwania od braku danych. Propozycji nie zamyka (``added`` stawia
  człowiek, 07.10.2026) — lista propozycji i tak pomija osoby w rekrutacji.
* Wpis „Praca w tle” (``job_automation``) po każdym dopełnieniu.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, union_all

from app.core.config import settings
from app.core.scheduling import is_business_day
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_stage_removal import CandidateStageRemoval
from app.models.job import Job, JobStatus
from app.models.job_autofill_pool import JobAutofillPool
from app.models.job_proposal import JobProposal
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage
from app.services import candidate_claim
from app.services.board_stage_badges import board_column_for
from app.services.pipeline_latest import current_hired_stage_clause, latest_stage_ids
from app.services.request_work_state import IN_WORK_STATES

logger = logging.getLogger(__name__)

TARGET = 20
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
# Stawka ponad tyle nad budżetem = system nie dodaje (25.10.2026).
BUDGET_HARD_OVER = Decimal("0.25")
# „Stawka od” poniżej tej kwoty to błąd odczytu (na produkcji 0,6 zł/h), nie
# stawka — liczy się jak nieznana.
_MIN_PLAUSIBLE_RATE = Decimal("20")


def enabled() -> bool:
    return bool(getattr(settings, "NEW_COLUMN_AUTOFILL_ENABLED", False))


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


# ── Kogo dodać ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Pick:
    candidate_id: int
    score: float
    run_id: Optional[str]
    matched_must: tuple[str, ...]
    missing_must: tuple[str, ...]


def _names(evidence: Optional[dict], key: str) -> tuple[str, ...]:
    values = (evidence or {}).get(key) or []
    return tuple(str(v) for v in values if isinstance(v, str) and v)


async def ranked_picks(db, job_id: int, *, limit: int) -> list[Pick]:
    """Najlepsi z puli i otwartych propozycji, bez osób, których system nie
    dodaje (patrz docstring modułu, poza bramką kwalifikacji)."""
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
    dismissed = select(JobProposal.candidate_id).where(
        JobProposal.job_id == job_id, JobProposal.status == "dismissed"
    )
    hired_now = select(CandidateStage.candidate_id).where(current_hired_stage_clause())
    rows = (
        await db.execute(
            select(both.c.candidate_id, both.c.score, both.c.run_id, both.c.evidence)
            .where(
                both.c.candidate_id.not_in(ever_in_job),
                both.c.candidate_id.not_in(removed),
                both.c.candidate_id.not_in(dismissed),
                both.c.candidate_id.not_in(hired_now),
            )
            .order_by(both.c.score.desc(), both.c.candidate_id)
        )
    ).all()
    picks: dict[int, Pick] = {}
    for candidate_id, score, run_id, evidence in rows:
        if candidate_id in picks:
            continue  # wiersze idą od najlepszego wyniku — pierwszy wygrywa
        evidence = evidence or {}
        picks[candidate_id] = Pick(
            candidate_id=int(candidate_id),
            score=float(score),
            run_id=run_id,
            matched_must=_names(evidence, "matched_must"),
            missing_must=_names(evidence, "missing_must"),
        )
        if len(picks) >= limit:
            break
    return list(picks.values())


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


async def _by_rules(db, job: Job, picks: list[Pick]) -> list[Pick]:
    """Reguły z odrzuceń: bez osób daleko ponad budżetem i pracujących teraz
    u klienta; osoby trochę ponad budżetem za resztą (kolejność wyniku
    w obrębie poziomu zostaje). Czyta tylko potrzebne kolumny — okno ma do
    ``_RULES_WINDOW`` osób, a pełny wiersz kandydata niesie tekst CV."""
    from types import SimpleNamespace

    from app.services import client_off_limits
    from app.services.candidate_rate_from import (
        effective_currency_sql,
        effective_rate_sql,
    )
    from app.services.dealbreaker_filters import resolve_job_budget_hourly

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
    )
    people = {
        row.id: SimpleNamespace(**row._mapping)
        for row in (
            await db.execute(
                select(*columns).where(
                    Candidate.id.in_([p.candidate_id for p in picks])
                )
            )
        ).all()
    }
    budget = resolve_job_budget_hourly(job)
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
        tiered.append((tier, pick))
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
    return {
        "kind": ENTRY_KIND,
        "score": round(pick.score, 2),
        "run_id": pick.run_id,
        "matched_must": list(pick.matched_must),
        "missing_must": list(pick.missing_must),
        "rate_from_hourly": float(rate) if rate is not None else None,
        "rate_currency": currency if rate is not None else None,
        "availability_date": availability.isoformat() if availability else None,
        "availability_status": getattr(status, "value", status),
    }


# ── Dopełnienie jednej rekrutacji ───────────────────────────────────────────


async def fill_job(
    db, job_id: int, *, now: datetime, limit: Optional[int] = None
) -> list[int]:
    """Dopełnij „Nowych” do ``TARGET`` (najwyżej ``limit`` osób naraz).
    Zwraca id dodanych osób. Bez commitu."""
    from app.api.proposals_bulk import add_candidates_to_job

    job = await db.get(Job, job_id)
    if (
        job is None
        or job.status != JobStatus.published
        or job.work_state not in IN_WORK_STATES
    ):
        return []
    have = (await new_column_counts(db, [job_id])).get(job_id, 0)
    missing = TARGET - have
    if limit is not None:
        missing = min(missing, limit)
    if missing <= 0:
        return []
    picks = await _by_rules(
        db, job, await ranked_picks(db, job_id, limit=_RULES_WINDOW)
    )
    picks = picks[: missing * _PICK_HEADROOM + 10]
    chosen = (await _allowed(db, job, picks, now))[:missing]
    if not chosen:
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
                    "target": TARGET,
                },
            )
        )
        await db.flush()
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

    now = now or datetime.now(timezone.utc)
    if not enabled():
        return {"skipped": "disabled"}
    if not in_work_hours(now):
        _state.last_tick = None
        return {"skipped": "outside_hours"}
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
