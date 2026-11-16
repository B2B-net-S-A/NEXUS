"""Roczny plik JPK_ST_KR(1) z ewidencji środków trwałych K6 (K8c).

Decyzja Artura z 16.11.2026: plik powstaje już teraz, choć rozporządzenie MF
z 29.10.2026 (Dz.U. 2026 poz. 1444) zwalnia z jego przesyłania za lata
2026–2028 — NEXUS niczego nie wysyła, plik służy sprawdzeniu ewidencji
i porównaniu z Symfonią Środki Trwałe. Schemat MF JPK_ST_KR(1) v1-0 (wzór
2024/04/24/04242) w ``jpk_kr_schema/schemat_st_kr.xsd`` (pobrany z gov.pl
16.11.2026, importy jak w JPK_KR_PD).

Zasady (pytania i odpowiedzi MF JPK_PD, 16.11.2026):

* Środki na stanie w roku: przyjęte do końca roku, a zbyte nie wcześniej niż
  w tym roku (pyt. 49, 113). Całkowicie umorzone też.
* Strona rachunkowa z planu bilansowego K6: ``E_21`` wartość na początek roku
  (albo przyjęcia) bez zmian z roku, ``E_24`` ulepszenia z roku, ``E_26`` odpisy
  roku, ``E_27`` umorzenie narastająco z rokiem (pyt. 103, 107), ``E_25B`` =
  odpis jednorazowy z roku.
* **CIT estoński** (pyt. 137): ``E_9_1`` = X, ``E_10A`` = stawka z wykazu
  (plan podatkowy K6), ``E_10B`` = 0, ``E_11`` = 0, ``E_17`` = X, ``E_19`` = 0;
  ``E_12`` i ``E_20`` — wartość i umorzenie podatkowe na koniec roku przed
  ryczałtem dla środków przyjętych przed nim, 0 dla przyjętych w czasie
  ryczałtu. Zasady ogólne = plik się nie składa (jak JPK_KR_PD).
* ``E_5`` = numer OT z NEXUSA; środek ze stanem z Symfonii nie ma OT w NEXUSIE
  — wpis „stan z Symfonii ŚT” i ostrzeżenie. ``E_2``/``E_3`` = data przyjęcia
  (K6 nie trzyma osobno daty nabycia). ``E_6`` = F, gdy OT jest z faktury
  z kolejki kosztów, inaczej I.
* Zbycie w roku: ``E_28`` data, ``E_29`` S (sprzedaż) albo I (likwidacja),
  ``E_30`` numer dokumentu LT/SP.

Plik nie zawiera danych osób zespołu — pobiera każdy z modułem Sprawozdań.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from lxml import etree
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ledger_assets import LedgerAsset
from app.services.finance_ledger.costs import LedgerError
from app.services.hr.payroll_lists import parameters as payroll_parameters
from app.services.ledger import depreciation, jpk_kr
from app.services.ledger.assets import operations_of, plan_input
from app.services.ledger.depreciation import PlanInput
from app.services.ledger.jpk import money
from app.services.ledger.settings import JpkKrSettings, LedgerSettings

NS = "http://jpk.mf.gov.pl/wzor/2024/04/24/04242/"
SCHEMA = jpk_kr.SCHEMA_DIR / "schemat_st_kr.xsd"
FROM_SYMFONIA = "stan z Symfonii ŚT"
RATE_MAX = Decimal(100)


@dataclass(frozen=True)
class Asset:
    id: int
    inventory: str
    name: str
    kind: str
    kst: Optional[str]
    accepted_on: date
    balance: PlanInput
    tax: PlanInput
    balance_rate: Decimal
    tax_rate: Decimal
    status: str
    disposed_on: Optional[date]
    ot_number: Optional[str] = None
    from_invoice: bool = False
    disposal_number: Optional[str] = None


@dataclass(frozen=True)
class Entry:
    """Wiersz ``ST_KR`` (kwoty w groszach)."""

    asset: Asset
    balance_start: int
    balance_changes: int
    balance_year: int
    balance_accumulated: int
    balance_one_off: int
    tax_value: int
    tax_accumulated: int


def in_register(asset: Asset, year: int) -> bool:
    return asset.accepted_on <= date(year, 12, 31) and (
        asset.disposed_on is None or asset.disposed_on >= date(year, 1, 1)
    )


def _improvements(plan: PlanInput, start: date, end: date) -> int:
    return sum(amount for day, amount in plan.improvements if start <= day <= end)


def _start_value(plan: PlanInput, year: int) -> int:
    """Wartość początkowa na pierwszy dzień roku, bez zmian z roku (pyt. 107)."""

    if plan.accepted.year >= year:
        return plan.initial
    return depreciation.value_at(plan, date(year - 1, 12, 1))


def _accumulated(plan: PlanInput, month: date) -> int:
    rows = depreciation.schedule(plan, until=month)
    return min(
        depreciation.accumulated_at(plan, rows, month),
        depreciation.value_at(plan, month),
    )


def entry(asset: Asset, *, year: int, estonian_since: int) -> Entry:
    december = date(year, 12, 1)
    rows = depreciation.schedule(asset.balance, until=december)
    in_year = [row for row in rows if row.month.year == year]
    one_off = (
        sum(row.amount for row in in_year) if asset.balance.method == "one_off" else 0
    )
    cutoff = date(estonian_since - 1, 12, 1)
    before = asset.accepted_on < date(estonian_since, 1, 1)
    if before:
        opening = asset.tax.opening
        if opening is not None and depreciation.first_of(opening.month) > cutoff:
            # Stan z Symfonii późniejszy niż początek ryczałtu: umorzenie
            # podatkowe z tego stanu (pod ryczałtem odpisy podatkowe stoją).
            tax_accumulated = opening.accumulated
        else:
            tax_accumulated = _accumulated(asset.tax, cutoff)
        tax_value = depreciation.value_at(asset.tax, cutoff)
    else:
        tax_accumulated = tax_value = 0
    return Entry(
        asset=asset,
        balance_start=_start_value(asset.balance, year),
        balance_changes=_improvements(
            asset.balance, date(year, 1, 1), date(year, 12, 31)
        ),
        balance_year=sum(row.amount for row in in_year),
        balance_accumulated=_accumulated(asset.balance, december),
        balance_one_off=one_off,
        tax_value=tax_value,
        tax_accumulated=tax_accumulated,
    )


def problems(
    *,
    year: int,
    entries: list[Entry],
    company: payroll_parameters.Company,
    settings: JpkKrSettings,
) -> list[jpk_kr.Problem]:
    out: list[jpk_kr.Problem] = []
    if year > jpk_kr.SCHEMA_LAST_YEAR:
        out.append(
            jpk_kr.Problem(
                "year", f"Schemat MF przyjmuje daty do {jpk_kr.SCHEMA_LAST_YEAR} roku."
            )
        )
    if not entries:
        out.append(
            jpk_kr.Problem(
                "empty", "W ewidencji K6 nie ma środków na stanie w tym roku."
            )
        )
    no_kst = [
        item.asset.inventory
        for item in entries
        if item.asset.kind == "fixed" and not item.asset.kst
    ]
    if no_kst:
        out.append(
            jpk_kr.Problem("kst", "Środki trwałe bez symbolu KŚT.", tuple(no_kst[:50]))
        )
    if not settings.estonian:
        out.append(
            jpk_kr.Problem(
                "estonian",
                "NEXUS składa JPK_ST_KR tylko dla CIT estońskiego — amortyzacja "
                "podatkowa na zasadach ogólnych jest poza NEXUSEM.",
            )
        )
    missing = jpk_kr.company_missing(company, settings)
    if missing:
        out.append(
            jpk_kr.Problem("company", "Brakuje danych podatnika.", tuple(missing))
        )
    return out


def warnings(entries: list[Entry]) -> list[str]:
    from_symfonia = [
        item.asset.inventory for item in entries if not item.asset.ot_number
    ]
    out = [
        "Data nabycia (E_2/E_3) = data przyjęcia z ewidencji K6.",
    ]
    if from_symfonia:
        out.append(
            "Środki ze stanem z Symfonii nie mają OT w NEXUSIE — w E_5 wpis "
            f"„{FROM_SYMFONIA}” ({len(from_symfonia)})."
        )
    return out


def _rate(value: Decimal) -> str:
    return f"{min(max(value, Decimal(0)), RATE_MAX):.2f}"


def build(
    *,
    year: int,
    entries: list[Entry],
    company: payroll_parameters.Company,
    settings: JpkKrSettings,
    correction: bool,
    now: datetime,
) -> bytes:
    """XML JPK_ST_KR(1) (wariant CIT estońskiego, pyt. 137)."""

    sub = jpk_kr.sub
    root = etree.Element(f"{{{NS}}}JPK", nsmap={None: NS, "etd": jpk_kr.ETD})
    jpk_kr.header(
        root,
        code="JPK_ST",
        system_code="JPK_ST_KR (1)",
        version="1-0",
        ns=NS,
        year_from=date(year, 1, 1),
        year_to=date(year, 12, 31),
        correction=correction,
        now=now,
        tax_office=company.tax_office_code or "",
        with_period=False,
    )
    jpk_kr.subject(
        root, ns=NS, company=company, settings=settings, estonian_marker=False
    )
    for item in entries:
        asset = item.asset
        node = sub(root, "ST_KR", ns=NS)
        sub(node, "E_1", jpk_kr.clean(asset.inventory, jpk_kr.TEXT_MAX), ns=NS)
        sub(
            node,
            "E_2" if asset.kind == "fixed" else "E_3",
            asset.accepted_on.isoformat(),
            ns=NS,
        )
        sub(node, "E_4", asset.accepted_on.isoformat(), ns=NS)
        sub(node, "E_5", asset.ot_number or FROM_SYMFONIA, ns=NS)
        sub(node, "E_6", "F" if asset.from_invoice else "I", ns=NS)
        sub(
            node,
            "E_7",
            jpk_kr.clean(asset.name, jpk_kr.TEXT_MAX) or asset.inventory,
            ns=NS,
        )
        if asset.kind == "fixed" and asset.kst:
            sub(node, "E_8", asset.kst, ns=NS)
        sub(node, "E_9_1", "X", ns=NS)
        sub(node, "E_10A", _rate(asset.tax_rate), ns=NS)
        sub(node, "E_10B", money(0), ns=NS)
        sub(node, "E_11", _rate(Decimal(0)), ns=NS)
        sub(node, "E_12", money(item.tax_value), ns=NS)
        sub(node, "E_17", "X", ns=NS)
        sub(node, "E_19", money(0), ns=NS)
        sub(node, "E_20", money(item.tax_accumulated), ns=NS)
        sub(node, "E_21", money(item.balance_start), ns=NS)
        if item.balance_changes:
            sub(node, "E_24", money(item.balance_changes), ns=NS)
        sub(node, "E_25A", _rate(asset.balance_rate), ns=NS)
        sub(node, "E_25B", money(item.balance_one_off), ns=NS)
        sub(node, "E_26", money(item.balance_year), ns=NS)
        sub(node, "E_27", money(item.balance_accumulated), ns=NS)
        if asset.disposed_on is not None and asset.disposed_on.year == year:
            sub(node, "E_28", asset.disposed_on.isoformat(), ns=NS)
            sub(node, "E_29", "S" if asset.status == "sold" else "I", ns=NS)
            sub(node, "E_30", asset.disposal_number or asset.inventory, ns=NS)
        sub(node, "E_32", 2, ns=NS)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


# ── Baza ─────────────────────────────────────────────────────────────────────


async def load_assets(db: AsyncSession, year: int) -> list[Asset]:
    rows = (
        await db.scalars(
            select(LedgerAsset)
            .where(LedgerAsset.accepted_on <= date(year, 12, 31))
            .order_by(LedgerAsset.inventory_number, LedgerAsset.id)
        )
    ).all()
    operations = await operations_of(db, [row.id for row in rows])
    out = []
    for row in rows:
        ops = operations.get(row.id, [])
        ot = next((op for op in ops if op.op_type == "OT"), None)
        disposal = next(
            (op for op in reversed(ops) if op.op_type in ("LT", "SP")), None
        )
        asset = Asset(
            id=row.id,
            inventory=row.inventory_number,
            name=row.name,
            kind=row.kind,
            kst=row.kst,
            accepted_on=row.accepted_on,
            balance=plan_input(row, ops),
            tax=plan_input(row, ops, tax=True),
            balance_rate=Decimal(row.balance_rate),
            tax_rate=Decimal(row.tax_rate),
            status=row.status,
            disposed_on=row.disposed_on,
            ot_number=ot.number if ot is not None else None,
            from_invoice=ot is not None and ot.cost_entry_id is not None,
            disposal_number=disposal.number if disposal is not None else None,
        )
        if in_register(asset, year):
            out.append(asset)
    return out


async def prepare(
    db: AsyncSession, settings: LedgerSettings, *, year: int
) -> tuple[list[Entry], payroll_parameters.Company, list[jpk_kr.Problem]]:
    since = settings.jpk_kr.estonian_since or year
    entries = [
        entry(asset, year=year, estonian_since=since)
        for asset in await load_assets(db, year)
    ]
    company = await payroll_parameters.load_company(db)
    return (
        entries,
        company,
        problems(year=year, entries=entries, company=company, settings=settings.jpk_kr),
    )


async def overview(
    db: AsyncSession, settings: LedgerSettings, *, year: int
) -> dict[str, Any]:
    entries, _, found = await prepare(db, settings, year=year)
    return {
        "assets": len(entries),
        "problems": [jpk_kr.problem_json(item) for item in found],
        "warnings": warnings(entries),
        "ready": not found,
        "file_name": f"JPK_ST_KR_{year}.xml",
    }


async def file(
    db: AsyncSession,
    settings: LedgerSettings,
    *,
    year: int,
    correction: bool,
    now: datetime,
) -> tuple[str, bytes]:
    entries, company, found = await prepare(db, settings, year=year)
    if found:
        raise LedgerError(
            "Plik JPK_ST_KR się nie składa — " + jpk_kr.problems_text(found),
            status=422,
        )
    content = build(
        year=year,
        entries=entries,
        company=company,
        settings=settings.jpk_kr,
        correction=correction,
        now=now,
    )
    errors = jpk_kr.validate(content, SCHEMA)
    if errors:
        raise LedgerError(
            f"Plik JPK_ST_KR nie przechodzi schematu MF — {' | '.join(errors)}",
            status=422,
        )
    return f"JPK_ST_KR_{year}.xml", content
