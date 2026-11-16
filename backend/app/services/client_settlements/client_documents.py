"""Dokumenty dla klienta na wiele osób (roadmapa E6.1 PKO, E6.2 Velo).

Reguła ``cl.client_document`` mówi, na kogo jest dokument (``per``):

* „cały miesiąc” — jeden zbiorczy protokół odbioru na wszystkie osoby (PKO,
  wzór z załącznika do umowy): numer, imię i nazwisko, rola, numer zamówienia,
  stawka za godzinę netto, liczba godzin, kwota netto. Numer zamówienia jest
  w tytule linii zamówienia (``client_orders.title``). Protokół i paczka
  (protokół, Time Sheety, akceptacje w HTML) są gotowe dopiero przy komplecie
  osób: klient chce jednego protokołu (odpowiedź rozliczeń z 12.11.2026).
  Adres wysyłki paczki stoi w regule ``cl.send_to`` (tylko w bazie).
* „podpisujący” — arkusze zbiorcze per osoba podpisująca u klienta (Velo):
  podpisujący to menedżer u klienta z kontraktu. Każdy arkusz do pobrania
  osobno, żeby wysłać go od razu, gdy jest gotowy; obok „Pobierz wszystkie”.
  Po podpisach wszystkich arkuszy: arkusz pod fakturę ze stawką i wartością.

Kwoty (stawki, wartości) tylko dla kont z dostępem do kwot. Dokumenty projektu
(Service Delivery Confirmation) są w ``service_confirmation``.
"""

from __future__ import annotations

import asyncio
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from html import escape
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.client_order import ClientOrder
from app.models.client_settlement import ClientSettlement
from app.models.contact import Contact
from app.models.consultant_portal import CpDocument
from app.models.job import Job
from app.services.client_order_lines import month_bounds
from app.services.client_settlements import (
    client_invoice,
    mail_text,
    service,
    signoffs,
    timesheet_pko,
)
from app.services.client_settlements.service_confirmation import render_pdf
from app.services.consultant_portal import documents as portal_documents

MONEY = Decimal("0.01")
HOURS_PER_MD = Decimal("8")
NO_SIGNER = "Bez podpisującego"
#: Dopiski w tytule rekrutacji, których nie ma w roli na dokumencie klienta.
_JOB_NOISE = re.compile(r"\s*(\([^)]*\)|-\s*\d+\.\s*iteracja.*)$", re.IGNORECASE)
_JOB_CODE = re.compile(r"\s*\((?:[A-Z]{2,5}-\d+)\)", re.IGNORECASE)


class DocumentError(service.SettlementError):
    pass


def layout(rules: dict[str, dict[str, Any]], month: str) -> Optional[str]:
    """``month`` (protokół), ``signer`` (arkusze) albo ``None``."""

    kind = signoffs.document_rule(rules, month)
    return {signoffs.PROTOCOL: "month", signoffs.SHEET: "signer"}.get(kind or "")


