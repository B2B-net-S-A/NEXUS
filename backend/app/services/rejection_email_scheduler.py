"""Schedules + dispatches candidate-rejection emails.

Two entry points:
- `maybe_schedule()` — called from pipeline.move after a stage is flushed.
  Decides whether the rejection qualifies (previous stage is client-visible,
  candidate has email, job has a recruiter), renders the template with a
  snapshot of "other active processes", and inserts a ScheduledRejectionEmail
  row with `scheduled_at = now + 15min`.
- `dispatch()` — called from the background loop when `scheduled_at` is due.
  Re-verifies the candidate is STILL rejected (defense-in-depth: a restore via
  `/bulk-move` or verification-revert doesn't cancel the queued mail), resolves
  the recruiter's M365 connection and sends via `m365_sender.send_new`, with
  retry/backoff on failure and `status=skipped` when no mailbox is connected.

Business rule for the trigger: we fire when the *previous* stage was
`{cv_sent, client_interview, acceptance, negotiation, onboarding}` — i.e. the
candidate was visible to the client. This includes `cv_sent` even though its
`STAGE_CATEGORY` label is `internal`; semantically "CV sent to client" =
client-visible, which is what the user feedback captures.

Template body is a string snapshot taken at schedule time (renderer lives in
this module; no Jinja dependency). Placeholders are double-braced:
`{{candidate_name}}`, `{{job_title}}`, `{{recruiter_name}}`,
`{{other_processes_count}}`, `{{other_processes_list}}`, plus a conditional
block `{{#if other_processes}}...{{/if}}` stripped when there are none.

Od 13.10.2026 (decyzje Artura D1–D6) treść domyślna żyje w kodzie
(`_DEFAULT_SUBJECT`/`_DEFAULT_BODY`, bez pożegnania — podpis dokleja Outlook),
okno odrzucenia pokazuje ją przed wysyłką (`preview`), a rekruter może ją
poprawić przy jednej osobie (`maybe_schedule(edited_subject=…, edited_body=…)`).
Szablony odrzucenia z Ustawień nie są czytane — tylko jawny `override_id`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from html import escape as html_escape
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import user_can_access_candidate_domain
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.email_template import EmailCategory, EmailTemplate
from app.models.job import Job
from app.models.m365 import M365Connection
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.rejection_email import (
    RejectionEmailStatus,
    ScheduledRejectionEmail,
)
from app.models.user import User
from app.services.m365.access import M365OwnerIneligible, eligible_m365_owner
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    resolve_effective_section_access,
    section_access_for_user,
)

logger = logging.getLogger(__name__)


# Stages after which a rejection notifies the candidate. `cv_sent` is
# intentionally included even though STAGE_CATEGORY labels it `internal` —
# business-wise, once CV is out to the client, the candidate is visible.
TRIGGER_PREVIOUS_STAGES: frozenset[PipelineStage] = frozenset(
    {
        PipelineStage.cv_sent,
        PipelineStage.client_interview,
        PipelineStage.acceptance,
        PipelineStage.negotiation,
        PipelineStage.onboarding,
    }
)

# Kolumny Tablicy, z których osoba była widoczna dla klienta — ta sama reguła
# po kolumnie (``board_column_for``), którą czyta okno odrzucenia
# (`frontend/src/lib/rejection-email.ts`). Runda 9 (R9-N11-2): etapy
# rozpoznawane po nazwie („Po Interview”, „Umowa wysłana”) mają kod
# `interview`/`new`, więc sam kod gubił je po jednej stronie.
TRIGGER_PREVIOUS_COLUMNS: frozenset[str] = frozenset(
    {"cv_sent", "client_interview", "contract"}
)

# Powody, dla których zaznaczony mail odrzucenia NIE został zaplanowany —
# `POST /api/pipeline/move` oddaje je w `rejection_email_status`.
EMAIL_STATUS_SCHEDULED = "scheduled"
EMAIL_SKIP_NOT_CLIENT_VISIBLE = "not_client_visible"
EMAIL_SKIP_NO_CANDIDATE_EMAIL = "no_candidate_email"
EMAIL_SKIP_NO_PERMISSION = "no_permission"
EMAIL_SKIP_NO_MAILBOX = "no_mailbox"

# Znacznik w `last_error` wiersza `pending`, którego wysyłka już ruszyła
# (rezerwacja zatwierdzona przed Graphem). Takiego wiersza nie da się
# anulować — mail mógł już wyjść (runda 9, R9-N10-10).
SEND_IN_PROGRESS = "send_in_progress"


def send_in_progress(row: ScheduledRejectionEmail) -> bool:
    """Wysyłka tego wiersza ruszyła — anulowanie niczego by nie cofnęło."""
    return (
        row.status == RejectionEmailStatus.pending
        and row.last_error == SEND_IN_PROGRESS
    )


def _can_send_rejection_email(user: User) -> bool:
    """Require both the candidate persona and current Pipeline write access."""

    return (
        user_can_access_candidate_domain(user)
        and section_access_for_user(user, ProductSection.pipeline)
        >= SectionAccess.write
    )


async def _mark_permission_revoked(
    db: AsyncSession,
    row: ScheduledRejectionEmail,
    *,
    reason: str,
) -> None:
    """Terminate queued external communication after an authorization revoke."""

    row.status = RejectionEmailStatus.skipped
    row.last_error = reason
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=getattr(row, "candidate_id", 0),
            action="rejection_email_skipped",
            user_id=row.recruiter_id,
            details={
                "scheduled_rejection_email_id": row.id,
                "job_id": getattr(row, "job_id", None),
                "reason": reason,
            },
        )
    )
    await db.flush()
    await db.commit()


# Stages considered "active" when listing OTHER processes the candidate is
# still in. Terminal stages are excluded.
ACTIVE_OTHER_STAGES_EXCLUDE: frozenset[PipelineStage] = frozenset(
    {PipelineStage.rejected, PipelineStage.withdrawn, PipelineStage.hired}
)

DELAY_MINUTES = 15
MAX_ATTEMPTS = 3
# Dzierżawa wiersza na czas wysyłki (rezerwacja commitowana przed Graphem
# zdejmuje blokadę FOR UPDATE). Dłuższa niż najdłuższa wysyłka z ponowieniami.
SEND_LEASE_MINUTES = 30


# ── Public API ──────────────────────────────────────────────────────────────


def previous_is_client_visible(
    legacy: Optional[str],
    *,
    name: Optional[str] = None,
    category: Optional[str] = None,
    terminal_type: Optional[str] = None,
) -> bool:
    """Czy osoba z tego etapu była widoczna dla klienta (reguła maila)."""
    from app.services.board_stage_badges import board_column_for

    if legacy is not None and legacy in {s.value for s in TRIGGER_PREVIOUS_STAGES}:
        return True
    return (
        board_column_for(name, legacy, category=category, terminal_type=terminal_type)
        in TRIGGER_PREVIOUS_COLUMNS
    )


async def sender_has_mailbox(db: AsyncSession, user_id: int) -> bool:
    """Aktywne połączenie Microsoft 365 osoby, z której skrzynki wyjdzie mail."""
    return bool(
        await db.scalar(
            select(M365Connection.id)
            .where(
                M365Connection.user_id == user_id,
                M365Connection.is_active.is_(True),
            )
            .limit(1)
        )
    )


async def skip_reason(
    db: AsyncSession, *, stage: CandidateStage, sender: User
) -> Optional[str]:
    """Dlaczego zaznaczony mail odrzucenia NIE zostanie zaplanowany (albo None).

    Runda 9 (R9-N11-1): mail wychodzi ze skrzynki osoby, która odrzuca — nie
    prowadzącego rekrutacji. Bez podłączonej skrzynki nic nie planujemy
    i mówimy to wprost (dotąd mail szedł z cudzej skrzynki albo przepadał
    po cichu na `skipped` po 15 minutach).
    """
    if not await _previous_row_client_visible(db, stage):
        return EMAIL_SKIP_NOT_CLIENT_VISIBLE
    candidate = await db.get(Candidate, stage.candidate_id)
    if candidate is None or not candidate.email:
        return EMAIL_SKIP_NO_CANDIDATE_EMAIL
    return await _sender_skip_reason(db, sender)


async def _sender_skip_reason(db: AsyncSession, sender: User) -> Optional[str]:
    """Powód po stronie nadawcy — ten sam dla każdej odrzucanej osoby."""
    await resolve_effective_section_access(db, sender)
    if not _can_send_rejection_email(sender):
        return EMAIL_SKIP_NO_PERMISSION
    if not await sender_has_mailbox(db, sender.id):
        return EMAIL_SKIP_NO_MAILBOX
    return None


@dataclass(frozen=True)
class PreviewPerson:
    candidate_id: int
    to_email: Optional[str]
    skip_reason: Optional[str]


@dataclass(frozen=True)
class RejectionEmailPreview:
    """Podgląd maila w oknie odrzucenia (13.10.2026).

    ``subject``/``body`` — zwykły tekst dla pierwszej osoby, do której mail
    wyjdzie (``None``, gdy do nikogo). Przy kilku osobach okno pokazuje go
    tylko do odczytu; każda osoba dostaje swoje imię przy wysyłce.
    """

    subject: Optional[str]
    body: Optional[str]
    people: list[PreviewPerson]


async def preview(
    db: AsyncSession,
    *,
    job: Job,
    candidate_ids: Sequence[int],
    sender: User,
) -> RejectionEmailPreview:
    """Co wyjdzie po odrzuceniu tych osób — przed potwierdzeniem.

    Te same reguły i ta sama kolejność powodów co ``skip_reason`` przy ruchu,
    tylko o BIEŻĄCYM wierszu pary (osoba jeszcze nie jest odrzucona).
    Osoba bez wiersza w tej rekrutacji albo już zamknięta = ``not_client_visible``.
    """
    from app.models.pipeline_template import PipelineStageDef

    ids = list(dict.fromkeys(candidate_ids))
    latest = (
        select(
            CandidateStage.candidate_id.label("candidate_id"),
            CandidateStage.stage.label("stage"),
            CandidateStage.stage_def_id.label("stage_def_id"),
            func.row_number()
            .over(
                partition_by=CandidateStage.candidate_id,
                order_by=(CandidateStage.moved_at.desc(), CandidateStage.id.desc()),
            )
            .label("rn"),
        )
        .where(
            CandidateStage.job_id == job.id,
            CandidateStage.candidate_id.in_(ids),
        )
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                latest.c.candidate_id,
                latest.c.stage,
                PipelineStageDef.name,
                PipelineStageDef.category,
                PipelineStageDef.terminal_type,
            )
            .outerjoin(PipelineStageDef, PipelineStageDef.id == latest.c.stage_def_id)
            .where(latest.c.rn == 1)
        )
    ).all()
    visible = {
        candidate_id
        for candidate_id, stage, name, category, terminal_type in rows
        if previous_is_client_visible(
            getattr(stage, "value", stage),
            name=name,
            category=getattr(category, "value", category),
            terminal_type=getattr(terminal_type, "value", terminal_type),
        )
    }
    candidates = {
        c.id: c
        for c in (
            await db.scalars(select(Candidate).where(Candidate.id.in_(ids)))
        ).all()
    }
    sender_reason = await _sender_skip_reason(db, sender)

    people: list[PreviewPerson] = []
    first_ok: Optional[Candidate] = None
    for candidate_id in ids:
        candidate = candidates.get(candidate_id)
        email = (candidate.email or None) if candidate is not None else None
        if candidate_id not in visible:
            reason: Optional[str] = EMAIL_SKIP_NOT_CLIENT_VISIBLE
        elif not email:
            reason = EMAIL_SKIP_NO_CANDIDATE_EMAIL
        else:
            reason = sender_reason
        if reason is None and first_ok is None:
            first_ok = candidate
        people.append(
            PreviewPerson(candidate_id=candidate_id, to_email=email, skip_reason=reason)
        )

    subject: Optional[str] = None
    body: Optional[str] = None
    if first_ok is not None:
        subject, body = default_text(candidate=first_ok, job=job, recruiter=sender)
    return RejectionEmailPreview(subject=subject, body=body, people=people)


async def maybe_schedule(
    db: AsyncSession,
    *,
    stage: CandidateStage,
    job: Job,
    recruiter_id: Optional[int],
    template_override_id: Optional[int] = None,
    edited_subject: Optional[str] = None,
    edited_body: Optional[str] = None,
) -> Optional[ScheduledRejectionEmail]:
    """Maybe schedule a rejection email for a freshly-created rejected stage.

    Returns the scheduled row on success, or None when the rejection
    doesn't qualify (early-internal stage, no candidate email, no recruiter,
    no M365 connection yet etc.). Caller must have flushed `stage` so
    `stage.id` is populated.

    Any exception is allowed to propagate — rejection_email scheduling is
    not critical path for the pipeline move, but we want transactional
    consistency: if scheduling fails mid-way we let the whole move roll back.

    ``edited_subject``/``edited_body`` — temat i treść poprawione w oknie
    odrzucenia (zwykły tekst, sprawdzony przez ``StageMove``). Wysyłamy je
    dokładnie tak, treść zawsze z escape (``plain_text_to_html``).
    """
    if stage.stage != PipelineStage.rejected:
        return None
    if recruiter_id is None:
        return None

    if not await _previous_row_client_visible(db, stage):
        return None

    candidate = await db.get(Candidate, stage.candidate_id)
    if candidate is None or not candidate.email:
        return None

    recruiter = await db.get(User, recruiter_id)
    if recruiter is None:
        return None
    await resolve_effective_section_access(db, recruiter)
    if not _can_send_rejection_email(recruiter):
        return None

    other_processes = await _load_other_active_processes(
        db, candidate_id=stage.candidate_id, current_job_id=stage.job_id
    )

    edited = bool(edited_subject or edited_body)
    template = None if edited else await _resolve_template(db, template_override_id)
    subject, body_html = _render(
        template=template,
        candidate=candidate,
        job=job,
        recruiter=recruiter,
        other_processes=other_processes,
    )
    if edited_subject:
        subject = edited_subject
    if edited_body:
        from app.services.email_template_variables import plain_text_to_html

        body_html = plain_text_to_html(edited_body)

    scheduled = ScheduledRejectionEmail(
        candidate_stage_id=stage.id,
        candidate_id=candidate.id,
        job_id=job.id,
        recruiter_id=recruiter_id,
        to_email=candidate.email,
        subject=subject,
        body_html=body_html,
        other_processes=other_processes,
        template_id=template.id if template else None,
        status=RejectionEmailStatus.pending,
        scheduled_at=datetime.now(timezone.utc) + timedelta(minutes=DELAY_MINUTES),
    )
    db.add(scheduled)
    await db.flush()

    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate.id,
            action="rejection_email_scheduled",
            user_id=recruiter_id,
            details={
                "scheduled_rejection_email_id": scheduled.id,
                "job_id": job.id,
                "candidate_stage_id": stage.id,
                "to_email": candidate.email,
                "scheduled_at": scheduled.scheduled_at.isoformat(),
                "other_processes_count": len(other_processes),
                "edited": edited,
            },
        )
    )

    db.add(
        Notification(
            user_id=recruiter_id,
            title="Zaplanowano email odrzucenia",
            message=(
                f"Email odrzucenia do {candidate.name} {candidate.lastname} "
                f"zostanie wysłany za {DELAY_MINUTES} minut. Masz czas aby anulować."
            ),
            link=f"/candidates/{candidate.id}",
            notification_type=NotificationType.rejection_email_scheduled,
            related_entity_type="scheduled_rejection_email",
            related_entity_id=scheduled.id,
        )
    )

    return scheduled


async def dispatch(db: AsyncSession, row_id: int) -> None:
    """Dispatch one scheduled rejection email (sent/skipped/failed transition).

    Called from the background loop. Uses `SELECT ... FOR UPDATE SKIP LOCKED`
    so parallel loop iterations (e.g. during HA deploys) don't double-send.
    Caller owns the session and the commit — we flush and let the loop's
    context manager commit on success or rollback on exception.
    """
    row = await db.scalar(
        select(ScheduledRejectionEmail)
        .where(ScheduledRejectionEmail.id == row_id)
        .with_for_update(skip_locked=True)
    )
    if row is None:
        logger.info("rejection_email_dispatch: row %s already locked or gone", row_id)
        return
    # Re-check — status may have changed (cancelled) between loop's SELECT
    # pass and FOR UPDATE acquisition.
    if row.status != RejectionEmailStatus.pending:
        logger.info(
            "rejection_email_dispatch: row %s skipped (status=%s)", row_id, row.status
        )
        return

    # Queued work can outlive a role cutover.  Treat current RBAC as the
    # authorization source and terminate the queue row without retrying or
    # notifying the now-Finance/viewer account with candidate PII.
    owner = await eligible_m365_owner(db, row.recruiter_id)
    if owner is None:
        await _mark_permission_revoked(
            db,
            row,
            reason="m365_owner_outside_candidate_domain",
        )
        logger.warning(
            "rejection_email_dispatch: row %s skipped — owner outside candidate domain",
            row_id,
        )
        return
    if not _can_send_rejection_email(owner):
        await _mark_permission_revoked(
            db,
            row,
            reason="pipeline_write_access_revoked",
        )
        logger.warning(
            "rejection_email_dispatch: row %s skipped — Pipeline write access revoked",
            row_id,
        )
        return

    # Defense-in-depth (audyt P1.7): NIE wysyłaj, jeśli kandydat został w
    # międzyczasie PRZYWRÓCONY z odrzucenia. Ścieżka `/move` anuluje pending
    # maile przy ruchu na etap nieterminalny, ale inne ścieżki (np. `/bulk-move`,
    # revert weryfikacji) tego nie robią — a każda przyszła ścieżka też mogłaby
    # ominąć anulowanie. Sprawdzamy AKTUALNY (najnowszy) etap pary
    # (candidate, job) tuż przed wysyłką; jeśli to już nie `rejected`, kandydat
    # wrócił do procesu → oznaczamy mail jako cancelled i nic nie wysyłamy.
    current_stage = await db.scalar(
        select(CandidateStage.stage)
        .where(
            CandidateStage.candidate_id == row.candidate_id,
            CandidateStage.job_id == row.job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )
    if current_stage != PipelineStage.rejected:
        current_stage_label = getattr(current_stage, "value", current_stage)
        row.status = RejectionEmailStatus.cancelled
        row.cancelled_at = datetime.now(timezone.utc)
        row.last_error = f"candidate_restored:current_stage={current_stage_label}"
        db.add(
            Activity(
                entity_type="candidate",
                entity_id=row.candidate_id,
                action="rejection_email_cancelled_on_restore",
                user_id=row.recruiter_id,
                details={
                    "scheduled_rejection_email_id": row.id,
                    "job_id": row.job_id,
                    "reason": "candidate_no_longer_rejected_at_dispatch",
                    "current_stage": current_stage_label,
                },
            )
        )
        await db.flush()
        await db.commit()
        logger.info(
            "rejection_email_dispatch: row %s cancelled — candidate restored "
            "(current_stage=%s)",
            row_id,
            current_stage_label,
        )
        return

    connection = await db.scalar(
        select(M365Connection).where(
            M365Connection.user_id == row.recruiter_id,
            M365Connection.is_active.is_(True),
        )
    )
    if connection is None:
        row.status = RejectionEmailStatus.skipped
        row.last_error = "no_active_m365_connection"
        db.add(
            Activity(
                entity_type="candidate",
                entity_id=row.candidate_id,
                action="rejection_email_skipped",
                user_id=row.recruiter_id,
                details={
                    "scheduled_rejection_email_id": row.id,
                    "reason": "no_active_m365_connection",
                },
            )
        )
        db.add(
            Notification(
                user_id=row.recruiter_id,
                title="Email odrzucenia niewysłany",
                message=(
                    "Skrzynka Microsoft 365 nie jest podłączona. "
                    "Kandydat nie otrzymał powiadomienia o odrzuceniu. "
                    "Podłącz skrzynkę w Ustawieniach → Integracje."
                ),
                link="/settings?tab=integracje",
                notification_type=NotificationType.rejection_email_skipped,
                related_entity_type="scheduled_rejection_email",
                related_entity_id=row.id,
            )
        )
        await db.flush()
        await db.commit()
        return

    # Deferred import — keeps scheduler importable without the heavy M365
    # dependency chain (msal, etc.) in unit-test environments.
    from app.services.m365 import sender as m365_sender

    # Re-read immediately before entering the Graph sender. Queued work may
    # spend time behind row locks or other due emails after the first check.
    owner = await eligible_m365_owner(db, row.recruiter_id)
    if owner is None or not _can_send_rejection_email(owner):
        await _mark_permission_revoked(
            db,
            row,
            reason=(
                "pipeline_write_access_revoked"
                if owner is not None
                else "m365_owner_outside_candidate_domain"
            ),
        )
        logger.warning(
            "rejection_email_dispatch: row %s skipped — authorization changed before send",
            row_id,
        )
        return

    # Rezerwacja wysyłki (wiersz ``Email`` z kluczem ``scheduled-rejection:
    # {id}``) jest commitowana PRZED Graphem, jak w pozostałych ścieżkach
    # wysyłki. Bez tego rezerwacja żyła w transakcji harmonogramu: anulowanie
    # zadania albo padnięty commit po udanej wysyłce cofały ją razem z tą
    # transakcją, wiersz zostawał ``pending`` i następny bieg pętli wysyłał
    # kandydatowi DRUGI mail odrzucenia (audyt 25.09.2026, R3-6).
    # Commit zdejmuje blokadę FOR UPDATE, więc wiersz harmonogramu dostaje
    # dzierżawę: pętla bierze tylko ``scheduled_at <= now()``. Gdy proces
    # zginie w trakcie, po dzierżawie ponowienie trafia w zapisaną rezerwację
    # (``EmailSendConflict``) i zamyka wiersz jako „nie wiadomo” — bez maila.
    row.scheduled_at = datetime.now(timezone.utc) + timedelta(
        minutes=SEND_LEASE_MINUTES
    )
    # Runda 9 (R9-N10-10): znacznik „wysyłka ruszyła” zatwierdzony razem
    # z rezerwacją — `/cancel` i ruch przywracający kandydata nie mogą już
    # odpowiedzieć „Anulowano”, gdy mail za chwilę (albo właśnie) wychodzi.
    row.last_error = SEND_IN_PROGRESS
    await db.flush()

    send_error: Optional[Exception] = None
    try:
        email = await m365_sender.send_new(
            db,
            connection,
            to=[row.to_email],
            subject=row.subject,
            body_html=row.body_html,
            candidate_id=row.candidate_id,
            # audyt 22.09 r2 (FIX-03): STAŁY klucz intencji per wiersz
            # harmonogramu. Klucz minutowy dawał po ponowieniu nowy odcisk,
            # więc drugi mail odrzucenia wychodził do kandydata.
            client_request_id=f"scheduled-rejection:{row.id}",
            commit_reservation=True,
        )
    except m365_sender.EmailSendConflict as conflict:
        # Graph mógł już wysłać maila (utracona odpowiedź) albo wysyłka z tym
        # kluczem jest w toku. NIE ponawiamy — drugi mail odrzucenia do
        # kandydata jest gorszy niż żaden. Wiersz ``Email`` w stanie
        # ``uncertain`` zostaje w bazie (commit), więc ewentualne ponowienie
        # i tak trafi w istniejący klucz, a rekruter dostaje prośbę
        # o sprawdzenie folderu Wysłane.
        await _mark_send_outcome_unknown(db, row, conflict)
        logger.warning(
            "rejection_email_dispatch: row %s send outcome %s — no retry",
            row_id,
            conflict.state,
        )
        return
    except M365OwnerIneligible:
        # Close the narrow TOCTOU gap between the explicit role check above
        # and the sender/Graph execution boundary. This is terminal, not a
        # provider failure, so never enqueue retries or candidate notifications.
        row.status = RejectionEmailStatus.skipped
        row.last_error = "m365_owner_outside_candidate_domain"
        await db.flush()
        await db.commit()
        logger.warning(
            "rejection_email_dispatch: row %s skipped — owner changed before send",
            row_id,
        )
        return
    except Exception as exc:  # noqa: BLE001 — Graph raises a menagerie
        send_error = exc
        email = None

    if send_error is not None:
        # Roll back any partial state from the sender (e.g. draft row) and
        # re-acquire the scheduled row on a fresh transaction so we can write
        # retry/failed bookkeeping.
        await db.rollback()
        retry_row = await db.get(ScheduledRejectionEmail, row_id)
        if retry_row is None:
            return
        retry_row.attempts = (retry_row.attempts or 0) + 1
        retry_row.last_error = str(send_error)[:2000]
        if retry_row.attempts >= MAX_ATTEMPTS:
            retry_row.status = RejectionEmailStatus.failed
            db.add(
                Activity(
                    entity_type="candidate",
                    entity_id=retry_row.candidate_id,
                    action="rejection_email_failed",
                    user_id=retry_row.recruiter_id,
                    details={
                        "scheduled_rejection_email_id": retry_row.id,
                        "attempts": retry_row.attempts,
                        "last_error": retry_row.last_error,
                    },
                )
            )
            db.add(
                Notification(
                    user_id=retry_row.recruiter_id,
                    title="Email odrzucenia — błąd wysyłki",
                    message=(
                        f"Nie udało się wysłać emaila po {retry_row.attempts} "
                        "próbach. Sprawdź logi i połączenie z Microsoft 365."
                    ),
                    link=f"/candidates/{retry_row.candidate_id}",
                    notification_type=NotificationType.rejection_email_failed,
                    related_entity_type="scheduled_rejection_email",
                    related_entity_id=retry_row.id,
                )
            )
        else:
            # Back off exponentially (5min × 2^attempts).
            retry_row.scheduled_at = datetime.now(timezone.utc) + timedelta(
                minutes=5 * (2**retry_row.attempts)
            )
        await db.flush()
        await db.commit()
        return

    # Rezerwacja zdjęła blokadę FOR UPDATE — wynik zapisujemy pod ponowną
    # blokadą wiersza. Status inny niż `pending` (anulowanie mimo znacznika,
    # np. starszą wersją API) nie cofa faktu: mail wyszedł, więc wiersz mówi
    # „wysłany”, a ślad zapisuje, co go próbowało zatrzymać.
    await db.refresh(row, with_for_update=True)
    status_before = row.status
    row.status = RejectionEmailStatus.sent
    row.sent_at = datetime.now(timezone.utc)
    row.email_id = email.id
    row.last_error = None
    sent_details: dict = {
        "scheduled_rejection_email_id": row.id,
        "email_id": email.id,
        "to": row.to_email,
    }
    if status_before != RejectionEmailStatus.pending:
        sent_details["status_before_send_result"] = getattr(
            status_before, "value", status_before
        )
        logger.warning(
            "rejection_email_dispatch: row %s sent although status was %s",
            row_id,
            getattr(status_before, "value", status_before),
        )
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=row.candidate_id,
            action="rejection_email_sent",
            user_id=row.recruiter_id,
            details=sent_details,
        )
    )
    db.add(
        Notification(
            user_id=row.recruiter_id,
            title="Email odrzucenia wysłany",
            message=f"Kandydat {row.to_email} otrzymał powiadomienie.",
            link=f"/candidates/{row.candidate_id}",
            notification_type=NotificationType.rejection_email_sent,
            related_entity_type="scheduled_rejection_email",
            related_entity_id=row.id,
        )
    )
    await db.flush()
    await db.commit()


# ── Internals ───────────────────────────────────────────────────────────────


async def _mark_send_outcome_unknown(
    db: AsyncSession, row: ScheduledRejectionEmail, conflict: Exception
) -> None:
    """Wynik wysyłki nieznany — zamknij wiersz bez ponowień (FIX-03)."""
    state = getattr(conflict, "state", "uncertain")
    email_id = getattr(conflict, "email_id", None)
    row.status = RejectionEmailStatus.failed
    row.last_error = f"send_outcome_{state}"
    if email_id is not None:
        row.email_id = email_id
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=row.candidate_id,
            action="rejection_email_uncertain",
            user_id=row.recruiter_id,
            details={
                "scheduled_rejection_email_id": row.id,
                "email_id": email_id,
                "send_state": state,
            },
        )
    )
    await db.flush()
    notification = Notification(
        user_id=row.recruiter_id,
        title="Email odrzucenia — sprawdź folder Wysłane",
        message=(
            "Nie wiadomo, czy email odrzucenia wyszedł do kandydata "
            "(Microsoft 365 nie potwierdził wysyłki). Sprawdź folder "
            "Wysłane w Outlooku — NEXUS nie wyśle go ponownie."
        ),
        link=f"/candidates/{row.candidate_id}",
        notification_type=NotificationType.rejection_email_failed,
        related_entity_type="scheduled_rejection_email",
        related_entity_id=row.id,
    )
    # Dzienny dedup powiadomień (ix_notif_dedup_daily) nie może wycofać
    # zamknięcia wiersza — savepoint tylko wokół powiadomienia.
    try:
        async with db.begin_nested():
            db.add(notification)
    except IntegrityError:
        logger.info(
            "rejection_email_dispatch: uncertain notification for row %s "
            "already sent today",
            row.id,
        )
    await db.commit()


async def _previous_row_client_visible(
    db: AsyncSession, current: CandidateStage
) -> bool:
    """Poprzedni wiersz pary (przed odrzuceniem) — widoczny dla klienta?

    Runda 10 (R10-V2-9): „poprzedni” w kolejności ``moved_at, id`` — tej
    samej, w której Tablica, okno odrzucenia i ``/move`` wybierają bieżący
    wiersz. Import Traffita dopisuje wiersze historyczne (starszy
    ``moved_at``, wyższe id), więc kolejność po samym id wskazywała import
    „Nowi” zamiast „CV wysłane”.
    """
    from app.models.pipeline_template import PipelineStageDef

    if current.moved_at is None:
        before = CandidateStage.id < current.id
    else:
        before = or_(
            CandidateStage.moved_at < current.moved_at,
            and_(
                CandidateStage.moved_at == current.moved_at,
                CandidateStage.id < current.id,
            ),
        )

    row = (
        await db.execute(
            select(
                CandidateStage.stage,
                PipelineStageDef.name,
                PipelineStageDef.category,
                PipelineStageDef.terminal_type,
            )
            .outerjoin(
                PipelineStageDef, PipelineStageDef.id == CandidateStage.stage_def_id
            )
            .where(
                CandidateStage.candidate_id == current.candidate_id,
                CandidateStage.job_id == current.job_id,
                CandidateStage.id != current.id,
                before,
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return False
    stage, name, category, terminal_type = row
    return previous_is_client_visible(
        getattr(stage, "value", stage),
        name=name,
        category=getattr(category, "value", category),
        terminal_type=getattr(terminal_type, "value", terminal_type),
    )


async def _load_other_active_processes(
    db: AsyncSession, *, candidate_id: int, current_job_id: int
) -> list[dict]:
    """Return [{"job_id": int, "title": str}, ...] for the candidate's OTHER
    processes that are still in front of a client.

    Uses a window function (ROW_NUMBER OVER PARTITION BY job_id) to pick
    the LATEST stage row per (candidate, job) — critical so that a
    candidate who has been through multiple stages on a job is classified
    by their CURRENT position, not any historical row.

    Runda 9 (R9-N10-2): mail idzie do kandydata, więc lista nie może zdradzać
    więcej niż strona kariery. Wchodzą wyłącznie rekrutacje OPUBLIKOWANE,
    w których osoba jest dziś u klienta (kolumny „CV wysłane”, „Rozmowa
    u klienta”, „Umowa”), a tytuł pochodzi WYŁĄCZNIE z zatwierdzonego opisu
    publicznego. Rekrutacja bez niego nie trafia na listę — `jobs.title`
    niesie nazwę klienta i numery zapytań (do 26.09 lista brała też
    zamknięte i archiwalne rekrutacje z Traffita).
    """
    from app.models.job import JobStatus
    from app.models.job_public_profile import JobPublicProfile
    from app.models.pipeline_template import PipelineStageDef
    from app.services.job_public_profile import STATUS_APPROVED, resolve_status

    latest = (
        select(
            CandidateStage.job_id.label("job_id"),
            CandidateStage.stage.label("stage"),
            CandidateStage.stage_def_id.label("stage_def_id"),
            func.row_number()
            .over(
                partition_by=CandidateStage.job_id,
                order_by=(CandidateStage.moved_at.desc(), CandidateStage.id.desc()),
            )
            .label("rn"),
        )
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id != current_job_id,
        )
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                Job,
                latest.c.stage,
                PipelineStageDef.name,
                PipelineStageDef.category,
                PipelineStageDef.terminal_type,
            )
            .join(latest, latest.c.job_id == Job.id)
            .outerjoin(PipelineStageDef, PipelineStageDef.id == latest.c.stage_def_id)
            .where(
                latest.c.rn == 1,
                Job.status == JobStatus.published,
                ~latest.c.stage.in_([s.value for s in ACTIVE_OTHER_STAGES_EXCLUDE]),
            )
            .order_by(Job.id)
        )
    ).all()
    out: list[dict] = []
    names_cache: dict = {}
    for job, stage, name, category, terminal_type in rows:
        column_ok = previous_is_client_visible(
            getattr(stage, "value", stage),
            name=name,
            category=getattr(category, "value", category),
            terminal_type=getattr(terminal_type, "value", terminal_type),
        )
        if not column_ok:
            continue
        profile = await db.scalar(
            select(JobPublicProfile).where(JobPublicProfile.job_id == job.id)
        )
        if profile is None:
            continue
        status, _default, effective = await resolve_status(
            db, job, profile, names_cache=names_cache
        )
        if status != STATUS_APPROVED or not effective:
            continue
        out.append({"job_id": job.id, "title": effective})
    return out


async def _resolve_template(
    db: AsyncSession, override_id: Optional[int]
) -> Optional[EmailTemplate]:
    """Szablon wskazany jawnie (``override_id``) albo ``None`` → treść z kodu.

    D6 (13.10.2026): mail automatyczny nie sięga już po szablony odrzucenia
    z Ustawień (nazwany „Auto-odrzucenie…”, domyślny, dowolny). Na produkcji
    żaden nie był używany, a poprawka jednego z nich podmieniłaby po cichu
    treść, którą okno odrzucenia pokazuje rekruterowi.

    Runda 9 (R9-N10-5): szablon ze zmienną, której `_render` nie wypełnia
    (np. `{{company_name}}` z dawnego zasiewu), jest pomijany — kandydat
    dostałby dosłowne `{{company_name}}`.
    """
    from app.services.email_template_variables import unsupported_variables

    if not override_id:
        return None
    override = await db.get(EmailTemplate, override_id)
    # M4 PR-04 (audyt P1.14): override MUSI być templatem kategorii
    # rejection — dotąd dało się podstawić dowolny template (offer,
    # follow-up...) jako "mail odrzucenia". Zły override → treść z kodu
    # + warning, nie cichy send.
    if override is not None and override.category == EmailCategory.rejection:
        missing = unsupported_variables(override.subject, override.body)
        if not missing:
            return override
        logger.warning(
            "rejection template %s pominięty — zmienne bez wartości: %s",
            override.id,
            ", ".join(missing),
        )
        return None
    logger.warning(
        "rejection template override %s odrzucony (brak/kategoria %s) — treść z kodu",
        override_id,
        getattr(override, "category", None),
    )
    return None


def _render(
    *,
    template: Optional[EmailTemplate],
    candidate: Candidate,
    job: Job,
    recruiter: User,
    other_processes: list[dict],
) -> tuple[str, str]:
    """Render (subject, body_html) with placeholders filled.

    Supports two constructs:
      - `{{placeholder}}` — simple string replace.
      - `{{#if other_processes}}...{{/if}}` — kept when other_processes
        is non-empty, stripped (body + tags) otherwise.

    Falls back to a hard-coded subject/body when no template exists (first
    boot before seed).
    """
    from app.services.email_template_variables import body_to_html

    subject_tmpl = template.subject if template else _DEFAULT_SUBJECT
    # Runda 9 (R9-N10-5): szablon z pola tekstowego (bez znaczników) → HTML;
    # wcześniej akapity sklejały się w jedną linię, a `&` szło surowo.
    body_tmpl = body_to_html(template.body if template else _DEFAULT_BODY)

    ctx = _context(
        candidate=candidate,
        job=job,
        recruiter=recruiter,
        other_processes=other_processes,
    )
    # M4 PR-04 (audyt P1.14): body jest HTML-em — wartości placeholderów są
    # escapowane (nazwisko kandydata z "<script>" nie może stać się kodem).
    # Subject to plain text (RFC nagłówek) — encje HTML byłyby tam widoczne.
    body_ctx = {k: html_escape(v) for k, v in ctx.items()}

    return _apply(subject_tmpl, ctx, has_others=bool(other_processes)), _apply(
        body_tmpl, body_ctx, has_others=bool(other_processes)
    )


def default_text(*, candidate: Candidate, job: Job, recruiter: User) -> tuple[str, str]:
    """Temat i treść domyślna jako ZWYKŁY tekst — do pola w oknie odrzucenia.

    Bez escape: pole tekstowe pokazuje `R&D` jako `R&D`. Przy wysyłce tekst
    (poprawiony albo nie) i tak przechodzi przez escape.
    """
    ctx = _context(
        candidate=candidate, job=job, recruiter=recruiter, other_processes=[]
    )
    return (
        _apply(_DEFAULT_SUBJECT, ctx, has_others=False),
        _apply(_DEFAULT_BODY, ctx, has_others=False),
    )


def _context(
    *,
    candidate: Candidate,
    job: Job,
    recruiter: User,
    other_processes: list[dict],
) -> dict[str, str]:
    return {
        "candidate_name": (candidate.name or "").strip(),
        "candidate_lastname": (candidate.lastname or "").strip(),
        "candidate_full_name": f"{candidate.name} {candidate.lastname}".strip(),
        "job_title": (job.title or "").strip(),
        "recruiter_name": (recruiter.name or recruiter.email or "").strip(),
        "other_processes_count": str(len(other_processes)),
        "other_processes_list": ", ".join(
            p["title"] for p in other_processes if p.get("title")
        ),
    }


_IF_BLOCK_RE = re.compile(
    r"\{\{#if\s+other_processes\s*\}\}(.*?)\{\{/if\}\}",
    re.DOTALL,
)


def _apply(template: str, ctx: dict[str, str], *, has_others: bool) -> str:
    """Apply the conditional block + simple placeholders."""

    def _block_sub(m: re.Match[str]) -> str:
        return m.group(1) if has_others else ""

    rendered = _IF_BLOCK_RE.sub(_block_sub, template)
    for key, value in ctx.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


# Treść Artura z 13.10.2026 (D2: „Życzymy”). Zwykły tekst — pusta linia to
# akapit. Bez „Pozdrawiam”: `m365/sender.py` dokleja podpis z Outlooka, więc
# kandydat dostawał dwa pożegnania. Bez bloku „inne procesy” (D4).
_DEFAULT_SUBJECT = "Informacja zwrotna — {{job_title}}"
_DEFAULT_BODY = (
    "Cześć {{candidate_name}},\n"
    "\n"
    "dziękujemy za udział w rekrutacji na stanowisko {{job_title}}. "
    "Niestety został wybrany inny kandydat.\n"
    "\n"
    "Życzymy powodzenia i zachęcamy do udziału w przyszłych procesach "
    "rekrutacyjnych!"
)
