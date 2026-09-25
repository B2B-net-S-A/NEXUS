"""Kolejka publikacji rekrutacji na portalach (0360, 0381).

Zgłoszenie publikacji (``request_publish``) zapisuje wiersz ``publishing``
z ustawieniami ogłoszenia (``options``); worker (``process_batch``) bierze
wiersze ``FOR UPDATE SKIP LOCKED`` (wzór ``index_outbox_service.claim_batch``)
i woła adapter. Żywe ogłoszenie dostaje ``pending_action``:
``update`` (nowa zatwierdzona treść albo zmienione ustawienia) albo
``close`` (wycofanie, zamknięcie rekrutacji). Odmowy przed kolejką:

* portal wyłączony / bez konfiguracji / konto niepołączone → 409;
* rekrutacja nieopublikowana → 409;
* brak ZATWIERDZONEGO opisu publicznego → 409 — do portalu idzie wyłącznie
  biała lista z ``job_public_profile.public_job_payload`` (nigdy klient ani
  stawka, jak na stronie kariery);
* brak aktywnego linku aplikacyjnego rekrutacji → 409 — kandydat z portalu
  aplikuje przez stronę kariery (``/r/<slug>``);
* braki w ustawieniach ogłoszenia → 422 z listą (kredyt portalu jest płatny,
  więc nie wysyłamy czegoś, co portal i tak odrzuci);
* żywa publikacja na tym portalu już jest → 409 (i częściowy UNIQUE w bazie).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.invite_link import CandidateInviteLink
from app.models.job import Job, JobStatus
from app.models.job_posting import JobPosting, Portal, PostingStatus
from app.models.job_public_profile import JobPublicProfile
from app.services import job_portals
from app.services.job_portals import jjit_payload
from app.services.job_portals.base import (
    PortalError,
    PortalGone,
    PortalReconnectRequired,
    PostingContent,
)

logger = logging.getLogger(__name__)

LIVE_STATUSES = (PostingStatus.publishing, PostingStatus.published)

ACTION_PUBLISH = "publish"
ACTION_UPDATE = "update"
ACTION_CLOSE = "close"

# Konto do ponownego połączenia: wiersz czeka, próby się nie zużywają.
_RECONNECT_WAIT = timedelta(hours=1)
_BACKOFF_CAP_SECONDS = 3600


class PortalRequestError(Exception):
    """Odmowa zgłoszenia (409/422) z komunikatem po polsku."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        problems: Optional[list[str]] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.problems = problems or []


@dataclass(frozen=True)
class BuiltContent:
    content: PostingContent
    profile_hash: str
    payload_hash: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _job_link_slug(db: AsyncSession, job_id: int) -> Optional[str]:
    now = _now()
    rows = (
        await db.scalars(
            select(CandidateInviteLink)
            .where(
                CandidateInviteLink.job_id == job_id,
                CandidateInviteLink.kind == "job",
                CandidateInviteLink.revoked.is_(False),
                CandidateInviteLink.slug.is_not(None),
            )
            .order_by(CandidateInviteLink.created_at.desc())
        )
    ).all()
    for link in rows:
        if link.expires_at is None or link.expires_at > now:
            return link.slug
    return None


