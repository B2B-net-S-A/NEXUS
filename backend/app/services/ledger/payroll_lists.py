"""Lista płac z pliku Enovy → dokument LP w buforze (K3c, do czasu Płac w NEXUSIE — K7).

Płace liczy Enova 365; księgowa przepisywała każdą listę do Symfonii ręcznie.
Tu: plik listy z Enovy (XLSX albo CSV, wiersz na osobę) → podgląd sum →
dokument LP w buforze z wrażliwością płacową (D2): wczytują, widzą
i zatwierdzają go tylko Płace i administrator. Do Symfonii idzie domyślnie
paczką płacową (K3b, rodzaj „Listy płac”).

Formatu eksportu Enovy nie znamy z próbki, więc kolumny rozpoznajemy po
słowach w nagłówku, nie po przedrostkach: nagłówek ze znacznikiem pracodawcy
(„pracodawca”, „firma”, „płatnik”, „zakład”) nigdy nie trafia do kwot
pracownika, a taki, którego nie umiemy przypisać, odrzuca plik. Podstawy
(„Podstawa…”), koszty uzyskania i składniki brutto pomijamy. Dwie kolumny tej
samej pozycji = odmowa (poza potrąceniami, które się sumują). Kolumna łączna
(„ZUS pracownika”, „ZUS pracodawcy”) obok niepełnego rozbicia = odmowa, obok
pełnego — musi się z nim zgadzać co do grosza.

Każda niezgodność, przez którą dokument wyszedłby zbilansowany, ale z innymi
kwotami niż lista, blokuje zapis (przegląd K3c 14.11.2026): brutto −
potrącenia ≠ „Do wypłaty”, wiersz „Razem” ≠ suma osób, brak kolumny „Do
wypłaty”, składki ZUS pracownika bez żadnej składki pracodawcy. Wiersz sumy
poznajemy po pierwszym słowie („Razem”, „Suma”…) w dowolnej komórce tekstowej
— „Sumała” to nazwisko, nie suma.

Dekret (sumy listy; kolumna „Wydział”/„MPK” daje MPK pozycji kosztowych):

* Wn wynagrodzenia (brutto) / Ma rozrachunki z tytułu wynagrodzeń (brutto),
* Wn rozrachunki z tytułu wynagrodzeń (potrącenia: składki pracownika,
  zdrowotna, zaliczka PIT, PPK pracownika, inne potrącenia) / Ma ZUS, Ma US,
  Ma PPK, Ma inne potrącenia,
* Wn składki i PPK pracodawcy (koszt) / Ma ZUS (emerytalna, rentowa,
  wypadkowa, FP, FS, FGŚP, FEP), Ma PPK.

Na rozrachunkach z tytułu wynagrodzeń zostaje netto do wypłaty — rozliczy je
wyciąg (K4). Źródło: ``payroll_list`` / ``RRRR-MM:<lista>``; ponowny import
tej samej listy przebudowuje szkic, zatwierdzony LP poprawia się stornem (409).
"""

from __future__ import annotations

import hashlib
import re
from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ledger import LedgerDocument
from app.services.finance_ledger import identifiers
from app.services.finance_ledger.costs import LedgerError
from app.services.finance_ledger.counterparty_import import (
    ImportFileError,
    _sheet_rows,  # czytnik XLSX/CSV ze strażnikiem bomby ZIP (E1)
)
from app.services.ledger import documents, engine
from app.services.ledger.documents import DocumentSpec, Viewer
from app.services.ledger.engine import LineIn
from app.services.ledger.opening import parse_amount
from app.services.ledger.settings import PayrollAccounts
from app.services.ledger_schema import MPK_MAX

SOURCE_TYPE = "payroll_list"
MAX_BYTES = 5 * 1024 * 1024
HEADER_SCAN_ROWS = 15
LIST_NAME_MAX = 40
MESSAGES_MAX = 50
TOTAL_MARKERS = frozenset({"razem", "suma", "ogolem", "total", "lacznie"})
EMPLOYER_MARKERS = ("pracodaw", "firm", "platnik", "zaklad")
#: Nagłówki pomijane przed czymkolwiek innym (podstawy, koszty uzyskania,
#: numery) — mogą zawierać słowa składek („Podstawa ub. zdrowotnego”).
IGNORED_FIRST = (
    "podstaw",
    "koszt",
    "kwotawoln",
    "kwotazmniejsz",
    "ulga",
    "lp",
    "nr",
    "kod",
    "stanowisko",
    "etat",
)
#: Składniki brutto i świadczenia — pomijane po sprawdzeniu „brutto”/„netto”.
IGNORED_AFTER = ("wynagrodzenie", "zasilek", "przychod", "dochod", "premia", "dodatek")
PERSON_WORDS = frozenset(
    {"pracownik", "osoba", "nazwiskoiimie", "imieinazwisko", "imienazwisko"}
)
MPK_PREFIXES = (
    "wydzial",
    "dzial",
    "mpk",
    "pion",
    "miejscepowstaniakosztow",
    "centrumkosztow",
)
#: Klucz dla nagłówka z kwotą pracodawcy, której nie umiemy przypisać.
UNKNOWN_EMPLOYER = "unknown_employer"

