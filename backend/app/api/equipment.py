"""Sprzęt i protokoły — rejestr, wydania i zwroty, import plików recepcji.

Prefiks ``/api/equipment`` (wpięty w ``app/main.py``). Każda trasa ma nazwaną bramkę
``require_hr_*`` (``app/api/hr_gates.py`` albo własną w tym module) i sprawdza
przełącznik modułu w ``app_settings['hr_modules']``.

Kto co widzi (D13 — „Sprzęt” osobno od „Kadr”):

* uprawnienie „Sprzęt” (recepcja, admin) — cały rejestr, wydania, zwroty,
  protokoły, zadania, cennik i import; posiadaczem bywa też uczestnik
  Akademii (``holder_kind="academy"``, id zgłoszenia),
* Kadry — sprzęt osoby tylko do odczytu (``GET /people/{user_id}``),
* każdy — własny sprzęt (``GET /me``),
* podgląd Delivery — sprzęt kontraktu (zakładka „Sprzęt” kontraktu) w zakresie
  klientów Delivery Leada; zadanie zwrotu przy zakończeniu współpracy zakłada
  też „Status kontraktu”; flagę klienta „sprzęt od nas” zmienia też „Edycja
  klientów”,
* wzory protokołów (etap 3, O3) — wgrywa, wycofuje i pobiera recepcja (admin
  ma wszystko); wybór wzoru dla klienta jest w pakiecie klienta
  (``api/client_onboarding.py``).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.care_gates import refuse_automation
from app.api.deps import require_onboarded_user
from app.api.hr_gates import ensure_module
from app.core.database import get_db
from app.core.http_headers import content_disposition
from app.core.scheduling import business_today
from app.models.client import Client
from app.models.contract import Contract
from app.models.user import User
from app.services.access_scope import (
    assert_delivery_lead_client_visible,
    resolve_delivery_lead_client_ids,
)
from app.services.action_permissions import ProductAction, has_permission
from app.services.equipment import (
    importer,
    issuing,
    protocol_changes,
    protocol_document,
    protocol_template,
    protocols,
    registry,
    tasks,
)
from app.services.equipment.registry import EquipmentError
from app.services.hr.modules import HrModule
from app.services.permission_denial import ensure_any_permission

router = APIRouter()

MAX_UPLOAD_BYTES = 20 * 1024 * 1024

Category = Literal[
    "laptop", "telefon", "monitor", "karta_sim", "karta_dostepu", "akcesorium", "inne"
]
ItemStatus = Literal["na_stanie", "wydany", "serwis", "wycofany", "zgubiony"]
Ownership = Literal["nasz", "klienta"]
HolderKindIn = Literal["user", "contract", "external", "academy"]
Condition = Literal["sprawny", "uszkodzony", "niekompletny", "zgubiony"]


# ── Bramki ────────────────────────────────────────────────────────────────────


def require_hr_equipment(*permissions: ProductAction):
    """Moduł „Sprzęt” włączony i jedno z ``permissions`` (admin ma wszystkie)."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, HrModule.equipment)
        ensure_any_permission(current_user, *permissions)
        return current_user

    _check.required_permissions = permissions
    return _check


def require_hr_equipment_person_reader():
    """Sprzęt osoby: ona sama, recepcja albo Kadry (tylko odczyt)."""

    async def _check(
        user_id: int,
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, HrModule.equipment)
        if current_user.id != user_id:
            ensure_any_permission(
                current_user, ProductAction.equipment, ProductAction.people_admin
            )
        return current_user

    return _check


