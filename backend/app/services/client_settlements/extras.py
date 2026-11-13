"""Dodatki do rozliczenia kontraktora (potrzeba Finansów z 13.11.2026).

Kontraktor dolicza do faktury kwoty spoza godzin: premię za polecenie,
weryfikację techniczną (zleca ją rekruter), szkolenie, delegację. Dodatek to
wiersz ``client_settlement_extras`` na (kontrakt, miesiąc):

* zgłasza go back office z karty sprawy, Finanse na karcie osoby albo
  konsultant w panelu (delegacja z dokumentami) — zawsze jako ``pending``;
  Finanse wpisujące dodatek same go od razu zatwierdzają,
* zatwierdzony dodatek zwiększa oczekiwaną kwotę faktury kontraktora
  (``expected``), więc faktura z doliczonym poleceniem nie jest „inną kwotą”,
* różnica faktury równa zgłoszonemu, a niezatwierdzonemu dodatkowi to uwaga
  „czeka na zatwierdzenie dodatku”, nigdy błąd: koszty dodatkowe przed
  odrzuceniem potwierdza rozliczający (reguła ``travel.extra_costs_confirm``),
  dlatego odrzucenie wymaga powodu,
* dodatek z ``bill_to_client`` idzie do „Do faktury dla klienta” według
  ``cl.extra_costs_on_invoice``.

Rodzaj ``integration`` (koszty integracji BNP, ``cl.integration_costs``) ma
własną ścieżkę ze zgodą DL-a — tu go nie zgłaszamy, nie zatwierdzamy i nie
liczymy do kwoty faktury kontraktora.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_settlement_extra import (
    ClientSettlementExtra,
    ClientSettlementExtraDocument,
)
from app.models.contract import Contract
from app.services import storage_service
from app.services.client_settlement_extras_schema import (
    DECISION_NOTE_MAX,
    FILE_NAME_MAX,
)
from app.services.client_settlements_schema import (
    EXTRA_DESCRIPTION_MAX as DESCRIPTION_MAX,
)
from app.services.hr import documents_store

PENDING, APPROVED, REJECTED = "pending", "approved", "rejected"
SOURCE_BACK_OFFICE, SOURCE_FINANCE, SOURCE_PORTAL = "back_office", "finance", "portal"
INTEGRATION = "integration"
TRAVEL = "travel"

KIND_LABELS: dict[str, str] = {
    "referral": "Premia za polecenie",
    "tech_check": "Weryfikacja techniczna",
    "training": "Szkolenie",
    "travel": "Delegacja",
    "integration": "Koszty integracji",
    "other": "Inny dodatek",
}
#: Rodzaje, które zgłasza back office i Finanse (integracja ma ścieżkę DL-a).
STAFF_KINDS: tuple[str, ...] = tuple(k for k in KIND_LABELS if k != INTEGRATION)
STATUS_LABELS = {PENDING: "Zgłoszony", APPROVED: "Zatwierdzony", REJECTED: "Odrzucony"}
SOURCE_LABELS = {
    SOURCE_BACK_OFFICE: "back office",
    SOURCE_FINANCE: "Finanse",
    SOURCE_PORTAL: "konsultant w panelu",
}

AMOUNT_MAX = Decimal("100000")
MONEY = Decimal("0.01")
DOCS_PER_EXTRA = 10
STORE_DIR = "settlement_extras"
_MONTH = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


class ExtraError(ValueError):
    """Odmowa z komunikatem dla użytkownika."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


# ── Walidacja ────────────────────────────────────────────────────────────────


def clean_month(month: str) -> str:
    if not _MONTH.match(month or ""):
        raise ExtraError("Podaj okres w formacie RRRR-MM.")
    return month


