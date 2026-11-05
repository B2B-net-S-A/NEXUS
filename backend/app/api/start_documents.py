"""Dokumenty do startu: lista klienta, stan pary, pliki, PESEL, mail do konsultanta.

Reguły: ``app/services/start_documents.py`` i
``docs/claude/kontrakty/dokumenty-do-startu.md``.

Kto co może:

* **lista klienta, odczyt**: podgląd Delivery (Delivery Lead u swoich klientów);
  **zapis**: „Klienci: dodawanie i edycja” w tym samym zakresie,
* **stan pary**: role rekrutacji z dostępem do rekrutacji, odpowiedzialny
  rekruter i Delivery Lead klienta,
* **dodanie pliku i PESEL-u**: jak stan pary,
* **pobranie pliku**: odpowiedzialny rekruter, Delivery Lead klienta, Head of
  Recruitment, admin. KRK to dane o karalności, więc krąg jest węższy niż
  Tablica,
* **odczyt PESEL-u**: Delivery Lead klienta i admin, każdy odczyt zapisany
  w historii,
* **„Sprawdzone”, zwrot, „Nie dotyczy”**: Delivery Lead klienta, Head of
  Recruitment, admin.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Annotated, Any, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.permission_access import ClientsEditUser, DeliveryViewUser
from app.api.recruitment_access import ensure_job_membership
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.http_headers import content_disposition
from app.models.activity import Activity
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract
from app.models.job import Job
from app.models.notification import NotificationType
from app.models.recruitment_pipeline import CandidateStage
from app.models.start_document import ClientStartDocument, PlacementStartDocument
from app.models.user import User, UserRole
from app.services import start_documents as svc
from app.services import start_documents_fill as fill
from app.services import start_documents_mail as mail
from app.services import storage_service
from app.services.access_scope import (
    assert_delivery_lead_client_visible,
    resolve_delivery_lead_client_ids,
)
from app.services.b2b_documents.signed_scan import read_scan
from app.services.b2b_esign.mail import mailbox_connected, send_from
from app.services.board_tasks import dl_portfolio_client_ids
from app.services.m365.sender import FileAttachment
from app.services.notification_triggers import emit
from app.services.request_semantics import is_read_only_http_request
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)

logger = logging.getLogger(__name__)

router = APIRouter()
#: Lista klienta to Delivery: sekcja przed uprawnieniem (`permission_access`).
clients_router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)

MSG_ROLE = "Dokumenty do startu prowadzą osoby z rekrutacji i Delivery Lead klienta."
MSG_NOT_FOUND = "Nie ma takiej pozycji na liście tego klienta."
MSG_NO_LIST = "Ten klient nie ma listy dokumentów do startu."
MSG_NOT_IN_JOB = "Ta osoba nie jest w tej rekrutacji."
MSG_LINK = "Podaj pełny adres strony zaczynający się od https://."
MSG_NO_REVIEW = "To robi Delivery Lead klienta, Head of Recruitment albo administrator."
MSG_NO_FILE_ACCESS = (
    "Plik pobierze odpowiedzialny rekruter, Delivery Lead klienta, Head of "
    "Recruitment albo administrator."
)
MSG_NO_PESEL_ACCESS = "PESEL widzi tylko Delivery Lead klienta i administrator."
MSG_WRONG_KIND = "Ta pozycja nie przyjmuje takiej wartości."
MSG_NOT_DELIVERED = "Tej pozycji jeszcze nikt nie dostarczył."
MSG_NO_TEMPLATE = "Ta pozycja nie ma wzoru do pobrania."
MSG_NO_EMAIL = "Ta osoba nie ma adresu e-mail w NEXUSIE. Skopiuj treść i wyślij ją z własnej skrzynki."
MSG_NO_FILE = "Ten plik nie jest zapisany przy tej pozycji."
MSG_TEMPLATE_FORMAT = "Wzór musi być plikiem DOCX albo PDF."
MAX_TEMPLATE_BYTES = 10 * 1024 * 1024
#: Limit Graph na załącznik wysyłany tą drogą (``m365.sender.FileAttachment``).
MAX_ATTACHMENT_BYTES = 3 * 1024 * 1024

_WORK_ROLES = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.talent_community_manager,
    UserRole.recruiter,
)


async def require_start_documents_access(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> User:
    """Bramka tras pary: rola rekrutacji i sekcja „Rekrutacje”, jak Tablica.

    Odczyt na odczyt, zapis na każdy krok (plik, PESEL, mail ze skrzynki osoby)."""

    if current_user.has_role(UserRole.user) or not current_user.has_any_role(
        *_WORK_ROLES
    ):
        raise HTTPException(status_code=403, detail=MSG_ROLE)
    required = (
        SectionAccess.read
        if is_read_only_http_request(request.method, request.url.path)
        else SectionAccess.write
    )
    granted = section_access_for_user(current_user, ProductSection.pipeline)
    if granted < required:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "section_access_denied",
                "section": ProductSection.pipeline.value,
                "required": required.name,
                "granted": granted.name,
            },
        )
    return current_user


WorkUser = Annotated[User, Depends(require_start_documents_access)]
Db = Annotated[AsyncSession, Depends(get_db)]


# ── Lista klienta ─────────────────────────────────────────────────────────────


class ClientDocumentIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    note: Optional[str] = Field(None, max_length=300)
    kind: str = "file"
    required: bool = True
    offset_days: int = Field(-2, ge=-30, le=30)
    link_url: Optional[str] = Field(None, max_length=500)
    fill_from_agreement: bool = False

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        if value not in (svc.KIND_FILE, svc.KIND_PESEL, svc.KIND_AGREEMENT):
            raise ValueError("Nieznany rodzaj pozycji.")
        return value

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("Podaj nazwę dokumentu.")
        return cleaned

    @field_validator("link_url")
    @classmethod
    def _link(cls, value: Optional[str]) -> Optional[str]:
        cleaned = (value or "").strip()
        if not cleaned:
            return None
        try:
            parsed = urlparse(cleaned)
            host = parsed.hostname
        except ValueError:
            host = None
            parsed = None
        if (
            parsed is None
            or parsed.scheme != "https"
            or not host
            or re.search(r"\s", cleaned)
        ):
            raise ValueError(MSG_LINK)
        return cleaned


def _document_out(document: ClientStartDocument) -> dict[str, Any]:
    return {
        "id": document.id,
        "name": document.name,
        "note": document.note,
        "kind": document.kind,
        "required": document.required,
        "offset_days": document.offset_days,
        "link_url": document.link_url,
        "fill_from_agreement": document.fill_from_agreement,
        "template_name": document.template_name,
    }


async def _client_in_scope(db: AsyncSession, user: User, client_id: int) -> None:
    if await db.get(Client, client_id) is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego klienta.")
    assert_delivery_lead_client_visible(
        client_id, await resolve_delivery_lead_client_ids(user, db)
    )


async def _load_document(db: AsyncSession, document_id: int) -> ClientStartDocument:
    document = await db.get(ClientStartDocument, document_id)
    if document is None or document.archived_at is not None:
        raise HTTPException(status_code=404, detail=MSG_NOT_FOUND)
    return document


@clients_router.get("/start-documents/clients/{client_id}")
async def client_list(
    client_id: int, current_user: DeliveryViewUser, db: Db
) -> dict[str, Any]:
    await _client_in_scope(db, current_user, client_id)
    lists = await svc.client_lists(db, [client_id])
    return {"items": [_document_out(d) for d in lists.get(client_id, [])]}


@clients_router.post("/start-documents/clients/{client_id}", status_code=201)
async def add_client_document(
    client_id: int, payload: ClientDocumentIn, current_user: ClientsEditUser, db: Db
) -> dict[str, Any]:
    await _client_in_scope(db, current_user, client_id)
    document = ClientStartDocument(
        client_id=client_id,
        position=await svc.next_position(db, client_id),
        created_by=current_user.id,
        updated_by=current_user.id,
        **payload.model_dump(),
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return _document_out(document)


@clients_router.patch("/start-documents/items/{document_id}")
async def update_client_document(
    document_id: int, payload: ClientDocumentIn, current_user: ClientsEditUser, db: Db
) -> dict[str, Any]:
    document = await _load_document(db, document_id)
    await _client_in_scope(db, current_user, document.client_id)
    for key, value in payload.model_dump().items():
        setattr(document, key, value)
    document.updated_by = current_user.id
    await db.commit()
    await db.refresh(document)
    return _document_out(document)


@clients_router.delete("/start-documents/items/{document_id}", status_code=204)
async def archive_client_document(
    document_id: int, current_user: ClientsEditUser, db: Db
) -> Response:
    """Pozycja znika z listy, a pliki par zostają (mogły już trafić do klienta)."""

    document = await _load_document(db, document_id)
    await _client_in_scope(db, current_user, document.client_id)
    document.archived_at = svc.utcnow()
    document.updated_by = current_user.id
    await db.commit()
    return Response(status_code=204)


def _template_type(filename: Optional[str], data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".docx") and data[:2] == b"PK":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if name.endswith(".pdf") and data[:5] == b"%PDF-":
        return "application/pdf"
    raise HTTPException(status_code=415, detail=MSG_TEMPLATE_FORMAT)


@clients_router.put("/start-documents/items/{document_id}/template")
async def upload_template(
    document_id: int,
    current_user: ClientsEditUser,
    db: Db,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    document = await _load_document(db, document_id)
    await _client_in_scope(db, current_user, document.client_id)
    data = await file.read(MAX_TEMPLATE_BYTES + 1)
    if not data or len(data) > MAX_TEMPLATE_BYTES:
        raise HTTPException(status_code=413, detail="Wzór może mieć najwyżej 10 MB.")
    content_type = _template_type(file.filename, data)
    name = (file.filename or "wzor").rsplit("/", 1)[-1][:255]
    path, _size = storage_service.save_start_document_file(
        f"clients/{document.client_id}", name, data
    )
    previous = document.template_path
    document.template_path = path
    document.template_name = name
    document.template_content_type = content_type
    document.updated_by = current_user.id
    await db.commit()
    await db.refresh(document)
    if previous:
        storage_service.delete_start_document_file(previous)
    return _document_out(document)


# ── Dostęp do pary ────────────────────────────────────────────────────────────


class PairAccess:
    """Co konto może przy tej parze (liczone raz, w jednym miejscu)."""

    def __init__(
        self, *, state: svc.PairState, user: User, in_portfolio: bool, member: bool
    ) -> None:
        self.state = state
        is_dl = user.has_role(UserRole.delivery_lead) and (
            in_portfolio or state.delivery_lead_id == user.id
        )
        is_oversight = user.has_any_role(UserRole.admin, UserRole.head_of_recruitment)
        is_recruiter = state.recruiter_id == user.id
        self.can_review = is_dl or is_oversight
        self.can_work = self.can_review or is_recruiter or member
        self.can_download = self.can_review or is_recruiter
        self.can_view_pesel = is_dl or user.has_role(UserRole.admin)

    def as_dict(self) -> dict[str, bool]:
        return {
            "can_work": self.can_work,
            "can_review": self.can_review,
            "can_download": self.can_download,
            "can_view_pesel": self.can_view_pesel,
        }


async def _pair_exists(db: AsyncSession, candidate_id: int, job_id: int) -> bool:
    """Osoba jest w tej rekrutacji: etap na Tablicy albo kontrakt."""

    for model in (CandidateStage, Contract):
        found = await db.scalar(
            select(model.id)
            .where(model.candidate_id == candidate_id, model.job_id == job_id)
            .limit(1)
        )
        if found is not None:
            return True
    return False


async def _pair_access(
    db: AsyncSession, user: User, candidate_id: int, job_id: int
) -> PairAccess:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Rekrutacja nie istnieje.")
    # Bez tego dowolny `candidate_id` w adresie dawałby cudzy e-mail i mail do obcej osoby.
    if not await _pair_exists(db, candidate_id, job_id):
        raise HTTPException(status_code=404, detail=MSG_NOT_IN_JOB)
    state = await svc.pair_state(db, candidate_id, job)
    if state is None:
        raise HTTPException(status_code=404, detail=MSG_NO_LIST)
    portfolio = await dl_portfolio_client_ids(db, user.id)
    member = True
    try:
        await ensure_job_membership(db, user, job_id)
    except HTTPException:
        member = False
    access = PairAccess(
        state=state, user=user, in_portfolio=job.client_id in portfolio, member=member
    )
    if not access.can_work:
        raise HTTPException(status_code=403, detail=MSG_ROLE)
    return access


def _item_for(access: PairAccess, document_id: int) -> svc.ItemState:
    item = next((i for i in access.state.items if i.document.id == document_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail=MSG_NOT_FOUND)
    return item


async def _row_for_update(
    db: AsyncSession, document_id: int, candidate_id: int, job_id: int
) -> Optional[PlacementStartDocument]:
    # `populate_existing`: `_pair_access` wczytał ten wiersz bez blokady, a po
    # odczekaniu na nią liczy się stan z bazy, nie z sesji.
    return await db.scalar(
        select(PlacementStartDocument)
        .where(
            PlacementStartDocument.document_id == document_id,
            PlacementStartDocument.candidate_id == candidate_id,
            PlacementStartDocument.job_id == job_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def _lock_or_create_row(
    db: AsyncSession, *, document_id: int, candidate_id: int, job_id: int, status: str
) -> PlacementStartDocument:
    """Wiersz pary pod blokadą. Dwa równoległe pierwsze zapisy nie dają błędu 500."""

    await db.execute(
        pg_insert(PlacementStartDocument)
        .values(
            document_id=document_id,
            candidate_id=candidate_id,
            job_id=job_id,
            status=status,
        )
        .on_conflict_do_nothing(constraint="uq_placement_start_documents_pair")
    )
    row = await _row_for_update(db, document_id, candidate_id, job_id)
    assert row is not None  # wstawiony wyżej albo przez równoległe żądanie
    return row


def _item_out(item: svc.ItemState, names: dict[int, str]) -> dict[str, Any]:
    row = item.row
    document = item.document
    return {
        **_document_out(document),
        "state": item.state,
        "deadline": _iso(item.deadline),
        "file_name": row.file_name if row else None,
        "has_value": bool(row and (row.file_path or row.pesel)),
        "delivered_at": row.delivered_at.isoformat()
        if row and row.delivered_at
        else None,
        "delivered_by_name": names.get(row.delivered_by)
        if row and row.delivered_by
        else None,
        "checked_at": row.checked_at.isoformat() if row and row.checked_at else None,
        "checked_by_name": names.get(row.checked_by)
        if row and row.checked_by
        else None,
        "reason": row.reason if row else None,
        "reason_by_name": names.get(row.reason_by) if row and row.reason_by else None,
    }


async def _names(db: AsyncSession, ids: set[Optional[int]]) -> dict[int, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(wanted)))
    return {uid: name for uid, name in rows.all()}


async def _list_sent_at(
    db: AsyncSession, candidate_id: int, job_id: int
) -> Optional[datetime]:
    rows = await db.scalars(
        select(Activity)
        .where(
            Activity.entity_type == "candidate",
            Activity.entity_id == candidate_id,
            Activity.action == "start_documents_list_sent",
        )
        .order_by(Activity.id.desc())
        .limit(20)
    )
    for activity in rows.all():
        if (activity.details or {}).get("job_id") == job_id:
            return activity.created_at
    return None


async def _pair_out(db: AsyncSession, access: PairAccess) -> dict[str, Any]:
    state = access.state
    ids: set[Optional[int]] = {state.recruiter_id, state.delivery_lead_id}
    for item in state.items:
        if item.row is not None:
            ids |= {item.row.delivered_by, item.row.checked_by, item.row.reason_by}
    names = await _names(db, ids)
    return {
        "candidate_id": state.candidate_id,
        "job_id": state.job_id,
        "client_id": state.client_id,
        "client_name": state.client_name,
        "start_date": state.start_date.isoformat() if state.start_date else None,
        "deadline": state.deadline.isoformat() if state.deadline else None,
        "tone": state.tone,
        "working": state.working,
        "done": state.done_count,
        "total": len(state.required),
        "recruiter_name": names.get(state.recruiter_id) if state.recruiter_id else None,
        "delivery_lead_name": (
            names.get(state.delivery_lead_id) if state.delivery_lead_id else None
        ),
        "agreement_number": state.agreement_number,
        "list_sent_at": _iso(await _list_sent_at(db, state.candidate_id, state.job_id)),
        "items": [_item_out(item, names) for item in state.items],
        "permissions": access.as_dict(),
    }


def _iso(value: Optional[datetime | date]) -> Optional[str]:
    return value.isoformat() if value is not None else None


@router.get("/start-documents/pair")
async def pair_view(
    current_user: WorkUser,
    db: Db,
    candidate_id: int = Query(...),
    job_id: int = Query(...),
) -> Optional[dict[str, Any]]:
    """Stan pary. Klient bez listy: ``null``, żeby front nie pokazał niczego."""

    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Rekrutacja nie istnieje.")
    if not await svc.client_lists(db, [job.client_id] if job.client_id else []):
        return None
    access = await _pair_access(db, current_user, candidate_id, job_id)
    return await _pair_out(db, access)


# ── Dostarczenie ──────────────────────────────────────────────────────────────


async def _reload(
    db: AsyncSession, user: User, candidate_id: int, job_id: int
) -> dict[str, Any]:
    await db.commit()
    return await _pair_out(db, await _pair_access(db, user, candidate_id, job_id))


async def _deliver_row(
    db: AsyncSession,
    *,
    user: User,
    document_id: int,
    candidate_id: int,
    job_id: int,
) -> PlacementStartDocument:
    row = await _lock_or_create_row(
        db,
        document_id=document_id,
        candidate_id=candidate_id,
        job_id=job_id,
        status=svc.STATUS_DELIVERED,
    )
    row.status = svc.STATUS_DELIVERED
    row.delivered_at = svc.utcnow()
    row.delivered_by = user.id
    row.checked_at = None
    row.checked_by = None
    row.reason = None
    row.reason_at = None
    row.reason_by = None
    return row


@router.put("/start-documents/pair/{candidate_id}/{job_id}/items/{document_id}/file")
async def upload_file(
    candidate_id: int,
    job_id: int,
    document_id: int,
    current_user: WorkUser,
    db: Db,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Plik liczy się od razu, Delivery Lead może go zwrócić (decyzja 05.11.2026)."""

    access = await _pair_access(db, current_user, candidate_id, job_id)
    item = _item_for(access, document_id)
    if item.document.kind != svc.KIND_FILE:
        raise HTTPException(status_code=422, detail=MSG_WRONG_KIND)
    name, content_type, data = await read_scan(
        file, format_msg="Dokument musi być plikiem PDF, JPG albo PNG."
    )
    path, _size = storage_service.save_start_document_file(
        f"pairs/{candidate_id}-{job_id}", name, data
    )
    try:
        row = await _deliver_row(
            db,
            user=current_user,
            document_id=document_id,
            candidate_id=candidate_id,
            job_id=job_id,
        )
        previous = row.file_path
        row.file_path = path
        row.file_name = name
        row.file_content_type = content_type
        result = await _reload(db, current_user, candidate_id, job_id)
    except Exception:
        # Plik z danymi o karalności nie może zostać na dysku bez wskaźnika.
        await db.rollback()
        storage_service.delete_start_document_file(path)
        raise
    if previous:
        storage_service.delete_start_document_file(previous)
    return result


