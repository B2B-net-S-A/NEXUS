"""Trasy wtyczki LinkedIn (``/api/extension/*``) — decyzja Artura 28.10.2026.

Makiety: https://claude.ai/artifact/1PEmR5Gm5UQTdtRwVCRRg4, kontrakt:
``extension/API.md``, reguły: ``docs/claude/integracje/wtyczka-linkedin.md``.

Dwie klasy tras:

* połączenie i zarządzanie (``/connect``, ``/connections``) — JWT z NEXUSA,
  woła je front (strona „Połącz wtyczkę” i Ustawienia);
* praca na LinkedInie — klucz ``X-Extension-Key`` (``ExtensionAuth``), woła
  je wyłącznie wtyczka. JWT na tych trasach nie działa, a klucz nie działa
  nigdzie indziej.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, RecruiterPlus
from app.api.extension_deps import ExtensionAuth, ExtensionReader, ExtensionWriter
from app.api.section_access import SOURCING_SECTION_DEPENDENCIES
from app.core.config import settings
from app.core.database import get_db
from app.models.client import Client
from app.models.job import Job
from app.models.candidate import Candidate
from app.models.linkedin_extension import LinkedinExtensionConnection
from app.models.user import User, UserRole
from app.schemas.linkedin_extension import (
    AddCandidateRequest,
    AddCandidateResponse,
    AssignJobsRequest,
    AssignJobsResponse,
    BatchRequest,
    BatchResponse,
    ContactRequest,
    ContactResponse,
    DraftRequest,
    DraftResponse,
    IdResponse,
    LookupResponse,
    NoteRequest,
    ProfilePdfResponse,
    ProfileRead,
    RefreshRequest,
    RefreshResponse,
    ConnectRequest,
    ConnectResponse,
    ConnectionAdminOut,
    ConnectionsAdminResponse,
    ExtensionUserBrief,
    JobOption,
    JobOptionsResponse,
    MeResponse,
    UsageOut,
)
from app.core.scheduling import business_today
from app.services import linkedin_extension_lookup as lookup_service
from app.services import linkedin_extension_writes as writes
from app.services.linkedin_extension_auth import (
    DailyLimitReached,
    allowed_extension_ids,
    count_add,
    count_page_read,
    issue_connection,
    roll_day,
)
from app.services.linkedin_message_draft import draft_message

logger = logging.getLogger(__name__)

router = APIRouter()


def initials(name: str) -> str:
    parts = [p for p in (name or "").split() if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


def user_brief(user: User) -> ExtensionUserBrief:
    return ExtensionUserBrief(id=user.id, name=user.name, initials=initials(user.name))


def usage_out(connection: LinkedinExtensionConnection) -> UsageOut:
    today = business_today()
    same_day = connection.usage_day == today
    return UsageOut(
        reads_today=connection.reads_today if same_day else 0,
        reads_limit=settings.LINKEDIN_EXTENSION_DAILY_READ_LIMIT,
        adds_today=connection.adds_today if same_day else 0,
    )


def frontend_url() -> str:
    return settings.PUBLIC_BASE_URL.rstrip("/")


# ── Połączenie (JWT) ─────────────────────────────────────────────────────────


@router.post(
    "/connect",
    response_model=ConnectResponse,
    dependencies=SOURCING_SECTION_DEPENDENCIES,
)
async def connect_extension(
    data: ConnectRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> ConnectResponse:
    """Wydaj klucz wtyczce wskazanej przez stronę ``/extension/connect``.

    Klucz trafia wyłącznie do wtyczki z listy ``LINKEDIN_EXTENSION_IDS`` —
    inaczej dowolna inna wtyczka zainstalowana w przeglądarce mogłaby otworzyć
    tę stronę ze swoim id i odebrać klucz osoby. Pusta lista = nikt.
    """
    if not settings.LINKEDIN_EXTENSION_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Wtyczka LinkedIn jest wyłączona.",
        )
    if data.extension_id not in allowed_extension_ids():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Ta wtyczka nie jest wtyczką NEXUSA. Zainstaluj wtyczkę z linku "
                "od administratora i połącz ją ponownie."
            ),
        )
    wire, connection = await issue_connection(
        db,
        user_id=current_user.id,
        authorization_version=current_user.authorization_version,
        extension_version=data.extension_version,
    )
    await db.commit()
    logger.info(
        "linkedin_extension.connected user_id=%s key_id=%s",
        current_user.id,
        connection.key_id,
    )
    return ConnectResponse(
        key=wire,
        user=user_brief(current_user),
        expires_at=connection.expires_at,
        api_base=settings.PUBLIC_API_BASE_URL.rstrip("/"),
        frontend_url=frontend_url(),
    )


@router.get("/connections", response_model=ConnectionsAdminResponse)
async def list_connections(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> ConnectionsAdminResponse:
    """Ustawienia → Wtyczka LinkedIn: aktywne połączenia zespołu."""
    rows = (
        await db.execute(
            select(LinkedinExtensionConnection)
            .where(LinkedinExtensionConnection.revoked_at.is_(None))
            .order_by(LinkedinExtensionConnection.last_used_at.desc().nulls_last())
        )
    ).scalars().all()
    items: list[ConnectionAdminOut] = []
    for row in rows:
        usage = usage_out(row)
        items.append(
            ConnectionAdminOut(
                key_id=row.key_id,
                user_id=row.user_id,
                user_name=row.user.name if row.user else str(row.user_id),
                extension_version=row.extension_version,
                created_at=row.created_at,
                expires_at=row.expires_at,
                last_used_at=row.last_used_at,
                reads_today=usage.reads_today,
                adds_today=usage.adds_today,
            )
        )
    return ConnectionsAdminResponse(
        items=items, reads_limit=settings.LINKEDIN_EXTENSION_DAILY_READ_LIMIT
    )


@router.post(
    "/connections/{key_id}/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=SOURCING_SECTION_DEPENDENCIES,
)
async def revoke_connection(
    key_id: str,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Odłącz wtyczkę: admin dowolną, każdy swoją."""
    from datetime import datetime, timezone

    row = await db.scalar(
        select(LinkedinExtensionConnection).where(
            LinkedinExtensionConnection.key_id == key_id
        )
    )
    if row is None or (
        row.user_id != current_user.id and not current_user.has_role(UserRole.admin)
    ):
        raise HTTPException(status_code=404, detail="Nie ma takiego połączenia.")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        row.revoked_by = current_user.id
        await db.commit()