COLUMN_LABELS: dict[str, str] = {
    "gross": "Brutto",
    "emp_pension": "Emerytalne (pracownik)",
    "emp_disability": "Rentowe (pracownik)",
    "emp_sickness": "Chorobowe",
    "emp_social": "ZUS pracownika (razem)",
    "health": "Zdrowotne",
    "pit": "Zaliczka PIT",
    "ppk_emp": "PPK pracownika",
    "deductions": "Inne potrącenia",
    "net": "Do wypłaty",
    "net_alt": "Netto",
    "er_pension": "Emerytalne (pracodawca)",
    "er_disability": "Rentowe (pracodawca)",
    "accident": "Wypadkowe",
    "er_social": "ZUS pracodawcy (razem)",
    "fp": "FP",
    "fs": "FS",
    "fgsp": "FGŚP",
    "fep": "FEP",
    "ppk_er": "PPK pracodawcy",
    "person": "Pracownik",
    "mpk": "Wydział / MPK",
}
TEXT_COLUMNS = frozenset({"person", "mpk"})
EMPLOYEE_PARTS = ("emp_pension", "emp_disability", "emp_sickness")
EMPLOYER_PARTS = ("er_pension", "er_disability", "accident")
EMPLOYER_KEYS = frozenset(
    {*EMPLOYER_PARTS, "er_social", "fp", "fs", "fgsp", "fep", "ppk_er"}
)
#: Pozycje, które mogą mieć kilka kolumn (sumują się).
SUMMED = frozenset({"deductions"})
_TOKENS = re.compile(r"[^\w]+", re.UNICODE)


def column_for(header: str) -> Optional[str]:
    """Nagłówek → klucz kolumny (``None`` = kolumna, której nie czytamy).

    Pracodawca ma pierwszeństwo: nagłówek ze znacznikiem pracodawcy trafia do
    kwot pracodawcy albo do ``UNKNOWN_EMPLOYER`` (odmowa pliku), nigdy do
    pracownika.
    """

    word = identifiers.fold(header)
    if not word:
        return None
    if word in PERSON_WORDS or word.startswith(("nazwisko", "imie")):
        return "person"
    if word.startswith(MPK_PREFIXES):
        return "mpk"
    if word.startswith(IGNORED_FIRST):
        return None
    employer = any(marker in word for marker in EMPLOYER_MARKERS)
    if not employer:
        if "brutto" in word:
            return "gross"
        if "dowyplaty" in word or "wyplatanetto" in word or word == "wyplata":
            return "net"
        if "netto" in word:
            return "net_alt"
    if word.startswith(IGNORED_AFTER):
        return None
    if "fgsp" in word or "funduszgwarant" in word:
        return "fgsp"
    if word.startswith("fep") or "pomost" in word:
        return "fep"
    if word.startswith("fp") or "funduszprac" in word:
        return "fp"
    if word.startswith("fs") or "solidarn" in word:
        return "fs"
    if "wypadk" in word:
        return "accident"
    if "ppk" in word:
        return "ppk_er" if employer else "ppk_emp"
    if "emeryt" in word:
        return "er_pension" if employer else "emp_pension"
    if "rentow" in word:
        return "er_disability" if employer else "emp_disability"
    if "chorob" in word:
        return UNKNOWN_EMPLOYER if employer else "emp_sickness"
    if "zdrow" in word:
        return UNKNOWN_EMPLOYER if employer else "health"
    if "zus" in word or "spoleczn" in word or word.startswith("skladk"):
        return "er_social" if employer else "emp_social"
    if "zaliczk" in word or "podatek" in word or word.startswith("pit"):
        return UNKNOWN_EMPLOYER if employer else "pit"
    if "potrac" in word:
        return "deductions"
    return UNKNOWN_EMPLOYER if employer else None


