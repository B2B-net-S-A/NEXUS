"""Masowa wysyłka nowej umowy B2B do aktywnych kontraktorów — trasy (E5b, 0758).

Decyzja Artura 22.11.2026: ok. 600 aktywnych kontraktorów B2B dostanie nową
umowę do podpisu (przenosi prawa autorskie, więc podpis kwalifikowany). Nowy
wzór jest w przygotowaniu, więc wszystko działa na obecnym wzorze Generatora,
a do ludzi nic nie wychodzi, dopóki admin nie oznaczy nowego wzoru jako
podpiętego. Podgląd i próba bez wysyłki działają zawsze.

Trasy pod ``/api/b2b-generator/mass-send`` za tą samą bramką sekcji co
Generator i „Wyślij do podpisu”. Każda osoba w podglądzie i w paczce to ktoś,
czyją obecną umowę pytający mógłby wysłać do podpisu
(``service.may_send_for`` = ``b2b_esign._assert_row_sender``). Zmiana
przełącznika „nowy wzór podpięty” — tylko admin.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.b2b_contract_generator import _require_contract_generation
from app.api.b2b_esign import MSG_OFF, MSG_SIGNER
from app.api.contract_access import B2BGeneratorAccess
from app.api.deps import AdminUser
from app.api.section_access import SOURCING_SECTION_DEPENDENCIES
from app.core.config import settings as app_config
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.b2b_mass_send import B2BMassSendBatch, B2BMassSendItem
from app.models.b2b_signing_request import B2BSigningRequest
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.user import User, UserRole
from app.services.b2b_esign import mail as esign_mail
from app.services.b2b_esign import settings as esign_settings
from app.services.b2b_mass_send import readiness, service
from app.services.b2b_mass_send import settings as mass_settings

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)

_PREFIX = "/mass-send"
#: Terminy linku jak w oknie „Wyślij do podpisu” (1, 3, 5, 7 dni) i 14 z makiety.
LINK_DAYS: tuple[int, ...] = (1, 3, 5, 7, 14)


# ── Schematy ────────────────────────────────────────────────────────────────


class MassSendPerson(BaseModel):
    id: int
    name: str


class MassSendSettingsOut(BaseModel):
    template_ready: bool
    template_ready_at: Optional[str] = None
    template_ready_by: Optional[str] = None
    template_label: str
    worker_enabled: bool
    can_start: bool
    mailbox_connected: bool
    company_signers: list[MassSendPerson]
    link_days: list[int]
    chunk_size: int


class MassSendSettingsIn(BaseModel):
    template_ready: bool


class MassSendClientCount(BaseModel):
    client_id: Optional[int]
    client_name: str
    total: int
    ready: int


class MassSendRow(BaseModel):
    contract_id: int
    candidate_id: int
    name: str
    client_id: Optional[int]
    client_name: str
    status: Literal["ready", "needs_review", "skipped"]
    reason: Optional[str] = None
    reason_label: Optional[str] = None
    missing: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    data_source: Optional[str] = None
    end_date: Optional[date] = None


class MassSendSummary(BaseModel):
    total: int
    ready: int
    needs_review: int
    skipped: int
    ending_soon: int
    by_reason: dict[str, int]
    by_client: list[MassSendClientCount]


class MassSendPreviewOut(BaseModel):
    summary: MassSendSummary
    rows: list[MassSendRow]
    rows_total: int
    # Osoby bez e-maila (do uzupełnienia) — imiennie, bez stronicowania.
    no_email: list[MassSendPerson]


class MassSendStartIn(BaseModel):
    skip_ending: bool = True
    company_signer_id: int
    days: int = Field(default=14, ge=1, le=30)


class MassSendDryRunIn(BaseModel):
    skip_ending: bool = True


class MassSendDryRunOut(BaseModel):
    summary: MassSendSummary
    # Osoby, które plan uznał za gotowe, a Generator by odrzucił.
    problems: list[MassSendRow]
    would_send: int
    blocked: bool
    block_reasons: list[str]


class MassSendProgress(BaseModel):
    pending: int = 0
    created: int = 0
    sent: int = 0
    failed: int = 0
    needs_review: int = 0
    skipped: int = 0
    waiting_contractor: int = 0
    waiting_company: int = 0
    signed: int = 0
    closed: int = 0


class MassSendBatchOut(BaseModel):
    id: int
    status: str
    started_by: Optional[MassSendPerson]
    company_signer: Optional[MassSendPerson]
    link_days: int
    skip_ending: bool
    template_label: str
    planned: dict[str, int]
    created_at: datetime
    finished_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    progress: MassSendProgress
    template_ready: bool


class MassSendItemOut(BaseModel):
    id: int
    candidate_id: Optional[int]
    name: str
    client_name: Optional[str]
    status: str
    reason: Optional[str]
    reason_label: Optional[str]
    missing: list[str]
    error: Optional[str]
    contract_number: Optional[str]
    generated_contract_id: Optional[int]
    signing_status: Optional[str]


class MassSendItemsOut(BaseModel):
    items: list[MassSendItemOut]
    total: int


# ── Pomocnicze ──────────────────────────────────────────────────────────────


def _row(planned: service.Planned) -> MassSendRow:
    assessment = planned.assessment
    person = planned.person
    return MassSendRow(
        contract_id=person.contract_id,
        candidate_id=person.candidate_id,
        name=person.candidate_name,
        client_id=person.client_id,
        client_name=person.client_name,
        status=assessment.status,
        reason=assessment.reason,
        reason_label=readiness.reason_label(assessment.reason),
        missing=list(assessment.missing),
        issues=list(assessment.issues),
        data_source=assessment.data_source,
        end_date=readiness.effective_end(person),
    )


async def _names(db: AsyncSession, ids: list[int]) -> dict[int, str]:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(ids)))
    return {uid: name for uid, name in rows.all()}


async def _assert_may_start(
    db: AsyncSession, user: User
) -> esign_settings.EsignSettings:
    """Poziom „Generowanie” i podpis w NEXUSIE włączony dla tego konta."""
    _require_contract_generation(user)
    esign = await esign_settings.load(db)
    if not esign.can_send(user):
        raise HTTPException(status_code=403, detail=MSG_OFF)
    return esign


async def _batch_out(db: AsyncSession, batch: B2BMassSendBatch) -> MassSendBatchOut:
    names = await _names(db, [batch.started_by or 0, batch.company_signer_id or 0])
    ready = (await mass_settings.load(db)).template_ready
    return MassSendBatchOut(
        id=batch.id,
        status=batch.status,
        started_by=(
            MassSendPerson(id=batch.started_by, name=names[batch.started_by])
            if batch.started_by in names
            else None
        ),
        company_signer=(
            MassSendPerson(
                id=batch.company_signer_id, name=names[batch.company_signer_id]
            )
            if batch.company_signer_id in names
            else None
        ),
        link_days=batch.link_days,
        skip_ending=batch.skip_ending,
        template_label=batch.template_label,
        planned={k: int(v) for k, v in (batch.planned or {}).items()},
        created_at=batch.created_at,
        finished_at=batch.finished_at,
        cancelled_at=batch.cancelled_at,
        progress=MassSendProgress(**await service.progress(db, batch.id)),
        template_ready=ready,
    )


async def _visible_batch(
    db: AsyncSession, user: User, batch_id: int
) -> B2BMassSendBatch:
    """Paczkę widzi osoba, która ją zaczęła, i admin (lista ma imiona)."""
    batch = await db.get(B2BMassSendBatch, batch_id)
    if batch is None or not (
        batch.started_by == user.id or user.has_role(UserRole.admin)
    ):
        raise HTTPException(status_code=404, detail="Nie ma takiej wysyłki.")
    return batch


# ── Ustawienia ──────────────────────────────────────────────────────────────


@router.get(f"{_PREFIX}/settings", response_model=MassSendSettingsOut)
async def mass_send_settings(
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> MassSendSettingsOut:
    current = await mass_settings.load(db)
    esign = await esign_settings.load(db)
    names = await _names(db, [current.marked_by or 0, *esign.company_signer_ids])
    try:
        _require_contract_generation(current_user)
        can_start = esign.can_send(current_user)
    except HTTPException:
        can_start = False
    return MassSendSettingsOut(
        template_ready=current.template_ready,
        template_ready_at=current.marked_at if current.template_ready else None,
        template_ready_by=(
            names.get(current.marked_by or -1) if current.template_ready else None
        ),
        template_label=service.TEMPLATE_LABEL,
        worker_enabled=app_config.B2B_MASS_SEND_ENABLED,
        can_start=can_start,
        mailbox_connected=await esign_mail.mailbox_connected(db, current_user.id),
        company_signers=[
            MassSendPerson(id=uid, name=names[uid])
            for uid in esign.company_signer_ids
            if uid in names
        ],
        link_days=list(LINK_DAYS),
        chunk_size=service.CHUNK,
    )


@router.put(f"{_PREFIX}/settings", response_model=MassSendSettingsOut)
async def put_mass_send_settings(
    body: MassSendSettingsIn,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> MassSendSettingsOut:
    """Admin oznacza nowy wzór jako podpięty (albo cofa to oznaczenie)."""
    await mass_settings.save(
        db,
        template_ready=body.template_ready,
        actor_id=current_user.id,
        now=datetime.now(timezone.utc),
    )
    await db.commit()
    return await mass_send_settings(current_user, db)


# ── Podgląd i próba ─────────────────────────────────────────────────────────


@router.get(f"{_PREFIX}/preview", response_model=MassSendPreviewOut)
async def mass_send_preview(
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
    skip_ending: bool = Query(True),
    status: Optional[Literal["ready", "needs_review", "skipped"]] = Query(None),
    offset: int = Query(0, ge=0, le=100_000),
    limit: int = Query(50, ge=1, le=200),
) -> MassSendPreviewOut:
    """Kto dostanie nową umowę: liczby po klientach i stan każdej osoby. Bez zapisu."""
    _require_contract_generation(current_user)
    today = business_today()
    planned = await service.collect(
        db, current_user, today=today, skip_ending=skip_ending
    )
    rows = [p for p in planned if status is None or p.assessment.status == status]
    return MassSendPreviewOut(
        summary=MassSendSummary(**service.counts(planned, today)),
        rows=[_row(p) for p in rows[offset : offset + limit]],
        rows_total=len(rows),
        no_email=[
            MassSendPerson(id=p.person.candidate_id, name=p.person.candidate_name)
            for p in planned
            if p.assessment.reason == readiness.REASON_NO_EMAIL
        ][:200],
    )


@router.post(f"{_PREFIX}/dry-run", response_model=MassSendDryRunOut)
async def mass_send_dry_run(
    body: MassSendDryRunIn,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> MassSendDryRunOut:
    """Próba bez wysyłki: plan i bramki Generatora dla każdej gotowej osoby.

    Nic nie zapisuje, nie zużywa numerów i działa także przy zablokowanej
    wysyłce — mówi wtedy, co blokuje."""
    _require_contract_generation(current_user)
    today = business_today()
    planned, problems = await service.dry_run(
        db, current_user, skip_ending=body.skip_ending
    )
    reasons: list[str] = []
    if not (await mass_settings.load(db)).template_ready:
        reasons.append(service.MSG_TEMPLATE_NOT_READY)
    if not app_config.B2B_MASS_SEND_ENABLED:
        reasons.append(service.MSG_WORKER_OFF)
    esign = await esign_settings.load(db)
    if not esign.can_send(current_user):
        reasons.append(MSG_OFF)
    if not esign.company_signer_ids:
        reasons.append(MSG_SIGNER)
    if not await esign_mail.mailbox_connected(db, current_user.id):
        reasons.append(service.MSG_NO_MAILBOX)
    problem_rows = []
    for item in planned:
        message = problems.get(item.person.candidate_id)
        if message:
            row = _row(item)
            row.status = "needs_review"
            row.reason = readiness.REASON_MISSING
            row.reason_label = readiness.reason_label(readiness.REASON_MISSING)
            row.issues = [*row.issues, message]
            problem_rows.append(row)
    summary = service.counts(planned, today)
    summary["ready"] -= len(problem_rows)
    summary["needs_review"] += len(problem_rows)
    for client in summary["by_client"]:
        client["ready"] -= sum(
            1 for row in problem_rows if row.client_id == client["client_id"]
        )
    return MassSendDryRunOut(
        summary=MassSendSummary(**summary),
        problems=problem_rows,
        would_send=summary["ready"],
        blocked=bool(reasons),
        block_reasons=reasons,
    )


# ── Paczka ──────────────────────────────────────────────────────────────────


@router.post(f"{_PREFIX}/batches", response_model=MassSendBatchOut)
async def start_mass_send(
    body: MassSendStartIn,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> MassSendBatchOut:
    """Zacznij wysyłkę. 409, dopóki nowy wzór nie jest podpięty."""
    esign = await _assert_may_start(db, current_user)
    if not (await mass_settings.load(db)).template_ready:
        raise HTTPException(status_code=409, detail=service.MSG_TEMPLATE_NOT_READY)
    if not app_config.B2B_MASS_SEND_ENABLED:
        raise HTTPException(status_code=409, detail=service.MSG_WORKER_OFF)
    if body.company_signer_id not in esign.company_signer_ids:
        raise HTTPException(status_code=422, detail=MSG_SIGNER)
    if not await esign_mail.mailbox_connected(db, current_user.id):
        raise HTTPException(status_code=409, detail=service.MSG_NO_MAILBOX)
    batch = await service.create_batch(
        db,
        current_user,
        skip_ending=body.skip_ending,
        company_signer_id=body.company_signer_id,
        days=body.days,
    )
    await db.commit()
    return await _batch_out(db, batch)


@router.get(f"{_PREFIX}/batches/current", response_model=Optional[MassSendBatchOut])
async def current_mass_send(
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> Optional[MassSendBatchOut]:
    """Ostatnia paczka pytającego (admin: ostatnia w ogóle) albo ``null``."""
    query = select(B2BMassSendBatch).order_by(B2BMassSendBatch.id.desc()).limit(1)
    if not current_user.has_role(UserRole.admin):
        query = query.where(B2BMassSendBatch.started_by == current_user.id)
    batch = await db.scalar(query)
    return await _batch_out(db, batch) if batch is not None else None


@router.get(f"{_PREFIX}/batches/{{batch_id}}", response_model=MassSendBatchOut)
async def get_mass_send(
    batch_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> MassSendBatchOut:
    return await _batch_out(db, await _visible_batch(db, current_user, batch_id))


@router.get(f"{_PREFIX}/batches/{{batch_id}}/items", response_model=MassSendItemsOut)
async def mass_send_items(
    batch_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
    status: Optional[
        Literal["pending", "created", "sent", "failed", "needs_review", "skipped"]
    ] = Query(None),
    offset: int = Query(0, ge=0, le=100_000),
    limit: int = Query(50, ge=1, le=200),
) -> MassSendItemsOut:
    batch = await _visible_batch(db, current_user, batch_id)
    where = [B2BMassSendItem.batch_id == batch.id]
    if status is not None:
        where.append(B2BMassSendItem.status == status)
    total = int(
        await db.scalar(select(func.count(B2BMassSendItem.id)).where(*where)) or 0
    )
    rows = await db.execute(
        select(
            B2BMassSendItem,
            Candidate.name,
            Candidate.lastname,
            Client.name,
            B2BGeneratedContract.contract_number,
            B2BSigningRequest.status,
        )
        .outerjoin(Candidate, Candidate.id == B2BMassSendItem.candidate_id)
        .outerjoin(Client, Client.id == B2BMassSendItem.client_id)
        .outerjoin(
            B2BGeneratedContract,
            B2BGeneratedContract.id == B2BMassSendItem.generated_contract_id,
        )
        .outerjoin(
            B2BSigningRequest,
            B2BSigningRequest.id == B2BMassSendItem.signing_request_id,
        )
        .where(*where)
        .order_by(B2BMassSendItem.id)
        .offset(offset)
        .limit(limit)
    )
    items = [
        MassSendItemOut(
            id=item.id,
            candidate_id=item.candidate_id,
            name=" ".join(p for p in (first, last) if p).strip() or "—",
            client_name=client,
            status=item.status,
            reason=item.reason,
            reason_label=readiness.reason_label(item.reason),
            missing=list(item.missing or []),
            error=item.error,
            contract_number=number,
            generated_contract_id=item.generated_contract_id,
            signing_status=signing,
        )
        for item, first, last, client, number, signing in rows.all()
    ]
    return MassSendItemsOut(items=items, total=total)


@router.post(f"{_PREFIX}/batches/{{batch_id}}/cancel", response_model=MassSendBatchOut)
async def cancel_mass_send(
    batch_id: int,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> MassSendBatchOut:
    """Zatrzymaj wysyłkę: kto jeszcze nie dostał linku, już go nie dostanie."""
    batch = await _visible_batch(db, current_user, batch_id)
    locked = await db.get(
        B2BMassSendBatch, batch.id, with_for_update=True, populate_existing=True
    )
    if locked is None or locked.status != "running":
        raise HTTPException(status_code=409, detail="Ta wysyłka już się skończyła.")
    await service.cancel_batch(
        db, locked, actor_id=current_user.id, now=datetime.now(timezone.utc)
    )
    await db.commit()
    return await _batch_out(db, locked)
