"""Automatyczny pełny przegląd bazy dla rekrutacji (21.09.2026).

Rekruter nie musi klikać „Szukaj w całej bazie": po publikacji rekrutacji albo
istotnej zmianie wymagań/budżetu system w NOCY uruchamia ten sam trwały przegląd
co ręczny (`candidate_search_runs`), a najlepsze wyniki odkłada do skrzynki
„Propozycje" (`job_proposals`, źródło `full_base`). Nic nie wchodzi do
pipeline'u i nic nie wychodzi na zewnątrz bez kliknięcia człowieka.

Reguły, które łatwo cofnąć „przy okazji":

* Sygnałem jest zdarzenie rekrutacji w `candidate_match_outbox` (to samo, które
  zasila auto-match nowych CV) NOWSZE niż ostatni przegląd automatyczny tej
  rekrutacji — nie „każda opublikowana rekrutacja". Przegląd to ~100–130 MB
  wierszy wyników; przemiatanie wszystkich otwartych rekrutacji co noc
  zapchałoby wolumen bazy.
* Najwyżej JEDEN przegląd automatyczny na rekrutację na noc (także nieudany —
  awaria nie może zapętlić się w oknie) i `AUTO_FULL_REVIEW_MAX_PER_NIGHT`
  łącznie. Odcisk requestu równy ostatniemu UDANEMU przeglądowi automatycznemu
  = pominięcie (zmiana nie dotknęła niczego, co wpływa na ranking).
* Automat USTĘPUJE ludziom: nie startuje, gdy jakikolwiek przegląd jest
  w kolejce albo w toku (worker jest jeden, w procesie web), a kolejka i tak
  bierze ręczne przeglądy pierwsze.
* `version_trace.origin = "auto"` (patrz `candidate_search_store`): nie zajmuje
  slotu autora, nie jest chroniony przez retencję, czyta go każdy z dostępem do
  rekrutacji, a profil punktacji jest BEZ użytkownika (globalny/klienta), więc
  wynik jest wspólny dla zespołu.
* Publikacja propozycji dzieje się w transakcji kończącej przegląd, w
  savepoincie; jej awaria nigdy nie psuje przeglądu. `reconcile_unpublished`
  domyka przeglądy, którym publikacja się nie udała.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import DateTime, case, exists, func, or_, select

from app.core.config import settings
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_auto_match import CandidateMatchOutbox
from app.models.candidate_search_run import CandidateSearchResult, CandidateSearchRun
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.user import User
from app.services import candidate_search_store as store
from app.services.auto_match_rules import is_good_match
from app.services.request_work_state import IN_WORK_STATES

logger = logging.getLogger(__name__)

ACTIVITY_ENTITY = "job_automation"
PROPOSALS_METRIC = "auto_proposals"
# Przegląd bez wektora zapytania (Voyage milczał): nic nie zostało zmierzone,
# więc to awaria automatu, nie wynik (runda 6 audytu). Ustawia `_publish`,
# czytają `_last_auto_run_at` i `_last_successful_fingerprint`.
SEMANTIC_BLIND_METRIC = "auto_semantic_blind"
_PICK_LIMIT = 50
_RECONCILE_WINDOW = timedelta(days=2)


def enabled() -> bool:
    return bool(getattr(settings, "AUTO_FULL_REVIEW_ENABLED", False))


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.BUSINESS_TZ)


def _hours() -> tuple[int, int]:
    start = int(settings.AUTO_FULL_REVIEW_WINDOW_START_HOUR) % 24
    end = int(settings.AUTO_FULL_REVIEW_WINDOW_END_HOUR) % 24
    return start, end


def in_window(now: datetime) -> bool:
    """Półotwarte okno [start, end) w `BUSINESS_TZ`; równe godziny = zamknięte."""
    start, end = _hours()
    hour = now.astimezone(_tz()).hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def night_start(now: datetime) -> datetime:
    """Początek bieżącego okna (UTC) — granica „tej nocy" dla limitów."""
    start, _end = _hours()
    local = now.astimezone(_tz())
    day = local.date()
    if local.hour < start:
        day -= timedelta(days=1)
    return datetime.combine(day, time(hour=start), tzinfo=_tz()).astimezone(
        timezone.utc
    )


# ── Wybór rekrutacji ────────────────────────────────────────────────────────


