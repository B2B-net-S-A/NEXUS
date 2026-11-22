"""Wyciąg CAMT.053 (ISO 20022, ``BkToCstmrStmt``) — wersje 001.02–001.13.

Elementy szukamy po nazwie lokalnej (``{*}``), więc wersja przestrzeni nazw
nie ma znaczenia. Pozycja (``Ntry``) może nieść kilka transakcji (``TxDtls``,
księgowanie zbiorcze) — każda jest osobnym wierszem z własną kwotą; bez
``TxDtls`` wierszem jest sama pozycja. Kontrahent obciążenia to wierzyciel
(``Cdtr``/``CdtrAcct``), uznania — dłużnik (``Dbtr``/``DbtrAcct``).

Audyt A2 (19.10.2026):

* **storno** — wg ISO 20022 ``CdtDbtInd`` opisuje kierunek samego wpisu;
  ``RvslInd=true`` mówi tylko, że wpis odwraca operację o kierunku
  przeciwnym (CRDT + storno = wpływ, np. zwrot naszego nieudanego przelewu).
  Kierunku nie odwracamy drugi raz — inaczej zwrot wypłaty wyglądał jak
  przelew do osoby i oznaczał jej rozliczenie jako opłacone. Tak samo MT940:
  ``RC`` to obciążenie, ``RD`` uznanie. Strony (``RltdPties``) w stornie
  zostają jak w operacji pierwotnej, więc kontrahentem jest strona
  pierwotnej operacji: przy zwrocie naszego przelewu — jego odbiorca
  (``Cdtr``), nie my (``Dbtr``),
* **status** — liczą się tylko operacje zaksięgowane: ``Ntry/Sts`` równe
  ``BOOK`` (tekst w 001.02–001.07, ``Sts/Cd`` od 001.08); ``PDNG``
  i ``INFO`` pomijamy, brak ``Sts`` = zaksięgowana (jak dotąd),
* **waluta** — z ``Amt/@Ccy`` wpisu, bez niego z ``Acct/Ccy`` wyciągu
  (``Stmt``), który niesie operację; plik z kilkoma rachunkami nie bierze
  waluty pierwszego. ``ParsedStatement.currency`` to waluta pierwszego
  wyciągu (tylko informacja).

Saldo: wyciąg z ``Bal`` otwarcia (``OPBD``, a bez niego ``PRCD``) i zamknięcia
(``CLBD``) daje ``BalanceCheck`` z sumą zaksięgowanych pozycji (``Ntry/Amt``),
datami sald (``Bal/Dt``) i numerem wyciągu (``LglSeqNb`` albo ``ElctrncSeqNb``).
Odrzuca go Księga (K4a), nie parser.

Plik od użytkownika: parser bez DTD, encji i sieci (lxml ``resolve_entities``
wyłączone, ``<!DOCTYPE`` odrzucany), bez ogromnych drzew.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from lxml import etree

from app.services.hr.bank.accounts import AccountError, mask_accounts, normalize_nrb
from app.services.hr.bank.parsed import (
    BalanceCheck,
    ParsedStatement,
    StatementError,
    StatementLine,
)

MAX_LINES = 20_000


def looks_like(raw: bytes) -> bool:
    head = raw[:4096]
    return b"<" in head and (b"BkToCstmrStmt" in raw[:65536] or b"camt.053" in head)


def _parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        remove_comments=True,
        remove_pis=True,
    )


def _text(node: Optional[etree._Element], path: str) -> str:
    if node is None:
        return ""
    found = node.find(path)
    return (found.text or "").strip() if found is not None and found.text else ""


def _all_text(node: Optional[etree._Element], path: str) -> list[str]:
    if node is None:
        return []
    return [(item.text or "").strip() for item in node.findall(path) if item.text]


def _date(node: etree._Element, path: str) -> Optional[date]:
    raw = _text(node, f"{path}/{{*}}Dt") or _text(node, f"{path}/{{*}}DtTm")[:10]
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError as exc:
        raise StatementError("Wyciąg CAMT.053 ma niepoprawną datę.") from exc


def _amount(
    node: Optional[etree._Element], default_currency: str
) -> Optional[tuple[Decimal, str]]:
    if node is None or not (node.text or "").strip():
        return None
    try:
        value = Decimal(node.text.strip())
    except InvalidOperation as exc:
        raise StatementError("Wyciąg CAMT.053 ma niepoprawną kwotę.") from exc
    return abs(value), (node.get("Ccy") or default_currency).upper()


def _balance(
    statement: etree._Element, codes: tuple[str, ...]
) -> Optional[tuple[Decimal, Optional[date]]]:
    """Saldo wyciągu o pierwszym pasującym kodzie ``Bal/Tp`` (ze znakiem) i jego data.

    Zła data salda nie odrzuca pliku — wyciąg bez niej nie dowodzi ciągłości.
    """

    found: dict[str, tuple[Decimal, Optional[date]]] = {}
    for node in statement.findall("{*}Bal"):
        code = _text(node, "{*}Tp/{*}CdOrPrtry/{*}Cd").upper()
        amount = _amount(node.find("{*}Amt"), "")
        if code in codes and code not in found and amount is not None:
            debit = _text(node, "{*}CdtDbtInd") == "DBIT"
            try:
                day = _date(node, "{*}Dt")
            except StatementError:
                day = None
            found[code] = (-amount[0] if debit else amount[0], day)
    return next((found[code] for code in codes if code in found), None)


def _statement_number(statement: etree._Element) -> Optional[int]:
    """Numer wyciągu banku: ``LglSeqNb``, a bez niego ``ElctrncSeqNb``."""

    for path in ("{*}LglSeqNb", "{*}ElctrncSeqNb"):
        raw = _text(statement, path)
        if raw.isdigit():
            return int(raw)
    return None


def _booked(entry: etree._Element) -> bool:
    """Operacja zaksięgowana: ``Sts`` = ``BOOK`` (tekst albo ``Sts/Cd``) albo brak."""

    status = _text(entry, "{*}Sts/{*}Cd") or _text(entry, "{*}Sts")
    return not status or status.upper() == "BOOK"


def _account(node: Optional[etree._Element], party: str) -> Optional[str]:
    if node is None:
        return None
    for path in (
        f"{{*}}RltdPties/{{*}}{party}Acct/{{*}}Id/{{*}}IBAN",
        f"{{*}}RltdPties/{{*}}{party}Acct/{{*}}Id/{{*}}Othr/{{*}}Id",
    ):
        raw = _text(node, path)
        if raw:
            try:
                return normalize_nrb(raw)
            except AccountError:
                return None
    return None


def _name(node: Optional[etree._Element], party: str) -> str:
    if node is None:
        return ""
    return mask_accounts(
        _text(node, f"{{*}}RltdPties/{{*}}{party}/{{*}}Nm")
        or _text(node, f"{{*}}RltdPties/{{*}}{party}/{{*}}Pty/{{*}}Nm")
    )


def _title(entry: etree._Element, tx: Optional[etree._Element]) -> str:
    parts: list[str] = []
    if tx is not None:
        parts.extend(_all_text(tx, "{*}RmtInf/{*}Ustrd"))
        parts.extend(_all_text(tx, "{*}RmtInf/{*}Strd/{*}CdtrRefInf/{*}Ref"))
        if not parts:
            parts.append(_text(tx, "{*}AddtlTxInf"))
    if not any(parts):
        parts.append(_text(entry, "{*}AddtlNtryInf"))
    return mask_accounts(" ".join(part for part in parts if part).strip())


def parse(raw: bytes) -> ParsedStatement:
    if b"<!DOCTYPE" in raw[:4096].upper() or b"<!ENTITY" in raw.upper():
        raise StatementError("Wyciąg CAMT.053 nie może mieć deklaracji DOCTYPE.")
    try:
        root = etree.fromstring(raw, parser=_parser())
    except etree.XMLSyntaxError as exc:
        raise StatementError(
            "Plik XML jest uszkodzony — to nie jest wyciąg CAMT.053."
        ) from exc
    # Deklaracja DOCTYPE w innym kodowaniu (np. UTF-16) omija sprawdzenie bajtów.
    if root.getroottree().docinfo.doctype:
        raise StatementError("Wyciąg CAMT.053 nie może mieć deklaracji DOCTYPE.")
    statements = root.findall(".//{*}BkToCstmrStmt/{*}Stmt")
    if not statements:
        raise StatementError("To nie jest wyciąg CAMT.053 (brak BkToCstmrStmt/Stmt).")
    account: Optional[str] = None
    currency: Optional[str] = None
    lines: list[StatementLine] = []
    accounts: list[str] = []
    balances: list[BalanceCheck] = []
    for number, statement in enumerate(statements, start=1):
        movement = Decimal("0")
        iban = _text(statement, "{*}Acct/{*}Id/{*}IBAN")
        try:
            accounts.append(
                normalize_nrb(iban)
                if iban
                else _text(statement, "{*}Acct/{*}Id/{*}Othr/{*}Id")
            )
        except AccountError:
            accounts.append(iban)
        if iban and account is None:
            try:
                account = normalize_nrb(iban)
            except AccountError:
                account = None
        statement_currency = (_text(statement, "{*}Acct/{*}Ccy") or "PLN").upper()
        currency = currency or statement_currency
        for entry in statement.findall("{*}Ntry"):
            indicator = _text(entry, "{*}CdtDbtInd")
            if indicator not in ("DBIT", "CRDT") or not _booked(entry):
                continue
            # Kierunek wpisu = CdtDbtInd, także w stornie (docstring modułu).
            direction = "debit" if indicator == "DBIT" else "credit"
            reversed_ = _text(entry, "{*}RvslInd").lower() == "true"
            booked = _date(entry, "{*}BookgDt") or _date(entry, "{*}ValDt")
            if booked is None:
                raise StatementError("Wyciąg CAMT.053: operacja bez daty księgowania.")
            entry_amount = _amount(entry.find("{*}Amt"), statement_currency)
            entry_ref = _text(entry, "{*}AcctSvcrRef") or _text(entry, "{*}NtryRef")
            # Kontrahent pierwotnej operacji: storno uznania (DBIT) to zwrot
            # pieniędzy płacącemu (Dbtr), storno obciążenia (CRDT) — zwrot od
            # odbiorcy naszego przelewu (Cdtr).
            original_debit = (indicator == "DBIT") != reversed_
            party = "Cdtr" if original_debit else "Dbtr"
            details = entry.findall("{*}NtryDtls/{*}TxDtls")
            first_line = len(lines)
            for tx in details or [None]:
                amount = None
                if tx is not None:
                    amount = _amount(tx.find("{*}Amt"), statement_currency) or _amount(
                        tx.find("{*}AmtDtls/{*}TxAmt/{*}Amt"), statement_currency
                    )
                if amount is None or len(details) <= 1:
                    amount = entry_amount or amount
                if amount is None:
                    raise StatementError("Wyciąg CAMT.053: operacja bez kwoty.")
                reference = ""
                if tx is not None:
                    reference = _text(tx, "{*}Refs/{*}AcctSvcrRef") or _text(
                        tx, "{*}Refs/{*}EndToEndId"
                    )
                    if reference.upper() == "NOTPROVIDED":
                        reference = ""
                lines.append(
                    StatementLine(
                        index=len(lines) + 1,
                        booked_on=booked,
                        amount=amount[0],
                        direction=direction,
                        currency=amount[1],
                        title=_title(entry, tx),
                        counterparty_name=_name(tx, party),
                        counterparty_account=_account(tx, party),
                        bank_ref=(reference or entry_ref)[:48],
                    )
                )
                if len(lines) > MAX_LINES:
                    raise StatementError(
                        "Wyciąg ma za dużo operacji — podziel go na miesiące."
                    )
            # Saldo zmienia kwota pozycji; bez niej — suma jej transakcji.
            total = (
                entry_amount[0]
                if entry_amount
                else sum((line.amount for line in lines[first_line:]), Decimal("0"))
            )
            movement += -total if direction == "debit" else total
        opening = _balance(statement, ("OPBD", "PRCD"))
        closing = _balance(statement, ("CLBD",))
        if opening is not None and closing is not None:
            balances.append(
                BalanceCheck(
                    statement=number,
                    opening=opening[0],
                    movement=movement,
                    closing=closing[0],
                    opening_day=opening[1],
                    closing_day=closing[1],
                    number=_statement_number(statement),
                )
            )
    return ParsedStatement(
        format="camt053",
        account=account,
        currency=currency,
        lines=tuple(lines),
        accounts=tuple(accounts),
        balances=tuple(balances),
    )


__all__ = ["looks_like", "parse"]
