"""Opieka · „Konsultanci” (etap 3, makieta M1, 17.10.2026).

Jedna lista trwających kontraktów w zakresie czytającego (DL — swój portfel)
z rytmem kontaktu przy każdej osobie: poziom, skąd się wziął (program
pierwszych 90 dni, domyślny, zmiana z powodem i datą „do kiedy”), następna
rozmowa (``plan.next_contact`` — ta sama reguła co karta kontraktu), ostatnia
rozmowa, sygnały z podpowiedzią „podnieść rytm?” i liczba rozmów w tym
i następnym miesiącu wyliczona z rytmów (``plan.conversations_between``).

Zakres: portfel Delivery Leada, head back office — wszyscy klienci
(``access.rhythm_scope``). „Moi” i filtry (rytm, wstrzymani, z sygnałem)
liczy front z jednej odpowiedzi (``is_mine``) — liczniki przy filtrach widać
naraz. Odczyt niczego nie zapisuje; opinia menedżera w sygnałach i zdrowie
relacji (``health``, 22.10.2026) tylko dla ról z D11 — inaczej ``null``.
``redeploy_active`` = aktywny wpis „Do przepięcia” (filtr „Decyzja”).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.care import access as care_access
from app.services.care import cadence, front_office
from app.services.care import health as care_health
from app.services.care import plan as care_plan
from app.services.care.week import client_managers, last_conversation_payload


def _month(bounds: tuple[date, date]) -> dict[str, date]:
    return {"from": bounds[0], "to": bounds[1]}


async def consultants(
    db: AsyncSession, user: User, *, today: date, include_feedback: bool
) -> dict[str, Any]:
    allowed = await care_access.rhythm_scope(user, db)
    contracts = await care_access.live_contracts(db, allowed=allowed)
    owners = await care_access.effective_owners(db, contracts)
    ids = [contract.id for contract in contracts]
    periods = await care_plan.periods_by_contract(db, ids)
    items = await care_plan.open_items(db, ids)
    latest = await care_plan.latest_conversations(db, ids)
    managers = await client_managers(db, contracts)
    upcoming = {
        contract.id: care_plan.next_contact(
            items[contract.id], latest.get(contract.id), today
        )
        for contract in contracts
    }
    overdue = {
        contract_id: (today - contact.due_on).days
        for contract_id, contact in upcoming.items()
        if contact is not None and contact.due_on < today
    }
    signals = await cadence.signals_for(
        db,
        contracts,
        today=today,
        overdue_days=overdue,
        include_feedback=include_feedback,
    )
    names = await care_access.user_names(
        db,
        [
            *(choice.user_id for choice in owners.values()),
            *(p.created_by for rows in periods.values() for p in rows),
        ],
    )
    # Zdrowie relacji (krąg D11 — ta sama flaga co opinia menedżera w sygnałach).
    healths = (
        await care_health.health_for(
            db, contracts, today=today, overdue_days=overdue, periods=periods
        )
        if include_feedback
        else {}
    )
    redeploy = await front_office.active_redeploy(db, ids)
    who = await cadence.changer(db, user)
    this_month, next_month = cadence.this_month(today), cadence.next_month(today)

    rows = []
    for contract in contracts:
        own = periods.get(contract.id, [])
        owner_id = owners[contract.id].user_id
        current = cadence.current_payload(contract, own, today, names)
        contact = upcoming[contract.id]
        rows.append(
            {
                "contract_id": contract.id,
                "candidate_id": contract.candidate_id,
                "candidate_name": contract.candidate_name,
                "client_id": contract.client_id,
                "client_name": contract.client_name,
                "job_title": contract.job_title,
                "contract_type": contract.contract_type,
                "start_date": contract.start_date,
                "end_date": contract.end_date,
                "owner": cadence.person_ref(owner_id, names),
                "is_mine": owner_id == user.id,
                "manager": managers.get(contract.id),
                "cadence": current,
                "next_contact": (
                    {
                        **contact.payload(today),
                        "kind": contact.kind,
                        "overdue_days": overdue.get(contract.id, 0),
                    }
                    if contact is not None
                    else None
                ),
                "last_conversation": last_conversation_payload(latest.get(contract.id)),
                "signals": signals[contract.id],
                "suggested_level": cadence.suggestion(
                    current["level"], signals[contract.id]
                ),
                "conversations": {
                    "this_month": cadence.month_count(contract, own, this_month),
                    "next_month": cadence.month_count(contract, own, next_month),
                },
                "can_change_cadence": who.can_change(contract, owner_id),
                "health": healths.get(contract.id),
                "redeploy_active": bool(redeploy.get(contract.id)),
            }
        )
    rows.sort(
        key=lambda row: (
            row["next_contact"]["due_on"] if row["next_contact"] else date.max,
            (row["candidate_name"] or "").casefold(),
        )
    )
    return {
        "today": today,
        "months": {"this": _month(this_month), "next": _month(next_month)},
        "items": rows,
        "total": len(rows),
        "feedback_visible": include_feedback,
    }