def _finished_review_started_at():
    """Start ostatniego przeglądu z wpisu „Praca w tle” (``_publish``).

    Retencja kasuje przeglądy automatyczne po 2 dniach, a zdarzenie żyje
    14 dni — bez tego śladu rekrutacja wracała do kolejki co 2 noce i zjadała
    nocny limit nowym (runda 6 audytu). Wpis sprzed tej zmiany nie ma
    ``run_created_at`` — wtedy chwila wpisu.
    """
    return (
        select(
            func.max(
                func.coalesce(
                    Activity.details["run_created_at"].astext.cast(
                        DateTime(timezone=True)
                    ),
                    Activity.created_at,
                )
            )
        )
        .where(
            Activity.entity_type == ACTIVITY_ENTITY,
            Activity.entity_id == Job.id,
            Activity.action == "auto_full_review_finished",
        )
        .correlate(Job)
        .scalar_subquery()
    )


def _last_auto_run_at():
    """Ostatni przegląd automatyczny, który się NIE wywrócił.

    Przegląd ``failed`` nie zamyka tematu: tej nocy chroni go ``ran_tonight``,
    następnej nocy rekrutacja wraca (runda 6 audytu)."""
    live_run = (
        select(func.max(CandidateSearchRun.created_at))
        .where(
            CandidateSearchRun.job_id == Job.id,
            store.auto_origin_clause(),
            CandidateSearchRun.state != "failed",
            # Przegląd bez wektora nie zamyka tematu — jak `failed`.
            ~CandidateSearchRun.metrics.has_key(SEMANTIC_BLIND_METRIC),
        )
        .correlate(Job)
        .scalar_subquery()
    )
    return func.greatest(live_run, _finished_review_started_at())


async def pending_job_ids(db, *, now: datetime, limit: int = _PICK_LIMIT) -> list[int]:
    """Opublikowane rekrutacje ze zdarzeniem nowszym niż ostatni auto-przegląd."""
    lookback = now - timedelta(
        days=max(1, int(settings.AUTO_FULL_REVIEW_EVENT_LOOKBACK_DAYS))
    )
    tonight = night_start(now)
    event_at = (
        select(func.max(CandidateMatchOutbox.created_at))
        .where(
            CandidateMatchOutbox.job_id == Job.id,
            CandidateMatchOutbox.created_at >= lookback,
        )
        .correlate(Job)
        .scalar_subquery()
    )
    ran_tonight = exists(
        select(CandidateSearchRun.id).where(
            CandidateSearchRun.job_id == Job.id,
            store.auto_origin_clause(),
            CandidateSearchRun.created_at >= tonight,
        )
    )
    last_auto = _last_auto_run_at()
    rows = await db.execute(
        select(Job.id)
        .where(
            Job.status == JobStatus.published,
            # 0371: „Klient milczy” i „Zakończony” to requesty, nad którymi
            # nikt nie pracuje — nocny limit przeglądów idzie na te w pracy.
            Job.work_state.in_(IN_WORK_STATES),
            or_(Job.recruiter_id.is_not(None), Job.tac_id.is_not(None)),
            event_at.is_not(None),
            or_(last_auto.is_(None), event_at > last_auto),
            ~ran_tonight,
        )
        # „Szukamy kandydatów” pierwsze: od liczby pasujących w bazie zależy,
        # czy automat przydziału da rekrutera, czy wystarczy sourcer.
        .order_by(case((Job.work_state == "searching", 0), else_=1), event_at, Job.id)
        .limit(limit)
    )
    return [int(job_id) for (job_id,) in rows.all()]


async def _author_id(db, job: Job) -> Optional[int]:
    wanted = [uid for uid in (job.recruiter_id, job.tac_id) if uid]
    if not wanted:
        return None
    active = set(
        (
            await db.scalars(
                select(User.id).where(User.id.in_(wanted), User.is_active.is_(True))
            )
        ).all()
    )
    # Właściciel nieaktywny (konta odtwarzane przez sync Traffita) nie blokuje
    # przeglądu: wynik i tak jest wspólny, autor to tylko wymagany klucz obcy.
    return next((uid for uid in wanted if uid in active), wanted[0])


async def _last_successful_fingerprint(db, job_id: int) -> Optional[str]:
    fingerprint = await db.scalar(
        select(CandidateSearchRun.request_fingerprint)
        .where(
            CandidateSearchRun.job_id == job_id,
            store.auto_origin_clause(),
            CandidateSearchRun.state.in_((*store.ACTIVE_STATES, *store.RESULT_STATES)),
            # Odcisk przeglądu bez wektora nie jest „bez zmian” — trzeba go
            # powtórzyć (runda 6 audytu).
            ~CandidateSearchRun.metrics.has_key(SEMANTIC_BLIND_METRIC),
        )
        .order_by(CandidateSearchRun.created_at.desc())
        .limit(1)
    )
    if fingerprint is not None:
        return fingerprint
    # Przegląd skasowany przez retencję: odcisk zostaje we wpisie „Praca w tle”.
    return await db.scalar(
        select(Activity.details["fingerprint"].astext)
        .where(
            Activity.entity_type == ACTIVITY_ENTITY,
            Activity.entity_id == job_id,
            Activity.action == "auto_full_review_finished",
            Activity.details["fingerprint"].astext.is_not(None),
        )
        .order_by(Activity.created_at.desc())
        .limit(1)
    )


