"""Raport Time for Teams z maila → wersja raportu godzin klienta (Nordea, 23.11.2026).

Cost Control Nordei wysyła raport T4T do koordynatorki rozliczeń i na wsparcie@; gdy
zapomni, Finanse przekazują go dalej. Czytnik rozliczeń (``consultant_portal/mailbox.py``)
podaje tu załączniki maila, zanim zapisze je jako dokumenty konsultantów:

* arkusz rozpoznany jako T4T (``t4t.read``) staje się kolejną wersją raportu miesiąca,
  tak jak „Wgraj raport” na ekranie (``time_reports.upload``); ten sam plik drugi raz to
  duplikat bez nowej wersji;
* skoroszyt z kilkoma arkuszami raportu (kolejne wersje złożone przez Finanse) = ostatni
  arkusz, bo to najnowszy stan; wersji nie sumujemy;
* klient to ten jeden klient, który ma na ten miesiąc regułę ``report.time_for_teams``
  albo wgrane raporty (``time_reports.enabled_clients``). Zero albo kilku = arkusz zostaje
  zwykłym dokumentem do ręcznego wgrania, z wpisem w logu.

Arkusz wczytany jako raport nie trafia już do dokumentów konsultantów (byłby kartą bez osoby).
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.client_settlements import t4t, time_reports
from app.services.client_settlements.service import SettlementError

logger = logging.getLogger(__name__)

_SHEET_EXTENSIONS = (".xlsx", ".xlsm")


@dataclass
class T4tMailResult:
    consumed: set[int] = field(default_factory=set)
    versions: int = 0
    duplicates: int = 0


def _read(content: bytes) -> Optional[list[t4t.T4tSheet]]:
    try:
        sheets = t4t.read(content)
    except t4t.T4tError:
        return None
    return sheets or None


async def _client_for(db: AsyncSession, month: str) -> Optional[int]:
    clients = await time_reports.enabled_clients(db, month)
    return clients[0] if len(clients) == 1 else None


async def ingest(
    db: AsyncSession, files: list[dict[str, Any]], *, received_on: date
) -> T4tMailResult:
    """Wczytaj arkusze T4T z załączników; ``consumed`` = indeksy plików wczytanych."""

    result = T4tMailResult()
    for index, attachment in enumerate(files):
        name = str(attachment.get("name") or "")
        raw = attachment.get("contentBytes")
        if attachment.get("isInline") or not isinstance(raw, str):
            continue
        if not name.lower().endswith(_SHEET_EXTENSIONS):
            continue
        try:
            content = base64.b64decode(raw, validate=True)
        except ValueError:
            continue
        sheets = await asyncio.to_thread(_read, content)
        if not sheets:
            continue
        chosen = sheets[-1]
        if not chosen.rows or chosen.month is None:
            continue
        client_id = await _client_for(db, chosen.month)
        if client_id is None:
            logger.warning(
                "t4t_mail: raport %s bez jednego klienta z regułą T4T, zostaje dokumentem",
                chosen.month,
            )
            continue
        try:
            async with db.begin_nested():
                outcome = await time_reports.upload(
                    db,
                    client_id,
                    chosen.month,
                    received_on=received_on,
                    file_name=name or None,
                    content=content,
                    sheet=chosen.name if len(sheets) > 1 else None,
                    actor=None,
                )
        except SettlementError as exc:
            logger.warning(
                "t4t_mail: raport %s odrzucony (%s)", chosen.month, exc.message
            )
            continue
        result.consumed.add(index)
        if outcome.get("duplicate"):
            result.duplicates += 1
        else:
            result.versions += 1
    return result
