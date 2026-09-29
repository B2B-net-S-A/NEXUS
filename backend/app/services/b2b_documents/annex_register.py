"""Generator aneksów → wiersz rejestru „Umowy bieżące” PRZY WYGENEROWANIU.

Decyzja Artura 29.09.2026 (ticket „Generator aneksów”): wiersz rejestru
zmienia się od razu po wygenerowaniu aneksu — firma i NIP (uzupełnienie danych
firmy), data rozpoczęcia (zmiana daty startu), stawki (zmiana stawki).
Kontrakt, harmonogram stawek i profil kandydata zmieniają się dalej dopiero
przy „Oznacz jako podpisany” (``effects.py``) — aneks, którego nikt nie
podpisał, nie może zostawić w kontrakcie stawki bez podpisu.

Dlatego zmiana w rejestrze jest ODWRACALNA: dokument zapamiętuje stan wiersza
sprzed pierwszego zastosowania (``register_before``) i to, co sam wpisuje
(``register_applied``), a wiersz jest przeliczany (``_recompute``): wartość
z najnowszego aktywnego aneksu tego typu, bez aktywnych — stan sprzed
pierwszego. Anulowanie albo usunięcie niepodpisanego aneksu przelicza wiersz
z pominięciem tego aneksu.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.b2b_contract_document import B2BContractDocument
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.services.b2b_documents.registry import parse_amount

#: Pola wiersza, które zmienia dany typ aneksu.
REGISTER_FIELDS: dict[str, tuple[str, ...]] = {
    "annex_party_data": ("partner_legal_name", "partner_nip", "partner_entity_type"),
    "annex_start_date": ("start_date", "start_date_mode"),
    "annex_rate_change": ("annex_rates",),
}

_DATE_FIELDS = frozenset({"start_date"})


def _iso(value: Any) -> str | None:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10]).isoformat()
        except ValueError:
            return None
    return None


def _to_json(field: str, value: Any) -> Any:
    return _iso(value) if field in _DATE_FIELDS else value


def _from_json(field: str, value: Any) -> Any:
    if field in _DATE_FIELDS and isinstance(value, str):
        return date.fromisoformat(value[:10])
    return value


def normalized_rate_items(values: dict[str, Any]) -> list[dict[str, Any]]:
    """Pozycje stawki w kształcie zapisu (liczby, daty ISO, klient z nazwą)."""
    items: list[dict[str, Any]] = []
    for raw in values.get("rate_items") or []:
        if not isinstance(raw, dict):
            continue
        amount = parse_amount(raw.get("rate"))
        if amount is None:
            continue
        client_id = raw.get("client_id")
        items.append(
            {
                "rate": round(amount, 2),
                "from": _iso(raw.get("from")),
                "to": _iso(raw.get("to")),
                "client_id": int(client_id) if client_id else None,
                "client_name": (raw.get("client_name") or None),
            }
        )
    return items


def planned(
    doc_type_key: str, values: dict[str, Any], *, document_id: int | None
) -> dict[str, Any]:
    """Nowe wartości pól wiersza (w kształcie JSON) — bez zapisu."""
    if doc_type_key == "annex_party_data":
        nip = "".join(ch for ch in str(values.get("new_nip") or "") if ch.isdigit())
        return {
            "partner_legal_name": (values.get("new_legal_name") or "").strip() or None,
            "partner_nip": nip or None,
            # Aneks uzupełnienia danych dotyczy zawsze osoby fizycznej, która
            # założyła JDG (ticket, pkt 1.4).
            "partner_entity_type": "sole_trader",
        }
    if doc_type_key == "annex_start_date":
        return {
            "start_date": _iso(values.get("new_start_date")),
            "start_date_mode": "exact",
        }
    if doc_type_key == "annex_rate_change":
        return {
            "annex_rates": {
                "items": normalized_rate_items(values),
                "effective_date": _iso(values.get("effective_date")),
                "document_id": document_id,
            }
        }
    return {}


def _current(row: B2BGeneratedContract, field: str) -> Any:
    return _to_json(field, getattr(row, field))


def _applied(doc: B2BContractDocument) -> dict[str, Any]:
    applied = (doc.render_payload or {}).get("register_applied")
    return applied if isinstance(applied, dict) else {}


async def _recompute(
    db: AsyncSession,
    row: B2BGeneratedContract,
    doc_type_key: str,
    *,
    exclude_id: int | None = None,
) -> list[str]:
    """Ustaw pola wiersza na wartość z NAJNOWSZEGO aktywnego aneksu tego typu
    (kolejność wystawienia), a bez aktywnych — na stan sprzed pierwszego.

    Pamiętanie samego „przed” w każdym dokumencie nie wystarcza: anulowanie
    aneksu A po wystawieniu B, a potem B, wracało do wartości A — aneksu, który
    nie doszedł do skutku; „Popraw” starszego aneksu nadpisywał nowszy. Pole,
    którego wartość nie pochodzi z żadnego aneksu (zmiana spoza generatora,
    np. import z Excela), zostaje nietknięte."""
    fields = REGISTER_FIELDS.get(doc_type_key, ())
    if not fields:
        return []
    docs = list(
        (
            await db.scalars(
                select(B2BContractDocument)
                .where(
                    B2BContractDocument.parent_generated_contract_id == row.id,
                    B2BContractDocument.document_type == doc_type_key,
                )
                .order_by(B2BContractDocument.id)
            )
        ).all()
    )
    changed: list[str] = []
    for field in fields:
        touching = [d for d in docs if field in _applied(d)]
        if not touching:
            continue
        before = (touching[0].render_payload or {}).get("register_before") or {}
        baseline = before.get(field) if isinstance(before, dict) else None
        active = [d for d in touching if d.id != exclude_id and d.status != "cancelled"]
        target = _applied(active[-1])[field] if active else baseline
        current = _current(row, field)
        if current == target:
            continue
        known = [baseline, *(_applied(d)[field] for d in touching)]
        if current not in known:
            continue
        setattr(row, field, _from_json(field, target))
        changed.append(field)
    return changed


async def apply(
    db: AsyncSession,
    doc: B2BContractDocument,
    row: B2BGeneratedContract,
    values: dict[str, Any],
) -> None:
    """Zapisz w dokumencie, co wpisuje do wiersza, i przelicz wiersz.

    ``register_before`` = stan wiersza przed PIERWSZYM zastosowaniem tego
    dokumentu (bazą jest ``register_before`` najstarszego aneksu)."""
    fields = REGISTER_FIELDS.get(doc.document_type, ())
    if not fields:
        return
    payload = dict(doc.render_payload or {})
    changes = planned(doc.document_type, values, document_id=doc.id)
    before = payload.get("register_before")
    if not isinstance(before, dict):
        before = {field: _current(row, field) for field in fields}
    applied: dict[str, Any] = {}
    for field in fields:
        new_value = changes.get(field)
        if new_value is None and field != "annex_rates":
            # Brak wartości w aneksie nie kasuje danych wiersza.
            continue
        applied[field] = new_value
    payload["register_before"] = before
    payload["register_applied"] = applied
    doc.render_payload = payload
    await db.flush()
    await _recompute(db, row, doc.document_type)


async def revert(
    db: AsyncSession,
    doc: B2BContractDocument,
    row: B2BGeneratedContract | None,
) -> list[str]:
    """Aneks anulowany albo usuwany: wiersz wraca do najnowszego aktywnego
    aneksu tego typu albo do stanu sprzed aneksów. Zwraca zmienione pola."""
    if row is None or not _applied(doc):
        return []
    return await _recompute(db, row, doc.document_type, exclude_id=doc.id)


def rate_items_from_register(row: B2BGeneratedContract) -> list[dict[str, Any]]:
    """Obecne stawki umowy: ostatni aneks albo etapy z wygenerowanej umowy."""
    annex = row.annex_rates if isinstance(row.annex_rates, dict) else None
    if annex and annex.get("items"):
        return [dict(i) for i in annex["items"] if isinstance(i, dict)]
    payload = row.render_payload or {}
    stages = payload.get("rate_stages") or []
    items: list[dict[str, Any]] = []
    for stage in stages:
        if not isinstance(stage, dict) or stage.get("rate") in (None, ""):
            continue
        items.append(
            {
                "rate": stage.get("rate"),
                "from": _iso(stage.get("effective_from")),
                "to": _iso(stage.get("effective_to")),
                "client_id": None,
                "client_name": None,
            }
        )
    if not items and payload.get("rate_candidate") not in (None, ""):
        items.append(
            {
                "rate": payload.get("rate_candidate"),
                "from": None,
                "to": None,
                "client_id": None,
                "client_name": None,
            }
        )
    return items
