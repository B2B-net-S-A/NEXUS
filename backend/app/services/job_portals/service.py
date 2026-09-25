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

# Znacznik w ``remote_state`` świeżego wiersza: nowa publikacja anulowała
# zaległe zamknięcie po niepewnej próbie tej pary (``_cancel_stale_cleanup``)
# i przejęła obowiązek sprzątania. ``remote_state`` nowego wiersza jest puste
# do pierwszej odpowiedzi portalu, a ta znacznik nadpisuje (publikacja przejęła
# ogłoszenie albo portal odpowiedział, że go nie ma).
_INHERITED_CLEANUP = "inherited_cleanup"

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
    inherited_cleanup = await _cancel_stale_cleanup(db, job.id, portal)
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
        remote_state=_INHERITED_CLEANUP if inherited_cleanup else None,
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


def external_ref_for(job_id: int, portal: Portal) -> str:
    """Nasz ``externalId`` u dostawcy — STAŁY dla pary rekrutacja × portal.

    Dostawca nie deduplikuje po ``externalId``, więc to my szukamy po nim
    przed każdym ``POST`` i przy zamykaniu ogłoszenia bez znanego id. Stały
    identyfikator sprawia, że nowy wiersz po nieudanej/wycofanej publikacji
    znajdzie ogłoszenie, które mogło jednak powstać, zamiast kupić drugie.
    """
    return f"nexus-job-{job_id}-{getattr(portal, 'value', portal)}"


def _maybe_sent(posting: JobPosting) -> bool:
    """Czy ``POST`` mógł już pójść (worker brał wiersz co najmniej raz).

    ``next_attempt_at`` ustawia wyłącznie dzierżawa workera (``claim_batch``)
    i odstęp po próbie — świeży wiersz ma tam NULL. Do 25.09.2026 liczyły się
    tylko ``attempts``, a te rosną dopiero PO odpowiedzi portalu: wycofanie
    w trakcie pierwszej wysyłki usuwało wiersz jako „nigdy niewysłany”,
    a opłacone ogłoszenie zostawało na portalu bez możliwości zamknięcia.
    """
    return (
        (posting.attempts or 0) > 0
        or posting.external_id is not None
        or posting.next_attempt_at is not None
    )


async def _cancel_stale_cleanup(db: AsyncSession, job_id: int, portal: Portal) -> bool:
    """Nowa publikacja anuluje zaległe zamknięcie po niepewnej publikacji.

    Wiersz ``failed`` z ``pending_action = close`` (timeouty do końca prób —
    ogłoszenie MOGŁO powstać) zamyka ogłoszenie po naszym STAŁYM externalId.
    Ten sam externalId niesie nowa publikacja tej pary, więc zaległe
    zamknięcie zamknęłoby NOWE, opłacone ogłoszenie. Anulujemy je: nowa
    publikacja najpierw szuka ogłoszenia po externalId i przejmie to, które
    mogło powstać, zamiast kupować drugie (audyt 25.09.2026).

    Zwraca True, gdy coś anulowano — nowy wiersz dziedziczy wtedy sprzątanie
    (``_INHERITED_CLEANUP``): wycofany, zanim worker go wziął, nie może zniknąć
    jako „nigdy niewysłany”, bo ogłoszenie z poprzedniej próby zostałoby na
    portalu bez nikogo, kto je zamknie (audyt 25.09.2026, runda 2).
    """
    stale = (
        await db.scalars(
            select(JobPosting)
            .where(
                JobPosting.job_id == job_id,
                JobPosting.portal == portal,
                JobPosting.status == PostingStatus.failed,
                JobPosting.pending_action == ACTION_CLOSE,
            )
            .with_for_update()
        )
    ).all()
    for old in stale:
        old.pending_action = None
        old.next_attempt_at = None
        old.last_error = (
            "Zamknięcie anulowane — nowa publikacja przejmie ogłoszenie, "
            "jeśli poprzednia próba je utworzyła."
        )
    return bool(stale)


