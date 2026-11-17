"""Bilans otwarcia z Symfonii (K2): plik zestawienia sald → dokument BO w buforze.

Plan „Księgowość w NEXUSIE” (13.11.2026): księga NEXUSA idzie równolegle
z Symfonią, więc saldo da się porównać dopiero z bilansem otwarcia roku.
Finanse eksportują z Symfonii FK zestawienie obrotów i sald (XLSX albo CSV)
— dokładny układ kolumn jeszcze nie jest znany, więc nagłówki rozpoznajemy po
aliasach, jak import kontrahentów E1 (ten sam czytnik plików ze strażnikiem
rozmiaru po rozpakowaniu).

* **Kolumny**: konto (wymagane), nazwa (opcjonalnie) i saldo — albo para
  Wn / Ma (BO Wn, Saldo Wn, …), albo jedna kolumna salda ze znakiem (Wn > 0).
  Wiersz z obiema stronami liczy się per saldo (Wn − Ma). Wiersze bez konta,
  sumy („Razem”, „Suma”, „Ogółem”) i salda zerowe pomijamy; to samo konto
  dwa razy = jedna pozycja z sumą.
* **Dwie pary kolumn** (zestawienie obrotów i sald z Symfonii ma i „BO Wn/Ma”,
  i „Saldo Wn/Ma”): rok otwierają kolumny BO; ``basis=saldo`` bierze saldo
  końcowe. **Wiersze syntetyczne** (``010``), pod którymi plik ma analitykę
  z kwotą (``010-3``), pomijamy — inaczej bilans byłby podwojony; ich kwota
  musi się równać sumie analityki (inaczej błąd wiersza).
* **Konta** muszą być w planie kont NEXUSA (albo być analityką słownika);
  analityka kontrahentów (``201-2-1042``) dostaje kontrahenta po ID Symfonii.
  Brakujące konta to problem z listą — plan kont uzupełnia księgowa.
* **Bilans** musi się bilansować (suma Wn = suma Ma) — inaczej zapisu nie ma.
* **Zapis**: jeden dokument BO na rok (źródło ``opening_import`` / rok) w dniu
  1 stycznia, w buforze; ponowny import przebudowuje szkic, zatwierdzony BO
  poprawia się stornem. Import robi osoba z listy „Księgowi” albo admin.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance_ledger import FinanceCounterparty
from app.models.ledger import LedgerDocument, LedgerPeriod, LedgerYear
from app.services.finance_ledger import identifiers
from app.services.finance_ledger.costs import LedgerError
from app.services.finance_ledger.counterparty_import import (
    ImportFileError,
    _sheet_rows,  # czytnik XLSX/CSV ze strażnikiem bomby ZIP (E1)
)
from app.services.finance_ledger.posting import clean_account, money_pl
from app.services.ledger import documents, engine
from app.services.ledger.documents import DocumentSpec, Viewer
from app.services.ledger.engine import LineIn, PlanAccount
from app.services.ledger_schema import LINE_TEXT_MAX

SOURCE_TYPE = "opening_import"
MAX_BYTES = 5 * 1024 * 1024
HEADER_SCAN_ROWS = 15
PREVIEW_LINES = 50
MISSING_SHOWN = 50
AMOUNT_LIMIT = Decimal("1000000000000")

ACCOUNT_ALIASES = (
    "konto",
    "numerkonta",
    "nrkonta",
    "symbolkonta",
    "kontoksiegowe",
    "account",
)
NAME_ALIASES = ("nazwa", "nazwakonta", "opis", "name")
BALANCE_ALIASES = ("saldo", "saldokoncowe", "balance")
#: Pary kolumn salda: bilans otwarcia, saldo końcowe, sama strona.
PAIRS: dict[str, dict[str, tuple[str, ...]]] = {
    "bo": {
        "debit": ("bown", "bilansotwarciawn"),
        "credit": ("boma", "bilansotwarciama"),
    },
    "saldo": {
        "debit": ("saldown", "saldokoncowewn", "saldowinien"),
        "credit": ("saldoma", "saldokoncowema"),
    },
    "plain": {"debit": ("wn", "winien", "debit"), "credit": ("ma", "credit")},
}
TOTAL_WORDS = ("razem", "suma", "ogolem", "total")
#: Excel trzyma kwoty jako liczby zmiennoprzecinkowe (1234.5600000000002).
FLOAT_NOISE = Decimal("0.0000001")


@dataclass
class OpeningRow:
    line: int
    account: str
    name: str
    amount: int  # grosze, Wn > 0, Ma < 0


@dataclass
class ParsedOpening:
    rows: list[OpeningRow] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    skipped: int = 0
    #: Sposób odczytu salda (``bo`` / ``saldo`` / ``plain`` / ``balance``) i czy
    #: plik miał obie pary kolumn (BO i saldo końcowe) — ekran pyta wtedy o wybór.
    basis: str = ""
    both_bases: bool = False
    #: Wiersze syntetyczne pominięte, bo ich kwotę niosą konta analityczne.
    synthetic_skipped: int = 0


def _header_name(raw: str) -> Optional[str]:
    """Nagłówek → ``account`` / ``name`` / ``balance`` / ``<para>:<strona>``."""

    word = identifiers.fold(raw)
    if not word:
        return None
    if word in ACCOUNT_ALIASES or any(
        len(alias) >= 5 and word.startswith(alias) for alias in ACCOUNT_ALIASES
    ):
        return "account"
    if word in NAME_ALIASES:
        return "name"
    if word in BALANCE_ALIASES:
        return "balance"
    for pair, sides in PAIRS.items():
        for side, aliases in sides.items():
            for alias in aliases:
                if word == alias or (len(alias) >= 4 and word.startswith(alias)):
                    return f"{pair}:{side}"
    return None


BASIS_OPENING = "bo"
BASIS_CLOSING = "saldo"
BASES = (BASIS_OPENING, BASIS_CLOSING)


def _header(
    rows: list[list[str]], basis: Optional[str] = None
) -> tuple[int, dict[int, str], str, bool]:
    """Wiersz nagłówka, kolumny, sposób odczytu salda i czy plik miał obie pary.

    Plik z kolumnami i „BO Wn/Ma”, i „Saldo Wn/Ma” (zestawienie obrotów i sald
    ZOiS z Symfonii) otwiera rok kolumnami BO; ``basis="saldo"`` bierze saldo
    końcowe (zestawienie za poprzedni rok).
    """

    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        columns: dict[int, str] = {}
        for position, raw in enumerate(row):
            name = _header_name(raw)
            if name and name not in columns.values():
                columns[position] = name
        names = set(columns.values())
        if "account" not in names:
            continue
        complete = [
            pair for pair in PAIRS if {f"{pair}:debit", f"{pair}:credit"} <= names
        ]
        if basis is not None and basis not in BASES:
            raise ImportFileError("Nieznany sposób odczytu kolumn salda.")
        if BASIS_OPENING in complete and BASIS_CLOSING in complete:
            return index, columns, basis or BASIS_OPENING, True
        if basis is not None and basis in complete:
            return index, columns, basis, False
        if complete:
            return index, columns, complete[0], False
        if "balance" in names:
            return index, columns, "balance", False
    raise ImportFileError(
        "Nie znaleziono wiersza nagłówka z kolumną „Konto” i saldem: „Wn” i „Ma” "
        "(np. „BO Wn”, „Saldo Ma”) albo jedną kolumną „Saldo”."
    )


_SPACES = re.compile(r"[\s\u00a0\u202f']")


def parse_amount(raw: str) -> Optional[Decimal]:
    """„1 234,56”, „1234.56”, „-1 234,56”, „(1 234,56)” → Decimal; puste → 0."""

    text = _SPACES.sub("", raw or "")
    if not text:
        return Decimal("0")
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    if "," in text and "." in text:
        # Separator tysięcy i dziesiętny naraz: dziesiętny to ten ostatni.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if not value.is_finite() or abs(value) >= AMOUNT_LIMIT:
        return None
    rounded = value.quantize(Decimal("0.01"))
    if abs(value - rounded) > FLOAT_NOISE:
        return None
    return -rounded if negative else rounded


def _is_total(*texts: str) -> bool:
    return any(
        identifiers.fold(text).startswith(word)
        for text in texts
        for word in TOTAL_WORDS
    )


def _drop_synthetic(parsed: ParsedOpening, merged: dict[str, OpeningRow]) -> None:
    """Zestawienie sald ma wiersz syntetyczny (``010``) i jego analitykę (``010-3``).

    Liczone oba podwoiłyby bilans, więc zostają konta końcowe (bez potomków
    z kwotą). Kwota syntetyki musi się zgadzać z sumą potomków — inaczej część
    salda nie ma analityki i zapis ją zgubiłby, więc to błąd wiersza.
    """

    synthetic = {
        "-".join(account.split("-")[:cut])
        for account in merged
        for cut in range(1, len(account.split("-")))
    } & set(merged)
    leaves = {number: row for number, row in merged.items() if number not in synthetic}
    for account in sorted(synthetic):
        row = merged.pop(account)
        parsed.synthetic_skipped += 1
        below = sum(
            leaf.amount
            for number, leaf in leaves.items()
            if number.startswith(f"{account}-")
        )
        if below != row.amount:
            parsed.errors.append(
                {
                    "line": row.line,
                    "message": (
                        f"Konto {account}: saldo syntetyczne nie zgadza się z sumą "
                        "kont analitycznych pod nim."
                    ),
                }
            )


def parse(content: bytes, *, basis: Optional[str] = None) -> ParsedOpening:
    if len(content) > MAX_BYTES:
        raise ImportFileError("Plik jest za duży (najwyżej 5 MB).")
    rows = _sheet_rows(content)
    header_index, columns, mode, both = _header(rows, basis)
    parsed = ParsedOpening(basis=mode, both_bases=both)
    merged: dict[str, OpeningRow] = {}
    for offset, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        values = {
            name: row[pos] if pos < len(row) else "" for pos, name in columns.items()
        }
        raw_account = (values.get("account") or "").replace(" ", "")
        name = values.get("name") or ""
        if not raw_account or _is_total(raw_account, name):
            parsed.skipped += 1
            continue
        try:
            account = clean_account(raw_account, f"Wiersz {offset}")
        except LedgerError as exc:
            parsed.errors.append({"line": offset, "message": exc.message})
            continue
        if mode == "balance":
            debit, credit = parse_amount(values.get("balance", "")), Decimal("0")
        else:
            debit = parse_amount(values.get(f"{mode}:debit", ""))
            credit = parse_amount(values.get(f"{mode}:credit", ""))
        if debit is None or credit is None:
            parsed.errors.append(
                {"line": offset, "message": f"Konto {account}: nieczytelna kwota."}
            )
            continue
        amount = int(((debit - credit) * 100).to_integral_value())
        if amount == 0:
            parsed.skipped += 1
            continue
        if account in merged:
            merged[account].amount += amount
        else:
            merged[account] = OpeningRow(offset, account, name, amount)
    merged = {number: row for number, row in merged.items() if row.amount != 0}
    _drop_synthetic(parsed, merged)
    parsed.rows = list(merged.values())
    if not parsed.rows and not parsed.errors:
        raise ImportFileError("Plik nie ma żadnego salda do bilansu otwarcia.")
    return parsed


def _dictionary_parent(
    account: str, plan: dict[str, PlanAccount]
) -> Optional[PlanAccount]:
    resolved, _ = engine.resolve(account, plan)
    if resolved is not None and resolved.analytic:
        return resolved.plan
    return None


async def build(
    db: AsyncSession, parsed: ParsedOpening, year: int
) -> tuple[Optional[DocumentSpec], dict[str, Any]]:
    """Dokument BO z pliku i podsumowanie podglądu (bez zapisu)."""

    plan = await documents.load_plan(db)
    partners: dict[str, int] = {}
    suffixes = {
        row.account.rsplit("-", 1)[-1]
        for row in parsed.rows
        if (parent := _dictionary_parent(row.account, plan)) is not None
        and parent.dictionary == "counterparty"
    }
    if suffixes:
        found = await db.execute(
            select(
                FinanceCounterparty.symfonia_partner_id, FinanceCounterparty.id
            ).where(FinanceCounterparty.symfonia_partner_id.in_(suffixes))
        )
        partners = {partner: cp_id for partner, cp_id in found.all() if partner}
    missing: list[str] = []
    lines: list[LineIn] = []
    for row in sorted(
        parsed.rows, key=lambda item: (item.account.split("-")[0], item.account)
    ):
        resolved, problem = engine.resolve(row.account, plan)
        if resolved is None:
            missing.append(row.account)
            continue
        counterparty_id = None
        if resolved.analytic and resolved.plan.dictionary == "counterparty":
            counterparty_id = partners.get(row.account.rsplit("-", 1)[-1])
        lines.append(
            LineIn(
                side="debit" if row.amount > 0 else "credit",
                account=row.account,
                amount=abs(row.amount),
                counterparty_id=counterparty_id,
                description=row.name[:LINE_TEXT_MAX],
            )
        )
    debit = sum(line.amount for line in lines if line.side == "debit")
    credit = sum(line.amount for line in lines if line.side == "credit")
    problems: list[str] = []
    january = await db.execute(
        select(LedgerYear.status, LedgerPeriod.status)
        .join(LedgerPeriod, LedgerPeriod.year_id == LedgerYear.id)
        .where(LedgerYear.year == year, LedgerPeriod.month == 1)
    )
    state = january.first()
    if state is None:
        problems.append(
            f"Nie ma roku obrotowego {year} — załóż go w Ustawieniach Księgowości."
        )
    elif state[0] != "open" or state[1] != "open":
        problems.append(
            f"Styczeń {year} jest zamknięty — bilansu otwarcia nie zapiszesz."
        )
    if missing:
        shown = ", ".join(missing[:MISSING_SHOWN])
        more = (
            f" i jeszcze {len(missing) - MISSING_SHOWN}"
            if len(missing) > MISSING_SHOWN
            else ""
        )
        problems.append(
            f"Kont nie ma w planie kont NEXUSA ({len(missing)}): {shown}{more} — "
            "dodaj je w „Plan kont” i wczytaj plik ponownie."
        )
    if debit != credit:
        problems.append(
            f"Bilans się nie bilansuje: Wn {money_pl(debit)}, Ma {money_pl(credit)} "
            f"(różnica {money_pl(abs(debit - credit))})."
        )
    if parsed.errors:
        problems.append(f"Wiersze z błędem: {len(parsed.errors)} — popraw je w pliku.")
    if not problems:
        problems.extend(
            engine.check(lines, plan, max_lines=engine.OPENING_LINES_MAX).issues[:1]
        )
    summary = {
        "year": year,
        "rows": len(parsed.rows),
        "skipped": parsed.skipped,
        "basis": parsed.basis,
        "both_bases": parsed.both_bases,
        "synthetic_skipped": parsed.synthetic_skipped,
        "errors": parsed.errors[:MISSING_SHOWN],
        "debit_total": debit,
        "credit_total": credit,
        "balanced": debit == credit,
        "missing_accounts": missing[:MISSING_SHOWN],
        "missing_total": len(missing),
        "counterparties_matched": sum(1 for line in lines if line.counterparty_id),
        "problems": problems,
        "preview": [
            {
                "account": line.account,
                "name": line.description,
                "side": line.side,
                "amount": line.amount,
            }
            for line in lines[:PREVIEW_LINES]
        ],
    }
    if problems:
        return None, summary
    spec = DocumentSpec(
        doc_type="BO",
        op_date=date(year, 1, 1),
        doc_date=date(year, 1, 1),
        lines=lines,
        number=f"BO {year}",
        description=f"Bilans otwarcia {year} — import z Symfonii FK",
        source_type=SOURCE_TYPE,
        source_id=str(year),
        meta={"source": "symfonia", "rows": len(parsed.rows)},
    )
    return spec, summary


async def save(
    db: AsyncSession, spec: DocumentSpec, *, viewer: Viewer
) -> LedgerDocument:
    """Zapis BO (bez commita): szkic tego roku przebudowany, zatwierdzony = 409."""

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
                f"Bilans otwarcia {spec.source_id} jest już zatwierdzony (pozycja "
                f"{existing.journal_no}) — popraw go stornem, potem wczytaj plik ponownie.",
                status=409,
            )
        await documents.delete_draft(db, existing.id, viewer=viewer)
    return await documents.create_draft(db, spec, actor_id=viewer.user_id)