def _params(rules: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {
        k: str(v or "").strip()
        for k, v in rules["cl.client_document"]["params"].items()
    }


def send_to(rules: dict[str, dict[str, Any]]) -> Optional[str]:
    rule = rules["cl.send_to"]
    if rule["level"] == "off":
        return None
    return str(rule["params"].get("email") or "").strip() or None


def _role(title: Optional[str]) -> str:
    if not title:
        return ""
    cleaned = _JOB_CODE.sub("", title)
    for _ in range(3):
        cleaned = _JOB_NOISE.sub("", cleaned).strip()
    return re.sub(r"\s+-\s+", " ", cleaned).strip(" -")


def order_number(
    order: Optional[ClientOrder], fallback: Optional[str]
) -> Optional[str]:
    """Numer zamówienia z tytułu linii („Zamówienie nr 9001/2026” → „9001/2026”)."""

    return (
        service.number_from_title(order.title) if order is not None else None
    ) or fallback


def hourly_rate(order: Optional[ClientOrder]) -> Optional[Decimal]:
    if order is None:
        return None
    unit = getattr(order.rate_unit, "value", order.rate_unit)
    if unit == "hourly" and order.rate_client is not None:
        return Decimal(order.rate_client)
    if order.md_rate_revenue is not None:
        return Decimal(order.md_rate_revenue) / HOURS_PER_MD
    if unit == "daily" and order.rate_client is not None:
        return Decimal(order.rate_client) / HOURS_PER_MD
    return None


@dataclass
class Person:
    contract_id: int
    name: str
    status: str
    settlement: Optional[ClientSettlement]
    order: Optional[ClientOrder] = None
    order_number: Optional[str] = None
    role: str = ""
    hours: Optional[Decimal] = None
    md: Optional[Decimal] = None
    rate_hour: Optional[Decimal] = None
    rate_day: Optional[Decimal] = None
    period: tuple[date, date] = (date.min, date.min)
    signer: str = NO_SIGNER
    signed: Optional[dict[str, Any]] = None
    files: list[CpDocument] = field(default_factory=list)

    @property
    def amount(self) -> Optional[Decimal]:
        if self.hours is None or self.rate_hour is None:
            return None
        return (self.hours * self.rate_hour).quantize(MONEY, rounding=ROUND_HALF_UP)

    @property
    def amount_md(self) -> Optional[Decimal]:
        if self.md is None or self.rate_day is None:
            return None
        return (self.md * self.rate_day).quantize(MONEY, rounding=ROUND_HALF_UP)


async def _hours(document: Optional[CpDocument]) -> Optional[Decimal]:
    if document is None or document.mime not in timesheet_pko.MIMES:
        return None
    try:
        content = portal_documents.path_for(document.file_path).read_bytes()
    except OSError:
        return None
    parsed = await asyncio.to_thread(timesheet_pko.parse, content, document.mime)
    return parsed.total_hours if parsed is not None and parsed.entries else None


async def _people(db: AsyncSession, client_id: int, month: str) -> list[Person]:
    people = await service._people(db, client_id, month)
    ids = [p.contract.id for p in people]
    settlements = (
        {
            s.contract_id: s
            for s in (
                await db.scalars(
                    select(ClientSettlement).where(
                        ClientSettlement.contract_id.in_(ids),
                        ClientSettlement.period_month == month,
                        ClientSettlement.kind == service.ACTUAL,
                    )
                )
            ).all()
        }
        if ids
        else {}
    )
    numbers = await service._order_numbers(db, ids, month)
    first, last = month_bounds(month)
    out: list[Person] = []
    for p in people:
        s = settlements.get(p.contract.id)
        order = await db.get(ClientOrder, s.order_id) if s and s.order_id else None
        if order is None:
            order = await service._order_for(db, p.contract.id, month)
        job_id = (order.job_id if order else None) or p.contract.job_id
        job_title = (
            await db.scalar(select(Job.title).where(Job.id == job_id))
            if job_id
            else None
        )
        signer = None
        if p.contract.client_pm_contact_id:
            signer = await db.scalar(
                select(Contact.name).where(
                    Contact.id == p.contract.client_pm_contact_id
                )
            )
        start = max(first, p.contract.start_date or first)
        end = min(last, p.contract.end_date or last)
        person = Person(
            contract_id=p.contract.id,
            name=p.name,
            status=s.status if s else "missing",
            settlement=s,
            order=order,
            order_number=order_number(order, numbers.get(p.contract.id)),
            role=_role(job_title),
            md=Decimal(s.md_regular) if s and s.md_regular is not None else None,
            rate_hour=hourly_rate(order),
            rate_day=client_invoice.client_price(order).rate if order else None,
            period=(start, end),
            signer=(signer or p.contract.client_pm_name or "").strip() or NO_SIGNER,
            signed=signoffs.signed_state(s.checks if s else None, signoffs.SHEET),
        )
        if s is not None and s.status == "accepted":
            hours = await _hours(
                await db.get(CpDocument, s.report_document_id)
                if s.report_document_id
                else None
            )
            charged = Decimal(s.md_charged) if s.md_charged is not None else None
            if hours is None or (service.md_over(s) and charged is not None):
                hours = (charged or Decimal(s.md_regular or 0)) * HOURS_PER_MD
            person.hours = hours
        out.append(person)
    return out


def _period_text(month: str) -> str:
    first, last = month_bounds(month)
    return f"Od {first.strftime('%d.%m.%Y')} do {last.strftime('%d.%m.%Y')}"


def _money(value: Optional[Decimal]) -> str:
    if value is None:
        return "—"
    text = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    return f"{text} zł"


def _num(value: Optional[Decimal]) -> str:
    if value is None:
        return "—"
    return f"{value.normalize():f}".replace(".", ",")


_STYLE = (
    "@page{size:A4 landscape;margin:14mm 12mm}"
    "body{font-family:'DejaVu Sans','Liberation Sans',sans-serif;font-size:9pt;color:#1f2933}"
    "h1{font-size:13pt;text-align:center;margin:6pt 0}"
    ".top{font-size:8pt;font-weight:700;text-transform:uppercase;margin-bottom:6pt}"
    ".firm{margin:6pt 0 10pt}"
    "table.t{border-collapse:collapse;width:100%}"
    ".t th,.t td{border:0.6px solid #7b8794;padding:3pt 4pt;vertical-align:top}"
    ".t th{background:#eef2f5;font-size:8pt;text-align:left}"
    ".n{text-align:right;white-space:nowrap}"
    ".sign{display:flex;justify-content:space-between;margin-top:40pt}"
    ".sign div{width:40%;text-align:center;border-top:0.6px dotted #52606d;padding-top:3pt}"
)


# ── PKO: protokół odbioru ────────────────────────────────────────────────────


def _protocol_rows(people: list[Person]) -> list[Person]:
    return [p for p in people if p.status == "accepted" and p.hours]


def protocol_html(
    *, header: str, client_name: str, month: str, rows: list[Person]
) -> str:
    from app.services.consultant_portal.panel import BUYER

    body = "".join(
        "<tr>"
        f"<td class='n'>{i}</td><td>{escape(p.name)}</td><td>{escape(p.role)}</td>"
        f"<td>{escape(p.order_number or '—')}</td>"
        f"<td class='n'>{_money(p.rate_hour)}</td><td class='n'>{_num(p.hours)}</td>"
        f"<td class='n'>{_money(p.amount)}</td>"
        "</tr>"
        for i, p in enumerate(rows, start=1)
    )
    address = escape(BUYER["address"]).replace(", ", "<br>")
    return (
        "<!DOCTYPE html><html lang='pl'><head><meta charset='utf-8'>"
        f"<title>Protokół odbioru {escape(month)}</title><style>{_STYLE}</style></head><body>"
        + (f"<p class='top'>{escape(header)}</p>" if header else "")
        + "<h1>PROTOKÓŁ ODBIORU</h1>"
        f"<p class='firm'><b>FIRMA:</b><br>{escape(BUYER['name'])}<br>{address}"
        f"<br>NIP {escape(BUYER['nip'])}</p>"
        f"<p><b>OKRES ROZLICZENIOWY:</b> {escape(_period_text(month))}</p>"
        "<table class='t'><thead><tr><th>Numer</th><th>Imię i Nazwisko</th>"
        "<th>Rola/profil</th><th>Numer zamówienia</th><th>Stawka za godzinę netto</th>"
        "<th>Liczba godzin przepracowanych</th><th>Kwota netto</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
        "<div class='sign'><div>Podpis dostawcy</div>"
        f"<div>Podpis pracownika {escape(client_name)}</div></div>"
        "</body></html>"
    )


def _month_view(
    client: Client,
    month: str,
    rules: dict[str, dict[str, Any]],
    people: list[Person],
    amounts: bool,
) -> dict[str, Any]:
    rows = _protocol_rows(people)
    accepted = sum(1 for p in people if p.status == "accepted")
    complete = bool(people) and accepted == len(people)
    signed = [
        signoffs.signed_state(
            p.settlement.checks if p.settlement else None, signoffs.PROTOCOL
        )
        for p in people
    ]
    signed_ok = complete and all(s and s.get("complete") for s in signed)
    return {
        "people": len(people),
        "accepted": accepted,
        "ready": complete,
        "send_to": send_to(rules),
        "signed": signed_ok,
        "signed_by": next(
            (s.get("signer") for s in signed if s and s.get("signer")), None
        ),
        "missing_roles": [p.name for p in rows if not p.role],
        "missing_orders": [p.name for p in rows if not p.order_number],
        "waiting": [
            {"person": p.name, "status": p.status}
            for p in people
            if p.status != "accepted"
        ],
        "hours": f"{sum((p.hours or 0 for p in rows), Decimal('0')):.2f}",
        "net": f"{sum((p.amount or 0 for p in rows), Decimal('0')):.2f}"
        if amounts
        else None,
        "files": [
            {
                "person": p.name,
                "timesheet": p.settlement is not None
                and p.settlement.report_document_id is not None,
            }
            for p in rows
        ],
    }


async def protocol_pdf(
    db: AsyncSession, client_id: int, month: str
) -> tuple[bytes, str]:
    client, rules, people = await _load(db, client_id, month, "month")
    rows = _protocol_rows(people)
    accepted = sum(1 for p in people if p.status == "accepted")
    if not people or accepted < len(people):
        raise DocumentError(
            f"Protokół czeka na komplet: przyjęte {accepted} z {len(people)} osób.",
            status=409,
        )
    html = protocol_html(
        header=_params(rules).get("header", ""),
        client_name=client.name,
        month=month,
        rows=rows,
    )
    content = await asyncio.to_thread(render_pdf, html)
    return content, f"Protokol_odbioru_{month}.pdf"


def _safe(text: str) -> str:
    return re.sub(r"[^\w.-]+", "_", text, flags=re.UNICODE).strip("_") or "plik"


async def package_zip(
    db: AsyncSession, client_id: int, month: str
) -> tuple[bytes, str]:
    """Paczka do klienta: protokół, Time Sheety i akceptacje w HTML."""

    protocol, protocol_name = await protocol_pdf(db, client_id, month)
    _client, _rules, people = await _load(db, client_id, month, "month")
    year, mon = (int(x) for x in month.split("-"))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(protocol_name, protocol)
        used: set[str] = {protocol_name}
        for person in _protocol_rows(people):
            documents = (
                await db.scalars(
                    select(CpDocument).where(
                        CpDocument.contract_id == person.contract_id,
                        CpDocument.kind == "report",
                        CpDocument.period_year == year,
                        CpDocument.period_month == mon,
                        CpDocument.status != "rejected",
                    )
                )
            ).all()
            files: list[tuple[str, bytes]] = []
            mails: list[mail_text.Mail] = []
            for document in sorted(documents, key=lambda d: d.created_at, reverse=True):
                try:
                    content = portal_documents.path_for(document.file_path).read_bytes()
                except OSError:
                    continue
                if document.id == person.settlement.report_document_id:
                    name = document.file_name or f"TimeSheet_{_safe(person.name)}.xlsm"
                    files.append((name, content))
                elif document.mime in mail_text.MAIL_MIMES:
                    mail = mail_text.read(content, document.mime)
                    if mail is not None:
                        mails.append(mail)
            # Najnowsza akceptacja, która przeszła kontrolę; bez takiej — najnowszy mail.
            passing = [
                m
                for m in mails
                if mail_text.judge([m], month=month, hours=person.hours, md=None).ok
            ] or mails
            for mail in passing[:1]:
                files.append(
                    (
                        mail_text.html_name(mail, f"Akceptacja_{_safe(person.name)}"),
                        mail_text.to_html(mail).encode("utf-8"),
                    )
                )
            for name, content in files:
                base, dot, ext = name.rpartition(".")
                candidate, n = name, 2
                while candidate in used:
                    candidate = (
                        f"{base or name}_{n}{dot}{ext}" if dot else f"{name}_{n}"
                    )
                    n += 1
                used.add(candidate)
                archive.writestr(candidate, content)
    return buffer.getvalue(), f"Paczka_{_safe(_client.name)}_{month}.zip"


# ── Velo: arkusze zbiorcze per podpisujący ───────────────────────────────────


def sheet_html(*, signer: str, rows: list[Person], with_amounts: bool) -> str:
    def date_text(value: date) -> str:
        return value.strftime("%d-%m-%Y")

    head = (
        "<th>Nazwisko i imię</th><th>Rodzaj kompetencji (profil)</th>"
        "<th>Zlecenie od<br>(dd-mm-rrrr)</th><th>Zlecenie do<br>(dd-mm-rrrr)</th>"
        "<th>Liczba MD</th>"
        + ("<th>Stawka</th><th>Wartość</th>" if with_amounts else "")
    )
    body = "".join(
        "<tr>"
        f"<td>{escape(p.name)}</td><td>{escape(p.role)}</td>"
        f"<td>{date_text(p.period[0])}</td><td>{date_text(p.period[1])}</td>"
        f"<td class='n'>{_num(p.md)}</td>"
        + (
            f"<td class='n'>{_money(p.rate_day)}</td><td class='n'>{_money(p.amount_md)}</td>"
            if with_amounts
            else ""
        )
        + "</tr>"
        for p in rows
    )
    total = (
        "<tr><td><b>Suma</b></td><td></td><td></td><td></td><td></td><td></td>"
        f"<td class='n'><b>{_money(sum((p.amount_md or 0 for p in rows), Decimal('0')))}</b></td></tr>"
        if with_amounts
        else ""
    )
    title = "Arkusz pracy zbiorczy" + ("" if with_amounts else f" — {escape(signer)}")
    return (
        "<!DOCTYPE html><html lang='pl'><head><meta charset='utf-8'>"
        f"<title>{title}</title><style>{_STYLE}</style></head><body>"
        f"<h1>{title}</h1><table class='t'><thead><tr>{head}</tr></thead>"
        f"<tbody>{body}{total}</tbody></table></body></html>"
    )


def _sheet_people(people: list[Person]) -> list[Person]:
    return [
        p
        for p in people
        if p.settlement is not None and p.status != "needs_fix" and p.md is not None
    ]


def _groups(people: list[Person]) -> dict[str, list[Person]]:
    groups: dict[str, list[Person]] = {}
    for p in _sheet_people(people):
        groups.setdefault(p.signer, []).append(p)
    return dict(
        sorted(groups.items(), key=lambda kv: (kv[0] == NO_SIGNER, kv[0].lower()))
    )


def _signer_view(people: list[Person], amounts: bool) -> dict[str, Any]:
    groups = _groups(people)
    rows = _sheet_people(people)
    signed = [p for p in rows if p.signed and p.signed.get("complete")]
    all_signed = bool(rows) and len(signed) == len(rows)
    return {
        "signers": [
            {
                "signer": signer,
                "people": len(items),
                "md": f"{sum((p.md or 0 for p in items), Decimal('0')):.3f}",
                "signed": sum(
                    1 for p in items if p.signed and p.signed.get("complete")
                ),
            }
            for signer, items in groups.items()
        ],
        "rows": [
            {
                "contract_id": p.contract_id,
                "person": p.name,
                "signer": p.signer,
                "md": f"{p.md:.3f}" if p.md is not None else None,
                "status": p.status,
                "signed": bool(p.signed and p.signed.get("complete")),
                "signed_by": (p.signed or {}).get("signer"),
                "signed_at": (p.signed or {}).get("signed_at"),
                "amount": f"{p.amount_md:.2f}"
                if amounts and p.amount_md is not None
                else None,
            }
            for p in rows
        ],
        "without_sheet": [
            {"person": p.name, "status": p.status} for p in people if p not in rows
        ],
        "all_signed": all_signed,
        "net": f"{sum((p.amount_md or 0 for p in rows), Decimal('0')):.2f}"
        if amounts
        else None,
    }


async def sheet_pdf(
    db: AsyncSession, client_id: int, month: str, signer: str
) -> tuple[bytes, str]:
    _client, _rules, people = await _load(db, client_id, month, "signer")
    rows = _groups(people).get(signer)
    if not rows:
        raise DocumentError(
            "Nie ma osób dla tego podpisującego w tym miesiącu.", status=404
        )
    content = await asyncio.to_thread(
        render_pdf, sheet_html(signer=signer, rows=rows, with_amounts=False)
    )
    return content, f"Arkusz_zbiorczy_{_safe(signer)}_{month}.pdf"


async def sheets_zip(db: AsyncSession, client_id: int, month: str) -> tuple[bytes, str]:
    _client, _rules, people = await _load(db, client_id, month, "signer")
    groups = _groups(people)
    if not groups:
        raise DocumentError("W tym miesiącu nie ma jeszcze MD do arkuszy.", status=404)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for signer, rows in groups.items():
            content = await asyncio.to_thread(
                render_pdf, sheet_html(signer=signer, rows=rows, with_amounts=False)
            )
            archive.writestr(f"Arkusz_zbiorczy_{_safe(signer)}_{month}.pdf", content)
    return buffer.getvalue(), f"Arkusze_zbiorcze_{month}.zip"


async def invoice_sheet_pdf(
    db: AsyncSession, client_id: int, month: str
) -> tuple[bytes, str]:
    """Arkusz pod fakturę: wszystkie osoby ze stawką i wartością, po podpisach."""

    _client, _rules, people = await _load(db, client_id, month, "signer")
    rows = _sheet_people(people)
    waiting = [p.name for p in rows if not (p.signed and p.signed.get("complete"))]
    if not rows or waiting:
        raise DocumentError(
            f"Arkusz pod fakturę czeka na podpisy: {len(waiting)} z {len(rows)} osób.",
            status=409,
        )
    content = await asyncio.to_thread(
        render_pdf, sheet_html(signer="", rows=rows, with_amounts=True)
    )
    return content, f"Arkusz_zbiorczy_wartosci_{month}.pdf"


# ── Wspólne ──────────────────────────────────────────────────────────────────


async def _load(
    db: AsyncSession, client_id: int, month: str, expected: str
) -> tuple[Client, dict[str, dict[str, Any]], list[Person]]:
    client = await db.get(Client, client_id)
    if client is None:
        raise DocumentError("Nie ma takiego klienta.", status=404)
    rules = await service.rules_for(db, client_id, month)
    if layout(rules, month) != expected:
        raise DocumentError(
            "Klient nie ma w regułach tego dokumentu za ten miesiąc.", status=404
        )
    return client, rules, await _people(db, client_id, month)


async def collect(
    db: AsyncSession, client_id: int, month: str, *, amounts: bool
) -> Optional[dict[str, Any]]:
    """Blok listy miesiąca albo ``None``, gdy klient nie ma takiego dokumentu."""

    client = await db.get(Client, client_id)
    if client is None:
        raise DocumentError("Nie ma takiego klienta.", status=404)
    rules = await service.rules_for(db, client_id, month)
    kind = layout(rules, month)
    if kind is None:
        return None
    params = _params(rules)
    people = await _people(db, client_id, month)
    base: dict[str, Any] = {
        "client_id": client_id,
        "month": month,
        "enabled": True,
        "layout": kind,
        "kind": params.get("kind")
        or ("Protokół odbioru" if kind == "month" else "Arkusz zbiorczy"),
        "stage": None,
        "can_see_amounts": amounts,
        "projects": [],
        "skipped": [],
    }
    if kind == "month":
        base["protocol"] = _month_view(client, month, rules, people, amounts)
    else:
        base["sheets"] = _signer_view(people, amounts)
    return base
