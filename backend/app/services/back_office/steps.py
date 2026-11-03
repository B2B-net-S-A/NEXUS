"""Kroki wejścia i wyjścia: sprawa z kartami-dziećmi w kolumnach zespołów.

Kroki stoją na sprawach (``contract:<id>:start`` i ``contract:<id>:end``), więc
moduł ``lifecycle`` może zostać wyłączony. Krok zalicza się sam, gdy źródło
mówi, że praca jest zrobiona (kontrakt zakończony, linia zamówienia zamknięta,
pozycje checklisty odhaczone), albo ręcznie. Gdy wszystkie są zrobione, sprawa
zamyka się sama. Ręczne zamknięcie sprawy domyka jej otwarte kroki.

Ławka to krok pierwszy z bezpiecznikiem: 14 dni przed końcem sprawa wyjścia
powstaje także bez decyzji, żeby odebranie dostępów nie czekało na rozmowę.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_case import AdminCase
from app.models.back_office import BoCard, BoCardEvent
from app.models.contract import Contract
from app.services.admin_cases import hooks as case_hooks
from app.services.admin_cases import rules as case_rules
from app.services.hr import audit

#: Bezpiecznik ławki: tyle dni przed końcem kroki ruszają bez decyzji.
SAFETY_VALVE_DAYS = 14
_EXIT_KEY = "contract:%:end"
_ENTRY_KEY = "contract:%:start"


@dataclass(frozen=True)
class Step:
    slug: str
    label: str
    team: str
    lane: str
    #: Początki tekstu pozycji checklisty sprawy, które niesie ten krok.
    checklist: tuple[str, ...] = ()


EXIT_STEPS: tuple[Step, ...] = (
    Step(
        "decision",
        "Ławka: decyzja o przepięciu",
        "care",
        "exit",
        (case_rules.END_DECISION_ITEM,),
    ),
    Step("contract_end", "Rozwiązanie umowy", "contracts", "ending"),
    Step("order_close", "Zamknięcie linii zamówienia", "orders", "extend"),
    Step(
        "equipment",
        "Zwrot sprzętu i dostępy",
        "care",
        "exit",
        (
            case_rules.END_EQUIPMENT_ITEM,
            case_rules.END_ACCESS_PREFIX,
            case_rules.END_ACCESS_GENERIC,
        ),
    ),
    Step(
        "settlement",
        "Ostatnie rozliczenie",
        "finance",
        "changes",
        (case_rules.END_SETTLEMENT_ITEM,),
    ),
)
ENTRY_STEPS: tuple[Step, ...] = (
    Step("contract_signed", "Umowa podpisana", "contracts", "sign"),
    Step("order", "Zamówienie od klienta", "orders", "mail"),
    Step("equipment", "Sprzęt i dostępy", "care", "entry"),
    Step("pack", "Pakiet klienta i mail powitalny", "care", "entry"),
)


def steps_for_case(source_key: Optional[str]) -> tuple[Step, ...]:
    key = source_key or ""
    if key.startswith("contract:") and key.endswith(":end"):
        return EXIT_STEPS
    if key.startswith("contract:") and key.endswith(":start"):
        return ENTRY_STEPS
    return ()


def checklist_items(case: AdminCase, step: Step) -> list[dict[str, Any]]:
    return [
        item
        for item in case.checklist or []
        if any(str(item.get("text", "")).startswith(p) for p in step.checklist)
    ]


def checklist_done(case: AdminCase, step: Step) -> bool:
    items = checklist_items(case, step)
    return bool(items) and all(item.get("done") is True for item in items)


@dataclass(frozen=True)
class ContractFacts:
    status: Optional[str]
    agreement_last_day: Optional[date]
    signed: bool
    active_orders: int
    any_orders: int
    open_decision: bool


async def _facts(db: AsyncSession, contract_ids: list[int]) -> dict[int, ContractFacts]:
    if not contract_ids:
        return {}
    rows = (
        (
            await db.execute(
                text(
                    """
                    SELECT k.id, k.status::text AS status, k.agreement_last_day,
                      EXISTS (SELECT 1 FROM b2b_generated_contracts g
                              WHERE g.contract_id = k.id
                                AND g.signature_status = 'signed_both') AS signed,
                      (SELECT count(*) FROM client_orders o
                       WHERE o.contract_id = k.id AND o.status = 'active') AS active_orders,
                      (SELECT count(*) FROM client_orders o
                       WHERE o.contract_id = k.id) AS any_orders,
                      EXISTS (SELECT 1 FROM redeploy_queue_items r
                              WHERE r.contract_id = k.id
                                AND r.status IN ('open', 'in_progress')) AS open_decision
                    FROM contracts k WHERE k.id = ANY(:ids)
                    """
                ),
                {"ids": contract_ids},
            )
        )
        .mappings()
        .all()
    )
    return {
        row["id"]: ContractFacts(
            status=row["status"],
            agreement_last_day=row["agreement_last_day"],
            signed=row["signed"],
            active_orders=row["active_orders"],
            any_orders=row["any_orders"],
            open_decision=row["open_decision"],
        )
        for row in rows
    }


#: Kiedy krok zalicza się sam; krok z samą checklistą czyta ``checklist_done``.
_AUTO_DONE: dict[str, Callable[[ContractFacts], bool]] = {
    "contract_end": lambda f: f.status == "ended" or f.agreement_last_day is not None,
    "order_close": lambda f: f.any_orders > 0 and f.active_orders == 0,
    "contract_signed": lambda f: f.signed or f.status in ("active", "ending"),
    "order": lambda f: f.active_orders > 0,
}


def step_auto_done(step: Step, case: AdminCase, facts: Optional[ContractFacts]) -> bool:
    if step.checklist and checklist_done(case, step):
        return True
    if step.slug == "decision" and facts is not None and not facts.open_decision:
        return True
    rule = _AUTO_DONE.get(step.slug)
    return rule(facts) if rule is not None and facts is not None else False


CLOSED_WITH_CASE = "closed_with_case"


def step_key(case_id: int, slug: str) -> str:
    return f"step:{case_id}:{slug}"


async def open_due_exit_cases(db: AsyncSession, *, today: date) -> int:
    """Bezpiecznik 14 dni i decyzja „nie przepinamy” zakładają sprawę wyjścia."""

    contracts = (
        await db.scalars(
            select(Contract).where(
                text(
                    """
                    contracts.status IN ('active', 'ending')
                    AND contracts.end_date IS NOT NULL
                    AND contracts.end_date >= :today
                    AND (
                      contracts.end_date <= :valve
                      OR EXISTS (
                        SELECT 1 FROM redeploy_queue_items r
                        WHERE r.contract_id = contracts.id
                          AND r.reason = 'project_end'
                          AND r.status = 'dismissed'
                          AND r.due_on = contracts.end_date
                      )
                    )
                    AND NOT EXISTS (
                      SELECT 1 FROM admin_cases c
                      WHERE c.source_key = 'contract:' || contracts.id || '\\:end'
                        AND c.status <> 'closed'
                    )
                    """
                ).bindparams(
                    today=today, valve=today + timedelta(days=SAFETY_VALVE_DAYS)
                )
            )
        )
    ).all()
    opened = 0
    for contract in contracts:
        # Zamkniętą przez automat hak otwiera, a zamkniętą przez człowieka zostawia.
        case = await case_hooks.open_case_for_contract_end(db, contract)
        if case is not None and not case_rules.is_terminal(case.status):
            opened += 1
    return opened


async def close_extended_exit_cases(db: AsyncSession, *, today: date) -> int:
    """Koniec się oddalił: sprawa z bezpiecznika nie stoi przy osobie, która zostaje.

    ``terminated_at`` odróżnia ją od „Zakończ współpracę”, a decyzja „nie przepinamy”
    na ten sam termin ją utrzymuje. Zamknięcie automatu da się odwrócić przy
    prawdziwym końcu, zamknięcie człowieka już nie.
    """

    contract_ids = (
        await db.scalars(
            select(Contract.id).where(
                text(
                    """
                    contracts.status IN ('active', 'ending')
                    AND contracts.terminated_at IS NULL
                    AND (contracts.end_date IS NULL OR contracts.end_date > :valve)
                    AND EXISTS (
                      SELECT 1 FROM admin_cases c
                      WHERE c.source_key = 'contract:' || contracts.id || '\\:end'
                        AND c.status NOT IN ('done', 'closed')
                    )
                    AND NOT EXISTS (
                      SELECT 1 FROM redeploy_queue_items r
                      WHERE r.contract_id = contracts.id
                        AND r.reason = 'project_end'
                        AND r.status = 'dismissed'
                        AND r.due_on = contracts.end_date
                    )
                    """
                ).bindparams(valve=today + timedelta(days=SAFETY_VALVE_DAYS))
            )
        )
    ).all()
    for contract_id in contract_ids:
        await case_hooks.close_case_for_undone_end(db, contract_id)
    return len(contract_ids)


def _close_card(db: AsyncSession, card: BoCard, *, now: datetime, action: str) -> None:
    if action == CLOSED_WITH_CASE:
        # Nikt tego kroku nie zrobił: wróci, gdy sprawa się otworzy.
        card.meta = {**(card.meta or {}), CLOSED_WITH_CASE: True}
    card.state = "done"
    card.closed_at = now
    card.updated_at = now
    db.add(BoCardEvent(card_id=card.id, action=action, details={}, created_at=now))


async def close_case_when_all_done(
    db: AsyncSession, case: AdminCase, *, now: datetime
) -> bool:
    """Wszystkie kroki zrobione = sprawa zrobiona (bez kliknięcia, ze śladem)."""

    if case_rules.is_terminal(case.status):
        return False
    case.status = "done"
    case.closed_at = now
    case.updated_at = now
    audit.record(
        db,
        actor_user_id=None,
        subject_user_id=case.subject_user_id,
        entity_type="admin_case",
        entity_id=case.id,
        action="case_updated",
        details={"fields": ["status"], "status": "done", "source": "back_office_steps"},
    )
    await db.flush()
    return True


async def sync_steps(
    db: AsyncSession, *, today: date, now: Optional[datetime] = None
) -> dict[str, int]:
    moment = now or datetime.now(timezone.utc)
    opened = await open_due_exit_cases(db, today=today)
    extended = await close_extended_exit_cases(db, today=today)
    parents = (
        await db.execute(
            select(BoCard, AdminCase)
            .join(AdminCase, AdminCase.id == BoCard.case_id)
            .where(
                BoCard.source_kind == "case",
                BoCard.state != "done",
                AdminCase.source_key.like("contract:%"),
            )
        )
    ).all()
    facts = await _facts(
        db, sorted({case.contract_id for _, case in parents if case.contract_id})
    )
    ids = [card.id for card, _ in parents]
    existing: dict[str, BoCard] = {
        child.source_key: child
        for child in (
            await db.scalars(
                select(BoCard).where(BoCard.parent_card_id.in_(ids or [-1]))
            )
        ).all()
    }
    created = closed = reopened = cases_done = 0
    for parent, case in parents:
        definition = steps_for_case(case.source_key)
        if not definition:
            continue
        contract_facts = facts.get(case.contract_id) if case.contract_id else None
        all_done = True
        # Sprawa otwarta po komplecie kroków (mail w wątku) czeka na człowieka:
        # zamyka ją dopiero krok zrobiony teraz.
        finished_now = False
        for order, step in enumerate(definition):
            key = step_key(case.id, step.slug)
            child = existing.get(key)
            done = step_auto_done(step, case, contract_facts)
            if child is None:
                child = BoCard(
                    team=step.team,
                    lane=step.lane,
                    source_kind="step",
                    source_key=key,
                    parent_card_id=parent.id,
                    step_order=order,
                    case_id=case.id,
                    contract_id=case.contract_id,
                    client_id=parent.client_id,
                    title=step.label,
                    person=parent.person,
                    client_label=parent.client_label,
                    due_on=parent.due_on,
                    href=parent.href,
                    state="done" if done else "new",
                    closed_at=moment if done else None,
                    meta={"step": step.slug, "parent_title": parent.title},
                    created_at=moment,
                    updated_at=moment,
                )
                db.add(child)
                created += 1
                finished_now = finished_now or done
            elif done and child.state != "done":
                _close_card(db, child, now=moment, action="step_done_auto")
                closed += 1
                finished_now = True
            elif not done and (child.meta or {}).get(CLOSED_WITH_CASE):
                child.meta = {
                    k: v for k, v in child.meta.items() if k != CLOSED_WITH_CASE
                }
                child.state = "new"
                child.closed_at = None
                child.due_on = parent.due_on
                child.updated_at = moment
                reopened += 1
            elif child.due_on != parent.due_on:
                child.due_on = parent.due_on
                child.updated_at = moment
            all_done = all_done and child.state == "done"
        if (
            all_done
            and finished_now
            and await close_case_when_all_done(db, case, now=moment)
        ):
            cases_done += 1
    # Sprawa zamknięta ręcznie albo cofnięta: jej otwarte kroki znikają z tablicy.
    orphans = (
        await db.scalars(
            select(BoCard)
            .join(AdminCase, AdminCase.id == BoCard.case_id)
            .where(
                BoCard.source_kind == "step",
                BoCard.state != "done",
                AdminCase.status.in_(("done", "closed")),
            )
        )
    ).all()
    for child in orphans:
        _close_card(db, child, now=moment, action=CLOSED_WITH_CASE)
    await db.flush()
    return {
        "exit_cases_opened": opened,
        "exit_cases_extended": extended,
        "created": created,
        "reopened": reopened,
        "closed": closed + len(orphans),
        "cases_done": cases_done,
    }