def require_hr_equipment_self():
    """Własny sprzęt — każde konto po onboardingu, przy włączonym module."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, HrModule.equipment)
        return current_user

    return _check


_manager = require_hr_equipment(ProductAction.equipment)


def require_hr_equipment_contract_reader():
    """Sprzęt konsultanta na kontrakcie: recepcja albo podgląd Delivery —
    bez roli „Automatyzacje” (decyzja Artura 19.10.2026, numery seryjne
    i protokoły to nie dane do integracji)."""

    permissions = (ProductAction.equipment, ProductAction.delivery_view)

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        refuse_automation(current_user)
        await ensure_module(db, current_user, HrModule.equipment)
        ensure_any_permission(current_user, *permissions)
        return current_user

    _check.required_permissions = permissions
    return _check


_contract_reader = require_hr_equipment_contract_reader()
_return_planner = require_hr_equipment(
    ProductAction.equipment, ProductAction.contract_status
)
_provider_reader = require_hr_equipment(
    ProductAction.equipment, ProductAction.delivery_view
)
_provider_editor = require_hr_equipment(
    ProductAction.equipment, ProductAction.clients_edit
)
_person_reader = require_hr_equipment_person_reader()
_self = require_hr_equipment_self()


def _http(exc: EquipmentError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


async def _client_in_scope(db: AsyncSession, user: User, client_id: int) -> None:
    """Delivery Lead działa u swoich klientów; recepcja i pozostali — u wszystkich."""
    if has_permission(user, ProductAction.equipment):
        return
    assert_delivery_lead_client_visible(
        client_id, await resolve_delivery_lead_client_ids(user, db)
    )


async def _contract_in_scope(
    db: AsyncSession, user: User, contract_id: int
) -> Contract:
    contract = await db.get(Contract, contract_id)
    if contract is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego kontraktu.")
    await _client_in_scope(db, user, contract.client_id)
    return contract


# ── Modele żądań ──────────────────────────────────────────────────────────────


class ModelIn(BaseModel):
    category: Category
    name: str = Field(min_length=1, max_length=200)
    manufacturer: Optional[str] = Field(default=None, max_length=120)
    price_pln: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("9999999"))
    is_active: bool = True


class ModelPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    manufacturer: Optional[str] = Field(default=None, max_length=120)
    price_pln: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("9999999"))
    is_active: Optional[bool] = None


class ItemFields(BaseModel):
    inventory_number: Optional[str] = Field(default=None, max_length=40)
    serial_number: Optional[str] = Field(default=None, max_length=120)
    imei: Optional[str] = Field(default=None, max_length=32)
    iccid: Optional[str] = Field(default=None, max_length=40)
    phone_number: Optional[str] = Field(default=None, max_length=32)
    access_card_number: Optional[str] = Field(default=None, max_length=40)
    ownership: Optional[Ownership] = None
    purchase_date: Optional[date] = None
    location: Optional[str] = Field(default=None, max_length=120)
    notes: Optional[str] = Field(default=None, max_length=2000)


class ItemIn(ItemFields):
    model_id: int
    status: Optional[ItemStatus] = None


class ItemPatch(ItemFields):
    model_id: Optional[int] = None
    status: Optional[ItemStatus] = None


class ExternalPersonIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    work_email: Optional[str] = Field(default=None, max_length=255)
    note: Optional[str] = Field(default=None, max_length=200)


class MoveToUserIn(BaseModel):
    user_id: int


class IssueLineIn(BaseModel):
    item_id: int
    unit_value: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("9999999"))
    accessories: Optional[str] = Field(default=None, max_length=200)


class IssueIn(BaseModel):
    holder_kind: HolderKindIn
    holder_id: int
    protocol_date: Optional[date] = None
    lines: list[IssueLineIn] = Field(min_length=1, max_length=40)
    send_link: bool = False


class ReturnLineIn(BaseModel):
    assignment_id: int
    condition: Condition
    notes: Optional[str] = Field(default=None, max_length=500)


class ReturnIn(BaseModel):
    protocol_date: Optional[date] = None
    lines: list[ReturnLineIn] = Field(min_length=1, max_length=40)


class ConfirmIn(BaseModel):
    method: Optional[Literal["papier", "profil_zaufany"]] = None
    signer_name: Optional[str] = Field(default=None, max_length=200)


class ProtocolLineFix(BaseModel):
    position: int = Field(ge=1)
    unit_value: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("9999999"))
    accessories: Optional[str] = Field(default=None, max_length=200)
    condition: Optional[Condition] = None
    notes: Optional[str] = Field(default=None, max_length=500)


class ProtocolFix(BaseModel):
    """Poprawka przed podpisem — przysłane pola zmieniają, brak pola = bez zmiany."""

    protocol_date: Optional[date] = None
    holder_name: Optional[str] = Field(default=None, max_length=200)
    lines: list[ProtocolLineFix] = Field(default_factory=list, max_length=40)


class ProtocolCancelIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class TaskPatch(BaseModel):
    status: Literal["otwarte", "zrobione", "anulowane"]


class ImportRowPatch(BaseModel):
    decision: Literal["przyjmij", "pomin", "konflikt", "do_wyjasnienia"]
    holder_user_id: Optional[int] = None
    holder_contract_id: Optional[int] = None


class ProviderIn(BaseModel):
    equipment_provider: Literal["nasz", "klienta", "nieznany"]


class TemplatePatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=300)
    is_active: Optional[bool] = None


# ── Rejestr ───────────────────────────────────────────────────────────────────


@router.get("/summary")
async def get_summary(
    _: User = Depends(_manager), db: AsyncSession = Depends(get_db)
) -> dict:
    return await registry.summary(db)


@router.get("/models")
async def list_models(
    _: User = Depends(_manager), db: AsyncSession = Depends(get_db)
) -> dict:
    return {"items": await registry.list_models(db)}


@router.post("/models", status_code=status.HTTP_201_CREATED)
async def create_model(
    payload: ModelIn,
    current_user: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        model = await registry.create_model(
            db, payload.model_dump(), actor=current_user
        )
    except EquipmentError as exc:
        raise _http(exc) from exc
    return registry.model_payload(model)


@router.patch("/models/{model_id}")
async def update_model(
    model_id: int,
    payload: ModelPatch,
    current_user: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        model = await registry.update_model(
            db, model_id, payload.model_dump(exclude_unset=True), actor=current_user
        )
    except EquipmentError as exc:
        raise _http(exc) from exc
    return registry.model_payload(model)


@router.get("/items")
async def list_items(
    category: Optional[Category] = None,
    item_status: Optional[ItemStatus] = Query(default=None, alias="status"),
    holder: Optional[Literal["none", "user", "contract", "external", "academy"]] = None,
    q: Optional[str] = Query(default=None, max_length=120),
    free: bool = False,
    unsigned: bool = False,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await registry.list_items(
        db,
        category=category,
        status=item_status,
        holder=holder,
        q=q,
        free_only=free,
        unsigned=unsigned,
        limit=limit,
        offset=offset,
    )


@router.post("/items", status_code=status.HTTP_201_CREATED)
async def create_item(
    payload: ItemIn,
    current_user: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        item = await registry.create_item(
            db, payload.model_dump(exclude_unset=True), actor=current_user
        )
    except EquipmentError as exc:
        raise _http(exc) from exc
    return await registry.item_detail(db, item.id)


@router.get("/items/{item_id}")
async def get_item(
    item_id: int, _: User = Depends(_manager), db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        return await registry.item_detail(db, item_id)
    except EquipmentError as exc:
        raise _http(exc) from exc


@router.patch("/items/{item_id}")
async def update_item(
    item_id: int,
    payload: ItemPatch,
    current_user: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        await registry.update_item(
            db, item_id, payload.model_dump(exclude_unset=True), actor=current_user
        )
        return await registry.item_detail(db, item_id)
    except EquipmentError as exc:
        raise _http(exc) from exc


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: int,
    current_user: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        await registry.delete_item(db, item_id, actor=current_user)
    except EquipmentError as exc:
        raise _http(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/holders")
async def search_holders(
    q: str = Query(default="", max_length=120),
    kind: Optional[Literal["academy"]] = None,
    _: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Konta, kontrakty i osoby spoza; ``kind=academy`` — uczestnicy Akademii."""
    return {"items": await registry.search_holders(db, q, kind=kind)}


