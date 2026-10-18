"""Opieka · automat „Przypisz wg obłożenia” (decyzja Artura 18.10.2026).

* **Kogo**: kontrakty aktywne i kończące się BEZ opiekuna wpisanego na
  kontrakcie (``care_owner_user_id``) — także te, w których opiekunem jest
  dziś domyślny opiekun klienta albo Delivery Lead z łańcucha
  ``care_access.effective_owners``.
* **Komu**: osoba z puli (``owner_pool``), która widzi opiekę i nie jest
  wykluczona, z najmniejszą liczbą aktywnych podopiecznych (faktyczny opiekun
  z łańcucha; przydzielane kontrakty liczą się dopiero po przydziale). Remis:
  stała kolejność puli — po nazwisku, potem id. Osoba z portfelem Delivery
  Leada dostaje tylko kontrakty swoich klientów.
* **Podgląd przed zapisem**: ``preview`` niczego nie zapisuje; ``apply``
  zapisuje DOKŁADNIE pary z podglądu (kontrakt → opiekun) i odrzuca parę,
  której opiekun wypadł z puli; kontrakt, który w międzyczasie dostał
  opiekuna, jest pomijany (``skipped``). Ślad ``care.owner_set`` z powodem
  ``auto_load``.
* **Nowy kontrakt** (hak ``contract_hooks.contract_started`` i dzienny
  przebieg opieki) dostaje opiekuna tą samą regułą, gdy
  ``auto_new_contracts`` jest włączone.
* **Powiadomienie opiekuna** tylko przy włączonym module ``care`` — przy
  wyłączonym (tryb cienia) link prowadziłby na 404. Typ ``care_contact_due``
  (sekcja Delivery, kategoria kontraktów) — jeden dzwonek na kontrakt przy
  haku, jeden zbiorczy na osobę przy zapisie hurtem.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract import Contract
from app.models.contract_care import CONTRACTS_CARE
from app.models.notification import NotificationType
from app.models.user import User
from app.services.care import access as care_access
from app.services.care import owner_pool
from app.services.care import plan as care_plan
from app.services.hr import audit
from app.services.hr import modules as hr_modules
from app.services.hr.modules import HrModule
from app.services.hr.notify import notify_each

AUTO_REASON = "auto_load"
MAX_AUTO = 2000
NO_OPTION = "nikt z puli nie ma tego klienta w portfelu"
NO_POOL = "pula opiekunów jest pusta — wskaż przełożonego albo zdejmij wykluczenia"
POOL_CHANGED = (
    "Pula opiekunów zmieniła się od podglądu — odśwież podgląd i zapisz jeszcze raz."
)


@dataclass(frozen=True)
class Pick:
    contract: care_access.CareContract
    owner: User


@dataclass(frozen=True)
class AutoPlan:
    pool: list[owner_pool.PoolMember]
    picks: list[Pick]
    unassigned: list[care_access.CareContract]
    load_before: dict[int, int]
    load_after: dict[int, int]
    reason: Optional[str]


async def _scopes(
    db: AsyncSession, users: Sequence[User]
) -> dict[int, Optional[frozenset[int]]]:
    return {user.id: await care_access.allowed_client_ids(user, db) for user in users}


async def plan_for(
    db: AsyncSession,
    targets: Sequence[care_access.CareContract],
    *,
    live: Optional[Sequence[care_access.CareContract]] = None,
) -> AutoPlan:
    """Przydział wg obłożenia dla ``targets`` (bez zapisu)."""

    config = await owner_pool.load_config(db)
    pool = await owner_pool.members(db, config)
    eligible = [m.user for m in pool if m.eligible]
    eligible_ids = {u.id for u in eligible}
    live = list(live) if live is not None else await care_access.live_contracts(db)
    target_ids = {c.id for c in targets}
    owners = await care_access.effective_owners(
        db, [c for c in live if c.id not in target_ids]
    )
    load: Counter[int] = Counter(
        choice.user_id
        for choice in owners.values()
        if choice.user_id is not None and choice.user_id in eligible_ids
    )
    before = {user.id: load[user.id] for user in eligible}
    if not eligible:
        return AutoPlan(pool, [], list(targets), before, dict(before), NO_POOL)
    rank = {user.id: index for index, user in enumerate(eligible)}
    scopes = await _scopes(db, eligible)
    picks: list[Pick] = []
    unassigned: list[care_access.CareContract] = []
    ordered = sorted(
        targets,
        key=lambda c: (c.start_date or date.min, c.client_name.casefold(), c.id),
    )
    for contract in ordered:
        options = [
            user
            for user in eligible
            if scopes[user.id] is None or contract.client_id in scopes[user.id]
        ]
        if not options:
            unassigned.append(contract)
            continue
        owner = min(options, key=lambda u: (load[u.id], rank[u.id]))
        load[owner.id] += 1
        picks.append(Pick(contract, owner))
    after = {user.id: load[user.id] for user in eligible}
    return AutoPlan(pool, picks, unassigned, before, after, None)


async def targets_without_owner(
    db: AsyncSession, *, allowed: Optional[frozenset[int]] = None
) -> tuple[list[care_access.CareContract], list[care_access.CareContract]]:
    """(kontrakty bez opiekuna na kontrakcie, wszystkie żywe kontrakty)."""

    live = await care_access.live_contracts(db)
    targets = [
        c
        for c in live
        if c.explicit_owner_id is None and (allowed is None or c.client_id in allowed)
    ]
    return targets, live


def _person(user: User) -> dict[str, Any]:
    return {"id": user.id, "name": user.name}


async def preview(db: AsyncSession, actor: User) -> dict[str, Any]:
    allowed = await care_access.rhythm_scope(actor, db)
    targets, live = await targets_without_owner(db, allowed=allowed)
    result = await plan_for(db, targets, live=live)
    config = await owner_pool.load_config(db)
    manager_name = (
        (await care_access.user_names(db, [config.manager_user_id])).get(
            config.manager_user_id
        )
        if config.manager_user_id
        else None
    )
    return {
        "pool": pool_payload(result),
        "config": config_payload(config, manager_name),
        "manager_choices": await owner_pool.manager_choices(db),
        "items": [
            {
                "contract_id": pick.contract.id,
                "candidate_name": pick.contract.candidate_name,
                "client_name": pick.contract.client_name,
                "start_date": pick.contract.start_date,
                "owner": _person(pick.owner),
            }
            for pick in result.picks
        ],
        "unassigned": [
            {
                "contract_id": c.id,
                "candidate_name": c.candidate_name,
                "client_name": c.client_name,
                "reason": result.reason or NO_OPTION,
            }
            for c in result.unassigned
        ],
        "counts": {
            "targets": len(targets),
            "assigned": len(result.picks),
            "unassigned": len(result.unassigned),
            "eligible": sum(1 for m in result.pool if m.eligible),
        },
    }


def pool_payload(result: AutoPlan) -> list[dict[str, Any]]:
    return [
        {
            "id": member.user.id,
            "name": member.user.name,
            "excluded": member.excluded,
            "sees_care": member.sees_care,
            "eligible": member.eligible,
            "note": None if member.sees_care else owner_pool.NO_CARE_ACCESS,
            "consultants_now": result.load_before.get(member.user.id),
            "consultants_after": result.load_after.get(member.user.id),
        }
        for member in result.pool
    ]


def config_payload(
    config: owner_pool.PoolConfig, manager_name: Optional[str]
) -> dict[str, Any]:
    return {
        "manager": {"id": config.manager_user_id, "name": manager_name}
        if config.manager_user_id
        else None,
        "manager_from_division": config.manager_from_division,
        "excluded_user_ids": list(config.excluded_user_ids),
        "auto_new_contracts": config.auto_new_contracts,
    }


async def _write(
    db: AsyncSession,
    picks: Sequence[Pick],
    *,
    actor_id: Optional[int],
    previous: dict[int, care_access.OwnerChoice],
    today: date,
) -> None:
    by_owner: dict[int, list[int]] = {}
    for pick in picks:
        by_owner.setdefault(pick.owner.id, []).append(pick.contract.id)
    for owner_id, contract_ids in by_owner.items():
        await db.execute(
            update(CONTRACTS_CARE)
            .where(
                CONTRACTS_CARE.c.id.in_(contract_ids),
                CONTRACTS_CARE.c.care_owner_user_id.is_(None),
            )
            .values(care_owner_user_id=owner_id)
        )
    for pick in picks:
        audit.record(
            db,
            actor_user_id=actor_id,
            subject_user_id=pick.owner.id,
            entity_type="contract",
            entity_id=pick.contract.id,
            action="care.owner_set",
            details={
                "previous": None,
                "previous_effective": previous[pick.contract.id].user_id
                if pick.contract.id in previous
                else None,
                "owner": pick.owner.id,
                "reason": AUTO_REASON,
                "bulk": actor_id is not None,
            },
        )
    await care_plan.ensure_plans(db, [p.contract for p in picks], today=today)


async def _care_enabled(db: AsyncSession) -> bool:
    return bool((await hr_modules.load_modules(db)).get(HrModule.care))


async def apply(
    db: AsyncSession,
    *,
    actor: User,
    pairs: Sequence[tuple[int, int]],
    today: date,
) -> dict[str, Any]:
    """Zapis par z podglądu (bez commita)."""

    wanted = dict(pairs)
    allowed = await care_access.rhythm_scope(actor, db)
    contracts = await care_access.live_contracts(
        db, allowed=allowed, contract_ids=wanted
    )
    eligible = {m.user.id: m.user for m in await owner_pool.members(db) if m.eligible}
    if any(owner_id not in eligible for owner_id in wanted.values()):
        raise HTTPException(status.HTTP_409_CONFLICT, POOL_CHANGED)
    scopes = await _scopes(db, list(eligible.values()))
    picks: list[Pick] = []
    for contract in contracts:
        if contract.explicit_owner_id is not None:
            continue
        owner = eligible[wanted[contract.id]]
        scope = scopes[owner.id]
        if scope is not None and contract.client_id not in scope:
            raise HTTPException(status.HTTP_409_CONFLICT, POOL_CHANGED)
        picks.append(Pick(contract, owner))
    previous = await care_access.effective_owners(db, [p.contract for p in picks])
    if picks:
        await _write(db, picks, actor_id=actor.id, previous=previous, today=today)
    notified = 0
    if picks and await _care_enabled(db):
        counts = Counter(p.owner.id for p in picks)
        for owner_id, count in counts.items():
            notified += await notify_each(
                db,
                [owner_id],
                title="Nowi podopieczni",
                message=f"Przydzielono Ci {count} {_people(count)} do opieki.",
                ntype=NotificationType.care_contact_due,
                link="/care?tab=consultants",
                exclude=[actor.id],
                log_tag="care",
            )
    by_owner = Counter(p.owner.id for p in picks)
    return {
        "changed": len(picks),
        "skipped": len(wanted) - len(picks),
        "notified": notified,
        "by_owner": [
            {**_person(eligible[owner_id]), "count": count}
            for owner_id, count in sorted(
                by_owner.items(), key=lambda kv: (eligible[kv[0]].name or "").casefold()
            )
        ],
    }


def _people(count: int) -> str:
    if count == 1:
        return "konsultanta"
    return "konsultantów"


async def assign_new(
    db: AsyncSession, contract_ids: Sequence[int], *, today: date
) -> int:
    """Nowe kontrakty bez opiekuna → automat (hak startu, dzienny przebieg)."""

    config = await owner_pool.load_config(db)
    if not config.auto_new_contracts or config.manager_user_id is None:
        return 0
    live = await care_access.live_contracts(db)
    wanted = set(contract_ids)
    targets = [c for c in live if c.id in wanted and c.explicit_owner_id is None]
    if not targets:
        return 0
    result = await plan_for(db, targets, live=live)
    if not result.picks:
        return 0
    previous = await care_access.effective_owners(db, targets)
    await _write(db, result.picks, actor_id=None, previous=previous, today=today)
    if await _care_enabled(db):
        from app.services.care.reminders import contract_link  # noqa: PLC0415

        for pick in result.picks:
            await notify_each(
                db,
                [pick.owner.id],
                title="Nowy podopieczny",
                message=f"Jesteś opiekunem: {pick.contract.label}.",
                ntype=NotificationType.care_contact_due,
                related_entity_type="contract",
                related_entity_id=pick.contract.id,
                link=contract_link(pick.contract.id),
                log_tag="care",
            )
    return len(result.picks)


async def on_contract_started(db: AsyncSession, contract: Contract) -> None:
    from app.core.scheduling import business_today  # noqa: PLC0415

    await db.flush()
    await assign_new(db, [contract.id], today=business_today())


#: Dzienny przebieg łapie tylko świeże kontrakty — starsze bez opiekuna
#: przydziela człowiek („Przypisz wg obłożenia” z podglądem).
SWEEP_DAYS = 14


async def sweep(db: AsyncSession, *, today: date) -> int:
    """Dzienny przebieg: kontrakty aktywowane inną ścieżką niż hak startu."""

    targets, _ = await targets_without_owner(db)
    since = today - timedelta(days=SWEEP_DAYS)
    fresh = [
        c.id for c in targets if c.start_date is not None and c.start_date >= since
    ]
    return await assign_new(db, fresh, today=today)
