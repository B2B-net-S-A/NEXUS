"""Materiały na start i propozycja aktywacji panelu konsultanta.

Materiał jest klienta albo wspólny (``client_id`` puste). Propozycja to materiały wspólne
i klienta kontraktu, a osoba aktywująca decyduje, co zostaje. Zmiana listy dotyczy tylko
nowych aktywacji i tej osoby, bo wybór leży przy aktywacji (``cp_activation_materials``).
Materiału się nie kasuje: wycofany znika z panelu, a wiersz i plik zostają.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional
from urllib.parse import urlsplit

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.upload_filename import fit_filename_column
from app.models.client import Client
from app.models.consultant_panel import (
    ClientOnboardingMaterial,
    ClientSettlementRule,
    CpActivation,
    CpActivationMaterial,
)
from app.models.contract import Contract
from app.models.user import User
from app.services.consultant_portal import activation, documents, portal_settings
from app.services.consultant_portal.auth import PortalError
from app.services.consultant_portal.panel import material_row
from app.services.consultant_panel_schema import FILE_NAME_MAX
from app.services.hr import documents_store, welcome_mail

NOT_FOUND = "Nie ma takiego materiału."
CLIENT_NOT_FOUND = "Nie ma takiego klienta."
CONTRACT_NOT_FOUND = "Nie ma takiego kontraktu."
NEEDS_ONE_SOURCE = "Dodaj plik albo link, jedno z dwóch."
BAD_LINK = "Link musi zaczynać się od https://."
FOREIGN_MATERIAL = "Ten materiał należy do innego klienta."


async def _for_client(
    db: AsyncSession, client_id: Optional[int]
) -> list[ClientOnboardingMaterial]:
    rows = await db.scalars(
        select(ClientOnboardingMaterial)
        .where(
            ClientOnboardingMaterial.active.is_(True),
            or_(
                ClientOnboardingMaterial.client_id.is_(None),
                ClientOnboardingMaterial.client_id == client_id,
            ),
        )
        .order_by(
            ClientOnboardingMaterial.client_id.is_not(None),
            ClientOnboardingMaterial.position,
            ClientOnboardingMaterial.id,
        )
    )
    return list(rows)


async def proposal(db: AsyncSession, contract_id: int) -> dict[str, Any]:
    """Wszystko, co pokazuje okno aktywacji jednego kontraktu."""

    contract = await db.get(Contract, contract_id)
    if contract is None:
        raise PortalError(CONTRACT_NOT_FOUND, status=404, code="contract_not_found")
    client = await db.get(Client, contract.client_id) if contract.client_id else None
    state = await activation.state_for(db, contract_id)
    chosen: Optional[set[int]] = None
    row = await db.scalar(
        select(CpActivation).where(CpActivation.contract_id == contract_id)
    )
    if row is not None:
        chosen = set(
            await db.scalars(
                select(CpActivationMaterial.material_id).where(
                    CpActivationMaterial.activation_id == row.id
                )
            )
        )
    draft = await welcome_mail.draft_for(db, contract_id, assume_panel_open=True)
    sent = await welcome_mail.sent_for(db, contract_id)
    return {
        "contract_id": contract_id,
        "client_id": contract.client_id,
        "client": (client.display_name or client.name) if client else None,
        "start_date": contract.start_date.isoformat() if contract.start_date else None,
        "can_activate": contract.status in activation.ACTIVATABLE,
        "suggested_email": await activation.suggested_email(db, contract)
        or state.email,
        "activation": {
            "active": state.active,
            "email": state.email,
            "activated_at": state.activated_at.isoformat()
            if state.activated_at
            else None,
            "activated_by": state.activated_by,
            "deactivated_at": state.deactivated_at.isoformat()
            if state.deactivated_at
            else None,
            "last_login_at": state.last_login_at.isoformat()
            if state.last_login_at
            else None,
            "address_changed": state.address_changed,
        },
        "materials": [
            {
                **material_row(material),
                "selected": chosen is None or material.id in chosen,
            }
            for material in await _for_client(db, contract.client_id)
        ],
        "mail": {
            "enabled": await welcome_mail.is_enabled(db),
            "subject": draft.subject,
            "body": draft.body,
            "issues": [
                {
                    "code": issue.code,
                    "message": issue.message,
                    "blocking": issue.blocking,
                }
                for issue in draft.issues
            ],
            "sent_at": sent.sent_at.isoformat() if sent else None,
        },
        "portal_state": await portal_settings.load_raw_state(db),
    }


async def choose(
    db: AsyncSession, row: CpActivation, contract_id: int, material_ids: Iterable[int]
) -> None:
    contract = await db.get(Contract, contract_id)
    allowed = {
        material.id
        for material in await _for_client(db, contract.client_id if contract else None)
    }
    wanted = set(material_ids)
    if not wanted <= allowed:
        raise PortalError(FOREIGN_MATERIAL, status=422, code="foreign_material")
    await db.execute(
        delete(CpActivationMaterial).where(CpActivationMaterial.activation_id == row.id)
    )
    db.add_all(
        CpActivationMaterial(activation_id=row.id, material_id=material_id)
        for material_id in sorted(wanted)
    )
    await db.flush()


def _clean_link(url: Optional[str]) -> Optional[str]:
    value = (url or "").strip()
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.netloc:
        raise PortalError(BAD_LINK, code="bad_link")
    return value


async def add(
    db: AsyncSession,
    *,
    client_id: Optional[int],
    title: str,
    url: Optional[str],
    content: Optional[bytes],
    file_name: Optional[str],
    actor: User,
) -> dict[str, Any]:
    clean_title = " ".join(title.replace("\x00", "").split())
    link = _clean_link(url)
    if not clean_title or bool(link) == bool(content):
        raise PortalError(NEEDS_ONE_SOURCE, code="needs_one_source")
    if client_id is not None and await db.get(Client, client_id) is None:
        raise PortalError(CLIENT_NOT_FOUND, status=404, code="client_not_found")
    material = ClientOnboardingMaterial(
        client_id=client_id,
        title=clean_title,
        kind="link" if link else "file",
        url=link,
        created_by=actor.id,
    )
    if content:
        try:
            mime, digest = documents_store.check(content)
        except documents_store.FileRejected as exc:
            raise PortalError(str(exc), code="bad_file") from None
        material.file_path = documents._save(
            f"materials/{client_id or 'shared'}", content, mime=mime, digest=digest
        )
        material.file_name = (
            fit_filename_column(file_name, FILE_NAME_MAX) if file_name else None
        )
        material.mime = mime
        material.size_bytes = len(content)
    db.add(material)
    await db.flush()
    return {**material_row(material), "selected": True}


async def retire(db: AsyncSession, material_id: int) -> None:
    material = await db.get(ClientOnboardingMaterial, material_id)
    if material is None:
        raise PortalError(NOT_FOUND, status=404, code="material_not_found")
    material.active = False
    await db.flush()


# ── Szablon rozliczenia ──────────────────────────────────────────────────────


def _rule_row(rule: Optional[ClientSettlementRule], client_id: int) -> dict[str, Any]:
    return {
        "client_id": client_id,
        "mode": rule.mode if rule else None,
        "instructions": rule.instructions if rule else "",
        "updated_at": rule.updated_at.isoformat() if rule else None,
    }


async def settlement_rule(db: AsyncSession, client_id: int) -> dict[str, Any]:
    return _rule_row(await db.get(ClientSettlementRule, client_id), client_id)


async def save_settlement_rule(
    db: AsyncSession, client_id: int, *, mode: str, instructions: str, actor: User
) -> dict[str, Any]:
    if await db.get(Client, client_id) is None:
        raise PortalError(CLIENT_NOT_FOUND, status=404, code="client_not_found")
    rule = await db.get(ClientSettlementRule, client_id)
    if rule is None:
        rule = ClientSettlementRule(client_id=client_id, mode=mode)
        db.add(rule)
    rule.mode = mode
    rule.instructions = instructions.replace("\x00", "").strip()
    rule.updated_by = actor.id
    await db.flush()
    await db.refresh(rule)
    return _rule_row(rule, client_id)
