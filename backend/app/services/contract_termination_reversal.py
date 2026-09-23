"""„Cofnij zakończenie" — kontrakt zakończony przez pomyłkę (ticket 09.2026).

Stan docelowy: wszystko wraca do stanu sprzed zakończenia, tak jakby
zakończenia nie było. Kontrakt odzyskuje status, datę końca i pola
zakończenia; każde zamówienie ruszone przez zakończenie — status i datę końca
przypisania; sprawa „Wymagana decyzja o pozostałej puli MD" znika razem ze
swoimi alertami; importy MD wgrane w czasie zakończenia są przeliczane dla tej
osoby. Zużycie MD, pula i stawki zostają bez zmian — zakończenie ich nie
ruszało (poza pulą, o której decyzja BLOKUJE cofnięcie).

Dwa źródła stanu „przed":

* **migawka** (``contract_termination_snapshots``, od 0357) — zapisana przy
  zakończeniu, dokładna;
* **historia** — zakończenia sprzed 0357. Datę końca przypisania bierzemy
  z dziennika zmian zamówień (``order_change_events``: wpis „stara data →
  data zakończenia"); gdy go brak, z daty końca zamówienia (grupy), na którym
  jest konsultant. Zamówienie okresowe bez śladu w dzienniku jest POMIJANE
  z powodem — zgadnięta data końca wpisałaby do przychodu horyzont, którego
  nikt nie zatwierdził.

Plan liczy się tą samą funkcją dla podglądu (okno potwierdzenia) i dla
wykonania; wykonanie przelicza go pod blokadą, więc podgląd sprzed minuty nie
może zapisać nieaktualnego stanu.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import (
    GROUP_STATUS_ACTIVE,
    GROUP_STATUS_DRAFT,
    GROUP_STATUS_SCHEDULED,
)
from app.models.client_order_offboarding import (
    OFFBOARDING_RESOLUTION_REMOVE,
    OFFBOARDING_RESOLUTION_TRANSFER,
    OFFBOARDING_STATUS_PENDING,
    OFFBOARDING_STATUS_RESOLVED,
    ClientOrderOffboardingCase,
)
from app.models.contract import Contract, ContractStatus, ContractTerminationReason
from app.models.contract_amendment import ContractAmendment, ContractAmendmentType
from app.models.contract_termination_snapshot import (
    SNAPSHOT_SOURCE_HISTORY,
    SNAPSHOT_STATUS_OPEN,
    SNAPSHOT_STATUS_REVERSED,
    ContractTerminationSnapshot,
)
from app.models.dl_alert import (
    ALERT_CONTRACT_ENDING,
    ALERT_MD_CONSULTANT_ENDED,
    ALERT_PERIODIC_ORDER_ENDING,
)
from app.models.order_change_event import FIELD_END_DATE, OrderChangeEvent
from app.services.client_order_lines import (
    consultant_display_name,
    recompute_remaining,
    record_event,
)
from app.services.contract_lifecycle import assert_transition
from app.services.dl_alerts import resolve_entity_alerts
from app.services.multi_consultant_orders import EVENT_MD_OFFBOARDING_RESTORED
from app.services.order_md_exhaustion import (
    closed_by_md_exhaustion,
    sync_md_group_exhaustion,
)
from app.services.shared_md_orders import uses_shared_md_pool

REVERSAL_REASON = "termination_reversed"
REVERSAL_HISTORY_TEXT = "Cofnięto zakończenie (pomyłka)"

_OPEN_GROUP_STATUSES = (GROUP_STATUS_ACTIVE, GROUP_STATUS_SCHEDULED, GROUP_STATUS_DRAFT)
_ENDED_ORDER_STATUSES = (ClientOrderStatus.completed, ClientOrderStatus.cancelled)
_DECISION_LABELS = {
    OFFBOARDING_RESOLUTION_REMOVE: "zamknięcie pozostałej puli MD",
    OFFBOARDING_RESOLUTION_TRANSFER: "przekazanie puli MD innemu konsultantowi",
}
_STATUS_LABELS = {
    "draft": "Szkic",
    "active": "Aktywne",
    "paused": "Wstrzymane",
    "completed": "Zakończone",
    "cancelled": "Anulowane",
}


class ReversalUnavailable(Exception):
    """Kontrakt nie ma zakończenia, które dałoby się cofnąć."""


def _value(raw: Any) -> Any:
    return getattr(raw, "value", raw)


def _parse_date(raw: Any) -> Optional[date]:
    if raw in (None, ""):
        return None
    if isinstance(raw, date):
        return raw
    return date.fromisoformat(str(raw))


def _iso(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value is not None else None


@dataclass
class OrderRestore:
    order_id: int
    order_group_id: Optional[int]
    order_label: str
    kind: str  # "group" | "periodic"
    consultant: str
    status_now: str
    status_target: str
    end_date_now: Optional[date]
    end_date_target: Optional[date]
    end_date_source: str  # "snapshot" | "history" | "order_end"
    removes_decision_case: bool = False

    def as_json(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "order_group_id": self.order_group_id,
            "order_label": self.order_label,
            "kind": self.kind,
            "consultant": self.consultant,
            "status_now": self.status_now,
            "status_target": self.status_target,
            "end_date_now": _iso(self.end_date_now),
            "end_date_target": _iso(self.end_date_target),
            "end_date_source": self.end_date_source,
            "removes_decision_case": self.removes_decision_case,
        }


@dataclass
class ReversalPlan:
    contract: Contract
    source: str  # "snapshot" | "history"
    snapshot: Optional[ContractTerminationSnapshot]
    terminated_on: Optional[date]
    since: Optional[datetime]
    status_target: ContractStatus
    end_date_target: Optional[date]
    terminated_at_target: Optional[date]
    termination_reason_target: Optional[str]
    termination_lessons_target: Optional[str]
    orders: list[OrderRestore] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[dict[str, Any]] = field(default_factory=list)
    pending_case_ids: list[int] = field(default_factory=list)
    md_imports: list[dict[str, Any]] = field(default_factory=list)
    lines: dict[int, ClientOrder] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        contract = self.contract
        return {
            "contract_id": contract.id,
            "source": self.source,
            "terminated_on": _iso(self.terminated_on),
            "contract": {
                "status_now": str(_value(contract.status)),
                "status_target": str(_value(self.status_target)),
                "end_date_now": _iso(contract.end_date),
                "end_date_target": _iso(self.end_date_target),
                "clears_termination": contract.terminated_at is not None
                and self.terminated_at_target is None,
            },
            "orders": [item.as_json() for item in self.orders],
            "skipped": self.skipped,
            "blockers": self.blockers,
            "md_imports": self.md_imports,
            "decision_cases_removed": len(self.pending_case_ids),
        }


# ── Dostępność ──────────────────────────────────────────────────────────────


async def _pending_cases(
    db: AsyncSession, contract_id: int
) -> list[ClientOrderOffboardingCase]:
    return list(
        (
            await db.scalars(
                select(ClientOrderOffboardingCase)
                .where(
                    ClientOrderOffboardingCase.contract_id == contract_id,
                    ClientOrderOffboardingCase.status == OFFBOARDING_STATUS_PENDING,
                )
                .order_by(ClientOrderOffboardingCase.id)
            )
        ).all()
    )


async def reversal_available(db: AsyncSession, contract: Contract) -> bool:
    """Czy kontrakt ma zakończenie, które da się cofnąć (bez liczenia planu).

    Zakończony kontrakt — zawsze. Kontrakt, który wrócił do aktywnych zwykłą
    zmianą statusu, a jego zamówienia zostały w „Zakończonych" (dokładnie
    przypadek ze zgłoszenia) — gdy ma otwartą migawkę albo nierozstrzygniętą
    decyzję o puli MD. Bez limitu czasu od zakończenia.
    """
    status = _value(contract.status)
    if status == ContractStatus.void.value:
        return False
    if status == ContractStatus.ended.value:
        return True
    snapshot = await db.scalar(
        select(ContractTerminationSnapshot.id).where(
            ContractTerminationSnapshot.contract_id == contract.id,
            ContractTerminationSnapshot.status == SNAPSHOT_STATUS_OPEN,
        )
    )
    if snapshot is not None:
        return True
    if contract.terminated_at is None:
        return False
    return bool(await _pending_cases(db, contract.id))


# ── Plan ────────────────────────────────────────────────────────────────────


async def _load_orders(
    db: AsyncSession, order_ids: list[int]
) -> dict[int, ClientOrder]:
    if not order_ids:
        return {}
    rows = await db.scalars(
        select(ClientOrder)
        .options(
            selectinload(ClientOrder.order_group),
            selectinload(ClientOrder.contract).selectinload(Contract.candidate),
        )
        .where(ClientOrder.id.in_(order_ids))
        .order_by(ClientOrder.id)
        .execution_options(populate_existing=True)
    )
    return {order.id: order for order in rows.unique().all()}


def _order_label(order: ClientOrder) -> str:
    group = order.order_group
    if group is not None:
        return group.order_number
    return (order.title or f"Zamówienie #{order.id}").strip()


def _restore_item(
    order: ClientOrder,
    *,
    status_target: str,
    end_date_target: Optional[date],
    end_date_source: str,
) -> OrderRestore:
    return OrderRestore(
        order_id=order.id,
        order_group_id=order.order_group_id,
        order_label=_order_label(order),
        kind="group" if order.order_group_id is not None else "periodic",
        consultant=consultant_display_name(order),
        status_now=str(order.status.value),
        status_target=status_target,
        end_date_now=order.end_date,
        end_date_target=end_date_target,
        end_date_source=end_date_source,
    )


async def _plan_from_snapshot(
    db: AsyncSession, plan: ReversalPlan, snapshot: ContractTerminationSnapshot
) -> None:
    entries = [dict(item) for item in (snapshot.orders or [])]
    orders = await _load_orders(db, [int(item["order_id"]) for item in entries])
    for entry in entries:
        order = orders.get(int(entry["order_id"]))
        if order is None:
            plan.skipped.append(
                {
                    "order_id": int(entry["order_id"]),
                    "order_label": f"Zamówienie #{entry['order_id']}",
                    "reason": "Zamówienie zostało usunięte po zakończeniu.",
                }
            )
            continue
        status_after = entry.get("status_after")
        end_after = _parse_date(entry.get("end_date_after"))
        if str(order.status.value) != status_after or order.end_date != end_after:
            plan.skipped.append(
                {
                    "order_id": order.id,
                    "order_label": _order_label(order),
                    "reason": (
                        "Zamówienie zmieniono po zakończeniu (status albo data "
                        "końca) — zostaje w obecnym stanie."
                    ),
                }
            )
            continue
        plan.lines[order.id] = order
        plan.orders.append(
            _restore_item(
                order,
                status_target=str(entry.get("status_before") or "active"),
                end_date_target=_parse_date(entry.get("end_date_before")),
                end_date_source="snapshot",
            )
        )


async def _history_end_dates(
    db: AsyncSession, order_ids: list[int], terminated_on: date
) -> dict[int, tuple[Optional[date], datetime]]:
    """Ostatni wpis dziennika „stara data → data zakończenia" per zamówienie."""
    if not order_ids:
        return {}
    rows = await db.execute(
        select(
            OrderChangeEvent.order_id,
            OrderChangeEvent.old_date,
            OrderChangeEvent.created_at,
        )
        .where(
            OrderChangeEvent.order_id.in_(order_ids),
            OrderChangeEvent.field == FIELD_END_DATE,
            OrderChangeEvent.new_date == terminated_on,
        )
        .order_by(OrderChangeEvent.id.asc())
    )
    found: dict[int, tuple[Optional[date], datetime]] = {}
    for order_id, old_date, created_at in rows:
        found[int(order_id)] = (old_date, created_at)
    return found