def clean_amount(raw: Any) -> Decimal:
    try:
        value = Decimal(str(raw).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except InvalidOperation:
        raise ExtraError("Podaj kwotę netto, np. 200 albo 200,50.") from None
    if not value.is_finite() or value <= 0 or value > AMOUNT_MAX:
        raise ExtraError(
            "Kwota netto musi być większa od zera i nie większa niż 100 000 zł."
        )
    return value.quantize(MONEY)


def clean_text(raw: Optional[str], *, minimum: int, maximum: int, label: str) -> str:
    value = " ".join((raw or "").replace("\x00", "").split())
    if len(value) < minimum:
        raise ExtraError(label)
    return value[:maximum]


def clean_kind(kind: str, allowed: Iterable[str] = STAFF_KINDS) -> str:
    if kind not in allowed:
        raise ExtraError("Wybierz rodzaj dodatku.")
    return kind


# ── Suma do faktury kontraktora ──────────────────────────────────────────────


@dataclass(frozen=True)
class Totals:
    """Dodatki osoby w miesiącu, które liczą się do faktury kontraktora."""

    approved: Decimal = Decimal("0")
    pending: tuple[Decimal, ...] = field(default_factory=tuple)

    @property
    def pending_total(self) -> Decimal:
        return sum(self.pending, Decimal("0"))

    def explains(self, diff: Decimal, tolerance: Decimal) -> bool:
        """Czy różnica faktury to zgłoszony, a niezatwierdzony dodatek (jeden albo wszystkie)."""

        if not self.pending:
            return False
        candidates = (*self.pending, self.pending_total)
        return any(abs(diff - amount) <= tolerance for amount in candidates)


def counts_on_invoice(extra: ClientSettlementExtra) -> bool:
    return extra.kind != INTEGRATION


def totals(extras: Iterable[ClientSettlementExtra]) -> Totals:
    approved = Decimal("0")
    pending: list[Decimal] = []
    for extra in extras:
        if not counts_on_invoice(extra):
            continue
        if extra.status == APPROVED:
            approved += Decimal(extra.amount)
        elif extra.status == PENDING:
            pending.append(Decimal(extra.amount))
    return Totals(approved, tuple(pending))


async def for_contracts(
    db: AsyncSession, contract_ids: list[int], month: str
) -> dict[int, list[ClientSettlementExtra]]:
    if not contract_ids:
        return {}
    rows = await db.scalars(
        select(ClientSettlementExtra)
        .where(
            ClientSettlementExtra.contract_id.in_(contract_ids),
            ClientSettlementExtra.period_month == month,
        )
        .order_by(ClientSettlementExtra.created_at, ClientSettlementExtra.id)
    )
    out: dict[int, list[ClientSettlementExtra]] = {}
    for row in rows:
        out.setdefault(int(row.contract_id), []).append(row)
    return out


async def expected_by_contract(
    db: AsyncSession, contract_ids: list[int], month: str
) -> dict[int, Totals]:
    """Zatwierdzone i czekające dodatki osób w miesiącu — do kontroli ``ci.amount``."""

    return {
        cid: totals(items)
        for cid, items in (await for_contracts(db, contract_ids, month)).items()
    }


def margin_shift(items: Iterable[ClientSettlementExtra]) -> tuple[Decimal, Decimal]:
    """(dodatkowy koszt, dodatkowy przychód) miesiąca: zatwierdzone dodatki są kosztem,
    fakturowane klientowi także przychodem. Integracja liczy się osobno (DL)."""

    approved = [e for e in items if e.status == APPROVED and counts_on_invoice(e)]
    cost = sum((Decimal(e.amount) for e in approved), Decimal("0"))
    revenue = sum(
        (Decimal(e.amount) for e in approved if e.bill_to_client), Decimal("0")
    )
    return cost, revenue


async def billed_to_client(
    db: AsyncSession, contract_ids: list[int], month: str
) -> dict[int, list[ClientSettlementExtra]]:
    """Zatwierdzone dodatki fakturowane klientowi (``cl.extra_costs_on_invoice``)."""

    return {
        cid: kept
        for cid, items in (await for_contracts(db, contract_ids, month)).items()
        if (
            kept := [
                e
                for e in items
                if e.status == APPROVED and e.bill_to_client and counts_on_invoice(e)
            ]
        )
    }


# ── Zapis ────────────────────────────────────────────────────────────────────


async def create(
    db: AsyncSession,
    contract_id: int,
    month: str,
    *,
    kind: str,
    amount: Any,
    description: Optional[str],
    source: str,
    actor_id: Optional[int],
    now: datetime,
    bo_card_id: Optional[int] = None,
    bill_to_client: bool = False,
    approve: bool = False,
    kinds: Iterable[str] = STAFF_KINDS,
) -> ClientSettlementExtra:
    contract = await db.get(Contract, contract_id)
    if contract is None:
        raise ExtraError("Nie ma takiego kontraktu.", status=404)
    if contract.client_id is None:
        raise ExtraError(
            "Kontrakt nie ma klienta — dodatek nie ma się gdzie rozliczyć."
        )
    kind = clean_kind(kind, kinds)
    text = (
        clean_text(
            description,
            minimum=0 if kind != "other" else 3,
            maximum=DESCRIPTION_MAX,
            label="Opisz, czego dotyczy dodatek.",
        )
        or KIND_LABELS[kind]
    )
    extra = ClientSettlementExtra(
        client_id=int(contract.client_id),
        contract_id=contract_id,
        period_month=clean_month(month),
        kind=kind,
        amount=clean_amount(amount),
        description=text,
        status=APPROVED if approve else PENDING,
        source=source,
        bo_card_id=bo_card_id,
        bill_to_client=bool(bill_to_client),
        created_by=actor_id,
        decided_by=actor_id if approve else None,
        decided_at=now if approve else None,
    )
    db.add(extra)
    await db.flush()
    return extra


async def _locked(
    db: AsyncSession, extra_id: int, contract_id: int
) -> ClientSettlementExtra:
    extra = await db.scalar(
        select(ClientSettlementExtra)
        .where(ClientSettlementExtra.id == extra_id)
        .with_for_update()
    )
    if extra is None or extra.contract_id != contract_id:
        raise ExtraError("Nie ma takiego dodatku.", status=404)
    if extra.kind == INTEGRATION:
        raise ExtraError(
            "Koszt integracji zatwierdza Delivery Lead klienta w jego ścieżce.",
            status=403,
        )
    return extra


async def approve(
    db: AsyncSession,
    extra_id: int,
    contract_id: int,
    *,
    actor_id: int,
    now: datetime,
    bill_to_client: Optional[bool] = None,
) -> ClientSettlementExtra:
    extra = await _locked(db, extra_id, contract_id)
    extra.status = APPROVED
    extra.decided_by = actor_id
    extra.decided_at = now
    extra.decision_note = None
    if bill_to_client is not None:
        extra.bill_to_client = bill_to_client
    await db.flush()
    return extra


async def reject(
    db: AsyncSession,
    extra_id: int,
    contract_id: int,
    *,
    actor_id: int,
    now: datetime,
    reason: Optional[str],
) -> ClientSettlementExtra:
    """Odrzucenie wymaga powodu: koszt dodatkowy potwierdza rozliczający
    (``travel.extra_costs_confirm``), więc nic nie odrzuca się samo."""

    extra = await _locked(db, extra_id, contract_id)
    extra.status = REJECTED
    extra.decided_by = actor_id
    extra.decided_at = now
    extra.decision_note = clean_text(
        reason,
        minimum=5,
        maximum=DECISION_NOTE_MAX,
        label="Napisz, dlaczego dodatek jest odrzucony — zobaczy to zgłaszający.",
    )
    await db.flush()
    return extra


async def set_billing(
    db: AsyncSession, extra_id: int, contract_id: int, *, bill_to_client: bool
) -> ClientSettlementExtra:
    extra = await _locked(db, extra_id, contract_id)
    extra.bill_to_client = bill_to_client
    await db.flush()
    return extra


# ── Dokumenty ────────────────────────────────────────────────────────────────


def _relative(contract_id: int, digest: str, mime: str) -> str:
    return (
        f"{documents_store.SUBDIR}/{STORE_DIR}/{int(contract_id)}/"
        f"{digest}.{documents_store.EXTENSIONS[mime]}"
    )


async def add_document(
    db: AsyncSession,
    extra: ClientSettlementExtra,
    *,
    content: bytes,
    file_name: Optional[str],
    channel: str,
    uploaded_by: Optional[int],
) -> ClientSettlementExtraDocument:
    """Plik dodatku (faktura, paragon, bilet): PDF, DOCX, JPG albo PNG do 20 MB,
    typ z treści. Ten sam plik drugi raz przy dodatku nie tworzy kopii."""

    try:
        mime, digest = documents_store.check(content)
    except documents_store.FileRejected as exc:
        raise ExtraError(str(exc)) from None
    existing = await db.scalar(
        select(ClientSettlementExtraDocument).where(
            ClientSettlementExtraDocument.extra_id == extra.id,
            ClientSettlementExtraDocument.sha256 == digest,
        )
    )
    if existing is not None:
        return existing
    count = await db.scalar(
        select(func.count())
        .select_from(ClientSettlementExtraDocument)
        .where(ClientSettlementExtraDocument.extra_id == extra.id)
    )
    if (count or 0) >= DOCS_PER_EXTRA:
        raise ExtraError(f"Dodatek może mieć najwyżej {DOCS_PER_EXTRA} plików.")
    relative = _relative(extra.contract_id, digest, mime)
    target = Path(storage_service.STORAGE_ROOT) / relative
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f"{target.name}.part")
        temporary.write_bytes(content)
        os.replace(temporary, target)
    name = (file_name or "").replace("\x00", "").strip()[:FILE_NAME_MAX] or None
    document = ClientSettlementExtraDocument(
        extra_id=extra.id,
        file_path=relative,
        file_name=name,
        mime=mime,
        sha256=digest,
        size_bytes=len(content),
        channel=channel,
        uploaded_by=uploaded_by,
    )
    db.add(document)
    await db.flush()
    return document


