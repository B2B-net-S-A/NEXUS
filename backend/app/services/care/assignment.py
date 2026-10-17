"""Opieka · „Przydział” (etap 3, O10, makieta M3, 17.10.2026).

* **Obciążenie** opiekunów liczone z rytmów, nie samą liczbą osób: rozmowy
  w następnym miesiącu (``plan.conversations_between`` — kamienie i rytm)
  i podział osób po poziomach rytmu. Opiekun = opiekun kontraktu z łańcucha
  ``access.effective_owners`` (kontrakt → domyślny opiekun klienta → DL).
* **Próg** (``app_settings['care_load_threshold']``, rozmowy w miesiącu) to
  ostrzeżenie, nie blokada; ustawia go head back office albo admin w tym
  samym ekranie. Brak wiersza = bez progu.
* **Zmiana wielu kontraktów naraz** — head back office
  (``app_settings['hr_divisions']``) i admin, z powodem z listy. Każdy
  zmieniony kontrakt dostaje ślad ``care.owner_set`` z powodem, poprzednim
  opiekunem wpisanym na kontrakcie i poprzednim faktycznym opiekunem; oś
  konsultanta go pokazuje. DL zmienia opiekuna pojedynczo u swoich klientów
  (zakładka „Opieka” kontraktu), jak dotąd.
* **„Bez opiekuna”** = nikt w łańcuchu (ani kontrakt, ani domyślny opiekun
  klienta, ani DL). Podpowiedź przy wierszu mówi, skąd jest opiekun albo
  czego brakuje (np. „klient bez domyślnego opiekuna”).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any, Literal, Optional, get_args

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.contract_care import CONTRACTS_CARE
from app.models.user import User, UserRole
from app.services.care import access as care_access
from app.services.care import cadence
from app.services.care import plan as care_plan
from app.services.care.cadence_rules import level_on
from app.services.hr import audit

OwnerReason = Literal[
    "new_consultants",
    "balance_load",
    "owner_leaving",
    "client_change",
    "person_request",
    "other",
]
OWNER_REASONS: tuple[str, ...] = get_args(OwnerReason)
OWNER_REASON_LABELS: dict[str, str] = {
    "new_consultants": "nowi konsultanci klienta",
    "balance_load": "wyrównanie obciążenia",
    "owner_leaving": "odejście albo nieobecność opiekuna",
    "client_change": "zmiana u klienta",
    "person_request": "prośba konsultanta",
    "other": "inny powód",
}
LOAD_THRESHOLD_SETTING = "care_load_threshold"
THRESHOLD_MAX = 1000
MAX_BULK = 500
#: „Kończący zamówienie” — ten sam horyzont co sygnał przy konsultancie.
ENDING_DAYS = cadence.ORDER_END_SIGNAL_DAYS
TOP_CLIENTS = 3

STALE_SELECTION = (
    "Część wybranych kontraktów już się zakończyła albo nie istnieje — odśwież listę."
)
OWNER_INVALID = (
    "Opiekunem może być aktywny Delivery Lead, Talent Community Manager albo "
    "administrator."
)


async def load_threshold(db: AsyncSession) -> Optional[int]:
    raw = await db.scalar(
        select(AppSetting.value).where(AppSetting.key == LOAD_THRESHOLD_SETTING)
    )
    value = raw.get("monthly_conversations") if isinstance(raw, dict) else None
    return value if isinstance(value, int) and 0 < value <= THRESHOLD_MAX else None


async def save_threshold(
    db: AsyncSession, *, value: Optional[int], actor: User
) -> Optional[int]:
    previous = await load_threshold(db)
    payload = {"monthly_conversations": value}
    await db.execute(
        pg_insert(AppSetting)
        .values(key=LOAD_THRESHOLD_SETTING, value=payload, updated_by=actor.id)
        .on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": payload, "updated_by": actor.id},
        )
    )
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="app_setting",
        entity_id=LOAD_THRESHOLD_SETTING,
        action="care.load_threshold_set",
        details={"previous": previous, "value": value},
    )
    return value


def _hint(
    choice: care_access.OwnerChoice,
    contract: care_access.CareContract,
    default_active: bool,
) -> str:
    if choice.source is not None:
        return choice.source  # contract | client | delivery_lead
    if contract.client_default_owner_id is not None and not default_active:
        return "default_inactive"
    return "no_default"


async def overview(db: AsyncSession, user: User, *, today: date) -> dict[str, Any]:
    allowed = await care_access.allowed_client_ids(user, db)
    contracts = await care_access.live_contracts(db, allowed=allowed)
    owners = await care_access.effective_owners(db, contracts)
    periods = await care_plan.periods_by_contract(db, [c.id for c in contracts])
    month = cadence.next_month(today)
    candidates = await care_access.owner_candidates(db)
    default_ids = {c.client_default_owner_id for c in contracts} - {None}
    active_defaults = (
        set(
            await db.scalars(
                select(User.id).where(
                    User.id.in_(sorted(default_ids)), User.is_active.is_(True)
                )
            )
        )
        if default_ids
        else set()
    )
    names = await care_access.user_names(
        db,
        [*(o.user_id for o in owners.values()), *default_ids],
    )

    load: dict[int, dict[str, Any]] = {}
    clients_of: dict[int, Counter[str]] = defaultdict(Counter)
    rows = []
    for contract in contracts:
        own = periods.get(contract.id, [])
        level = (
            level_on(contract.start_date, own, today).level
            if contract.start_date is not None
            else None
        )
        talks = cadence.month_count(contract, own, month)
        choice = owners[contract.id]
        if choice.user_id is not None:
            card = load.setdefault(
                choice.user_id,
                {"consultants": 0, "conversations": 0, "by_level": Counter()},
            )
            card["consultants"] += 1
            card["conversations"] += talks
            if level is not None:
                card["by_level"][level] += 1
            clients_of[choice.user_id][contract.client_name] += 1
        end = contract.end_date
        rows.append(
            {
                "contract_id": contract.id,
                "candidate_id": contract.candidate_id,
                "candidate_name": contract.candidate_name,
                "job_title": contract.job_title,
                "contract_type": contract.contract_type,
                "client_id": contract.client_id,
                "client_name": contract.client_name,
                "start_date": contract.start_date,
                "end_date": end,
                "owner": cadence.person_ref(choice.user_id, names),
                "owner_source": choice.source,
                "explicit_owner_id": contract.explicit_owner_id,
                "client_default_owner": cadence.person_ref(
                    contract.client_default_owner_id, names
                ),
                "hint": _hint(
                    choice,
                    contract,
                    contract.client_default_owner_id in active_defaults,
                ),
                "ending_soon": end is not None
                and today <= end < today + timedelta(days=ENDING_DAYS),
                "cadence_level": level,
                "conversations_next_month": talks,
            }
        )
    rows.sort(
        key=lambda row: (
            row["owner"] is not None,
            row["start_date"] or date.max,
            (row["candidate_name"] or "").casefold(),
        )
    )

    threshold = await load_threshold(db)
    by_id = {u.id: u for u in candidates}
    # Opiekunowie z konsultantami i TCM bez nikogo (do kogo można przypisać).
    owner_ids = set(load) | {
        u.id for u in candidates if u.has_role(UserRole.talent_community_manager)
    }
    owner_names = await care_access.user_names(db, owner_ids)
    cards = []
    for owner_id in owner_ids:
        card = load.get(
            owner_id, {"consultants": 0, "conversations": 0, "by_level": {}}
        )
        account = by_id.get(owner_id)
        cards.append(
            {
                "id": owner_id,
                "name": owner_names.get(owner_id, ""),
                "is_delivery_lead": bool(
                    account and account.has_role(UserRole.delivery_lead)
                ),
                "consultants": card["consultants"],
                "conversations": card["conversations"],
                "by_level": dict(card["by_level"]),
                "clients": [
                    name for name, _ in clients_of[owner_id].most_common(TOP_CLIENTS)
                ],
                "over_threshold": threshold is not None
                and card["conversations"] > threshold,
            }
        )
    cards.sort(key=lambda card: (-card["consultants"], card["name"].casefold()))

    clients: dict[int, dict[str, Any]] = {}
    for contract in contracts:
        entry = clients.setdefault(
            contract.client_id,
            {
                "id": contract.client_id,
                "name": contract.client_name,
                "default_owner": cadence.person_ref(
                    contract.client_default_owner_id, names
                ),
                "default_owner_active": contract.client_default_owner_id
                in active_defaults,
                "consultants": 0,
            },
        )
        entry["consultants"] += 1

    can_assign = user.has_role(UserRole.admin) or await cadence.is_back_office_head(
        db, user
    )
    return {
        "today": today,
        "month": {"from": month[0], "to": month[1]},
        "counts": {
            "active": len(rows),
            "without_owner": sum(1 for row in rows if row["owner"] is None),
            "owners": sum(1 for card in cards if card["consultants"]),
            "conversations": sum(row["conversations_next_month"] for row in rows),
            "ending": sum(1 for row in rows if row["ending_soon"]),
        },
        "threshold": {"monthly_conversations": threshold},
        "owners": cards,
        "items": rows,
        "clients": sorted(clients.values(), key=lambda c: c["name"].casefold()),
        "owner_choices": [{"id": u.id, "name": u.name} for u in candidates],
        "can_assign": can_assign,
        "can_edit_threshold": can_assign,
        "can_edit_defaults": care_access.is_care_worker(user),
    }


async def assign(
    db: AsyncSession,
    *,
    actor: User,
    contract_ids: list[int],
    owner_id: int,
    reason: str,
    today: date,
) -> dict[str, Any]:
    """Jeden opiekun dla wielu kontraktów (bez commita)."""

    ids = sorted(set(contract_ids))
    allowed = await care_access.allowed_client_ids(actor, db)
    contracts = await care_access.live_contracts(db, allowed=allowed, contract_ids=ids)
    if len(contracts) != len(ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, STALE_SELECTION)
    owner = await db.get(User, owner_id)
    if owner is None or not owner.is_active or not care_access.is_care_worker(owner):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, OWNER_INVALID)
    scope = await care_access.allowed_client_ids(owner, db)
    if scope is not None:
        outside = sorted(
            {c.client_name for c in contracts if c.client_id not in scope},
            key=str.casefold,
        )
        if outside:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{owner.name} nie ma w portfelu klientów: {', '.join(outside)}.",
            )
    previous = await care_access.effective_owners(db, contracts)
    changed = [c for c in contracts if c.explicit_owner_id != owner.id]
    if changed:
        await db.execute(
            update(CONTRACTS_CARE)
            .where(CONTRACTS_CARE.c.id.in_([c.id for c in changed]))
            .values(care_owner_user_id=owner.id)
        )
        for contract in changed:
            audit.record(
                db,
                actor_user_id=actor.id,
                subject_user_id=owner.id,
                entity_type="contract",
                entity_id=contract.id,
                action="care.owner_set",
                details={
                    "previous": contract.explicit_owner_id,
                    "previous_effective": previous[contract.id].user_id,
                    "owner": owner.id,
                    "reason": reason,
                    "bulk": True,
                },
            )
        # Nowy opiekun widzi plan od razu, nie po nocnym przebiegu.
        await care_plan.ensure_plans(db, changed, today=today)
    return {
        "changed": len(changed),
        "unchanged": len(contracts) - len(changed),
        "owner": {"id": owner.id, "name": owner.name},
    }