async def request_unpublish(
    db: AsyncSession, *, job: Job, portal: Portal
) -> Optional[JobPosting]:
    """Wycofanie: wiersz, którego worker jeszcze nie brał = od razu ``removed``.

    Każdy inny (opublikowany albo w trakcie publikacji po próbie) dostaje
    ``pending_action = close`` — worker zamyka ogłoszenie na portalu, a gdy
    nie zna jego id, szuka po naszym ``externalId``. Zamknięcie na portalu
    jest ostateczne: kolejna publikacja to nowe ogłoszenie i nowy kredyt.
    """

    posting = await _live(db, job.id, portal, lock=True)
    if posting is None:
        return None
    _close_or_drop(posting)
    return posting


def _inherits_cleanup(posting: JobPosting) -> bool:
    return posting.remote_state == _INHERITED_CLEANUP


def _close_or_drop(posting: JobPosting) -> None:
    if (
        posting.status == PostingStatus.publishing
        and not _maybe_sent(posting)
        and not _inherits_cleanup(posting)
    ):
        posting.status = PostingStatus.removed
        posting.pending_action = None
        posting.last_error = None
    elif posting.pending_action != ACTION_CLOSE:
        _queue(posting, ACTION_CLOSE)


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
        _close_or_drop(posting)
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
    """Nowa zatwierdzona wersja opisu publicznego → aktualizacja na portalach.

    Wiersz z aktualizacją już w kolejce (także w trakcie wysyłki) liczy się
    jako objęty: worker po wysyłce porównuje zatwierdzoną wersję z tą, którą
    wysłał (``process_one``), i zostawia ``update`` w kolejce, gdy opis
    zmienił się w trakcie. Dzierżawy w toku nie ruszamy — reset
    ``next_attempt_at`` pozwoliłby drugiemu tickowi wziąć ten sam wiersz.
    """
    rows = (
        await db.scalars(
            select(JobPosting)
            .where(
                JobPosting.job_id == job_id,
                JobPosting.status == PostingStatus.published,
                or_(
                    JobPosting.pending_action.is_(None),
                    JobPosting.pending_action == ACTION_UPDATE,
                ),
            )
            .with_for_update()
        )
    ).all()
    queued = 0
    for posting in rows:
        if posting.pending_action is None:
            _queue(posting, ACTION_UPDATE)
            queued += 1
    # Liczba NOWO zakolejkowanych — wiersz, który już czeka, nie jest dublem.
    return queued


async def has_live_postings(db: AsyncSession, job_id: int) -> bool:
    """Żywe ogłoszenie ALBO zamknięcie wciąż w kolejce (także po porażce)."""
    return (
        await db.scalar(
            select(JobPosting.id)
            .where(
                JobPosting.job_id == job_id,
                or_(
                    JobPosting.status.in_(LIVE_STATUSES),
                    JobPosting.pending_action == ACTION_CLOSE,
                ),
            )
            .limit(1)
        )
    ) is not None


# ── Worker ───────────────────────────────────────────────────────────────────
#
# Wiersz jest „dzierżawiony” (``next_attempt_at`` = teraz + dzierżawa) w krótkiej
# transakcji, a wywołania portalu idą BEZ blokady wiersza — trasy API
# (wycofanie, zmiana ustawień, zamknięcie rekrutacji) nie czekają na HTTP.
# Wynik zapisuje osobna, krótka transakcja per wiersz: wyjątek jednego wiersza
# nie cofa opłaconej publikacji drugiego. Proces zabity w trakcie = wiersz
# wraca po dzierżawie, a ``publish`` najpierw szuka ogłoszenia po externalId.

_LEASE = timedelta(minutes=15)
_UNEXPECTED = "Nieoczekiwany błąd przy wysyłce do portalu — spróbujemy ponownie."