@dataclass
class PayrollRow:
    line: int
    mpk: Optional[str]
    amounts: dict[str, int]


@dataclass
class ParsedList:
    headers: dict[str, str] = field(default_factory=dict)
    rows: list[PayrollRow] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    #: Braki całego pliku, które blokują zapis (np. brak kolumny „Do wypłaty”).
    problems: list[str] = field(default_factory=list)
    skipped: int = 0


def _header(rows: list[list[str]]) -> tuple[int, dict[int, str]]:
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        columns: dict[int, str] = {}
        seen: dict[str, str] = {}
        for position, raw in enumerate(row):
            key = column_for(raw)
            if key is None:
                continue
            if key == UNKNOWN_EMPLOYER:
                raise ImportFileError(
                    f"Kolumna „{raw.strip()}” wygląda na kwotę pracodawcy, ale nie "
                    "wiadomo którą — nazwij ją jak składkę (np. „Emerytalne "
                    "pracodawca”, „FP pracodawca”, „PPK pracodawcy”)."
                )
            if key in seen and key not in SUMMED:
                raise ImportFileError(
                    f"Kolumny „{seen[key]}” i „{raw.strip()}” to w pliku ta sama "
                    f"pozycja ({COLUMN_LABELS[key]}) — nazwij je jednoznacznie (np. "
                    "„Emerytalne pracodawca”), inaczej jedna z kwot by przepadła."
                )
            seen.setdefault(key, raw.strip())
            columns[position] = key
        if "gross" in columns.values():
            _check_breakdown(set(columns.values()), seen)
            return index, columns
    raise ImportFileError(
        "Nie znaleziono wiersza nagłówka z kolumną „Brutto” (np. „Razem brutto”)."
    )


def _check_breakdown(keys: set[str], seen: dict[str, str]) -> None:
    """Kolumna łączna obok niepełnego rozbicia = odmowa (część kwot by znikła)."""

    for combined, parts in (
        ("emp_social", EMPLOYEE_PARTS),
        ("er_social", EMPLOYER_PARTS),
    ):
        present = [part for part in parts if part in keys]
        if combined in keys and present and len(present) < len(parts):
            missing = [COLUMN_LABELS[part] for part in parts if part not in keys]
            raise ImportFileError(
                f"Kolumna „{seen[combined]}” i tylko część składek osobno (brak: "
                f"{', '.join(missing)}) — zostaw albo samą sumę, albo wszystkie "
                "składki osobno."
            )


def _first_word(text: str) -> str:
    for token in _TOKENS.split(text or ""):
        if token:
            return identifiers.fold(token)
    return ""


def _total_row(row: list[str], amount_positions: set[int]) -> bool:
    """Wiersz sumy: pierwsze słowo którejś komórki tekstowej to znacznik sumy."""

    return any(
        _first_word(cell) in TOTAL_MARKERS
        for position, cell in enumerate(row)
        if position not in amount_positions
    )


def _deductions(amounts: dict[str, int]) -> int:
    """Potrącenia z brutto: składki pracownika, zdrowotna, PIT, PPK, inne."""

    return (
        employee_social(amounts)
        + amounts.get("health", 0)
        + amounts.get("pit", 0)
        + amounts.get("ppk_emp", 0)
        + amounts.get("deductions", 0)
    )


def employee_social(amounts: dict[str, int]) -> int:
    parts = [key for key in EMPLOYEE_PARTS if key in amounts]
    if parts:
        return sum(amounts[key] for key in parts)
    return amounts.get("emp_social", 0)


def employer_social(amounts: dict[str, int]) -> int:
    parts = [key for key in EMPLOYER_PARTS if key in amounts]
    if parts:
        return sum(amounts[key] for key in parts)
    return amounts.get("er_social", 0)


def _row_amounts(
    row: list[str], columns: dict[int, str], headers: dict[str, str]
) -> tuple[dict[str, int], list[str]]:
    amounts: dict[str, int] = {}
    broken: list[str] = []
    for position, key in columns.items():
        if key in TEXT_COLUMNS:
            continue
        raw = row[position] if position < len(row) else ""
        value = parse_amount(raw)
        if value is None:
            broken.append(headers.get(key, COLUMN_LABELS[key]))
            continue
        grosze = int((value * 100).to_integral_value())
        amounts[key] = amounts.get(key, 0) + grosze if key in SUMMED else grosze
    net_alt = amounts.pop("net_alt", None)
    if "net" not in amounts and net_alt is not None:
        amounts["net"] = net_alt
    return amounts, broken


