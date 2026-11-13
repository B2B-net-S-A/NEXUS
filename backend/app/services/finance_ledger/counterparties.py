"""Kartoteka kontrahentów z kontami Symfonii (E0): lista, rola, import, edycja.

Rola nie jest zapisana — liczymy ją przy odczycie z tego, co NEXUS już wie
o numerze, w tej kolejności:

* ``client`` — NIP albo VAT UE prowadzi do klienta (``client_invoicing.clients
  .nip_registry``, ta sama reguła co przy fakturach do klientów),
* ``team`` — NIP osoby zespołu z danych do rozliczeń (``employee_billing_details``),
* ``contractor`` — NIP kontraktora klienta (kontrakt aktywny albo niedawno
  zakończony, ``contractor_invoices.load_index``),
* ``supplier`` — reszta: dostawcy biura i usług.

Import nadpisuje pola, które plik ma wypełnione; pusta komórka niczego nie
kasuje (konto wpisane ręcznie w NEXUSIE nie znika po ponownym imporcie pliku
bez tej kolumny). Kontrahenta szukamy po identyfikatorze, potem po ID Symfonii.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance_ledger import FinanceCounterparty
from app.models.hr_settlement import EmployeeBillingDetails
from app.services.finance_ledger import counterparty_import as importer
from app.services.finance_ledger import identifiers
from app.services.finance_ledger_schema import LINK_COUNTERPARTIES
from app.services.order_client_identity import normalize_buyer_number

ROLES: tuple[str, ...] = ("client", "team", "contractor", "supplier")
ROLE_LABELS = {
    "client": "klient",
    "team": "osoba zespołu",
    "contractor": "kontraktor",
    "supplier": "dostawca",
}
EDITABLE = ("symfonia_partner_id", "cost_account", "revenue_account", "email")
ERROR_SAMPLE = 50


class CounterpartyError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class RoleIndex:
    clients: frozenset[str] = frozenset()
    team: frozenset[str] = frozenset()
    contractors: frozenset[str] = frozenset()

    def role(self, id_type: Optional[str], id_value: Optional[str]) -> str:
        if not id_value or id_type not in ("nip", "vat_eu"):
            return "supplier"
        if normalize_buyer_number(id_value) in self.clients:
            return "client"
        if id_type == "nip" and id_value in self.team:
            return "team"
        if id_type == "nip" and id_value in self.contractors:
            return "contractor"
        return "supplier"


async def role_index(db: AsyncSession, today) -> RoleIndex:
    from app.services.client_invoicing.clients import nip_registry  # noqa: PLC0415
    from app.services.client_settlements import contractor_invoices  # noqa: PLC0415

    registry = await nip_registry(db)
    team = {
        nip
        for nip in await db.scalars(
            select(EmployeeBillingDetails.nip).where(
                EmployeeBillingDetails.nip.is_not(None)
            )
        )
        if nip
    }
    contractors = await contractor_invoices.load_index(db, today)
    return RoleIndex(
        clients=frozenset(registry.by_nip) | registry.ambiguous,
        team=frozenset(team),
        contractors=frozenset(contractors.by_nip),
    )


def payload(row: FinanceCounterparty, role: str) -> dict[str, Any]:
    return {
        "id": row.id,
        "id_type": row.id_type,
        "id_type_label": identifiers.TYPE_LABELS.get(row.id_type or "", None),
        "id_value": row.id_value,
        "name": row.name,
        "street": row.street,
        "postal_code": row.postal_code,
        "city": row.city,
        "country": row.country,
        "email": row.email,
        "symfonia_partner_id": row.symfonia_partner_id,
        "cost_account": row.cost_account,
        "revenue_account": row.revenue_account,
        "role": role,
        "role_label": ROLE_LABELS[role],
        "imported_at": row.imported_at.isoformat() if row.imported_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def list_view(
    db: AsyncSession,
    *,
    today,
    q: Optional[str],
    role: Optional[str],
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """Kartoteka z rolą; ok. 2,3 tys. wierszy, więc rolę liczymy w pamięci."""

    statement = select(FinanceCounterparty).order_by(
        FinanceCounterparty.name, FinanceCounterparty.id
    )
    needle = " ".join((q or "").split())
    if needle:
        pattern = f"%{needle}%"
        compact = identifiers.normalize_search(needle)
        conditions = [
            FinanceCounterparty.name.ilike(pattern),
            FinanceCounterparty.symfonia_partner_id.ilike(pattern),
            FinanceCounterparty.cost_account.ilike(pattern),
            FinanceCounterparty.revenue_account.ilike(pattern),
        ]
        if compact:
            conditions.append(FinanceCounterparty.id_value.ilike(f"%{compact}%"))
        statement = statement.where(or_(*conditions))
    rows = list(await db.scalars(statement))
    index = await role_index(db, today)
    counted = [(row, index.role(row.id_type, row.id_value)) for row in rows]
    counts = {name: 0 for name in ROLES}
    for _row, row_role in counted:
        counts[row_role] += 1
    if role:
        counted = [(row, row_role) for row, row_role in counted if row_role == role]
    return {
        "items": [
            payload(row, row_role) for row, row_role in counted[offset : offset + limit]
        ],
        "total": len(counted),
        "role_counts": counts,
        "without_account": sum(1 for row, _ in counted if not row.cost_account),
    }


async def update(
    db: AsyncSession,
    counterparty_id: int,
    changes: dict[str, Optional[str]],
    *,
    actor_id: int,
) -> FinanceCounterparty:
    row = await db.get(FinanceCounterparty, counterparty_id, with_for_update=True)
    if row is None:
        raise CounterpartyError("Nie ma takiego kontrahenta.", status=404)
    raw = {key: (changes.get(key) or "") for key in EDITABLE if key in changes}
    try:
        cleaned = importer.clean_values({"name": row.name, **raw})
    except identifiers.IdentifierError as exc:
        raise CounterpartyError(str(exc), status=422) from exc
    if "email" in raw and raw["email"].strip() and cleaned["email"] is None:
        raise CounterpartyError("Niepoprawny adres e-mail.", status=422)
    for key in raw:
        setattr(row, key, cleaned[key])
    if row.id_value is None and row.symfonia_partner_id is None:
        raise CounterpartyError(
            "Kontrahent bez identyfikatora musi mieć ID Symfonii.", status=422
        )
    if row.symfonia_partner_id:
        taken = await db.scalar(
            select(FinanceCounterparty.id).where(
                FinanceCounterparty.symfonia_partner_id == row.symfonia_partner_id,
                FinanceCounterparty.id != row.id,
            )
        )
        if taken is not None:
            raise CounterpartyError("To ID Symfonii ma już inny kontrahent.")
    row.updated_by = actor_id
    await db.flush()
    await db.refresh(row)
    return row


# ── Import ───────────────────────────────────────────────────────────────────


@dataclass
class ImportResult:
    created: int = 0
    changed: int = 0
    unchanged: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    changes: list[dict[str, Any]] = field(default_factory=list)
    linked_entries: int = 0

    def as_dict(self, parsed: importer.ParsedFile, *, saved: bool) -> dict[str, Any]:
        return {
            "saved": saved,
            "rows": len(parsed.rows) + len(self.errors),
            "created": self.created,
            "changed": self.changed,
            "unchanged": self.unchanged,
            "error_count": len(self.errors),
            "errors": self.errors[:ERROR_SAMPLE],
            "changes": self.changes[:ERROR_SAMPLE],
            "columns": sorted(set(parsed.columns.values())),
            "linked_entries": self.linked_entries,
        }


async def apply_import(
    db: AsyncSession,
    parsed: importer.ParsedFile,
    *,
    save: bool,
    actor_id: int,
    now: datetime,
) -> ImportResult:
    """Porównanie pliku z kartoteką; ``save`` zapisuje (bez commita).

    Podgląd i zapis idą tą samą drogą, więc liczby z podglądu są tym, co
    zapis zrobi (o ile nikt w międzyczasie nie zmienił kartoteki).
    """

    result = ImportResult(errors=list(parsed.errors))
    existing = list(await db.scalars(select(FinanceCounterparty)))
    by_id = {(row.id_type, row.id_value): row for row in existing if row.id_value}
    by_symfonia = {
        row.symfonia_partner_id: row for row in existing if row.symfonia_partner_id
    }
    for item in parsed.rows:
        row = by_id.get((item.id_type, item.id_value)) if item.id_value else None
        symfonia = item.values.get("symfonia_partner_id")
        owner = by_symfonia.get(symfonia) if symfonia else None
        if row is None and owner is not None:
            if owner.id_value and item.id_value:
                result.errors.append(
                    {
                        "line": item.line,
                        "message": f"ID Symfonii {symfonia} ma kontrahent z innym "
                        "identyfikatorem.",
                    }
                )
                continue
            row = owner
        elif row is not None and owner is not None and owner is not row:
            result.errors.append(
                {
                    "line": item.line,
                    "message": f"ID Symfonii {symfonia} ma już inny kontrahent.",
                }
            )
            continue
        if row is None:
            result.created += 1
            if save:
                created = FinanceCounterparty(
                    id_type=item.id_type,
                    id_value=item.id_value,
                    imported_at=now,
                    updated_by=actor_id,
                    **{key: value for key, value in item.values.items()},
                )
                db.add(created)
                if item.id_value:
                    by_id[(item.id_type, item.id_value)] = created
                if symfonia:
                    by_symfonia[symfonia] = created
            continue
        diff = {
            key: {"from": getattr(row, key), "to": value}
            for key, value in item.values.items()
            if value is not None and getattr(row, key) != value
        }
        if row.id_value is None and item.id_value:
            diff["id_value"] = {"from": None, "to": item.id_value}
        if not diff:
            result.unchanged += 1
            continue
        result.changed += 1
        result.changes.append(
            {"line": item.line, "name": row.name, "fields": sorted(diff)}
        )
        if save:
            for key, change in diff.items():
                setattr(row, key, change["to"])
            if "id_value" in diff:
                row.id_type = item.id_type
                by_id[(item.id_type, item.id_value)] = row
            row.imported_at = now
            row.updated_by = actor_id
    if save:
        await db.flush()
        linked = await db.execute(text(LINK_COUNTERPARTIES))
        result.linked_entries = int(linked.rowcount or 0)
    result.errors.sort(key=lambda error: error["line"])
    return result