def _hash(payload: dict[str, Any], apply_url: str, options: Any) -> str:
    encoded = json.dumps(
        {"job": payload, "apply_url": apply_url, "options": options or {}},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def build_content(
    db: AsyncSession, job: Job, *, options: Any = None
) -> BuiltContent:
    """Treść ogłoszenia albo odmowa — wyłącznie z zatwierdzonego opisu."""

    from app.services.career_slugs import job_link_url
    from app.services.job_public_profile import (
        STATUS_APPROVED,
        public_job_payload,
        resolve_status,
    )

    profile = await db.scalar(
        select(JobPublicProfile).where(JobPublicProfile.job_id == job.id)
    )
    status, _default, title = await resolve_status(db, job, profile)
    if profile is None or status != STATUS_APPROVED:
        raise PortalRequestError(
            409,
            "public_profile_not_approved",
            "Rekrutacja nie ma zatwierdzonego opisu publicznego — zatwierdź go "
            "w „Stronie kariery”, zanim wyślesz ogłoszenie na portal.",
        )
    slug = await _job_link_slug(db, job.id)
    if not slug:
        raise PortalRequestError(
            409,
            "job_link_missing",
            "Rekrutacja nie ma aktywnego linku aplikacyjnego — utwórz link na "
            "stronie kariery; kandydaci z portalu aplikują przez niego.",
        )
    payload = public_job_payload(
        job,
        title=title,
        link_slug=slug,
        subtitle=profile.subtitle,
        about=profile.about,
        sections=profile.sections,
    )
    apply_url = job_link_url(slug)
    content = PostingContent(
        title=title,
        job=payload,
        apply_url=apply_url,
        options=dict(options or {}),
    )
    return BuiltContent(
        content=content,
        profile_hash=profile.approved_hash or "",
        payload_hash=_hash(payload, apply_url, options),
    )


async def _ensure_portal_ready(db: AsyncSession, portal: Portal) -> None:
    if portal not in job_portals.ADAPTERS:
        raise PortalRequestError(
            422, "portal_unsupported", "Ten portal nie ma integracji w NEXUSIE."
        )
    config = job_portals.PortalConfig.from_settings(portal)
    state = await job_portals.resolve_state(db, config)
    if state == "not_connected":
        raise PortalRequestError(
            409,
            "portal_not_connected",
            "Konto portalu nie jest połączone — admin łączy je w Ustawieniach → "
            "Portale ogłoszeniowe.",
        )
    if state != "ready":
        raise PortalRequestError(
            409,
            "portal_not_configured",
            "Portal nie jest skonfigurowany — publikacja jest niedostępna.",
        )


def default_listing_options(job: Job) -> dict[str, Any]:
    """Podpowiedź ustawień ogłoszenia z rekrutacji (kategoria zawsze pusta)."""
    from app.services.job_public_profile import public_params

    work_mode = (
        getattr(job.work_mode, "value", job.work_mode) if job.work_mode else None
    )
    return jjit_payload.default_options(public_params(job), work_mode=work_mode)


def _checked_options(
    portal: Portal, content: PostingContent, options: dict[str, Any]
) -> dict[str, Any]:
    adapter = job_portals.adapter_for(portal)
    problems = adapter.validate_options(dataclasses.replace(content, options=options))
    if problems:
        raise PortalRequestError(
            422,
            "listing_invalid",
            "Ogłoszenie ma braki — uzupełnij je przed publikacją.",
            problems,
        )
    return options


async def _live(
    db: AsyncSession, job_id: int, portal: Portal, *, lock: bool = False
) -> Optional[JobPosting]:
    stmt = select(JobPosting).where(
        JobPosting.job_id == job_id,
        JobPosting.portal == portal,
        JobPosting.status.in_(LIVE_STATUSES),
    )
    if lock:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt)


async def request_publish(
    db: AsyncSession,
    *,
    job: Job,
    portal: Portal,
    user_id: Optional[int],
    options: Any = None,
) -> JobPosting:
    await _ensure_portal_ready(db, portal)
    if job.status != JobStatus.published:
        raise PortalRequestError(
            409,
            "job_not_published",
            "Opublikuj rekrutację w NEXUSIE, zanim wyślesz ogłoszenie na portal.",
        )
    if await _live(db, job.id, portal) is not None:
        raise PortalRequestError(
            409,
            "posting_already_live",
            "Ogłoszenie tej rekrutacji na tym portalu już jest publikowane.",
        )
    normalized = jjit_payload.normalize_options(
        options if options is not None else default_listing_options(job)
    )
    built = await build_content(db, job, options=normalized)
    _checked_options(portal, built.content, normalized)
    posting = JobPosting(
        job_id=job.id,
        portal=portal,
        status=PostingStatus.publishing,
        attempts=0,
        options=normalized,
        pending_action=ACTION_PUBLISH,
        payload_hash=built.payload_hash,
        public_profile_hash=built.profile_hash,
        created_by=user_id,
    )
    db.add(posting)
    await db.flush()
    return posting


