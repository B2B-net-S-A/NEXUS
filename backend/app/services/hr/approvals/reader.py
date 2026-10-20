"""Odczyt kwoty i sprzedawcy z faktury albo paragonu do zgody (F32, 0486).

Model z rejestru (``AIFeatureKey.expense_document_read``) dostaje sam
dokument — PDF albo zdjęcie — bez danych osoby, która prosiła o zgodę.
Wynik to podpowiedź: pola wracają do osoby do sprawdzenia, a kwotę do
rozliczenia zatwierdzają Finanse. Awaria modelu, brak kwoty albo śmieci
w odpowiedzi = ``ReadResult(status="failed")`` — dokument zostaje przy
zgodzie, osoba wpisuje kwotę sama (wynik modelu nigdy nie jest warunkiem).
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from starlette.concurrency import run_in_threadpool

from app.models.ai_feature import AIFeatureKey
from app.services.ai_models import fallbacks_for, model_for
from app.services.hr import white_list

logger = logging.getLogger(__name__)

READER_VERSION = "expense_read:v1"
_AMOUNT_LIMIT = Decimal("10000000")
_CENT = Decimal("0.01")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

PROMPT = """Odczytaj dane z dokumentu zakupu (faktura albo paragon) wystawionego w Polsce albo za granicą.
Zwróć WYŁĄCZNIE obiekt JSON:
{"doc_type": "invoice" albo "receipt", "seller_name": nazwa sprzedawcy, "seller_nip": NIP sprzedawcy (10 cyfr, bez PL) albo null,
 "invoice_number": numer dokumentu albo null, "issue_date": "RRRR-MM-DD" albo null, "currency": kod waluty (PLN, EUR, USD…),
 "net_amount": suma netto albo null, "vat_amount": suma VAT albo null, "gross_amount": kwota do zapłaty brutto}
Kwoty jako liczby z kropką, bez spacji i waluty. Gdy czegoś nie ma w dokumencie, wpisz null — niczego nie zgaduj."""


@dataclass(frozen=True)
class ReadResult:
    status: str  # "read" | "failed"
    fields: dict[str, Any] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {"version": READER_VERSION, "status": self.status, **self.fields}


def _amount(raw: Any) -> Optional[Decimal]:
    if raw is None or isinstance(raw, bool):
        return None
    text = str(raw).replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        value = Decimal(text).quantize(_CENT)
    except (InvalidOperation, ValueError):
        return None
    if value < 0 or value > _AMOUNT_LIMIT:
        return None
    return value


def _nip(raw: Any) -> Optional[str]:
    if not raw:
        return None
    try:
        return white_list.clean_nip(str(raw))
    except white_list.WhiteListError:
        return None


def _date(raw: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(raw)) if raw else None
    except ValueError:
        return None


def _short(raw: Any, limit: int) -> Optional[str]:
    text = " ".join(str(raw or "").split())
    return text[:limit] or None


def clean_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """Pola odczytu po walidacji (kwoty, NIP z sumą kontrolną, data, waluta)."""

    currency = str(raw.get("currency") or "PLN").strip().upper()
    issue = _date(raw.get("issue_date"))
    out: dict[str, Any] = {
        "doc_type": "receipt" if raw.get("doc_type") == "receipt" else "invoice",
        "seller_name": _short(raw.get("seller_name"), 256),
        "seller_nip": _nip(raw.get("seller_nip")),
        "invoice_number": _short(raw.get("invoice_number"), 256),
        "issue_date": issue.isoformat() if issue else None,
        "currency": currency if _CURRENCY_RE.match(currency) else "PLN",
        "net_amount": None,
        "vat_amount": None,
        "gross_amount": None,
    }
    for key in ("net_amount", "vat_amount", "gross_amount"):
        value = _amount(raw.get(key))
        out[key] = str(value) if value is not None else None
    return out


def parse_reply(text: str) -> ReadResult:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return ReadResult("failed")
    try:
        raw = json.loads(text[start : end + 1])
    except ValueError:
        return ReadResult("failed")
    if not isinstance(raw, dict):
        return ReadResult("failed")
    fields = clean_fields(raw)
    if fields["gross_amount"] is None:
        return ReadResult("failed", fields)
    return ReadResult("read", fields)


def _content_block(content: bytes, mime: str) -> dict[str, Any]:
    data = base64.b64encode(content).decode("ascii")
    if mime == "application/pdf":
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": mime, "data": data},
        }
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": mime, "data": data},
    }


def _call_model(content: bytes, mime: str) -> str:
    from app.services.claude_client import call_claude, text_of  # noqa: PLC0415

    message = call_claude(
        model=model_for(AIFeatureKey.expense_document_read),
        fallback_models=list(fallbacks_for(AIFeatureKey.expense_document_read)),
        max_tokens=800,
        temperature=0,
        thinking={"type": "disabled"},
        messages=[
            {
                "role": "user",
                "content": [
                    _content_block(content, mime),
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
    )
    return text_of(message)


async def read_document(content: bytes, mime: str) -> ReadResult:
    """Wywołanie modelu (wołający deklaruje ``ai_feature``); awaria = ``failed``."""

    try:
        reply = await run_in_threadpool(_call_model, content, mime)
    except Exception as exc:  # noqa: BLE001 — odczyt to dodatek, dokument zostaje
        logger.warning("approvals: odczyt dokumentu nieudany (%s)", type(exc).__name__)
        return ReadResult("failed")
    return parse_reply(reply)
