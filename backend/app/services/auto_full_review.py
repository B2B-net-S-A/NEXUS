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
* Od 07.10.2026 (decyzja Artura) publikujemy WSZYSTKIE osoby powyżej progu
  `AUTO_FULL_REVIEW_MIN_SCORE`, które przechodzą `is_good_match` — bez limitu
  liczby (dawne `AUTO_FULL_REVIEW_TOP_K` = 60 nie jest czytane). Propozycje
  `full_base`, których przegląd już nie zaproponował, dostają `expired`
  (`job_proposals.expire_full_base`) — tylko po najnowszym przeglądzie tej
  rekrutacji z wynikami (`_newest_result_run`) i tylko osoby, które ten
  przegląd ocenił (albo spoza jego populacji); osoba bez oceny zostaje.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import DateTime, and_, case, exists, func, or_, select

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
# Przegląd z niepełnym pokryciem (runda 8, R8-N11-3): partia `failed`
# (wyjątek/timeout oceny) albo dopuszczeni bez pomiaru, bo Qdrant chwilowo
# milczał (`unavailable`). Propozycje z reszty publikujemy, ale przegląd NIE
# zamyka tematu — inaczej następnej nocy odcisk dawał `unchanged`, a pominięci
# kandydaci nie trafiali do „Propozycji”, dopóki request się nie zmienił.
INCOMPLETE_METRIC = "auto_incomplete_coverage"
_NOT_A_FINAL_REVIEW = (SEMANTIC_BLIND_METRIC, INCOMPLETE_METRIC)
_PICK_LIMIT = 50
UNCHANGED_MAX_AGE = timedelta(hours=20)
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


# Wpis „odcisk bez zmian” (runda 7, A6): zdarzenie rekrutacji, które nie
# zmieniło requestu (np. „Klient milczy → Szukamy”), nie zapisywało pamięci
# przeglądu, więc rekrutacja wisiała w ``pending_job_ids`` przez całe 14 dni
# i co noc zjadała miejsce w kolejce. Nie trafia do „Pracy w tle” (tam idą
# tylko akcje z ``job_proposals._BACKGROUND_KINDS``).
UNCHANGED_ACTION = "auto_full_review_unchanged"
_REVIEW_MEMORY_ACTIONS = ("auto_full_review_finished", UNCHANGED_ACTION)


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
            Activity.action.in_(_REVIEW_MEMORY_ACTIONS),
            ~Activity.details.has_key(INCOMPLETE_METRIC),
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
            # Przegląd bez wektora albo z niepełnym pokryciem nie zamyka
            # tematu — jak `failed`.
            *(~CandidateSearchRun.metrics.has_key(key) for key in _NOT_A_FINAL_REVIEW),
        )
        .correlate(Job)
        .scalar_subquery()
    )
    return func.greatest(live_run, _finished_review_started_at())


# Klucze `version_trace`, których zmiana zmienia odcisk requestu przeglądu
# (`request_matching_context`), a które da się porównać w SQL. Po zmianie
# któregoś z nich okno propozycji odpowiada 409 „Request zmienił się” do czasu
# nowego przeglądu (audyt 07.10.2026: 15 z 25 nocnych przeglądów pod starą
# wersją reguł).
_REVIEW_VERSION_KEYS = ("must_gate_policy", "must_gate_mode", "ranker_version")


def current_review_versions() -> dict[str, str]:
    """Wersje, pod którymi przegląd policzony DZIŚ dostałby ten sam stempel."""
    from app.services.critical_skills import gate_mode
    from app.services.matching_contracts import current_version_trace
    from app.services.requirement_contract import MUST_GATE_POLICY_VERSION

    return {
        "must_gate_policy": MUST_GATE_POLICY_VERSION,
        "must_gate_mode": gate_mode(),
        "ranker_version": current_version_trace().ranker_version,
    }


def _reviewed_under_older_versions():
    """Ostatni przegląd automatyczny (nie `failed`) ma inną wersję reguł.

    Przegląd bez stempla tych kluczy (sprzed ich wprowadzenia) nie liczy się
    jako nieaktualny — o jego kolejności decyduje wiek, jak dotąd."""
    current = current_review_versions()
    latest = (
        select(CandidateSearchRun.version_trace)
        .where(
            CandidateSearchRun.job_id == Job.id,
            store.auto_origin_clause(),
            CandidateSearchRun.state != "failed",
        )
        .order_by(CandidateSearchRun.created_at.desc())
        .limit(1)
        .correlate(Job)
        .scalar_subquery()
    )
    return or_(
        *(
            and_(
                latest[key].astext.is_not(None),
                latest[key].astext != current[key],
            )
            for key in _REVIEW_VERSION_KEYS
        )
    )