@router.get("/start-documents/pair/{candidate_id}/{job_id}/items/{document_id}/file")
async def download_file(
    candidate_id: int,
    job_id: int,
    document_id: int,
    current_user: WorkUser,
    db: Db,
) -> Response:
    access = await _pair_access(db, current_user, candidate_id, job_id)
    if not access.can_download:
        raise HTTPException(status_code=403, detail=MSG_NO_FILE_ACCESS)
    item = _item_for(access, document_id)
    if item.row is None or not item.row.file_path:
        raise HTTPException(status_code=404, detail=MSG_NO_FILE)
    try:
        data = storage_service.read_start_document_file(item.row.file_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=MSG_NO_FILE) from exc
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate_id,
            action="start_documents_file_read",
            user_id=current_user.id,
            details={"job_id": job_id, "document_id": document_id},
        )
    )
    await db.commit()
    return Response(
        content=data,
        media_type=item.row.file_content_type or "application/octet-stream",
        headers={
            "Content-Disposition": content_disposition(
                item.row.file_name or "dokument", "attachment"
            )
        },
    )


class PeselIn(BaseModel):
    pesel: str = Field(min_length=11, max_length=20)


@router.put("/start-documents/pair/{candidate_id}/{job_id}/items/{document_id}/pesel")
async def save_pesel(
    candidate_id: int,
    job_id: int,
    document_id: int,
    payload: PeselIn,
    current_user: WorkUser,
    db: Db,
) -> dict[str, Any]:
    access = await _pair_access(db, current_user, candidate_id, job_id)
    item = _item_for(access, document_id)
    if item.document.kind != svc.KIND_PESEL:
        raise HTTPException(status_code=422, detail=MSG_WRONG_KIND)
    value = svc.normalize_pesel(payload.pesel)
    if value is None:
        raise HTTPException(status_code=422, detail=svc.MSG_PESEL)
    row = await _deliver_row(
        db,
        user=current_user,
        document_id=document_id,
        candidate_id=candidate_id,
        job_id=job_id,
    )
    row.pesel = value
    return await _reload(db, current_user, candidate_id, job_id)