async def _plan_from_history(db: AsyncSession, plan: ReversalPlan) -> None:
    """Zakończenie sprzed 0357: stan „przed" z historii zmian przypisania."""

    contract = plan.contract
    terminated_on = plan.terminated_on
    if terminated_on is None:
        return
    candidate_ids = list(
        (
            await db.scalars(
                select(ClientOrder.id)
                .where(
                    ClientOrder.contract_id == contract.id,
                    ClientOrder.client_id == contract.client_id,
                    ClientOrder.status.in_(_ENDED_ORDER_STATUSES),
                )
                .order_by(ClientOrder.id)
            )
        ).all()
    )
    orders = await _load_orders(db, candidate_ids)
    history = await _history_end_dates(db, candidate_ids, terminated_on)
    pending_orders = set(
        (
            await db.scalars(
                select(ClientOrderOffboardingCase.order_id).where(
                    ClientOrderOffboardingCase.contract_id == contract.id,
                    ClientOrderOffboardingCase.status == OFFBOARDING_STATUS_PENDING,
                )
            )
        ).all()
    )
    earliest: Optional[datetime] = None
    for order_id in candidate_ids:
        order = orders[order_id]
        group = order.order_group
        evidence = history.get(order_id)
        ended_by_termination = (
            evidence is not None
            or order_id in pending_orders
            or (
                order.status == ClientOrderStatus.completed
                and order.end_date == terminated_on
            )
        )
        if not ended_by_termination:
            continue
        if order.status == ClientOrderStatus.cancelled:
            # Zamówienie zaczynające się po dacie zakończenia zostało anulowane;
            # dziennik zmian nie niesie statusu, więc stanu sprzed nie znamy.
            plan.skipped.append(
                {
                    "order_id": order.id,
                    "order_label": _order_label(order),
                    "reason": (
                        "Zamówienie anulowane przy zakończeniu — historia nie "
                        "zapisała jego wcześniejszego statusu. Przywróć je ręcznie."
                    ),
                }
            )
            continue
        if evidence is not None:
            end_target, created_at = evidence
            source = "history"
            if earliest is None or created_at < earliest:
                earliest = created_at
        elif group is not None:
            end_target, source = group.end_date, "order_end"
        else:
            plan.skipped.append(
                {
                    "order_id": order.id,
                    "order_label": _order_label(order),
                    "reason": (
                        "Brak w historii zmian daty końca sprzed zakończenia — "
                        "uzupełnij okres zamówienia ręcznie."
                    ),
                }
            )
            continue
        status_target = (
            ClientOrderStatus.draft.value
            if group is None and order.filled_at is None
            else ClientOrderStatus.active.value
        )
        plan.lines[order.id] = order
        plan.orders.append(
            _restore_item(
                order,
                status_target=status_target,
                end_date_target=end_target,
                end_date_source=source,
            )
        )
    cases_since = await db.scalar(
        select(ClientOrderOffboardingCase.created_at)
        .where(
            ClientOrderOffboardingCase.contract_id == contract.id,
            ClientOrderOffboardingCase.effective_date == terminated_on,
        )
        .order_by(ClientOrderOffboardingCase.created_at.asc())
        .limit(1)
    )
    candidates = [moment for moment in (earliest, cases_since) if moment is not None]
    plan.since = min(candidates) if candidates else None


