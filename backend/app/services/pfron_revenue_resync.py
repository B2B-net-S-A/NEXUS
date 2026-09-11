"""PFRON 507–509 (0306) — krok przychodu kontraktu zaraz po rozdzieleniu zamówień.

Korekta 0306 (``pfron_renewal_split_repair``) jest surowym SQL-em, więc nie
wyzwala synchronizacji kontrakt ↔ zamówienia (0304). Zostawia harmonogram
przychodu kontraktów w stanie sprzed korekty: krok z nadpisanego zamówienia
(nowa stawka od 01.09) idzie razem z wierszem na nowe zamówienie, a przywrócony
okres nie ma własnego kroku — resolver czyta więc czerwiec–sierpień stawką
NOWEGO okresu, aż do najbliższego zapisu zamówienia tej osoby.

Ten krok domyka lukę od razu: czyta paragon 0306 i dla każdego rozdzielonego
kontraktu, którego przywrócony okres niesie start i stawkę
(``contract_revenue_resync == pending``), woła tę samą funkcję, co zwykły zapis
zamówienia (``contract_order_sync.resync_contract`` — z audytem
``synced_with_orders``), bez autoaktywacji szkicu. Tylko przy włączonej
synchronizacji 0304: bez niej system zachowuje się jak przed wdrożeniem 0304
i nie ma czego domykać.

Jednorazowy: własny marker w ``app_settings`` + własny advisory lock, czekanie
na blokady ograniczone ``lock_timeout``, blokada wiersza klienta jak u writera
maila. Brak paragonu 0306 (blok jeszcze nie przeszedł) = nic, bez markera —
następny start spróbuje ponownie. Wołający commituje; ``entrypoint.sh`` loguje
wyłącznie liczby (:func:`summarize_for_log`).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.services import contract_order_sync
from app.services.pfron_renewal_split_repair import (
    DEFAULT_LOCK_TIMEOUT,
    PFRON_RENEWAL_SPLIT_MARKER,
    REVENUE_RESYNC_PENDING,
)

PFRON_REVENUE_RESYNC_MARKER = "0306_pfron_revenue_resync"

STATUS_DONE = "done"
STATUS_SKIPPED = "skipped"
STATUS_SKIPPED_SYNC_DISABLED = "skipped_sync_disabled"

#: Pierwsza wersja bloku 0306 (sprzed utwardzenia) pisała tę wartość przy
#: KAŻDYM podziale — gdyby to ona przeszła na produkcji pierwsza, luka
#: w przychodzie jest ta sama, więc krok ją też domyka.
_LEGACY_PENDING = "pending_next_order_write"


def _pending_contract_ids(receipt: Mapping[str, Any]) -> list[int]:
    """Kontrakty rozdzielonych zamówień, którym korekta zostawiła lukę w przychodzie."""
    ids = {
        int(entry["contract_id"])
        for entry in receipt.get("orders") or []
        if entry.get("status") == "split"
        and entry.get("contract_revenue_resync")
        in (REVENUE_RESYNC_PENDING, _LEGACY_PENDING)
        and entry.get("contract_id") is not None
    }
    return sorted(ids)


async def run_pfron_revenue_resync(
    db: AsyncSession,
    *,
    split_marker: str = PFRON_RENEWAL_SPLIT_MARKER,
    marker: str = PFRON_REVENUE_RESYNC_MARKER,
    today: Optional[date] = None,
    lock_timeout: str = DEFAULT_LOCK_TIMEOUT,
) -> Optional[dict[str, Any]]:
    """Synchronizuj przychód kontraktów po korekcie 0306. ``None`` = nic w tym biegu.

    ``None`` znaczy: krok już wykonany (marker) albo korekta 0306 jeszcze
    nie przeszła (brak jej paragonu) — w obu przypadkach bez zapisu.
    Inaczej zwraca podsumowanie, które zapisuje też jako marker.
    """
    await db.execute(
        text("SELECT set_config('lock_timeout', :timeout, true)"),
        {"timeout": lock_timeout},
    )
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    if await db.get(AppSetting, marker) is not None:
        return None
    split = await db.get(AppSetting, split_marker)
    if split is None:
        return None
    receipt: Mapping[str, Any] = split.value or {}
    contract_ids = _pending_contract_ids(receipt)

    summary: dict[str, Any] = {
        "revision": marker,
        "split_receipt": split_marker,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "contract_ids": contract_ids,
    }
    if not contract_ids:
        summary["status"] = STATUS_SKIPPED
        summary["reason"] = "no_split_contract_needs_revenue_resync"
    elif not await contract_order_sync.sync_enabled(db):
        summary["status"] = STATUS_SKIPPED_SYNC_DISABLED
    else:
        # Writer maila zaczyna od tej blokady (``apply_document``), a
        # synchronizacja blokuje potem wiersz kontraktu — ta sama kolejność.
        client_id = receipt.get("client_id")
        if client_id is not None:
            await db.execute(
                text("SELECT id FROM clients WHERE id = :client_id FOR UPDATE"),
                {"client_id": int(client_id)},
            )
        results: list[dict[str, Any]] = []
        for contract_id in contract_ids:
            outcome = await contract_order_sync.resync_contract(
                db,
                contract_id,
                actor_id=None,
                today=today,
                auto_activate=False,
            )
            if outcome is None:
                results.append(
                    {"contract_id": contract_id, "result": "contract_missing"}
                )
                continue
            results.append(
                {
                    "contract_id": contract_id,
                    "result": "changed" if outcome.changed else "unchanged",
                    "details": outcome.as_details(),
                }
            )
        summary["status"] = STATUS_DONE
        summary["contracts"] = results

    db.add(AppSetting(key=marker, value=summary))
    await db.flush()
    return summary


def summarize_for_log(summary: Optional[Mapping[str, Any]]) -> str:
    """Jedna linia do logu kontenera: status i liczby — bez stawek i nazw."""
    if summary is None:
        return "nothing to do (already done or 0306 receipt missing)"
    line = f"status={summary.get('status')} contracts={len(summary.get('contract_ids') or [])}"
    results = summary.get("contracts")
    if results is not None:
        changed = sum(1 for item in results if item.get("result") == "changed")
        missing = sum(1 for item in results if item.get("result") == "contract_missing")
        line += f" changed={changed} missing={missing}"
    return line
