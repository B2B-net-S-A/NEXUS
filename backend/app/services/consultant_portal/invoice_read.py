"""Pola faktury PDF z rozliczenia@ i z portalu: koszt w kontroli miesiąca.

Decyzja Artura z 27.11.2026: faktury konsultantów spoza KSeF (papier, PDF)
NEXUS ma widzieć sam, równolegle z eBI24, a nie dopiero po jego wyłączeniu.
Do tej pory widział je tylko z eksportu archiwum eBI24 z 16.11, a faktura PDF
z poczty leżała w ``cp_documents`` bez kwoty.

Odczyt robi ten sam czytnik co przy zgodach (``hr.approvals.reader``, model
z rejestru ``expense_document_read`` w ``ai_feature()``): sprzedawca, NIP,
numer, data, kwoty. Wynik to dodatek, nie warunek: dokument leży dalej
w Back Office jak dotąd.

* Odpowiedź bez kwoty albo nie do odczytania → ``failed`` na stałe; kontrola
  miesiąca tego dokumentu nie liczy.
* Awaria wywołania (sieć, 429, 529) albo chwilowy brak pliku → ``retry``
  z licznikiem; po ``MAX_ATTEMPTS`` próbach ``failed``. Bez tego jedna awaria
  modelu w przebiegu pętli oznaczałaby do ``LIMIT`` prawdziwych faktur jako
  nieczytelne na zawsze (przegląd 27.11.2026).

Czytamy pliki PDF i zdjęcia faktur (nie arkusze ani maile), nieodrzucone,
po kilka na przebieg pętli czytnika poczty (``LIMIT``), od najnowszych.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ai_feature import AIFeatureKey
from app.models.consultant_portal import CpDocument
from app.services.ai_quota import AIQuotaExceeded, ai_feature
from app.services.consultant_portal import documents
from app.services.hr.approvals import reader

logger = logging.getLogger(__name__)

#: Plików na jeden przebieg pętli (co 15 min): ok. 100 faktur w miesiącu.
LIMIT = 10
MAX_ATTEMPTS = 3
READABLE_MIMES = ("application/pdf", "image/jpeg", "image/png", "image/webp")
READ, FAILED, RETRY = "read", "failed", "retry"
_ZERO = Decimal("0")


def _amount(raw: Any) -> Optional[Decimal]:
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


def cost_net(fields: Any) -> Optional[Decimal]:
    """Netto do kontroli miesiąca: netto z faktury, a bez niego brutto tylko
    przy VAT jawnie zerowym (zwolnienie). VAT nieodczytany ≠ zero: brutto
    faktury z VAT-em zawyżyłoby koszt o 23% (przegląd 27.11.2026)."""

    if not isinstance(fields, dict):
        return None
    net = _amount(fields.get("net_amount"))
    if net is not None:
        return net
    if _amount(fields.get("vat_amount")) == _ZERO:
        return _amount(fields.get("gross_amount"))
    return None


def _nip_digits(raw: Any) -> str:
    value = "".join(ch for ch in str(raw or "").upper() if ch.isalnum())
    return value[2:] if value.startswith("PL") and value[2:].isdigit() else value


def own_company_document(fields: Any) -> bool:
    """Sprzedawcą jest nasza spółka (``KSEF_CONTEXT_NIP``): to nie faktura konsultanta.

    Produkcja 28.11.2026: zamówienie klienta (Energa, „EITE/Z/UR/…”, 93 000 zł)
    przyszło na rozliczenia@ i czytnik odczytał je jako fakturę z netto, ze
    sprzedawcą B2B.NET. Bez kontraktu nikt go nie dostał, ale przypięte do
    kontraktu osoby (np. przekazane przez konsultanta) liczyłoby się jako jej koszt.
    """

    company = _nip_digits(getattr(settings, "KSEF_CONTEXT_NIP", ""))
    if not company or not isinstance(fields, dict):
        return False
    return _nip_digits(fields.get("seller_nip")) == company


def counts_as_cost(fields: Any) -> bool:
    """Odczyt nadaje się do kontroli miesiąca: faktura z kwotą netto.

    Status ``failed`` z czytnika zgód znaczy „bez brutto” (wydatek płaci się
    brutto), a koszt w kontroli miesiąca to netto: faktura z netto bez
    odczytanego brutto liczy się (produkcja 28.11.2026: faktura za X z netto
    i bez brutto wypadała z kontroli). Nie liczy się tylko ponawiany odczyt
    i paragon, a także dokument, w którym sprzedawcą jest nasza spółka
    (``own_company_document``)."""

    return (
        isinstance(fields, dict)
        and fields.get("status") in (READ, FAILED)
        and fields.get("doc_type") != "receipt"
        and cost_net(fields) is not None
        and not own_company_document(fields)
    )


def _retry(document: CpDocument, error: str) -> dict[str, Any]:
    previous = document.invoice_fields or {}
    attempts = int(previous.get("attempts") or 0) + 1
    status = FAILED if attempts >= MAX_ATTEMPTS else RETRY
    return {"status": status, "error": error, "attempts": attempts}


async def read_one(db: AsyncSession, document: CpDocument) -> dict[str, Any]:
    """Odczyt jednego pliku; zapisuje wynik przy dokumencie i go zwraca.

    ``{}`` = limit AI, bez zapisu (dokument wraca w następnym przebiegu)."""

    try:
        content = documents.path_for(document.file_path).read_bytes()
    except (FileNotFoundError, OSError):
        result = _retry(document, "no_file")
    else:
        try:
            async with ai_feature(db, AIFeatureKey.expense_document_read):
                read = await reader.try_read(content, document.mime)
        except AIQuotaExceeded:
            return {}
        result = read.as_json() if read is not None else _retry(document, "model")
    document.invoice_fields = result
    return result


async def read_pending(db: AsyncSession, *, limit: int = LIMIT) -> dict[str, int]:
    """Nieczytane i do ponowienia faktury z poczty i portalu; wołający zatwierdza."""

    rows = (
        await db.scalars(
            select(CpDocument)
            .where(
                CpDocument.kind == "invoice",
                CpDocument.status != "rejected",
                CpDocument.mime.in_(READABLE_MIMES),
                or_(
                    CpDocument.invoice_fields.is_(None),
                    CpDocument.invoice_fields["status"].astext == RETRY,
                ),
            )
            .order_by(CpDocument.id.desc())
            .limit(limit)
        )
    ).all()
    out = {READ: 0, FAILED: 0, RETRY: 0, "later": 0}
    for document in rows:
        result = await read_one(db, document)
        if not result:
            out["later"] += 1
            break
        if result.get("status") == RETRY:
            out[RETRY] += 1
        else:
            out[READ if counts_as_cost(result) else FAILED] += 1
    return out