@router.get("/start-documents/pair/{candidate_id}/{job_id}/items/{document_id}/pesel")
async def read_pesel(
    candidate_id: int,
    job_id: int,
    document_id: int,
    current_user: WorkUser,
    db: Db,
) -> dict[str, str]:
    access = await _pair_access(db, current_user, candidate_id, job_id)
    if not access.can_view_pesel:
        raise HTTPException(status_code=403, detail=MSG_NO_PESEL_ACCESS)
    item = _item_for(access, document_id)
    if item.row is None or not item.row.pesel:
        raise HTTPException(status_code=404, detail="PESEL nie jest wpisany.")
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate_id,
            action="start_documents_pesel_read",
            user_id=current_user.id,
            details={"job_id": job_id, "document_id": document_id},
        )
    )
    value = item.row.pesel
    await db.commit()
    return {"pesel": value}


# ── Delivery Lead: sprawdzenie, zwrot, „Nie dotyczy” ──────────────────────────


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/start-documents/pair/{candidate_id}/{job_id}/items/{document_id}/check")
async def check_item(
    candidate_id: int,
    job_id: int,
    document_id: int,
    current_user: WorkUser,
    db: Db,
) -> dict[str, Any]:
    access = await _pair_access(db, current_user, candidate_id, job_id)
    if not access.can_review:
        raise HTTPException(status_code=403, detail=MSG_NO_REVIEW)
    _item_for(access, document_id)
    row = await _row_for_update(db, document_id, candidate_id, job_id)
    if row is None or row.status != svc.STATUS_DELIVERED:
        raise HTTPException(status_code=409, detail=MSG_NOT_DELIVERED)
    row.checked_at = svc.utcnow()
    row.checked_by = current_user.id
    return await _reload(db, current_user, candidate_id, job_id)