async def _history_contract_end_date(
    db: AsyncSession, contract: Contract, terminated_on: Optional[date]
) -> Optional[date]:
    """Data końca umowy sprzed zakończenia bez migawki.

    Skrócenie umowy zostawia aneks ``early_termination`` ze starą datą; bez
    niego umowa była bezterminowa (reguła umów B2B) albo kończyła się właśnie
    wtedy — i wtedy nie ma czego cofać w samej dacie.
    """
    if terminated_on is None:
        return None
    amendment = await db.scalar(
        select(ContractAmendment)
        .where(
            ContractAmendment.contract_id == contract.id,
            ContractAmendment.amendment_type == ContractAmendmentType.early_termination,
            ContractAmendment.effective_date == terminated_on,
        )
        .order_by(ContractAmendment.id.desc())
        .limit(1)
    )
    if amendment is not None and isinstance(amendment.old_values, dict):
        return _parse_date(amendment.old_values.get("end_date"))
    return None


async def _add_blockers(db: AsyncSession, plan: ReversalPlan) -> None:
    contract = plan.contract
    if _value(contract.status) == ContractStatus.void.value:
        plan.blockers.append(
            {
                "code": "contract_void",
                "message": "Kontrakt jest unieważniony — nie ma czego przywracać.",
            }
        )
    case_query = select(ClientOrderOffboardingCase).where(
        ClientOrderOffboardingCase.contract_id == contract.id,
        ClientOrderOffboardingCase.status == OFFBOARDING_STATUS_RESOLVED,
        ClientOrderOffboardingCase.resolution.in_(tuple(_DECISION_LABELS)),
    )
    if plan.snapshot is not None:
        case_query = case_query.where(
            ClientOrderOffboardingCase.created_at >= plan.snapshot.created_at
        )
    elif plan.terminated_on is not None:
        case_query = case_query.where(
            ClientOrderOffboardingCase.effective_date == plan.terminated_on
        )
    for case in (
        await db.scalars(case_query.order_by(ClientOrderOffboardingCase.id))
    ).all():
        number = case.order_number_snapshot or f"#{case.order_id}"
        label = _DECISION_LABELS.get(case.resolution or "", case.resolution or "")
        target = (case.resolution_payload or {}).get("target_consultant")
        if target and case.resolution == OFFBOARDING_RESOLUTION_TRANSFER:
            label = f"{label} ({target})"
        when = case.resolved_at.date().isoformat() if case.resolved_at else "—"
        plan.blockers.append(
            {
                "code": "md_pool_decided",
                "order_id": case.order_id,
                "order_label": number,
                "decision": case.resolution,
                "message": (
                    f"Na zamówieniu {number} podjęto już decyzję o pozostałej "
                    f"puli MD: {label} ({when}). Cofnięcie zakończenia "
                    "przywróciłoby pulę, którą rozdysponowano — najpierw trzeba "
                    "odwrócić tę decyzję na zamówieniu."
                ),
            }
        )

    seen_groups: set[int] = set()
    for item in plan.orders:
        order = plan.lines[item.order_id]
        group = order.order_group
        if group is None or group.id in seen_groups:
            continue
        seen_groups.add(group.id)
        if group.status in _OPEN_GROUP_STATUSES or closed_by_md_exhaustion(group):
            continue
        plan.blockers.append(
            {
                "code": "order_group_closed",
                "order_id": order.id,
                "order_label": group.order_number,
                "message": (
                    f"Zamówienie {group.order_number} jest zamknięte "
                    f"({group.closure_reason or group.status}) — najpierw przywróć "
                    "samo zamówienie, potem cofnij zakończenie."
                ),
            }
        )


