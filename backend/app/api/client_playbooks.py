"""Karta klienta — standardy współpracy per klient, prowadzone przez Delivery Leada.

Dwa wejścia, jedna prawda w bazie (lustro ``client_cv_rules``):

* profil klienta (``/api/clients/{id}/playbook``) — odczyt (każda rola
  operacyjna) i zapis (``DeliverySectionUser`` = zapis w sekcji Delivery),
  historia zmian (odczyt w sekcji Delivery);
* przegląd zbiorczy (``/api/settings/client-playbooks``) — klienci, którzy
  mają kartę; renderowany też w Pomocy → Klienci i na stronie oferty.

Zapis = obowiązuje. Bez bramki zatwierdzenia jak w regułach CV: seed z
migracji 0271 NIGDY nie nadpisuje istniejącego wiersza, więc nie ma
„propozycji", którą trzeba by odróżnić od decyzji człowieka. Zmiana treści
bumpuje ``version`` i zostawia wpis w ``client_playbook_events`` z diffem.

Model dostępu (decyzja 03.09.2026, świadome odstępstwo od reguł CV):

* ODCZYT karty i przeglądu jest org-wide dla każdej roli operacyjnej, BEZ
  grafu klienta. Karta zastępuje 14 wzorów Word w Pomocy, które czytał każdy
  zalogowany; rekruter czyta ją PRZED przypisaniem do rekrutacji — po to jest.
  Treść to procedura, nie kwoty.
* ZAPIS i historia idą jak reguły CV po #1351: sekcja Delivery
  (``DeliverySectionUser``) plus graf klienta (``resolve_client_access``):
  admin org-wide, Delivery Lead wyłącznie klient ze swojego portfela.
* ``off_limits`` pochodzi z umowy ramowej (``client_contract_terms``), więc
  jedzie w odpowiedzi tylko do ról z odczytem sekcji Delivery; reszta dostaje
  ``null`` — karta nie może być bocznym wejściem do warunków umowy.
"""

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import OperationalUser
from app.api.help_materials import _validate_url
from app.api.section_access import DeliverySectionUser
from app.core.database import get_db
from app.models.client import Client
from app.models.client_contract_terms import ClientContractTerms
from app.models.client_playbook import ClientPlaybook
from app.models.client_playbook_event import ClientPlaybookEvent
from app.models.user import User
from app.services.client_access import deny, resolve_client_access
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)

router = APIRouter(tags=["client-playbooks"])

# Pola objęte wersjonowaniem i diffem w historii (kolejność = kolejność w `changes`).
PLAYBOOK_FIELDS: tuple[str, ...] = (
    "sla_business_days",
    "sla_min_candidates",
    "cv_limit_per_process",
    "hold_hours",
    "multi_project_cooldown_days",
    "rate_policy",
    "about_for_candidate",
    "priority_rules",
    "process_rules_md",
    "onboarding_md",
    "documents",
)

_CLIENT_DISPLAY_NAME = func.coalesce(
    func.nullif(func.trim(Client.display_name), ""), Client.name
)


# ── Schematy ────────────────────────────────────────────────────────────────


class PlaybookDocument(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=2000)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Nazwa dokumentu jest wymagana.")
        return stripped

    @field_validator("url")
    @classmethod
    def _http_only(cls, value: str) -> str:
        # ValueError z `_validate_url` → 422 (tylko absolutne http/https).
        return _validate_url(value)