async def update_options(
    db: AsyncSession, *, job: Job, portal: Portal, options: Any
) -> JobPosting:
    """Nowe ustawienia żywego ogłoszenia; opublikowane idzie do aktualizacji."""
    posting = await _live(db, job.id, portal, lock=True)
    if posting is None:
        raise PortalRequestError(
            404, "posting_missing", "Rekrutacja nie jest publikowana na tym portalu."
        )
    if posting.pending_action == ACTION_CLOSE:
        raise PortalRequestError(
            409, "posting_closing", "Ogłoszenie jest właśnie zamykane."
        )
    normalized = jjit_payload.normalize_options(options)
    built = await build_content(db, job, options=normalized)
    _checked_options(portal, built.content, normalized)
    posting.options = normalized
    if posting.status == PostingStatus.published:
        _queue(posting, ACTION_UPDATE)
    return posting


def _queue(posting: JobPosting, action: str) -> None:
    posting.pending_action = action
    posting.attempts = 0
    posting.next_attempt_at = None
    posting.last_error = None


async def request_unpublish(
    db: AsyncSession, *, job: Job, portal: Portal
) -> Optional[JobPosting]:
    """Wycofanie: wiersz ``publishing`` (worker go nie wziął) = od razu ``removed``.

    Opublikowany dostaje ``pending_action = close`` — portal zamyka worker
    (ponowienia, konto do ponownego połączenia). Zamknięcie na portalu jest
    ostateczne: kolejna publikacja to nowe ogłoszenie i nowy kredyt.
    """

    posting = await _live(db, job.id, portal, lock=True)
    if posting is None:
        return None
    if posting.status == PostingStatus.publishing:
        posting.status = PostingStatus.removed
        posting.pending_action = None
        posting.last_error = None
        return posting
    _queue(posting, ACTION_CLOSE)
    return posting


async def close_live_postings(db: AsyncSession, job_id: int) -> int:
    """Zamknięcie rekrutacji zamyka jej ogłoszenia na portalach.

    No-op, gdy nic nie jest opublikowane (np. archiwum z Traffita). Zwraca
    liczbę wierszy zmienionych.
    """
    rows = (
        await db.scalars(
            select(JobPosting)
            .where(
                JobPosting.job_id == job_id,
                JobPosting.status.in_(LIVE_STATUSES),
            )
            .with_for_update()
        )
    ).all()
    for posting in rows:
        if posting.status == PostingStatus.publishing:
            posting.status = PostingStatus.removed
            posting.pending_action = None
        elif posting.pending_action != ACTION_CLOSE:
            _queue(posting, ACTION_CLOSE)
    return len(rows)


async def close_postings_of_closed_jobs(db: AsyncSession) -> int:
    """Siatka bezpieczeństwa workera: rekrutacja nieopublikowana = zamknięcie.

    Obejmuje każdą ścieżkę zmiany statusu (PATCH, nocne archiwum Traffita,
    zmiany hurtowe), także te, które nie wołają ``close_live_postings``.
    """
    job_ids = (
        await db.scalars(
            select(JobPosting.job_id)
            .join(Job, Job.id == JobPosting.job_id)
            .where(
                JobPosting.status.in_(LIVE_STATUSES),
                or_(
                    JobPosting.pending_action.is_(None),
                    JobPosting.pending_action != ACTION_CLOSE,
                ),
                Job.status != JobStatus.published,
            )
            .distinct()
            .limit(50)
        )
    ).all()
    for job_id in job_ids:
        await close_live_postings(db, job_id)
    return len(job_ids)


