"""Lista zamknięcia miesiąca i terminy podatków (K3d, zakładka „Miesiąc”).

Przed zamknięciem okresu widać, czy źródła miesiąca są w księdze (Źródła K2,
automaty K3a), czy bufor jest pusty i czy zatwierdzone dokumenty poszły do
Symfonii (K3b, tylko w trybie roku „symfonia” albo „równolegle”) i — dla
Płac — czy jest lista płac z Enovy (K3c; osoba bez Płac widzi tylko, kto ją
wczytuje, bez liczby). Etapy, których jeszcze nie ma (bank, VAT, środki
trwałe), stoją na liście z numerem etapu — do tego czasu robi je Symfonia.

Terminy za miesiąc M przypadają w miesiącu M+1; sobota, niedziela i święto
przesuwają termin na następny dzień roboczy (art. 12 § 5 Ordynacji podatkowej,
do składek przez ustawę o systemie ubezpieczeń społecznych):

* ZUS (DRA i składki) — 15. (płatnik, który nie jest osobą fizyczną opłacającą
  składki tylko za siebie; art. 47 ustawy o systemie ubezpieczeń społecznych),
* PPK — 15. (art. 28 ustawy o PPK),
* PIT-4: zaliczki od wynagrodzeń pobrane w M — 20. (art. 38 ustawy o PIT),
* VAT i JPK_V7M — 25. (art. 99 i 103 ustawy o VAT).

Kwoty dojdą z listą płac (K3c z pliku Enovy, potem K7) i rozliczeniem VAT (K5).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ, is_business_day
from app.models.ledger import LedgerDocument, LedgerPeriod, LedgerYear
from app.services.ledger import exports, payroll_lists, sources
from app.services.ledger.documents import Viewer
from app.services.ledger.settings import LedgerSettings


@dataclass(frozen=True)
class Deadline:
    key: str
    label: str
    nominal: date
    due: date
    basis: str
    amount_from: str


#: Terminy za miesiąc M w miesiącu M+1: klucz, dzień, etykieta, podstawa, skąd kwota.
DEADLINES: tuple[tuple[str, int, str, str, str], ...] = (
    (
        "zus",
        15,
        "ZUS — DRA i składki",
        "art. 47 ustawy o systemie ubezpieczeń społecznych",
        "lista płac (K3c z pliku Enovy, potem K7)",
    ),
    ("ppk", 15, "PPK — wpłaty", "art. 28 ustawy o PPK", "lista płac (K3c, K7)"),
    (
        "pit",
        20,
        "PIT-4 — zaliczki od wynagrodzeń pobrane w miesiącu",
        "art. 38 ustawy o PIT",
        "lista płac (K3c, K7)",
    ),
    (
        "vat",
        25,
        "VAT — JPK_V7M i przelew",
        "art. 99 i 103 ustawy o VAT",
        "rozliczenie VAT (K5)",
    ),
)
#: Etapy, których jeszcze nie ma: klucz, etykieta, kto robi to do tego czasu.
LATER: tuple[tuple[str, str, str], ...] = (
    ("bank", "Wyciągi bankowe", "etap K4 — do tego czasu import XML w Symfonii"),
    (
        "vat",
        "Rozliczenie VAT i JPK_V7M",
        "etap K5 — do tego czasu rejestry w Symfonii",
    ),
    ("assets", "Amortyzacja", "etap K6 — do tego czasu Symfonia Środki Trwałe"),
)


def next_business_day(day: date) -> date:
    """Ten sam dzień, gdy roboczy; inaczej następny dzień roboczy (kalendarz PL)."""

    zone = ZoneInfo(DEFAULT_TZ)
    while not is_business_day(datetime(day.year, day.month, day.day, 12, tzinfo=zone)):
        day += timedelta(days=1)
    return day


def deadlines(year: int, month: int) -> list[Deadline]:
    """Terminy za miesiąc ``year``-``month`` (płatne w następnym miesiącu)."""

    following = (year + 1, 1) if month == 12 else (year, month + 1)
    out: list[Deadline] = []
    for key, day, label, basis, amount_from in DEADLINES:
        nominal = date(following[0], following[1], day)
        out.append(
            Deadline(
                key=key,
                label=label,
                nominal=nominal,
                due=next_business_day(nominal),
                basis=basis,
                amount_from=amount_from,
            )
        )
    return out


def source_check(item: dict[str, Any], href: str) -> dict[str, Any]:
    """Pozycja listy z karty „Źródeł” miesiąca (``sources.month_summary``)."""

    pending = int(item["to_post"]) + int(item["changed"])
    problems = int(item["problems_total"])
    parts = []
    if pending:
        parts.append(f"do zaksięgowania: {pending}")
    if problems:
        parts.append(f"do wyjaśnienia: {problems}")
    if problems:
        state = "problem"
    elif pending:
        state = "todo"
    else:
        state = "ok"
    detail = ", ".join(parts) or (
        "w księdze" if item["total"] else "nic w tym miesiącu"
    )
    return {
        "key": f"source:{item['kind']}",
        "label": item["label"],
        "state": state,
        "detail": detail,
        "href": href,
    }


def symfonia_check(status: dict[str, Any], href: str) -> dict[str, Any]:
    """Pozycja listy z paczek do Symfonii (``exports.month_status``)."""

    parts = []
    if status["outside"]:
        parts.append(f"zatwierdzone poza paczką: {status['outside']}")
    if status["waiting"]:
        parts.append(
            "czeka na „Zaksięgowana w Symfonii”: " + ", ".join(status["waiting"])
        )
    return {
        "key": "symfonia",
        "label": "Paczka do Symfonii",
        "state": "todo" if parts else "ok",
        "detail": "; ".join(parts) or "wszystko w paczkach",
        "href": href,
    }


async def payroll_check(
    db: AsyncSession, period_id: int, viewer: Viewer, href: str
) -> dict[str, Any]:
    """Lista płac z Enovy w okresie (K3c). Osoba bez Płac nie widzi liczby (D2)."""

    if not viewer.payroll:
        return {
            "key": "payroll",
            "label": "Lista płac",
            "state": "later",
            "detail": "wczytują ją Płace z pliku Enovy (Automaty)",
            "href": None,
        }
    count = await db.scalar(
        select(func.count())
        .select_from(LedgerDocument)
        .where(
            LedgerDocument.period_id == period_id,
            LedgerDocument.source_type == payroll_lists.SOURCE_TYPE,
            LedgerDocument.reversed_by_id.is_(None),
        )
    )
    return {
        "key": "payroll",
        "label": "Lista płac z Enovy",
        "state": "ok" if count else "todo",
        "detail": f"w księdze: {count}"
        if count
        else "wczytaj listę z Enovy w „Automatach”",
        "href": None if count else href,
    }


async def _drafts(db: AsyncSession, period_id: int, viewer: Viewer) -> int:
    conditions = [
        LedgerDocument.period_id == period_id,
        LedgerDocument.status == "draft",
    ]
    if not viewer.payroll:
        conditions.append(LedgerDocument.sensitivity.is_(None))
    count = await db.scalar(
        select(func.count()).select_from(LedgerDocument).where(*conditions)
    )
    return int(count or 0)


async def checklist(
    db: AsyncSession,
    year: int,
    month: int,
    *,
    viewer: Viewer,
    settings: LedgerSettings,
) -> dict[str, Any]:
    """Lista zamknięcia miesiąca i terminy (bez zapisu)."""

    query = f"?year={year}&month={month}"
    summary = await sources.month_summary(
        db, year, month, viewer=viewer, settings=settings
    )
    items = [
        source_check(item, f"/accounting/sources{query}") for item in summary["items"]
    ]
    year_row = await db.scalar(select(LedgerYear).where(LedgerYear.year == year))
    period = None
    if year_row is not None:
        period = await db.scalar(
            select(LedgerPeriod).where(
                LedgerPeriod.year_id == year_row.id, LedgerPeriod.month == month
            )
        )
    if period is not None:
        drafts = await _drafts(db, period.id, viewer)
        items.append(
            {
                "key": "drafts",
                "label": "Bufor — dokumenty do zatwierdzenia",
                "state": "todo" if drafts else "ok",
                "detail": f"w buforze: {drafts}" if drafts else "pusty",
                "href": f"/accounting/documents{query}&status=draft",
            }
        )
        items.append(
            await payroll_check(
                db, period.id, viewer, f"/accounting/automations{query}"
            )
        )
    status = await exports.month_status(db, year, month, viewer=viewer)
    if status is not None:
        items.append(symfonia_check(status, f"/accounting/symfonia{query}"))
    items.extend(
        {
            "key": f"later:{key}",
            "label": label,
            "state": "later",
            "detail": detail,
            "href": None,
        }
        for key, label, detail in LATER
        # Środki trwałe (K6) są już w „Źródłach”, gdy moduł jest otwarty.
        if not (key == "assets" and sources.assets_open(settings, viewer))
    )
    return {
        "year": year,
        "month": month,
        "period_status": period.status if period is not None else None,
        "items": items,
        "deadlines": [
            {
                "key": item.key,
                "label": item.label,
                "nominal": item.nominal.isoformat(),
                "due": item.due.isoformat(),
                "basis": item.basis,
                "amount_from": item.amount_from,
            }
            for item in deadlines(year, month)
        ],
    }
