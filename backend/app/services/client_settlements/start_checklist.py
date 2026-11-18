"""Karta „Start rozliczeń” dla admina (decyzja Artura 16.11.2026, tryb „Tylko zespół”).

Jedno miejsce z przełącznikami i tym, czego brakuje do startu: moduł rozliczeń, stan panelu
konsultanta, moduł back office, czytnik rozliczenia@, reguły klientów i aktywacje paneli.
Tylko odczyt; przełączniki zapisują ich własne trasy.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.client_settlement import ClientSettlementRuleSet
from app.models.consultant_panel import CpActivation
from app.services.client_settlements import rules_catalog
from app.services.client_settlements import settings as module_settings
from app.services.consultant_portal import mailbox, portal_settings
from app.services.hr import modules as hr_modules

#: Reguły, o których karta przypomina przy każdym kliencie z regułami.
CHARGE_RULE = "order.charge_on_accept"


async def _rule_clients(db: AsyncSession) -> list[dict[str, Any]]:
    latest = (
        select(
            ClientSettlementRuleSet.client_id,
            func.max(ClientSettlementRuleSet.effective_from).label("effective_from"),
        )
        .group_by(ClientSettlementRuleSet.client_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                Client.id,
                Client.name,
                ClientSettlementRuleSet.effective_from,
                ClientSettlementRuleSet.rules,
            )
            .join(latest, latest.c.client_id == Client.id)
            .join(
                ClientSettlementRuleSet,
                (ClientSettlementRuleSet.client_id == latest.c.client_id)
                & (ClientSettlementRuleSet.effective_from == latest.c.effective_from),
            )
            .order_by(Client.name)
        )
    ).all()
    result = []
    for client_id, name, effective_from, stored in rows:
        rules = rules_catalog.effective(stored or {})
        result.append(
            {
                "client_id": client_id,
                "name": name,
                "effective_from": effective_from,
                "md_charged_on_accept": rules[CHARGE_RULE]["level"] != "off",
            }
        )
    return result


async def load(db: AsyncSession) -> dict[str, Any]:
    raw_state = await portal_settings.load_raw_state(db)
    modules = await hr_modules.load_modules(db)
    active_panels = await db.scalar(
        select(func.count())
        .select_from(CpActivation)
        .where(CpActivation.deactivated_at.is_(None))
    )
    return {
        "module_enabled": await module_settings.is_enabled(db),
        "portal_state": raw_state,
        "back_office": bool(modules.get(hr_modules.HrModule.back_office)),
        "mailbox": await mailbox.status(db),
        "rule_clients": await _rule_clients(db),
        "active_panels": int(active_panels or 0),
    }
