"""Katalog raportów klienta: definicje per klient, kalendarz, pobranie, historia.

Decyzje Artura 15.11.2026 (``docs/claude/klienci/katalog-raportow-klienta.md``):
wejście w Klientach (tryb „Raporty dla klientów”) i w karcie klienta,
wpis zatwierdza DL klienta (zgodność: admin), raport wysyła DL sam, a NEXUS
zapisuje wysyłkę. Bramki: sekcja Delivery na routerze, odczyt „podgląd
Delivery”, zapis „edycja klientów”, zakres klientów DL-a w handlerze, kwoty
w pliku — „Stawki i kwoty: podgląd” (sprawdzane per generator) w portfelu kwot
klienta (``can_read_client_finance``): zakres Delivery hybrydy DL + TCM to
wszyscy klienci, kwoty — tylko klienci z przypisania (audyt 24.11.2026).
"""

import hashlib
import logging
from datetime import date, datetime, time
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from fastapi import status as http_status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import NOT_READ_ONLY, user_can_view_client_rate
from app.api.client_framework_contracts import LegalDocsReader
from app.api.financial_access import can_read_client_finance
from app.api.permission_access import (
    AmountsViewUser,
    ClientsEditUser,
    DeliveryViewUser,
)
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.http_headers import content_disposition
from app.core.scheduling import DEFAULT_TZ, business_today
from app.models.ai_feature import AIFeatureKey
from app.models.client import Client
from app.models.client_report import ClientReportDefinition, ClientReportRun
from app.models.user import User
from app.services import client_reports_schema as schema
from app.services import storage_service
from app.services.access_scope import (
    DL_CLIENT_OUT_OF_SCOPE_DETAIL,
    assert_delivery_lead_client_visible,
    resolve_delivery_lead_client_ids,
    resolve_delivery_lead_finance_client_ids,
)
from app.services.action_permissions import ProductAction, has_permission
from app.services.client_reports import catalog, schedule, suggest
from app.services.dl_alerts import client_not_deleted_clause
from app.services.client_reports.registry import (
    XLSX_MEDIA_TYPE,
    Generator,
    ReportContext,
    ReportData,
    all_generators,
    build_tabular_workbook,
    clean_params,
    get_generator,
    report_file_name,
)
from app.services.permission_denial import permission_denied

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
UPLOAD_EXTENSIONS = (
    ".pdf",
    ".xlsx",
    ".xls",
    ".csv",
    ".docx",
    ".doc",
    ".zip",
    ".msg",
    ".eml",
)
MonthParam = Query(..., pattern=r"^20\d{2}-(0[1-9]|1[0-2])$")
PeriodParam = Query(..., min_length=4, max_length=schema.PERIOD_KEY_MAX)


# ------------------------------------------------------------------ schematy


class DefinitionIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=schema.NAME_MAX)
    family: Literal["settlement", "management", "compliance", "on_request"]
    generator_key: Optional[str] = Field(None, max_length=schema.GENERATOR_MAX)
    params: dict[str, Any] = Field(default_factory=dict)
    rhythm: Literal[
        "weekly",
        "monthly",
        "quarterly",
        "semiannual",
        "annual",
        "contract_year",
        "event",
        "on_request",
    ]
    due_rule: dict[str, Any] = Field(default_factory=dict)
    recipient: Optional[str] = Field(None, max_length=schema.RECIPIENT_MAX)
    channel: Optional[str] = Field(None, max_length=schema.CHANNEL_MAX)
    file_format: Optional[str] = Field(None, max_length=schema.FORMAT_MAX)
    preparer: Literal["dl", "finance", "board", "iod", "consultant", "client"] = "dl"
    preparer_user_id: Optional[int] = None
    source_kind: Literal["contract", "amendment", "dl", "manual"] = "dl"
    source_contract_id: Optional[int] = None
    source_chunk_id: Optional[int] = None
    source_ref: Optional[str] = Field(None, max_length=schema.SOURCE_REF_MAX)
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    notes: Optional[str] = Field(None, max_length=4000)