async def _notify_owner(
    db: AsyncSession,
    state: svc.PairState,
    *,
    actor: User,
    title: str,
    message: str,
    ntype: NotificationType,
    entity_id: int,
) -> bool:
    """Czy dzwonek wyszedł: bez odbiorcy i przy powtórce tego dnia nie wychodzi."""

    owner = state.owner_id
    if owner is None or owner == actor.id:
        return False
    sent = await emit(
        db,
        user_id=owner,
        title=title,
        message=message,
        ntype=ntype,
        related_entity_type="placement_start_documents",
        related_entity_id=entity_id,
        link=f"/jobs/{state.job_id}?candidate={state.candidate_id}",
    )
    return sent is not None


@router.post("/start-documents/pair/{candidate_id}/{job_id}/items/{document_id}/return")
async def return_item(
    candidate_id: int,
    job_id: int,
    document_id: int,
    payload: ReasonIn,
    current_user: WorkUser,
    db: Db,
) -> dict[str, Any]:
    access = await _pair_access(db, current_user, candidate_id, job_id)
    if not access.can_review:
        raise HTTPException(status_code=403, detail=MSG_NO_REVIEW)
    item = _item_for(access, document_id)
    row = await _row_for_update(db, document_id, candidate_id, job_id)
    if row is None or row.status != svc.STATUS_DELIVERED:
        raise HTTPException(status_code=409, detail=MSG_NOT_DELIVERED)
    # Odrzucony plik nie zostaje: to dane o karalności, a nowy i tak przyjdzie.
    rejected_path = row.file_path
    row.status = svc.STATUS_RETURNED
    row.pesel = None
    row.file_path = None
    row.file_name = None
    row.file_content_type = None
    row.checked_at = None
    row.checked_by = None
    row.reason = payload.reason.strip()
    row.reason_at = svc.utcnow()
    row.reason_by = current_user.id
    await _notify_owner(
        db,
        access.state,
        actor=current_user,
        title="Dokument do startu wrócił do poprawy",
        message=(
            f"{access.state.candidate_name}: {item.document.name}. Powód: {row.reason}"
        ),
        ntype=NotificationType.start_documents_returned,
        entity_id=row.id,
    )
    result = await _reload(db, current_user, candidate_id, job_id)
    if rejected_path:
        storage_service.delete_start_document_file(rejected_path)
    return result