class ClientPlaybookPayload(BaseModel):
    """Pełna podmiana karty. Brak klucza = NULL / pusta lista."""

    sla_business_days: Optional[int] = Field(default=None, ge=0, le=365)
    sla_min_candidates: Optional[int] = Field(default=None, ge=1, le=1000)
    cv_limit_per_process: Optional[int] = Field(default=None, ge=1, le=1000)
    hold_hours: Optional[int] = Field(default=None, ge=1, le=8760)
    multi_project_cooldown_days: Optional[int] = Field(default=None, ge=1, le=3650)
    rate_policy: Optional[str] = Field(default=None, max_length=500)
    about_for_candidate: Optional[str] = Field(default=None, max_length=4000)
    priority_rules: Optional[str] = Field(default=None, max_length=4000)
    process_rules_md: Optional[str] = Field(default=None, max_length=20000)
    onboarding_md: Optional[str] = Field(default=None, max_length=20000)
    documents: list[PlaybookDocument] = Field(default_factory=list, max_length=50)

    @field_validator(
        "rate_policy",
        "about_for_candidate",
        "priority_rules",
        "process_rules_md",
        "onboarding_md",
    )
    @classmethod
    def _blank_to_none(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class OffLimitsRead(BaseModel):
    months: Optional[int] = None
    scope: Optional[str] = None
    notes: Optional[str] = None


class ClientPlaybookRead(BaseModel):
    client_id: int
    client_name: Optional[str] = None
    # `exists=False` + `version=0` = brak wiersza; GET nigdy nie daje 404 na braku karty.
    exists: bool = False
    version: int = 0
    sla_business_days: Optional[int] = None
    sla_min_candidates: Optional[int] = None
    cv_limit_per_process: Optional[int] = None
    hold_hours: Optional[int] = None
    multi_project_cooldown_days: Optional[int] = None
    rate_policy: Optional[str] = None
    about_for_candidate: Optional[str] = None
    priority_rules: Optional[str] = None
    process_rules_md: Optional[str] = None
    onboarding_md: Optional[str] = None
    documents: list[dict[str, str]] = Field(default_factory=list)
    # Tylko do odczytu, z `client_contract_terms`; None = brak warunków umowy
    # ALBO brak odczytu sekcji Delivery (patrz docstring modułu).
    off_limits: Optional[OffLimitsRead] = None
    seed_key: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by_name: Optional[str] = None


class ClientPlaybookListItem(ClientPlaybookRead):
    """Wiersz przeglądu — dziś identyczny z Read; osobna klasa dla stabilnego typu frontu."""


class ClientPlaybooksOverview(BaseModel):
    items: list[ClientPlaybookListItem]


class PlaybookEventRead(BaseModel):
    id: int
    playbook_version: int
    action: str
    changes: dict[str, Any] = Field(default_factory=dict)
    actor_name: Optional[str] = None
    created_at: Optional[str] = None


# ── Helpery ─────────────────────────────────────────────────────────────────


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


async def _client_or_404(db: AsyncSession, client_id: int) -> Client:
    client = await db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Klient nie został znaleziony.")
    return client


def _client_label(client: Client) -> str:
    return (client.display_name or "").strip() or client.name


async def _playbook_for(db: AsyncSession, client_id: int) -> Optional[ClientPlaybook]:
    return (
        await db.execute(
            select(ClientPlaybook).where(ClientPlaybook.client_id == client_id)
        )
    ).scalar_one_or_none()


async def _terms_for(db: AsyncSession, client_id: int) -> Optional[ClientContractTerms]:
    return (
        await db.execute(
            select(ClientContractTerms).where(
                ClientContractTerms.client_id == client_id
            )
        )
    ).scalar_one_or_none()


def _off_limits(terms: Optional[ClientContractTerms]) -> Optional[OffLimitsRead]:
    if terms is None:
        return None
    return OffLimitsRead(
        months=terms.off_limits_months,
        scope=terms.off_limits_scope,
        notes=terms.off_limits_notes,
    )


def _can_read_off_limits(user: User) -> bool:
    """Off-limit z umowy ramowej widzą tylko role z odczytem sekcji Delivery."""
    return section_access_for_user(user, ProductSection.delivery) >= SectionAccess.read


async def _off_limits_for(
    db: AsyncSession, user: User, client_id: int
) -> Optional[OffLimitsRead]:
    if not _can_read_off_limits(user):
        return None
    return _off_limits(await _terms_for(db, client_id))


async def _require_client_playbook_access(
    db: AsyncSession, user: User, client_id: int, *, write: bool
) -> None:
    """Graf klienta pod sufitem sekcji — lustro `_require_client_rule_access`.

    `can_edit_knowledge` = zapis w sekcji Delivery AND (admin-like OR zespół
    klienta); `can_view_knowledge` = admin-like OR czytelnik organizacyjny OR
    zespół klienta OR przypisanie do rekrutacji u tego klienta.
    """
    access = await resolve_client_access(db, user, client_id)
    allowed = access.can_edit_knowledge if write else access.can_view_knowledge
    if not allowed:
        action = "edycja" if write else "odczyt historii"
        raise deny(f"{action} karty klienta jest niedozwolony")


def _state(row: Optional[ClientPlaybook]) -> dict[str, Any]:
    """Migawka pól objętych diffem; `documents` zawsze jako lista (None == [])."""
    state: dict[str, Any] = {}
    for field in PLAYBOOK_FIELDS:
        value = getattr(row, field, None) if row is not None else None
        if field == "documents":
            value = list(value or [])
        state[field] = value
    return state


def _diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        key: {"from": before.get(key), "to": after.get(key)}
        for key in after
        if before.get(key) != after.get(key)
    }


