"""Porównanie JPK_KR_PD z NEXUSA z plikiem z Symfonii FK (K8c).

Dopóki księgą urzędową roku jest Symfonia (tryb roku ``symfonia`` albo
``parallel``), NEXUS pokazuje różnice między swoim plikiem rocznym a plikiem
z Symfonii — tak jak porównanie JPK_V7M (K5b-3b). Pliku nie zapisujemy.

* Plik czytany bez sieci, encji i DTD (lxml), po nazwach elementów bez
  przestrzeni nazw; rok z nagłówka (``DataOd``/``DataDo``) musi być rokiem
  porównania (422), do 100 MB (413).
* ZOiS po numerze konta (``S_1``): kwoty ``S_4``–``S_11`` w groszach i znaczniki
  ``S_12_1``/``S_12_2``; konta tylko po jednej stronie. Dziennik: liczba
  dowodów i sumy kontrolne ``Ctrl``.
* Plik ma dokumenty płacowe — porównuje osoba z Płacami albo administrator.
"""

from __future__ import annotations

from typing import Any, Optional

from lxml import etree
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.finance_ledger.costs import LedgerError
from app.services.ledger import jpk_kr
from app.services.ledger.documents import Viewer
from app.services.ledger.jpk_compare import _child, _grosze, _local
from app.services.ledger.settings import LedgerSettings

MAX_BYTES = 100 * 1024 * 1024
LISTED_MAX = 200
AMOUNT_FIELDS = ("S_4", "S_5", "S_6", "S_7", "S_8", "S_9", "S_10", "S_11")
CTRL_FIELDS = ("C_1", "C_2", "C_3", "C_4", "C_5")
#: C_1 i C_3 to liczby, reszta — kwoty.
CTRL_COUNTS = ("C_1", "C_3")


def parse(content: bytes) -> dict[str, Any]:
    """JPK_KR_PD → rok, konta ZOiS (kwoty w groszach, znaczniki), sumy Ctrl."""

    if len(content) > MAX_BYTES:
        raise LedgerError("Plik z Symfonii jest za duży (najwyżej 100 MB).", status=413)
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, huge_tree=True, load_dtd=False
    )
    try:
        root = etree.fromstring(content, parser)
    except etree.XMLSyntaxError:
        raise LedgerError("To nie jest plik XML JPK.", status=422) from None
    if _local(root) != "JPK":
        raise LedgerError("To nie jest plik JPK_KR_PD (brak elementu JPK).", status=422)
    head = next((node for node in root if _local(node) == "Naglowek"), None)
    if head is None:
        raise LedgerError("Plik JPK bez nagłówka.", status=422)
    starts = _child(head, "DataOd") or _child(head, "RokDataOd") or ""
    ends = _child(head, "DataDo") or _child(head, "RokDataDo") or ""
    try:
        year = int(starts[:4])
        end_year = int(ends[:4])
    except ValueError:
        raise LedgerError("Plik JPK bez okresu w nagłówku.", status=422) from None
    accounts: dict[str, dict[str, Any]] = {}
    for node in root.iter():
        if not isinstance(node.tag, str) or not _local(node).startswith("ZOiS"):
            continue
        if _local(node) == "ZOiS":
            continue
        number = (_child(node, "S_1") or "").strip()
        if not number:
            continue
        accounts[number] = {
            "amounts": {key: _grosze(_child(node, key)) for key in AMOUNT_FIELDS},
            "markers": [
                value
                for value in (_child(node, "S_12_1"), _child(node, "S_12_2"))
                if value
            ],
        }
    ctrl_node = next((node for node in root if _local(node) == "Ctrl"), None)
    ctrl: dict[str, int] = {}
    if ctrl_node is not None:
        for key in CTRL_FIELDS:
            text = _child(ctrl_node, key)
            if text is None:
                continue
            ctrl[key] = int(text) if key in CTRL_COUNTS else _grosze(text)
    return {"year": year, "end_year": end_year, "accounts": accounts, "ctrl": ctrl}


def _markers(pair: Optional[jpk_kr.Pair]) -> list[str]:
    pair = pair or jpk_kr.Pair(jpk_kr.OTHER, jpk_kr.OTHER)
    return [pair.debit] if pair.debit == pair.credit else [pair.debit, pair.credit]