@router.post(
    "/start-documents/pair/{candidate_id}/{job_id}/items/{document_id}/not-applicable"
)
async def not_applicable(
    candidate_id: int,
    job_id: int,
    document_id: int,
    payload: ReasonIn,
    current_user: WorkUser,
    db: Db,
) -> dict[str, Any]:
    """Np. powrót po przerwie z ważnym NDA. Powód zostaje w historii pozycji."""

    access = await _pair_access(db, current_user, candidate_id, job_id)
    if not access.can_review:
        raise HTTPException(status_code=403, detail=MSG_NO_REVIEW)
    _item_for(access, document_id)
    row = await _lock_or_create_row(
        db,
        document_id=document_id,
        candidate_id=candidate_id,
        job_id=job_id,
        status=svc.STATUS_NOT_APPLICABLE,
    )
    row.status = svc.STATUS_NOT_APPLICABLE
    row.reason = payload.reason.strip()
    row.reason_at = svc.utcnow()
    row.reason_by = current_user.id
    return await _reload(db, current_user, candidate_id, job_id)


@router.delete(
    "/start-documents/pair/{candidate_id}/{job_id}/items/{document_id}/state"
)
async def reset_item(
    candidate_id: int,
    job_id: int,
    document_id: int,
    current_user: WorkUser,
    db: Db,
) -> dict[str, Any]:
    """Cofa „Nie dotyczy”: pozycja wraca do stanu sprzed decyzji DL-a."""

    access = await _pair_access(db, current_user, candidate_id, job_id)
    if not access.can_review:
        raise HTTPException(status_code=403, detail=MSG_NO_REVIEW)
    _item_for(access, document_id)
    row = await _row_for_update(db, document_id, candidate_id, job_id)
    if row is not None and row.status == svc.STATUS_NOT_APPLICABLE:
        if row.file_path or row.pesel:
            row.status = svc.STATUS_DELIVERED
            row.reason = None
            row.reason_at = None
            row.reason_by = None
        else:
            await db.delete(row)
    return await _reload(db, current_user, candidate_id, job_id)


