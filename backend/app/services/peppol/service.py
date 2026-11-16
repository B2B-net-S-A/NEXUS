"""E-faktury Peppol przy fakturach sprzedażowych z KSeF (plan Nordei N2).

Przepływ: Finanse wystawiają fakturę jak dziś w EBI24, faktura trafia do KSeF,
a pętla pobierania faktur sprzedażowych (``client_invoicing/sync.py``) zapisuje
ją w ``client_sales_invoices``. Gdy nabywca jest odbiorcą Peppol
(``settings.receivers``), ta sama pętla oddaje tutaj pobrany XML (``capture``)
— bez dodatkowego zapytania do KSeF. Faktury zapisane wcześniej doczytuje
``backfill_xml`` z resztki budżetu pobrań pętli sprzedaży (najwyżej
``BACKFILL_MAX`` na przebieg), więc limit pobrań Płac zostaje nietknięty.

Dalej ``prepare`` buduje UBL i sprawdza go regułami EN16931 i Peppol: błąd =
``invalid`` z powodem, poprawny = ``ready``. ``send`` (przycisk Finansów albo
automat po włączeniu ``auto_send``) buduje plik z PDF-em, waliduje go
jeszcze raz i oddaje dostawcy; ``refresh`` dociąga wynik doręczenia.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.models.client_einvoice import ClientSalesInvoiceEinvoice as Einvoice
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.user import User
from app.services.hr.ksef import fa
from app.services.hr.ksef.client import KsefApiError
from app.services.peppol import fa_reader, pdf, providers, settings, ubl, validation

logger = logging.getLogger(__name__)

BACKFILL_MAX = 10
MAX_XML_ATTEMPTS = 5
SEND_BATCH_MAX = 50
AUTO_SEND_MAX = 50
REFRESH_MAX = 200
HISTORY_MAX = 20
PREPARABLE = frozenset(
    {"waiting_xml", "waiting_receiver", "invalid", "ready", "skipped"}
)
SENT = frozenset({"sent", "delivered", "rejected"})
#: Po tym czasie „sending” bez wyniku można wysłać ponownie (ręcznie, po sprawdzeniu u dostawcy).
SENDING_STALE = timedelta(minutes=10)

STATUS_LABELS = {
    "waiting_xml": "Czeka na XML z KSeF",
    "waiting_receiver": "Brak adresu Peppol",
    "invalid": "Błąd walidacji",
    "ready": "Do wysłania",
    "sending": "Wysyłka niepewna",
    "sent": "Wysłana",
    "delivered": "Doręczona",
    "rejected": "Odrzucona",
    "skipped": "Bez e-faktury",
}


class EinvoiceError(ValueError):
    def __init__(self, message: str, status: int = 409) -> None:
        self.status = status
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: Optional[datetime]) -> Optional[str]:
    return moment.isoformat() if moment else None


def effective_status(row: Einvoice, mode: str) -> str:
    """Wysyłka testowa nie zamyka faktury w trybie produkcyjnym."""

    if mode == "production" and row.target == "test" and row.status in SENT:
        return "ready"
    return row.status


def _problem(code: str, text: str) -> dict[str, str]:
    return {"rule": code, "flag": "fatal", "text": text[:500], "location": ""}


def sender_id(doc: fa_reader.FaDocument) -> ubl.PeppolId:
    raw = (app_settings.PEPPOL_SENDER_ID or "").strip()
    return ubl.PeppolId.parse(raw or f"9945:PL{doc.seller.nip}")


@dataclass(frozen=True)
class Built:
    result: ubl.UblResult
    recipient: str
    findings: list[validation.Finding]


async def _build(
    row: Einvoice,
    invoice: ClientSalesInvoice,
    value: dict[str, Any],
    *,
    with_pdf: bool,
) -> Built:
    """UBL i wynik walidacji; ``ConversionError``/``NothingToSend``/``LookupError``."""

    if not row.fa_xml:
        raise LookupError("waiting_xml")
    receiver = settings.find_receiver(value, row.receiver_key)
    address = settings.address_for(receiver, value["mode"]) if receiver else None
    if not receiver or not address:
        raise LookupError("waiting_receiver")
    doc = fa_reader.read(row.fa_xml.encode("utf-8"))
    attachment = None
    if with_pdf:
        content = pdf.render(doc, ksef_number=invoice.ksef_number)
        attachment = ubl.Attachment(pdf.filename(doc.number), content)
    result = ubl.build(
        doc,
        sender=sender_id(doc),
        receiver=ubl.Receiver(
            ubl.PeppolId.parse(address),
            legal_id=receiver.get("legal_id"),
            legal_id_scheme=receiver.get("legal_id_scheme"),
        ),
        attachment=attachment,
    )
    findings = await validation.validate_async(result.xml)
    return Built(result=result, recipient=address, findings=findings)


async def prepare(
    db: AsyncSession, row: Einvoice, invoice: ClientSalesInvoice, value: dict[str, Any]
) -> None:
    """Stan przed wysyłką: brak XML-a, brak adresu, błąd, do wysłania, bez e-faktury."""

    if row.status not in PREPARABLE:
        return
    try:
        built = await _build(row, invoice, value, with_pdf=False)
    except LookupError as missing:
        row.status = str(missing.args[0])
        row.problems = []
        return
    except ubl.NothingToSend as exc:
        row.status, row.problems, row.document_type = (
            "skipped",
            [_problem("nothing_to_send", str(exc))],
            None,
        )
        return
    except ubl.ConversionError as exc:
        row.status, row.problems = "invalid", [_problem(exc.code, str(exc))]
        return
    except fa_reader.UnsupportedInvoice as exc:
        row.status = "invalid"
        row.problems = [
            _problem(
                exc.code, "Pozycje faktury bez kwot netto (faktura liczona od brutto)."
            )
        ]
        return
    except fa.InvoiceParseError as exc:
        row.status, row.problems = "invalid", [_problem(f"parse:{exc.code}", str(exc))]
        return
    except validation.ValidationUnavailable as exc:
        row.status, row.problems = "invalid", [_problem("validator", str(exc))]
        return
    row.document_type = built.result.document_type
    row.problems = [finding.as_dict() for finding in built.findings]
    row.status = "invalid" if validation.blocking(built.findings) else "ready"


# ── Zapis XML-a z pętli KSeF ─────────────────────────────────────────────────


def _match_key(invoice: ClientSalesInvoice) -> Optional[str]:
    return settings.receiver_key(invoice.buyer_foreign_id, invoice.buyer_nip)


def _in_scope(invoice: ClientSalesInvoice, value: dict[str, Any]) -> Optional[str]:
    key = _match_key(invoice)
    if settings.find_receiver(value, key) is None:
        return None
    if invoice.issue_date < date.fromisoformat(value["since"]):
        return None
    return key


async def capture(db: AsyncSession, invoice: ClientSalesInvoice, xml: bytes) -> bool:
    """XML świeżo pobranej faktury (pętla KSeF); ``True`` = to faktura z e-fakturą."""

    value = await settings.load(db)
    key = _in_scope(invoice, value)
    if key is None:
        return False
    row = await db.scalar(select(Einvoice).where(Einvoice.invoice_id == invoice.id))
    if row is None:
        row = Einvoice(
            invoice_id=invoice.id,
            receiver_key=key,
            status="waiting_xml",
            problems=[],
            history=[],
        )
        db.add(row)
    if not row.fa_xml:
        row.fa_xml = xml.decode("utf-8")
    await prepare(db, row, invoice, value)
    await db.flush()
    return True


async def scan(db: AsyncSession, value: Optional[dict[str, Any]] = None) -> int:
    """Wiersze dla faktur odbiorców Peppol zapisanych przed włączeniem (bez XML-a)."""

    value = value or await settings.load(db)
    keys = [entry["key"] for entry in value["receivers"]]
    if not keys:
        return 0
    pl_keys = [key[2:] for key in keys if key.startswith("PL")]
    since = date.fromisoformat(value["since"])
    invoices = list(
        await db.scalars(
            select(ClientSalesInvoice)
            .outerjoin(Einvoice, Einvoice.invoice_id == ClientSalesInvoice.id)
            .where(
                Einvoice.id.is_(None),
                ClientSalesInvoice.issue_date >= since,
                or_(
                    func.upper(ClientSalesInvoice.buyer_foreign_id).in_(keys),
                    and_(
                        ClientSalesInvoice.buyer_foreign_id.is_(None),
                        ClientSalesInvoice.buyer_nip.in_(pl_keys or [""]),
                    ),
                ),
            )
        )
    )
    for invoice in invoices:
        key = _match_key(invoice)
        if key:
            db.add(
                Einvoice(
                    invoice_id=invoice.id,
                    receiver_key=key,
                    status="waiting_xml",
                    problems=[],
                    history=[],
                )
            )
    await db.flush()
    return len(invoices)


async def backfill_xml(db: AsyncSession, source: Any, budget: int) -> tuple[int, int]:
    """Doczytuje XML z KSeF dla ``waiting_xml`` (najwyżej ``budget`` pobrań);
    zwraca (liczba pobrań, liczba zapisanych plików).

    Skrót pliku musi się zgadzać z ``client_sales_invoices.xml_sha256`` — inny
    plik pod tym numerem to błąd, nie e-faktura. Blokada 429 przerywa (wyjątek
    idzie do pętli, która zapisuje blokadę dla obu ścieżek KSeF)."""

    if budget <= 0:
        return 0, 0
    value = await settings.load(db)
    await scan(db, value)
    rows = list(
        await db.execute(
            select(Einvoice, ClientSalesInvoice)
            .join(ClientSalesInvoice, ClientSalesInvoice.id == Einvoice.invoice_id)
            .where(
                Einvoice.status == "waiting_xml",
                Einvoice.xml_attempts < MAX_XML_ATTEMPTS,
            )
            .order_by(ClientSalesInvoice.issue_date.desc(), Einvoice.id)
            .limit(min(budget, BACKFILL_MAX))
        )
    )
    loaded = attempted = 0
    for row, invoice in rows:
        attempted += 1
        row.xml_attempts = int(row.xml_attempts or 0) + 1
        try:
            xml = await source.download_invoice(invoice.ksef_number)
        except KsefApiError as exc:
            if exc.category == "rate_limited":
                await db.flush()
                raise
            logger.warning("[peppol] XML faktury %s: %s", invoice.id, exc.category)
            continue
        if hashlib.sha256(xml).hexdigest() != invoice.xml_sha256:
            row.status = "invalid"
            row.problems = [
                _problem(
                    "xml_hash",
                    "Plik z KSeF różni się od zapisanego przy pobraniu faktury.",
                )
            ]
            continue
        row.fa_xml = xml.decode("utf-8")
        await prepare(db, row, invoice, value)
        loaded += 1
    await db.flush()
    return attempted, loaded


# ── Wysyłka i statusy ────────────────────────────────────────────────────────


async def _claim(
    db: AsyncSession, einvoice_id: int, mode: str, *, manual: bool
) -> tuple[Optional[Einvoice], Optional[ClientSalesInvoice], str, str]:
    """Przejęcie wiersza do wysyłki: ``sending`` zapisane (commit) przed
    wywołaniem dostawcy. Blokada wiersza i świeży odczyt po jej uzyskaniu —
    drugie, równoległe „Wyślij” (albo automat) widzi już ``sending`` i odpuszcza.
    Zwraca (wiersz, faktura, poprzedni stan, numer faktury) albo powód odmowy
    w trzecim polu (wtedy bez wiersza)."""

    pair = (
        await db.execute(
            select(Einvoice, ClientSalesInvoice)
            .join(ClientSalesInvoice, ClientSalesInvoice.id == Einvoice.invoice_id)
            .where(Einvoice.id == einvoice_id)
            .with_for_update(of=Einvoice)
            .execution_options(populate_existing=True)
        )
    ).first()
    if pair is None:
        await db.rollback()
        return None, None, "Nie ma takiej e-faktury.", str(einvoice_id)
    row, invoice = pair
    number = invoice.invoice_number
    status = effective_status(row, mode)
    allowed = {"ready"} if not manual else {"ready", "rejected"}
    stale = (
        row.status == "sending"
        and row.updated_at is not None
        and _now() - row.updated_at > SENDING_STALE
    )
    if not (status in allowed or (manual and stale)):
        current = row.status
        await db.rollback()
        if current == "sending":
            return (
                None,
                None,
                "Wysyłka w toku albo bez pewnej odpowiedzi dostawcy — sprawdź u dostawcy, ponowna wysyłka po 10 minutach.",
                number,
            )
        return (
            None,
            None,
            f"Stan „{STATUS_LABELS.get(status, status)}” — nie do wysłania.",
            number,
        )
    previous = row.status
    row.status = "sending"
    await db.commit()
    return row, invoice, previous, number


def _record(row: Einvoice, entry: dict[str, Any]) -> None:
    row.history = [*(row.history or []), entry][-HISTORY_MAX:]


def _apply(row: Einvoice, result: providers.SendResult, moment: datetime) -> None:
    row.checked_at = moment
    if result.state == providers.DELIVERED:
        row.status, row.delivered_at, row.delivery_detail = (
            "delivered",
            row.delivered_at or moment,
            None,
        )
    elif result.state == providers.FAILED:
        row.status, row.delivery_detail = (
            "rejected",
            (result.detail or "Odrzucona.")[:500],
        )
    else:
        row.status = "sent"


def _restore(row: Einvoice, previous: str) -> None:
    """Powrót ze ``sending`` do stanu sprzed przejęcia (dokument nie wyszedł)."""

    row.status = "ready" if previous == "sending" else previous


async def _send_one(
    db: AsyncSession,
    provider: providers.PeppolProvider,
    row: Einvoice,
    invoice: ClientSalesInvoice,
    previous: str,
    value: dict[str, Any],
    actor_id: Optional[int],
) -> Optional[str]:
    """Wysyłka przejętego wiersza (``sending``); zwraca powód, gdy nie wyszła."""

    mode = value["mode"]
    try:
        built = await _build(row, invoice, value, with_pdf=True)
    except LookupError as missing:
        row.status, row.problems = str(missing.args[0]), []
        return STATUS_LABELS.get(row.status, row.status)
    except ubl.NothingToSend as exc:
        row.status, row.problems = "skipped", [_problem("nothing_to_send", str(exc))]
        return str(exc)
    except ubl.ConversionError as exc:
        row.status, row.problems = "invalid", [_problem(exc.code, str(exc))]
        return str(exc)
    except (fa.InvoiceParseError, fa_reader.UnsupportedInvoice) as exc:
        row.status, row.problems = "invalid", [_problem("parse", str(exc))]
        return str(exc)
    except validation.ValidationUnavailable as exc:
        _restore(row, previous)
        return str(exc)
    blocking = validation.blocking(built.findings)
    if blocking:
        row.status, row.problems = (
            "invalid",
            [finding.as_dict() for finding in built.findings],
        )
        return blocking[0].text
    row.document_type, row.problems = (
        built.result.document_type,
        [f.as_dict() for f in built.findings],
    )
    digest = hashlib.sha256(built.result.xml).hexdigest()
    moment = _now()
    try:
        result = await provider.send(
            providers.SendRequest(
                xml=built.result.xml,
                doctype_id=built.result.doctype_id,
                recipient=built.recipient,
            )
        )
    except providers.ProviderError as exc:
        entry = {
            "at": moment.isoformat(),
            "target": mode,
            "recipient": built.recipient,
            "detail": str(exc)[:300],
            "by": actor_id,
        }
        if not exc.retry:
            row.status, row.sent_at, row.sent_by = "rejected", moment, actor_id
            row.target, row.recipient, row.provider = (
                mode,
                built.recipient,
                provider.name,
            )
            row.delivery_detail = str(exc)[:500]
            _record(row, {**entry, "state": "failed"})
        elif exc.uncertain:
            # Dostawca mógł przyjąć dokument: zostaje „sending” dla osoby,
            # automat go nie ponowi (u odbiorcy byłaby druga faktura).
            row.target, row.recipient, row.provider = (
                mode,
                built.recipient,
                provider.name,
            )
            row.delivery_detail = (
                f"{exc} Sprawdź w panelu dostawcy, czy dokument wyszedł, przed ponowną wysyłką."
            )[:500]
            _record(row, {**entry, "state": "unknown"})
        else:
            _restore(row, previous)
            row.delivery_detail = (
                str(exc)[:500] if previous == "rejected" else row.delivery_detail
            )
        return str(exc)
    row.target, row.recipient, row.provider = mode, built.recipient, provider.name
    row.provider_document_id = result.document_id[:128]
    row.ubl_sha256, row.sent_at, row.sent_by = digest, moment, actor_id
    row.delivered_at, row.delivery_detail = None, None
    _apply(row, result, moment)
    _record(
        row,
        {
            "at": moment.isoformat(),
            "target": mode,
            "recipient": built.recipient,
            "document_id": result.document_id,
            "state": result.state,
            "detail": (result.detail or "")[:300] or None,
            "by": actor_id,
        },
    )
    logger.info("[peppol] e-faktura %s wysłana (%s, %s)", row.id, mode, result.state)
    return None if row.status != "rejected" else row.delivery_detail


async def send(
    db: AsyncSession, ids: list[int], *, actor: Optional[User], automatic: bool = False
) -> dict[str, Any]:
    """Wysyłka wybranych; automat (``automatic``) bierze wyłącznie „Do wysłania”."""

    provider = providers.open_provider()
    if provider is None:
        raise EinvoiceError(
            providers.load_config().disabled_reason or "Wysyłka wyłączona."
        )
    if not ids:
        raise EinvoiceError("Nie wybrano faktur.", 422)
    if len(ids) > SEND_BATCH_MAX:
        raise EinvoiceError(f"Najwyżej {SEND_BATCH_MAX} faktur naraz.", 422)
    value = await settings.load(db)
    await db.commit()
    sent, failed = 0, []
    for einvoice_id in ids:
        row, invoice, previous, number = await _claim(
            db, einvoice_id, value["mode"], manual=not automatic
        )
        if row is None:
            failed.append(
                {"id": einvoice_id, "invoice_number": number, "reason": previous}
            )
            continue
        try:
            reason = await _send_one(
                db, provider, row, invoice, previous, value, actor.id if actor else None
            )
        except Exception:
            # Nieznany błąd po przejęciu: wiersz zostaje „sending” dla osoby.
            await db.rollback()
            logger.exception("[peppol] wysyłka e-faktury %s przerwana", einvoice_id)
            raise
        await db.commit()
        if reason is None:
            sent += 1
        else:
            failed.append(
                {"id": einvoice_id, "invoice_number": number, "reason": reason}
            )
    return {"sent": sent, "failed": failed, "mode": value["mode"]}


async def refresh(db: AsyncSession, *, limit: int = REFRESH_MAX) -> int:
    """Wynik doręczenia dla wysłanych (``sent``) — z API dostawcy."""

    provider = providers.open_provider()
    if provider is None:
        return 0
    rows = list(
        await db.scalars(
            select(Einvoice)
            .where(Einvoice.status == "sent", Einvoice.provider == provider.name)
            .order_by(Einvoice.checked_at.nullsfirst(), Einvoice.id)
            .limit(limit)
        )
    )
    changed = 0
    for row in rows:
        try:
            result = await provider.status(row.provider_document_id or "")
        except providers.ProviderError as exc:
            row.checked_at = _now()
            if exc.retry:
                break
            continue
        before = row.status
        _apply(row, result, _now())
        changed += int(row.status != before)
    await db.commit()
    return changed


async def hourly(db: AsyncSession) -> dict[str, int]:
    """Z pętli KSeF: nowe faktury w zakresie, statusy doręczenia, automat."""

    value = await settings.load(db)
    created = await scan(db, value)
    await db.commit()
    refreshed = await refresh(db)
    auto = 0
    if value["auto_send"] and providers.load_config().enabled:
        ids = list(
            await db.scalars(
                select(Einvoice.id)
                .where(Einvoice.status == "ready")
                .order_by(Einvoice.id)
                .limit(AUTO_SEND_MAX)
            )
        )
        if ids:
            auto = (await send(db, ids, actor=None, automatic=True))["sent"]
    return {"created": created, "refreshed": refreshed, "auto_sent": auto}


# ── Odczyt dla ekranu ────────────────────────────────────────────────────────


def _month_filter(month: Optional[str]) -> Any:
    if not month:
        return None
    year, number = (int(part) for part in month.split("-"))
    return or_(
        and_(
            ClientSalesInvoice.period_year == year,
            ClientSalesInvoice.period_month == number,
        ),
        and_(
            ClientSalesInvoice.period_year.is_(None),
            func.extract("year", ClientSalesInvoice.issue_date) == year,
            func.extract("month", ClientSalesInvoice.issue_date) == number,
        ),
    )


async def client_ids(db: AsyncSession) -> list[int]:
    found = await db.scalars(
        select(ClientSalesInvoice.client_id)
        .join(Einvoice, Einvoice.invoice_id == ClientSalesInvoice.id)
        .where(ClientSalesInvoice.client_id.is_not(None))
        .distinct()
    )
    return sorted(int(value) for value in found)


def _row_view(
    row: Einvoice,
    invoice: ClientSalesInvoice,
    mode: str,
    receivers: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    status = effective_status(row, mode)
    receiver = receivers.get(row.receiver_key)
    return {
        "id": row.id,
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "ksef_number": invoice.ksef_number,
        "kind": invoice.invoice_kind,
        "issue_date": invoice.issue_date.isoformat(),
        "period": f"{invoice.period_year}-{invoice.period_month:02d}"
        if invoice.period_year and invoice.period_month
        else None,
        "buyer_name": invoice.buyer_name,
        "receiver_name": receiver["name"] if receiver else row.receiver_key,
        "currency": invoice.currency,
        "gross_amount": str(invoice.gross_amount),
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "document_type": row.document_type,
        "problems": row.problems or [],
        "delivery_detail": row.delivery_detail,
        "target": row.target,
        "recipient": row.recipient,
        "sent_at": _iso(row.sent_at),
        "delivered_at": _iso(row.delivered_at),
        "tested_at": _iso(row.sent_at) if row.target == "test" else None,
        "history": row.history or [],
    }


async def list_view(
    db: AsyncSession, *, client_id: int, month: Optional[str]
) -> dict[str, Any]:
    value = await settings.load(db)
    query = (
        select(Einvoice, ClientSalesInvoice)
        .join(ClientSalesInvoice, ClientSalesInvoice.id == Einvoice.invoice_id)
        .where(
            or_(
                ClientSalesInvoice.client_id == client_id,
                ClientSalesInvoice.client_id.is_(None),
            )
        )
        .order_by(ClientSalesInvoice.issue_date.desc(), ClientSalesInvoice.id.desc())
    )
    month_clause = _month_filter(month)
    if month_clause is not None:
        query = query.where(month_clause)
    receivers = {entry["key"]: entry for entry in value["receivers"]}
    rows = [
        _row_view(row, invoice, value["mode"], receivers)
        for row, invoice in await db.execute(query)
    ]
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    provider = providers.load_config()
    return {
        "mode": value["mode"],
        "auto_send": value["auto_send"],
        "provider": provider.name,
        "provider_ready": provider.enabled,
        "provider_detail": provider.disabled_reason,
        "rows": rows,
        "counts": counts,
    }


async def document(db: AsyncSession, einvoice_id: int) -> tuple[bytes, str]:
    """Plik UBL (z PDF-em) do pobrania — taki, jaki poszedłby teraz."""

    pair = (
        await db.execute(
            select(Einvoice, ClientSalesInvoice)
            .join(ClientSalesInvoice, ClientSalesInvoice.id == Einvoice.invoice_id)
            .where(Einvoice.id == einvoice_id)
        )
    ).first()
    if pair is None:
        raise EinvoiceError("Nie ma takiej e-faktury.", 404)
    row, invoice = pair
    value = await settings.load(db)
    try:
        built = await _build(row, invoice, value, with_pdf=True)
    except LookupError as missing:
        raise EinvoiceError(
            STATUS_LABELS.get(str(missing.args[0]), "Brak danych.")
        ) from missing
    except (
        ubl.ConversionError,
        ubl.NothingToSend,
        fa.InvoiceParseError,
        fa_reader.UnsupportedInvoice,
    ) as exc:
        raise EinvoiceError(str(exc)) from exc
    name = "".join(
        ch if ch.isalnum() or ch in "-." else "_" for ch in invoice.invoice_number
    )[:80]
    return built.result.xml, f"{name or 'e-faktura'}.xml"


async def recheck(db: AsyncSession, ids: Optional[list[int]] = None) -> int:
    """Ponowne przygotowanie (np. po zmianie adresu odbiorcy albo trybu)."""

    value = await settings.load(db)
    query = (
        select(Einvoice, ClientSalesInvoice)
        .join(ClientSalesInvoice, ClientSalesInvoice.id == Einvoice.invoice_id)
        .where(Einvoice.status.in_(PREPARABLE))
    )
    if ids:
        query = query.where(Einvoice.id.in_(ids))
    count = 0
    for row, invoice in await db.execute(query.limit(500)):
        await prepare(db, row, invoice, value)
        count += 1
    await db.commit()
    return count