async def build_reversal_plan(
    db: AsyncSession, contract: Contract, *, lock: bool = False
) -> ReversalPlan:
    if not await reversal_available(db, contract):
        raise ReversalUnavailable(
            "Ten kontrakt nie ma zakończenia, które można cofnąć."
        )
    snapshot_query = select(ContractTerminationSnapshot).where(
        ContractTerminationSnapshot.contract_id == contract.id,
        ContractTerminationSnapshot.status == SNAPSHOT_STATUS_OPEN,
    )
    if lock:
        snapshot_query = snapshot_query.with_for_update()
    snapshot = await db.scalar(snapshot_query)

    pending = await _pending_cases(db, contract.id)
    if snapshot is not None:
        before = dict(snapshot.contract_before or {})
        terminated_on = snapshot.effective_date
        plan = ReversalPlan(
            contract=contract,
            source="snapshot",
            snapshot=snapshot,
            terminated_on=terminated_on,
            since=snapshot.created_at,
            status_target=ContractStatus(before.get("status") or "active"),
            end_date_target=_parse_date(before.get("end_date")),
            terminated_at_target=_parse_date(before.get("terminated_at")),
            termination_reason_target=before.get("termination_reason"),
            termination_lessons_target=before.get("termination_lessons"),
        )
        await _plan_from_snapshot(db, plan, snapshot)
    else:
        terminated_on = contract.terminated_at or (
            pending[0].effective_date if pending else contract.end_date
        )
        status_now = ContractStatus(_value(contract.status))
        plan = ReversalPlan(
            contract=contract,
            source="history",
            snapshot=None,
            terminated_on=terminated_on,
            since=None,
            status_target=(
                ContractStatus.active
                if status_now in (ContractStatus.ended, ContractStatus.ending)
                else status_now
            ),
            end_date_target=await _history_contract_end_date(
                db, contract, terminated_on
            ),
            terminated_at_target=None,
            termination_reason_target=None,
            termination_lessons_target=None,
        )
        await _plan_from_history(db, plan)

    # Umowa „Zakończona" bez daty końca nie istnieje (patrz
    # `_status_after_end_date_change`) — stan przed, który tak wygląda, to
    # zapis zmiany daty na już zakończonej umowie; celem jest wtedy aktywna.
    today = business_today()
    if plan.status_target == ContractStatus.ended and (
        plan.end_date_target is None or plan.end_date_target > today
    ):
        plan.status_target = ContractStatus.active

    restored_ids = {item.order_id for item in plan.orders}
    plan.pending_case_ids = [
        case.id for case in pending if case.order_id in restored_ids
    ]
    for item in plan.orders:
        if any(
            case.order_id == item.order_id and case.id in plan.pending_case_ids
            for case in pending
        ):
            item.removes_decision_case = True

    await _add_blockers(db, plan)

    if plan.since is not None:
        from app.api.md_consumption import reapply_rows_for_restored_line

        for item in plan.orders:
            order = plan.lines[item.order_id]
            if order.order_group_id is None or order.md_total is None:
                continue
            rows = await reapply_rows_for_restored_line(
                db,
                line=order,
                since=plan.since,
                ended_on=item.end_date_now,
                target_end_date=item.end_date_target,
                user_id=None,
                dry_run=True,
            )
            plan.md_imports.extend(_import_json(row, item) for row in rows)
    return plan


