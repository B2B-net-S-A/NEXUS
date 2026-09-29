"""Generator aneksów → wiersz rejestru „Umowy bieżące” PRZY WYGENEROWANIU.

Decyzja Artura 29.09.2026 (ticket „Generator aneksów”): wiersz rejestru
zmienia się od razu po wygenerowaniu aneksu — firma i NIP (uzupełnienie danych
firmy), data rozpoczęcia (zmiana daty startu), stawki (zmiana stawki).
Kontrakt, harmonogram stawek i profil kandydata zmieniają się dalej dopiero
przy „Oznacz jako podpisany” (``effects.py``) — aneks, którego nikt nie
podpisał, nie może zostawić w kontrakcie stawki bez podpisu.

Dlatego zmiana w rejestrze jest ODWRACALNA: dokument zapamiętuje stan wiersza
sprzed pierwszego zastosowania (``register_before``) i to, co sam wpisał
(``register_applied``). Anulowanie albo usunięcie niepodpisanego aneksu
przywraca tylko te pola, które nadal mają wartość z tego aneksu — późniejszy
aneks do tej samej umowy wygrywa.
"""

from __future__ import annotations

from datetime import date
from typing import Any

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


def apply(
    doc: B2BContractDocument,
    row: B2BGeneratedContract,
    values: dict[str, Any],
) -> dict[str, Any]:
    """Wpisz zmiany aneksu do wiersza i zapamiętaj stan sprzed nich.

    Zwraca nowy ``render_payload`` dokumentu (wołający go przypisuje).
    Ponowne wygenerowanie („Popraw”) zostawia pierwotny ``register_before``."""
    fields = REGISTER_FIELDS.get(doc.document_type, ())
    payload = dict(doc.render_payload or {})
    if not fields:
        return payload
    changes = planned(doc.document_type, values, document_id=doc.id)
    before = payload.get("register_before")
    if not isinstance(before, dict):
        before = {field: _current(row, field) for field in fields}
    applied: dict[str, Any] = {}
    for field in fields:
        if field not in changes:
            continue
        new_value = changes[field]
        if new_value is None and field != "annex_rates":
            # Brak wartości w aneksie nie kasuje danych wiersza.
            continue
        setattr(row, field, _from_json(field, new_value))
        applied[field] = new_value
    payload["register_before"] = before
    payload["register_applied"] = applied
    return payload


def revert(doc: B2BContractDocument, row: B2BGeneratedContract | None) -> list[str]:
    """Cofnij zmiany aneksu w wierszu — tylko pola, których nikt nie zmienił
    od tego czasu. Zwraca listę przywróconych pól."""
    if row is None:
        return []
    payload = doc.render_payload or {}
    before = payload.get("register_before")
    applied = payload.get("register_applied")
    if not isinstance(before, dict) or not isinstance(applied, dict):
        return []
    restored: list[str] = []
    for field, value in applied.items():
        if field not in before or _current(row, field) != value:
            continue
        setattr(row, field, _from_json(field, before[field]))
        restored.append(field)
    return restored


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
