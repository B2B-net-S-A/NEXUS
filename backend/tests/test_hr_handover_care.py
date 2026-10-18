"""Opieka nad konsultantami przy odejściu opiekuna (etap 3, O11, 17.10.2026).

Szósty rodzaj pracy w przekazaniu: kontrakty, których odchodzący jest
opiekunem, i domyślne opieki klientów przechodzą na przejmującego — domyślnie
na head back office. Delivery Lead przejmie je tylko u klientów ze swojego
portfela; kontrakt zakończony zostaje przy dawnym opiekunie (historia).
Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.hr_lifecycle import LifecycleCase, WorkHandover
from app.models.hr_ops import HrAuditEvent
from app.models.hr_profile import EmployeeProfile
from app.models.user import User, UserRole
from app.services.hr import lifecycle_service as service
from app.services.hr.handover import execute_handover, receiver_issue, work_summary
from tests.test_equipment_api import _contract, _drop_contract
from tests.test_hr_consultant_entry import back_office_head  # noqa: F401
from tests.test_hr_handover_reports import modules_on  # noqa: F401

WARSAW = ZoneInfo("Europe/Warsaw")


def _last_day() -> date:
    day = business_today() + timedelta(days=9)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


async def _people() -> dict[str, User]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:

        def person(label: str, role: str) -> User:
            user = User(
                email=f"care-ho-{label}-{tag}@example.com",
                name=f"Osoba {label} {tag}",
                role=UserRole(role),
                roles=[role],
                is_active=True,
                profile_completed=True,
            )
            db.add(user)
            return user

        actor = person("kadry", "admin")
        boss = person("szef", "head_of_recruitment")
        leaver = person("opiekunka", "talent_community_manager")
        foreign_lead = person("dl", "delivery_lead")
        await db.flush()
        db.add_all(
            [
                EmployeeProfile(user_id=boss.id),
                EmployeeProfile(user_id=leaver.id, manager_user_id=boss.id),
            ]
        )
        await db.commit()
    return {
        "actor": actor,
        "boss": boss,
        "leaver": leaver,
        "foreign_lead": foreign_lead,
    }


async def _cared(leaver_id: int) -> tuple[dict, dict]:
    live = await _contract(start=business_today() - timedelta(days=30), end=None)
    ended = await _contract(start=business_today() - timedelta(days=300), end=None)
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE contracts SET care_owner_user_id = :u WHERE id IN (:a, :b)"),
            {"u": leaver_id, "a": live["id"], "b": ended["id"]},
        )
        await db.execute(
            text("UPDATE contracts SET status = 'ended' WHERE id = :b"),
            {"b": ended["id"]},
        )
        await db.execute(
            text("UPDATE clients SET default_care_owner_user_id = :u WHERE id = :c"),
            {"u": leaver_id, "c": live["client_id"]},
        )
        await db.commit()
    return live, ended


@pytest.mark.asyncio
async def test_care_goes_to_the_back_office_head_by_default(
    modules_on,  # noqa: F811
    back_office_head,  # noqa: F811
) -> None:
    people = await _people()
    live, ended = await _cared(people["leaver"].id)
    last_day = _last_day()
    try:
        async with AsyncSessionLocal() as db:
            counts = await work_summary(
                db, people["leaver"].id, last_working_day=last_day
            )
            assert counts["care"] == 2  # kontrakt w toku + domyślna opieka klienta
            actor = await db.get(User, people["actor"].id)
            case = await service.create_offboarding(
                db,
                actor=actor,
                user_id=people["leaver"].id,
                last_working_day=last_day,
                exit_initiator=None,
                exit_reason=None,
                exit_note=None,
                manager_user_id=None,
                manager_given=False,
                template_id=None,
            )
            await db.commit()
            rows = {
                row.work_kind: row
                for row in await db.scalars(
                    select(WorkHandover).where(WorkHandover.case_id == case.id)
                )
            }
            # Pozostałe rodzaje idą do przełożonego, opieka — do head back office.
            assert rows["care"].receiver_user_id == back_office_head.id
            assert rows["care"].item_count == 2
            assert rows["reports"].receiver_user_id == people["boss"].id
            # DL bez tego klienta w portfelu nie przejmie opieki.
            foreign = await db.get(User, people["foreign_lead"].id)
            assert (
                await receiver_issue(db, foreign, "care", case)
                == "receiver_out_of_scope"
            )
            case = await db.get(LifecycleCase, case.id)
            moment = datetime.combine(
                last_day, datetime.min.time(), tzinfo=WARSAW
            ).replace(hour=18, minute=5)
            await execute_handover(db, case, now=moment)
            await db.commit()
            care = await db.scalar(
                select(WorkHandover).where(
                    WorkHandover.case_id == case.id, WorkHandover.work_kind == "care"
                )
            )
            owners = dict(
                (
                    await db.execute(
                        text(
                            "SELECT id, care_owner_user_id FROM contracts WHERE id IN (:a, :b)"
                        ),
                        {"a": live["id"], "b": ended["id"]},
                    )
                ).all()
            )
            default = await db.scalar(
                text("SELECT default_care_owner_user_id FROM clients WHERE id = :c"),
                {"c": live["client_id"]},
            )
            trail = await db.scalar(
                select(HrAuditEvent).where(
                    HrAuditEvent.entity_type == "contract",
                    HrAuditEvent.entity_id == str(live["id"]),
                    HrAuditEvent.action == "care.owner_set",
                )
            )
        assert care.status == "done"
        assert care.result == {"contracts": 1, "clients": 1, "items": 2}
        assert owners[live["id"]] == back_office_head.id
        assert owners[ended["id"]] == people["leaver"].id  # historia zostaje
        assert default == back_office_head.id
        assert trail.details["previous"] == people["leaver"].id
        assert trail.details["reason"] == "handover"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    "UPDATE clients SET default_care_owner_user_id = NULL WHERE id IN (:a, :b)"
                ),
                {"a": live["client_id"], "b": ended["client_id"]},
            )
            await db.execute(
                text(
                    "UPDATE contracts SET care_owner_user_id = NULL WHERE id IN (:a, :b)"
                ),
                {"a": live["id"], "b": ended["id"]},
            )
            await db.commit()
        await _drop_contract(live)
        await _drop_contract(ended)