def _import_json(row: Any, item: OrderRestore) -> dict[str, Any]:
    return {
        "import_id": row.import_id,
        "row_id": row.row_id,
        "period_month": row.period_month,
        "filename": row.filename,
        "md_reported": str(row.md_reported),
        "order_id": item.order_id,
        "order_label": item.order_label,
        "skipped": row.skipped,
    }


# ── Wykonanie ───────────────────────────────────────────────────────────────


def _describe_restore(item: OrderRestore, contract_id: int) -> str:
    horizon = (
        "bezterminowo"
        if item.end_date_target is None
        else f"do {item.end_date_target.strftime('%d.%m.%Y')}"
    )
    return (
        f"{REVERSAL_HISTORY_TEXT} — {item.consultant} wraca do aktywnej obsady "
        f"({horizon}; status: {_STATUS_LABELS.get(item.status_target, item.status_target)}). "
        f"Kontrakt #{contract_id}. Zużycie MD, pula i stawki bez zmian."
    )


async def execute_reversal(
    db: AsyncSession, contract: Contract, *, actor_id: Optional[int]
) -> ReversalPlan:
    """Cofnij zakończenie. Wołający trzyma blokadę kontraktu i commituje
    (``commit_order_write`` — synchronizacja kontrakt ↔ zamówienia i braki)."""

    plan = await build_reversal_plan(db, contract, lock=True)
    if plan.blockers:
        raise ReversalBlocked(plan)
    now = datetime.now(timezone.utc)

    # 1. Kontrakt.
    current = ContractStatus(_value(contract.status))
    if plan.status_target != current:
        assert_transition(current, plan.status_target)
        contract.status = plan.status_target
    contract.end_date = plan.end_date_target
    contract.terminated_at = plan.terminated_at_target
    contract.termination_reason = (
        None
        if plan.termination_reason_target is None
        else ContractTerminationReason(plan.termination_reason_target)
    )
    contract.termination_lessons = plan.termination_lessons_target

    # 2. Decyzje o puli MD, które zakończenie wystawiło, a nikt ich nie podjął:
    # alerty zamykamy jako nieaktualne (nie „obsłużone" — nikt ich nie
    # obsłużył), a samą sprawę usuwamy. Zostawiona jako „rozstrzygnięta"
    # blokowałaby nową sprawę przy ponownym zakończeniu z tą samą datą
    # (unikalność zamówienie × data), a karta zamówienia dalej pokazywałaby
    # datę zejścia. Ślad zostaje w historii zamówienia (wpis „decyzja MD
    # wymagana" i wpis cofnięcia).
    alerts_closed = 0
    for case_id in plan.pending_case_ids:
        alerts_closed += await resolve_entity_alerts(
            db,
            alert_type=ALERT_MD_CONSULTANT_ENDED,
            entity_key=f"case:{case_id}",
            now=now,
        )
    if plan.pending_case_ids:
        await db.execute(
            delete(ClientOrderOffboardingCase).where(
                ClientOrderOffboardingCase.id.in_(plan.pending_case_ids)
            )
        )
    alerts_closed += await resolve_entity_alerts(
        db,
        alert_type=ALERT_CONTRACT_ENDING,
        entity_key=f"contract:{contract.id}",
        now=now,
    )

    # 3. Zamówienia.
    groups_to_sync: set[int] = set()
    for item in plan.orders:
        order = plan.lines[item.order_id]
        order.status = ClientOrderStatus(item.status_target)
        order.end_date = item.end_date_target
        # Cykl „zamówienie kończy się X" liczony z daty zakończenia — nieaktualny.
        # Po przywróconej dacie skaner założy nowy cykl, jeśli trzeba.
        alerts_closed += await resolve_entity_alerts(
            db,
            alert_type=ALERT_PERIODIC_ORDER_ENDING,
            entity_key=f"order:{order.id}",
            now=now,
        )
        description = _describe_restore(item, contract.id)
        payload = {
            "reason": REVERSAL_REASON,
            "contract_id": contract.id,
            "order_id": order.id,
            "terminated_on": _iso(plan.terminated_on),
            "status_before": item.status_now,
            "status_after": item.status_target,
            "end_date_before": _iso(item.end_date_now),
            "end_date_after": _iso(item.end_date_target),
            "end_date_source": item.end_date_source,
        }
        if order.order_group_id is not None:
            groups_to_sync.add(order.order_group_id)
            record_event(
                db,
                group_id=order.order_group_id,
                order_id=order.id,
                event_type=EVENT_MD_OFFBOARDING_RESTORED,
                description=description,
                payload=payload,
                user_id=actor_id,
            )
        else:
            db.add(
                Activity(
                    entity_type="client_order",
                    entity_id=order.id,
                    action=REVERSAL_REASON,
                    user_id=actor_id,
                    details={**payload, "message": description},
                )
            )
    await db.flush()

    for item in plan.orders:
        order = plan.lines[item.order_id]
        group = order.order_group
        if (
            group is not None
            and order.md_total is not None
            and not uses_shared_md_pool(group)
        ):
            await recompute_remaining(db, order)
    for group_id in sorted(groups_to_sync):
        await sync_md_group_exhaustion(db, group_id)
    await db.flush()

    # 4. Importy MD wgrane w czasie zakończenia.
    reapplied: list[dict[str, Any]] = []
    if plan.since is not None:
        from app.api.md_consumption import reapply_rows_for_restored_line

        for item in plan.orders:
            order = plan.lines[item.order_id]
            if order.order_group_id is None or order.md_total is None:
                continue
            rows = await reapply_rows_for_restored_line(
                db,
                line=order,
                since=plan.since,
                ended_on=item.end_date_now,
                target_end_date=item.end_date_target,
                user_id=actor_id,
                dry_run=False,
            )
            reapplied.extend(_import_json(row, item) for row in rows)
    plan.md_imports = reapplied

    # 5. Ślad: kontrakt (historia), migawka (karta „Zakończenie cofnięte").
    receipt = {
        "source": plan.source,
        "terminated_on": _iso(plan.terminated_on),
        "restored_order_ids": [item.order_id for item in plan.orders],
        "skipped_order_ids": [item["order_id"] for item in plan.skipped],
        "decision_cases_removed": list(plan.pending_case_ids),
        "md_import_rows": [
            {
                "import_id": row["import_id"],
                "row_id": row["row_id"],
                "skipped": bool(row["skipped"]),
            }
            for row in reapplied
        ],
        "alerts_closed": alerts_closed,
    }
    snapshot = plan.snapshot
    if snapshot is None:
        snapshot = ContractTerminationSnapshot(
            contract_id=contract.id,
            effective_date=plan.terminated_on,
            source=SNAPSHOT_SOURCE_HISTORY,
            contract_before={
                "status": plan.status_target.value,
                "end_date": _iso(plan.end_date_target),
                "terminated_at": None,
                "termination_reason": None,
                "termination_lessons": None,
            },
            orders=[
                {
                    "order_id": item.order_id,
                    "order_group_id": item.order_group_id,
                    "status_before": item.status_target,
                    "end_date_before": _iso(item.end_date_target),
                    "group_status_before": None,
                    "status_after": item.status_now,
                    "end_date_after": _iso(item.end_date_now),
                }
                for item in plan.orders
            ],
            created_by_user_id=actor_id,
            status=SNAPSHOT_STATUS_REVERSED,
        )
        db.add(snapshot)
    snapshot.status = SNAPSHOT_STATUS_REVERSED
    snapshot.closed_at = now
    snapshot.reversed_at = now
    snapshot.reversed_by_user_id = actor_id
    snapshot.reversal_payload = receipt

    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract.id,
            action=REVERSAL_REASON,
            user_id=actor_id,
            details={
                "message": REVERSAL_HISTORY_TEXT,
                "from_status": current.value,
                "to_status": contract.status.value,
                **receipt,
                "md_import_rows": len(reapplied),
            },
        )
    )
    await db.flush()
    return plan


class ReversalBlocked(Exception):
    def __init__(self, plan: ReversalPlan) -> None:
        super().__init__("termination reversal blocked")
        self.plan = plan


async def latest_reversal(
    db: AsyncSession, contract_id: int
) -> Optional[ContractTerminationSnapshot]:
    return await db.scalar(
        select(ContractTerminationSnapshot)
        .where(
            ContractTerminationSnapshot.contract_id == contract_id,
            ContractTerminationSnapshot.status == SNAPSHOT_STATUS_REVERSED,
        )
        .order_by(ContractTerminationSnapshot.reversed_at.desc())
        .limit(1)
    )


__all__ = [
    "REVERSAL_HISTORY_TEXT",
    "ReversalBlocked",
    "ReversalPlan",
    "ReversalUnavailable",
    "build_reversal_plan",
    "execute_reversal",
    "latest_reversal",
    "reversal_available",
]