async def pending_job_ids(db, *, now: datetime, limit: int = _PICK_LIMIT) -> list[int]:
    """Opublikowane rekrutacje w pracy, które tej nocy jeszcze nie miały przeglądu.

    Od 30.09.2026 (decyzja Artura) co noc WSZYSTKIE rekrutacje w pracy, nie
    tylko te ze zdarzeniem: nowe CV w bazie nie jest zdarzeniem rekrutacji,
    a do 30.09 propozycje dostawało 5 rekrutacji na noc. Kolejność: najpierw
    zdarzenie nowsze niż ostatni przegląd albo przegląd pod starą wersją reguł
    (07.10.2026), potem „Szukamy”, potem najdawniej przeglądane.
    """
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
    stale_versions = _reviewed_under_older_versions()
    rows = await db.execute(
        select(Job.id)
        .where(
            Job.status == JobStatus.published,
            # 0371: „Klient milczy” i „Zakończony” to requesty, nad którymi
            # nikt nie pracuje — nocny limit przeglądów idzie na te w pracy.
            Job.work_state.in_(IN_WORK_STATES),
            or_(Job.recruiter_id.is_not(None), Job.tac_id.is_not(None)),
            ~ran_tonight,
        )
        # Zdarzenie od ostatniego przeglądu (albo stara wersja reguł) pierwsze,
        # potem „Szukamy kandydatów”,
        # potem najdawniej przeglądane.
        .order_by(
            case(
                (
                    and_(
                        event_at.is_not(None),
                        or_(last_auto.is_(None), event_at > last_auto),
                    ),
                    0,
                ),
                # Przegląd pod starą wersją reguł jest nieczytelny (409) — jak
                # zdarzenie rekrutacji.
                (stale_versions, 0),
                else_=1,
            ),
            case((Job.work_state == "searching", 0), else_=1),
            last_auto.asc().nulls_first(),
            Job.id,
        )
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


async def _last_successful_fingerprint(
    db, job_id: int
) -> tuple[Optional[str], Optional[datetime]]:
    row = (
        await db.execute(
            select(
                CandidateSearchRun.request_fingerprint, CandidateSearchRun.created_at
            )
            .where(
                CandidateSearchRun.job_id == job_id,
                store.auto_origin_clause(),
                CandidateSearchRun.state.in_(
                    (*store.ACTIVE_STATES, *store.RESULT_STATES)
                ),
                # Odcisk przeglądu bez wektora (runda 6) albo z niepełnym
                # pokryciem (runda 8) nie jest „bez zmian” — trzeba go powtórzyć.
                *(
                    ~CandidateSearchRun.metrics.has_key(key)
                    for key in _NOT_A_FINAL_REVIEW
                ),
            )
            .order_by(CandidateSearchRun.created_at.desc())
            .limit(1)
        )
    ).first()
    if row is not None and row[0] is not None:
        return row[0], row[1]
    # Przegląd skasowany przez retencję: odcisk zostaje we wpisie „Praca w tle”.
    row = (
        await db.execute(
            select(Activity.details["fingerprint"].astext, Activity.created_at)
            .where(
                Activity.entity_type == ACTIVITY_ENTITY,
                Activity.entity_id == job_id,
                Activity.action == "auto_full_review_finished",
                Activity.details["fingerprint"].astext.is_not(None),
            )
            .order_by(Activity.created_at.desc())
            .limit(1)
        )
    ).first()
    return (row[0], row[1]) if row is not None else (None, None)


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
    fingerprint, reviewed_at = await _last_successful_fingerprint(db, job_id)
    # „Bez zmian” pomija przegląd tylko przez UNCHANGED_MAX_AGE (30.09.2026):
    # starszy przegląd nie widział CV dodanych od tamtej pory.
    if (
        fingerprint == context.fingerprint
        and reviewed_at is not None
        and datetime.now(timezone.utc) - reviewed_at < UNCHANGED_MAX_AGE
    ):
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


async def _remember_unchanged(db, job_id: int, checked_at: datetime) -> None:
    """Zamknij zdarzenia sprzed ``checked_at`` — request się nie zmienił.

    Nigdy nie rzuca: brak wpisu najwyżej powtórzy tanie sprawdzenie odcisku.
    """
    try:
        db.add(
            Activity(
                entity_type=ACTIVITY_ENTITY,
                entity_id=job_id,
                action=UNCHANGED_ACTION,
                user_id=None,
                details={"run_created_at": checked_at.isoformat()},
            )
        )
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        logger.warning("[auto_full_review] job=%s unchanged memory not saved", job_id)


# Rekrutacje pominięte tej nocy (np. `unchanged`) — żeby każdy tick nie liczył
# ich odcisku od nowa. Pamięć procesu wystarcza: restart najwyżej powtórzy tanie
# sprawdzenie.
_skipped_tonight: dict[int, datetime] = {}
_maintenance_done: set[datetime] = set()
_critical_cache_loaded_at: dict[str, datetime] = {}
_CRITICAL_CACHE_TTL = timedelta(hours=1)


async def _refresh_critical_stats_cache(now: datetime) -> None:
    """Statystyki krytycznych z bazy do pamięci procesu (raz na godzinę).

    Bramka czyta je synchronicznie; bez odświeżenia proces po deployu
    pracowałby na seedzie z badania aż do niedzielnego przeliczenia.
    """
    from app.core.database import AsyncSessionLocal
    from app.services import critical_skills

    loaded = _critical_cache_loaded_at.get("at")
    if loaded is not None and now - loaded < _CRITICAL_CACHE_TTL:
        return
    try:
        async with AsyncSessionLocal() as db:
            await critical_skills.refresh_cache(db)
        _critical_cache_loaded_at["at"] = now
    except Exception as exc:  # noqa: BLE001 — seed zostaje, pętla żyje
        logger.warning(
            "[auto_full_review] critical stats cache: %s", type(exc).__name__
        )


async def _nightly_maintenance(tonight: datetime, now: datetime) -> None:
    """Raz na noc, przed przeglądami (30.09.2026):

    - przeliczenie statystyk umiejętności krytycznych, gdy starsze niż tydzień
      (po nim podpowiedzi mogą się zmienić — odciski przeglądów też);
    - poniedziałkowy skrót propozycji bez decyzji do Delivery Leadów.

    Błąd któregokolwiek nie blokuje przeglądów tej nocy.
    """
    from app.core.database import AsyncSessionLocal
    from app.services import critical_skills
    from app.services.proposals_digest import send_pending_proposals_digest

    if tonight in _maintenance_done:
        return
    _maintenance_done.add(tonight)
    try:
        async with AsyncSessionLocal() as db:
            if await critical_skills.stats_are_stale(db, now=now):
                await critical_skills.recompute_and_store(db)
                _critical_cache_loaded_at["at"] = now
    except Exception as exc:  # noqa: BLE001
        logger.warning("[auto_full_review] critical stats: %s", type(exc).__name__)
    try:
        async with AsyncSessionLocal() as db:
            sent = await send_pending_proposals_digest(db, now)
            await db.commit()
            if sent:
                logger.info("[auto_full_review] proposals digest: %s DL", sent)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[auto_full_review] proposals digest: %s", type(exc).__name__)


async def tick(*, now: Optional[datetime] = None) -> dict:
    """Jeden krok pętli: co najwyżej JEDEN nowy przegląd. Nigdy nie rzuca dalej
    niż do pętli (która łapie wszystko)."""
    from app.core.database import AsyncSessionLocal

    now = now or datetime.now(timezone.utc)
    if not enabled():
        return {"skipped": "disabled"}
    await _refresh_critical_stats_cache(now)
    async with AsyncSessionLocal() as db:
        published = await reconcile_unpublished(db, now=now)
        await db.commit()
    if not in_window(now):
        return {"skipped": "outside_window", "reconciled": published}
    tonight = night_start(now)
    await _nightly_maintenance(tonight, now)
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
            checked_at = datetime.now(timezone.utc)
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
                if reason == "unchanged":
                    await _remember_unchanged(db, job_id, checked_at)
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


# Wiersze przeglądu czytane paczkami: powyżej progu bywa ich kilkaset, a każdy
# niesie dowody wymagań (JSONB).
_PUBLISH_PAGE = 500


async def _job_accepts_proposals(db, job_id: int) -> bool:
    """Rekrutacja opublikowana i w pracy — tylko taka dostaje propozycje."""
    job = await db.get(Job, job_id)
    return (
        job is not None
        and job.status == JobStatus.published
        and job.work_state in IN_WORK_STATES
    )


async def publish_run_proposals(
    db, run: CandidateSearchRun, *, revive_expired: bool = True
) -> int:
    """Wszystkie wyniki przeglądu powyżej progu → `job_proposals` (`full_base`).

    Bez limitu liczby (07.10.2026): każda osoba dopuszczona, zmierzona,
    z wynikiem ≥ `AUTO_FULL_REVIEW_MIN_SCORE` i przechodząca `is_good_match`.
    Paczkami po `_PUBLISH_PAGE` wierszy przeglądu, upsert też paczkami
    (`job_proposals._UPSERT_CHUNK`). Bez commitu.
    """
    from app.services.auto_match_outbox import candidate_revision
    from app.services.job_proposals import upsert_proposals

    if run.job_id is None:
        return 0
    # Rekrutacja zamknięta albo już nie w pracy (np. „Klient milczy”,
    # „Zakończony”) nie dostaje nowych propozycji — także z zaległej
    # publikacji `reconcile_unpublished` (runda 6 audytu).
    if not await _job_accepts_proposals(db, run.job_id):
        return 0
    min_score = float(settings.AUTO_FULL_REVIEW_MIN_SCORE)
    require_must = bool(settings.AUTO_MATCH_REQUIRE_MUST)
    # Znani zespołowi (07.10.2026): punkty historii idą do dowodów i ustawiają
    # kolejność listy; o tym, KTO trafia do propozycji, dalej decyduje próg.
    from app.services.known_people_signal import known_people_for_job

    known = await known_people_for_job(db, await db.get(Job, run.job_id))
    published = 0
    offset = 0
    while True:
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
                    .offset(offset)
                    .limit(_PUBLISH_PAGE)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            break
        offset += len(rows)
        picked = []
        for row in rows:
            requirements = (row.evidence or {}).get("requirements") or []
            rec = {
                "score": float(row.fit_score),
                "status": "published",
                "matching_must": _requirement_names(requirements, met=True),
                "gap_must": _requirement_names(requirements, met=False),
            }
            if not is_good_match(rec, min_score=min_score, require_must=require_must):
                continue
            picked.append((row, rec, requirements))
        if picked:
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
                        **(
                            {"history": known[row.candidate_id].evidence()}
                            if row.candidate_id in known
                            else {}
                        ),
                    },
                }
                for row, rec, requirements in picked
                if row.candidate_id in candidates
            ]
            published += await upsert_proposals(
                db,
                run.job_id,
                payload,
                source="full_base",
                run_id=run.id,
                revive_expired=revive_expired,
            )
        if len(rows) < _PUBLISH_PAGE:
            break
    return published