# ----------------------------------------------------------------- pomocnicze


async def _client_or_404(db: AsyncSession, client_id: int) -> Client:
    client = await db.get(Client, client_id)
    if client is None:
        raise HTTPException(404, "Nie ma takiego klienta.")
    return client


async def _scope(db: AsyncSession, user: User) -> Optional[frozenset[int]]:
    return await resolve_delivery_lead_client_ids(user, db)


async def _visible_client(
    db: AsyncSession, user: User, client_id: int
) -> Optional[frozenset[int]]:
    await _client_or_404(db, client_id)
    allowed = await _scope(db, user)
    assert_delivery_lead_client_visible(client_id, allowed)
    return allowed


async def _definition(
    db: AsyncSession, user: User, definition_id: int
) -> tuple[ClientReportDefinition, Optional[frozenset[int]]]:
    definition = await db.get(ClientReportDefinition, definition_id)
    if definition is None:
        raise HTTPException(404, "Nie ma takiego raportu w katalogu.")
    allowed = await _scope(db, user)
    assert_delivery_lead_client_visible(definition.client_id, allowed)
    return definition, allowed


def _validate(body: DefinitionIn) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        due_rule = schedule.validate_due_rule(body.due_rule)
    except schedule.ScheduleError as exc:
        raise HTTPException(422, str(exc)) from exc
    if (
        body.rhythm == "contract_year"
        and "anchor" not in due_rule
        and body.valid_from is None
    ):
        raise HTTPException(
            422, "Rok umowy potrzebuje początku (MM-DD) albo daty „obowiązuje od”."
        )
    if body.valid_from and body.valid_to and body.valid_to < body.valid_from:
        raise HTTPException(422, "„Obowiązuje do” jest przed „obowiązuje od”.")
    params: dict[str, Any] = {}
    if body.generator_key:
        generator = get_generator(body.generator_key)
        if generator is None:
            raise HTTPException(422, "Nieznany generator raportu.")
        if body.rhythm not in generator.rhythms:
            raise HTTPException(422, "Ten generator nie liczy raportu w tym rytmie.")
        try:
            params = clean_params(generator, body.params)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    return due_rule, params


async def _check_source(db: AsyncSession, client_id: int, body: DefinitionIn) -> None:
    if body.preparer_user_id is not None:
        person = await db.get(User, body.preparer_user_id)
        if person is None or not person.is_active:
            raise HTTPException(
                422, "Osoba przygotowująca nie istnieje albo jest nieaktywna."
            )
    if body.source_contract_id is None:
        return
    from app.models.client_framework_contract import ClientFrameworkContract

    contract = await db.get(ClientFrameworkContract, body.source_contract_id)
    if contract is None or contract.client_id != client_id:
        raise HTTPException(422, "Umowa źródłowa nie należy do tego klienta.")


async def _amounts_clients(db: AsyncSession, user: User) -> Optional[frozenset[int]]:
    """Granica kwot konta rządzonego portfelem DL (``None`` = bez tej granicy)."""
    return await resolve_delivery_lead_finance_client_ids(user, db)


def _reads_amounts(
    user: User, client_id: int, finance_clients: Optional[frozenset[int]]
) -> bool:
    """Kwoty raportu jednego klienta: uprawnienie i portfel kwot.

    Zakres Delivery (``_scope``) tu nie wystarcza: hybryda DL + TCM widzi
    w Delivery wszystkich klientów, a kwoty tylko u klientów z przypisania.
    """
    return has_permission(user, ProductAction.amounts_view) and can_read_client_finance(
        user, client_id=client_id, delivery_lead_finance_client_ids=finance_clients
    )