@router.post("/start-documents/pair/{candidate_id}/{job_id}/remind")
async def remind_recruiter(
    candidate_id: int, job_id: int, current_user: WorkUser, db: Db
) -> dict[str, bool]:
    """„Przypomnij rekruterowi”. Dzwonek najwyżej raz dziennie (``emit``)."""

    access = await _pair_access(db, current_user, candidate_id, job_id)
    if not access.can_review:
        raise HTTPException(status_code=403, detail=MSG_NO_REVIEW)
    state = access.state
    if state.complete:
        return {"sent": False}
    sent = await _notify_owner(
        db,
        state,
        actor=current_user,
        title=f"{current_user.name} prosi o dokumenty do startu",
        message=(
            f"{state.candidate_name}: brakuje "
            f"{', '.join(i.document.name for i in state.missing)}."
        ),
        ntype=NotificationType.start_documents_reminder,
        entity_id=state.candidate_id,
    )
    await db.commit()
    return {"sent": sent}


# ── Wzory i mail do konsultanta ───────────────────────────────────────────────


async def _agreement_payload(
    db: AsyncSession, candidate_id: int, job_id: int
) -> Optional[dict[str, Any]]:
    return await db.scalar(
        select(B2BGeneratedContract.render_payload)
        .where(
            B2BGeneratedContract.candidate_id == candidate_id,
            B2BGeneratedContract.job_id == job_id,
            B2BGeneratedContract.contract_status.in_(("in_progress", "active")),
        )
        .order_by(B2BGeneratedContract.id.desc())
        .limit(1)
    )