async def _newest_result_run(db, run: CandidateSearchRun) -> bool:
    """Czy to najnowszy przegląd automatyczny tej rekrutacji z wynikami.

    Nowszy przegląd bez wektora zapytania (``SEMANTIC_BLIND_METRIC``) niczego
    nie opublikował, więc się nie liczy. Nowszy przegląd jeszcze bez publikacji
    — liczy się (opublikuje i wygasi sam). Bez tego zaległa publikacja
    starszego przeglądu (`reconcile_unpublished`) wygaszałaby propozycje
    nowszego.
    """
    if run.job_id is None or run.created_at is None:
        return False
    newer = await db.scalar(
        select(
            exists().where(
                store.auto_origin_clause(),
                CandidateSearchRun.job_id == run.job_id,
                CandidateSearchRun.id != run.id,
                CandidateSearchRun.state.in_(store.RESULT_STATES),
                CandidateSearchRun.created_at > run.created_at,
                ~func.coalesce(
                    CandidateSearchRun.metrics.has_key(SEMANTIC_BLIND_METRIC), False
                ),
            )
        )
    )
    return not newer


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


# Runda 9 (R9-N5-3): ile razy z rzędu przegląd z TYM SAMYM odciskiem może
# skończyć się niepełnym pokryciem, zanim automat uzna temat za zamknięty.
# Pojedynczy wadliwy wektor (``unavailable`` bez awarii wywołania) powtarza się
# co noc identycznie — bez sufitu rekrutacja wracała przez całe okno zdarzeń
# (14 nocy) i zjadała nocny limit.
MAX_INCOMPLETE_REPEATS = 2