async def _assert_reads_amounts(db: AsyncSession, user: User, client_id: int) -> None:
    if not has_permission(user, ProductAction.amounts_view):
        raise permission_denied(ProductAction.amounts_view)
    if not _reads_amounts(user, client_id, await _amounts_clients(db, user)):
        raise HTTPException(403, DL_CLIENT_OUT_OF_SCOPE_DETAIL)


async def _gate_generator(
    db: AsyncSession, user: User, definition: ClientReportDefinition
) -> Any:
    generator = get_generator(definition.generator_key)
    if generator is None:
        raise HTTPException(
            409,
            "Ten raport nie ma generatora — przygotuj plik poza NEXUSEM i wgraj go przy wysyłce.",
        )
    if generator.needs_amounts:
        await _assert_reads_amounts(db, user, definition.client_id)
    if generator.needs_client_rate and not user_can_view_client_rate(user):
        raise HTTPException(
            403, "Raport zawiera stawki do klienta, których Twoja rola nie widzi."
        )
    return generator


def _period(definition: ClientReportDefinition, key: str) -> schedule.Period:
    try:
        return schedule.period_from_key(
            definition.rhythm, key, definition.due_rule, definition.valid_from
        )
    except schedule.ScheduleError as exc:
        raise HTTPException(422, str(exc)) from exc


async def _load(
    db: AsyncSession,
    definition: ClientReportDefinition,
    generator: Any,
    period: schedule.Period,
):
    client = await _client_or_404(db, definition.client_id)
    ctx = ReportContext(
        client_id=client.id,
        client_name=client.name,
        period=period,
        params=definition.params or {},
        today=business_today(),
    )
    return client, await generator.loader(db, ctx)


async def _payloads(
    db: AsyncSession,
    user: User,
    definitions: list[ClientReportDefinition],
    allowed: Optional[frozenset[int]],
) -> list[dict[str, Any]]:
    today = business_today()
    finance_clients = await _amounts_clients(db, user)
    assignments = await catalog.dl_assignments(db, {d.client_id for d in definitions})
    users = await catalog.user_names(
        db, [d.preparer_user_id for d in definitions if d.preparer_user_id]
    )
    sent = await catalog.sent_periods(db, [d.id for d in definitions])
    out = []
    for definition in definitions:
        runs = sent.get(definition.id, {})
        last = max(runs.values(), key=lambda r: r.sent_at) if runs else None
        out.append(
            catalog.definition_payload(
                definition,
                preparer=catalog.preparer_label(definition, assignments, users),
                next_info=catalog.next_due(definition, runs, today),
                last_sent=last,
                confirmable=catalog.can_confirm(
                    user, definition.family, definition.client_id, allowed
                ),
                can_view_amounts=_reads_amounts(
                    user, definition.client_id, finance_clients
                ),
            )
        )
    return out