def _row_problems(amounts: dict[str, int]) -> list[str]:
    """Niezgodności wiersza, przez które kwoty w LP byłyby inne niż na liście."""

    problems = []
    for combined, parts, label in (
        ("emp_social", EMPLOYEE_PARTS, "ZUS pracownika"),
        ("er_social", EMPLOYER_PARTS, "ZUS pracodawcy"),
    ):
        if combined in amounts and all(part in amounts for part in parts):
            split = sum(amounts[part] for part in parts)
            if split != amounts[combined]:
                problems.append(
                    f"{label} razem {amounts[combined] / 100:.2f} zł ≠ suma składek "
                    f"{split / 100:.2f} zł."
                )
    if "net" in amounts:
        computed = amounts.get("gross", 0) - _deductions(amounts)
        if computed != amounts["net"]:
            problems.append(
                f"Brutto − potrącenia = {computed / 100:.2f} zł, a „Do wypłaty” = "
                f"{amounts['net'] / 100:.2f} zł (różnica "
                f"{(amounts['net'] - computed) / 100:.2f} zł) — któraś kwota nie "
                "trafiła do potrąceń; sprawdź rozpoznane kolumny."
            )
    return problems


def parse(content: bytes) -> ParsedList:
    if len(content) > MAX_BYTES:
        raise ImportFileError("Plik jest za duży (najwyżej 5 MB).")
    sheet = _sheet_rows(content)
    header_index, columns = _header(sheet)
    raw_headers = sheet[header_index]
    headers: dict[str, str] = {}
    for position, key in columns.items():
        headers.setdefault(key, raw_headers[position].strip())
    parsed = ParsedList(headers=headers)
    keys = set(columns.values())
    if not keys & {"net", "net_alt"}:
        parsed.problems.append(
            "W pliku nie ma kolumny „Do wypłaty” (ani „Netto”) — bez niej nie da się "
            "sprawdzić potrąceń pracownika."
        )
    if keys & {"emp_social", *EMPLOYEE_PARTS} and not keys & EMPLOYER_KEYS:
        parsed.problems.append(
            "Lista ma składki ZUS pracownika, ale żadnej składki pracodawcy — ich "
            "kolumny nie zostały rozpoznane albo nie ma ich w eksporcie."
        )
    amount_positions = {pos for pos, key in columns.items() if key not in TEXT_COLUMNS}
    total: Optional[tuple[int, dict[str, int]]] = None
    for offset, row in enumerate(sheet[header_index + 1 :], start=header_index + 2):
        if _total_row(row, amount_positions):
            parsed.skipped += 1
            amounts, broken = _row_amounts(row, columns, headers)
            if not broken:
                filled = {
                    key: amounts[key]
                    for position, key in columns.items()
                    if key in amounts and position < len(row) and row[position].strip()
                }
                total = (offset, filled)
            continue
        amounts, broken = _row_amounts(row, columns, headers)
        if broken:
            parsed.errors.append(
                {"line": offset, "message": f"Nieczytelna kwota: {', '.join(broken)}."}
            )
            continue
        if not any(amounts.values()):
            parsed.skipped += 1
            continue
        problems = _row_problems(amounts)
        if problems:
            parsed.errors.append({"line": offset, "message": " ".join(problems)})
            continue
        mpk = None
        for position, key in columns.items():
            if key == "mpk" and position < len(row):
                mpk = row[position].strip().upper()[:MPK_MAX] or None
        parsed.rows.append(PayrollRow(line=offset, mpk=mpk, amounts=amounts))
    if total is not None:
        line, filled = total
        for key, value in filled.items():
            summed = sum(row.amounts.get(key, 0) for row in parsed.rows)
            if summed != value:
                parsed.errors.append(
                    {
                        "line": line,
                        "message": (
                            f"Wiersz sumy: {headers.get(key, COLUMN_LABELS[key])} = "
                            f"{value / 100:.2f} zł, a suma osób = {summed / 100:.2f} zł."
                        ),
                    }
                )
    if not parsed.rows and not parsed.errors:
        raise ImportFileError("Plik nie ma żadnego wiersza z kwotami listy płac.")
    return parsed


@dataclass(frozen=True)
class Totals:
    gross: int
    employee: int  # potrącenia z brutto (składki, zdrowotna, PIT, PPK, inne)
    employer: int  # składki pracodawcy, FP, FS, FGŚP, PPK pracodawcy
    zus: int
    pit: int
    ppk: int
    deductions: int
    net: int  # brutto − potrącenia


