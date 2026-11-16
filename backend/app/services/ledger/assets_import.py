"""Import ewidencji z Symfonii Środki Trwałe (K6): plik → podgląd → środki w NEXUSIE.

Finanse eksportują ewidencję z Symfonii ŚT (XLSX albo CSV). Układu kolumn nie
znamy z próbki, więc nagłówki rozpoznajemy po aliasach, jak import
kontrahentów E1 i bilans otwarcia K2 (ten sam czytnik plików ze strażnikiem
rozmiaru po rozpakowaniu).

* **Stan na koniec miesiąca** (parametr importu): umorzenie bilansowe
  i podatkowe z pliku jest umorzeniem na koniec tego miesiąca; NEXUS liczy
  odpisy od następnego. Środki z importu nie dostają OT w księdze — ich wartość
  i umorzenie przychodzą bilansem otwarcia z Symfonii (K2).
* **Kolumny wymagane**: nazwa, data przyjęcia, wartość początkowa. Reszta ma
  wartości domyślne: numer inwentarzowy kolejny (``ST/RRRR/NNN``), rodzaj
  z kolumny „Rodzaj” (inaczej z konta 020 albo braku KŚT — WNiP), konta 010/070
  albo 020/071, MPK ``OG``, metoda liniowa, stawka podatkowa i metoda = jak
  bilansowe, umorzenie 0. Metoda degresywna ze stanem nie na koniec grudnia
  potrzebuje umorzenia na początek roku.
* **Stawka**: procent („10”, „10,5”, „10%”); wartość poniżej 1 to ułamek
  z Excela (0,3 = 30%).
* Środki zlikwidowane i sprzedane (kolumna stanu albo data zbycia) pomijamy —
  ewidencja NEXUSA zaczyna się od środków w używaniu.
* **Wszystko albo nic**: błędny wiersz, numer inwentarzowy już w ewidencji albo
  konto spoza planu kont blokują zapis całego pliku. Import robi lista
  „Księgowi” albo admin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ledger_assets import LedgerAsset
from app.services.finance_ledger import identifiers
from app.services.finance_ledger.costs import LedgerError
from app.services.finance_ledger.counterparty_import import (
    ImportFileError,
    _sheet_rows,  # czytnik XLSX/CSV ze strażnikiem bomby ZIP (E1)
)
from app.services.finance_ledger.posting import clean_account
from app.services.ledger import assets, depreciation, documents, engine
from app.services.ledger.documents import Viewer
from app.services.ledger.opening import parse_amount
from app.services.ledger.settings import LedgerSettings
from app.services.ledger_assets_schema import INVENTORY_MAX, KST_MAX, NAME_MAX

MAX_BYTES = 5 * 1024 * 1024
ROWS_MAX = 5_000
HEADER_SCAN_ROWS = 15
PREVIEW_ROWS = 200
ERRORS_SHOWN = 100

#: Pole → aliasy nagłówka (po ``identifiers.fold``). Dopasowanie dokładne,
#: a dla aliasów z ``PREFIXED`` także początek nagłówka; wygrywa najdłuższy.
ALIASES: dict[str, tuple[str, ...]] = {
    "inventory_number": (
        "numerinwentarzowy",
        "nrinwentarzowy",
        "nrinw",
        "numerinw",
        "inwentarz",
        "symbol",
        "numer",
    ),
    "name": ("nazwa", "nazwasrodka", "nazwasrodkatrwalego", "opis"),
    "kind": ("rodzaj", "rodzajsrodka", "typ", "typsrodka"),
    "kst": ("kst", "symbolkst", "kodkst", "grupakst", "klasyfikacja"),
    "accepted_on": (
        "dataprzyjecia",
        "dataprzyjeciadouzywania",
        "datawprowadzenia",
        "dataot",
        "przyjeto",
    ),
    "initial_value": ("wartoscpoczatkowa", "wartoscpocz", "wartoscbrutto"),
    "balance_accumulated": (
        "umorzenie",
        "umorzeniebilansowe",
        "umorzeniebil",
        "dotychczasoweumorzenie",
        "umorzeniedotychczasowe",
    ),
    "tax_accumulated": ("umorzeniepodatkowe", "umorzeniepod"),
    "balance_year": (
        "umorzenienapoczatekroku",
        "umorzeniebilansowenapoczatekroku",
        "boumorzenia",
        "boumorzeniabilansowego",
    ),
    "tax_year": (
        "umorzeniepodatkowenapoczatekroku",
        "boumorzeniapodatkowego",
    ),
    "balance_method": (
        "metoda",
        "metodaamortyzacji",
        "metodabilansowa",
        "metodaamortyzacjibilansowej",
    ),
    "tax_method": (
        "metodapodatkowa",
        "metodaamortyzacjipodatkowej",
        "metodapod",
    ),
    "balance_rate": (
        "stawka",
        "stawkaamortyzacji",
        "stawkabilansowa",
        "stawkaamortyzacjibilansowej",
        "stawkabil",
    ),
    "tax_rate": ("stawkapodatkowa", "stawkaamortyzacjipodatkowej", "stawkapod"),
    "coefficient": ("wspolczynnik", "wspolczynnikdegresywnej"),
    "asset_account": ("konto", "kontosrodka", "kontoewidencyjne", "kontowartosci"),
    "depreciation_account": ("kontoumorzenia", "kontoumorzeniowe"),
    "mpk": ("mpk", "miejscepowstaniakosztow", "miejscekosztow", "osrodekkosztow"),
    "status": ("stan", "status", "stansrodka"),
    "disposed_on": ("datalikwidacji", "datazbycia", "datasprzedazy", "datawycofania"),
}
PREFIXED = frozenset(
    {
        "numerinwentarzowy",
        "nrinwentarzowy",
        "nazwasrodka",
        "dataprzyjecia",
        "wartoscpoczatkowa",
        "umorzeniebilansowe",
        "umorzeniepodatkowe",
        "umorzeniebilansowenapoczatekroku",
        "umorzeniepodatkowenapoczatekroku",
        "umorzenienapoczatekroku",
        "metodaamortyzacji",
        "metodabilansowa",
        "metodapodatkowa",
        "stawkaamortyzacji",
        "stawkabilansowa",
        "stawkapodatkowa",
        "kontoumorzenia",
        "kontosrodka",
        "datalikwidacji",
        "datazbycia",
        "datasprzedazy",
    }
)
REQUIRED = ("name", "accepted_on", "initial_value")
METHOD_WORDS: tuple[tuple[str, str], ...] = (
    ("liniow", "linear"),
    ("lin", "linear"),
    ("degres", "degressive"),
    ("deg", "degressive"),
    ("jednoraz", "one_off"),
    ("jedn", "one_off"),
    ("nieamort", "none"),
    ("brak", "none"),
    ("bez", "none"),
    ("nie", "none"),
    ("linear", "linear"),
    ("degressive", "degressive"),
    ("oneoff", "one_off"),
    ("none", "none"),
)
SINGLE_LETTER_METHODS = {"l": "linear", "d": "degressive", "j": "one_off"}
DISPOSED_WORDS = ("zlikwid", "likwid", "sprzeda", "zbyt", "wycofan")
_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y", "%Y.%m.%d")


@dataclass
class ImportRow:
    line: int
    values: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class ParsedAssets:
    rows: list[ImportRow] = field(default_factory=list)
    skipped_disposed: int = 0
    columns: dict[str, str] = field(default_factory=dict)


def match_header(raw: str) -> Optional[str]:
    word = identifiers.fold(raw)
    if not word:
        return None
    best: Optional[tuple[int, str]] = None
    for name, aliases in ALIASES.items():
        for alias in aliases:
            hit = word == alias or (alias in PREFIXED and word.startswith(alias))
            if hit and (best is None or len(alias) > best[0]):
                best = (len(alias), name)
    return best[1] if best else None


def _header(rows: list[list[str]]) -> tuple[int, dict[int, str], dict[str, str]]:
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        columns: dict[int, str] = {}
        raw_names: dict[str, str] = {}
        for position, raw in enumerate(row):
            name = match_header(raw)
            if name and name not in columns.values():
                columns[position] = name
                raw_names[name] = raw
        if all(name in columns.values() for name in REQUIRED):
            return index, columns, raw_names
    raise ImportFileError(
        "Nie znaleziono wiersza nagłówka z kolumnami „Nazwa”, „Data przyjęcia” "
        "i „Wartość początkowa”."
    )


def parse_date(raw: str) -> Optional[date]:
    text = (raw or "").strip()
    if not text:
        return None
    text = text.split(" ")[0].split("T")[0]
    for pattern in _DATE_FORMATS:
        try:
            return datetime.strptime(text, pattern).date()  # noqa: DTZ007 — sama data z pliku
        except ValueError:
            continue
    return None


def parse_rate(raw: str) -> Optional[Decimal]:
    text = (raw or "").replace("%", "").replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if not value.is_finite() or value < 0:
        return None
    if 0 < value < 1:
        value *= 100  # ułamek z Excela: 0,3 = 30%
    if value > 100:
        return None
    return value.quantize(Decimal("0.01"))


def parse_method(raw: str) -> Optional[str]:
    word = identifiers.fold(raw)
    if not word:
        return None
    if word in SINGLE_LETTER_METHODS:
        return SINGLE_LETTER_METHODS[word]
    for prefix, method in METHOD_WORDS:
        if word.startswith(prefix):
            return method
    return None


def parse_kind(raw: str) -> Optional[str]:
    word = identifiers.fold(raw)
    if not word:
        return None
    if word.startswith(("wnip", "wartoscniemat", "wartosciniemat", "intangible")):
        return "intangible"
    if word.startswith(("st", "srodek", "srodki", "fixed")):
        return "fixed"
    return None


def _grosze(raw: str, label: str, errors: list[str]) -> Optional[int]:
    value = parse_amount(raw)
    if value is None:
        errors.append(f"{label}: niepoprawna kwota „{raw[:30]}”.")
        return None
    return int(value * 100)


def _row(raw: dict[str, str], line: int) -> Optional[ImportRow]:
    """Wiersz pliku → wartości środka (``None`` = pusty albo zbyty — pomijamy)."""

    row = ImportRow(line=line)
    errors = row.errors
    values = row.values
    name = " ".join((raw.get("name") or "").split())
    if not name and not (raw.get("initial_value") or "").strip():
        return None
    status = identifiers.fold(raw.get("status") or "")
    if any(word in status for word in DISPOSED_WORDS) or parse_date(
        raw.get("disposed_on") or ""
    ):
        row.values["disposed"] = True
        return row
    if not name:
        errors.append("Brak nazwy środka.")
    values["name"] = name[:NAME_MAX]
    values["inventory_number"] = " ".join((raw.get("inventory_number") or "").split())[
        :INVENTORY_MAX
    ]
    accepted = parse_date(raw.get("accepted_on") or "")
    if accepted is None:
        errors.append("Brak albo niepoprawna data przyjęcia.")
    values["accepted_on"] = accepted
    initial = _grosze(raw.get("initial_value") or "", "Wartość początkowa", errors)
    if initial is not None and initial <= 0:
        errors.append("Wartość początkowa musi być większa od zera.")
    values["initial_value"] = initial
    values["kst"] = "".join((raw.get("kst") or "").split())[:KST_MAX] or None
    for key, label in (
        ("balance_accumulated", "Umorzenie bilansowe"),
        ("tax_accumulated", "Umorzenie podatkowe"),
        ("balance_year", "Umorzenie bilansowe na początek roku"),
        ("tax_year", "Umorzenie podatkowe na początek roku"),
    ):
        text = (raw.get(key) or "").strip()
        values[key] = _grosze(text, label, errors) if text else None
    for side in ("balance", "tax"):
        text = raw.get(f"{side}_method") or ""
        method = parse_method(text)
        if text.strip() and method is None:
            errors.append(f"Nieznana metoda amortyzacji „{text[:30]}”.")
        values[f"{side}_method"] = method
        rate_text = raw.get(f"{side}_rate") or ""
        rate = parse_rate(rate_text)
        if rate_text.strip() and rate is None:
            errors.append(f"Niepoprawna stawka „{rate_text[:20]}” (od 0 do 100%).")
        values[f"{side}_rate"] = rate
    coefficient_text = "".join((raw.get("coefficient") or "").split())
    values["coefficient"] = None
    if coefficient_text:
        try:
            coefficient = Decimal(coefficient_text.replace(",", "."))
            if not coefficient.is_finite():
                raise InvalidOperation
            values["coefficient"] = coefficient.quantize(Decimal("0.01"))
        except InvalidOperation:
            errors.append(f"Niepoprawny współczynnik „{coefficient_text[:20]}”.")
    kind_text = raw.get("kind") or ""
    values["kind"] = parse_kind(kind_text)
    if kind_text.strip() and values["kind"] is None:
        errors.append(f"Nieznany rodzaj „{kind_text[:30]}” (środek trwały albo WNiP).")
    for key in ("asset_account", "depreciation_account"):
        text = (raw.get(key) or "").strip()
        if not text:
            values[key] = None
            continue
        try:
            values[key] = clean_account(text, "Konto")
        except LedgerError as exc:
            errors.append(exc.message)
            values[key] = None
    values["mpk"] = "".join((raw.get("mpk") or "").split()).upper() or None
    return row


def parse(content: bytes) -> ParsedAssets:
    if len(content) > MAX_BYTES:
        raise ImportFileError("Plik jest za duży (najwyżej 5 MB).")
    rows = _sheet_rows(content)
    header_index, columns, raw_names = _header(rows)
    parsed = ParsedAssets(columns=raw_names)
    for offset, raw_row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        raw = {
            name: raw_row[position] if position < len(raw_row) else ""
            for position, name in columns.items()
        }
        row = _row(raw, offset)
        if row is None:
            continue
        if row.values.get("disposed"):
            parsed.skipped_disposed += 1
            continue
        parsed.rows.append(row)
        if len(parsed.rows) > ROWS_MAX:
            raise ImportFileError(f"Plik ma więcej niż {ROWS_MAX} środków.")
    if not parsed.rows:
        raise ImportFileError("Plik nie ma żadnego środka w używaniu.")
    return parsed


def _kind_of(values: dict[str, Any]) -> str:
    """Rodzaj z kolumny, inaczej z konta (020 = WNiP); bez obu — środek trwały."""

    if values.get("kind"):
        return str(values["kind"])
    account = values.get("asset_account") or ""
    return "intangible" if account.startswith("02") else "fixed"


def _asset_values(values: dict[str, Any], month: date) -> dict[str, Any]:
    """Wartości wiersza → słownik jak z formularza (z domyślnymi)."""

    kind = _kind_of(values)
    balance_method = values.get("balance_method") or "linear"
    balance_rate = values.get("balance_rate")
    if balance_rate is None:
        balance_rate = Decimal("100") if balance_method == "one_off" else Decimal(0)
    tax_method = values.get("tax_method") or balance_method
    tax_rate = values.get("tax_rate")
    if tax_rate is None:
        tax_rate = balance_rate
    balance = values.get("balance_accumulated") or 0
    return {
        "name": values["name"],
        "inventory_number": values.get("inventory_number") or "",
        "kind": kind,
        "kst": values.get("kst") if kind == "fixed" else None,
        "accepted_on": values["accepted_on"],
        "initial_value": values["initial_value"],
        "asset_account": values.get("asset_account"),
        "depreciation_account": values.get("depreciation_account"),
        "mpk": values.get("mpk") or "OG",
        "balance_method": balance_method,
        "balance_rate": balance_rate,
        "tax_method": tax_method,
        "tax_rate": tax_rate,
        "coefficient": values.get("coefficient"),
        "opening": {
            "month": month,
            "balance": balance,
            "tax": values.get("tax_accumulated")
            if values.get("tax_accumulated") is not None
            else balance,
            "balance_year": values.get("balance_year"),
            "tax_year": values.get("tax_year")
            if values.get("tax_year") is not None
            else values.get("balance_year"),
        },
        "note": "Z Symfonii Środki Trwałe",
    }


async def run(
    db: AsyncSession,
    content: bytes,
    *,
    month: date,
    save: bool,
    viewer: Viewer,
    settings: LedgerSettings,
) -> dict[str, Any]:
    """Podgląd albo zapis (bez commita) ewidencji ze stanem na koniec ``month``."""

    month = depreciation.first_of(month)
    parsed = parse(content)
    plan = await documents.load_plan(db)
    existing = set(
        await db.scalars(
            select(LedgerAsset.inventory_number).where(
                LedgerAsset.inventory_number.in_(
                    [
                        row.values["inventory_number"]
                        for row in parsed.rows
                        if row.values.get("inventory_number")
                    ]
                    or ["-"]
                )
            )
        )
    )
    end = depreciation.add_months(month, 1)
    seen: dict[str, int] = {}
    missing_accounts: set[str] = set()
    prepared: list[tuple[ImportRow, dict[str, Any]]] = []
    for row in parsed.rows:
        values = row.values
        number = values.get("inventory_number")
        if number:
            if number in existing:
                row.errors.append(f"Numer {number} jest już w ewidencji NEXUSA.")
            if number in seen:
                row.errors.append(
                    f"Numer {number} powtarza się (wiersz {seen[number]})."
                )
            seen.setdefault(number, row.line)
        accepted = values.get("accepted_on")
        if accepted is not None and accepted >= end:
            row.errors.append(
                "Środek przyjęty po miesiącu stanu — wprowadź go w NEXUSIE dokumentem OT."
            )
        if row.errors:
            continue
        asset_values = _asset_values(values, month)
        defaults = assets.DEFAULT_ACCOUNTS[asset_values["kind"]]
        for key, default in zip(("asset_account", "depreciation_account"), defaults):
            number_ = asset_values[key] or default
            asset_values[key] = number_
            resolved, _ = engine.resolve(number_, plan)
            if resolved is None:
                missing_accounts.add(number_)
                row.errors.append(f"Konta {number_} nie ma w planie kont.")
        try:
            probe = LedgerAsset(
                kind=asset_values["kind"],
                kst=asset_values["kst"],
                accepted_on=asset_values["accepted_on"],
                initial_value=asset_values["initial_value"],
                balance_method=asset_values["balance_method"],
                balance_rate=asset_values["balance_rate"],
                tax_method=asset_values["tax_method"],
                tax_rate=asset_values["tax_rate"],
                coefficient=asset_values["coefficient"]
                or depreciation.COEFFICIENT_DEFAULT,
                opening_month=month,
                opening_balance=asset_values["opening"]["balance"],
                opening_tax=asset_values["opening"]["tax"],
                opening_balance_year=asset_values["opening"]["balance_year"],
                opening_tax_year=asset_values["opening"]["tax_year"],
            )
            assets.validate_plan(probe)
        except LedgerError as exc:
            row.errors.append(exc.message)
        if assets.mpk_kind(asset_values["mpk"]) is None:
            row.errors.append(
                f"Nieznane MPK „{asset_values['mpk']}” (FO, BO, OG, K<id>)."
            )
        prepared.append((row, asset_values))
    errors = [row for row in parsed.rows if row.errors]
    totals = {"initial": 0, "balance": 0, "tax": 0}
    for _, asset_values in prepared:
        totals["initial"] += asset_values["initial_value"]
        totals["balance"] += asset_values["opening"]["balance"]
        totals["tax"] += asset_values["opening"]["tax"]
    created = 0
    if save:
        if errors:
            raise LedgerError(
                f"W pliku są błędy ({len(errors)} wierszy) — popraw je przed zapisem.",
                status=422,
            )
        for row, asset_values in prepared:
            try:
                await assets.create_asset(
                    db, asset_values, viewer=viewer, settings=settings
                )
            except LedgerError as exc:
                raise LedgerError(
                    f"Wiersz {row.line}: {exc.message}", status=exc.status
                ) from exc
            created += 1
    preview = [
        {
            "line": row.line,
            "inventory_number": values.get("inventory_number") or None,
            "name": values.get("name"),
            "kind": values.get("kind"),
            "kst": values.get("kst"),
            "accepted_on": values["accepted_on"].isoformat()
            if values.get("accepted_on")
            else None,
            "initial_value": values.get("initial_value"),
            "balance": values["opening"]["balance"] if "opening" in values else None,
            "tax": values["opening"]["tax"] if "opening" in values else None,
            "balance_method": values.get("balance_method"),
            "balance_rate": str(values["balance_rate"])
            if values.get("balance_rate") is not None
            else None,
            "mpk": values.get("mpk"),
        }
        for row, values in prepared[:PREVIEW_ROWS]
    ]
    return {
        "month": f"{month.year}-{month.month:02d}",
        "saved": save,
        "created": created,
        "rows": len(parsed.rows),
        "valid": len(parsed.rows) - len(errors),
        "skipped_disposed": parsed.skipped_disposed,
        "columns": parsed.columns,
        "preview": preview,
        "errors": [
            {"line": row.line, "problems": row.errors} for row in errors[:ERRORS_SHOWN]
        ],
        "errors_total": len(errors),
        "missing_accounts": sorted(missing_accounts),
        "totals": totals,
    }
