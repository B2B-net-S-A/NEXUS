"""Karta klienta — standardy współpracy per klient, prowadzone przez Delivery Leada.

Dwa wejścia, jedna prawda w bazie (lustro ``client_cv_rules``):

* profil klienta (``/api/clients/{id}/playbook``) — odczyt (każda rola
  operacyjna) i zapis (``DeliverySectionUser`` = zapis w sekcji Delivery),
  historia zmian (odczyt w sekcji Delivery);
* przegląd zbiorczy (``/api/settings/client-playbooks``) — klienci, którzy
  mają kartę; renderowany też w Pomocy → Klienci i na stronie oferty.

Zapis = obowiązuje. Bez bramki zatwierdzenia jak w regułach CV: seed z
migracji 0272 NIGDY nie nadpisuje istniejącego wiersza, więc nie ma
„propozycji", którą trzeba by odróżnić od decyzji człowieka. Zmiana treści
bumpuje ``version`` i zostawia wpis w ``client_playbook_events`` z diffem.

Model dostępu (decyzja 03.09.2026, świadome odstępstwo od reguł CV):

* ODCZYT karty i przeglądu jest org-wide dla każdej roli operacyjnej, BEZ
  grafu klienta. Karta zastępuje 14 wzorów Word w Pomocy, które czytał każdy
  zalogowany; rekruter czyta ją PRZED przypisaniem do rekrutacji — po to jest.
  Treść to procedura, nie kwoty.
* ZAPIS i historia idą jak reguły CV po #1351: sekcja Delivery
  (``DeliverySectionUser``) plus graf klienta (``resolve_client_access``).
  Zapis wymaga uprawnienia „Klienci: dodawanie i edycja” — domyślnie admin
  i Delivery Lead, obaj org-wide (``purpose="org"``).
* Off-limits (``client_contract_terms.off_limits_*``) NIE jedzie w karcie —
  funkcja usunięta 27.09.2026 decyzją Artura (runda 9, R9-N4-8); kolumny
  w bazie zostają.
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
from app.api.permission_access import require_permission
from app.api.section_access import DeliverySectionUser
from app.core.database import get_db
from app.models.client import Client
from app.models.client_playbook import ClientPlaybook
from app.models.client_playbook_event import ClientPlaybookEvent
from app.models.user import User
from app.services.action_permissions import ProductAction
from app.services.client_access import (
    assert_client_writable,
    deny,
    resolve_client_access,
)
from app.services.client_playbook_seed import seed_entry

router = APIRouter(tags=["client-playbooks"])

# Zapis karty wymaga uprawnienia „Klienci: dodawanie i edycja”. Deklaruje je
# TRASA (dekorator), nie parametr handlera: odmowa nazywa brakującą pozycję,
# zanim sięgniemy do bazy — także wtedy, gdy zatrzymuje bramka sekcji.
# U kogo wolno, rozstrzyga dalej ``_require_client_playbook_access``.
CLIENTS_EDIT_DEPENDENCIES = [Depends(require_permission(ProductAction.clients_edit))]

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


class PlaybookSeedRequest(BaseModel):
    """Backfill: który wzór z seed.json przypisać wskazanemu klientowi."""

    seed_key: str = Field(min_length=1, max_length=64)


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
    # 0403: `web` = opis z researchu w internecie („Champion po ludzku”),
    # `manual`/NULL = wpisany przez człowieka.
    about_for_candidate_origin: Optional[str] = None
    about_for_candidate_sources: list[dict[str, str]] = Field(default_factory=list)
    priority_rules: Optional[str] = None
    process_rules_md: Optional[str] = None
    onboarding_md: Optional[str] = None
    documents: list[dict[str, str]] = Field(default_factory=list)
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


async def _require_client_playbook_access(
    db: AsyncSession, user: User, client_id: int, *, write: bool
) -> None:
    """Graf klienta pod sufitem sekcji — lustro `_require_client_rule_access`.

    `can_edit_knowledge` = uprawnienie „Klienci: dodawanie i edycja” u klienta
    z zakresu (`purpose="org"`: Delivery Lead prowadzi kartę KAŻDEGO klienta);
    `can_view_knowledge` = admin-like OR czytelnik organizacyjny OR zespół
    klienta OR przypisanie do rekrutacji u tego klienta. Odmowa zapisu nazywa
    brakujące uprawnienie.
    """
    access = await resolve_client_access(db, user, client_id, purpose="org")
    allowed = access.can_edit_knowledge if write else access.can_view_knowledge
    if not allowed:
        if write:
            raise access.edit_denial("edycja karty klienta jest niedozwolona")
        raise deny("odczyt historii karty klienta jest niedozwolony")


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


def _payload_from_seed(entry: dict[str, Any]) -> ClientPlaybookPayload:
    """Payload karty z wpisu seed.json — te same walidacje co PUT (granice, URL-e).

    `entry` niesie dokładnie pola `PLAYBOOK_FIELDS` (+ `seed_key`, `name_pattern`,
    które tu nie wchodzą). Klucze `None` pomijamy, żeby wpaść w domyślne pola
    payloadu (None / pusta lista), a nie karmić walidatora `None`-em tam, gdzie
    typ to lista.
    """
    data = {
        field: entry[field] for field in PLAYBOOK_FIELDS if entry.get(field) is not None
    }
    return ClientPlaybookPayload(**data)


def _to_read(
    row: Optional[ClientPlaybook],
    *,
    client_id: int,
    client_name: Optional[str],
    updated_by_name: Optional[str] = None,
) -> ClientPlaybookRead:
    if row is None:
        return ClientPlaybookRead(client_id=client_id, client_name=client_name)
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
        about_for_candidate_origin=(row.about_for_candidate_origin or "manual")
        if row.about_for_candidate
        else None,
        about_for_candidate_sources=[
            {"url": str(s.get("url")), "title": str(s.get("title") or s.get("url"))}
            for s in (row.about_for_candidate_sources or [])
            if isinstance(s, dict) and s.get("url")
        ][:8],
        priority_rules=row.priority_rules,
        process_rules_md=row.process_rules_md,
        onboarding_md=row.onboarding_md,
        documents=list(row.documents or []),
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
        updated_by_name=updated_by_name,
    )


@router.put(
    "/clients/{client_id}/playbook",
    response_model=ClientPlaybookRead,
    dependencies=CLIENTS_EDIT_DEPENDENCIES,
)
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
    # Zapis tylko na widocznym kliencie (S1) i pod blokadą jego wiersza (S4):
    # dwa równoległe zapisy liczyły diff i wersję od tego samego stanu, więc
    # dwie różne treści dostawały ten sam numer wersji.
    client = await assert_client_writable(db, client_id, lock=True)
    await _require_client_playbook_access(db, current_user, client.id, write=True)
    row = await _playbook_for(db, client.id)
    before = _state(row)
    created = row is None
    if row is None:
        row = ClientPlaybook(client_id=client.id)
        db.add(row)

    _apply_payload(row, payload)
    changes = _diff(before, _state(row))
    if "about_for_candidate" in changes:
        # Opis poprawiony przez człowieka przestaje być „z internetu” — research
        # („Champion po ludzku”) już go nie nadpisze.
        row.about_for_candidate_origin = "manual"
        row.about_for_candidate_sources = None

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
        updated_by_name=updated_by_name,
    )


@router.post(
    "/clients/{client_id}/playbook/seed",
    response_model=ClientPlaybookRead,
    dependencies=CLIENTS_EDIT_DEPENDENCIES,
)
async def seed_client_playbook(
    client_id: int,
    body: PlaybookSeedRequest,
    current_user: DeliverySectionUser,
    db: AsyncSession = Depends(get_db),
) -> ClientPlaybookRead:
    """Backfill: załóż kartę klienta z gotowej treści seeda (rodziny nazw).

    Automatyczny seed 0272 wstawia kartę TYLKO przy dokładnie jednym żywym
    kliencie pasującym do wzorca nazwy, więc rodziny (BNP/PKO/Bank Pocztowy) i
    klienci przemianowani przez Traffita zostają bez karty. Ten endpoint
    przypisuje istniejącą treść seeda wskazanemu `client_id`. NIE nadpisuje
    istniejącej karty (409) — decyzja człowieka wygrywa z seedem, jak w
    automatycznym `ON CONFLICT DO NOTHING`.
    """
    client = await assert_client_writable(db, client_id, lock=True)
    await _require_client_playbook_access(db, current_user, client.id, write=True)
    entry = seed_entry(body.seed_key)
    if entry is None:
        raise HTTPException(
            status_code=400, detail=f"Nieznany szablon karty: {body.seed_key}."
        )
    if await _playbook_for(db, client.id) is not None:
        raise HTTPException(
            status_code=409,
            detail="Ten klient ma już kartę — backfill nie nadpisuje istniejącej.",
        )

    payload = _payload_from_seed(entry)
    before = _state(None)
    row = ClientPlaybook(client_id=client.id, seed_key=body.seed_key)
    db.add(row)
    _apply_payload(row, payload)
    row.version = await _next_version(db, client.id)
    row.updated_by = current_user.id
    changes = _diff(before, _state(row))
    try:
        await db.flush()
        _record_event(
            db,
            client_id=client.id,
            version=int(row.version or 1),
            action="seeded",
            changes=changes,
            actor=current_user,
        )
        await db.commit()
    except IntegrityError as exc:
        # Wyścig z równoległym backfillem/zapisem tego samego klienta → 409
        # zamiast 500 bez CORS („Network Error”); patrz `upsert_client_playbook`.
        await db.rollback()
        if "ux_client_playbooks_client" not in str(exc.orig or exc):
            raise
        raise HTTPException(
            status_code=409,
            detail="Kartę tego klienta właśnie założył ktoś inny. Odśwież widok.",
        ) from exc
    await db.refresh(row)
    return _to_read(
        row,
        client_id=client.id,
        client_name=_client_label(client),
        updated_by_name=current_user.name,
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
            .where(
                Client.hidden.is_(False),
                Client.merged_into_client_id.is_(None),
                # Klient usunięty z profilu (0307) ma kartę, więc zawsze idzie
                # ścieżką „z historią" — bez tego wisiałby w Pomocy z linkiem
                # do profilu, który zwraca 404.
                Client.deleted_at.is_(None),
            )
            .order_by(func.lower(_CLIENT_DISPLAY_NAME), ClientPlaybook.id)
        )
    ).all()

    items = [
        ClientPlaybookListItem(
            **_to_read(
                row,
                client_id=row.client_id,
                client_name=client_name,
                updated_by_name=editor_name,
            ).model_dump()
        )
        for row, client_name, editor_name in rows
    ]
    return ClientPlaybooksOverview(items=items)