async def _next_version(db: AsyncSession, client_id: int) -> int:
    """Pierwsza wersja NOWEGO wiersza = max z historii klienta + 1 (numeracja nie restartuje)."""
    last = await db.scalar(
        select(func.max(ClientPlaybookEvent.playbook_version)).where(
            ClientPlaybookEvent.client_id == client_id
        )
    )
    return int(last or 0) + 1


def _record_event(
    db: AsyncSession,
    *,
    client_id: int,
    version: int,
    action: str,
    changes: Optional[dict[str, Any]],
    actor: User,
) -> None:
    db.add(
        ClientPlaybookEvent(
            client_id=client_id,
            playbook_version=version,
            action=action,
            changes=changes or None,
            actor_user_id=actor.id,
            actor_name=actor.name,
        )
    )


def _apply_payload(row: ClientPlaybook, payload: ClientPlaybookPayload) -> None:
    row.sla_business_days = payload.sla_business_days
    row.sla_min_candidates = payload.sla_min_candidates
    row.cv_limit_per_process = payload.cv_limit_per_process
    row.hold_hours = payload.hold_hours
    row.multi_project_cooldown_days = payload.multi_project_cooldown_days
    row.rate_policy = payload.rate_policy
    row.about_for_candidate = payload.about_for_candidate
    row.priority_rules = payload.priority_rules
    row.process_rules_md = payload.process_rules_md
    row.onboarding_md = payload.onboarding_md
    row.documents = [
        {"name": doc.name, "url": doc.url} for doc in payload.documents
    ] or None


def _to_read(
    row: Optional[ClientPlaybook],
    *,
    client_id: int,
    client_name: Optional[str],
    off_limits: Optional[OffLimitsRead],
    updated_by_name: Optional[str] = None,
) -> ClientPlaybookRead:
    if row is None:
        return ClientPlaybookRead(
            client_id=client_id, client_name=client_name, off_limits=off_limits
        )
    return ClientPlaybookRead(
        client_id=client_id,
        client_name=client_name,
        exists=True,
        version=int(row.version or 1),
        sla_business_days=row.sla_business_days,
        sla_min_candidates=row.sla_min_candidates,
        cv_limit_per_process=row.cv_limit_per_process,
        hold_hours=row.hold_hours,
        multi_project_cooldown_days=row.multi_project_cooldown_days,
        rate_policy=row.rate_policy,
        about_for_candidate=row.about_for_candidate,
        priority_rules=row.priority_rules,
        process_rules_md=row.process_rules_md,
        onboarding_md=row.onboarding_md,
        documents=list(row.documents or []),
        off_limits=off_limits,
        seed_key=row.seed_key,
        updated_at=_iso(row.updated_at),
        updated_by_name=updated_by_name,
    )


# ── Trasy ───────────────────────────────────────────────────────────────────