def totals(rows: list[PayrollRow]) -> tuple[Totals, dict[Optional[str], list[int]]]:
    """Sumy listy i koszty per MPK (brutto, koszt pracodawcy)."""

    sums: dict[str, int] = defaultdict(int)
    by_mpk: dict[Optional[str], list[int]] = defaultdict(lambda: [0, 0])
    for row in rows:
        amounts = row.amounts
        funds = (
            amounts.get("fp", 0)
            + amounts.get("fs", 0)
            + amounts.get("fgsp", 0)
            + amounts.get("fep", 0)
        )
        er_social = employer_social(amounts)
        employer = er_social + funds + amounts.get("ppk_er", 0)
        sums["gross"] += amounts.get("gross", 0)
        sums["employee"] += _deductions(amounts)
        sums["employer"] += employer
        sums["zus"] += (
            employee_social(amounts) + amounts.get("health", 0) + er_social + funds
        )
        sums["pit"] += amounts.get("pit", 0)
        sums["ppk"] += amounts.get("ppk_emp", 0) + amounts.get("ppk_er", 0)
        sums["deductions"] += amounts.get("deductions", 0)
        cost = by_mpk[row.mpk]
        cost[0] += amounts.get("gross", 0)
        cost[1] += employer
    result = Totals(
        gross=sums["gross"],
        employee=sums["employee"],
        employer=sums["employer"],
        zus=sums["zus"],
        pit=sums["pit"],
        ppk=sums["ppk"],
        deductions=sums["deductions"],
        net=sums["gross"] - sums["employee"],
    )
    return result, dict(by_mpk)


def decree(
    rows: list[PayrollRow], accounts: PayrollAccounts
) -> tuple[list[LineIn], list[str]]:
    """Pozycje LP albo problemy (brak kont, ujemne sumy)."""

    total, by_mpk = totals(rows)
    problems: list[str] = []
    missing = accounts.missing()
    if missing:
        problems.append(
            "Ustaw konta listy płac w Ustawieniach Księgowości: "
            + ", ".join(missing)
            + "."
        )
    if total.ppk and not accounts.ppk_account:
        problems.append(
            "Lista ma wpłaty PPK — ustaw konto „Rozrachunki PPK” w Ustawieniach."
        )
    if total.deductions and not accounts.deductions_account:
        problems.append(
            "Lista ma inne potrącenia — ustaw ich konto w Ustawieniach Księgowości."
        )
    negative = [
        name
        for name, value in (
            ("brutto", total.gross),
            ("potrącenia", total.employee),
            ("składki pracodawcy", total.employer),
        )
        if value < 0
    ]
    if negative or any(cost < 0 for pair in by_mpk.values() for cost in pair):
        problems.append(
            "Ujemne sumy listy ("
            + (", ".join(negative) or "koszty MPK")
            + ") — korektę listy płac wczytaj jako osobną listę po wyjaśnieniu w Enovie."
        )
    if problems:
        return [], problems
    lines: list[LineIn] = []
    for mpk in sorted(by_mpk, key=lambda value: (value is None, value or "")):
        gross, employer = by_mpk[mpk]
        if gross:
            lines.append(
                LineIn(
                    "debit",
                    accounts.wages_account,
                    gross,
                    "Wynagrodzenia brutto",
                    mpk=mpk,
                )
            )
        if employer:
            lines.append(
                LineIn(
                    "debit",
                    accounts.insurance_account,
                    employer,
                    "Składki ZUS, FP, FS, FGŚP, FEP i PPK pracodawcy",
                    mpk=mpk,
                )
            )
    if total.employee:
        lines.append(
            LineIn(
                "debit",
                accounts.settlement_account,
                total.employee,
                "Potrącenia z wynagrodzeń",
            )
        )
    for side, account, amount, text in (
        ("credit", accounts.settlement_account, total.gross, "Wynagrodzenia brutto"),
        (
            "credit",
            accounts.zus_account,
            total.zus,
            "Składki ZUS (pracownik, zdrowotna, pracodawca, FP, FS, FGŚP, FEP)",
        ),
        ("credit", accounts.pit_account, total.pit, "Zaliczki na PIT"),
        ("credit", accounts.ppk_account, total.ppk, "Wpłaty PPK"),
        ("credit", accounts.deductions_account, total.deductions, "Inne potrącenia"),
    ):
        if amount:
            lines.append(LineIn(side, account, amount, text))
    return lines, []