async def start_for_job(db, job_id: int) -> tuple[Optional[str], str]:
    """Załóż przegląd automatyczny. Zwraca (run_id | None, powód). Bez commitu."""
    from fastapi import HTTPException

    from app.services.champion_intake import enforce_operation
    from app.services.request_matching_context import build_request_context
    from app.services.scoring_service import resolve_active_profile
    from app.services.search_eligibility_freshness import eligibility_fingerprint

    job = await db.get(Job, job_id)
    if job is None or job.status != JobStatus.published:
        return None, "job_not_published"
    author_id = await _author_id(db, job)
    if author_id is None:
        return None, "no_owner"
    if job.client_id is None or await db.get(Client, job.client_id) is None:
        return None, "no_client"
    try:
        enforce_operation(job, "search")
    except HTTPException:
        return None, "champion_gate"
    # Profil BEZ użytkownika: wynik ma być wspólny dla zespołu.
    profile = await resolve_active_profile(db, user_id=None, client_id=job.client_id)
    context = build_request_context(job, profile)
    if await _last_successful_fingerprint(db, job_id) == context.fingerprint:
        return None, "unchanged"
    run = await store.create_run(
        db,
        actor_id=author_id,
        client_id=job.client_id,
        job_id=job_id,
        request_fingerprint=context.fingerprint,
        request_context=context.as_dict(),
        version_trace={
            **context.versions,
            "eligibility_fingerprint": await eligibility_fingerprint(db, job=job),
            store.ORIGIN_KEY: store.ORIGIN_AUTO,
        },
    )
    return run.id, "started"


async def _search_busy(db) -> bool:
    """Ustąp ludziom (i sobie): worker jest jeden, w procesie web."""
    return bool(
        await db.scalar(
            select(func.count())
            .select_from(CandidateSearchRun)
            .where(CandidateSearchRun.state.in_(store.ACTIVE_STATES))
        )
    )


async def _started_since(db, since: datetime) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(CandidateSearchRun)
            .where(
                store.auto_origin_clause(),
                CandidateSearchRun.created_at >= since,
            )
        )
        or 0
    )


async def _record_start_failure(db, job_id: int, code: str) -> None:
    """Wpis w „Pracy w tle" + licznik serii awarii. Nigdy nie rzuca."""
    from app.services import automation_failures as failures

    try:
        await failures.record_job_failure_event(
            db, job_id=job_id, action="auto_full_review_failed", error_code=code
        )
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
    await failures.record_failure(failures.KIND_FULL_REVIEW, code, job_id=job_id)


# Rekrutacje pominięte tej nocy (np. `unchanged`) — żeby każdy tick nie liczył
# ich odcisku od nowa. Pamięć procesu wystarcza: restart najwyżej powtórzy tanie
# sprawdzenie.
_skipped_tonight: dict[int, datetime] = {}


async def tick(*, now: Optional[datetime] = None) -> dict:
    """Jeden krok pętli: co najwyżej JEDEN nowy przegląd. Nigdy nie rzuca dalej
    niż do pętli (która łapie wszystko)."""
    from app.core.database import AsyncSessionLocal

    now = now or datetime.now(timezone.utc)
    if not enabled():
        return {"skipped": "disabled"}
    async with AsyncSessionLocal() as db:
        published = await reconcile_unpublished(db, now=now)
        await db.commit()
    if not in_window(now):
        return {"skipped": "outside_window", "reconciled": published}
    tonight = night_start(now)
    for job_id, at in list(_skipped_tonight.items()):
        if at < tonight:
            _skipped_tonight.pop(job_id, None)
    async with AsyncSessionLocal() as db:
        if await _search_busy(db):
            return {"skipped": "search_active", "reconciled": published}
        started_tonight = await _started_since(db, tonight)
        cap = max(0, int(settings.AUTO_FULL_REVIEW_MAX_PER_NIGHT))
        if started_tonight >= cap:
            return {"skipped": "night_cap", "reconciled": published}
        for job_id in await pending_job_ids(db, now=now):
            if job_id in _skipped_tonight:
                continue
            try:
                run_id, reason = await start_for_job(db, job_id)
            except Exception as exc:  # noqa: BLE001 — jedna rekrutacja nie blokuje nocy
                await db.rollback()
                _skipped_tonight[job_id] = now
                await _record_start_failure(db, job_id, type(exc).__name__)
                continue
            if run_id is None:
                await db.rollback()
                _skipped_tonight[job_id] = now
                logger.info("[auto_full_review] job=%s skipped: %s", job_id, reason)
                continue
            await db.commit()
            logger.info("[auto_full_review] job=%s run=%s started", job_id, run_id)
            return {"started": run_id, "job_id": job_id, "reconciled": published}
    return {"skipped": "nothing_due", "reconciled": published}


