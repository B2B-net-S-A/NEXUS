"""Sondy „u nas”: co zmiana w prawie znaczy na danych NEXUSA.

Rejestr w kodzie: klucz → zapytanie tylko do odczytu, wynik to liczba, zdanie
i link do listy na ekranie. Same liczby, bez nazwisk i kwot. Analityk wybiera
sondy z katalogu (klucz i opis), ale liczb nie dostaje: liczy je NEXUS po
biegu Analityka i raz dziennie (``tasks/law_radar.py``).

„Dziś” to kalendarz firmy (``business_today``), nie data serwera.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Awaitable, Callable, Iterable, Optional

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.hr_payroll_lists import PayrollParameterVersion
from app.models.job_posting import JobPosting, PostingStatus
from app.models.law_radar import LawChange, LawChangeProbe
from app.services.law_radar import schema

logger = logging.getLogger(__name__)

B2B_LONG_MONTHS = 24
#: Lista na ekranie, do której prowadzi wynik sondy.
LINKS: dict[str, str] = {
    "b2b_long_contracts": "/contracts",
    "postings_without_salary": "/jobs",
    "payroll_params_next_year": "/accounting/payroll",
    "ksef_sales_invoices": "/finance/faktury",
}
FAILED_TEXT = "Nie udało się policzyć — spróbujemy przy następnym przeliczeniu."


@dataclass(frozen=True)
class ProbeResult:
    value: Optional[int]
    text: str
    link: Optional[str] = None


@dataclass(frozen=True)
class Probe:
    key: str
    description: str
    compute: Callable[[AsyncSession, date], Awaitable[ProbeResult]]


def plural(n: int, one: str, few: str, many: str) -> str:
    """Polska odmiana liczebnika: 1 umowa, 2 umowy, 5 umów, 22 umowy."""

    if n == 1:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many


def months_back(today: date, months: int) -> date:
    """Ten sam dzień ``months`` miesięcy wcześniej (31 → ostatni dzień miesiąca)."""

    index = today.year * 12 + today.month - 1 - months
    year, month = divmod(index, 12)
    month += 1
    for day in range(today.day, 27, -1):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return date(year, month, min(today.day, 28))


def next_year_start(today: date) -> date:
    return date(today.year + 1, 1, 1)


def last_full_month(today: date) -> tuple[date, date]:
    """Pierwszy i ostatni dzień poprzedniego miesiąca."""

    end = today.replace(day=1) - timedelta(days=1)
    return end.replace(day=1), end


async def _b2b_long_contracts(db: AsyncSession, today: date) -> ProbeResult:
    since = months_back(today, B2B_LONG_MONTHS)
    count = await db.scalar(
        select(func.count())
        .select_from(Contract)
        .where(
            Contract.contract_type == ContractType.b2b,
            Contract.status == ContractStatus.active,
            Contract.voided_at.is_(None),
            Contract.start_date.is_not(None),
            Contract.start_date <= since,
        )
    )
    n = int(count or 0)
    word = plural(
        n,
        "aktywna umowa B2B trwa",
        "aktywne umowy B2B trwają",
        "aktywnych umów B2B trwa",
    )
    return ProbeResult(
        n, f"{n} {word} co najmniej 24 miesiące.", LINKS["b2b_long_contracts"]
    )


async def _postings_without_salary(db: AsyncSession, today: date) -> ProbeResult:
    salary = JobPosting.options["salary"]
    count = await db.scalar(
        select(func.count())
        .select_from(JobPosting)
        .where(
            JobPosting.status == PostingStatus.published,
            or_(
                JobPosting.options.is_(None),
                salary.is_(None),
                func.jsonb_typeof(salary) == "null",
            ),
        )
    )
    n = int(count or 0)
    word = plural(
        n,
        "opublikowane ogłoszenie",
        "opublikowane ogłoszenia",
        "opublikowanych ogłoszeń",
    )
    return ProbeResult(
        n, f"{n} {word} bez widełek wynagrodzenia.", LINKS["postings_without_salary"]
    )


async def _payroll_params_next_year(db: AsyncSession, today: date) -> ProbeResult:
    start = next_year_start(today)
    count = await db.scalar(
        select(func.count())
        .select_from(PayrollParameterVersion)
        .where(
            PayrollParameterVersion.effective_from == start,
            PayrollParameterVersion.replaced_at.is_(None),
        )
    )
    missing = 0 if int(count or 0) else 1
    label = start.strftime("%d.%m.%Y")
    text = (
        f"Brak parametrów płac od {label}."
        if missing
        else f"Parametry płac od {label} są w NEXUSIE."
    )
    return ProbeResult(missing, text, LINKS["payroll_params_next_year"])


async def _ksef_sales_invoices(db: AsyncSession, today: date) -> ProbeResult:
    first, last = last_full_month(today)
    count = await db.scalar(
        select(func.count())
        .select_from(ClientSalesInvoice)
        .where(
            ClientSalesInvoice.ksef_number.is_not(None),
            ClientSalesInvoice.issue_date >= first,
            ClientSalesInvoice.issue_date <= last,
        )
    )
    n = int(count or 0)
    word = plural(n, "faktura sprzedaży", "faktury sprzedaży", "faktur sprzedaży")
    return ProbeResult(
        n,
        f"{n} {word} z numerem KSeF w {first.strftime('%m.%Y')}.",
        LINKS["ksef_sales_invoices"],
    )


async def _related_party_documents(db: AsyncSession, today: date) -> ProbeResult:
    return ProbeResult(None, "Listy podmiotów powiązanych nie ma dziś w NEXUSIE.", None)


REGISTRY: dict[str, Probe] = {
    probe.key: probe
    for probe in (
        Probe(
            "b2b_long_contracts",
            "Liczba aktywnych umów B2B trwających co najmniej 24 miesiące "
            "(ryzyko uznania za stosunek pracy).",
            _b2b_long_contracts,
        ),
        Probe(
            "postings_without_salary",
            "Liczba opublikowanych ogłoszeń o pracę bez widełek wynagrodzenia.",
            _postings_without_salary,
        ),
        Probe(
            "payroll_params_next_year",
            "Czy w NEXUSIE są parametry płac (składki, PIT, płaca minimalna) "
            "od 1 stycznia następnego roku.",
            _payroll_params_next_year,
        ),
        Probe(
            "ksef_sales_invoices",
            "Liczba faktur sprzedaży z numerem KSeF w ostatnim pełnym miesiącu.",
            _ksef_sales_invoices,
        ),
        Probe(
            "related_party_documents",
            "Czy NEXUS ma listę podmiotów powiązanych i dokumentację transakcji z nimi.",
            _related_party_documents,
        ),
    )
}


def catalog() -> list[dict[str, str]]:
    """Klucze i opisy dla Analityka, bez liczb."""

    return [{"key": p.key, "description": p.description} for p in REGISTRY.values()]


def known_keys(keys: Iterable[str]) -> list[str]:
    """Klucze z rejestru w kolejności podania, bez powtórek; nieznane odpadają."""

    out: list[str] = []
    for key in keys:
        if key in REGISTRY and key not in out:
            out.append(key)
    return out


async def compute(db: AsyncSession, probe_key: str, today: date) -> ProbeResult:
    """Jedna sonda w punkcie zapisu: błąd zapytania nie psuje reszty."""

    probe = REGISTRY[probe_key]
    try:
        async with db.begin_nested():
            return await probe.compute(db, today)
    except Exception as exc:  # noqa: BLE001 — sonda to dodatek, nie warunek
        logger.warning("law_radar probe=%s failed: %s", probe_key, type(exc).__name__)
        return ProbeResult(None, FAILED_TEXT, LINKS.get(probe_key))


async def recompute(
    db: AsyncSession, change_ids: Iterable[int], *, now: datetime, today: date
) -> int:
    """Przelicz sondy zmian; zwraca liczbę zapisanych wyników.

    Sonda liczy dane całej firmy, więc ten sam klucz liczymy raz na wywołanie.
    Wiersze sond, których zmiana już nie wymienia, znikają.
    """

    ids = sorted(set(change_ids))
    if not ids:
        return 0
    changes = (
        await db.execute(
            select(LawChange.id, LawChange.probe_keys).where(LawChange.id.in_(ids))
        )
    ).all()
    cache: dict[str, ProbeResult] = {}
    written = 0
    for change_id, raw_keys in changes:
        keys = known_keys(raw_keys or [])
        stale = delete(LawChangeProbe).where(LawChangeProbe.change_id == change_id)
        if keys:
            stale = stale.where(LawChangeProbe.probe_key.not_in(keys))
        await db.execute(stale)
        for key in keys:
            if key not in cache:
                cache[key] = await compute(db, key, today)
            result = cache[key]
            statement = insert(LawChangeProbe).values(
                change_id=change_id,
                probe_key=key,
                value=result.value,
                text=result.text[: schema.PROBE_TEXT_MAX],
                link=result.link,
                computed_at=now,
            )
            await db.execute(
                statement.on_conflict_do_update(
                    constraint="uq_law_change_probes_change_key",
                    set_={
                        "value": statement.excluded.value,
                        "text": statement.excluded.text,
                        "link": statement.excluded.link,
                        "computed_at": now,
                    },
                )
            )
            written += 1
    await db.commit()
    logger.info(
        "law_radar probes changes=%d results=%d keys=%d",
        len(changes),
        written,
        len(cache),
    )
    return written


async def open_change_ids(db: AsyncSession) -> list[int]:
    return list(
        (
            await db.execute(
                select(LawChange.id).where(LawChange.status.in_(schema.OPEN_STATUSES))
            )
        ).scalars()
    )


async def oldest_open_computed_at(db: AsyncSession) -> Optional[datetime]:
    """Najstarszy wynik sondy otwartej zmiany: dzienny bieg pętli liczy od niego."""

    return await db.scalar(
        select(func.min(LawChangeProbe.computed_at))
        .join(LawChange, LawChange.id == LawChangeProbe.change_id)
        .where(LawChange.status.in_(schema.OPEN_STATUSES))
    )
