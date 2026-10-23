"""Rozliczenie zatwierdzonych wydatków (etap 3 zgód, 0486, decyzje Artura 20.10.2026).

Zgoda na wydatek po zatwierdzeniu dostaje rozliczenie (``on_approved``):

* wydatek raz — ``open`` (czeka na zakup i dokument) → ``documented``
  (przy zgodzie jest faktura albo paragon) → ``settled`` (Finanse kliknęły
  „Rozliczone”); bez dokumentu przez 30 dni — ``expired``,
* subskrypcja i inny wydatek cykliczny — ``active`` w rejestrze (każda
  faktura rozliczana osobno) → ``ended``; roczna ma ``renews_on`` i pytanie
  do opiekuna 30 dni przed odnowieniem,
* premia — bez rozliczenia (jest w Płacach).

Dokumenty (``approval_documents``): osoba wgrywa fakturę albo paragon (odczyt
kwoty i sprzedawcy przez AI jako podpowiedź), a faktura kosztowa z KSeF od
sprzedawcy znanego ze zgody przypina się sama (``match_document``). Faktura
wyższa od zgody o więcej niż 10% czeka na dopłatę: jedno „Poproś o dopłatę”
(autor albo Finanse), decyduje zatwierdzający jednym przyciskiem. Nikt nie
rozlicza własnego wydatku. Prezent dla klienta trafia do Historii zdarzeń
klienta, delegacja — do obecności autora jako ``business_trip``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import and_, exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today, local_now
from app.models.client import Client
from app.models.hr_approval import (
    ApprovalDocument,
    ApprovalFixedCostSeller,
    ApprovalRequest,
)
from app.models.hr_profile import EmployeeProfile
from app.models.notification import NotificationType
from app.models.user import User, UserRole
from app.services.hr import audit, white_list
from app.services.hr import calendar as work_calendar
from app.services.hr.approvals import reader, store
from app.services.hr.approvals import service as approvals
from app.services.hr.notify import notify_each
from app.services.hr_approval_settlement_schema import (
    ATTACHED_STATUSES,
    EXPIRY_DAYS,
    INVOICE_NUMBER_MAX_LENGTH,
    MAX_DOCUMENTS_PER_REQUEST,
    NOTE_MAX_LENGTH,
    OPEN_SETTLEMENT_STATUSES,
    RENEWAL_NOTICE_DAYS,
    SELLER_NAME_MAX_LENGTH,
    TOPUP_TOLERANCE_PERCENT,
)

logger = logging.getLogger(__name__)

_CENT = Decimal("0.01")
_TOLERANCE = Decimal(100 + TOPUP_TOLERANCE_PERCENT) / Decimal(100)
_AMOUNT_LIMIT = Decimal("10000000")
#: Delegacja dłuższa niż tyle dni nie trafia do obecności (pomyłka w datach).
MAX_TRIP_DAYS = 62
#: Faktura KSeF od sprzedawcy ze zgody wiąże się, gdy wystawiona nie wcześniej niż tyle dni przed prośbą.
MATCH_LOOKBACK_DAYS = 30
CORRECTION_TYPES = ("Kor", "KorZal", "KorRoz")
#: Dzienny przebieg (wygasanie, odnowienia) nie wcześniej niż o tej godzinie — dzwonki nie w nocy.
DAILY_FROM_HOUR = 8

STATUS_LABELS: dict[str, str] = {
    "open": "czeka na fakturę",
    "documented": "do rozliczenia",
    "settled": "rozliczona",
    "expired": "wygasła",
    "active": "w rejestrze",
    "ended": "zakończona",
}


class SettlementError(approvals.ApprovalError):
    """Błąd rozliczenia (422); podklasy jak w zgodach: 403, 404, 409."""


# ── porównanie z kwotą zgody ───────────────────────────────────────────────


def approved_amount(request: ApprovalRequest) -> Decimal:
    return request.decided_amount or request.amount


def document_amount(doc: ApprovalDocument, basis: str) -> Optional[Decimal]:
    """Kwota dokumentu w podstawie zgody (netto albo brutto)."""

    if basis == "net":
        if doc.net_amount is not None:
            return doc.net_amount
        if doc.gross_amount is not None and doc.vat_amount is not None:
            return doc.gross_amount - doc.vat_amount
        return None
    return doc.gross_amount


@dataclass(frozen=True)
class Comparison:
    """``fits`` / ``over`` (ponad 10%, bez zatwierdzonej dopłaty) / ``unknown``."""

    status: str
    approved: Decimal
    documented: Optional[Decimal]
    limit: Decimal
    excess: Optional[Decimal]
    percent: Optional[int]

    def as_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "approved": str(self.approved),
            "documented": str(self.documented) if self.documented is not None else None,
            "limit": str(self.limit),
            "excess": str(self.excess) if self.excess is not None else None,
            "percent": self.percent,
        }


def compare(
    request: ApprovalRequest,
    docs: list[ApprovalDocument],
    *,
    doc: Optional[ApprovalDocument] = None,
) -> Comparison:
    """Wydatek raz: suma dokumentów zgody; cykliczny: jeden dokument (``doc``).

    Granica = kwota zgody + 10% + zatwierdzone dopłaty. Dokument w innej
    walucie albo bez kwoty = ``unknown`` (porównuje człowiek).
    """

    approved = approved_amount(request)
    scope = [d for d in docs if d.status in ATTACHED_STATUSES]
    if request.recurrence != "once":
        scope = [doc] if doc is not None else []
    topups = sum(
        (
            d.topup_amount
            for d in scope
            if d.topup_status == "approved" and d.topup_amount
        ),
        Decimal(0),
    )
    limit = (approved * _TOLERANCE).quantize(_CENT) + topups
    amounts = [document_amount(d, request.amount_basis) for d in scope]
    if (
        not scope
        or any(a is None for a in amounts)
        or any(d.currency != request.currency for d in scope)
    ):
        return Comparison("unknown", approved, None, limit, None, None)
    documented = sum(amounts, Decimal(0))  # type: ignore[arg-type]
    if documented <= limit:
        return Comparison("fits", approved, documented, limit, None, None)
    excess = documented - approved - topups
    percent = int(((documented - approved) / approved * 100).to_integral_value())
    return Comparison("over", approved, documented, limit, excess, percent)


# ── ustawienie rozliczenia po zatwierdzeniu ─────────────────────────────────


def first_renewal(start: Optional[date], today: date) -> date:
    """Najbliższa rocznica startu po dziś (bez startu — rok od dziś)."""

    anchor = start or today
    renewal = _add_year(anchor)
    while renewal <= today:
        renewal = _add_year(renewal)
    return renewal


def _add_year(day: date) -> date:
    try:
        return day.replace(year=day.year + 1)
    except ValueError:  # 29.02
        return day.replace(year=day.year + 1, day=28)


def expiry(request: ApprovalRequest) -> Optional[date]:
    """Termin wygaśnięcia do pokazania — zgoda „raz” go nie ma (22.10.2026),
    choć zgody sprzed decyzji niosą jeszcze datę z backfillu."""

    return None if request.recurrence == "once" else request.expires_on


async def on_approved(db: AsyncSession, request: ApprovalRequest, actor: User) -> None:
    """Rozliczenie, Historia klienta i obecność po zatwierdzeniu wydatku."""

    if request.kind == "bonus" or request.status != "approved":
        return
    today = business_today()
    request.settlement_status = "open" if request.recurrence == "once" else "active"
    # Wydatek jednorazowy bez dokumentu nie wygasa (decyzja Artura 22.10.2026):
    # delegacja czy szkolenie za dwa miesiące rozliczają się po wydarzeniu.
    # Cykliczny ze startem w przyszłości (subskrypcja od stycznia) liczy 30 dni
    # od startu — inaczej wygasałby, zanim przyjdzie pierwsza faktura.
    if request.recurrence == "once":
        request.expires_on = None
    else:
        start = request.starts_on or today
        request.expires_on = max(today, start) + timedelta(days=EXPIRY_DAYS)
    if request.recurrence == "yearly":
        request.renews_on = first_renewal(request.starts_on, today)
    await db.flush()
    if request.kind == "gift" and request.client_id:
        await _record_gift(db, request, actor)
    if request.kind == "trip" and request.starts_on:
        await _record_trip(db, request, actor)
    if request.seller_nip:
        await rematch_seller(db, request.seller_nip)


async def _record_gift(db: AsyncSession, request: ApprovalRequest, actor: User) -> None:
    from app.services.critical_events import record_executed  # noqa: PLC0415

    await record_executed(
        db,
        actor=actor,
        event_type="client.gift",
        entity_type="client",
        entity_id=request.client_id,
        entity_label=request.title,
        client_id=request.client_id,
        details={
            "approval_request_id": request.id,
            "amount": str(approved_amount(request)),
            "currency": request.currency,
            "requester_user_id": request.requester_user_id,
        },
    )


async def _record_trip(db: AsyncSession, request: ApprovalRequest, actor: User) -> None:
    """Dni robocze delegacji jako ``business_trip`` w obecności autora."""

    from app.services.hr.time_entries import TimeError  # noqa: PLC0415
    from app.services.hr.time_month import set_attendance  # noqa: PLC0415

    start = request.starts_on
    end = request.ends_on or start
    if start is None or end < start or (end - start).days > MAX_TRIP_DAYS:
        return
    profile = await db.scalar(
        select(EmployeeProfile).where(
            EmployeeProfile.user_id == request.requester_user_id
        )
    )
    if profile is None:
        return
    calendar = await work_calendar.load_calendar(db, start, end)
    marked = 0
    for day in calendar.working_days(start, end):
        try:
            async with db.begin_nested():
                await set_attendance(
                    db,
                    subject=profile,
                    actor_user_id=actor.id,
                    day=day,
                    status="business_trip",
                    location=None,
                    note=None,
                )
            marked += 1
        except TimeError:
            # Dzień urlopu zostaje urlopem — delegacja go nie nadpisuje.
            continue
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=request.requester_user_id,
        entity_type="approval_request",
        entity_id=request.id,
        action="approval_trip_attendance",
        details={"days": marked},
    )


# ── odczyt i uprawnienia ────────────────────────────────────────────────────


async def documents_of(
    db: AsyncSession, request_ids: list[int]
) -> dict[int, list[ApprovalDocument]]:
    out: dict[int, list[ApprovalDocument]] = {rid: [] for rid in request_ids}
    if not request_ids:
        return out
    rows = await db.scalars(
        select(ApprovalDocument)
        .where(ApprovalDocument.approval_request_id.in_(request_ids))
        .order_by(ApprovalDocument.issue_date.nulls_last(), ApprovalDocument.id)
    )
    for doc in rows:
        out.setdefault(int(doc.approval_request_id), []).append(doc)
    return out


def is_finance(user: User) -> bool:
    from app.services.action_permissions import (  # noqa: PLC0415
        ProductAction,
        has_permission,
    )

    return user.has_role(UserRole.admin) or has_permission(
        user, ProductAction.finance_module
    )


async def _visible(
    db: AsyncSession, actor: User, request: Optional[ApprovalRequest]
) -> bool:
    """Strony zgody jak w zgodach; Finanse — każdy rozliczany wydatek (premii nie)."""

    if request is None:
        return False
    if await approvals.can_view(db, actor, request):
        return True
    return is_finance(actor) and request.settlement_status is not None


async def visible_request(
    db: AsyncSession, actor: User, request_id: int
) -> ApprovalRequest:
    request = await db.get(ApprovalRequest, request_id)
    if not await _visible(db, actor, request):
        raise approvals.ApprovalNotFound(approvals.NOT_FOUND)
    return request


async def _request_for(
    db: AsyncSession, actor: User, request_id: int
) -> ApprovalRequest:
    request = await db.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not await _visible(db, actor, request):
        raise approvals.ApprovalNotFound(approvals.NOT_FOUND)
    return request


def _assert_can_add(actor: User, request: ApprovalRequest) -> None:
    if actor.id != request.requester_user_id and not is_finance(actor):
        raise approvals.ApprovalForbidden(
            "Fakturę albo paragon dołącza osoba, która prosiła o zgodę, albo Finanse."
        )
    _assert_open(request)


def _assert_open(request: ApprovalRequest) -> None:
    if request.settlement_status in OPEN_SETTLEMENT_STATUSES:
        return
    if request.settlement_status == "expired":
        raise approvals.ApprovalConflict(
            "Zgoda wygasła — 30 dni bez zakupu. Poproś o nową zgodę."
        )
    if request.settlement_status in ("settled", "ended"):
        raise approvals.ApprovalConflict(
            "Ta zgoda jest już rozliczona albo zakończona."
        )
    raise approvals.ApprovalConflict(
        "Fakturę dołącza się do zatwierdzonej zgody na wydatek."
    )


async def _document_for(
    db: AsyncSession, request: ApprovalRequest, document_id: int
) -> ApprovalDocument:
    doc = await db.scalar(
        select(ApprovalDocument)
        .where(
            ApprovalDocument.id == document_id,
            ApprovalDocument.approval_request_id == request.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if doc is None:
        raise approvals.ApprovalNotFound("Nie ma takiego dokumentu przy tej zgodzie.")
    return doc


async def _attached(
    db: AsyncSession, request: ApprovalRequest
) -> list[ApprovalDocument]:
    return (await documents_of(db, [request.id]))[request.id]


def _mark_documented(request: ApprovalRequest, docs: list[ApprovalDocument]) -> None:
    if request.recurrence != "once" or request.settlement_status not in (
        "open",
        "documented",
    ):
        return
    attached = [d for d in docs if d.status in ATTACHED_STATUSES]
    request.settlement_status = "documented" if attached else "open"


def _audit_doc(
    db: AsyncSession,
    doc: ApprovalDocument,
    *,
    actor_id: Optional[int],
    action: str,
    **extra: Any,
) -> None:
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=None,
        entity_type="approval_document",
        entity_id=doc.id,
        action=action,
        details={
            "approval_request_id": doc.approval_request_id,
            "source": doc.source,
            "status": doc.status,
            **extra,
        },
    )


# ── dokument od osoby (faktura albo paragon) ────────────────────────────────


async def attach_upload(
    db: AsyncSession,
    actor: User,
    request_id: int,
    *,
    content: bytes,
    file_name: str,
) -> ApprovalDocument:
    """Plik do zgody + odczyt AI; faktura już pobrana z KSeF łączy się z plikiem."""

    from app.models.ai_feature import AIFeatureKey  # noqa: PLC0415
    from app.services.ai_quota import AIQuotaExceeded, ai_feature  # noqa: PLC0415

    request = await _request_for(db, actor, request_id)
    _assert_can_add(actor, request)
    try:
        mime, digest = store.check(content)
    except store.FileRejected as exc:
        raise SettlementError(str(exc)) from None
    docs = await _attached(db, request)
    if len(docs) >= MAX_DOCUMENTS_PER_REQUEST:
        raise approvals.ApprovalConflict(
            f"Zgoda ma już {MAX_DOCUMENTS_PER_REQUEST} dokumentów."
        )
    if any(d.sha256 == digest for d in docs):
        raise approvals.ApprovalConflict("Ten plik jest już przy tej zgodzie.")

    try:
        async with ai_feature(db, AIFeatureKey.expense_document_read, user_id=actor.id):
            read = await reader.read_document(content, mime)
    except AIQuotaExceeded:
        read = reader.ReadResult("skipped")
    fields = read.fields
    relative = store.save(request.id, content, mime=mime, digest=digest)
    name = (file_name or "dokument").strip()[:255] or "dokument"
    twin = await _ksef_twin(db, fields.get("seller_nip"), fields.get("invoice_number"))
    if twin is not None:
        doc = twin
        doc.status = "pinned"
        doc.approval_request_id = request.id
        doc.match_reason = "upload"
    else:
        doc = ApprovalDocument(
            source="upload",
            status="pinned",
            approval_request_id=request.id,
            match_reason="upload",
            doc_type=fields.get("doc_type") or "invoice",
            seller_nip=fields.get("seller_nip"),
            seller_name=fields.get("seller_name"),
            invoice_number=fields.get("invoice_number"),
            issue_date=_iso_date(fields.get("issue_date")),
            currency=fields.get("currency") or request.currency,
            net_amount=_decimal(fields.get("net_amount")),
            vat_amount=_decimal(fields.get("vat_amount")),
            gross_amount=_decimal(fields.get("gross_amount")),
        )
        db.add(doc)
    doc.file_path = relative
    doc.file_name = name
    doc.mime = mime
    doc.size_bytes = len(content)
    doc.sha256 = digest
    doc.read_status = read.status
    doc.read_result = read.as_json()
    doc.added_by = actor.id
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        raise approvals.ApprovalConflict(
            "Ten plik jest już przy tej zgodzie."
        ) from None
    if not request.seller_nip and doc.seller_nip:
        request.seller_nip = doc.seller_nip
    _mark_documented(request, [*docs, doc])
    await db.flush()
    _audit_doc(
        db,
        doc,
        actor_id=actor.id,
        action="approval_document_attached",
        read_status=read.status,
        ksef=doc.ksef_number is not None,
    )
    return doc


async def _ksef_twin(
    db: AsyncSession, seller_nip: Optional[str], invoice_number: Optional[str]
) -> Optional[ApprovalDocument]:
    """Ta sama faktura pobrana już z KSeF (kolejka, stały koszt albo zamknięta)."""

    if not seller_nip or not invoice_number:
        return None
    return await db.scalar(
        select(ApprovalDocument)
        .where(
            ApprovalDocument.source == "ksef",
            ApprovalDocument.approval_request_id.is_(None),
            ApprovalDocument.seller_nip == seller_nip,
            func.lower(ApprovalDocument.invoice_number) == invoice_number.lower(),
        )
        .order_by(ApprovalDocument.id)
        .limit(1)
        .with_for_update()
    )


def _iso_date(raw: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(raw)) if raw else None
    except ValueError:
        return None


def _decimal(raw: Any) -> Optional[Decimal]:
    if raw is None or raw == "":
        return None
    try:
        value = Decimal(str(raw).replace(",", ".").replace(" ", "")).quantize(_CENT)
    except (InvalidOperation, ValueError):
        raise SettlementError("Kwota musi być liczbą, np. 1150,00.") from None
    if value < 0 or value > _AMOUNT_LIMIT:
        raise SettlementError("Kwota jest poza zakresem.")
    return value


@dataclass(frozen=True)
class DocumentFields:
    doc_type: Optional[str] = None
    seller_name: Optional[str] = None
    seller_nip: Optional[str] = None
    invoice_number: Optional[str] = None
    issue_date: Optional[date] = None
    currency: Optional[str] = None
    net_amount: Optional[str] = None
    vat_amount: Optional[str] = None
    gross_amount: Optional[str] = None


_AMOUNT_FIELDS = ("currency", "net_amount", "vat_amount", "gross_amount")
#: Z faktury KSeF wiążą kwoty i NIP sprzedawcy (klucz dopasowania; CHECK origin).
_KSEF_FIXED_FIELDS = (*_AMOUNT_FIELDS, "seller_nip")


async def update_document(
    db: AsyncSession,
    actor: User,
    request_id: int,
    document_id: int,
    fields: DocumentFields,
    *,
    provided: set[str],
) -> ApprovalDocument:
    """Poprawka odczytu (autor do rozliczenia, Finanse). Kwot z KSeF się nie zmienia."""

    request = await _request_for(db, actor, request_id)
    doc = await _document_for(db, request, document_id)
    finance = is_finance(actor)
    if not finance and actor.id != doc.added_by:
        raise approvals.ApprovalForbidden(
            "Dane dokumentu poprawia osoba, która go dodała, albo Finanse."
        )
    if doc.status == "settled":
        raise approvals.ApprovalConflict("Dokument jest już rozliczony.")
    if doc.topup_status == "pending":
        raise approvals.ApprovalConflict(
            "Dopłata czeka na decyzję — kwot teraz nie zmienisz."
        )
    if doc.source == "ksef" and provided & set(_KSEF_FIXED_FIELDS):
        raise approvals.ApprovalConflict(
            "Kwoty i NIP sprzedawcy z faktury KSeF są wiążące — nie zmienisz ich."
        )
    if "doc_type" in provided:
        doc.doc_type = "receipt" if fields.doc_type == "receipt" else "invoice"
    if "seller_name" in provided:
        doc.seller_name = _clean_text(fields.seller_name, SELLER_NAME_MAX_LENGTH)
    if "seller_nip" in provided:
        doc.seller_nip = clean_nip(fields.seller_nip)
    if "invoice_number" in provided:
        doc.invoice_number = _clean_text(
            fields.invoice_number, INVOICE_NUMBER_MAX_LENGTH
        )
    if "issue_date" in provided:
        doc.issue_date = fields.issue_date
    if "currency" in provided:
        currency = (fields.currency or "").strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise SettlementError("Waluta to trzy litery, np. PLN.")
        doc.currency = currency
    for name in ("net_amount", "vat_amount", "gross_amount"):
        if name in provided:
            setattr(doc, name, _decimal(getattr(fields, name)))
    if doc.topup_status == "rejected" and provided & set(_AMOUNT_FIELDS):
        # Nowa kwota = nowe porównanie; odrzucona dopłata dotyczyła starej.
        _clear_topup(doc)
    if not request.seller_nip and doc.seller_nip:
        request.seller_nip = doc.seller_nip
    await db.flush()
    _audit_doc(
        db,
        doc,
        actor_id=actor.id,
        action="approval_document_updated",
        fields=sorted(provided),
    )
    return doc


def _clean_text(raw: Optional[str], limit: int) -> Optional[str]:
    text = " ".join((raw or "").split())
    if len(text) > limit:
        raise SettlementError(f"Najwyżej {limit} znaków.")
    return text or None


def clean_nip(raw: Optional[str]) -> Optional[str]:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return white_list.clean_nip(text)
    except white_list.WhiteListError:
        raise SettlementError(
            "NIP sprzedawcy ma 10 cyfr z poprawną sumą kontrolną."
        ) from None


def _clear_topup(doc: ApprovalDocument) -> None:
    doc.topup_status = None
    doc.topup_amount = None
    doc.topup_requested_by = None
    doc.topup_requested_at = None
    doc.topup_decided_by = None
    doc.topup_decided_at = None
    doc.topup_note = None


async def remove_document(
    db: AsyncSession, actor: User, request_id: int, document_id: int
) -> Optional[str]:
    """Usuwa wgrany plik (pomyłka); faktura z KSeF wraca do kolejki Finansów.

    Zwraca ścieżkę pliku do skasowania PO commicie (``None`` = nic do skasowania).
    """

    request = await _request_for(db, actor, request_id)
    doc = await _document_for(db, request, document_id)
    if doc.status == "settled":
        raise approvals.ApprovalConflict("Dokument jest już rozliczony.")
    if not is_finance(actor) and actor.id != doc.added_by:
        raise approvals.ApprovalForbidden(
            "Dokument usuwa osoba, która go dodała, albo Finanse."
        )
    if doc.topup_status == "pending":
        raise approvals.ApprovalConflict("Dopłata czeka na decyzję — najpierw decyzja.")
    path = doc.file_path
    if doc.source == "ksef":
        if doc.file_path is None and not is_finance(actor):
            raise approvals.ApprovalForbidden("Fakturę z KSeF odpinają Finanse.")
        doc.status = "unmatched"
        doc.approval_request_id = None
        doc.match_reason = "unpinned"
        doc.file_path = doc.file_name = doc.mime = doc.sha256 = None
        doc.size_bytes = None
        _clear_topup(doc)
        _audit_doc(db, doc, actor_id=actor.id, action="approval_document_unpinned")
    else:
        _audit_doc(db, doc, actor_id=actor.id, action="approval_document_removed")
        await db.delete(doc)
    await db.flush()
    _mark_documented(request, await _attached(db, request))
    await db.flush()
    still_used = path and await db.scalar(
        select(ApprovalDocument.id).where(ApprovalDocument.file_path == path).limit(1)
    )
    return None if still_used else path


# ── dopłata ─────────────────────────────────────────────────────────────────


async def request_topup(
    db: AsyncSession, actor: User, request_id: int, document_id: int
) -> ApprovalDocument:
    """„Poproś o dopłatę” — faktura ponad zgodę o więcej niż 10%."""

    request = await _request_for(db, actor, request_id)
    doc = await _document_for(db, request, document_id)
    if actor.id != request.requester_user_id and not is_finance(actor):
        raise approvals.ApprovalForbidden("O dopłatę prosi autor zgody albo Finanse.")
    if doc.status != "pinned":
        raise approvals.ApprovalConflict("Dokument jest już rozliczony.")
    if doc.topup_status is not None:
        raise approvals.ApprovalConflict("Prośba o dopłatę do tego dokumentu już była.")
    comparison = compare(request, await _attached(db, request), doc=doc)
    if comparison.status != "over" or comparison.excess is None:
        raise approvals.ApprovalConflict(
            "Faktura mieści się w zgodzie — dopłata niepotrzebna."
        )
    doc.topup_status = "pending"
    doc.topup_amount = comparison.excess
    doc.topup_requested_by = actor.id
    doc.topup_requested_at = local_now()
    await db.flush()
    _audit_doc(
        db,
        doc,
        actor_id=actor.id,
        action="approval_topup_requested",
        amount=str(comparison.excess),
    )
    finals = await approvals.finals_for_request(db, request)
    await notify_each(
        db,
        [uid for uid in finals if uid != actor.id],
        title=f"Dopłata do zgody: {request.title}",
        message=(
            f"Faktura {approvals.money(comparison.documented, request.currency)} "
            f"przy zgodzie {approvals.money(comparison.approved, request.currency)} "
            f"(+{comparison.percent}%). Dopłata {approvals.money(comparison.excess, request.currency)}."
        ),
        ntype=NotificationType.hr_approval_topup_requested,
        link=approvals.request_link(request.id),
        related_entity_type="approval_request",
        related_entity_id=request.id,
        log_tag="approvals",
        fresh=True,
    )
    return doc


async def decide_topup(
    db: AsyncSession,
    actor: User,
    request_id: int,
    document_id: int,
    *,
    action: str,
    note: Optional[str],
) -> ApprovalDocument:
    """Zatwierdzający: „Zatwierdź dopłatę” / „Odrzuć” (z uwagą)."""

    if action not in ("approve", "reject"):
        raise SettlementError("Nieznana decyzja.")
    request = await _request_for(db, actor, request_id)
    doc = await _document_for(db, request, document_id)
    finals = await approvals.finals_for_request(db, request)
    if actor.id not in finals or actor.id == request.requester_user_id:
        raise approvals.ApprovalForbidden("O dopłacie decyduje zatwierdzający.")
    text = _note(note, required=action == "reject")
    result = await db.execute(
        update(ApprovalDocument)
        .where(
            ApprovalDocument.id == doc.id, ApprovalDocument.topup_status == "pending"
        )
        .values(
            topup_status="approved" if action == "approve" else "rejected",
            topup_decided_by=actor.id,
            topup_decided_at=local_now(),
            topup_note=text,
            updated_at=func.now(),
        )
        .returning(ApprovalDocument.id)
    )
    if result.scalar_one_or_none() is None:
        raise approvals.ApprovalConflict("Ta dopłata jest już rozpatrzona.")
    await db.refresh(doc)
    _audit_doc(db, doc, actor_id=actor.id, action=f"approval_topup_{doc.topup_status}")
    verdict = "zatwierdzona" if action == "approve" else "odrzucona"
    await notify_each(
        db,
        [request.requester_user_id],
        title=f"Dopłata {verdict}: {request.title}",
        message=actor.name or "",
        ntype=NotificationType.hr_approval_decided,
        link=approvals.my_request_link(request.id),
        related_entity_type="approval_request",
        related_entity_id=request.id,
        log_tag="approvals",
        fresh=True,
    )
    return doc


def _note(note: Optional[str], *, required: bool) -> Optional[str]:
    text = (note or "").strip()
    if required and len(text) < 3:
        raise SettlementError("Dopisz krótką uwagę (co najmniej 3 znaki).")
    if len(text) > NOTE_MAX_LENGTH:
        raise SettlementError(f"Uwaga może mieć najwyżej {NOTE_MAX_LENGTH} znaków.")
    return text or None


async def pending_topups(
    db: AsyncSession, user: User
) -> list[tuple[ApprovalRequest, ApprovalDocument]]:
    """Dopłaty czekające na decyzję tej osoby (zatwierdzający, bez własnych)."""

    rows = (
        await db.execute(
            select(ApprovalRequest, ApprovalDocument)
            .join(
                ApprovalDocument,
                ApprovalDocument.approval_request_id == ApprovalRequest.id,
            )
            .where(ApprovalDocument.topup_status == "pending")
            .order_by(ApprovalDocument.topup_requested_at)
        )
    ).all()
    out = []
    for request, doc in rows:
        if user.id == request.requester_user_id:
            continue
        if user.id in await approvals.finals_for_request(db, request):
            out.append((request, doc))
    return out


# ── Finanse: rozliczenie, przypięcie, kolejka ───────────────────────────────


async def _finance_document(db: AsyncSession, document_id: int) -> ApprovalDocument:
    doc = await db.scalar(
        select(ApprovalDocument)
        .where(ApprovalDocument.id == document_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if doc is None:
        raise approvals.ApprovalNotFound("Nie ma takiego dokumentu.")
    return doc


async def _locked_request(db: AsyncSession, request_id: int) -> ApprovalRequest:
    request = await db.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if request is None:
        raise approvals.ApprovalNotFound(approvals.NOT_FOUND)
    return request


async def settle_document(
    db: AsyncSession, actor: User, document_id: int, *, note: Optional[str]
) -> ApprovalDocument:
    """„Rozliczone” (Finanse). Wydatek raz zamyka całą zgodę."""

    # Kolejność blokad jak w akcjach autora: najpierw zgoda, potem dokument.
    request_id = await db.scalar(
        select(ApprovalDocument.approval_request_id).where(
            ApprovalDocument.id == document_id
        )
    )
    if request_id is None:
        raise approvals.ApprovalConflict("Rozlicza się dokument przypięty do zgody.")
    request = await _locked_request(db, request_id)
    doc = await _finance_document(db, document_id)
    if doc.status != "pinned" or doc.approval_request_id != request.id:
        raise approvals.ApprovalConflict("Rozlicza się dokument przypięty do zgody.")
    if actor.id == request.requester_user_id:
        raise approvals.ApprovalForbidden(
            "Własnego wydatku nie rozliczasz — zrobi to druga osoba z Finansów."
        )
    docs = await _attached(db, request)
    scope = (
        [d for d in docs if d.status == "pinned"]
        if request.recurrence == "once"
        else [doc]
    )
    if any(d.gross_amount is None for d in scope):
        raise approvals.ApprovalConflict(
            "Dokument nie ma kwoty — uzupełnij ją przed rozliczeniem."
        )
    if any(d.topup_status == "pending" for d in scope):
        raise approvals.ApprovalConflict("Dopłata czeka na decyzję zatwierdzającego.")
    comparison = compare(request, docs, doc=doc)
    rejected = any(d.topup_status == "rejected" for d in scope)
    if comparison.status == "over" and not rejected:
        raise approvals.ApprovalConflict(
            f"Faktura jest wyższa od zgody o {comparison.percent}% — najpierw dopłata."
        )
    text = _note(note, required=comparison.status == "over")
    now = local_now()
    for item in scope:
        item.status = "settled"
        item.settled_by = actor.id
        item.settled_at = now
        item.settle_note = text
    if request.recurrence == "once":
        request.settlement_status = "settled"
        request.settled_by = actor.id
        request.settled_at = now
    await db.flush()
    for item in scope:
        _audit_doc(
            db,
            item,
            actor_id=actor.id,
            action="approval_document_settled",
            comparison=comparison.status,
        )
    return doc


async def pin_document(
    db: AsyncSession, actor: User, document_id: int, request_id: int
) -> ApprovalDocument:
    """„Przypnij do zgody” — faktura z kolejki do zatwierdzonej zgody (Finanse)."""

    doc = await _finance_document(db, document_id)
    if doc.status in ATTACHED_STATUSES:
        raise approvals.ApprovalConflict("Faktura jest już przy zgodzie.")
    request = await _locked_request(db, request_id)
    if request.status != "approved" or request.kind == "bonus":
        raise approvals.ApprovalConflict(
            "Fakturę przypina się do zatwierdzonej zgody na wydatek."
        )
    _assert_open(request)
    _pin(doc, request, reason="manual")
    await db.flush()
    _mark_documented(request, await _attached(db, request))
    await db.flush()
    _audit_doc(db, doc, actor_id=actor.id, action="approval_document_pinned")
    return doc


def _pin(doc: ApprovalDocument, request: ApprovalRequest, *, reason: str) -> None:
    doc.status = "pinned"
    doc.approval_request_id = request.id
    doc.match_reason = reason
    doc.closed_by = doc.closed_at = doc.close_note = None
    if not request.seller_nip and doc.seller_nip:
        # Kolejna faktura tego sprzedawcy (np. subskrypcji) przypnie się sama.
        request.seller_nip = doc.seller_nip


async def close_document(
    db: AsyncSession, actor: User, document_id: int, *, note: Optional[str]
) -> ApprovalDocument:
    """Faktura bez zgody zamknięta przez Finanse (z notatką: co to było)."""

    doc = await _finance_document(db, document_id)
    if doc.status not in ("unmatched", "fixed_cost"):
        raise approvals.ApprovalConflict(
            "Zamyka się fakturę z kolejki „Faktury bez zgody”."
        )
    doc.status = "dismissed"
    doc.closed_by = actor.id
    doc.closed_at = local_now()
    doc.close_note = _note(note, required=True)
    await db.flush()
    _audit_doc(db, doc, actor_id=actor.id, action="approval_document_closed")
    return doc


async def reopen_document(
    db: AsyncSession, actor: User, document_id: int
) -> ApprovalDocument:
    doc = await _finance_document(db, document_id)
    if doc.status != "dismissed":
        raise approvals.ApprovalConflict("Wraca do kolejki tylko zamknięta faktura.")
    doc.status = "unmatched"
    doc.closed_by = doc.closed_at = doc.close_note = None
    await db.flush()
    _audit_doc(db, doc, actor_id=actor.id, action="approval_document_reopened")
    return doc


async def add_fixed_seller(
    db: AsyncSession, actor: User, *, seller_nip: str, note: Optional[str]
) -> int:
    """Sprzedawca „stały koszt”: jego niedopasowane faktury znikają z kolejki."""

    nip = clean_nip(seller_nip)
    if nip is None:
        raise SettlementError("Podaj NIP sprzedawcy.")
    name = await db.scalar(
        select(ApprovalDocument.seller_name)
        .where(
            ApprovalDocument.seller_nip == nip,
            ApprovalDocument.seller_name.is_not(None),
        )
        .order_by(ApprovalDocument.id.desc())
        .limit(1)
    )
    existing = await db.get(ApprovalFixedCostSeller, nip)
    if existing is not None:
        raise approvals.ApprovalConflict(
            "Ten sprzedawca jest już na liście stałych kosztów."
        )
    db.add(
        ApprovalFixedCostSeller(
            seller_nip=nip,
            seller_name=name,
            note=_note(note, required=False),
            added_by=actor.id,
        )
    )
    result = await db.execute(
        update(ApprovalDocument)
        .where(
            ApprovalDocument.seller_nip == nip, ApprovalDocument.status == "unmatched"
        )
        .values(status="fixed_cost", match_reason="fixed_cost", updated_at=func.now())
        .returning(ApprovalDocument.id)
    )
    moved = len(result.all())
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="approval_fixed_cost_seller",
        entity_id=nip,
        action="approval_fixed_seller_added",
        details={"moved": moved},
    )
    return moved


async def remove_fixed_seller(db: AsyncSession, actor: User, seller_nip: str) -> int:
    nip = clean_nip(seller_nip)
    row = await db.get(ApprovalFixedCostSeller, nip) if nip else None
    if row is None:
        raise approvals.ApprovalNotFound(
            "Tego sprzedawcy nie ma na liście stałych kosztów."
        )
    await db.delete(row)
    result = await db.execute(
        update(ApprovalDocument)
        .where(
            ApprovalDocument.seller_nip == nip, ApprovalDocument.status == "fixed_cost"
        )
        .values(status="unmatched", match_reason="no_approval", updated_at=func.now())
        .returning(ApprovalDocument.id)
    )
    moved = len(result.all())
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="approval_fixed_cost_seller",
        entity_id=nip,
        action="approval_fixed_seller_removed",
        details={"moved": moved},
    )
    return moved


# ── automatyczne przypięcie faktury z KSeF ──────────────────────────────────


async def _candidates(db: AsyncSession, doc: ApprovalDocument) -> list[ApprovalRequest]:
    clauses = [
        ApprovalRequest.status == "approved",
        ApprovalRequest.kind != "bonus",
        ApprovalRequest.settlement_status.in_(OPEN_SETTLEMENT_STATUSES),
        ApprovalRequest.seller_nip == doc.seller_nip,
        ApprovalRequest.currency == doc.currency,
    ]
    if doc.issue_date is not None:
        # Prośba nie później niż 30 dni po wystawieniu faktury: kolejne faktury
        # subskrypcji się przypinają, starsze faktury sprzedawcy — nie.
        clauses.append(
            func.date(ApprovalRequest.submitted_at)
            <= doc.issue_date + timedelta(days=MATCH_LOOKBACK_DAYS)
        )
    return list(
        await db.scalars(
            select(ApprovalRequest)
            .where(and_(*clauses))
            .order_by(ApprovalRequest.decided_at, ApprovalRequest.id)
            .with_for_update()
        )
    )


async def match_document(db: AsyncSession, doc: ApprovalDocument) -> None:
    """Zgoda ze znanym sprzedawcą → ``pinned``; stały koszt; reszta do kolejki.

    Najpierw zgoda (dodatkowa usługa od „stałego” sprzedawcy też ma zgodę),
    potem lista stałych kosztów. Kilka zgód tego sprzedawcy — wygrywa jedyna,
    w której kwota się mieści; inaczej kolejka z powodem ``several``.
    """

    if doc.status in ATTACHED_STATUSES:
        return
    if doc.ksef_invoice_type in CORRECTION_TYPES:
        return await _queue(db, doc, "correction")
    candidates = await _candidates(db, doc) if doc.seller_nip else []
    chosen: Optional[ApprovalRequest] = None
    if len(candidates) == 1:
        chosen = candidates[0]
    elif candidates:
        attached = await documents_of(db, [c.id for c in candidates])
        fitting = [
            c
            for c in candidates
            if compare(
                c, [*attached[c.id], _as_pinned(doc, c)], doc=_as_pinned(doc, c)
            ).status
            == "fits"
        ]
        if len(fitting) == 1:
            chosen = fitting[0]
    if chosen is not None:
        _pin(doc, chosen, reason="auto")
        await db.flush()
        _mark_documented(chosen, await _attached(db, chosen))
        await db.flush()
        _audit_doc(db, doc, actor_id=None, action="approval_document_auto_pinned")
        return
    fixed = doc.seller_nip and await db.get(ApprovalFixedCostSeller, doc.seller_nip)
    if fixed:
        doc.status = "fixed_cost"
        doc.match_reason = "fixed_cost"
        await db.flush()
        return
    await _queue(db, doc, "several" if candidates else "no_approval")


def _as_pinned(doc: ApprovalDocument, request: ApprovalRequest) -> ApprovalDocument:
    """Kopia dokumentu „gdyby był przypięty” — do porównania przed decyzją."""

    return ApprovalDocument(
        status="pinned",
        approval_request_id=request.id,
        currency=doc.currency,
        net_amount=doc.net_amount,
        vat_amount=doc.vat_amount,
        gross_amount=doc.gross_amount,
    )


async def _queue(db: AsyncSession, doc: ApprovalDocument, reason: str) -> None:
    doc.status = "unmatched"
    doc.approval_request_id = None
    doc.match_reason = reason
    await db.flush()


async def rematch_seller(db: AsyncSession, seller_nip: str) -> int:
    """Faktury z kolejki od tego sprzedawcy próbują się przypiąć (nowa zgoda)."""

    docs = list(
        await db.scalars(
            select(ApprovalDocument)
            .where(
                ApprovalDocument.seller_nip == seller_nip,
                ApprovalDocument.status == "unmatched",
            )
            .order_by(ApprovalDocument.issue_date, ApprovalDocument.id)
            .with_for_update()
        )
    )
    pinned = 0
    for doc in docs:
        await match_document(db, doc)
        pinned += doc.status == "pinned"
    return pinned


# ── subskrypcje ─────────────────────────────────────────────────────────────


async def answer_renewal(
    db: AsyncSession, actor: User, request_id: int, *, keep: bool
) -> ApprovalRequest:
    """Opiekun (albo Finanse): „Dalej potrzebna” / „Wyłącz”."""

    request = await _request_for(db, actor, request_id)
    if actor.id != request.requester_user_id and not is_finance(actor):
        raise approvals.ApprovalForbidden(
            "O odnowieniu decyduje opiekun subskrypcji albo Finanse."
        )
    if request.settlement_status != "active":
        raise approvals.ApprovalConflict("Ta pozycja nie jest w rejestrze.")
    if keep:
        if request.renews_on is None:
            raise approvals.ApprovalConflict("Ta subskrypcja odnawia się co miesiąc.")
        request.renewal_confirmed_for = request.renews_on
        action = "subscription_renewal_confirmed"
    else:
        request.settlement_status = "ended"
        request.ended_on = business_today()
        request.ended_by = actor.id
        action = "subscription_ended"
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=request.requester_user_id,
        entity_type="approval_request",
        entity_id=request.id,
        action=action,
        details={
            "renews_on": request.renews_on.isoformat() if request.renews_on else None
        },
    )
    return request


async def renewal_reminders(db: AsyncSession, today: date) -> int:
    """Raz na odnowienie: dzwonek do opiekuna 30 dni przed; minione odnowienie
    bez odpowiedzi przesuwa się o rok (subskrypcja dalej płacona)."""

    rows = list(
        await db.scalars(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.settlement_status == "active",
                ApprovalRequest.renews_on.is_not(None),
                ApprovalRequest.renews_on
                <= today + timedelta(days=RENEWAL_NOTICE_DAYS),
            )
            .with_for_update(skip_locked=True)
        )
    )
    sent = 0
    for request in rows:
        while request.renews_on is not None and request.renews_on < today:
            request.renews_on = _add_year(request.renews_on)
        if request.renews_on > today + timedelta(days=RENEWAL_NOTICE_DAYS):
            continue
        if request.renewal_asked_for == request.renews_on:
            continue
        request.renewal_asked_for = request.renews_on
        sent += await notify_each(
            db,
            [request.requester_user_id],
            title=f"Odnowienie subskrypcji: {request.title}",
            message=(
                f"Odnawia się {request.renews_on:%d.%m.%Y} na rok "
                f"({approvals.amount_text(request)}). Czy jest dalej potrzebna?"
            ),
            ntype=NotificationType.hr_subscription_renewal,
            link=approvals.my_request_link(request.id),
            related_entity_type="approval_request",
            related_entity_id=request.id,
            log_tag="approvals",
        )
    await db.flush()
    return sent


async def upcoming_renewals(db: AsyncSession, today: date) -> list[ApprovalRequest]:
    """Roczne odnowienia w ciągu 30 dni — linia porannego skrótu."""

    return list(
        await db.scalars(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.settlement_status == "active",
                ApprovalRequest.renews_on.is_not(None),
                ApprovalRequest.renews_on >= today,
                ApprovalRequest.renews_on
                <= today + timedelta(days=RENEWAL_NOTICE_DAYS),
            )
            .order_by(ApprovalRequest.renews_on, ApprovalRequest.id)
        )
    )


# ── wygasanie ───────────────────────────────────────────────────────────────


async def expire_stale(db: AsyncSession, today: date) -> int:
    """Zgoda cykliczna bez żadnego dokumentu po 30 dniach → ``expired``.

    Zgoda „raz” nie wygasa (decyzja Artura 22.10.2026) — warunek na
    ``recurrence``, bo zgody sprzed decyzji mają ``expires_on`` z backfillu.
    """

    has_doc = exists().where(
        ApprovalDocument.approval_request_id == ApprovalRequest.id,
        ApprovalDocument.status.in_(ATTACHED_STATUSES),
    )
    result = await db.execute(
        update(ApprovalRequest)
        .where(
            ApprovalRequest.settlement_status.in_(("open", "active")),
            ApprovalRequest.recurrence != "once",
            ApprovalRequest.expires_on < today,
            ~has_doc,
        )
        .values(settlement_status="expired", updated_at=func.now())
        .returning(
            ApprovalRequest.id, ApprovalRequest.requester_user_id, ApprovalRequest.title
        )
    )
    rows = result.all()
    for request_id, requester_id, title in rows:
        audit.record(
            db,
            actor_user_id=None,
            subject_user_id=requester_id,
            entity_type="approval_request",
            entity_id=request_id,
            action="approval_expired",
            details={"days": EXPIRY_DAYS},
        )
        await notify_each(
            db,
            [requester_id],
            title=f"Zgoda wygasła: {title}",
            message=f"{EXPIRY_DAYS} dni bez faktury ani paragonu. Gdy zakup jest dalej potrzebny, poproś o nową zgodę.",
            ntype=NotificationType.hr_approval_decided,
            link=approvals.my_request_link(request_id),
            related_entity_type="approval_request",
            related_entity_id=request_id,
            log_tag="approvals",
        )
    await db.flush()
    return len(rows)


async def daily_job(db: AsyncSession) -> dict[str, int]:
    """Raz dziennie (pętla ``hr_lifecycle``): wygasanie i odnowienia subskrypcji."""

    from app.services.hr import job_runs  # noqa: PLC0415
    from app.services.hr.modules import HrModule, load_modules  # noqa: PLC0415

    if local_now().hour < DAILY_FROM_HOUR:
        return {}
    if not (await load_modules(db)).get(HrModule.approvals):
        return {}
    today = business_today()
    run_id = await job_runs.claim(
        db, "approval_settlement_daily", today.isoformat(), local_now()
    )
    if run_id is None:
        return {}
    try:
        counts = {
            "expired": await expire_stale(db, today),
            "renewals": await renewal_reminders(db, today),
        }
    except Exception:
        await db.rollback()
        logger.exception("approvals: dzienny przebieg rozliczeń przerwany")
        await job_runs.finish(db, run_id, status="failed", counts={}, error="internal")
        return {}
    await job_runs.finish(db, run_id, status="done", counts=counts, commit=False)
    await db.commit()
    return counts


async def client_name(db: AsyncSession, client_id: Optional[int]) -> Optional[str]:
    if client_id is None:
        return None
    row = await db.execute(
        select(func.coalesce(Client.display_name, Client.name)).where(
            Client.id == client_id
        )
    )
    return row.scalar_one_or_none()