async def queue_content_update(db: AsyncSession, job_id: int) -> int:
    """Nowa zatwierdzona wersja opisu publicznego → aktualizacja na portalach."""
    rows = (
        await db.scalars(
            select(JobPosting)
            .where(
                JobPosting.job_id == job_id,
                JobPosting.status == PostingStatus.published,
                JobPosting.pending_action.is_(None),
            )
            .with_for_update()
        )
    ).all()
    for posting in rows:
        _queue(posting, ACTION_UPDATE)
    return len(rows)


async def has_live_postings(db: AsyncSession, job_id: int) -> bool:
    return (
        await db.scalar(
            select(JobPosting.id)
            .where(
                JobPosting.job_id == job_id,
                JobPosting.status.in_(LIVE_STATUSES),
            )
            .limit(1)
        )
    ) is not None


# ── Worker ───────────────────────────────────────────────────────────────────


async def claim_batch(db: AsyncSession, limit: int) -> list[JobPosting]:
    now = _now()
    return list(
        (
            await db.scalars(
                select(JobPosting)
                .where(
                    or_(
                        JobPosting.status == PostingStatus.publishing,
                        and_(
                            JobPosting.status == PostingStatus.published,
                            JobPosting.pending_action.in_(
                                (ACTION_UPDATE, ACTION_CLOSE)
                            ),
                        ),
                    ),
                    or_(
                        JobPosting.next_attempt_at.is_(None),
                        JobPosting.next_attempt_at <= now,
                    ),
                )
                .order_by(JobPosting.id.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(60 * 2 ** max(attempts - 1, 0), _BACKOFF_CAP_SECONDS))


def _action_of(posting: JobPosting) -> str:
    if posting.status == PostingStatus.publishing:
        return ACTION_PUBLISH
    return posting.pending_action or ACTION_UPDATE


async def process_posting(db: AsyncSession, posting: JobPosting) -> None:
    """Jedna akcja: publikacja, aktualizacja albo zamknięcie ogłoszenia."""

    now = _now()
    action = _action_of(posting)
    posting.attempts = (posting.attempts or 0) + 1
    adapter = job_portals.adapter_for(posting.portal)
    built: Optional[BuiltContent] = None
    try:
        if action == ACTION_CLOSE:
            if posting.external_id:
                await adapter.unpublish(posting.external_id)
        else:
            job = await db.get(Job, posting.job_id)
            if job is None:
                raise PortalError("Rekrutacja już nie istnieje.", retryable=False)
            if job.status != JobStatus.published:
                raise PortalRequestError(
                    409,
                    "job_not_published",
                    "Rekrutacja nie jest opublikowana — ogłoszenie nie zostało wysłane.",
                )
            built = await build_content(db, job, options=posting.options)
            content = dataclasses.replace(
                built.content, external_ref=f"nexus-posting-{posting.id}"
            )
            if action == ACTION_PUBLISH:
                result = await adapter.publish(content)
            else:
                result = await adapter.update(posting.external_id or "", content)
    except PortalReconnectRequired as exc:
        posting.attempts -= 1
        posting.last_error = exc.message
        posting.next_attempt_at = now + _RECONNECT_WAIT
        return
    except PortalGone as exc:
        posting.status = PostingStatus.removed
        posting.remote_state = "removed"
        posting.pending_action = None
        posting.next_attempt_at = None
        posting.last_error = None if action == ACTION_CLOSE else exc.message
        posting.last_synced_at = now
        return
    except PortalRequestError as exc:
        _give_up(posting, action, exc.message)
        return
    except PortalError as exc:
        posting.last_error = exc.message
        if not exc.retryable or posting.attempts >= settings.JOB_PORTAL_MAX_ATTEMPTS:
            _give_up(posting, action, exc.message)
        else:
            posting.next_attempt_at = now + _backoff(posting.attempts)
        return

    posting.attempts = 0
    posting.next_attempt_at = None
    posting.pending_action = None
    posting.last_error = None
    posting.last_synced_at = now
    if action == ACTION_CLOSE:
        posting.status = PostingStatus.removed
        posting.remote_state = "expired"
        return
    posting.status = PostingStatus.published
    posting.remote_state = "published"
    if result.external_id:
        posting.external_id = result.external_id
    if result.url:
        posting.url = result.url
    if action == ACTION_PUBLISH:
        posting.published_at = now
    if result.extra.get("title_unchanged"):
        posting.last_error = (
            "Portal nie pozwala zmienić tytułu po publikacji — na portalu "
            "został poprzedni tytuł."
        )
    assert built is not None
    posting.payload_hash = built.payload_hash
    posting.public_profile_hash = built.profile_hash


def _give_up(posting: JobPosting, action: str, message: str) -> None:
    posting.last_error = message
    posting.next_attempt_at = None
    if action == ACTION_PUBLISH:
        posting.status = PostingStatus.failed
        posting.pending_action = None
    elif action == ACTION_UPDATE:
        # Ogłoszenie dalej wisi w poprzedniej wersji — mówi o tym `last_error`.
        posting.pending_action = None
    else:
        # Zamknięcie, które się nie udało, zostaje w kolejce — ogłoszenie
        # wisiałoby na portalu. Kolejna próba za godzinę, bez końca prób.
        posting.attempts = 0
        posting.next_attempt_at = _now() + _RECONNECT_WAIT


async def process_batch(db: AsyncSession, limit: int = 10) -> int:
    postings = await claim_batch(db, limit)
    for posting in postings:
        await process_posting(db, posting)
    return len(postings)


async def sync_remote_states(db: AsyncSession, limit: int = 20) -> int:
    """Stan żywych ogłoszeń: wygasłe (90 dni / koniec subskrypcji) i usunięte."""
    cutoff = _now() - timedelta(hours=max(1, settings.JOB_PORTAL_STATUS_SYNC_HOURS))
    rows = (
        await db.scalars(
            select(JobPosting)
            .where(
                JobPosting.status == PostingStatus.published,
                JobPosting.pending_action.is_(None),
                JobPosting.external_id.is_not(None),
                JobPosting.portal.in_(list(job_portals.ADAPTERS)),
                or_(
                    JobPosting.last_synced_at.is_(None),
                    JobPosting.last_synced_at < cutoff,
                ),
            )
            .order_by(JobPosting.last_synced_at.asc().nulls_first())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for posting in rows:
        now = _now()
        adapter = job_portals.adapter_for(posting.portal)
        try:
            state = (await adapter.status(posting.external_id or "")).get("state")
        except PortalGone:
            posting.status = PostingStatus.removed
            posting.remote_state = "removed"
        except PortalError as exc:
            logger.info(
                "job portal status sync skipped posting=%s: %s",
                posting.id,
                type(exc).__name__,
            )
        else:
            posting.remote_state = state
            if state == "expired":
                posting.status = PostingStatus.expired
                posting.expires_at = posting.expires_at or now
        posting.last_synced_at = now
    return len(rows)


async def failed_recently(db: AsyncSession, *, hours: int = 24) -> int:
    since = _now() - timedelta(hours=hours)
    return int(
        await db.scalar(
            select(func.count(JobPosting.id)).where(
                JobPosting.status == PostingStatus.failed,
                JobPosting.updated_at >= since,
            )
        )
        or 0
    )


async def portal_health_inputs(db: AsyncSession) -> tuple[int, bool]:
    """(nieudane publikacje z doby, czy konto JustJoin.IT/RocketJobs wymaga połączenia)."""
    from app.models.job_board_connection import STATUS_RECONNECT_REQUIRED
    from app.services.job_portals import jjit_connection

    failed = await failed_recently(db)
    row = await jjit_connection.load(db)
    return failed, bool(row is not None and row.status == STATUS_RECONNECT_REQUIRED)
