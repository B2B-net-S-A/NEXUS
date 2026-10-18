"""Wyciąg CAMT.053 (ISO 20022, ``BkToCstmrStmt``) — wersje 001.02–001.13.

Elementy szukamy po nazwie lokalnej (``{*}``), więc wersja przestrzeni nazw
nie ma znaczenia. Pozycja (``Ntry``) może nieść kilka transakcji (``TxDtls``,
księgowanie zbiorcze) — każda jest osobnym wierszem z własną kwotą; bez
``TxDtls`` wierszem jest sama pozycja. Kontrahent obciążenia to wierzyciel
(``Cdtr``/``CdtrAcct``), uznania — dłużnik (``Dbtr``/``DbtrAcct``).

Plik od użytkownika: parser bez DTD, encji i sieci (lxml ``resolve_entities``
wyłączone, ``<!DOCTYPE`` odrzucany), bez ogromnych drzew.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from lxml import etree

from app.services.hr.bank.accounts import AccountError, mask_accounts, normalize_nrb
from app.services.hr.bank.parsed import ParsedStatement, StatementError, StatementLine

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


def _amount(node: Optional[etree._Element]) -> Optional[tuple[Decimal, str]]:
    if node is None or not (node.text or "").strip():
        return None
    try:
        value = Decimal(node.text.strip())
    except InvalidOperation as exc:
        raise StatementError("Wyciąg CAMT.053 ma niepoprawną kwotę.") from exc
    return abs(value), (node.get("Ccy") or "PLN").upper()


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
    for statement in statements:
        iban = _text(statement, "{*}Acct/{*}Id/{*}IBAN")
        if iban and account is None:
            try:
                account = normalize_nrb(iban)
            except AccountError:
                account = None
        currency = currency or _text(statement, "{*}Acct/{*}Ccy") or None
        for entry in statement.findall("{*}Ntry"):
            indicator = _text(entry, "{*}CdtDbtInd")
            if indicator not in ("DBIT", "CRDT"):
                continue
            # Storno odwraca kierunek (zwrot naszego przelewu to uznanie).
            reversed_ = _text(entry, "{*}RvslInd").lower() == "true"
            debit = (indicator == "DBIT") != reversed_
            direction = "debit" if debit else "credit"
            booked = _date(entry, "{*}BookgDt") or _date(entry, "{*}ValDt")
            if booked is None:
                raise StatementError("Wyciąg CAMT.053: operacja bez daty księgowania.")
            entry_amount = _amount(entry.find("{*}Amt"))
            entry_ref = _text(entry, "{*}AcctSvcrRef") or _text(entry, "{*}NtryRef")
            party = "Cdtr" if indicator == "DBIT" else "Dbtr"
            details = entry.findall("{*}NtryDtls/{*}TxDtls")
            for tx in details or [None]:
                amount = None
                if tx is not None:
                    amount = _amount(tx.find("{*}Amt")) or _amount(
                        tx.find("{*}AmtDtls/{*}TxAmt/{*}Amt")
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
    return ParsedStatement(
        format="camt053", account=account, currency=currency, lines=tuple(lines)
    )


__all__ = ["looks_like", "parse"]