async def _template_bytes(
    db: AsyncSession, document: ClientStartDocument, state: svc.PairState
) -> Optional[bytes]:
    if not document.template_path:
        return None
    try:
        data = storage_service.read_start_document_file(document.template_path)
    except FileNotFoundError:
        logger.warning("[start_documents] brak pliku wzoru document=%s", document.id)
        return None
    if document.fill_from_agreement:
        payload = await _agreement_payload(db, state.candidate_id, state.job_id)
        return fill.fill_template(data, fill.values_from_payload(payload))
    return data


@router.get(
    "/start-documents/pair/{candidate_id}/{job_id}/items/{document_id}/template"
)
async def download_pair_template(
    candidate_id: int,
    job_id: int,
    document_id: int,
    current_user: WorkUser,
    db: Db,
) -> Response:
    access = await _pair_access(db, current_user, candidate_id, job_id)
    item = _item_for(access, document_id)
    data = await _template_bytes(db, item.document, access.state)
    if data is None:
        raise HTTPException(status_code=404, detail=MSG_NO_TEMPLATE)
    return Response(
        content=data,
        media_type=item.document.template_content_type or "application/octet-stream",
        headers={
            "Content-Disposition": content_disposition(
                mail.attachment_name(item.document, access.state), "attachment"
            )
        },
    )


