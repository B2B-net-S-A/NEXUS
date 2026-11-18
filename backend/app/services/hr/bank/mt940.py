"""Wyciąg MT940 (SWIFT, wariant polskich banków — standard ZBP).

Czytamy pola: ``:25:`` (rachunek), ``:60F:`` (waluta), ``:61:`` (operacja:
data waluty, znak C/D/RC/RD, kwota, referencje) i ``:86:`` (opis operacji).
Opis w polskich bankach ma podpola ``~NN`` (albo ``^NN``, ``<NN``, ``>NN``,
``?NN``): 20–26 i 60–63 to tytuł (pocięty na kawałki stałej długości, więc
każdą grupę sklejamy bez spacji, a grupy oddziela spacja — w 63 Santander
podaje numer operacji), 27–28 i 32–33 nazwa kontrahenta, 30 + 31 numer banku
i rachunek, 38 IBAN. Opis bez podpól = cały tekst jest tytułem, a rachunek
szukamy jako 26 cyfr (z ``PL`` albo bez).

Plik może nieść kilka wyciągów po kolei (``:20:`` … ``-``, np. rachunek PLN
i EUR). Walutę operacji zapamiętujemy przy jej ``:61:`` — operacja zapisuje się
dopiero przy następnym ``:61:`` albo na końcu pliku, a do tego czasu ``:60F:``
kolejnego wyciągu zdążyłby podmienić walutę (audyt A2, 19.10.2026). Rachunek
``:25:`` nie jest cechą operacji (dopasowanie idzie po rachunku kontrahenta
z ``:86:``), a ``ParsedStatement.account`` to rachunek ostatniego wyciągu.

Saldo: każdy wyciąg (część wyciągu) od ``:60F:``/``:60M:`` do
``:62F:``/``:62M:`` daje ``BalanceCheck`` — otwarcie + operacje = zamknięcie
banku. Parser sam nie odrzuca pliku (stare ekrany importu bez zmian), robi to
Księga (K4a). Wyciąg Santandera przez eBI24 (``.eMT``, 06.10.2026) ma trzy
części z ``:62M:``/``:60M:`` i nagłówki SWIFT ``{1:}{2:}{4:`` … ``-}``.

Storno: ``RC`` (reversal of credit) to obciążenie, ``RD`` (reversal of debit)
— uznanie. Znak opisuje więc kierunek samego wpisu, tak jak ``CdtDbtInd``
w CAMT.053 przy ``RvslInd``.

Kodowanie: UTF-8, a gdy się nie da — windows-1250 (polskie banki). Parser jest
czysty i nie loguje treści wyciągu.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from app.services.hr.bank.accounts import (
    AccountError,
    mask_accounts,
    normalize_nrb,
    nrb_from_parts,
)
from app.services.hr.bank.parsed import (
    BalanceCheck,
    ParsedStatement,
    StatementError,
    StatementLine,
)

_TAG = re.compile(r"^:(\d{2}[A-Z]?):", re.M)
_LINE_61 = re.compile(
    r"^(?P<value>\d{6})(?P<entry>\d{4})?(?P<mark>RC|RD|C|D)(?P<funds>[A-Z])?"
    r"(?P<amount>\d{1,15},\d{0,2})(?P<type>[NSF][A-Z0-9]{3})"
    r"(?P<cref>[^/\r\n]{0,16})(?://(?P<bref>[^\r\n]{0,16}))?"
)
_BALANCE = re.compile(
    r"^(?P<mark>[CD])\d{6}(?P<currency>[A-Z]{3})(?P<amount>\d{1,15},\d{0,2})"
)
_SUBFIELD = re.compile(r"[~^<>?](\d{2})")
_ACCOUNT_IN_TEXT = re.compile(r"(?:PL)?(\d{2}(?:\s?\d{4}){6})")
_TITLE_GROUPS = (
    ("20", "21", "22", "23", "24", "25", "26"),
    ("60", "61", "62", "63"),
)
_NAME_FIELDS = ("32", "33", "27", "28")
#: Za duży plik to nie wyciąg miesiąca dla Płac.
MAX_LINES = 20_000


def decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "windows-1250"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def looks_like(text: str) -> bool:
    return bool(re.search(r"^:20:", text, re.M)) and bool(
        re.search(r"^:61:", text, re.M)
    )


def _blocks(text: str) -> list[tuple[str, str]]:
    """``[(tag, treść)]`` w kolejności pliku; linie kontynuacji należą do pola."""

    matches = list(_TAG.finditer(text))
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end]
        # Koniec komunikatu („-”) nie należy do ostatniego pola.
        body = re.sub(r"\r?\n-\s*$", "", body.rstrip())
        blocks.append((match.group(1), body))
    return blocks


def _date(yymmdd: str) -> date:
    year = 2000 + int(yymmdd[:2])
    try:
        return date(year, int(yymmdd[2:4]), int(yymmdd[4:6]))
    except ValueError as exc:
        raise StatementError("Wyciąg MT940 ma niepoprawną datę operacji.") from exc


def _balance(body: str) -> Optional[tuple[str, Decimal]]:
    """``:60F:``/``:62F:`` → (waluta, saldo ze znakiem); ``None`` = nie umiem."""

    match = _BALANCE.match(body.strip())
    if match is None:
        return None
    try:
        amount = Decimal(match.group("amount").replace(",", "."))
    except InvalidOperation:
        return None
    return match.group("currency"), -amount if match.group("mark") == "D" else amount


def _booking_date(value_date: date, entry: Optional[str]) -> date:
    """Data księgowania (MMDD) — rok jak w dacie waluty, z przejściem przez Nowy Rok."""

    if not entry:
        return value_date
    month, day = int(entry[:2]), int(entry[2:])
    year = value_date.year
    if month == 1 and value_date.month == 12:
        year += 1
    elif month == 12 and value_date.month == 1:
        year -= 1
    try:
        return date(year, month, day)
    except ValueError:
        return value_date


def _subfields(text: str) -> dict[str, str]:
    flat = text.replace("\r", "").replace("\n", "")
    marks = list(_SUBFIELD.finditer(flat))
    if len(marks) < 2:
        return {}
    # Kawałki do listy i jedno sklejenie na końcu — ``+=`` na napisie w słowniku
    # kopiuje całość za każdym razem (kwadratowo przy powtórzonym podpolu).
    chunks: dict[str, list[str]] = {}
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(flat)
        chunks.setdefault(mark.group(1), []).append(flat[mark.end() : end])
    return {key: "".join(parts) for key, parts in chunks.items()}


def _account_from_text(text: str) -> Optional[str]:
    for match in _ACCOUNT_IN_TEXT.finditer(text.replace("\n", " ")):
        try:
            return normalize_nrb(match.group(1))
        except AccountError:
            continue
    return None


def _details(text: str) -> tuple[str, str, Optional[str]]:
    """Opis ``:86:`` → (tytuł, nazwa kontrahenta, rachunek NRB)."""

    fields = _subfields(text)
    if not fields:
        flat = " ".join(part.strip() for part in text.splitlines())
        # Rachunek odczytany przed maskowaniem; tytuł bez pełnych numerów.
        return mask_accounts(flat.strip()), "", _account_from_text(flat)
    # Kawałki 20–26 i 60–63 sklejamy bez spacji (pocięte w pół słowa), ale obie
    # grupy oddziela spacja: Santander wpisuje w 63 swój numer operacji,
    # a doklejony wprost do tytułu psuł numer faktury („1/10/2026” +
    # „823973257”) — wyciąg 12.11.2026, 96 operacji bez pary. Tytuł przelewu
    # (4 × 35 znaków) mieści się w 20–25, więc spacja nie tnie jego słów.
    title = " ".join(
        part
        for part in (
            "".join(fields.get(key, "") for key in group).strip()
            for group in _TITLE_GROUPS
        )
        if part
    )
    name = " ".join(
        fields[key].strip() for key in _NAME_FIELDS if fields.get(key, "").strip()
    )
    account: Optional[str] = None
    iban = fields.get("38", "").strip()
    if iban:
        try:
            account = normalize_nrb(iban)
        except AccountError:
            account = None
    if account is None and (fields.get("30") or fields.get("31")):
        account = nrb_from_parts(fields.get("30", ""), fields.get("31", ""))
    if not title:
        title = fields.get("00", "").strip()
    return mask_accounts(title), mask_accounts(name), account


def parse(raw: bytes) -> ParsedStatement:
    text = decode(raw)
    if not looks_like(text):
        raise StatementError("To nie jest wyciąg MT940 (brak pól :20: i :61:).")
    account: Optional[str] = None
    currency: Optional[str] = None
    lines: list[StatementLine] = []
    accounts: list[str] = []
    pending: Optional[dict] = None
    balances: list[BalanceCheck] = []
    #: Saldo otwarcia bieżącego wyciągu i suma jego operacji (ze znakiem).
    opening: Optional[Decimal] = None
    movement = Decimal("0")
    statement_no = 0

    def flush() -> None:
        nonlocal pending
        if pending is None:
            return
        title, name, counterparty = _details(pending.get("details", ""))
        lines.append(
            StatementLine(
                index=len(lines) + 1,
                booked_on=pending["booked_on"],
                amount=pending["amount"],
                direction=pending["direction"],
                currency=pending["currency"],
                title=title,
                counterparty_name=name,
                counterparty_account=counterparty,
                bank_ref=pending["bank_ref"],
            )
        )
        pending = None

    for tag, body in _blocks(text):
        if tag == "25":
            raw_account = re.sub(r"[^0-9A-Z]", "", body.split("/")[-1].upper())
            try:
                account = normalize_nrb(raw_account)
            except AccountError:
                account = None
            accounts.append(account or raw_account)
        elif tag in ("60F", "60M"):
            statement_no += 1
            found = _balance(body)
            if found:
                currency = found[0]
            opening = found[1] if found else None
            movement = Decimal("0")
        elif tag in ("62F", "62M"):
            found = _balance(body)
            if opening is not None and found is not None:
                balances.append(
                    BalanceCheck(
                        statement=statement_no,
                        opening=opening,
                        movement=movement,
                        closing=found[1],
                    )
                )
            opening = None
        elif tag == "61":
            flush()
            match = _LINE_61.match(body.strip())
            if match is None:
                raise StatementError(
                    f"Wyciąg MT940: nie umiem przeczytać operacji nr {len(lines) + 1}."
                )
            try:
                amount = Decimal(match.group("amount").replace(",", "."))
            except InvalidOperation as exc:
                raise StatementError("Wyciąg MT940 ma niepoprawną kwotę.") from exc
            value_date = _date(match.group("value"))
            mark = match.group("mark")
            # Storno: RC (zwrot uznania) obciąża rachunek, RD (zwrot obciążenia)
            # go uznaje — kierunek samego wpisu, jak CdtDbtInd w CAMT.053.
            direction = "debit" if mark in ("D", "RC") else "credit"
            movement += -amount if direction == "debit" else amount
            reference = (match.group("bref") or "").strip() or (
                (match.group("cref") or "").strip()
                if (match.group("cref") or "").strip() not in ("", "NONREF")
                else ""
            )
            pending = {
                "booked_on": _booking_date(value_date, match.group("entry")),
                "amount": amount,
                "direction": direction,
                "bank_ref": reference,
                # Waluta wyciągu tej operacji — :60F: następnego wyciągu
                # przyjdzie przed zapisem operacji (flush przy kolejnym :61:).
                "currency": currency or "PLN",
            }
        elif tag == "86" and pending is not None:
            pending["details"] = body
        if len(lines) > MAX_LINES:
            raise StatementError("Wyciąg ma za dużo operacji — podziel go na miesiące.")
    flush()
    return ParsedStatement(
        format="mt940",
        account=account,
        currency=currency,
        lines=tuple(lines),
        accounts=tuple(accounts),
        balances=tuple(balances),
    )


__all__ = ["decode", "looks_like", "parse"]