# ── Praca na LinkedInie (klucz wtyczki) ──────────────────────────────────────


@router.get("/me", response_model=MeResponse)
async def extension_me(
    principal: ExtensionAuth,
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    roll_day(principal.connection)
    await db.commit()
    return MeResponse(
        user=user_brief(principal.user),
        usage=usage_out(principal.connection),
        frontend_url=frontend_url(),
    )


@router.get("/jobs", response_model=JobOptionsResponse)
async def extension_jobs(
    principal: ExtensionReader,
    q: Optional[str] = Query(default=None, max_length=100),
    db: AsyncSession = Depends(get_db),
) -> JobOptionsResponse:
    """Otwarte rekrutacje do wyboru w panelu (rekrutacje widzą wszyscy)."""
    stmt = (
        select(Job.id, Job.title, Client.name, User.name)
        .join(Client, Client.id == Job.client_id)
        .outerjoin(User, User.id == Job.recruiter_id)
        .where(Job.is_open.is_(True))
    )
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Job.title.ilike(like), Client.name.ilike(like)))
    stmt = stmt.order_by(Job.opened_at.desc().nulls_last(), Job.id.desc()).limit(40)
    rows = (await db.execute(stmt)).all()
    await db.commit()
    return JobOptionsResponse(
        items=[
            JobOption(id=r[0], title=r[1], client_name=r[2], recruiter_name=r[3])
            for r in rows
        ]
    )


def _count_read(principal) -> None:
    try:
        count_page_read(principal.connection)
    except DailyLimitReached as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="extension_daily_limit",
        ) from exc


async def _candidate_or_404(db: AsyncSession, candidate_id: int) -> Candidate:
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej osoby w NEXUSIE.")
    return candidate


@router.post("/lookup", response_model=LookupResponse)
async def extension_lookup(
    profile: ProfileRead,
    principal: ExtensionReader,
    db: AsyncSession = Depends(get_db),
) -> LookupResponse:
    """Co NEXUS wie o osobie z otwartej strony (makiety 1–3). Liczy 1 odczyt."""
    _count_read(principal)
    result = await lookup_service.lookup(db, principal.user, profile)
    usage = usage_out(principal.connection)
    await db.commit()
    return LookupResponse(**result.as_dict(), usage=usage)


@router.post("/lookup-batch", response_model=BatchResponse)
async def extension_lookup_batch(
    data: BatchRequest,
    principal: ExtensionReader,
    db: AsyncSession = Depends(get_db),
) -> BatchResponse:
    """Statusy osób z widocznej strony wyników (makieta 5). Liczy 1 odczyt."""
    _count_read(principal)
    items = await lookup_service.batch_lookup(db, principal.user, data.people)
    usage = usage_out(principal.connection)
    await db.commit()
    return BatchResponse(items=items, usage=usage)


@router.post(
    "/candidates",
    response_model=AddCandidateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": AddCandidateResponse}},
)
async def extension_add_candidate(
    data: AddCandidateRequest,
    principal: ExtensionWriter,
    db: AsyncSession = Depends(get_db),
) -> AddCandidateResponse:
    """Dodaj osobę z LinkedIna do bazy i opcjonalnie do rekrutacji.

    Off-limits bez odpowiedzi → 409 dla CAŁEGO żądania (rollback, osoby nie
    ma) — wtyczka zadaje pytanie i ponawia z ``off_limits_how``.
    """
    from fastapi.responses import JSONResponse

    candidate, created = await writes.create_candidate(db, principal.user, data.profile)
    outcome = await writes.assign_jobs(
        db, principal.user, candidate.id, data.job_ids, data.off_limits_how
    )
    if created:
        count_add(principal.connection)
    await db.commit()
    if created:
        try:
            from app.services.index_outbox_service import schedule_or_embed_candidate

            await schedule_or_embed_candidate(candidate.id, db)
        except Exception as exc:  # noqa: BLE001 — indeks to best-effort
            logger.warning("linkedin_extension.index_failed id=%s (%s)", candidate.id, exc)
    body = AddCandidateResponse(
        candidate_id=candidate.id,
        url=lookup_service.candidate_url(candidate.id),
        created=created,
        assigned_job_ids=outcome.assigned,
        skipped=outcome.skipped,
    )
    if not created:
        return JSONResponse(status_code=status.HTTP_200_OK, content=body.model_dump(mode="json"))
    return body


