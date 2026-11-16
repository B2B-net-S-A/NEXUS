"""Bilans i rachunek zysków i strat (K8a) z zatwierdzonych zapisów księgi.

* RZiS w **wariancie porównawczym** (decyzja Artura z 16.11.2026) za miesiące
  ``od``–``do``; bilans na koniec miesiąca ``do`` (BO + obroty od stycznia).
* Pozycja konta to znacznik MF (``markers``). Konto bilansowe z parą znaczników
  idzie pod znacznik Wn albo Ma według salda **każdej analityki** (należność
  jednego kontrahenta nie znosi się ze zobowiązaniem wobec drugiego).
* „Zysk (strata) netto” w bilansie (BPAVI) liczy się w trakcie roku z kont
  wynikowych od stycznia — razem z kontami 5 i 490 (te w porównawczym RZiS
  się nie pokazują, ale ich saldo różne od zera rozjechałoby bilans) —
  plus saldo konta z BPAVI (860 po zamknięciu roku).
* Konto z saldem albo obrotem bez znacznika (albo ze znacznikiem „INNE”, albo
  ze znacznikiem tylko wariantu kalkulacyjnego) to **problem**: sprawozdanie
  się nie domknie, plik e-Sprawozdania (K8b) nie powstanie.
* **Płace (D2):** kwoty pozycji to sumy całej księgi, jak sumy kont
  w obrotach i saldach. Rozbicie pozycji na konta i lista problemów schodzą
  najniżej do konta syntetycznego (pierwszy segment numeru), bo analityka
  rozrachunków z pracownikami to często jedna osoba.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance_posting import FinanceAccount
from app.models.ledger import LedgerDocument, LedgerLine, LedgerPeriod, LedgerYear
from app.services.finance_ledger.costs import LedgerError
from app.services.ledger import markers
from app.services.ledger.markers import (
    GROUP_ASSETS,
    GROUP_LIABILITIES,
    GROUP_RESULT,
    Marker,
)

ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII")
LETTERS = "abcdefghijklmnopqrstuvwxyz"
NET_RESULT = "BPAVI"
#: Sekcje RZiS w wariancie porównawczym: litera z kodu (``RPB…`` → B) i znak
#: (+1 przychody: Ma − Wn, −1 koszty: Wn − Ma).
INCOME_SECTIONS = {"A": 1, "D": 1, "G": 1}
COST_SECTIONS = {"B": -1, "E": -1, "H": -1, "J": -1, "K": -1}
COMPUTED = (
    ("C", "Zysk (strata) ze sprzedaży (A − B)", ("A", "-B")),
    ("F", "Zysk (strata) z działalności operacyjnej (C + D − E)", ("C", "D", "-E")),
    ("I", "Zysk (strata) brutto (F + G − H)", ("F", "G", "-H")),
    ("L", "Zysk (strata) netto (I − J − K)", ("I", "-J", "-K")),
)
ORDER = ("A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L")


def _range(month_from: Optional[int], month_to: Optional[int]) -> tuple[int, int]:
    start = month_from or 1
    end = month_to or 12
    if not (1 <= start <= 12 and 1 <= end <= 12) or start > end:
        raise LedgerError("Niepoprawny zakres miesięcy.", status=422)
    return start, end


@dataclass
class Node:
    label: str
    level: int
    amount: int = 0
    codes: list[str] = field(default_factory=list)
    accounts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    children: dict[str, "Node"] = field(default_factory=dict)


def _number(level: int, index: int, scheme: str) -> str:
    if scheme == "balance":
        if level == 1:
            return LETTERS[index].upper()
        if level == 2:
            return ROMAN[index] if index < len(ROMAN) else str(index + 1)
        if level == 3:
            return str(index + 1)
        if level == 4:
            return f"{LETTERS[index]})"
        return "–"
    return ROMAN[index] if level == 2 and index < len(ROMAN) else ""


def _skeleton(group_filter: Any) -> Node:
    """Drzewo pozycji ze słownika MF (wszystkie pozycje, także puste)."""

    root = Node(label="", level=0)
    for marker in markers.dictionary().values():
        if not group_filter(marker):
            continue
        node = root
        for depth, part in enumerate(marker.position, start=1):
            label = part.split(" / ")[0]
            node = node.children.setdefault(label, Node(label=label, level=depth))
        node.codes.append(marker.code)
    return root


def _place(root: Node, marker: Marker, amount: int, account: str) -> None:
    node = root
    for part in marker.position:
        node = node.children[part.split(" / ")[0]]
        node.amount += amount
        node.accounts[account] += amount
    root.amount += amount


def _dump_node(
    node: Node, number: str, scheme: str, names: dict[str, str]
) -> dict[str, Any]:
    return {
        "number": number,
        "label": node.label,
        "level": node.level,
        "amount": node.amount,
        "codes": node.codes,
        "accounts": [
            {"account": account, "name": names.get(account), "amount": value}
            for account, value in sorted(node.accounts.items())
            if value
        ]
        if not node.children
        else [],
        "children": _dump(node, scheme, names),
    }


def _dump(node: Node, scheme: str, names: dict[str, str]) -> list[dict[str, Any]]:
    return [
        _dump_node(child, _number(child.level, index, scheme), scheme, names)
        for index, child in enumerate(node.children.values())
    ]


async def _amounts(
    db: AsyncSession, year_id: int, start: int, end: int
) -> list[tuple[str, int, int]]:
    """(konto analityczne, saldo końcowe Wn−Ma na ``do``, saldo obrotów od–do)."""

    is_bo = LedgerDocument.doc_type == "BO"
    signed = case(
        (LedgerLine.side == "debit", LedgerLine.amount), else_=-LedgerLine.amount
    )
    rows = await db.execute(
        select(
            LedgerLine.account,
            func.coalesce(
                func.sum(case((is_bo | (LedgerPeriod.month <= end), signed), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (~is_bo & LedgerPeriod.month.between(start, end), signed),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .join(LedgerDocument, LedgerDocument.id == LedgerLine.document_id)
        .join(LedgerPeriod, LedgerPeriod.id == LedgerDocument.period_id)
        .where(LedgerDocument.year_id == year_id, LedgerDocument.status == "approved")
        .group_by(LedgerLine.account)
    )
    return [
        (account, int(closing), int(turnover))
        for account, closing, turnover in rows.all()
    ]


async def plan_report_lines(
    db: AsyncSession,
) -> tuple[dict[str, Optional[str]], dict[str, str]]:
    rows = (
        await db.execute(
            select(
                FinanceAccount.number, FinanceAccount.name, FinanceAccount.report_line
            )
        )
    ).all()
    return {number: line for number, _, line in rows}, {
        number: name for number, name, _ in rows
    }


def build(
    amounts: list[tuple[str, int, int]],
    own: dict[str, Optional[str]],
    names: dict[str, str],
    *,
    ytd_result: dict[str, int],
) -> dict[str, Any]:
    """Czyste wyliczenie (testy bez bazy).

    ``amounts``: (konto, saldo na koniec ``do``, saldo obrotów ``od``–``do``),
    ``ytd_result``: saldo obrotów od stycznia do ``do`` dla każdego konta
    (do „Zysku netto” w bilansie).
    """

    known = markers.dictionary()
    assets = _skeleton(lambda m: m.group == GROUP_ASSETS)
    liabilities = _skeleton(lambda m: m.group == GROUP_LIABILITIES)
    income = _skeleton(lambda m: m.comparative)
    problems: dict[tuple[str, str], int] = defaultdict(int)
    net_result = 0
    allocation_residual = 0
    first_names = {**names, "wynik": "Wynik z kont wynikowych od stycznia"}

    for account, closing, turnover in amounts:
        head = markers.first_segment(account)
        ytd = ytd_result.get(account, 0)
        if markers.excluded(account):
            if not head.startswith(markers.OFF_BALANCE_PREFIX):
                allocation_residual += ytd
                net_result -= ytd
            continue
        pair, _ = markers.resolve(account, own)
        if pair is None:
            if closing or turnover:
                problems[(head, "Konto bez pozycji sprawozdania")] += (
                    closing or turnover
                )
            continue
        code = pair.debit if closing >= 0 else pair.credit
        marker = known[code]
        if marker.group == GROUP_ASSETS:
            if closing:
                _place(assets, marker, closing, head)
        elif marker.group == GROUP_LIABILITIES:
            if closing:
                _place(liabilities, marker, -closing, head)
        elif marker.group == GROUP_RESULT:
            net_result -= ytd
            if closing != ytd:
                # Saldo z BO na koncie wynikowym (BO z niezamkniętego roku) nie ma
                # pozycji ani w RZiS, ani w bilansie — bez tego bilans by się
                # rozjechał bez wyjaśnienia (przegląd K8a).
                problems[(head, "Konto wynikowe z saldem w bilansie otwarcia")] += (
                    closing - ytd
                )
            if not marker.comparative:
                if turnover:
                    problems[(head, "Znacznik tylko wariantu kalkulacyjnego")] += (
                        turnover
                    )
                continue
            if turnover:
                section = code[2]
                sign = INCOME_SECTIONS.get(section) or COST_SECTIONS.get(section, -1)
                # Przychody: Ma − Wn; koszty: Wn − Ma.
                value = -turnover if sign > 0 else turnover
                _place(income, marker, value, head)
        elif closing or turnover:
            problems[(head, "Znacznik „INNE” — poza sprawozdaniem")] += (
                closing or turnover
            )

    if net_result:
        _place(liabilities, known[NET_RESULT], net_result, "wynik")

    by_letter: dict[str, int] = {}
    section_nodes: dict[str, Node] = {}
    for marker in known.values():
        if marker.comparative:
            label = marker.position[0].split(" / ")[0]
            section_nodes.setdefault(marker.code[2], income.children[label])
    for letter, node in section_nodes.items():
        by_letter[letter] = node.amount
    for letter, _label, parts in COMPUTED:
        by_letter[letter] = sum(
            -by_letter.get(part[1:], 0)
            if part.startswith("-")
            else by_letter.get(part, 0)
            for part in parts
        )
    computed_labels = {letter: label for letter, label, _ in COMPUTED}
    lines: list[dict[str, Any]] = []
    for letter in ORDER:
        node = section_nodes.get(letter)
        if node is not None:
            line = _dump_node(node, letter, "income", first_names)
        else:
            line = {
                "number": letter,
                "label": computed_labels[letter],
                "level": 1,
                "amount": by_letter[letter],
                "codes": [],
                "accounts": [],
                "children": [],
            }
        line["computed"] = node is None
        lines.append(line)

    assets_total = assets.amount
    liabilities_total = liabilities.amount
    issues = [
        {
            "account": head,
            "name": first_names.get(head),
            "problem": problem,
            "amount": value,
        }
        for (head, problem), value in sorted(problems.items())
    ]
    warnings = []
    if allocation_residual:
        warnings.append(
            {
                "code": "allocation_residual",
                "message": "Konta 5 i 490 nie znoszą się — rozliczenie kosztów na MPK "
                "nie jest kompletne; różnica jest w zysku netto bilansu, a nie w RZiS.",
                "amount": allocation_residual,
            }
        )
    return {
        "balance": {
            "assets": _dump(assets, "balance", first_names),
            "liabilities": _dump(liabilities, "balance", first_names),
            "assets_total": assets_total,
            "liabilities_total": liabilities_total,
            "balanced": assets_total == liabilities_total,
        },
        "income": {
            "variant": "comparative",
            "lines": lines,
            "net_result": by_letter["L"],
        },
        "issues": issues,
        "warnings": warnings,
        "complete": not issues,
    }


async def statements(
    db: AsyncSession,
    *,
    year: int,
    month_from: Optional[int] = None,
    month_to: Optional[int] = None,
) -> dict[str, Any]:
    start, end = _range(month_from, month_to)
    year_row = await db.scalar(select(LedgerYear).where(LedgerYear.year == year))
    if year_row is None:
        raise LedgerError(f"Nie ma roku obrotowego {year}.", status=404)
    amounts = await _amounts(db, year_row.id, start, end)
    ytd = (
        {account: turnover for account, _, turnover in amounts}
        if start == 1
        else {
            account: turnover
            for account, _, turnover in await _amounts(db, year_row.id, 1, end)
        }
    )
    own, names = await plan_report_lines(db)
    result = build(amounts, own, names, ytd_result=ytd)
    return {"year": year, "month_from": start, "month_to": end, **result}


async def account_positions(db: AsyncSession) -> list[dict[str, Any]]:
    """Plan kont z pozycją sprawozdania i jej źródłem (ekran „Pozycje kont”)."""

    rows = (
        await db.execute(
            select(
                FinanceAccount.id,
                FinanceAccount.number,
                FinanceAccount.name,
                FinanceAccount.account_type,
                FinanceAccount.active,
                FinanceAccount.report_line,
            ).order_by(FinanceAccount.number)
        )
    ).all()
    own = {row.number: row.report_line for row in rows}
    out = []
    for row in rows:
        pair, source = markers.resolve(row.number, own)
        out.append(
            {
                "id": row.id,
                "number": row.number,
                "name": row.name,
                "account_type": row.account_type,
                "active": row.active,
                "report_line": row.report_line,
                "source": source,
                "excluded": markers.excluded(row.number),
                "position": markers.describe(pair),
            }
        )
    return out
