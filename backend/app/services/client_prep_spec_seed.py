"""Jednorazowy zasiew „Specyfiki na prep” w kartach 12 klientów (F2, 24.11.2026).

Decyzje Artura z 24.11.2026 (pamięć „Fundamenty prepa i specyfika klientów”):
specyfika z odpowiedzi DL-i trafia do kart od razu, sprzeczności z kartami są
rozstrzygnięte. Krok robi dwie rzeczy, każdą tylko na swoim warunku:

- ``prep_spec`` u klienta z ``PREP_SPECS``, gdy karta istnieje, a specyfiki
  jeszcze nie ma (wpisanej przez człowieka nie nadpisujemy);
- Tauron: w „Co powiedzieć kandydatowi” zdanie o sztywnym limicie 165 h →
  godziny według zlecenia rekrutacyjnego, do biur dochodzi Warszawa; tylko gdy
  zdania stoją jak w kopii z 24.11.

Uwag tylko dla zespołu (czego kandydat ma nie usłyszeć) krok nie wpisuje:
repo jest publiczne, więc dopisuje je Delivery Lead w karcie.

Każda zmieniona karta dostaje nową wersję i wpis w historii
(``client_playbook_events``, ``action="saved"``, z diffem jak przy zapisie
z formularza). Paragon pod ``REPAIR_MARKER`` niesie tylko id klientów i kody.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.client_playbook import ClientPlaybook
from app.models.client_playbook_event import ClientPlaybookEvent
from app.services.client_prep_spec import normalize_prep_spec
from app.services.client_prep_spec_data import (
    PREP_SPECS,
    TAURON,
    TAURON_ABOUT_REPLACEMENTS,
)

logger = logging.getLogger(__name__)

REPAIR_MARKER = "client_prep_spec_seed_2026_11_24"
ACTOR_NAME = "NEXUS (specyfika na prep z odpowiedzi DL-i)"


def _tauron_about(current: Optional[str]) -> Optional[str]:
    """Nowy tekst albo ``None``, gdy któregoś zdania już nie ma (ktoś zmienił kartę)."""

    if not current:
        return None
    updated = current
    for old, new in TAURON_ABOUT_REPLACEMENTS:
        if old not in updated:
            return None
        updated = updated.replace(old, new, 1)
    return updated


def _changes_for(
    row: ClientPlaybook,
    specs: dict[int, dict[str, list[str]]],
    tauron_id: int,
) -> dict[str, dict[str, Any]]:
    changes: dict[str, dict[str, Any]] = {}
    spec = specs.get(row.client_id)
    if spec is not None and not row.prep_spec:
        changes["prep_spec"] = {"from": None, "to": normalize_prep_spec(spec)}
    if row.client_id == tauron_id:
        about = _tauron_about(row.about_for_candidate)
        if about is not None:
            changes["about_for_candidate"] = {
                "from": row.about_for_candidate,
                "to": about,
            }
    return changes


async def run_client_prep_spec_seed(
    db: AsyncSession,
    *,
    marker: str = REPAIR_MARKER,
    specs: Optional[dict[int, dict[str, list[str]]]] = None,
    tauron_id: int = TAURON,
) -> Optional[dict[str, Any]]:
    """Zasiej i popraw karty; ``None`` = już wykonane. Wołający commituje.

    ``specs`` i ``tauron_id`` podmieniają tylko testy (id z produkcji
    nie istnieją w bazie testowej).
    """
    specs = PREP_SPECS if specs is None else specs

    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    if await db.get(AppSetting, marker) is not None:
        return None
    rows = (
        await db.execute(
            select(ClientPlaybook)
            .where(ClientPlaybook.client_id.in_(sorted(specs)))
            .with_for_update()
        )
    ).scalars()
    found: dict[int, ClientPlaybook] = {row.client_id: row for row in rows}
    results: list[dict[str, Any]] = []
    for client_id in sorted(specs):
        row = found.get(client_id)
        if row is None:
            results.append({"client_id": client_id, "skipped": "no_card"})
            continue
        changes = _changes_for(row, specs, tauron_id)
        if not changes:
            results.append({"client_id": client_id, "skipped": "nothing_to_change"})
            continue
        for field, change in changes.items():
            setattr(row, field, change["to"])
        row.version = int(row.version or 1) + 1
        db.add(
            ClientPlaybookEvent(
                client_id=client_id,
                playbook_version=row.version,
                action="saved",
                changes=changes,
                actor_user_id=None,
                actor_name=ACTOR_NAME,
            )
        )
        results.append(
            {"client_id": client_id, "skipped": None, "fields": sorted(changes)}
        )
    summary = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "changed": sum(1 for r in results if r["skipped"] is None),
        "results": results,
    }
    db.add(AppSetting(key=marker, value=summary))
    await db.flush()
    logger.info("client prep spec seed: %s/%s", summary["changed"], len(results))
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already done"
    skipped = [
        f"{r['client_id']}:{r['skipped']}" for r in summary["results"] if r["skipped"]
    ]
    return f"changed={summary['changed']} skipped={','.join(skipped) or '-'}"