def last_day(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def list_key(name: str) -> str:
    key = identifiers.fold(name)[:40]
    if not key:
        raise LedgerError(
            "Podaj nazwę listy z Enovy (np. „LP 10/2026”) — po niej ponowny import "
            "tej samej listy przebudowuje szkic.",
            status=422,
        )
    return key


def spec_for(
    lines: list[LineIn],
    *,
    year: int,
    month: int,
    list_name: str,
    payment_date: Optional[date],
    file_sha256: str,
    rows: int,
) -> DocumentSpec:
    end = last_day(year, month)
    name = " ".join(list_name.split())[:LIST_NAME_MAX]
    return DocumentSpec(
        doc_type="LP",
        op_date=end,
        doc_date=payment_date or end,
        lines=lines,
        description=f"Lista płac {name} za {month:02d}.{year} (Enova)",
        source_type=SOURCE_TYPE,
        source_id=f"{year}-{month:02d}:{list_key(name)}",
        sensitivity="payroll",
        meta={"list": name, "rows": rows, "file_sha256": file_sha256},
    )


async def _save(db: AsyncSession, spec: DocumentSpec, viewer: Viewer) -> LedgerDocument:
    existing = await db.scalar(
        select(LedgerDocument).where(
            LedgerDocument.source_type == SOURCE_TYPE,
            LedgerDocument.source_id == spec.source_id,
            LedgerDocument.reversed_by_id.is_(None),
        )
    )
    if existing is not None:
        if existing.status != "draft":
            raise LedgerError(
                f"Ta lista płac jest już zatwierdzona (pozycja {existing.journal_no}) — "
                "popraw ją stornem, potem wczytaj plik ponownie.",
                status=409,
            )
        await documents.delete_draft(db, existing.id, viewer=viewer)
    return await documents.create_draft(db, spec, actor_id=viewer.user_id)


def _line_payload(line: LineIn) -> dict[str, Any]:
    return {
        "side": line.side,
        "account": line.account,
        "amount": line.amount,
        "mpk": line.mpk,
        "description": line.description,
    }


async def import_list(
    db: AsyncSession,
    content: bytes,
    *,
    year: int,
    month: int,
    list_name: str,
    payment_date: Optional[date],
    accounts: PayrollAccounts,
    viewer: Viewer,
    save: bool,
) -> dict[str, Any]:
    """Podgląd listy płac albo zapis LP do bufora (bez commita)."""

    list_key(list_name)
    parsed = parse(content)
    total, by_mpk = totals(parsed.rows)
    lines, problems = decree(parsed.rows, accounts) if not parsed.errors else ([], [])
    problems = [*parsed.problems, *problems]
    if lines:
        plan = await documents.load_plan(db)
        problems.extend(
            engine.check(lines, plan, max_lines=engine.lines_max("LP")).issues
        )
    payload: dict[str, Any] = {
        "rows": len(parsed.rows),
        "skipped": parsed.skipped,
        "columns": [
            {"key": key, "label": COLUMN_LABELS[key], "header": header}
            for key, header in parsed.headers.items()
        ],
        "totals": {
            "gross": total.gross,
            "employee": total.employee,
            "employer": total.employer,
            "zus": total.zus,
            "pit": total.pit,
            "ppk": total.ppk,
            "deductions": total.deductions,
            "net": total.net,
        },
        "mpk": [
            {"mpk": mpk, "gross": cost[0], "employer": cost[1]}
            for mpk, cost in sorted(
                by_mpk.items(), key=lambda item: (item[0] is None, item[0] or "")
            )
        ],
        "lines": [_line_payload(line) for line in lines],
        "errors": parsed.errors[:MESSAGES_MAX],
        "errors_total": len(parsed.errors),
        "warnings": parsed.warnings[:MESSAGES_MAX],
        "warnings_total": len(parsed.warnings),
        "problems": problems,
        "saved": False,
        "document": None,
    }
    if not save:
        return payload
    if parsed.errors or problems or not lines:
        raise LedgerError(
            "Listy płac nie zapisano — popraw błędy i problemy z podglądu.", status=422
        )
    doc = await _save(
        db,
        spec_for(
            lines,
            year=year,
            month=month,
            list_name=list_name,
            payment_date=payment_date,
            file_sha256=hashlib.sha256(content).hexdigest(),
            rows=len(parsed.rows),
        ),
        viewer,
    )
    payload["saved"] = True
    payload["document"] = {"id": doc.id, "number": doc.number}
    return payload
