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
"""

from __future__ import annotations

import logging
import re
from html import escape as html_escape
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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

# Stages considered "active" when listing OTHER processes the candidate is
# still in. Terminal stages are excluded.
ACTIVE_OTHER_STAGES_EXCLUDE: frozenset[PipelineStage] = frozenset(
    {PipelineStage.rejected, PipelineStage.withdrawn, PipelineStage.hired}
)

DELAY_MINUTES = 15
MAX_ATTEMPTS = 3


# ── Public API ──────────────────────────────────────────────────────────────


async def maybe_schedule(
    db: AsyncSession,
    *,
    stage: CandidateStage,
    job: Job,
    recruiter_id: Optional[int],
    template_override_id: Optional[int] = None,
) -> Optional[ScheduledRejectionEmail]:
    """Maybe schedule a rejection email for a freshly-created rejected stage.

    Returns the scheduled row on success, or None when the rejection
    doesn't qualify (early-internal stage, no candidate email, no recruiter,
    no M365 connection yet etc.). Caller must have flushed `stage` so
    `stage.id` is populated.

    Any exception is allowed to propagate — rejection_email scheduling is
    not critical path for the pipeline move, but we want transactional
    consistency: if scheduling fails mid-way we let the whole move roll back.
    """
    if stage.stage != PipelineStage.rejected:
        return None
    if recruiter_id is None:
        return None

    previous_stage = await _load_previous_stage(db, stage)
    if previous_stage is None or previous_stage not in TRIGGER_PREVIOUS_STAGES:
        return None

    candidate = await db.get(Candidate, stage.candidate_id)
    if candidate is None or not candidate.email:
        return None

    recruiter = await db.get(User, recruiter_id)
    if recruiter is None:
        return None

    other_processes = await _load_other_active_processes(
        db, candidate_id=stage.candidate_id, current_job_id=stage.job_id
    )

    template = await _resolve_template(db, template_override_id)
    subject, body_html = _render(
        template=template,
        candidate=candidate,
        job=job,
        recruiter=recruiter,
        other_processes=other_processes,
    )

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
                link="/settings/integrations",
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

    send_error: Optional[Exception] = None
    try:
        email = await m365_sender.send_new(
            db,
            connection,
            to=[row.to_email],
            subject=row.subject,
            body_html=row.body_html,
            candidate_id=row.candidate_id,
        )
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

    row.status = RejectionEmailStatus.sent
    row.sent_at = datetime.now(timezone.utc)
    row.email_id = email.id
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=row.candidate_id,
            action="rejection_email_sent",
            user_id=row.recruiter_id,
            details={
                "scheduled_rejection_email_id": row.id,
                "email_id": email.id,
                "to": row.to_email,
            },
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


async def _load_previous_stage(
    db: AsyncSession, current: CandidateStage
) -> Optional[PipelineStage]:
    """Load the stage BEFORE `current` for the same (candidate, job).

    Orders by id DESC (append-only table, id monotonic) and skips the row
    we were just handed.
    """
    prev = await db.scalar(
        select(CandidateStage.stage)
        .where(
            CandidateStage.candidate_id == current.candidate_id,
            CandidateStage.job_id == current.job_id,
            CandidateStage.id < current.id,
        )
        .order_by(CandidateStage.id.desc())
        .limit(1)
    )
    return prev


async def _load_other_active_processes(
    db: AsyncSession, *, candidate_id: int, current_job_id: int
) -> list[dict]:
    """Return [{"job_id": int, "title": str}, ...] for the candidate's OTHER
    active processes.

    Uses a window function (ROW_NUMBER OVER PARTITION BY job_id) to pick
    the LATEST stage row per (candidate, job) — critical so that a
    candidate who has been through multiple stages on a job is classified
    by their CURRENT position, not any historical row. Then filters out
    rows whose latest stage is terminal (rejected/withdrawn/hired).

    `job.client_id` / client name is deliberately NOT exposed (NDA — we
    don't tell a candidate which client they're still in play with).
    """
    latest = (
        select(
            CandidateStage.job_id.label("job_id"),
            CandidateStage.stage.label("stage"),
            func.row_number()
            .over(
                partition_by=CandidateStage.job_id,
                order_by=CandidateStage.id.desc(),
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
            select(Job.id, Job.title)
            .join(latest, latest.c.job_id == Job.id)
            .where(
                latest.c.rn == 1,
                ~latest.c.stage.in_([s.value for s in ACTIVE_OTHER_STAGES_EXCLUDE]),
            )
        )
    ).all()
    return [{"job_id": jid, "title": title or ""} for jid, title in rows]


async def _resolve_template(
    db: AsyncSession, override_id: Optional[int]
) -> Optional[EmailTemplate]:
    """Return the template to use.

    Priority:
      1. explicit override_id (user's choice from the UI),
      2. our named auto-rejection template (supports `{{#if other_processes}}`),
      3. any default rejection template (may not have the conditional block —
         renderer treats it as non-conditional),
      4. any rejection template,
      5. None — renderer falls back to the hard-coded Polish body.
    """
    if override_id:
        override = await db.get(EmailTemplate, override_id)
        # M4 PR-04 (audyt P1.14): override MUSI być templatem kategorii
        # rejection — dotąd dało się podstawić dowolny template (offer,
        # follow-up...) jako "mail odrzucenia". Zły override → fallback na
        # standardową ścieżkę wyboru + warning, nie cichy send.
        if override is not None and override.category == EmailCategory.rejection:
            return override
        logger.warning(
            "rejection template override %s odrzucony (brak/kategoria %s) — fallback",
            override_id,
            getattr(override, "category", None),
        )

    # Deferred import: emails.py pulls fastapi + auth deps; keeps the
    # scheduler importable in lean test contexts.
    from app.api.emails import REJECTION_EXTERNAL_TEMPLATE_NAME

    named = await db.scalar(
        select(EmailTemplate)
        .where(EmailTemplate.name == REJECTION_EXTERNAL_TEMPLATE_NAME)
        .limit(1)
    )
    if named is not None:
        return named

    default_rejection = await db.scalar(
        select(EmailTemplate)
        .where(
            EmailTemplate.category == EmailCategory.rejection,
            EmailTemplate.is_default.is_(True),
        )
        .limit(1)
    )
    if default_rejection is not None:
        return default_rejection

    return await db.scalar(
        select(EmailTemplate)
        .where(EmailTemplate.category == EmailCategory.rejection)
        .order_by(EmailTemplate.id.asc())
        .limit(1)
    )


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
    subject_tmpl = template.subject if template else _DEFAULT_SUBJECT
    body_tmpl = template.body if template else _DEFAULT_BODY

    ctx = {
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
    # M4 PR-04 (audyt P1.14): body jest HTML-em — wartości placeholderów są
    # escapowane (nazwisko kandydata z "<script>" nie może stać się kodem).
    # Subject to plain text (RFC nagłówek) — encje HTML byłyby tam widoczne.
    body_ctx = {k: html_escape(v) for k, v in ctx.items()}

    return _apply(subject_tmpl, ctx, has_others=bool(other_processes)), _apply(
        body_tmpl, body_ctx, has_others=bool(other_processes)
    )


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


_DEFAULT_SUBJECT = "Informacja zwrotna — {{job_title}}"
_DEFAULT_BODY = """<p>Cześć {{candidate_name}},</p>
<p>Dziękujemy za zaangażowanie w proces rekrutacyjny na stanowisko <strong>{{job_title}}</strong>.
Po analizie zebranych informacji zwrotnych podjęliśmy decyzję o zakończeniu współpracy
przy tym konkretnym procesie.</p>
{{#if other_processes}}<p>Nadal rozważamy Cię w <strong>{{other_processes_count}}</strong>
innych otwartych procesach: {{other_processes_list}}. Jeśli pojawią się nowe informacje,
dam znać.</p>{{/if}}
<p>Bardzo dziękuję za poświęcony czas i życzę powodzenia w dalszych poszukiwaniach.</p>
<p>Pozdrawiam,<br>{{recruiter_name}}</p>"""
