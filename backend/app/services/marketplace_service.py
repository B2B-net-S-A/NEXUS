"""Targ kandydatów (Candidate Marketplace) service.

Reverse-match pipeline: nowy projekt → skan puli marketplace → notyfikacje
dla kandydatów ze score >= threshold. Dedup per para (candidate_id, job_id)
przez `marketplace_alert_log` z `uq_marketplace_alert_pair`.

Publiczne API:
- ensure_marketplace_pool(db)           — singleton pool
- auto_sync_marketplace_membership(db)  — pilnuje membership wobec availability
- scan_job_for_marketplace_matches(...) — hot path (per job create / update)
- scan_candidate_for_top_jobs(...)      — UI expansion row: top-K matchów
- is_significant_job_update(old, new)   — pure filter dla triggera edycji
- add_candidate_to_marketplace(...)
- remove_candidate_from_marketplace(...)
- list_marketplace_candidates(...)

Zależy od:
- scoring_service.score_candidate_job  (0-100 scale)
- embedding_service.search_candidates_semantic  (query → Qdrant nexus_candidates)
- embedding_service.search_jobs_semantic        (query → Qdrant nexus_jobs)
- notifications.create_notification             (in-app dispatch)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import AvailabilityStatus, Candidate
from app.models.job import Job, JobStatus
from app.models.marketplace_alert_log import MarketplaceAlertLog
from app.models.notification import NotificationType
from app.models.talent_pool import TalentPool, TalentPoolMembership
from app.models.user import User

logger = logging.getLogger(__name__)


# Kandydat trafia na targ jeśli ma jeden z tych statusów.
_AUTO_ELIGIBLE_STATUSES = (
    AvailabilityStatus.actively_looking,
    AvailabilityStatus.open_to_offers,
)

# Nazwa singletona — stała (nie do edycji z UI).
MARKETPLACE_POOL_NAME = "Targ kandydatów"
MARKETPLACE_POOL_DESC = (
    "Kandydaci aktywnie szukający lub świeżo schodzący z projektu. "
    "AI monitoruje nowe rekrutacje i alertuje o dopasowaniach (score ≥ {threshold}).".format(
        threshold=int(settings.MARKETPLACE_SCORE_THRESHOLD)
    )
)

# Pola, których zmiana uznawana jest za istotną (trigger re-scan targu).
# Subset _EMBED_TRIGGER_FIELDS z api/jobs.py + title (retitling zwykle oznacza
# zmianę scope'u — reagujemy).
_SIGNIFICANT_FIELDS: frozenset[str] = frozenset(
    {
        "must_skills",
        "nice_skills",
        "seniority",
        "subcategory",
        "industry",
        "title",
    }
)


# ───────────────────────────────────────────────────────────────────────────
# Dataclasses (return types)
# ───────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SyncCounters:
    added: int = 0
    removed_status_change: int = 0
    removed_expired: int = 0


@dataclass(frozen=True)
class ScanResult:
    job_id: int
    candidates_scored: int = 0
    matches_found: int = 0  # score >= threshold (w tym ewentualne duplikaty)
    new_alerts: int = 0  # wyłącznie NOWE wpisy w marketplace_alert_log
    latency_ms: float = 0.0
    skipped_reason: Optional[str] = None


@dataclass(frozen=True)
class TopMatch:
    job_id: int
    title: str
    client_id: Optional[int]
    total_score: float
    seniority: Optional[str]
    matching_must: list[str] = field(default_factory=list)
    gap_must: list[str] = field(default_factory=list)


# ───────────────────────────────────────────────────────────────────────────
# Pool management
# ───────────────────────────────────────────────────────────────────────────


async def ensure_marketplace_pool(db: AsyncSession) -> TalentPool:
    """Return the singleton marketplace pool, creating it lazily if missing.

    Partial unique index `ux_talent_pools_marketplace_singleton` gwarantuje,
    że może być tylko JEDEN wiersz z is_marketplace=true. Race handler: jeśli
    drugi task dodaje w tym samym momencie, łapiemy IntegrityError i czytamy
    istniejący rekord.
    """
    result = await db.execute(
        select(TalentPool).where(TalentPool.is_marketplace.is_(True)).limit(1)
    )
    pool = result.scalar_one_or_none()
    if pool is not None:
        return pool

    pool = TalentPool(
        name=MARKETPLACE_POOL_NAME,
        description=MARKETPLACE_POOL_DESC,
        criteria={},
        created_by=None,
        is_marketplace=True,
    )
    db.add(pool)
    try:
        await db.flush()
    except IntegrityError:
        # Race z innym taskiem — ktoś już stworzył singletona.
        await db.rollback()
        result = await db.execute(
            select(TalentPool).where(TalentPool.is_marketplace.is_(True)).limit(1)
        )
        pool = result.scalar_one()
    return pool


async def auto_sync_marketplace_membership(db: AsyncSession) -> SyncCounters:
    """Reconcile marketplace membership with availability + expiry.

    Phase 1 (include): kandydaci z availability_status in AUTO_ELIGIBLE_STATUSES
    którzy nie mają jeszcze wpisu w puli → dodajemy z source_event="auto_availability".

    Phase 2 (exclude):
      - auto-entries, gdzie candidate.availability_status wyszedł z eligible → DELETE
      - manual-entries z marketplace_until < dziś → DELETE

    Nie commituje — caller robi commit (patrz marketplace_sweeper_loop).
    """
    pool = await ensure_marketplace_pool(db)

    # ── Phase 1: include ──────────────────────────────────────────────────
    existing_q = select(TalentPoolMembership.candidate_id).where(
        TalentPoolMembership.talent_pool_id == pool.id
    )
    existing_ids = {row[0] for row in (await db.execute(existing_q)).all()}

    eligible_q = select(Candidate.id).where(
        Candidate.availability_status.in_(_AUTO_ELIGIBLE_STATUSES)
    )
    eligible_ids = {row[0] for row in (await db.execute(eligible_q)).all()}

    to_add = eligible_ids - existing_ids
    added = 0
    for cand_id in to_add:
        db.add(
            TalentPoolMembership(
                talent_pool_id=pool.id,
                candidate_id=cand_id,
                added_by=None,
                source_event="auto_availability",
                source_job_id=None,
                marketplace_until=None,
            )
        )
        added += 1

    # ── Phase 2a: remove auto-entries gdy status wyszedł z eligible ───────
    removed_status = 0
    res = await db.execute(
        select(TalentPoolMembership.id)
        .join(Candidate, Candidate.id == TalentPoolMembership.candidate_id)
        .where(
            TalentPoolMembership.talent_pool_id == pool.id,
            TalentPoolMembership.source_event == "auto_availability",
            Candidate.availability_status.notin_(_AUTO_ELIGIBLE_STATUSES),
        )
    )
    stale_ids = [r[0] for r in res.all()]
    if stale_ids:
        await db.execute(
            delete(TalentPoolMembership).where(TalentPoolMembership.id.in_(stale_ids))
        )
        removed_status = len(stale_ids)

    # ── Phase 2b: remove manual entries po wygaśnięciu ────────────────────
    removed_expired = 0
    today = date.today()
    res = await db.execute(
        select(TalentPoolMembership.id).where(
            TalentPoolMembership.talent_pool_id == pool.id,
            TalentPoolMembership.marketplace_until.is_not(None),
            TalentPoolMembership.marketplace_until < today,
        )
    )
    expired_ids = [r[0] for r in res.all()]
    if expired_ids:
        await db.execute(
            delete(TalentPoolMembership).where(TalentPoolMembership.id.in_(expired_ids))
        )
        removed_expired = len(expired_ids)

    return SyncCounters(
        added=added,
        removed_status_change=removed_status,
        removed_expired=removed_expired,
    )


# ───────────────────────────────────────────────────────────────────────────
# Scan job → marketplace candidates (hot path)
# ───────────────────────────────────────────────────────────────────────────


def _should_scan_job(job: Job) -> Optional[str]:
    """Return a reason string to skip, or None if we should scan."""
    if job.status not in (JobStatus.draft, JobStatus.published):
        # `closed` jobów nie skanujemy.
        return (
            f"status={job.status.value if hasattr(job.status, 'value') else job.status}"
        )
    must = job.must_skills or []
    nice = job.nice_skills or []
    if not must and not nice:
        return "no_skills"
    if not job.embedding_id:
        # Embedding pojawi się później (re-scan z sweepera go złapie).
        return "no_embedding"
    return None


async def _resolve_marketplace_recipients(
    db: AsyncSession,
    *,
    candidate: Candidate,
    job: Job,
) -> tuple[Optional[int], Optional[int], set[int]]:
    """Work out who *would* be notified — read-only, no side effects.

    Returns (notified_candidate_owner_id, notified_job_owner_id, recipient_ids).
    Split out from the actual send so the caller can resolve recipients, claim
    the alert-log row, and only then emit. Deduplikujemy gdy obaj ownerzy to ten
    sam user. Skipujemy inactive userów.
    """
    cand_owner = candidate.created_by
    job_owner = job.recruiter_id

    unique_owners = {oid for oid in (cand_owner, job_owner) if oid is not None}
    if not unique_owners:
        return (None, None, set())

    active_rows = await db.execute(
        select(User.id).where(
            User.id.in_(unique_owners),
            User.is_active.is_(True),
        )
    )
    active_ids = {row[0] for row in active_rows.all()}
    recipients = unique_owners & active_ids

    notified_cand = cand_owner if cand_owner in recipients else None
    notified_job = job_owner if job_owner in recipients else None
    return (notified_cand, notified_job, recipients)


async def _emit_marketplace_notifications(
    db: AsyncSession,
    *,
    candidate: Candidate,
    job: Job,
    score: float,
    recipients: set[int],
) -> None:
    """Create the in-app notification rows for already-resolved recipients.

    Call ONLY after the alert-log claim succeeded — a notification for a pair
    that is already logged is a duplicate alert to a human.
    """
    from app.api.notifications import create_notification

    if not recipients:
        return

    candidate_for_link = f"/candidates/{candidate.id}?job={job.id}"
    title = f"Nowy match: {job.title}"
    score_int = int(round(score))
    message = (
        f"{candidate.name} {candidate.lastname} — score {score_int}/100 "
        f'dopasowanie do nowej rekrutacji „{job.title}".'
    )

    for uid in recipients:
        await create_notification(
            db,
            user_id=uid,
            title=title,
            message=message,
            notification_type=NotificationType.marketplace_match,
            link=candidate_for_link,
            related_entity_type="job",
            related_entity_id=job.id,
            dedupe_resurface=False,
        )


async def _try_insert_alert_log(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    score: float,
    notified_cand: Optional[int],
    notified_job: Optional[int],
) -> bool:
    """INSERT ... ON CONFLICT (candidate_id, job_id) DO NOTHING.

    Returns True if a new row was inserted (fresh alert), False if conflict
    (alert already logged — never re-notify this pair).
    """
    stmt = (
        pg_insert(MarketplaceAlertLog)
        .values(
            candidate_id=candidate_id,
            job_id=job_id,
            score=round(score, 2),
            notified_candidate_owner_id=notified_cand,
            notified_job_owner_id=notified_job,
        )
        .on_conflict_do_nothing(constraint="uq_marketplace_alert_pair")
        .returning(MarketplaceAlertLog.id)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


async def _was_already_alerted(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> bool:
    """Cheap pre-check — pomija scoring dla par już zalogowanych."""
    result = await db.execute(
        select(MarketplaceAlertLog.id).where(
            MarketplaceAlertLog.candidate_id == candidate_id,
            MarketplaceAlertLog.job_id == job_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def scan_job_for_marketplace_matches(
    job_id: int,
    db: AsyncSession,
    *,
    score_threshold: Optional[float] = None,
) -> ScanResult:
    """Scan marketplace pool against a freshly (re-)created job.

    - Wczytuje kandydatów z singletona TalentPool(is_marketplace=true).
    - Qdrant search_candidates_semantic(_build_job_text(job)) → sim_map.
    - Per kandydat: score_candidate_job(...) — early-skip gdy już zalogowany.
    - Score >= threshold: INSERT alert_log ON CONFLICT DO NOTHING → 2 notyfikacje.
    - Nie commituje — caller odpowiada za db.commit() (sweep/BG task).
    """
    from app.services.embedding_service import (
        _build_job_text,
        search_candidates_semantic,
    )
    from app.services.scoring_service import score_candidate_job

    threshold = (
        score_threshold
        if score_threshold is not None
        else settings.MARKETPLACE_SCORE_THRESHOLD
    )
    t0 = time.perf_counter()

    job = await db.get(Job, job_id)
    if job is None:
        return ScanResult(
            job_id=job_id,
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
            skipped_reason="job_not_found",
        )

    skip = _should_scan_job(job)
    if skip is not None:
        logger.info("marketplace_scan skipped job_id=%d reason=%s", job_id, skip)
        return ScanResult(
            job_id=job_id,
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
            skipped_reason=skip,
        )

    pool = await ensure_marketplace_pool(db)

    # Pobieramy kandydatów z puli (pełne obiekty — potrzebne do scoringu).
    members_q = (
        select(TalentPoolMembership)
        .where(TalentPoolMembership.talent_pool_id == pool.id)
        .options(selectinload(TalentPoolMembership.candidate))
    )
    memberships = (await db.execute(members_q)).scalars().all()
    candidates: list[Candidate] = [
        m.candidate for m in memberships if m.candidate is not None
    ]

    if not candidates:
        return ScanResult(
            job_id=job_id,
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
            skipped_reason="empty_pool",
        )

    # Semantic similarity — jedno Qdrant query na cały pool.
    pool_ids = {c.id for c in candidates}
    sim_map: dict[int, float] = {}
    try:
        job_text = _build_job_text(job)
        if job_text:
            # Fetch więcej niż rozmiar puli (ranking po cosine; część hitów
            # może być spoza puli — filtrujemy).
            hits = await search_candidates_semantic(
                query=job_text, top_k=max(50, min(len(candidates) * 2, 500))
            )
            for h in hits:
                cid = h.get("candidate_id")
                score = h.get("score")
                if cid in pool_ids and score is not None:
                    sim_map[int(cid)] = float(score)
    except Exception:
        logger.exception("marketplace_scan: semantic search failed job_id=%d", job_id)

    matches = 0
    new_alerts = 0
    scored = 0
    for cand in candidates:
        # Pre-check: para już w logu → skip całkowicie (no scoring wasted).
        if await _was_already_alerted(db, candidate_id=cand.id, job_id=job.id):
            continue
        try:
            bd = await score_candidate_job(
                cand, job, db, semantic_similarity=sim_map.get(cand.id)
            )
        except Exception:
            logger.exception(
                "marketplace_scan: scoring failed candidate_id=%d job_id=%d",
                cand.id,
                job.id,
            )
            continue
        scored += 1
        if bd.total < threshold:
            continue
        matches += 1

        # Claim the pair BEFORE notifying. Resolving recipients is a read, so
        # it can happen first; emitting is the side effect and must be gated on
        # the claim. The old order notified first and used `inserted` only for a
        # counter — so a pair that another pass had already logged (the cheap
        # `_was_already_alerted` pre-check races with concurrent scans) still
        # got a second round of notifications sent to the same humans.
        notified_cand, notified_job, recipients = await _resolve_marketplace_recipients(
            db, candidate=cand, job=job
        )
        inserted = await _try_insert_alert_log(
            db,
            candidate_id=cand.id,
            job_id=job.id,
            score=bd.total,
            notified_cand=notified_cand,
            notified_job=notified_job,
        )
        if not inserted:
            # Already alerted for this pair — never re-notify.
            continue
        new_alerts += 1
        await _emit_marketplace_notifications(
            db, candidate=cand, job=job, score=bd.total, recipients=recipients
        )

    latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    logger.info(
        "marketplace_scan",
        extra={
            "event": "marketplace_scan",
            "job_id": job.id,
            "pool_size": len(candidates),
            "candidates_scored": scored,
            "matches_found": matches,
            "new_alerts": new_alerts,
            "threshold": threshold,
            "latency_ms": latency_ms,
        },
    )
    return ScanResult(
        job_id=job.id,
        candidates_scored=scored,
        matches_found=matches,
        new_alerts=new_alerts,
        latency_ms=latency_ms,
    )


# ───────────────────────────────────────────────────────────────────────────
# Scan candidate → top jobs (UI expansion row)
# ───────────────────────────────────────────────────────────────────────────


async def scan_candidate_for_top_jobs(
    candidate_id: int,
    db: AsyncSession,
    *,
    top_k: Optional[int] = None,
) -> list[TopMatch]:
    """Top-K otwartych jobów pasujących do kandydata w puli targu.

    Używane przez UI (rozwijany wiersz tabeli `/marketplace`). NIE emituje
    notyfikacji — to pure read-only endpoint. Złączone: Qdrant search_jobs +
    scoring_service.rank_jobs_for_candidate.
    """
    from app.services.embedding_service import (
        _build_candidate_text,
        search_jobs_semantic,
    )
    from app.services.scoring_service import rank_jobs_for_candidate

    k = top_k or settings.MARKETPLACE_TOP_K_MATCHES_PER_CANDIDATE

    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        return []

    cand_text = _build_candidate_text(candidate)
    if not cand_text:
        return []

    # Szeroka pula PRZED filtrem statusu (M3-JOB-01): index jobów w Qdrant ma
    # wszystkie statusy, a większość bazy to closed joby z importu — top-30
    # semantic bywało w całości closed i wiersz „Top oferty" pokazywał pusto,
    # mimo że niżej w rankingu istniały dobre published joby.
    hits = await search_jobs_semantic(
        query=cand_text, top_k=settings.JOB_SEMANTIC_POOL_SIZE
    )
    if not hits:
        return []

    hit_ids = [h["job_id"] for h in hits if h.get("job_id")]
    if not hit_ids:
        return []

    # Filtruj tylko otwarte joby (draft/published — zgodne z _should_scan_job).
    res = await db.execute(
        select(Job).where(
            Job.id.in_(hit_ids),
            Job.status.in_((JobStatus.draft, JobStatus.published)),
        )
    )
    jobs = list(res.scalars().all())
    if not jobs:
        return []

    sim_map = {int(h["job_id"]): float(h["score"]) for h in hits}
    breakdowns = await rank_jobs_for_candidate(
        candidate, jobs, db, similarity_map=sim_map
    )
    top = breakdowns[:k]

    id_to_job = {j.id: j for j in jobs}
    return [
        TopMatch(
            job_id=bd.job_id,
            title=id_to_job[bd.job_id].title,
            client_id=id_to_job[bd.job_id].client_id,
            total_score=round(bd.total, 2),
            seniority=(
                id_to_job[bd.job_id].seniority.value
                if id_to_job[bd.job_id].seniority
                else None
            ),
            matching_must=list(bd.matching_must or []),
            gap_must=list(bd.gap_must or []),
        )
        for bd in top
        if bd.job_id in id_to_job
    ]


# ───────────────────────────────────────────────────────────────────────────
# Diff helper (pure func) for update_job trigger
# ───────────────────────────────────────────────────────────────────────────


def _normalize_skills(bucket: Any) -> frozenset[str]:
    """Porównywanie list skills jako setów nazw (ignoruje ordering + level/years)."""
    if not bucket:
        return frozenset()
    names: list[str] = []
    if isinstance(bucket, list):
        for item in bucket:
            if isinstance(item, dict):
                n = item.get("name")
                if n:
                    names.append(str(n).strip().lower())
            elif isinstance(item, str):
                names.append(item.strip().lower())
    return frozenset(n for n in names if n)


def _normalize_value(field: str, value: Any) -> Any:
    """Znormalizuj surowe wartości (enum.value itp.) do porównania starego/nowego."""
    if value is None:
        return None
    if field in ("must_skills", "nice_skills"):
        return _normalize_skills(value)
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, str):
        return value.strip()
    return value


def is_significant_job_update(
    old_values: Mapping[str, Any], new_values: Mapping[str, Any]
) -> bool:
    """Return True gdy zmiana w polach _SIGNIFICANT_FIELDS ma sens dla scoringu.

    Pure function — bez I/O. Używa _normalize_value aby ignorować trywialne
    różnice typu: zmiana kolejności skills, trailing whitespace, enum vs string.
    """
    for field in _SIGNIFICANT_FIELDS:
        old_raw = old_values.get(field)
        new_raw = new_values.get(field)
        if _normalize_value(field, old_raw) != _normalize_value(field, new_raw):
            return True
    return False


# ───────────────────────────────────────────────────────────────────────────
# Membership management API (for HTTP handlers)
# ───────────────────────────────────────────────────────────────────────────


async def add_candidate_to_marketplace(
    db: AsyncSession,
    *,
    candidate_id: int,
    added_by: Optional[int],
    marketplace_until: Optional[date] = None,
) -> TalentPoolMembership:
    """Ręczny wrzut kandydata na targ ("Wrzuć na targ" na karcie kandydata).

    Jeśli kandydat już jest w puli (auto_availability) → upgradujemy wpis na
    manual i ustawiamy marketplace_until (nadpisujemy source_event, nie tworzymy
    drugiego wpisu).
    """
    pool = await ensure_marketplace_pool(db)

    cand = await db.get(Candidate, candidate_id)
    if cand is None:
        raise ValueError(f"Candidate {candidate_id} not found")

    until = marketplace_until or (
        date.today() + timedelta(days=settings.MARKETPLACE_DEFAULT_DURATION_DAYS)
    )

    existing = await db.execute(
        select(TalentPoolMembership).where(
            TalentPoolMembership.talent_pool_id == pool.id,
            TalentPoolMembership.candidate_id == candidate_id,
        )
    )
    m = existing.scalar_one_or_none()
    if m is not None:
        m.source_event = "manual"
        m.added_by = added_by
        m.marketplace_until = until
        return m

    membership = TalentPoolMembership(
        talent_pool_id=pool.id,
        candidate_id=candidate_id,
        added_by=added_by,
        source_event="manual",
        source_job_id=None,
        marketplace_until=until,
    )
    db.add(membership)
    await db.flush()
    return membership


async def remove_candidate_from_marketplace(
    db: AsyncSession, *, candidate_id: int
) -> bool:
    """Explicit remove z targu (nie wygaśnięcie)."""
    pool = await ensure_marketplace_pool(db)
    result = await db.execute(
        select(TalentPoolMembership).where(
            TalentPoolMembership.talent_pool_id == pool.id,
            TalentPoolMembership.candidate_id == candidate_id,
        )
    )
    m = result.scalar_one_or_none()
    if m is None:
        return False
    await db.delete(m)
    return True


async def list_marketplace_candidates(
    db: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    q: Optional[str] = None,
    source_event: Optional[str] = None,
) -> tuple[list[tuple[TalentPoolMembership, Candidate]], int]:
    """Paginated list kandydatów w targu.

    Zwraca (rows, total). Każdy row to (membership, candidate) tuple.

    `source_event` zawęża do konkretnego źródła wpisu (np. "manual" pomija
    auto-include z availability_status). None = wszystkie wpisy.
    """
    pool = await ensure_marketplace_pool(db)

    base_filters = [TalentPoolMembership.talent_pool_id == pool.id]
    if source_event:
        base_filters.append(TalentPoolMembership.source_event == source_event)
    if q:
        like = f"%{q.lower()}%"
        base_filters.append(
            or_(
                func.lower(Candidate.name).like(like),
                func.lower(Candidate.lastname).like(like),
                func.lower(Candidate.email).like(like),
            )
        )

    total_q = (
        select(func.count(TalentPoolMembership.id))
        .join(Candidate, Candidate.id == TalentPoolMembership.candidate_id)
        .where(and_(*base_filters))
    )
    total = (await db.execute(total_q)).scalar_one() or 0

    rows_q = (
        select(TalentPoolMembership, Candidate)
        .join(Candidate, Candidate.id == TalentPoolMembership.candidate_id)
        .where(and_(*base_filters))
        .order_by(TalentPoolMembership.added_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(rows_q)
    rows = [(m, c) for m, c in result.all()]
    return rows, total


# ───────────────────────────────────────────────────────────────────────────
# Sweep-loop helpers
# ───────────────────────────────────────────────────────────────────────────


async def rescan_recent_jobs(
    db: AsyncSession, *, lookback: timedelta = timedelta(hours=2)
) -> int:
    """Safety-net rescan jobów zmienionych w ostatnim okienku.

    Używane przez marketplace_sweeper_loop — łapie sytuacje, gdy BackgroundTasks
    na pojedynczym requeście padł albo worker crashował. Dedup przez
    uq_marketplace_alert_pair gwarantuje że duplikaty nie powstaną.
    """
    cutoff = datetime.now(timezone.utc) - lookback
    result = await db.execute(
        select(Job.id).where(
            Job.updated_at >= cutoff,
            Job.status.in_((JobStatus.draft, JobStatus.published)),
        )
    )
    job_ids = [row[0] for row in result.all()]
    for jid in job_ids:
        try:
            await scan_job_for_marketplace_matches(jid, db)
        except Exception:
            logger.exception("rescan_recent_jobs: scan failed job_id=%d", jid)
    return len(job_ids)


async def run_marketplace_scan_safe(job_id: int) -> None:
    """Wrapper pod `BackgroundTasks.add_task(...)` z własną sesją + try/except.

    Wzorzec: `app.tasks.compute_proposals.compute_proposal_for_job` —
    FastAPI zamknie requestową sesję zanim background task pobiegnie, więc
    musimy otworzyć własną.
    """
    if not settings.MARKETPLACE_ENABLED:
        return
    try:
        async with AsyncSessionLocal() as db:
            await scan_job_for_marketplace_matches(job_id, db)
            await db.commit()
    except Exception:
        logger.exception("run_marketplace_scan_safe failed job_id=%d", job_id)