async def documents_for(
    db: AsyncSession, extra_ids: list[int]
) -> dict[int, list[ClientSettlementExtraDocument]]:
    if not extra_ids:
        return {}
    rows = await db.scalars(
        select(ClientSettlementExtraDocument)
        .where(ClientSettlementExtraDocument.extra_id.in_(extra_ids))
        .order_by(
            ClientSettlementExtraDocument.created_at, ClientSettlementExtraDocument.id
        )
    )
    out: dict[int, list[ClientSettlementExtraDocument]] = {}
    for row in rows:
        out.setdefault(int(row.extra_id), []).append(row)
    return out


async def document_of(
    db: AsyncSession, contract_id: int, extra_id: int, document_id: int
) -> tuple[ClientSettlementExtraDocument, Path]:
    document = await db.get(ClientSettlementExtraDocument, document_id)
    extra = await db.get(ClientSettlementExtra, extra_id)
    if (
        document is None
        or extra is None
        or document.extra_id != extra_id
        or extra.contract_id != contract_id
    ):
        raise ExtraError("Nie ma takiego pliku.", status=404)
    try:
        return document, documents_store.path_for(document.file_path)
    except FileNotFoundError:
        raise ExtraError("Plik nie jest dostępny na dysku.", status=404) from None


# ── Odczyt ───────────────────────────────────────────────────────────────────