@router.get("/holders/{kind}/{holder_id}")
async def holder_equipment(
    kind: HolderKindIn,
    holder_id: int,
    _: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        holder = await registry.resolve_holder(db, kind, holder_id)
    except EquipmentError as exc:
        raise _http(exc) from exc
    return {
        "holder": holder.as_dict(),
        **await registry.holder_equipment(db, kind, holder_id),
    }


@router.get("/external-people")
async def list_external_people(
    q: Optional[str] = Query(default=None, max_length=120),
    _: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {"items": await registry.list_external_people(db, q)}


@router.post("/external-people", status_code=status.HTTP_201_CREATED)
async def create_external_person(
    payload: ExternalPersonIn,
    current_user: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        person = await registry.create_external_person(
            db, payload.model_dump(), actor=current_user
        )
    except EquipmentError as exc:
        raise _http(exc) from exc
    return registry.external_payload(person)


@router.post("/external-people/{person_id}/move-to-user")
async def move_external_person_to_user(
    person_id: int,
    payload: MoveToUserIn,
    current_user: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """„Przepisz na konto”: niezwrócony sprzęt osoby spoza NEXUSA na jej nowe konto."""
    try:
        return await registry.move_external_to_user(
            db, person_id, payload.user_id, actor=current_user
        )
    except EquipmentError as exc:
        raise _http(exc) from exc


# ── Wydanie i zwrot ───────────────────────────────────────────────────────────


@router.post("/issue", status_code=status.HTTP_201_CREATED)
async def issue_equipment(
    payload: IssueIn,
    current_user: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        result = await issuing.issue(
            db,
            holder_kind=payload.holder_kind,
            holder_id=payload.holder_id,
            lines=[
                issuing.IssueLine(
                    item_id=line.item_id,
                    unit_value=line.unit_value,
                    accessories=line.accessories,
                )
                for line in payload.lines
            ],
            protocol_date=payload.protocol_date or business_today(),
            actor=current_user,
            with_link=payload.send_link,
        )
    except EquipmentError as exc:
        raise _http(exc) from exc
    lines = await protocols.protocol_lines(db, result.protocol.id)
    return {
        "protocol": protocols.protocol_payload(result.protocol, lines),
        "link_url": protocols.public_url(result.link_token)
        if result.link_token
        else None,
    }


@router.post("/return", status_code=status.HTTP_201_CREATED)
async def return_equipment(
    payload: ReturnIn,
    current_user: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        protocol = await issuing.return_items(
            db,
            lines=[
                issuing.ReturnLine(
                    assignment_id=line.assignment_id,
                    condition=line.condition,
                    notes=line.notes,
                )
                for line in payload.lines
            ],
            protocol_date=payload.protocol_date or business_today(),
            actor=current_user,
        )
    except EquipmentError as exc:
        raise _http(exc) from exc
    lines = await protocols.protocol_lines(db, protocol.id)
    return {"protocol": protocols.protocol_payload(protocol, lines)}


# ── Protokoły ─────────────────────────────────────────────────────────────────


@router.get("/protocols")
async def list_protocols(
    protocol_status: Optional[
        Literal["waiting", "oczekuje", "podpisany", "potwierdzony", "anulowany"]
    ] = Query(default=None, alias="status"),
    kind: Optional[Literal["wydanie", "zwrot"]] = None,
    q: Optional[str] = Query(default=None, max_length=120),
    _: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {
        "items": await protocols.list_protocols(
            db, status=protocol_status, kind=kind, q=q
        )
    }


async def _protocol(db: AsyncSession, protocol_id: int):
    try:
        return await protocols.get_protocol(db, protocol_id)
    except EquipmentError as exc:
        raise _http(exc) from exc


@router.get("/protocols/{protocol_id}")
async def get_protocol(
    protocol_id: int, _: User = Depends(_manager), db: AsyncSession = Depends(get_db)
) -> dict:
    return await _protocol_detail(db, await _protocol(db, protocol_id))


async def _protocol_detail(db: AsyncSession, protocol) -> dict:
    """Protokół z pozycjami i linkiem; pozycje wydania niosą podstawę nazwy
    i dodatki do okna „Popraw protokół”."""
    lines = await protocols.protocol_lines(db, protocol.id)
    link = await protocols.latest_link(db, protocol.id)
    payload = protocols.protocol_payload(protocol, lines, link=link)
    editable = await protocol_changes.editable_lines(db, protocol, lines)
    for line in payload["lines"]:
        line.update(editable.get(line["position"], {}))
    return payload


@router.patch("/protocols/{protocol_id}")
async def correct_protocol(
    protocol_id: int,
    payload: ProtocolFix,
    current_user: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Poprawka protokołu przed podpisem (decyzja Artura 28.10.2026)."""
    fields = payload.model_dump(
        include={"protocol_date", "holder_name"}, exclude_unset=True
    )
    try:
        protocol, link_revoked = await protocol_changes.correct(
            db,
            protocol_id,
            fields=fields,
            lines=[line.model_dump(exclude_unset=True) for line in payload.lines],
            actor=current_user,
        )
    except EquipmentError as exc:
        raise _http(exc) from exc
    return {**await _protocol_detail(db, protocol), "link_revoked": link_revoked}


@router.post("/protocols/{protocol_id}/cancel")
async def cancel_protocol(
    protocol_id: int,
    payload: ProtocolCancelIn,
    current_user: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Anulowanie niepotwierdzonego protokołu z powodem (decyzja Artura 28.10.2026)."""
    try:
        protocol = await protocol_changes.cancel(
            db, protocol_id, reason=payload.reason, actor=current_user
        )
    except EquipmentError as exc:
        raise _http(exc) from exc
    return await _protocol_detail(db, protocol)


@router.get("/protocols/{protocol_id}/document.docx")
async def protocol_docx(
    protocol_id: int, _: User = Depends(_manager), db: AsyncSession = Depends(get_db)
) -> Response:
    protocol = await _protocol(db, protocol_id)
    try:
        # Wzór z pakietu klienta, z którego powstał protokół (albo standard).
        content = await protocols.render_docx(db, protocol)
    except EquipmentError as exc:
        raise _http(exc) from exc
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": content_disposition(
                protocols.protocol_filename(protocol, "docx")
            )
        },
    )


@router.get("/protocols/{protocol_id}/document.pdf")
async def protocol_pdf(
    protocol_id: int, _: User = Depends(_manager), db: AsyncSession = Depends(get_db)
) -> Response:
    protocol = await _protocol(db, protocol_id)
    try:
        content = await protocols.render_pdf(db, protocol)
    except EquipmentError as exc:
        raise _http(exc) from exc
    except protocol_document.ProtocolPdfUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "PDF jest chwilowo niedostępny — pobierz plik Word.",
        ) from exc
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition(
                protocols.protocol_filename(protocol, "pdf")
            )
        },
    )


@router.post("/protocols/{protocol_id}/link")
async def create_protocol_link(
    protocol_id: int,
    current_user: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    protocol = await _protocol(db, protocol_id)
    try:
        link, token = await protocols.create_link(db, protocol, actor=current_user)
    except EquipmentError as exc:
        raise _http(exc) from exc
    return {
        "url": protocols.public_url(token),
        "expires_at": link.expires_at.isoformat(),
        "holder_email": protocol.holder_email,
    }


@router.post("/protocols/{protocol_id}/signed-file")
async def upload_signed_file(
    protocol_id: int,
    file: UploadFile = File(...),
    method: Literal["papier", "profil_zaufany"] = Form(...),
    current_user: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    protocol = await _protocol(db, protocol_id)
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        await protocols.save_signed_file(
            db,
            protocol,
            filename=file.filename or "protokol.pdf",
            content=content,
            method=method,
            actor=current_user,
        )
    except EquipmentError as exc:
        raise _http(exc) from exc
    return protocols.protocol_payload(protocol)


@router.get("/protocols/{protocol_id}/signed-file")
async def download_signed_file(
    protocol_id: int, _: User = Depends(_manager), db: AsyncSession = Depends(get_db)
) -> FileResponse:
    protocol = await _protocol(db, protocol_id)
    try:
        path = protocols.signed_file_path(protocol)
    except EquipmentError as exc:
        raise _http(exc) from exc
    return FileResponse(
        path,
        headers={
            "Content-Disposition": content_disposition(
                protocols.protocol_filename(protocol, path.suffix.lstrip(".") or "pdf")
            )
        },
    )


@router.post("/protocols/{protocol_id}/confirm")
async def confirm_protocol(
    protocol_id: int,
    payload: ConfirmIn,
    current_user: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    protocol = await _protocol(db, protocol_id)
    try:
        await protocols.confirm(
            db,
            protocol,
            method=payload.method,
            signer_name=payload.signer_name,
            actor=current_user,
        )
    except EquipmentError as exc:
        raise _http(exc) from exc
    return protocols.protocol_payload(protocol)


# ── Wzory protokołów (etap 3, O3) ─────────────────────────────────────────────

_DOCX = protocol_template.DOCX_MEDIA_TYPE


def _docx_response(content: bytes, filename: str) -> Response:
    return Response(
        content,
        media_type=_DOCX,
        headers={"Content-Disposition": content_disposition(filename)},
    )


@router.get("/protocol-templates")
async def list_protocol_templates(
    _: User = Depends(_manager), db: AsyncSession = Depends(get_db)
) -> dict:
    """Wgrane wzory z liczbą pakietów i protokołów oraz lista pól do wzoru."""
    return {
        "items": await protocol_template.list_templates(db),
        "fields": list(protocol_template.field_rows()),
        "required": protocol_template.REQUIRED_FIELDS,
        "max_bytes": protocol_template.MAX_UPLOAD_BYTES,
    }


@router.post("/protocol-templates", status_code=status.HTTP_201_CREATED)
async def upload_protocol_template(
    file: UploadFile = File(...),
    kind: Literal["wydanie", "zwrot"] = Form(...),
    name: str = Form(..., min_length=1, max_length=120),
    description: Optional[str] = Form(default=None, max_length=300),
    current_user: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    content = await file.read(protocol_template.MAX_UPLOAD_BYTES + 1)
    try:
        template = await protocol_template.create_template(
            db,
            kind=kind,
            name=name,
            description=description,
            filename=file.filename or "",
            content=content,
            actor=current_user,
        )
    except EquipmentError as exc:
        raise _http(exc) from exc
    return protocol_template.template_payload(template)


@router.patch("/protocol-templates/{template_id}")
async def update_protocol_template(
    template_id: int,
    payload: TemplatePatch,
    current_user: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        template = await protocol_template.update_template(
            db, template_id, payload.model_dump(exclude_unset=True), actor=current_user
        )
    except EquipmentError as exc:
        raise _http(exc) from exc
    return protocol_template.template_payload(template)


@router.get("/protocol-templates/standard/{kind}")
async def standard_protocol_template(
    kind: Literal["wydanie", "zwrot"], _: User = Depends(_manager)
) -> Response:
    """Wbudowany standard jako punkt wyjścia do własnego wzoru."""
    return _docx_response(
        protocol_template.standard_template_bytes(kind),
        f"Wzor_protokolu_{kind}_standard.docx",
    )


@router.get("/protocol-templates/{template_id}/file")
async def protocol_template_file(
    template_id: int, _: User = Depends(_manager), db: AsyncSession = Depends(get_db)
) -> Response:
    try:
        template, content = await protocol_template.template_content(db, template_id)
    except EquipmentError as exc:
        raise _http(exc) from exc
    return _docx_response(content, template.file_name)


@router.get("/protocol-templates/{template_id}/sample")
async def protocol_template_sample(
    template_id: int, _: User = Depends(_manager), db: AsyncSession = Depends(get_db)
) -> Response:
    """Wzór wypełniony fikcyjnym protokołem — sprawdzenie przed wyborem w pakiecie."""
    try:
        template, content = await protocol_template.template_content(db, template_id)
        document = protocol_template.sample_document(content, template.kind)
    except EquipmentError as exc:
        raise _http(exc) from exc
    return _docx_response(document, f"Probka_{template.file_name}")


# ── Do zrobienia ──────────────────────────────────────────────────────────────


@router.get("/tasks")
async def list_tasks(
    task_status: Literal["otwarte", "zrobione", "anulowane", "all"] = Query(
        default="otwarte", alias="status"
    ),
    _: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {"items": await tasks.list_tasks(db, status=task_status)}


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: int,
    payload: TaskPatch,
    current_user: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        task = await tasks.set_task_status(
            db, task_id, payload.status, actor=current_user
        )
    except EquipmentError as exc:
        raise _http(exc) from exc
    return {"id": task.id, "status": task.status}


@router.post("/tasks/{task_id}/remind")
async def remind_task_holder(
    task_id: int,
    current_user: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """„Przypomnij” przy zwrocie: dzwonek i mail do konta albo adres do wiadomości recepcji."""
    try:
        return await tasks.remind_holder(db, task_id, actor=current_user)
    except EquipmentError as exc:
        raise _http(exc) from exc


# ── Import plików recepcji ────────────────────────────────────────────────────


@router.post("/imports", status_code=status.HTTP_201_CREATED)
async def upload_import(
    file: UploadFile = File(...),
    current_user: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    content = await file.read(importer.MAX_FILE_BYTES + 1)
    try:
        batch = await importer.create_batch(
            db,
            filename=file.filename or "plik.xlsx",
            content=content,
            actor=current_user,
        )
    except EquipmentError as exc:
        raise _http(exc) from exc
    return importer.batch_payload(batch)


@router.get("/imports")
async def list_imports(
    _: User = Depends(_manager), db: AsyncSession = Depends(get_db)
) -> dict:
    return {"items": await importer.list_batches(db)}


@router.get("/imports/{batch_id}")
async def get_import(
    batch_id: int,
    decision: Optional[
        Literal["przyjmij", "pomin", "konflikt", "do_wyjasnienia"]
    ] = None,
    _: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        batch = await importer.get_batch(db, batch_id)
    except EquipmentError as exc:
        raise _http(exc) from exc
    return {
        **importer.batch_payload(batch),
        "rows": await importer.batch_rows(db, batch_id, decision=decision),
    }


@router.patch("/imports/{batch_id}/rows/{row_id}")
async def update_import_row(
    batch_id: int,
    row_id: int,
    payload: ImportRowPatch,
    current_user: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        row = await importer.update_row(
            db,
            batch_id,
            row_id,
            decision=payload.decision,
            holder_user_id=payload.holder_user_id,
            holder_contract_id=payload.holder_contract_id,
            actor=current_user,
        )
    except EquipmentError as exc:
        raise _http(exc) from exc
    return importer.row_payload(row)


@router.get("/imports/{batch_id}/control-sheet.xlsx")
async def import_control_sheet(
    batch_id: int, _: User = Depends(_manager), db: AsyncSession = Depends(get_db)
) -> Response:
    try:
        content = await importer.control_sheet(db, batch_id)
    except EquipmentError as exc:
        raise _http(exc) from exc
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": content_disposition(
                f"Arkusz_kontrolny_importu_{batch_id}.xlsx"
            )
        },
    )


@router.post("/imports/{batch_id}/apply")
async def apply_import(
    batch_id: int,
    current_user: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await importer.apply_batch(db, batch_id, actor=current_user)
    except EquipmentError as exc:
        raise _http(exc) from exc


# ── Kontrakt, klient, osoba ───────────────────────────────────────────────────


@router.get("/contracts/{contract_id}")
async def contract_equipment(
    contract_id: int,
    current_user: User = Depends(_contract_reader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _contract_in_scope(db, current_user, contract_id)
    return await registry.holder_equipment(db, "contract", contract_id)


@router.post("/contracts/{contract_id}/return-task")
async def contract_return_task(
    contract_id: int,
    current_user: User = Depends(_return_planner),
    db: AsyncSession = Depends(get_db),
) -> dict:
    contract = await _contract_in_scope(db, current_user, contract_id)
    task = await tasks.tasks_for_contract_end(db, contract)
    if task is None:
        return {"task": None}
    return {
        "task": {
            "id": task.id,
            "title": task.title,
            "due_on": task.due_on.isoformat() if task.due_on else None,
            "status": task.status,
        }
    }


@router.get("/clients/{client_id}/provider")
async def get_client_provider(
    client_id: int,
    current_user: User = Depends(_provider_reader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if await db.get(Client, client_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego klienta.")
    await _client_in_scope(db, current_user, client_id)
    return {"equipment_provider": await registry.client_provider(db, client_id)}


@router.put("/clients/{client_id}/provider")
async def set_client_provider(
    client_id: int,
    payload: ProviderIn,
    current_user: User = Depends(_provider_editor),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if await db.get(Client, client_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego klienta.")
    await _client_in_scope(db, current_user, client_id)
    try:
        value = await registry.set_client_provider(
            db, client_id, payload.equipment_provider, actor=current_user
        )
    except EquipmentError as exc:
        raise _http(exc) from exc
    return {"equipment_provider": value}


@router.get("/people/{user_id}")
async def person_equipment(
    user_id: int,
    _: User = Depends(_person_reader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if await db.get(User, user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego konta.")
    return await registry.holder_equipment(db, "user", user_id)


@router.get("/me")
async def my_equipment(
    current_user: User = Depends(_self), db: AsyncSession = Depends(get_db)
) -> dict:
    return await registry.holder_equipment(db, "user", current_user.id)
