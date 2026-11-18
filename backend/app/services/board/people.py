"""Zakładka „Firma” Rady (R7): placementy, kontraktorzy na projektach, zejścia.

Uwagi Rady z 18.11.2026: widok z Insights był za rozbudowany. Rada chce
placementów, liczby kontraktorów na projektach, zejść z opisem powodów
i wniosków; lejek może być zwinięty.

* **Placement** — pierwsze ``hired`` per para kandydat × rekrutacja
  (``analytics_kpi_milestones``), ta sama definicja co Insights → Firma.
* **Kontraktorzy na projektach** — kontrakty wykonywane w ostatnim dniu okna
  (``running_on``), według klienta (``project_name`` kontraktu jest prawie
  zawsze pusty, więc projektem jest klient).
* **Zejście** — kontrakt zakończony z datą końca w oknie (``departure_day``,
  ta sama funkcja co ruch konsultantów w Insights); powód, kto wypowiedział
  i „czego się nauczyliśmy” z okna zakończenia kontraktu.

Bez nazwisk konsultantów (jak w Insights dla Rady): klient i powód. Nazwy
rekrutacji też nie wychodzą — tytuł bywa „NAMED req — imię i nazwisko”.
Placementy sprzed 12.10.2026 pochodzą z raportów DynaReportera i nie mają
rekrutacji ani klienta — liczą się jako „bez przypisania”.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.services.client_identity import client_display_name_expression
from app.services.contract_placements_export import TERMINATION_LABELS
from app.services.insights_board_money import running_on
from app.services.integration_insights import (
    contract_flows,
    departure_day,
    load_contracts,
)

TOP_CLIENTS = 12
PARTY_LABELS = {"consultant": "konsultant", "company": "B2B.net"}
MODE_LABELS = {"notice": "wypowiedzenie", "mutual_agreement": "porozumienie stron"}


def _reason(contract: Any) -> str:
    value = contract.termination_reason
    return value.value if value is not None else "unknown"


def without_name(text_value: str, candidate: Any) -> str:
    """Opis zakończenia bez imienia i nazwiska konsultanta (także odmienionych:
    „Michała”, „Dyzmy”) — opis bywa wklejonym mailem klienta z nazwiskiem."""

    if not text_value or candidate is None:
        return text_value
    out = text_value
    for part in (
        getattr(candidate, "name", None),
        getattr(candidate, "lastname", None),
    ):
        for token in (part or "").split():
            if len(token) < 3:
                continue
            stem = token[: max(3, len(token) - 2)]
            out = re.sub(
                rf"\b{re.escape(stem)}\w*", "[konsultant]", out, flags=re.IGNORECASE
            )
    return re.sub(r"\[konsultant\](\s+\[konsultant\])+", "[konsultant]", out)


def reason_label(key: str) -> str:
    return TERMINATION_LABELS.get(key, "powód nie wpisany")


def exits(
    contracts: list[Any],
    first: date,
    last: date,
    clients: dict[int, str],
) -> dict[str, Any]:
    """Zejścia w oknie: liczba, powody (malejąco) i lista bez nazwisk."""

    items = []
    for contract in contracts:
        day = departure_day(contract)
        if day is None or not first <= day <= last:
            continue
        tenure = (
            round((day - contract.start_date).days / 30.44, 1)
            if contract.start_date
            else None
        )
        items.append(
            {
                "ended_on": day.isoformat(),
                "client": clients.get(contract.client_id, "—"),
                "project": contract.project_name,
                "reason": _reason(contract),
                "reason_label": reason_label(_reason(contract)),
                "lessons": without_name(
                    (contract.termination_lessons or "").strip(),
                    getattr(contract, "candidate", None),
                )
                or None,
                "party": PARTY_LABELS.get(contract.agreement_termination_party or ""),
                "mode": MODE_LABELS.get(contract.agreement_termination_mode or ""),
                "tenure_months": tenure,
            }
        )
    items.sort(key=lambda item: item["ended_on"], reverse=True)
    counts = Counter(item["reason"] for item in items)
    return {
        "count": len(items),
        "by_reason": [
            {"reason": key, "label": reason_label(key), "count": count}
            for key, count in counts.most_common()
        ],
        "items": items,
    }


def contractors_by_client(
    running: list[Any], clients: dict[int, str]
) -> list[dict[str, Any]]:
    per_client: dict[int, list[Any]] = defaultdict(list)
    for contract in running:
        per_client[contract.client_id].append(contract)
    rows = [
        {
            "client": clients.get(client_id, "—"),
            "count": len(items),
        }
        for client_id, items in per_client.items()
    ]
    rows.sort(key=lambda row: (-row["count"], row["client"]))
    if len(rows) <= TOP_CLIENTS:
        return rows
    rest = rows[TOP_CLIENTS:]
    return rows[:TOP_CLIENTS] + [
        {
            "client": f"pozostali klienci ({len(rest)})",
            "count": sum(row["count"] for row in rest),
            "rest": True,
        }
    ]


UNASSIGNED = "bez przypisania (raporty sprzed 12.10.2026)"


async def placements(
    db: AsyncSession, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            text(
                """
                SELECT fm.first_reached_at::date AS day,
                       COALESCE(NULLIF(btrim(c.display_name), ''), c.name) AS client
                FROM analytics_kpi_milestones fm
                LEFT JOIN jobs j ON j.id = fm.job_id
                LEFT JOIN clients c ON c.id = j.client_id
                WHERE fm.stage::text = 'hired'
                  AND fm.first_reached_at >= :start AND fm.first_reached_at < :end
                ORDER BY fm.first_reached_at DESC
                """
            ),
            {"start": start, "end": end},
        )
    ).all()
    return [
        {"day": day.isoformat(), "client": client or UNASSIGNED} for day, client in rows
    ]


def placements_by_client(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(item["client"] for item in items)
    rows = [{"client": client, "count": count} for client, count in counts.items()]
    rows.sort(
        key=lambda row: (row["client"] == UNASSIGNED, -row["count"], row["client"])
    )
    return rows


async def _clients(db: AsyncSession, contracts: list[Any]) -> dict[int, str]:
    client_ids = {c.client_id for c in contracts if c.client_id}
    clients = (
        dict(
            (
                await db.execute(
                    select(Client.id, client_display_name_expression()).where(
                        Client.id.in_(client_ids)
                    )
                )
            ).all()
        )
        if client_ids
        else {}
    )
    return clients


async def people_view(
    db: AsyncSession,
    *,
    window: tuple[date, date],
    previous: tuple[date, date],
    bounds: tuple[datetime, datetime],
    previous_bounds: tuple[datetime, datetime],
) -> dict[str, Any]:
    first, last = window
    prev_first, prev_last = previous
    contracts = await load_contracts(db, first=min(first, prev_first), last=last)
    clients = await _clients(db, contracts)
    running = running_on(contracts, last)
    previous_running = running_on(contracts, prev_last)
    flows = contract_flows(contracts, first, last)
    prev_flows = contract_flows(contracts, prev_first, prev_last)
    placed = await placements(db, *bounds)
    placed_before = await placements(db, *previous_bounds)
    return {
        "window": {"from": first.isoformat(), "to": last.isoformat()},
        "previous_window": {
            "from": prev_first.isoformat(),
            "to": prev_last.isoformat(),
        },
        "placements": {
            "count": len(placed),
            "previous": len(placed_before),
            "by_client": placements_by_client(placed),
        },
        "contractors": {
            "active": len(running),
            "previous": len(previous_running),
            "clients": len({c.client_id for c in running}),
            "by_client": contractors_by_client(running, clients),
        },
        "flows": {
            "starts": flows.starts,
            "ends": flows.ends,
            "resignations": flows.resignations,
            "previous_starts": prev_flows.starts,
            "previous_ends": prev_flows.ends,
        },
        "exits": exits(contracts, first, last, clients),
        "previous_exits": exits(contracts, prev_first, prev_last, clients)["by_reason"],
    }