@router.get("/clients/{client_id}/playbook", response_model=ClientPlaybookRead)
async def get_client_playbook(
    client_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> ClientPlaybookRead:
    """Karta klienta; 404 wyłącznie gdy nie ma KLIENTA. Brak karty = `exists=false`.

    Odczyt org-wide, bez grafu klienta — patrz docstring modułu.
    """
    client = await _client_or_404(db, client_id)
    row = await _playbook_for(db, client.id)
    updated_by_name = None
    if row is not None and row.updated_by:
        updated_by_name = await db.scalar(
            select(User.name).where(User.id == row.updated_by)
        )
    return _to_read(
        row,
        client_id=client.id,
        client_name=_client_label(client),
        off_limits=await _off_limits_for(db, current_user, client.id),
        updated_by_name=updated_by_name,
    )


@router.put("/clients/{client_id}/playbook", response_model=ClientPlaybookRead)
async def upsert_client_playbook(
    client_id: int,
    payload: ClientPlaybookPayload,
    current_user: DeliverySectionUser,
    db: AsyncSession = Depends(get_db),
) -> ClientPlaybookRead:
    """Zapisz kartę (pełna podmiana). Zmiana treści → bump `version` + wpis w historii.

    Zapis identycznej treści NIE bumpuje wersji i NIE zostawia wpisu — wersja
    ma mówić o treści, nie o kliknięciach. Bez bramki zatwierdzenia: zapis
    obowiązuje od razu.
    """
    client = await _client_or_404(db, client_id)
    await _require_client_playbook_access(db, current_user, client.id, write=True)
    row = await _playbook_for(db, client.id)
    before = _state(row)
    created = row is None
    if row is None:
        row = ClientPlaybook(client_id=client.id)
        db.add(row)

    _apply_payload(row, payload)
    changes = _diff(before, _state(row))

    try:
        if created or changes:
            if created:
                row.version = await _next_version(db, client.id)
            else:
                row.version = int(row.version or 1) + 1
            row.updated_by = current_user.id
            await db.flush()
            _record_event(
                db,
                client_id=client.id,
                version=int(row.version or 1),
                action="saved",
                changes=changes,
                actor=current_user,
            )
        await db.commit()
    except IntegrityError as exc:
        # Dwa PIERWSZE zapisy karty tego samego klienta naraz: oba widzą
        # `row is None`, drugi INSERT pada na `ux_client_playbooks_client`.
        # Bez tej gałęzi wyjątek leci jako 500 bez CORS („Network Error”);
        # 409 mówi, co się stało, a ponowny zapis trafia już w UPDATE.
        await db.rollback()
        if "ux_client_playbooks_client" not in str(exc.orig or exc):
            raise
        raise HTTPException(
            status_code=409,
            detail=(
                "Kartę tego klienta właśnie zapisał ktoś inny. "
                "Odśwież widok i zapisz ponownie."
            ),
        ) from exc
    await db.refresh(row)
    updated_by_name = current_user.name
    if row.updated_by and row.updated_by != current_user.id:
        updated_by_name = await db.scalar(
            select(User.name).where(User.id == row.updated_by)
        )
    return _to_read(
        row,
        client_id=client.id,
        client_name=_client_label(client),
        off_limits=await _off_limits_for(db, current_user, client.id),
        updated_by_name=updated_by_name,
    )


@router.get(
    "/clients/{client_id}/playbook/history", response_model=list[PlaybookEventRead]
)
async def client_playbook_history(
    client_id: int,
    current_user: DeliverySectionUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> list[PlaybookEventRead]:
    await _client_or_404(db, client_id)
    await _require_client_playbook_access(db, current_user, client_id, write=False)
    rows = (
        await db.scalars(
            select(ClientPlaybookEvent)
            .where(ClientPlaybookEvent.client_id == client_id)
            .order_by(
                ClientPlaybookEvent.created_at.desc(), ClientPlaybookEvent.id.desc()
            )
            .limit(limit)
        )
    ).all()
    return [
        PlaybookEventRead(
            id=e.id,
            playbook_version=e.playbook_version,
            action=e.action,
            changes=dict(e.changes or {}),
            actor_name=e.actor_name,
            created_at=_iso(e.created_at),
        )
        for e in rows
    ]


@router.get("/settings/client-playbooks", response_model=ClientPlaybooksOverview)
async def client_playbooks_overview(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> ClientPlaybooksOverview:
    """Wszystkie karty żywych klientów (bez ukrytych i scalonych), po nazwie wyświetlanej.

    CELOWO bez `resolve_client_visible_client_ids` (którym zawęża się przegląd
    reguł CV): to jest źródło zakładki Pomoc → Klienci, czyli procedur per
    klient dla każdej roli operacyjnej — patrz docstring modułu.
    """
    editor = aliased(User)
    rows = (
        await db.execute(
            select(ClientPlaybook, _CLIENT_DISPLAY_NAME, editor.name)
            .join(Client, Client.id == ClientPlaybook.client_id)
            .outerjoin(editor, editor.id == ClientPlaybook.updated_by)
            .where(Client.hidden.is_(False), Client.merged_into_client_id.is_(None))
            .order_by(func.lower(_CLIENT_DISPLAY_NAME), ClientPlaybook.id)
        )
    ).all()

    terms_by_client: dict[int, ClientContractTerms] = {}
    if rows and _can_read_off_limits(current_user):
        terms = (
            await db.scalars(
                select(ClientContractTerms).where(
                    ClientContractTerms.client_id.in_([r[0].client_id for r in rows])
                )
            )
        ).all()
        terms_by_client = {t.client_id: t for t in terms}

    items = [
        ClientPlaybookListItem(
            **_to_read(
                row,
                client_id=row.client_id,
                client_name=client_name,
                off_limits=_off_limits(terms_by_client.get(row.client_id)),
                updated_by_name=editor_name,
            ).model_dump()
        )
        for row, client_name, editor_name in rows
    ]
    return ClientPlaybooksOverview(items=items)
