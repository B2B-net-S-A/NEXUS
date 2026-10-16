"""Emitter powiadomień stage transition.

Wzorzec best-effort:
    - Top-level try/except — funkcja NIGDY nie rzuca w górę.
    - Per-recipient try/except — błąd jednego usera nie blokuje innych.
    - Per-channel try/except — błąd emaila nie blokuje in-app i odwrotnie.

In-app: korzysta z istniejącego ``emit()`` w
``services/notification_triggers.py`` — to daje DB insert + WS push +
dedup `ix_notif_dedup_daily` w jednym wywołaniu.

Email: SMTP via ``services/email.py:send_email`` — sync, no-op gdy
``SMTP_ENABLED=false``. Treść z hardcoded templatu PL.
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job
from app.models.notification import NotificationType
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.services.email import send_email
from app.services.notification_access import notification_recipient_has_access
from app.services.notification_delivery import (
    email_opted_out,
    guarded_send,
    load_policy,
)
from app.services.notification_triggers import emit
from app.services.board_stage_badges import cpro_enabled_for_client
from app.services.consultant_elsewhere_notifications import (
    notify_current_client_leads,
)
from app.services import screening_fix_requests, stage_remarks
from app.services.stage_handoff_recipients import (
    REASON_CPRO_QUEUE,
    REASON_CPRO_RETURNED,
    REASON_CV_SENT,
    REASON_DL_REVIEW,
    REASON_QC_RETURNED,
    REASON_STAGE_REACHED,
    TASK_REASONS,
    TITLE_CPRO_QUEUE,
    TITLE_CPRO_RETURNED,
    TITLE_DL_REVIEW,
    TITLE_QC_RETURNED,
)
from app.services.stage_notification_email_template import render_stage_email
from app.services.stage_notification_resolver import (
    ResolvedRecipient,
    resolve_recipients,
)

logger = logging.getLogger(__name__)


def _candidate_full_name(candidate: Candidate) -> str:
    parts = [getattr(candidate, "name", None), getattr(candidate, "lastname", None)]
    return " ".join(p for p in parts if p) or f"#{candidate.id}"


def _candidate_first_name(candidate: Candidate) -> str:
    return getattr(candidate, "name", None) or f"#{candidate.id}"


async def _client_name(db: AsyncSession, job: Job) -> Optional[str]:
    if not job.client_id:
        return None
    return await db.scalar(select(Client.name).where(Client.id == job.client_id))


async def _user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
    return await db.scalar(select(User).where(User.id == user_id))


def _inapp_content(
    *,
    reason: Optional[str],
    candidate: Candidate,
    candidate_full_name: str,
    stage_display_name: str,
    job: Job,
    mover: Optional[User],
    remark: Optional[str] = None,
    fix_labels: Sequence[str] = (),
) -> tuple[str, str, str]:
    """``(tytuł, treść, link)`` dzwonka.

    Przekazanie z przepływu mówi odbiorcy, co ma zrobić, i prowadzi na
    Tablicę rekrutacji z otwartą osobą; zwykła reguła etapu zostaje przy
    ogólnym zdaniu i profilu kandydata. ``remark`` to uwaga dla rekrutera
    zostawiona przy ruchu (`stage_remarks`) — stawki do klienta dzwonek nie
    niesie nigdy.
    """

    title, message, link = _inapp_base(
        reason=reason,
        candidate=candidate,
        candidate_full_name=candidate_full_name,
        stage_display_name=stage_display_name,
        job=job,
        mover=mover,
    )
    note = stage_remarks.short(remark)
    if note:
        message = f"{message} Uwaga: „{note}”"
    # D6 (08.10.2026): prośba DL o poprawki — które pola poprawić.
    fixes = screening_fix_requests.bell_suffix(fix_labels)
    if fixes:
        message = f"{message} {fixes}"
        if reason == REASON_QC_RETURNED:
            # Prosto do formularza screeningu z podświetlonymi polami.
            link = f"{link}&panel=screening"
    return title, message, link


# `notifications.title` to VARCHAR(255); nazwa rekrutacji od klienta bywa długa.
_TITLE_MAX = 255


def _fit_title(title: str) -> str:
    return title if len(title) <= _TITLE_MAX else title[: _TITLE_MAX - 1].rstrip() + "…"


def _cpro_job_label(job: Job) -> str:
    """Rekrutacja tak, jak zna ją Nordea: nazwa od klienta i numer (0380)."""

    reference = (getattr(job, "client_reference", None) or "").strip()
    title = job.title or ""
    # Nazwa Nordei zwykle kończy się już numerem („… (42946)”) — bez dubla.
    parts = [part.strip() for part in reference.split(",") if part.strip()]
    if not reference or all(part.lower() in title.lower() for part in parts):
        return job.title
    return f"{job.title} ({reference})"


def _inapp_base(
    *,
    reason: Optional[str],
    candidate: Candidate,
    candidate_full_name: str,
    stage_display_name: str,
    job: Job,
    mover: Optional[User],
) -> tuple[str, str, str]:
    job_title = getattr(job, "working_title", None) or job.title
    who = mover.name if mover and mover.name else "Ktoś z zespołu"
    board_link = f"/jobs/{job.id}?candidate={candidate.id}"
    if reason == REASON_DL_REVIEW:
        next_step = (
            "Sprawdź CV i zaakceptuj do kolejki Cpro."
            if cpro_enabled_for_client(getattr(job, "client_id", None))
            else "Sprawdź CV i wyślij je do klienta."
        )
        return (
            f"{TITLE_DL_REVIEW} {candidate_full_name}",
            f"{who} przekazał(a) CV kandydata {candidate_full_name} do QC "
            f"w rekrutacji „{job_title}”. {next_step}",
            # Prosto do przeglądu (stawka do klienta, trzy decyzje), nie do
            # samego panelu osoby — 04.10.2026.
            f"{board_link}&review=1",
        )
    if reason == REASON_CPRO_QUEUE:
        return (
            # Rekrutacja i numer u klienta w tytule (i temacie maila): ta sama
            # osoba w dwóch rekrutacjach Nordei dawała dwa identyczne dzwonki.
            _fit_title(
                f"{TITLE_CPRO_QUEUE} {candidate_full_name} · {_cpro_job_label(job)}"
            ),
            f"{who} zaakceptował(a) kandydata {candidate_full_name} do Cpro "
            f"w rekrutacji „{job_title}”. Stawka do Cpro jest wpisana — komplet "
            "danych czeka w kolejce Cpro na pulpicie.",
            board_link,
        )
    if reason == REASON_CPRO_RETURNED:
        return (
            f"{TITLE_CPRO_RETURNED} {candidate_full_name}",
            f"{who} zwrócił(a) kandydata {candidate_full_name} z kolejki Cpro "
            f"w rekrutacji „{job_title}”. Osoba wróciła do przeglądu Delivery "
            "Leada w „QC CV”.",
            board_link,
        )
    if reason == REASON_QC_RETURNED:
        return (
            f"{TITLE_QC_RETURNED} {candidate_full_name}",
            f"{who} cofnął(-ęła) CV kandydata {candidate_full_name} z QC "
            f"w rekrutacji „{job_title}”. Popraw i przekaż ponownie.",
            board_link,
        )
    if reason == REASON_CV_SENT:
        return (
            f"CV wysłane: {candidate_full_name}",
            f"{who} wysłał(a) CV kandydata {candidate_full_name} w rekrutacji "
            f"„{job_title}” (etap „{stage_display_name}”).",
            board_link,
        )
    if reason == REASON_STAGE_REACHED:
        return (
            f"{stage_display_name}: {candidate_full_name}",
            f"Kandydat {candidate_full_name} jest na etapie "
            f"„{stage_display_name}” w rekrutacji „{job_title}” — kartę "
            f"przesunął(-ęła) {who}.",
            board_link,
        )
    mover_part = f" przez {mover.name}" if mover else ""
    return (
        f"Kandydat {candidate_full_name} → {stage_display_name}",
        f"Kandydat {candidate_full_name} przeszedł na etap "
        f"„{stage_display_name}” w ofercie '{job.title}' (#{job.id}){mover_part}.",
        # Tablica z otwartą osobą, nie sam profil: wiersz trafia do okienka
        # „Rekrutacje” przy tej rekrutacji (16.10.2026, bez dzwonka).
        f"/jobs/{job.id}?candidate={candidate.id}",
    )


async def _send_inapp(
    db: AsyncSession,
    *,
    user_id: int,
    candidate: Candidate,
    candidate_full_name: str,
    stage_display_name: str,
    job: Job,
    new_stage: CandidateStage,
    mover: Optional[User],
    reason: Optional[str] = None,
    remark: Optional[str] = None,
    fix_labels: Sequence[str] = (),
) -> bool:
    title, message, link = _inapp_content(
        reason=reason,
        candidate=candidate,
        candidate_full_name=candidate_full_name,
        stage_display_name=stage_display_name,
        job=job,
        mover=mover,
        remark=remark,
        fix_labels=fix_labels,
    )
    notif = await emit(
        db,
        user_id=user_id,
        title=title,
        message=message,
        # Zadanie czekające na odbiorcę ma typ, którego nie da się wyciszyć;
        # informacja o ruchu zostaje przy `stage_rule`.
        ntype=(
            NotificationType.board_task_waiting
            if reason in TASK_REASONS
            else NotificationType.stage_rule
        ),
        related_entity_type="candidate_stage",
        related_entity_id=new_stage.id,
        link=link,
    )
    return notif is not None


def _send_email_for_recipient(
    *,
    user: User,
    candidate: Candidate,
    candidate_full_name: str,
    candidate_first_name: str,
    stage_display_name: str,
    client_name: Optional[str],
    job: Job,
    mover: Optional[User],
    new_stage: CandidateStage,
) -> None:
    if not user.email:
        logger.debug("stage_notif: email skipped — user=%s has no email", user.id)
        return
    if email_opted_out(user, "pipeline_stage"):
        # Własny wyłącznik maila („Maile do Ciebie”); dzwonek zostaje.
        logger.debug("stage_notif: email skipped — user=%s opted out", user.id)
        return
    base_url = (settings.PUBLIC_BASE_URL or "").rstrip("/")
    link = (
        f"{base_url}/candidates/{candidate.id}"
        if base_url
        else f"/candidates/{candidate.id}"
    )

    subject, text_body, html_body = render_stage_email(
        recipient_name=user.name or user.email,
        candidate_full_name=candidate_full_name,
        candidate_first_name=candidate_first_name,
        stage_name=stage_display_name,
        client_name=client_name,
        job_title=job.title,
        job_id=job.id,
        mover_name=(mover.name if mover else "system"),
        moved_at=new_stage.moved_at,
        notes=new_stage.notes,
        link=link,
    )
    guarded_send(
        "pipeline_stage",
        new_stage.moved_at,
        send_email,
        user.email,
        subject,
        text_body,
        html_body,
    )


async def notify_stage_change(
    db: AsyncSession,
    *,
    new_stage: CandidateStage,
    previous_stage: Optional[CandidateStage],
    job: Job,
    candidate: Candidate,
    mover: Optional[User],
    stage_display_name: str,
    hired_engagement: Optional[str] = None,
) -> int:
    """Emit notyfikacje (in-app + email) zgodnie z regułami.

    Zwraca liczbę pomyślnie wyemitowanych in-app notyfikacji (głównie do
    debugowania / monitoringu — caller może to ignorować).

    Best-effort: nigdy nie rzuca. Wszystkie błędy są logowane.
    """
    # 12.10.2026: Delivery Lead klienta, u którego osoba pracuje, gdy jej CV
    # idzie do innego klienta albo zostaje tam zatrudniona. Własny typ
    # dzwonka i własni odbiorcy — niezależnie od reguł etapu niżej. Tu, bo
    # przez tę funkcję przechodzi każdy ruch (pojedynczy, zbiorczy, automat,
    # podpis w Generatorze).
    await notify_current_client_leads(
        db,
        new_stage=new_stage,
        previous_stage=previous_stage,
        job=job,
        candidate=candidate,
        mover=mover,
        hired_engagement=hired_engagement,
    )
    try:
        recipients: list[ResolvedRecipient] = await resolve_recipients(
            db,
            new_stage=new_stage,
            previous_stage=previous_stage,
            job=job,
            candidate=candidate,
            mover_user_id=mover.id if mover else None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "stage_notif: resolver failed for stage=%s: %s", new_stage.id, exc
        )
        return 0

    if not recipients:
        return 0

    candidate_full = _candidate_full_name(candidate)
    candidate_first = _candidate_first_name(candidate)

    try:
        client_name = await _client_name(db, job)
    except Exception as exc:  # noqa: BLE001
        logger.warning("stage_notif: client name lookup failed: %s", exc)
        client_name = None

    try:
        remark = await stage_remarks.for_stage(db, new_stage.id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("stage_notif: remark lookup failed: %s", type(exc).__name__)
        remark = None
    try:
        fix_labels = (
            await screening_fix_requests.labels_for_stages(
                db, [new_stage.id], candidate_ids=[new_stage.candidate_id]
            )
        ).get(new_stage.id, [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("stage_notif: fix labels lookup failed: %s", type(exc).__name__)
        fix_labels = []

    emitted_inapp = 0
    for rec in recipients:
        if rec.notify_inapp:
            try:
                if await _send_inapp(
                    db,
                    user_id=rec.user_id,
                    candidate=candidate,
                    candidate_full_name=candidate_full,
                    stage_display_name=stage_display_name,
                    job=job,
                    new_stage=new_stage,
                    mover=mover,
                    reason=getattr(rec, "reason", None),
                    remark=remark,
                    fix_labels=fix_labels,
                ):
                    emitted_inapp += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "stage_notif: in-app emit failed user=%s stage=%s: %s",
                    rec.user_id,
                    new_stage.id,
                    exc,
                )

        if rec.notify_email:
            try:
                if not (await load_policy(db)).allows(
                    "pipeline_stage", new_stage.moved_at
                ):
                    continue
                # Ta sama bramka odbiorcy co dzwonek (`emit`): nieaktywne
                # konto, wyciszona kategoria albo odebrana sekcja = bez maila.
                # Do 25.09.2026 mail sprawdzał tylko politykę dostarczania,
                # więc wyciszony rekruter i konto bez sekcji Pipeline dalej
                # dostawały nazwisko kandydata pocztą (audyt R3-3).
                if not await notification_recipient_has_access(
                    db,
                    rec.user_id,
                    NotificationType.stage_rule,
                    related_entity_type="candidate_stage",
                    link=f"/candidates/{candidate.id}",
                ):
                    logger.debug(
                        "stage_notif: email skipped — user=%s not eligible",
                        rec.user_id,
                    )
                    continue
                user = await _user_by_id(db, rec.user_id)
                if user is None:
                    logger.debug(
                        "stage_notif: email skipped — user=%s not found",
                        rec.user_id,
                    )
                    continue
                # Blocking smtplib send (+ template render) — offload so the
                # per-recipient loop does not block the event loop.
                await run_in_threadpool(
                    _send_email_for_recipient,
                    user=user,
                    candidate=candidate,
                    candidate_full_name=candidate_full,
                    candidate_first_name=candidate_first,
                    stage_display_name=stage_display_name,
                    client_name=client_name,
                    job=job,
                    mover=mover,
                    new_stage=new_stage,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "stage_notif: email failed user=%s stage=%s: %s",
                    rec.user_id,
                    new_stage.id,
                    exc,
                )

    return emitted_inapp


__all__ = ["notify_stage_change"]