async def _incomplete_coverage(db, run: CandidateSearchRun) -> bool:
    """Część populacji nieoceniona przez AWARIĘ: partia `failed` albo `unavailable`.

    `stale`/`missing_index` NIE liczą się — to trwały stan indeksu, który
    następna noc by powtórzyła (przegląd nie zamknąłby się nigdy). Wiersz
    `failed` liczy się tylko przy awarii partii (``run.error_code``): bez niej
    `failed` znaczy, że kandydat zmienił się w trakcie przeglądu (dryf wersji)
    — jego zmiana sama zapisze zdarzenie, a następna noc i tak by go nie
    „dokończyła” (runda 9, R9-N5-3).
    """
    failed, unavailable = (
        await db.execute(
            select(
                func.count().filter(CandidateSearchResult.state == "failed"),
                func.count().filter(
                    CandidateSearchResult.eligible.is_(True),
                    CandidateSearchResult.measurement == "unavailable",
                ),
            ).where(CandidateSearchResult.run_id == run.id)
        )
    ).one()
    return bool((failed and run.error_code) or unavailable)


async def _incomplete_repeats(db, job_id: int, fingerprint: str) -> int:
    """Ile ostatnich przeglądów tej rekrutacji z rzędu było niepełnych z tym odciskiem."""
    rows = (
        await db.scalars(
            select(Activity.details)
            .where(
                Activity.entity_type == ACTIVITY_ENTITY,
                Activity.entity_id == job_id,
                Activity.action == "auto_full_review_finished",
            )
            .order_by(Activity.created_at.desc(), Activity.id.desc())
            .limit(MAX_INCOMPLETE_REPEATS)
        )
    ).all()
    streak = 0
    for details in rows:
        details = details or {}
        if (
            not details.get(INCOMPLETE_METRIC)
            or details.get("incomplete_fingerprint") != fingerprint
        ):
            break
        streak += 1
    return streak


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
    newest = await _newest_result_run(db, run)
    count = await publish_run_proposals(db, run, revive_expired=newest)
    incomplete = await _incomplete_coverage(db, run)
    # Wygaszanie po najnowszym przeglądzie z wynikami w rekrutacji, która
    # przyjmuje propozycje (inaczej publikacja niczego nie zapisała). Pokrycie
    # rozstrzyga `expire_full_base` per osoba: osoby bez oceny zostają, więc
    # niepełny przegląd też porządkuje tych, których ocenił (przegląd #2058).
    expired = 0
    if (
        newest
        and run.job_id is not None
        and await _job_accepts_proposals(db, run.job_id)
    ):
        from app.services.job_proposals import expire_full_base

        expired = await expire_full_base(db, job_id=run.job_id, run_id=run.id)
    # Po `finish_run` telemetria już nie nadpisuje `metrics`.
    metrics = {**(run.metrics or {}), PROPOSALS_METRIC: count}
    details = {
        "run_id": run.id,
        "proposals": count,
        "expired": expired,
        "eligible": eligible,
        "state": run.state,
        # Pamięć automatu po retencji przeglądu (runda 6 audytu).
        "run_created_at": run.created_at.isoformat() if run.created_at else None,
        "fingerprint": run.request_fingerprint,
    }
    if incomplete and run.job_id is not None:
        repeats = await _incomplete_repeats(db, run.job_id, run.request_fingerprint)
        if repeats >= MAX_INCOMPLETE_REPEATS:
            # Ten sam request był już niepełny `repeats` razy z rzędu — kolejna
            # noc nie da innego wyniku, więc przegląd zamyka temat (R9-N5-3).
            incomplete = False
            metrics["auto_incomplete_accepted"] = True
            details["incomplete_accepted"] = True
    if incomplete:
        # Bez odcisku i ze znacznikiem: wpis nie jest pamięcią przeglądu
        # (`_finished_review_started_at`, `_last_successful_fingerprint`).
        # Odcisk zostaje pod innym kluczem — liczy serię niepełnych.
        metrics[INCOMPLETE_METRIC] = True
        details["incomplete_fingerprint"] = details.pop("fingerprint")
        details[INCOMPLETE_METRIC] = True
    run.metrics = metrics
    db.add(
        Activity(
            entity_type=ACTIVITY_ENTITY,
            entity_id=run.job_id,
            action="auto_full_review_finished",
            user_id=None,
            details=details,
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