def ours(prepared: jpk_kr.Prepared) -> dict[str, Any]:
    accounts = {
        row.account: {
            "amounts": {
                "S_4": row.bo_debit,
                "S_5": row.bo_credit,
                "S_6": row.debit,
                "S_7": row.credit,
                "S_8": row.debit,
                "S_9": row.credit,
                "S_10": row.balance_debit,
                "S_11": row.balance_credit,
            },
            "markers": _markers(row.pair),
        }
        for row in prepared.rows
    }
    lines = [line for doc in prepared.docs for line in doc.lines]
    ctrl = {
        "C_1": len(prepared.docs),
        "C_2": sum(line.amount for line in lines if line.side == "debit"),
        "C_3": len(lines),
        "C_4": sum(line.amount for line in lines if line.side == "debit"),
        "C_5": sum(line.amount for line in lines if line.side == "credit"),
    }
    return {"accounts": accounts, "ctrl": ctrl}


def compare(nexus: dict[str, Any], symfonia: dict[str, Any]) -> dict[str, Any]:
    """Różnice kont (kwoty, znaczniki, jednostronne) i sum kontrolnych."""

    ours_accounts = nexus["accounts"]
    theirs = symfonia["accounts"]
    amounts: list[dict[str, Any]] = []
    marker_diffs: list[dict[str, Any]] = []
    for number in sorted(set(ours_accounts) & set(theirs), key=jpk_kr.account_order):
        mine, other = ours_accounts[number], theirs[number]
        fields = {
            key: {"nexus": mine["amounts"][key], "symfonia": other["amounts"][key]}
            for key in AMOUNT_FIELDS
            if mine["amounts"][key] != other["amounts"][key]
        }
        if fields:
            amounts.append({"account": number, "fields": fields})
        if mine["markers"] != other["markers"]:
            marker_diffs.append(
                {
                    "account": number,
                    "nexus": mine["markers"],
                    "symfonia": other["markers"],
                }
            )
    only_nexus = sorted(set(ours_accounts) - set(theirs), key=jpk_kr.account_order)
    only_symfonia = sorted(set(theirs) - set(ours_accounts), key=jpk_kr.account_order)
    ctrl = {
        key: {"nexus": nexus["ctrl"].get(key), "symfonia": symfonia["ctrl"].get(key)}
        for key in CTRL_FIELDS
        if nexus["ctrl"].get(key) != symfonia["ctrl"].get(key)
    }
    total = len(amounts) + len(marker_diffs) + len(only_nexus) + len(only_symfonia)
    return {
        "same": total == 0 and not ctrl,
        "accounts_nexus": len(ours_accounts),
        "accounts_symfonia": len(theirs),
        "amounts": amounts[:LISTED_MAX],
        "markers": marker_diffs[:LISTED_MAX],
        "only_nexus": only_nexus[:LISTED_MAX],
        "only_symfonia": only_symfonia[:LISTED_MAX],
        "ctrl": ctrl,
        "differences": total + len(ctrl),
    }


async def run(
    db: AsyncSession,
    viewer: Viewer,
    settings: LedgerSettings,
    *,
    year: int,
    content: bytes,
) -> dict[str, Any]:
    if not jpk_kr.can_download(viewer):
        raise LedgerError(
            "JPK_KR_PD zawiera dokumenty płacowe — porównuje go osoba z Płacami "
            "albo administrator.",
            status=403,
        )
    row = await jpk_kr.year_row(db, year)
    if row.mode == "nexus":
        raise LedgerError(
            "Rok jest prowadzony w NEXUSIE — porównanie z Symfonią jest do "
            "przełączenia księgi.",
            status=409,
        )
    symfonia = parse(content)
    if symfonia["year"] != year or symfonia["end_year"] != year:
        raise LedgerError(
            f"Plik z Symfonii jest za {symfonia['year']}, a porównanie za {year}.",
            status=422,
        )
    prepared = await jpk_kr.prepare(db, settings, year=year)
    return {"year": year, **compare(ours(prepared), symfonia)}