def as_dict(
    extra: ClientSettlementExtra,
    documents: list[ClientSettlementExtraDocument],
    *,
    amounts: bool,
    names: Optional[dict[int, str]] = None,
) -> dict[str, Any]:
    names = names or {}
    return {
        "id": extra.id,
        "contract_id": extra.contract_id,
        "month": extra.period_month,
        "kind": extra.kind,
        "kind_label": KIND_LABELS.get(extra.kind, extra.kind),
        "amount": f"{Decimal(extra.amount):.2f}" if amounts else None,
        "description": extra.description,
        "status": extra.status,
        "status_label": STATUS_LABELS.get(extra.status, extra.status),
        "source": extra.source,
        "source_label": SOURCE_LABELS.get(extra.source, extra.source),
        "reported_by": names.get(extra.created_by) if extra.created_by else None,
        "decided_by": names.get(extra.decided_by) if extra.decided_by else None,
        "decided_at": extra.decided_at.isoformat() if extra.decided_at else None,
        "decision_note": extra.decision_note,
        "bill_to_client": extra.bill_to_client,
        "bo_card_id": extra.bo_card_id,
        "counts_on_invoice": counts_on_invoice(extra),
        "created_at": extra.created_at.isoformat() if extra.created_at else None,
        "documents": [
            {
                "id": d.id,
                "file_name": d.file_name,
                "mime": d.mime,
                "channel": d.channel,
                "received_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in documents
        ],
    }


def pln(value: Decimal) -> str:
    text = f"{Decimal(value):,.2f}".replace(",", " ").replace(".", ",")
    return f"{text} zł"


async def block(
    db: AsyncSession,
    contract_id: int,
    month: str,
    *,
    amounts: bool,
    items: Optional[list[ClientSettlementExtra]] = None,
) -> dict[str, Any]:
    """Blok „Dodatki” karty osoby u Finansów: lista ze stanem, plikami i sumy."""

    from app.services.back_office.board import user_names  # noqa: PLC0415

    if items is None:
        items = (await for_contracts(db, [contract_id], month)).get(contract_id, [])
    docs = await documents_for(db, [e.id for e in items])
    names = await user_names(
        db, [e.created_by for e in items] + [e.decided_by for e in items]
    )
    sums = totals(items)
    return {
        "items": [
            as_dict(e, docs.get(e.id, []), amounts=amounts, names=names) for e in items
        ],
        "approved_total": f"{sums.approved:.2f}" if amounts else None,
        "pending_total": f"{sums.pending_total:.2f}" if amounts else None,
        "pending_count": len(sums.pending),
        "kinds": [{"key": k, "label": KIND_LABELS[k]} for k in STAFF_KINDS],
    }