# ── Publikacja propozycji ───────────────────────────────────────────────────


def _requirement_names(requirements, *, met: bool) -> list[str]:
    out = []
    for item in requirements or []:
        if not isinstance(item, dict) or item.get("level") != "must":
            continue
        if (item.get("status") == "met") != met:
            continue
        names = item.get("any_of") or ([item.get("name")] if item.get("name") else [])
        label = " lub ".join(str(n) for n in names if n)
        if label:
            out.append(label)
    return out


async def publish_run_proposals(db, run: CandidateSearchRun) -> int:
    """Top-K wyników przeglądu → `job_proposals` (źródło `full_base`). Bez commitu."""
    from app.services.auto_match_outbox import candidate_revision
    from app.services.job_proposals import upsert_proposals

    if run.job_id is None:
        return 0
    # Rekrutacja zamknięta albo już nie w pracy (np. „Klient milczy”,
    # „Zakończony”) nie dostaje nowych propozycji — także z zaległej
    # publikacji `reconcile_unpublished` (runda 6 audytu).
    job = await db.get(Job, run.job_id)
    if (
        job is None
        or job.status != JobStatus.published
        or job.work_state not in IN_WORK_STATES
    ):
        return 0
    top_k = max(1, int(settings.AUTO_FULL_REVIEW_TOP_K))
    min_score = float(settings.AUTO_FULL_REVIEW_MIN_SCORE)
    rows = (
        (
            await db.execute(
                select(CandidateSearchResult)
                .where(
                    CandidateSearchResult.run_id == run.id,
                    CandidateSearchResult.state == "evaluated",
                    CandidateSearchResult.eligible.is_(True),
                    # Wynik bez zmierzonej semantyki nie jest rankingiem.
                    CandidateSearchResult.measurement == "measured",
                    CandidateSearchResult.fit_score >= min_score,
                )
                .order_by(
                    CandidateSearchResult.fit_score.desc(),
                    CandidateSearchResult.candidate_id,
                )
                # Reguła must-have odsiewa część wierszy — bierzemy zapas.
                .limit(top_k * 3)
            )
        )
        .scalars()
        .all()
    )
    picked = []
    for row in rows:
        requirements = (row.evidence or {}).get("requirements") or []
        rec = {
            "score": float(row.fit_score),
            "status": "published",
            "matching_must": _requirement_names(requirements, met=True),
            "gap_must": _requirement_names(requirements, met=False),
        }
        if not is_good_match(
            rec,
            min_score=min_score,
            require_must=bool(settings.AUTO_MATCH_REQUIRE_MUST),
        ):
            continue
        picked.append((row, rec, requirements))
        if len(picked) >= top_k:
            break
    if not picked:
        return 0
    candidates = {
        c.id: c
        for c in (
            await db.scalars(
                select(Candidate).where(
                    Candidate.id.in_([row.candidate_id for row, _, _ in picked])
                )
            )
        ).all()
    }
    payload = [
        {
            "candidate_id": row.candidate_id,
            "score": rec["score"],
            "cv_revision": candidate_revision(candidates[row.candidate_id]),
            # `sanitize_evidence` przepuszcza wyłącznie nazwy wymagań i liczby.
            "evidence": {
                "requirements": requirements,
                "matched_must": rec["matching_must"],
                "missing_must": rec["gap_must"],
            },
        }
        for row, rec, requirements in picked
        if row.candidate_id in candidates
    ]
    return await upsert_proposals(
        db, run.job_id, payload, source="full_base", run_id=run.id
    )


