"""Klient o tej samej nazwie przy dodawaniu nowego (22.10.2026).

Dodanie klienta nie sprawdzało, czy firma już jest. 12.10.2026 powstał drugi
rekord „Energa” w zakładce Aktywni, a stary — z rekrutacjami i regułami CV —
został w Nieaktywnych; lista pokazywała Energę w obu zakładkach. Okno
„Dodaj firmę” dostaje teraz ostrzeżenie (nie blokadę): ta sama nazwa może
być inną firmą, decyduje człowiek.

Nazwy porównuje ``normalize_company_name`` (reguła „ta sama firma” wspólna
z ATLAS-em: bez wielkości liter, znaków diakrytycznych i formy prawnej),
więc „Energa” trafia na „Energa S.A.”. Porównujemy nazwę źródłową,
wyświetlaną, prawną i aliasy widocznych klientów — scalony, ukryty albo
usunięty rekord nie jest „już w bazie” dla osoby, która go nie widzi.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.client_directory import ClientAlias, ClientPortfolioScope
from app.services.client_identity import (
    client_display_name_expression,
    visible_client_predicates,
)
from app.services.company_names import normalize_company_name

_CATEGORY_LABELS = {
    "active": "Aktywni",
    "relationship": "Relacyjni",
    "inactive": "Nieaktywni",
}


@dataclass(frozen=True)
class SameNameClient:
    id: int
    name: str
    categories: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {"id": self.id, "name": self.name, "categories": list(self.categories)}


async def find_same_name_clients(
    db: AsyncSession, name: str
) -> tuple[SameNameClient, ...]:
    """Widoczni klienci, których któraś nazwa to ta sama firma co ``name``."""

    key = normalize_company_name(name)
    if not key:
        return ()

    rows = (
        await db.execute(
            select(
                Client.id,
                client_display_name_expression().label("display"),
                Client.name,
                Client.legal_name,
            ).where(*visible_client_predicates())
        )
    ).all()
    matched: dict[int, str] = {
        row.id: row.display
        for row in rows
        if key
        in {
            normalize_company_name(value or "")
            for value in (row.display, row.name, row.legal_name)
        }
    }
    display_by_id = {row.id: row.display for row in rows}
    aliases = (
        await db.execute(
            select(ClientAlias.client_id, ClientAlias.alias).where(
                ClientAlias.archived_at.is_(None),
                ClientAlias.client_id.in_(sorted(display_by_id) or [-1]),
            )
        )
    ).all()
    for alias in aliases:
        if normalize_company_name(alias.alias) == key:
            matched.setdefault(alias.client_id, display_by_id[alias.client_id])
    if not matched:
        return ()

    effective_category = func.coalesce(
        ClientPortfolioScope.category_override, ClientPortfolioScope.category
    )
    categories: dict[int, set[str]] = {}
    for client_id, category in (
        await db.execute(
            select(ClientPortfolioScope.client_id, effective_category).where(
                ClientPortfolioScope.client_id.in_(sorted(matched)),
                ClientPortfolioScope.archived_at.is_(None),
            )
        )
    ).all():
        value = getattr(category, "value", category)
        categories.setdefault(client_id, set()).add(str(value))

    return tuple(
        SameNameClient(
            id=client_id,
            name=matched[client_id],
            categories=tuple(
                c for c in _CATEGORY_LABELS if c in categories.get(client_id, ())
            ),
        )
        for client_id in sorted(matched)
    )


def duplicate_warning_detail(found: tuple[SameNameClient, ...]) -> dict[str, object]:
    """Treść 409 ``client_duplicate_warning`` dla okna „Dodaj firmę”."""

    described = ", ".join(
        f"{item.name} ({', '.join(_CATEGORY_LABELS[c] for c in item.categories)})"
        if item.categories
        else item.name
        for item in found
    )
    return {
        "code": "client_duplicate_warning",
        "message": f"Taki klient już jest: {described}.",
        "clients": [item.as_dict() for item in found],
    }
