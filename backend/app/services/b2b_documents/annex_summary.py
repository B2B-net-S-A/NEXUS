"""Skrót zmiany z aneksu — rejestr aneksów i zakładka „Aneksy” kontraktu.

Lista ma odpowiadać na „jaki aneks” bez otwierania dokumentu: „140,00 →
150,00 zł/h”, „02.11.2026 → 16.11.2026”, nazwa osoby skierowanej. Wartości
pochodzą z zapisanego formularza (``render_payload["values"]``), więc skrót
mówi to samo, co wydany plik.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.services.b2b_documents.annex_register import normalized_rate_items
from app.services.b2b_documents.registry import parse_amount


def _iso(value: Any) -> str | None:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10]).isoformat()
        except ValueError:
            return None
    return None


def _rate_items(values: dict[str, Any]) -> list[dict[str, Any]]:
    items = normalized_rate_items(values)
    if items:
        return items
    # Aneks sprzed generatora aneksów niesie jedną stawkę w `new_rate`.
    amount = parse_amount(values.get("new_rate"))
    if amount is None:
        return []
    return [
        {
            "rate": round(amount, 2),
            "from": None,
            "to": None,
            "client_id": None,
            "client_name": None,
        }
    ]


def annex_change(
    doc_type_key: str,
    values: dict[str, Any],
    *,
    rates_visible: bool,
    rates_before: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Co zmienia aneks, w kształcie dla listy. ``None`` = typ bez skrótu.

    Kwoty wyłącznie przy ``rates_visible`` (ta sama reguła widoczności stawek
    co DOCX aneksu); bez niej lista mówi tylko, że to zmiana stawki."""
    if doc_type_key == "annex_rate_change":
        if not rates_visible:
            return {"kind": "rate", "hidden": True}
        return {
            "kind": "rate",
            "hidden": False,
            "currency": str(values.get("currency") or "PLN").upper(),
            "items": _rate_items(values),
            "before": list(rates_before or []),
        }
    if doc_type_key == "annex_start_date":
        return {
            "kind": "start_date",
            "before": _iso(values.get("current_start_date")),
            "after": _iso(values.get("new_start_date")),
        }
    if doc_type_key == "annex_party_data":
        nip = "".join(ch for ch in str(values.get("new_nip") or "") if ch.isdigit())
        return {
            "kind": "party",
            "legal_name": (values.get("new_legal_name") or "").strip() or None,
            "nip": nip or None,
        }
    if doc_type_key == "annex_subcontractor":
        return {
            "kind": "delegate",
            "name": (values.get("delegate_name") or "").strip() or None,
        }
    if doc_type_key == "annex_mandate":
        return {
            "kind": "mandate",
            "period_from": _iso(values.get("period_from")),
            "period_to": _iso(values.get("period_to")),
            "rate_changed": bool(values.get("change_rate")),
        }
    return None