@router.post("/candidates/{candidate_id}/jobs", response_model=AssignJobsResponse)
async def extension_assign_jobs(
    candidate_id: int,
    data: AssignJobsRequest,
    principal: ExtensionWriter,
    db: AsyncSession = Depends(get_db),
) -> AssignJobsResponse:
    await _candidate_or_404(db, candidate_id)
    outcome = await writes.assign_jobs(
        db, principal.user, candidate_id, data.job_ids, data.off_limits_how
    )
    await db.commit()
    return AssignJobsResponse(assigned_job_ids=outcome.assigned, skipped=outcome.skipped)


@router.post("/candidates/{candidate_id}/refresh", response_model=RefreshResponse)
async def extension_refresh(
    candidate_id: int,
    data: RefreshRequest,
    principal: ExtensionWriter,
    db: AsyncSession = Depends(get_db),
) -> RefreshResponse:
    """„Zaktualizuj w NEXUSIE” — firma i stanowisko z LinkedIna (makieta 2)."""
    candidate = await _candidate_or_404(db, candidate_id)
    updated = await writes.refresh_from_profile(db, candidate, data.profile)
    await db.commit()
    return RefreshResponse(updated=updated)


@router.post("/candidates/{candidate_id}/contacts", response_model=ContactResponse)
async def extension_contact(
    candidate_id: int,
    data: ContactRequest,
    principal: ExtensionWriter,
    db: AsyncSession = Depends(get_db),
) -> ContactResponse:
    """„Wysłałem, zapisz kontakt” (makieta 4) — notatka i przypomnienie."""
    from app.api.notes import send_note_create_side_effects

    candidate = await _candidate_or_404(db, candidate_id)
    created, reminder_id = await writes.log_contact(db, principal.user, candidate, data)
    await db.commit()
    await send_note_create_side_effects(created)
    return ContactResponse(id=created.note.id, reminder_id=reminder_id)


@router.post("/candidates/{candidate_id}/notes", response_model=IdResponse)
async def extension_note(
    candidate_id: int,
    data: NoteRequest,
    principal: ExtensionWriter,
    db: AsyncSession = Depends(get_db),
) -> IdResponse:
    from app.api.notes import send_note_create_side_effects

    await _candidate_or_404(db, candidate_id)
    created = await writes.add_note(db, principal.user, candidate_id, data.text.strip())
    await db.commit()
    await send_note_create_side_effects(created)
    return IdResponse(id=created.note.id)


@router.post("/candidates/{candidate_id}/profile-pdf", response_model=ProfilePdfResponse)
async def extension_profile_pdf(
    candidate_id: int,
    principal: ExtensionWriter,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> ProfilePdfResponse:
    """PDF z „Zapisz jako PDF” na LinkedInie — jak CV: plik, odczyt, profil."""
    from app.api.candidates import (
        _after_cv_commit,
        _ingest_candidate_cv_file,
        _primary_cv_before_change,
        _read_upload_bounded,
        _sanitize_upload_filename,
    )

    candidate = await _candidate_or_404(db, candidate_id)
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400, detail="Wgraj plik PDF z „Zapisz jako PDF” na LinkedInie."
        )
    content = await _read_upload_bounded(file, label="PDF profilu")
    safe_filename = _sanitize_upload_filename(file.filename, fallback="linkedin-profil.pdf")
    replaced = await _primary_cv_before_change(db, candidate.id)
    document = await _ingest_candidate_cv_file(
        db,
        candidate=candidate,
        content=content,
        safe_filename=safe_filename,
        content_type="application/pdf",
        user_id=principal.user.id,
        external_source="linkedin_extension",
    )
    await db.commit()
    await _after_cv_commit(
        db,
        background_tasks,
        candidate=candidate,
        document=document,
        actor_user_id=principal.user.id,
        replaced_primary=replaced,
    )
    return ProfilePdfResponse(document_id=document.id)


@router.post("/draft-message", response_model=DraftResponse)
async def extension_draft_message(
    data: DraftRequest,
    principal: ExtensionReader,
    db: AsyncSession = Depends(get_db),
) -> DraftResponse:
    """Szkic wiadomości pod rekrutację (makieta 4). Wtyczka niczego nie wysyła."""
    result = await draft_message(
        db, user=principal.user, job_id=data.job_id, kind=data.kind, profile=data.profile
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej rekrutacji.")
    await db.commit()
    text, ai = result
    return DraftResponse(text=text, ai=ai)