def _run_payload(run: ClientReportRun, names: dict[int, str]) -> dict[str, Any]:
    return {
        "id": run.id,
        "period_key": run.period_key,
        "status": run.status,
        "file_name": run.file_name,
        "has_file": bool(run.file_path),
        "size_bytes": run.size_bytes,
        "generated_by": names.get(run.generated_by or 0),
        "sent_at": run.sent_at.isoformat() if run.sent_at else None,
        "sent_to": run.sent_to,
        "sent_by": names.get(run.sent_by or 0),
        "note": run.note,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


# --------------------------------------------------------------------- trasy


@router.get("/generators")
async def list_generators(current_user: DeliveryViewUser) -> list[dict[str, Any]]:
    return [
        {
            "key": g.key,
            "label": g.label,
            "description": g.description,
            "rhythms": list(g.rhythms),
            "needs_amounts": g.needs_amounts,
            "needs_client_rate": g.needs_client_rate,
            "params": [
                {
                    "key": p.key,
                    "label": p.label,
                    "kind": p.kind,
                    "default": p.default,
                    "hint": p.hint,
                }
                for p in g.params
            ],
        }
        for g in all_generators()
    ]


@router.get("/clients/{client_id}")
async def client_catalog(
    client_id: int,
    current_user: DeliveryViewUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    allowed = await _visible_client(db, current_user, client_id)
    definitions = list(
        await db.scalars(
            select(ClientReportDefinition)
            .where(
                ClientReportDefinition.client_id == client_id,
                ClientReportDefinition.status.in_(("active", "proposal")),
            )
            .order_by(ClientReportDefinition.family, ClientReportDefinition.name)
        )
    )
    return {
        "client_id": client_id,
        "can_edit": has_permission(current_user, ProductAction.clients_edit),
        "can_confirm": catalog.can_confirm(
            current_user, "management", client_id, allowed
        ),
        "definitions": await _payloads(db, current_user, definitions, allowed),
    }


@router.post(
    "/clients/{client_id}/definitions", status_code=http_status.HTTP_201_CREATED
)
async def create_definition(
    client_id: int,
    body: DefinitionIn,
    current_user: ClientsEditUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    allowed = await _visible_client(db, current_user, client_id)
    due_rule, params = _validate(body)
    await _check_source(db, client_id, body)
    confirmable = catalog.can_confirm(current_user, body.family, client_id, allowed)
    definition = ClientReportDefinition(
        client_id=client_id,
        **body.model_dump(exclude={"due_rule", "params", "name", "generator_key"}),
        name=body.name.strip(),
        generator_key=body.generator_key or None,
        due_rule=due_rule,
        params=params,
        status="active" if confirmable else "proposal",
        created_by=current_user.id,
        confirmed_by=current_user.id if confirmable else None,
        confirmed_at=func.now() if confirmable else None,
    )
    db.add(definition)
    await db.commit()
    await db.refresh(definition)
    return (await _payloads(db, current_user, [definition], allowed))[0]


@router.patch("/definitions/{definition_id}")
async def update_definition(
    definition_id: int,
    body: DefinitionIn,
    current_user: ClientsEditUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    definition, allowed = await _definition(db, current_user, definition_id)
    if definition.status == "active" and not (
        catalog.can_confirm(
            current_user, definition.family, definition.client_id, allowed
        )
        and catalog.can_confirm(
            current_user, body.family, definition.client_id, allowed
        )
    ):
        raise HTTPException(
            403,
            "Obowiązujący raport zmienia Delivery Lead klienta albo administrator (zgodność: administrator).",
        )
    if definition.status in ("rejected", "archived"):
        raise HTTPException(409, "Ten raport jest odrzucony albo zarchiwizowany.")
    due_rule, params = _validate(body)
    await _check_source(db, definition.client_id, body)
    for key, value in body.model_dump(
        exclude={"due_rule", "params", "name", "generator_key"}
    ).items():
        setattr(definition, key, value)
    definition.name = body.name.strip()
    definition.generator_key = body.generator_key or None
    definition.due_rule = due_rule
    generator = get_generator(definition.generator_key)
    if (
        generator
        and generator.needs_amounts
        and not _reads_amounts(
            current_user,
            definition.client_id,
            await _amounts_clients(db, current_user),
        )
    ):
        # Formularz bez podglądu kwot nie widział progów — nie kasujemy ich.
        hidden = {
            k: v
            for k, v in (definition.params or {}).items()
            if k not in catalog.AMOUNT_FREE_PARAMS
        }
        params = {**hidden, **params}
    definition.params = params
    await db.commit()
    await db.refresh(definition)
    return (await _payloads(db, current_user, [definition], allowed))[0]


async def _set_status(
    db: AsyncSession, user: User, definition_id: int, target: str
) -> dict[str, Any]:
    definition, allowed = await _definition(db, user, definition_id)
    if not catalog.can_confirm(user, definition.family, definition.client_id, allowed):
        detail = (
            "Raporty zgodności zatwierdza administrator."
            if definition.family == "compliance"
            else "Raport zatwierdza Delivery Lead klienta albo administrator."
        )
        raise HTTPException(403, detail)
    if target == "active" and definition.status != "proposal":
        raise HTTPException(409, "Potwierdzić można tylko propozycję.")
    if target == "rejected" and definition.status != "proposal":
        raise HTTPException(
            409, "Odrzucić można tylko propozycję; obowiązujący raport archiwizuj."
        )
    definition.status = target
    if target == "active":
        definition.confirmed_by = user.id
        definition.confirmed_at = func.now()
    await db.commit()
    await db.refresh(definition)
    return (await _payloads(db, user, [definition], allowed))[0]


@router.post("/definitions/{definition_id}/confirm")
async def confirm_definition(
    definition_id: int,
    current_user: ClientsEditUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _set_status(db, current_user, definition_id, "active")


@router.post("/definitions/{definition_id}/reject")
async def reject_definition(
    definition_id: int,
    current_user: ClientsEditUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _set_status(db, current_user, definition_id, "rejected")


@router.post("/definitions/{definition_id}/archive")
async def archive_definition(
    definition_id: int,
    current_user: ClientsEditUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _set_status(db, current_user, definition_id, "archived")


@router.post("/clients/{client_id}/suggest", dependencies=[LegalDocsReader])
async def suggest_from_contracts(
    client_id: int,
    current_user: ClientsEditUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Propozycje z umów; bez modelu same fragmenty ze słowami kluczowymi."""
    allowed = await _visible_client(db, current_user, client_id)
    fragments = await suggest.keyword_fragments(db, client_id)
    if not fragments:
        return {
            "created": [],
            "fragments": [],
            "model_used": False,
            "message": "W umowach klienta nie ma fragmentów o raportach.",
        }
    proposals: list[dict[str, Any]] = []
    model_used = False
    from app.services.ai_models import model_chain_for
    from app.services.ai_quota import ai_feature
    from app.services.llm_providers import api_key_configured
    from starlette.concurrency import run_in_threadpool

    chain = model_chain_for(AIFeatureKey.client_report_requirements)
    if chain and api_key_configured(chain[0]):
        prompt = suggest.build_prompt(fragments)
        try:
            async with ai_feature(
                db, AIFeatureKey.client_report_requirements, user_id=current_user.id
            ):
                await db.commit()  # połączenie wraca do puli na czas modelu
                raw = await run_in_threadpool(suggest.call_model, chain, prompt)
            proposals = suggest.parse_proposals(raw, {f.chunk_id for f in fragments})
            model_used = True
        except Exception as exc:  # noqa: BLE001 — AI to dodatek, nigdy bramka
            logger.warning(
                "client_reports.suggest: model failed client=%s (%s)",
                client_id,
                type(exc).__name__,
            )
            await db.rollback()
    names, chunks = await suggest.existing_names(db, client_id)
    by_chunk = {f.chunk_id: f for f in fragments}
    created: list[ClientReportDefinition] = []
    for item in proposals:
        if suggest.is_known(item["name"], names):
            continue
        fragment = by_chunk[item["source_chunk_id"]]
        definition = ClientReportDefinition(
            client_id=client_id,
            **item,
            params={},
            source_kind="amendment" if fragment.amendment_id else "contract",
            source_contract_id=fragment.contract_id,
            status="proposal",
            created_by=current_user.id,
        )
        db.add(definition)
        created.append(definition)
        names.add(suggest.normalize_name(item["name"]))
    if created:
        await db.commit()
        for definition in created:
            await db.refresh(definition)
    used = {d.source_chunk_id for d in created} | chunks
    return {
        "created": await _payloads(db, current_user, created, allowed),
        "fragments": [
            {
                "chunk_id": f.chunk_id,
                "contract_id": f.contract_id,
                "document": f.document,
                "snippet": suggest.snippet(f),
            }
            for f in fragments
            if f.chunk_id not in used
        ][:15],
        "model_used": model_used,
        "message": None,
    }


@router.get("/definitions/{definition_id}/periods")
async def definition_periods(
    definition_id: int,
    current_user: DeliveryViewUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    definition, _ = await _definition(db, current_user, definition_id)
    today = business_today()
    try:
        periods = schedule.recent_periods(
            definition.rhythm, today, 8, definition.due_rule, definition.valid_from
        )
    except schedule.ScheduleError as exc:
        raise HTTPException(422, str(exc)) from exc
    sent = (await catalog.sent_periods(db, [definition.id])).get(definition.id, {})
    out = []
    for period in periods:
        due = schedule.due_date(definition.due_rule, period)
        out.append(
            {
                "key": period.key,
                "label": period.label,
                "start": period.start.isoformat(),
                "end": period.end.isoformat(),
                "due": due.isoformat() if due else None,
                "state": schedule.report_state(due, period.key in sent, today),
                "closed": period.end < today,
            }
        )
    return out


@router.get("/definitions/{definition_id}/preview")
async def preview_report(
    definition_id: int,
    current_user: DeliveryViewUser,
    period: str = PeriodParam,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    definition, _ = await _definition(db, current_user, definition_id)
    generator = await _gate_generator(db, current_user, definition)
    span = _period(definition, period)
    _, data = await _load(db, definition, generator, span)
    return {
        "period_key": span.key,
        "period_label": span.label,
        "lines": [
            {"label": line.label, "value": line.value, "strong": line.strong}
            for line in data.lines
        ],
        "checks": list(data.checks),
        "sheets": [{"name": s.name, "rows": len(s.rows)} for s in data.sheets],
        "table": _preview_table(generator, data),
    }


PREVIEW_ROWS = 8


def _preview_table(generator: Generator, data: ReportData) -> Optional[dict[str, Any]]:
    """Pierwsze wiersze arkusza wskazanego przez generator (``preview_sheet``)."""
    sheet = next((s for s in data.sheets if s.name == generator.preview_sheet), None)
    if sheet is None:
        return None
    return {
        "headers": list(sheet.headers),
        "rows": [list(row) for row in sheet.rows[:PREVIEW_ROWS]],
        "more": max(len(sheet.rows) - PREVIEW_ROWS, 0),
    }


@router.get("/definitions/{definition_id}/export", dependencies=NOT_READ_ONLY)
async def export_report(
    definition_id: int,
    current_user: DeliveryViewUser,
    period: str = PeriodParam,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Plik raportu; kopia trafia do historii jako „wygenerowany”."""
    definition, _ = await _definition(db, current_user, definition_id)
    generator = await _gate_generator(db, current_user, definition)
    span = _period(definition, period)
    client, data = await _load(db, definition, generator, span)
    if data.file_bytes is not None:
        content, file_name = (
            data.file_bytes,
            data.file_name or report_file_name(client.name, definition.name, span),
        )
    else:
        title = f"{client.name} — {definition.name} — {span.label}"
        content, file_name = (
            build_tabular_workbook(data.sheets, title),
            report_file_name(client.name, definition.name, span),
        )
    path, size = storage_service.save_client_report_file(client.id, file_name, content)
    db.add(
        ClientReportRun(
            definition_id=definition.id,
            client_id=client.id,
            period_key=span.key,
            period_start=span.start,
            period_end=span.end,
            status="generated",
            file_name=file_name,
            file_path=path,
            content_type=XLSX_MEDIA_TYPE,
            size_bytes=size,
            sha256=hashlib.sha256(content).hexdigest(),
            generated_by=current_user.id,
        )
    )
    await db.commit()
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": content_disposition(file_name),
            "Cache-Control": "no-store",
        },
    )


@router.get("/definitions/{definition_id}/runs")
async def list_runs(
    definition_id: int,
    current_user: DeliveryViewUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    definition, _ = await _definition(db, current_user, definition_id)
    runs = list(
        await db.scalars(
            select(ClientReportRun)
            .where(ClientReportRun.definition_id == definition.id)
            .order_by(ClientReportRun.created_at.desc())
            .limit(50)
        )
    )
    names = await catalog.user_names(
        db, [r.generated_by for r in runs] + [r.sent_by for r in runs]
    )
    return [_run_payload(run, names) for run in runs]


@router.post(
    "/definitions/{definition_id}/runs", status_code=http_status.HTTP_201_CREATED
)
async def mark_sent(
    definition_id: int,
    current_user: ClientsEditUser,
    period_key: str = Form(..., min_length=4, max_length=schema.PERIOD_KEY_MAX),
    sent_on: date = Form(...),
    sent_to: Optional[str] = Form(None, max_length=schema.SENT_TO_MAX),
    note: Optional[str] = Form(None, max_length=2000),
    run_id: Optional[int] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """„Oznacz jako wysłany”: DL wysłał ze swojej poczty, NEXUS zapisuje ślad."""
    definition, _ = await _definition(db, current_user, definition_id)
    if definition.status != "active":
        raise HTTPException(409, "Wysyłkę zapisuje się przy obowiązującym raporcie.")
    if sent_on > business_today():
        raise HTTPException(422, "Data wysłania jest w przyszłości.")
    if definition.rhythm in schedule.CALENDAR_RHYTHMS:
        span = _period(definition, period_key)
        start, end = span.start, span.end
    else:
        start = end = sent_on
    sent_at = datetime.combine(sent_on, time(12), tzinfo=ZoneInfo(DEFAULT_TZ))
    run: Optional[ClientReportRun] = None
    if run_id is not None:
        run = await db.get(ClientReportRun, run_id)
        if (
            run is None
            or run.definition_id != definition.id
            or run.period_key != period_key
        ):
            raise HTTPException(
                422, "Wygenerowany plik nie pasuje do raportu i okresu."
            )
        if run.status == "sent":
            raise HTTPException(409, "Ten plik jest już oznaczony jako wysłany.")
    if file is not None and file.filename:
        name = file.filename
        if not name.lower().endswith(UPLOAD_EXTENSIONS):
            raise HTTPException(
                422, "Dozwolone pliki: PDF, Excel, CSV, Word, ZIP, wiadomość e-mail."
            )
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                413, f"Plik większy niż {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
            )
        if not content:
            raise HTTPException(422, "Plik jest pusty.")
        path, size = storage_service.save_client_report_file(
            definition.client_id, name, content
        )
        run = ClientReportRun(
            definition_id=definition.id,
            client_id=definition.client_id,
            period_key=period_key,
            period_start=start,
            period_end=end,
            status="sent",
            file_name=name[: schema.FILE_NAME_MAX],
            file_path=path,
            content_type=(file.content_type or "application/octet-stream")[:128],
            size_bytes=size,
            sha256=hashlib.sha256(content).hexdigest(),
            generated_by=current_user.id,
        )
        db.add(run)
    elif run is None:
        run = ClientReportRun(
            definition_id=definition.id,
            client_id=definition.client_id,
            period_key=period_key,
            period_start=start,
            period_end=end,
            status="sent",
        )
        db.add(run)
    run.status = "sent"
    run.sent_at = sent_at
    run.sent_to = (sent_to or "").strip() or None
    run.sent_by = current_user.id
    run.note = (note or "").strip() or None
    await db.commit()
    await db.refresh(run)
    names = await catalog.user_names(db, [run.generated_by, run.sent_by])
    return _run_payload(run, names)


@router.get("/runs/{run_id}/file", dependencies=NOT_READ_ONLY)
async def run_file(
    run_id: int, current_user: AmountsViewUser, db: AsyncSession = Depends(get_db)
) -> Response:
    """Plik z historii — tylko z podglądem kwot.

    W historii leżą pliki wgrane ręcznie (protokoły, sprawozdania) i pliki
    wygenerowane pod generatorem, który potem mógł się zmienić, więc bramka
    nie może zależeć od obecnego generatora definicji.
    """
    run = await db.get(ClientReportRun, run_id)
    if run is None or not run.file_path:
        raise HTTPException(404, "Ten wpis historii nie ma pliku.")
    definition, _ = await _definition(db, current_user, run.definition_id)
    # Każdy plik historii traktujemy jak plik z kwotami (docstring wyżej), więc
    # i portfel kwot sprawdzamy bez względu na generator.
    await _assert_reads_amounts(db, current_user, definition.client_id)
    generator = get_generator(definition.generator_key)
    if (
        generator
        and generator.needs_client_rate
        and not user_can_view_client_rate(current_user)
    ):
        raise HTTPException(
            403, "Plik zawiera stawki do klienta, których Twoja rola nie widzi."
        )
    try:
        content = storage_service.read_client_report_file(run.file_path)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Pliku nie ma w magazynie.") from exc
    return Response(
        content=content,
        media_type=run.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": content_disposition(run.file_name or "raport"),
            "Cache-Control": "no-store",
        },
    )


@router.get("/calendar")
async def calendar(
    current_user: DeliveryViewUser,
    month: str = MonthParam,
    mine: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Co i komu w miesiącu: terminy z definicji × okresów, stan z historii."""
    year, mon = (int(part) for part in month.split("-"))
    month_start = date(year, mon, 1)
    month_end = schedule.period_containing("monthly", month_start).end
    today = business_today()
    allowed = await _scope(db, current_user)
    query = select(ClientReportDefinition).where(
        ClientReportDefinition.status == "active",
        # Klient w archiwum nie świeci w kalendarzu (jak w dzwonkach).
        client_not_deleted_clause(ClientReportDefinition.client_id),
    )
    if allowed is not None:
        query = query.where(ClientReportDefinition.client_id.in_(list(allowed)))
    definitions = list(await db.scalars(query))
    assignments = await catalog.dl_assignments(db, {d.client_id for d in definitions})
    if mine:
        definitions = [
            d for d in definitions if catalog.preparer_is(current_user, d, assignments)
        ]
    users = await catalog.user_names(
        db, [d.preparer_user_id for d in definitions if d.preparer_user_id]
    )
    clients = await catalog.client_names(db, {d.client_id for d in definitions})
    sent = await catalog.sent_periods(db, [d.id for d in definitions])

    def item(entry: catalog.CalendarEntry) -> dict[str, Any]:
        d = entry.definition
        return {
            "due": entry.due.isoformat() if entry.due else None,
            "carried": entry.carried,
            "definition_id": d.id,
            "client_id": d.client_id,
            "client_name": clients.get(d.client_id, ""),
            "report": d.name,
            "family": d.family,
            "period_key": entry.period.key,
            "period_label": entry.period.label,
            "preparer_label": catalog.preparer_label(d, assignments, users),
            "preparer_is_me": catalog.preparer_is(current_user, d, assignments),
            "state": entry.state,
            "has_generator": get_generator(d.generator_key) is not None,
        }

    in_month: list[dict[str, Any]] = []
    later: list[dict[str, Any]] = []
    for definition in definitions:
        month_items, later_items = catalog.calendar_entries(
            definition, month_start, month_end, today, sent.get(definition.id, {})
        )
        in_month.extend(item(e) for e in month_items)
        later.extend(item(e) for e in later_items)
    in_month.sort(key=lambda i: (i["due"] or "9999", i["client_name"], i["report"]))
    later.sort(key=lambda i: (i["due"] or "9999", i["client_name"]))
    counts: dict[str, int] = {}
    for entry in in_month:
        counts[entry["state"]] = counts.get(entry["state"], 0) + 1
    return {
        "month": month,
        "today": today.isoformat(),
        "items": in_month,
        "upcoming": later,
        "counts": counts,
    }
