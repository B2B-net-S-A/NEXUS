"""Router ``/api/legal/client-fit`` — zgodność umów B2B z umową ramową klienta.

Asystent prawny, część G (``docs/asystent-prawny-plan.md``). Ustalenia niosą
cytaty z umowy ramowej klienta, więc bramka jest ta sama co treść umów
ramowych (``LegalDocsReader``: sekcja Delivery, „Stawki i kwoty: podgląd”
u klienta z zakresu, Delivery Lead — klienci z przypisania). Zlecenie
sprawdzenia jest odczytem z prawem zapisu sekcji (POST), a szkic klauzuli
klienta do nowych umów — zapisem dokumentów prawnych klienta
(``LegalDocsWriter``); szkic dostaje programista albo administrator, wzoru
umowy nic tu nie zmienia. Lista szkiców — wyłącznie administrator.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.client_framework_contracts import LegalDocsReader, LegalDocsWriter
from app.api.delivery_client_scope import DELIVERY_CLIENT_SCOPE_DEPENDENCIES
from app.api.deps import AdminUser
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.client import Client
from app.models.legal_client_fit import LegalClientFitFinding
from app.models.user import User
from app.services import framework_contract_index
from app.services.client_access import resolve_client_access
from app.services.legal_client_fit import service
from app.services.legal_client_fit.sources import SOURCE_AMENDMENT, SOURCE_FRAMEWORK
from app.services.legal_client_fit.topics import TOPIC_BY_KEY

router = APIRouter(
    dependencies=[*DELIVERY_SECTION_DEPENDENCIES, *DELIVERY_CLIENT_SCOPE_DEPENDENCIES]
)

DISCLAIMER = (
    "Sprawdzenie asystenta nie jest poradą prawną. Każdy cytat jest sprawdzony "
    "z tekstem umowy; kara umowna, spór z klientem i rozwiązanie ze skutkiem "
    "natychmiastowym idą do prawnika."
)

SourceKind = Literal["framework_contract", "amendment"]


class ClientFitSource(BaseModel):
    kind: SourceKind
    id: int
    name: str
    readable: bool
    note: Optional[str] = None


class ClientFitFindingSource(BaseModel):
    kind: SourceKind
    id: int
    name: str


class ClientFitClauseDraft(BaseModel):
    requested_at: datetime
    requested_by_name: Optional[str] = None


class ClientFitFindingRead(BaseModel):
    id: int
    topic: str
    topic_label: str
    state: Literal["gap", "decide", "ok"]
    summary: str
    client_quote: str
    client_ref: str
    client_source: ClientFitFindingSource
    our_quote: Optional[str] = None
    our_ref: Optional[str] = None
    next_step: Optional[str] = None
    annex_text: Optional[str] = None
    lawyer_review: list[str]
    affected_contracts: int
    clause_draft: Optional[ClientFitClauseDraft] = None


class ClientFitCounts(BaseModel):
    gap: int = 0
    decide: int = 0
    ok: int = 0


class ClientFitResponse(BaseModel):
    client_id: int
    client_name: str
    status: Literal[
        "never", "queued", "running", "done", "unavailable", "failed", "no_contract"
    ]
    status_message: Optional[str] = None
    checked_at: Optional[datetime] = None
    stale: bool
    sources: list[ClientFitSource]
    template_label: str
    active_b2b_contracts: int
    counts: ClientFitCounts
    findings: list[ClientFitFindingRead]
    can_request_clause_draft: bool
    disclaimer: str


class ClientFitCheckQueued(BaseModel):
    status: Literal["queued", "running"]


class ClientFitClauseDraftResponse(BaseModel):
    clause_draft: ClientFitClauseDraft


class ClauseDraftItem(BaseModel):
    finding_id: int
    client_id: int
    client_name: str
    topic: str
    topic_label: str
    text: str
    client_quote: str
    client_ref: str
    requested_at: datetime
    requested_by_name: Optional[str] = None


_STATE_ORDER = {"gap": 0, "decide": 1, "ok": 2}


async def _client_or_404(db: AsyncSession, client_id: int) -> Client:
    client = await db.get(Client, client_id)
    if client is None or client.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Nie ma takiego klienta.")
    return client


def _client_name(client: Client) -> str:
    return (client.display_name or client.name or "").strip() or f"Klient #{client.id}"


def _clause_draft(
    finding: LegalClientFitFinding, names: dict[int, str]
) -> Optional[ClientFitClauseDraft]:
    if finding.clause_draft_requested_at is None:
        return None
    return ClientFitClauseDraft(
        requested_at=finding.clause_draft_requested_at,
        requested_by_name=names.get(finding.clause_draft_requested_by_id or 0),
    )


@router.get("/client-fit/clients/{client_id}", response_model=ClientFitResponse)
async def get_client_fit(
    client_id: int,
    current_user: User = LegalDocsReader,
    db: AsyncSession = Depends(get_db),
) -> ClientFitResponse:
    """Ostatnie sprawdzenie klienta: ustalenia, źródła i stan biegu w tle."""
    client = await _client_or_404(db, client_id)
    view = await service.load_view(db, client)
    names = service.source_names(view.documents)
    access = await resolve_client_access(db, current_user, client_id)
    findings = sorted(view.findings, key=lambda f: (_STATE_ORDER.get(f.state, 9), f.id))
    counts = ClientFitCounts()
    items: list[ClientFitFindingRead] = []
    for finding in findings:
        setattr(counts, finding.state, getattr(counts, finding.state) + 1)
        kind = (
            SOURCE_AMENDMENT
            if finding.client_source_kind == SOURCE_AMENDMENT
            else SOURCE_FRAMEWORK
        )
        topic = TOPIC_BY_KEY.get(finding.topic)
        items.append(
            ClientFitFindingRead(
                id=finding.id,
                topic=finding.topic,
                topic_label=topic.label if topic else finding.topic,
                state=finding.state,  # type: ignore[arg-type]
                summary=finding.summary,
                client_quote=finding.client_quote,
                client_ref=finding.client_ref,
                client_source=ClientFitFindingSource(
                    kind=kind,
                    id=finding.client_source_id,
                    name=names.get((kind, finding.client_source_id))
                    or "dokument usunięty",
                ),
                our_quote=finding.our_quote,
                our_ref=finding.our_ref,
                next_step=finding.next_step,
                annex_text=finding.annex_text,
                lawyer_review=[str(x) for x in (finding.lawyer_review or [])],
                affected_contracts=view.active_b2b if finding.state != "ok" else 0,
                clause_draft=_clause_draft(finding, view.drafters),
            )
        )
    check = view.check
    return ClientFitResponse(
        client_id=client.id,
        client_name=_client_name(client),
        status=service.status_of(check),  # type: ignore[arg-type]
        status_message=check.status_message if check else None,
        checked_at=check.checked_at if check else None,
        stale=view.stale,
        sources=[
            ClientFitSource(
                kind=kind,
                id=row.id,
                name=row.name,
                readable=framework_contract_index.has_current_text(row),
                note=framework_contract_index.reading_note(row),
            )
            for kind, rows in (
                (SOURCE_FRAMEWORK, view.documents.contracts),
                (SOURCE_AMENDMENT, view.documents.amendments),
            )
            for row in rows
        ],
        template_label=view.template_label,
        active_b2b_contracts=view.active_b2b,
        counts=counts,
        findings=items,
        can_request_clause_draft=access.can_edit_legal_documents,
        disclaimer=DISCLAIMER,
    )


@router.post(
    "/client-fit/clients/{client_id}/check",
    response_model=ClientFitCheckQueued,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_client_fit_check(
    client_id: int,
    current_user: User = LegalDocsReader,
    db: AsyncSession = Depends(get_db),
) -> ClientFitCheckQueued:
    """„Sprawdź ponownie” — bieg w tle; trwające sprawdzenie nie zakłada drugiego."""
    await _client_or_404(db, client_id)
    row = await service.request_check(
        db, client_id, trigger="manual", user_id=current_user.id
    )
    return ClientFitCheckQueued(
        status="running" if row.status == "running" else "queued"
    )


@router.post(
    "/client-fit/clients/{client_id}/findings/{finding_id}/clause-draft",
    response_model=ClientFitClauseDraftResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_clause_draft(
    client_id: int,
    finding_id: int,
    current_user: LegalDocsWriter,
    db: AsyncSession = Depends(get_db),
) -> ClientFitClauseDraftResponse:
    """Szkic klauzuli klienta do nowych umów dla programisty — wzór się nie zmienia."""
    finding = await db.scalar(
        select(LegalClientFitFinding).where(
            LegalClientFitFinding.id == finding_id,
            LegalClientFitFinding.client_id == client_id,
        )
    )
    if finding is None:
        raise HTTPException(
            status_code=404, detail="Nie ma takiego ustalenia u klienta."
        )
    if finding.state == "ok" or not finding.annex_text:
        raise HTTPException(
            status_code=422,
            detail="Szkic klauzuli powstaje tylko z luki z proponowaną treścią.",
        )
    finding = await service.request_clause_draft(db, finding, current_user.id)
    return ClientFitClauseDraftResponse(
        clause_draft=ClientFitClauseDraft(
            requested_at=finding.clause_draft_requested_at,  # type: ignore[arg-type]
            requested_by_name=current_user.name,
        )
    )


@router.get("/client-fit/clause-drafts", response_model=list[ClauseDraftItem])
async def list_clause_drafts(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> list[ClauseDraftItem]:
    """Zgłoszone szkice klauzul klientów — lista dla programisty i administratora."""
    rows = (
        await db.execute(
            select(LegalClientFitFinding, Client, User.name)
            .join(Client, Client.id == LegalClientFitFinding.client_id)
            .outerjoin(
                User, User.id == LegalClientFitFinding.clause_draft_requested_by_id
            )
            .where(LegalClientFitFinding.clause_draft_requested_at.is_not(None))
            .order_by(LegalClientFitFinding.clause_draft_requested_at.desc())
            .limit(200)
        )
    ).all()
    out = []
    for finding, client, requester in rows:
        topic = TOPIC_BY_KEY.get(finding.topic)
        out.append(
            ClauseDraftItem(
                finding_id=finding.id,
                client_id=client.id,
                client_name=_client_name(client),
                topic=finding.topic,
                topic_label=topic.label if topic else finding.topic,
                text=finding.clause_draft_text or finding.annex_text or "",
                client_quote=finding.client_quote,
                client_ref=finding.client_ref,
                requested_at=finding.clause_draft_requested_at,
                requested_by_name=requester,
            )
        )
    return out
