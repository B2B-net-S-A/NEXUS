"""Sprzątanie rekordów testowych z produkcji (decyzja Artura 20.10.2026).

Ręczny audyt UI z 26–27.09.2026 (``docs/audits/2026-09-25/manual-ui-codex-
2026-09-26.md``, „Rekordów nie usuwano”) zostawił na produkcji fikcyjne osoby,
kontrakt testowy z końcem przed startem i szkice kontraktów na kliencie
„NEXUS QA UI”. Do tego osoba „E2E AutoApply” z Traffita (auto-aplikator).

Jednorazowo (paragon w ``app_settings`` + advisory lock), w jednej transakcji:

1. szkice zamówień przy szkicach kontraktów klienta testowego znikają tak jak
   przy „Usuń” (karta braku zamknięta, krok stawki zdjęty);
2. kontrakty testowe → ``void`` przez ``void_contract`` (dokumenty zostają);
3. spotkania z Outlooka, które synchronizacja podpięła do osoby testowej tylko
   dlatego, że jej e-mail to adres pracownika, wracają bez osoby albo do
   prawdziwego kandydata spośród uczestników (ta sama reguła co w ``sync``:
   najniższe ``id``, bez domen firmy) — zanim usunięcie zanonimizuje
   spotkania tej osoby;
4. osoby testowe są usuwane tą samą ścieżką co przycisk „Usuń” w profilu
   (``candidate_hard_delete``).

Każdy wiersz jest przypięty do ``id`` i odcisku (imię, klient, status); wiersz,
który się nie zgadza, zostaje nietknięty i trafia do paragonu jako pominięty.
Paragon niesie wyłącznie id i liczby.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.app_setting import AppSetting
from app.models.calendar_event import CalendarEvent
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus
from app.services import candidate_hard_delete
from app.services.candidate_hard_delete import EraseOutcome
from app.services.m365.calendar import M365_SOURCE

logger = logging.getLogger(__name__)

REPAIR_MARKER = "prod_test_records_cleanup_2026_10_20"
VOID_REASON = "Rekord testowy z ręcznego audytu UI (sprzątanie 20.10.2026)."


@dataclass(frozen=True)
class PinnedPerson:
    candidate_id: int
    name: str
    lastname: str


@dataclass(frozen=True)
class PinnedContract:
    contract_id: int
    candidate_id: int
    status: ContractStatus


@dataclass(frozen=True)
class PinnedDraftOrder:
    order_id: int
    contract_id: int


@dataclass(frozen=True)
class CleanupPlan:
    client_id: int
    client_name: str
    people: tuple[PinnedPerson, ...]
    contracts: tuple[PinnedContract, ...]
    draft_orders: tuple[PinnedDraftOrder, ...]
    # Spotkania z tym znacznikiem w tytule to próby audytu — zostają przy
    # osobie i usunięcie je zanonimizuje; reszta była podpięta przez adres.
    test_event_title_pattern: str


PROD_PLAN = CleanupPlan(
    client_id=77196,
    client_name="NEXUS QA UI 2026-09-26 A-Z",
    people=(
        PinnedPerson(598805, "NEXUSQA", "STANDALONE20260927"),
        PinnedPerson(593527, "NEXUS", "TEST-M365-20260926"),
        PinnedPerson(593528, "NEXUSQA", "UIAZ20260926"),
        PinnedPerson(166739, "E2E", "AutoApply"),
    ),
    contracts=(
        PinnedContract(676, 598805, ContractStatus.ended),
        # Szkice prawdziwych osób na kliencie testowym — osoby zostają.
        PinnedContract(695, 113818, ContractStatus.draft),
        PinnedContract(696, 631943, ContractStatus.draft),
    ),
    draft_orders=(PinnedDraftOrder(786, 695), PinnedDraftOrder(789, 696)),
    test_event_title_pattern="(TEST-M365-20260926|NEXUS QA UI)",
)


def _domain(address: Optional[str]) -> str:
    return (address or "").strip().lower().rpartition("@")[2]


async def _delete_draft_orders(
    db: AsyncSession, plan: CleanupPlan, summary: dict[str, Any]
) -> None:
    from app.services.contract_lifecycle import lock_contract_then_orders
    from app.services.contract_order_sync import (
        detach_order_rate_steps,
        sync_pending_order_contracts,
    )
    from app.services.order_gaps import close_gaps_of_deleted_orders
    from app.services.order_settlements import settlement_blockers

    ids = [pin.order_id for pin in plan.draft_orders]
    if not ids:
        return
    await lock_contract_then_orders(db, order_ids=ids)
    for pin in plan.draft_orders:
        order = await db.scalar(
            select(ClientOrder).where(ClientOrder.id == pin.order_id).with_for_update()
        )
        reason = None
        if order is None:
            reason = "missing"
        elif (
            order.client_id != plan.client_id
            or order.contract_id != pin.contract_id
            or order.status != ClientOrderStatus.draft
            or order.order_group_id is not None
        ):
            reason = "fingerprint_mismatch"
        elif order.file_path:
            reason = "has_file"
        elif await settlement_blockers(db, [order.id]):
            reason = "has_settlements"
        if reason:
            summary["orders_skipped"][str(pin.order_id)] = reason
            continue
        await close_gaps_of_deleted_orders(db, [order.id])
        await detach_order_rate_steps(db, order)
        await db.delete(order)
        summary["draft_orders_deleted"].append(pin.order_id)
    await db.flush()
    await sync_pending_order_contracts(db)


async def _void_contracts(
    db: AsyncSession, plan: CleanupPlan, summary: dict[str, Any]
) -> None:
    from app.services.contract_lifecycle import (
        ContractTransitionError,
        void_contract,
    )

    for pin in sorted(plan.contracts, key=lambda c: c.contract_id):
        contract = await db.scalar(
            select(Contract).where(Contract.id == pin.contract_id).with_for_update()
        )
        if contract is None:
            summary["contracts_skipped"][str(pin.contract_id)] = "missing"
            continue
        if (
            contract.client_id != plan.client_id
            or contract.candidate_id != pin.candidate_id
            or contract.status != pin.status
            or contract.voided_at is not None
        ):
            summary["contracts_skipped"][str(pin.contract_id)] = "fingerprint_mismatch"
            continue
        try:
            async with db.begin_nested():
                await void_contract(db, contract, actor_id=None, reason=VOID_REASON)
        except ContractTransitionError:
            summary["contracts_skipped"][str(pin.contract_id)] = "transition_refused"
            continue
        summary["contracts_voided"].append(pin.contract_id)


async def _release_address_matched_events(
    db: AsyncSession,
    person: Candidate,
    plan: CleanupPlan,
    summary: dict[str, Any],
) -> None:
    """Spotkania podpięte do osoby testowej tylko przez adres pracownika."""

    events = (
        await db.scalars(
            select(CalendarEvent)
            .where(
                CalendarEvent.candidate_id == person.id,
                CalendarEvent.external_source == M365_SOURCE,
                func.coalesce(CalendarEvent.title, "").op("!~*")(
                    plan.test_event_title_pattern
                ),
            )
            .order_by(CalendarEvent.id)
            .with_for_update()
        )
    ).all()
    if not events:
        return
    internal = set(settings.sso_allowed_domains_list)
    if person.email:
        internal.add(_domain(person.email))
    for event in events:
        addresses = sorted(
            {
                (row.get("address") or "").strip().lower()
                for row in (
                    event.attendees if isinstance(event.attendees, list) else []
                )
                if isinstance(row, dict)
            }
            - {""}
        )
        external = [a for a in addresses if _domain(a) not in internal]
        replacement = None
        if external:
            replacement = await db.scalar(
                select(Candidate.id)
                .where(
                    func.lower(func.btrim(Candidate.email)).in_(external),
                    Candidate.id.not_in([p.candidate_id for p in plan.people]),
                )
                .order_by(Candidate.id)
                .limit(1)
            )
        event.candidate_id = replacement
        if replacement is None:
            summary["calendar_unlinked"] += 1
        else:
            summary["calendar_relinked"] += 1
    await db.flush()


async def _erase_people(
    db: AsyncSession, plan: CleanupPlan, summary: dict[str, Any]
) -> list[EraseOutcome]:
    outcomes: list[EraseOutcome] = []
    for pin in plan.people:
        person = await db.get(Candidate, pin.candidate_id)
        if person is None:
            summary["candidates_skipped"][str(pin.candidate_id)] = "missing"
            continue
        if (person.name, person.lastname) != (pin.name, pin.lastname):
            summary["candidates_skipped"][str(pin.candidate_id)] = (
                "fingerprint_mismatch"
            )
            continue
        await _release_address_matched_events(db, person, plan, summary)
        outcome = await candidate_hard_delete.erase_candidate(db, person, actor=None)
        if outcome.teams_to_cancel:
            # Próby audytu są przeszłe; przyszłe spotkanie w Teams z zaproszeniem
            # osoby oznacza, że to nie jest już sam ślad testu — nic nie zapisujemy.
            raise RuntimeError("test person has future Teams meetings")
        outcomes.append(outcome)
        summary["candidates_deleted"].append(pin.candidate_id)
    return outcomes


async def run_prod_test_records_cleanup(
    db: AsyncSession,
    *,
    marker: str = REPAIR_MARKER,
    plan: CleanupPlan = PROD_PLAN,
) -> Optional[tuple[dict[str, Any], list[EraseOutcome]]]:
    """Wykonaj sprzątanie raz; ``None`` = już wykonane. Wołający commituje,
    a potem woła ``candidate_hard_delete.finish_after_commit`` dla wyników."""

    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    if await db.get(AppSetting, marker) is not None:
        return None
    summary: dict[str, Any] = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "client_pinned": False,
        "draft_orders_deleted": [],
        "orders_skipped": {},
        "contracts_voided": [],
        "contracts_skipped": {},
        "calendar_unlinked": 0,
        "calendar_relinked": 0,
        "candidates_deleted": [],
        "candidates_skipped": {},
    }
    client = await db.get(Client, plan.client_id)
    outcomes: list[EraseOutcome] = []
    if client is not None and client.name == plan.client_name:
        summary["client_pinned"] = True
        await _delete_draft_orders(db, plan, summary)
        await _void_contracts(db, plan, summary)
        outcomes = await _erase_people(db, plan, summary)
    db.add(AppSetting(key=marker, value=summary))
    await db.flush()
    logger.info(
        "prod test records cleanup: %s",
        summarize_for_log(summary),
    )
    return summary, outcomes


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already applied"
    if not summary["client_pinned"]:
        return "test client not found by id and name; nothing changed"
    skipped = (
        len(summary["orders_skipped"])
        + len(summary["contracts_skipped"])
        + len(summary["candidates_skipped"])
    )
    return (
        f"draft orders deleted {len(summary['draft_orders_deleted'])}, "
        f"contracts voided {len(summary['contracts_voided'])}, "
        f"calendar unlinked {summary['calendar_unlinked']} / "
        f"relinked {summary['calendar_relinked']}, "
        f"candidates deleted {len(summary['candidates_deleted'])}, "
        f"skipped {skipped}"
    )


__all__ = [
    "PROD_PLAN",
    "REPAIR_MARKER",
    "CleanupPlan",
    "PinnedContract",
    "PinnedDraftOrder",
    "PinnedPerson",
    "run_prod_test_records_cleanup",
    "summarize_for_log",
]