async def claim_batch(db: AsyncSession, limit: int) -> list[JobPosting]:
    now = _now()
    rows = list(
        (
            await db.scalars(
                select(JobPosting)
                .where(
                    or_(
                        JobPosting.status == PostingStatus.publishing,
                        and_(
                            JobPosting.status.in_(
                                (PostingStatus.published, PostingStatus.failed)
                            ),
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
    for posting in rows:
        posting.next_attempt_at = now + _LEASE
    return rows


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(60 * 2 ** max(attempts - 1, 0), _BACKOFF_CAP_SECONDS))


def _action_of(posting: JobPosting) -> str:
    if posting.pending_action == ACTION_CLOSE:
        return ACTION_CLOSE
    if posting.status == PostingStatus.publishing:
        return ACTION_PUBLISH
    return posting.pending_action or ACTION_UPDATE


def _snapshot(posting: JobPosting) -> str:
    return json.dumps(
        [posting.pending_action, posting.options], sort_keys=True, default=str
    )


@dataclass
class _Outcome:
    kind: str  # ok | gone | reconnect | give_up | retry
    message: Optional[str] = None
    result: Any = None
    built: Optional[BuiltContent] = None
    uncertain: bool = False  # porażka, po której ogłoszenie mogło jednak powstać


async def _run(db: AsyncSession, posting: JobPosting, action: str) -> _Outcome:
    # Wartości PRZED jakimkolwiek rollbackiem — po nim obiekt ORM wygasa, a
    # doczytanie atrybutu w sesji async to `MissingGreenlet`.
    posting_id = posting.id
    job_id = posting.job_id
    portal = posting.portal
    external_id = posting.external_id
    options = posting.options
    ref = external_ref_for(job_id, portal)
    try:
        adapter = job_portals.adapter_for(portal)
        if action == ACTION_CLOSE:
            await db.rollback()
            await adapter.unpublish(external_id, external_ref=ref)
            return _Outcome("ok")
        job = await db.get(Job, job_id)
        if job is None:
            return _Outcome("give_up", "Rekrutacja już nie istnieje.")
        if job.status != JobStatus.published:
            return _Outcome(
                "give_up",
                "Rekrutacja nie jest opublikowana — ogłoszenie nie zostało wysłane.",
            )
        built = await build_content(db, job, options=options)
        content = dataclasses.replace(built.content, external_ref=ref)
        await db.rollback()  # odczyty skończone — bez transakcji w trakcie HTTP
        if action == ACTION_PUBLISH:
            result = await adapter.publish(content)
        else:
            result = await adapter.update(external_id or "", content)
        return _Outcome("ok", result=result, built=built)
    except PortalReconnectRequired as exc:
        return _Outcome("reconnect", exc.message)
    except PortalGone as exc:
        return _Outcome("gone", exc.message)
    except PortalRequestError as exc:
        return _Outcome("give_up", exc.message)
    except PortalError as exc:
        kind = "retry" if exc.retryable else "give_up"
        return _Outcome(kind, exc.message, uncertain=exc.retryable)
    except Exception as exc:  # noqa: BLE001 — jeden wiersz nie wywraca kolejki
        logger.error(
            "job portal posting=%s action=%s failed: %s",
            posting_id,
            action,
            type(exc).__name__,
        )
        return _Outcome("retry", _UNEXPECTED, uncertain=True)


async def process_one(posting_id: int) -> None:
    """Jedna akcja na jednym wierszu: portal bez blokady, zapis w osobnej transakcji."""
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        posting = await db.get(JobPosting, posting_id)
        if posting is None:
            return
        action = _action_of(posting)
        snapshot = _snapshot(posting)
        sent_options = json.dumps(posting.options, sort_keys=True, default=str)
        sent_profile_hash = await _approved_hash(db, posting.job_id)
        outcome = await _run(db, posting, action)
    async with AsyncSessionLocal() as db:
        posting = await db.scalar(
            select(JobPosting).where(JobPosting.id == posting_id).with_for_update()
        )
        if posting is None:
            return
        stale = False
        if action in (ACTION_PUBLISH, ACTION_UPDATE):
            # Treść albo ustawienia zmieniły się w trakcie wysyłki: portal
            # dostał starą wersję, więc aktualizacja zostaje w kolejce. Do
            # 25.09.2026 porównanie widziało tylko `pending_action`/`options`,
            # a sukces publikacji zerował zlecenie — portal zostawał ze starą
            # treścią albo miastem (audyt, runda 4).
            now_options = json.dumps(posting.options, sort_keys=True, default=str)
            now_hash = await _approved_hash(db, posting.job_id)
            stale = now_options != sent_options or now_hash != sent_profile_hash
        _apply(
            posting,
            action,
            outcome,
            changed=_snapshot(posting) != snapshot,
            stale_content=stale,
        )
        await db.commit()


async def _approved_hash(db: AsyncSession, job_id: int) -> str:
    """Zatwierdzona wersja opisu publicznego (``approved_hash``) — licznik
    „zlecenia treści”: nowe zatwierdzenie zmienia ją, a nic innego nie."""

    return (
        await db.scalar(
            select(JobPublicProfile.approved_hash).where(
                JobPublicProfile.job_id == job_id
            )
        )
    ) or ""


def _apply(
    posting: JobPosting,
    action: str,
    outcome: _Outcome,
    *,
    changed: bool,
    stale_content: bool = False,
) -> None:
    """Wynik akcji na wierszu. ``changed`` = w trakcie HTTP ktoś zmienił
    zlecenie (wycofał, zmienił ustawienia) — wtedy nowe zlecenie zostaje.
    ``stale_content`` = portal dostał treść albo ustawienia sprzed zmiany
    z czasu wysyłki — po sukcesie (i przy porażce aktualizacji) zostaje
    ``update`` w kolejce."""
    now = _now()
    if outcome.kind == "reconnect":
        posting.last_error = outcome.message
        posting.next_attempt_at = now + _RECONNECT_WAIT
        return
    posting.attempts = (posting.attempts or 0) + 1
    if outcome.kind == "gone":
        posting.status = PostingStatus.removed
        posting.remote_state = "removed"
        posting.pending_action = None
        posting.next_attempt_at = None
        posting.last_error = None if action == ACTION_CLOSE else outcome.message
        posting.last_synced_at = now
        return
    if outcome.kind == "retry" and posting.attempts < settings.JOB_PORTAL_MAX_ATTEMPTS:
        posting.last_error = outcome.message
        posting.next_attempt_at = now + _backoff(posting.attempts)
        return
    if outcome.kind in ("retry", "give_up"):
        _give_up(posting, action, outcome.message or "", uncertain=outcome.uncertain)
        if action == ACTION_UPDATE and stale_content and posting.pending_action is None:
            # Aktualizacja starą treścią się nie udała, a w trakcie przyszła
            # nowa — ta nowa idzie jeszcze raz (portal może ją przyjąć).
            posting.pending_action = ACTION_UPDATE
            posting.attempts = 0
            posting.next_attempt_at = now + _backoff(1)
        return

    # Sukces.
    posting.last_synced_at = now
    posting.last_error = None
    if action == ACTION_CLOSE:
        posting.attempts = 0
        posting.next_attempt_at = None
        posting.pending_action = None
        posting.remote_state = "expired"
        if posting.status != PostingStatus.failed:
            posting.status = PostingStatus.removed
        return
    result = outcome.result
    posting.status = PostingStatus.published
    posting.remote_state = "published"
    if result.external_id:
        posting.external_id = result.external_id
    if result.url:
        posting.url = result.url[:1024]
    if action == ACTION_PUBLISH and posting.published_at is None:
        posting.published_at = now
    if result.extra.get("title_unchanged"):
        posting.last_error = (
            "Portal nie pozwala zmienić tytułu po publikacji — na portalu "
            "został poprzedni tytuł."
        )
    if outcome.built is not None:
        posting.payload_hash = outcome.built.payload_hash
        posting.public_profile_hash = outcome.built.profile_hash
    if stale_content and posting.pending_action != ACTION_CLOSE:
        posting.pending_action = ACTION_UPDATE
        posting.attempts = 0
        posting.next_attempt_at = None
        return
    if changed and posting.pending_action in (ACTION_UPDATE, ACTION_CLOSE):
        # Nowe zlecenie z czasu wysyłki czeka na następny tick.
        posting.next_attempt_at = None
        return
    posting.attempts = 0
    posting.next_attempt_at = None
    posting.pending_action = None


def _give_up(
    posting: JobPosting, action: str, message: str, *, uncertain: bool = False
) -> None:
    posting.last_error = message
    posting.next_attempt_at = None
    if action == ACTION_PUBLISH:
        posting.status = PostingStatus.failed
        posting.pending_action = None
        # `attempts` jest już policzone z tą próbą: > 1 = była wcześniejsza
        # próba, a ta kończyła się ponowieniem (timeout / 5xx) — ogłoszenie
        # MOGŁO wtedy powstać, choć ostatnia odmowa jest pewna (np. opis wrócił
        # do szkicu). Audyt 25.09.2026, runda 4.
        earlier_attempt = (posting.attempts or 0) > 1
        if uncertain or earlier_attempt or _inherits_cleanup(posting):
            # Timeouty do końca prób: ogłoszenie mogło powstać. Zamknięcie po
            # naszym externalId sprząta je, jeśli jest (bez niego — no-op).
            # To samo, gdy wiersz odziedziczył sprzątanie po wcześniejszej
            # niepewnej próbie — pewna odmowa TEJ publikacji nie mówi nic
            # o ogłoszeniu z tamtej.
            posting.pending_action = ACTION_CLOSE
            posting.attempts = 0
            posting.next_attempt_at = _now() + _RECONNECT_WAIT
    elif action == ACTION_UPDATE:
        # Ogłoszenie dalej wisi w poprzedniej wersji — mówi o tym `last_error`.
        posting.pending_action = None
    else:
        # Zamknięcie, które się nie udało, zostaje w kolejce — ogłoszenie
        # wisiałoby na portalu. Kolejna próba za godzinę, bez końca prób.
        posting.attempts = 0
        posting.next_attempt_at = _now() + _RECONNECT_WAIT


async def process_batch(db: AsyncSession, limit: int = 10) -> int:
    """Dzierżawi paczkę (krótka transakcja na ``db``), potem wiersz po wierszu."""
    ids = [posting.id for posting in await claim_batch(db, limit)]
    await db.commit()
    for posting_id in ids:
        await process_one(posting_id)
    return len(ids)


async def sync_remote_states(limit: int = 20) -> int:
    """Stan żywych ogłoszeń: wygasłe (90 dni / koniec subskrypcji) i usunięte.

    Bez blokady w trakcie HTTP; wynik każdego wiersza w osobnej transakcji.
    """
    from app.core.database import AsyncSessionLocal

    cutoff = _now() - timedelta(hours=max(1, settings.JOB_PORTAL_STATUS_SYNC_HOURS))
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(JobPosting.id, JobPosting.portal, JobPosting.external_id)
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
            )
        ).all()
    for posting_id, portal, external_id in rows:
        state: Optional[str] = None
        gone = False
        try:
            state = (await job_portals.adapter_for(portal).status(external_id)).get(
                "state"
            )
        except PortalGone:
            gone = True
        except Exception as exc:  # noqa: BLE001 — stan sprawdzimy następnym razem
            logger.info(
                "job portal status sync skipped posting=%s: %s",
                posting_id,
                type(exc).__name__,
            )
        async with AsyncSessionLocal() as db:
            posting = await db.scalar(
                select(JobPosting).where(JobPosting.id == posting_id).with_for_update()
            )
            if posting is None or posting.pending_action is not None:
                continue
            now = _now()
            if posting.status == PostingStatus.published:
                if gone:
                    posting.status = PostingStatus.removed
                    posting.remote_state = "removed"
                elif state:
                    posting.remote_state = str(state)[:20]
                    if state == "expired":
                        posting.status = PostingStatus.expired
                        posting.expires_at = posting.expires_at or now
            posting.last_synced_at = now
            await db.commit()
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