async def _semantic_blind(db, run: CandidateSearchRun) -> bool:
    """Ktoś dopuszczony, ale NIKT nie zmierzony = przegląd bez wektora zapytania.

    Worker kończy go jako ``partial`` (``vector=None`` → każdy wiersz
    „niezmierzony”), a automat liczył to jak udany przegląd: seria awarii
    Voyage'a nie docierała do admina, a odcisk takiego przeglądu dawał
    następnej nocy ``unchanged`` — rekrutacja zostawała bez propozycji.
    """
    eligible, measured = (
        await db.execute(
            select(
                func.count().filter(CandidateSearchResult.eligible.is_(True)),
                func.count().filter(
                    CandidateSearchResult.eligible.is_(True),
                    CandidateSearchResult.measurement == "measured",
                ),
            ).where(CandidateSearchResult.run_id == run.id)
        )
    ).one()
    return bool(eligible) and not measured


async def _publish(db, run: CandidateSearchRun, *, eligible: Optional[int]) -> int:
    if await _semantic_blind(db, run):
        from app.services import automation_failures as failures

        run.metrics = {
            **(run.metrics or {}),
            PROPOSALS_METRIC: 0,
            SEMANTIC_BLIND_METRIC: True,
        }
        await failures.record_job_failure_event(
            db,
            job_id=run.job_id,
            action="auto_full_review_failed",
            error_code=failures.NO_QUERY_VECTOR,
            run_id=run.id,
        )
        await db.flush()
        return 0
    count = await publish_run_proposals(db, run)
    # Po `finish_run` telemetria już nie nadpisuje `metrics`.
    run.metrics = {**(run.metrics or {}), PROPOSALS_METRIC: count}
    db.add(
        Activity(
            entity_type=ACTIVITY_ENTITY,
            entity_id=run.job_id,
            action="auto_full_review_finished",
            user_id=None,
            details={
                "run_id": run.id,
                "proposals": count,
                "eligible": eligible,
                "state": run.state,
                # Pamięć automatu po retencji przeglądu (runda 6 audytu).
                "run_created_at": run.created_at.isoformat()
                if run.created_at
                else None,
                "fingerprint": run.request_fingerprint,
            },
        )
    )
    await db.flush()
    return count


async def publish_on_finish(db, run_id: str, *, eligible: Optional[int]) -> None:
    """Wołane przez worker tuż po `finish_run`, PRZED jego commitem.

    Savepoint + połknięty wyjątek: awaria publikacji nie może cofnąć ani
    zablokować zakończenia przeglądu (`reconcile_unpublished` spróbuje ponownie).
    """
    try:
        run = await db.get(CandidateSearchRun, run_id)
        if run is None or not store.is_auto_run(run) or run.job_id is None:
            return
        async with db.begin_nested():
            await _publish(db, run, eligible=eligible)
    except Exception as exc:  # noqa: BLE001 — nigdy nie blokuje zakończenia
        from app.services import automation_failures as failures

        # Przegląd się udał, publikacja nie: `reconcile_unpublished` ponowi,
        # ale seria takich awarii ma dotrzeć do admina.
        await failures.record_failure(
            failures.KIND_FULL_REVIEW, f"publish:{type(exc).__name__}"
        )
        return
    from app.services import automation_failures as failures

    if (run.metrics or {}).get(SEMANTIC_BLIND_METRIC):
        await failures.record_failure(
            failures.KIND_FULL_REVIEW, failures.NO_QUERY_VECTOR, job_id=run.job_id
        )
        return
    await failures.record_success(failures.KIND_FULL_REVIEW)


async def reconcile_unpublished(db, *, now: datetime) -> int:
    """Zakończone auto-przeglądy bez znacznika publikacji (awaria savepointu)."""
    runs = (
        (
            await db.scalars(
                select(CandidateSearchRun)
                .join(Job, Job.id == CandidateSearchRun.job_id)
                .where(
                    store.auto_origin_clause(),
                    CandidateSearchRun.job_id.is_not(None),
                    CandidateSearchRun.state.in_(store.RESULT_STATES),
                    CandidateSearchRun.completed_at >= now - _RECONCILE_WINDOW,
                    ~CandidateSearchRun.metrics.has_key(PROPOSALS_METRIC),
                    # Zamknięta / niepracowana rekrutacja nie zajmuje limitu 5
                    # zaległych publikacji (runda 6 audytu).
                    Job.status == JobStatus.published,
                    Job.work_state.in_(IN_WORK_STATES),
                )
                .order_by(CandidateSearchRun.completed_at)
                .limit(5)
            )
        )
        .unique()
        .all()
    )
    done = 0
    for run in runs:
        try:
            async with db.begin_nested():
                await _publish(db, run, eligible=None)
            done += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[auto_full_review] reconcile failed run=%s: %s",
                run.id,
                type(exc).__name__,
            )
    return done