async def _list_attachments(
    db: AsyncSession, state: svc.PairState
) -> list[FileAttachment]:
    found: list[FileAttachment] = []
    for item in state.items:
        if item.done or not item.document.template_path:
            continue
        data = await _template_bytes(db, item.document, state)
        if data is None or len(data) > MAX_ATTACHMENT_BYTES:
            continue
        found.append(
            FileAttachment(
                name=mail.attachment_name(item.document, state),
                content_type=(
                    item.document.template_content_type or "application/octet-stream"
                ),
                data=data,
            )
        )
    return found


async def _candidate_email(db: AsyncSession, candidate_id: int) -> Optional[str]:
    return await db.scalar(select(Candidate.email).where(Candidate.id == candidate_id))


@router.get("/start-documents/pair/{candidate_id}/{job_id}/list-mail")
async def list_mail_preview(
    candidate_id: int, job_id: int, current_user: WorkUser, db: Db
) -> dict[str, Any]:
    access = await _pair_access(db, current_user, candidate_id, job_id)
    attachments = await _list_attachments(db, access.state)
    subject, _body, text = mail.render(access.state, [a.name for a in attachments])
    return {
        "to": await _candidate_email(db, candidate_id),
        "subject": subject,
        "text": text,
        "attachments": [a.name for a in attachments],
        "mailbox_connected": await mailbox_connected(db, current_user.id),
        "list_sent_at": _iso(await _list_sent_at(db, candidate_id, job_id)),
    }


@router.post("/start-documents/pair/{candidate_id}/{job_id}/list-mail")
async def list_mail_send(
    candidate_id: int, job_id: int, current_user: WorkUser, db: Db
) -> dict[str, Any]:
    access = await _pair_access(db, current_user, candidate_id, job_id)
    to = await _candidate_email(db, candidate_id)
    if not to:
        raise HTTPException(status_code=422, detail=MSG_NO_EMAIL)
    attachments = await _list_attachments(db, access.state)
    subject, body, _text = mail.render(access.state, [a.name for a in attachments])
    today = svc.business_today().isoformat()
    sent, problem = await send_from(
        db,
        user_id=current_user.id,
        to=to,
        subject=subject,
        body_html=body,
        candidate_id=candidate_id,
        request_key=f"start-docs-{candidate_id}-{job_id}-{current_user.id}-{today}",
        attachments=attachments,
    )
    if not sent:
        raise HTTPException(status_code=409, detail=problem or "Mail nie wyszedł.")
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate_id,
            action="start_documents_list_sent",
            user_id=current_user.id,
            details={"job_id": job_id, "attachments": [a.name for a in attachments]},
        )
    )
    await db.commit()
    return {"sent": True}


# ── Moje sprawy: pasek i pulpit ───────────────────────────────────────────────


def _mine_row(state: svc.PairState, names: dict[int, str]) -> dict[str, Any]:
    return {
        "candidate_id": state.candidate_id,
        "job_id": state.job_id,
        "candidate_name": state.candidate_name,
        "job_title": state.job_title,
        "client_name": state.client_name,
        "agreement_number": state.agreement_number,
        "start_date": _iso(state.start_date),
        "deadline": _iso(state.deadline),
        "tone": state.tone,
        "working": state.working,
        "done": state.done_count,
        "total": len(state.required),
        "missing": [i.document.name for i in state.missing],
        "to_check": [
            i.document.name
            for i in state.items
            if i.state == svc.STATUS_DELIVERED
            and i.row is not None
            and i.row.checked_at is None
            and i.document.kind == svc.KIND_FILE
        ],
        "recruiter_name": names.get(state.recruiter_id) if state.recruiter_id else None,
    }


@router.get("/start-documents/mine")
async def mine(current_user: WorkUser, db: Db) -> dict[str, Any]:
    """Moje pary bez kompletu: jako rekruter i jako Delivery Lead."""

    states = await svc.open_states(db)
    user_id = current_user.id
    is_dl = current_user.has_role(UserRole.delivery_lead)
    # Portfel daje dostęp do pary, ale lista i czerwona liczba są tylko „moje”:
    # Nordea ma trzech DL-i, a każdy odpowiada za swoje rekrutacje.
    as_dl = [s for s in states if is_dl and s.delivery_lead_id == user_id]
    chosen = [
        s for s in states if s.recruiter_id == user_id or s.delivery_lead_id == user_id
    ]
    if not is_dl:
        chosen = [s for s in chosen if s.recruiter_id == user_id]
    names = await _names(db, {s.recruiter_id for s in chosen})
    return {
        "role": "delivery_lead" if as_dl else "recruiter",
        "items": [_mine_row(s, names) for s in chosen],
    }
