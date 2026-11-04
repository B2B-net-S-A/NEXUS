"""Znacznik „Pracuje u nas” po audycie 48 h — zapytania na prawdziwym schemacie.

Punkty 13 i 14 audytu 13.10.2026 oraz dwa drobne: filtr ``ending_soon``
przy dwóch umowach i dzwonek o zatrudnieniu bez ochrony „raz na parę”.
Część czysta reguły: ``test_fix48_ws07_marker_rule.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.core.scheduling import business_today


def _tag() -> str:
    return uuid.uuid4().hex[:8]


async def _client(db, label: str):
    from app.models.client import Client

    client = Client(name=f"Ws07{label}-{_tag()}")
    db.add(client)
    await db.flush()
    return client


async def _candidate(db, label: str):
    from app.models.candidate import Candidate

    tag = _tag()
    candidate = Candidate(
        name=label, lastname=f"Ws07-{tag}", email=f"ws07-{label}-{tag}@example.com"
    )
    db.add(candidate)
    await db.flush()
    return candidate


def _order(client_id: int, contract_id: int, **kwargs):
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import RateUnit

    values = {
        "status": ClientOrderStatus.active,
        "rate_client": Decimal("150"),
        "rate_unit": RateUnit.hourly,
        **kwargs,
    }
    return ClientOrder(
        client_id=client_id,
        contract_id=contract_id,
        title=f"Ws07-{_tag()}",
        **values,
    )


async def _markers(ids: list[int], *, job_client_id: int | None = None) -> dict:
    from app.core.database import AsyncSessionLocal
    from app.services.employment_marker import load_employment_markers

    async with AsyncSessionLocal() as db:
        return await load_employment_markers(
            db, ids, today=business_today(), job_client_id=job_client_id
        )


async def _ending_soon(ids: list[int]) -> set[int]:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.services.employment_marker import ending_soon_exists

    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(Candidate.id).where(
                Candidate.id.in_(ids),
                ending_soon_exists(Candidate.id, today=business_today()),
            )
        )
        return set(rows.scalars().all())


# ── 13: stary etap „Zatrudniony” przy zakończonej umowie ────────────────────


async def _seed_former_consultant() -> dict:
    """Zatrudniony u klienta X dwa lata temu, umowa u X zakończona rok temu;
    druga osoba — umowa u X skończona przed nowym zatrudnieniem u X."""
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract, ContractStatus
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole

    today = business_today()
    tag = _tag()
    async with AsyncSessionLocal() as db:
        former_client = await _client(db, "Former")
        other_client = await _client(db, "Other")
        former = await _candidate(db, "Former")
        rehired = await _candidate(db, "Rehired")
        lead = User(
            email=f"ws07-lead-{tag}@example.com",
            password_hash="test-only",
            name=f"Lead {tag}",
            role=UserRole.delivery_lead,
            roles=[UserRole.delivery_lead.value],
            is_active=True,
        )
        recruiter = User(
            email=f"ws07-rec-{tag}@example.com",
            password_hash="test-only",
            name=f"Rekruter {tag}",
            role=UserRole.recruiter,
            roles=[UserRole.recruiter.value],
            is_active=True,
        )
        db.add_all([lead, recruiter])
        await db.flush()
        old_job = Job(
            title=f"Ws07Old-{tag}", status=JobStatus.closed, client_id=former_client.id
        )
        new_job = Job(
            title=f"Ws07New-{tag}",
            status=JobStatus.published,
            client_id=other_client.id,
        )
        db.add_all([old_job, new_job])
        await db.flush()
        two_years_ago = datetime.now(timezone.utc) - timedelta(days=730)
        db.add_all(
            [
                Contract(
                    candidate_id=former.id,
                    client_id=former_client.id,
                    job_id=old_job.id,
                    start_date=today - timedelta(days=700),
                    end_date=today - timedelta(days=365),
                    terminated_at=today - timedelta(days=365),
                    status=ContractStatus.ended,
                ),
                CandidateStage(
                    candidate_id=former.id,
                    job_id=old_job.id,
                    stage=PipelineStage.hired,
                    moved_at=two_years_ago,
                ),
                Contract(
                    candidate_id=rehired.id,
                    client_id=former_client.id,
                    start_date=today - timedelta(days=1500),
                    end_date=today - timedelta(days=1000),
                    status=ContractStatus.ended,
                ),
                CandidateStage(
                    candidate_id=rehired.id,
                    job_id=old_job.id,
                    stage=PipelineStage.hired,
                    moved_at=datetime.now(timezone.utc) - timedelta(days=3),
                ),
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=lead.id,
                    client_id=former_client.id,
                    is_head=True,
                ),
            ]
        )
        await db.commit()
        return {
            "former": former.id,
            "rehired": rehired.id,
            "former_client": former_client.id,
            "other_client": other_client.id,
            "new_job": new_job.id,
            "lead": lead.id,
            "recruiter": recruiter.id,
        }


async def test_hires_without_a_live_contract_are_not_employment():
    """Audyt 13.10 zamykał stary „Zatrudniony” umową; od 17.10.2026 (decyzja
    Artura) żaden etap bez żywej umowy nie daje znacznika — ani były
    konsultant, ani świeże ponowne zatrudnienie bez umowy. Filtr listy czyta
    to samo (`_at_client_predicate` — tylko umowy)."""
    from sqlalchemy import select

    from app.api.candidates import _at_client_predicate
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    world = await _seed_former_consultant()

    markers = await _markers([world["former"], world["rehired"]])

    assert markers[world["former"]] is None
    assert markers[world["rehired"]] is None
    async with AsyncSessionLocal() as db:
        found = await db.execute(
            select(Candidate.id).where(
                Candidate.id.in_([world["former"], world["rehired"]]),
                _at_client_predicate(),
            )
        )
    assert set(found.scalars().all()) == set()


async def test_former_clients_lead_gets_no_bell_and_the_hire_window_asks_nothing():
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.models.user import User
    from app.services.consultant_elsewhere_notifications import (
        employed_elsewhere_client_ids,
        notify_current_client_leads,
    )

    world = await _seed_former_consultant()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["new_job"])
        row = CandidateStage(
            candidate_id=world["former"],
            job_id=job.id,
            stage=PipelineStage.cv_sent,
            moved_by=world["recruiter"],
            moved_at=datetime.now(timezone.utc),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        sent = await notify_current_client_leads(
            db,
            new_stage=row,
            previous_stage=None,
            job=job,
            candidate=await db.get(Candidate, world["former"]),
            mover=await db.get(User, world["recruiter"]),
        )
        await db.commit()
        asked = await employed_elsewhere_client_ids(
            db, candidate_id=world["former"], job=job
        )

    assert sent == 0
    assert asked == []


# ── 14: data końca wypowiedzianej umowy i koniec łańcucha zamówień ──────────


async def test_terminated_contract_with_an_md_line_shows_its_end_date():
    from app.core.database import AsyncSessionLocal
    from app.models.client_order_group import ClientOrderGroup
    from app.models.contract import Contract, ContractStatus

    today = business_today()
    end = today + timedelta(days=10)
    async with AsyncSessionLocal() as db:
        client = await _client(db, "Md")
        person = await _candidate(db, "Md")
        contract = Contract(
            candidate_id=person.id,
            client_id=client.id,
            start_date=today - timedelta(days=200),
            end_date=end,
            terminated_at=end,
            status=ContractStatus.ending,
        )
        group = ClientOrderGroup(
            client_id=client.id,
            order_number=f"WS07-MD-{_tag()}",
            start_date=today - timedelta(days=200),
            status="active",
            order_type="md",
            is_cost_based=False,
            is_md_budget_based=False,
        )
        db.add_all([contract, group])
        await db.flush()
        db.add(
            _order(
                client.id,
                contract.id,
                order_group_id=group.id,
                start_date=today - timedelta(days=200),
                rate_client=None,
                md_total=Decimal("40"),
                md_remaining=Decimal("12"),
                md_input_mode="md",
                md_input_value=Decimal("40"),
                md_rate_revenue=Decimal("1000"),
            )
        )
        await db.commit()
        person_id = person.id

    marker = (await _markers([person_id]))[person_id]

    assert marker.phase == "ending"
    assert marker.clients[0].order_end_date == end
    assert person_id in await _ending_soon([person_id])


async def test_order_chain_that_ended_gives_its_last_day_unless_one_is_planned():
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrderStatus
    from app.models.contract import Contract, ContractStatus

    today = business_today()
    yesterday = today - timedelta(days=1)
    async with AsyncSessionLocal() as db:
        client = await _client(db, "Chain")
        ended = await _candidate(db, "Ended")
        planned = await _candidate(db, "Planned")
        contracts = {}
        for key, person in (("ended", ended), ("planned", planned)):
            contracts[key] = Contract(
                candidate_id=person.id,
                client_id=client.id,
                start_date=today - timedelta(days=300),
                status=ContractStatus.active,
            )
        db.add_all(contracts.values())
        await db.flush()
        for contract in contracts.values():
            db.add(
                _order(
                    client.id,
                    contract.id,
                    status=ClientOrderStatus.completed,
                    start_date=today - timedelta(days=300),
                    end_date=yesterday,
                )
            )
        # Kontynuacja zaplanowana jako szkic z datami — łańcuch trwa.
        db.add(
            _order(
                client.id,
                contracts["planned"].id,
                status=ClientOrderStatus.draft,
                start_date=today + timedelta(days=5),
                end_date=today + timedelta(days=200),
            )
        )
        await db.commit()
        ids = {"ended": ended.id, "planned": planned.id}

    markers = await _markers(list(ids.values()))

    assert markers[ids["ended"]].phase == "ending"
    assert markers[ids["ended"]].clients[0].order_end_date == yesterday
    assert markers[ids["planned"]].phase == "working"
    assert markers[ids["planned"]].clients[0].order_end_date is None
    assert await _ending_soon(list(ids.values())) == {ids["ended"]}


async def test_closed_md_line_without_its_own_date_ends_with_its_group():
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrderStatus
    from app.models.client_order_group import ClientOrderGroup
    from app.models.contract import Contract, ContractStatus

    today = business_today()
    group_end = today - timedelta(days=3)
    async with AsyncSessionLocal() as db:
        client = await _client(db, "MdClosed")
        person = await _candidate(db, "MdClosed")
        contract = Contract(
            candidate_id=person.id,
            client_id=client.id,
            start_date=today - timedelta(days=200),
            status=ContractStatus.active,
        )
        group = ClientOrderGroup(
            client_id=client.id,
            order_number=f"WS07-MDC-{_tag()}",
            start_date=today - timedelta(days=200),
            end_date=group_end,
            status="completed",
            # CHECK `ck_client_order_groups_closure`: zamknięta grupa ma datę zamknięcia.
            closure_date=group_end,
            order_type="md",
            is_cost_based=False,
            is_md_budget_based=False,
        )
        db.add_all([contract, group])
        await db.flush()
        db.add(
            _order(
                client.id,
                contract.id,
                order_group_id=group.id,
                status=ClientOrderStatus.completed,
                start_date=today - timedelta(days=200),
                end_date=None,
                rate_client=None,
                md_total=Decimal("40"),
                md_remaining=Decimal("0"),
                md_input_mode="md",
                md_input_value=Decimal("40"),
                md_rate_revenue=Decimal("1000"),
            )
        )
        await db.commit()
        person_id = person.id

    marker = (await _markers([person_id]))[person_id]

    assert marker.phase == "ending"
    assert marker.clients[0].order_end_date == group_end
    assert await _ending_soon([person_id]) == {person_id}


# ── drobne: filtr „Kończy u nas w ciągu 60 dni” przy dwóch umowach ──────────


async def test_ending_soon_skips_a_person_whose_second_contract_goes_on():
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract, ContractStatus

    today = business_today()
    async with AsyncSessionLocal() as db:
        first = await _client(db, "First")
        second = await _client(db, "Second")
        two = await _candidate(db, "Two")
        one = await _candidate(db, "One")
        rows = {
            "two_ending": Contract(
                candidate_id=two.id,
                client_id=first.id,
                start_date=today - timedelta(days=100),
                status=ContractStatus.active,
            ),
            "two_open": Contract(
                candidate_id=two.id,
                client_id=second.id,
                start_date=today - timedelta(days=100),
                status=ContractStatus.active,
            ),
            "one_ending": Contract(
                candidate_id=one.id,
                client_id=first.id,
                start_date=today - timedelta(days=100),
                status=ContractStatus.active,
            ),
        }
        db.add_all(rows.values())
        await db.flush()
        start = today - timedelta(days=100)
        db.add_all(
            [
                _order(
                    first.id,
                    rows["two_ending"].id,
                    start_date=start,
                    end_date=today + timedelta(days=10),
                ),
                _order(second.id, rows["two_open"].id, start_date=start, end_date=None),
                _order(
                    first.id,
                    rows["one_ending"].id,
                    start_date=start,
                    end_date=today + timedelta(days=10),
                ),
            ]
        )
        await db.commit()
        ids = {"two": two.id, "one": one.id}

    markers = await _markers(list(ids.values()))

    assert markers[ids["two"]].phase == "working"
    assert markers[ids["one"]].phase == "ending"
    assert await _ending_soon(list(ids.values())) == {ids["one"]}


# ── drobne: dzwonek o zatrudnieniu raz na parę osoba–rekrutacja ─────────────


async def test_hire_bell_rings_once_per_pair():
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.contract import Contract, ContractStatus
    from app.models.job import Job, JobStatus
    from app.models.notification import Notification, NotificationType
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole
    from app.services.consultant_elsewhere_notifications import (
        notify_current_client_leads,
    )

    tag = _tag()
    async with AsyncSessionLocal() as db:
        current = await _client(db, "Current")
        target = await _client(db, "Target")
        person = await _candidate(db, "Hired")
        lead = User(
            email=f"ws07-bell-lead-{tag}@example.com",
            password_hash="test-only",
            name=f"Lead {tag}",
            role=UserRole.delivery_lead,
            roles=[UserRole.delivery_lead.value],
            is_active=True,
        )
        db.add(lead)
        await db.flush()
        job = Job(
            title=f"Ws07Bell-{tag}", status=JobStatus.published, client_id=target.id
        )
        db.add_all(
            [
                job,
                Contract(
                    candidate_id=person.id,
                    client_id=current.id,
                    start_date=business_today() - timedelta(days=90),
                    status=ContractStatus.active,
                ),
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=lead.id, client_id=current.id, is_head=True
                ),
            ]
        )
        await db.commit()
        ids = {"person": person.id, "job": job.id, "lead": lead.id}

    async def move(stage: PipelineStage, minute: int) -> int:
        async with AsyncSessionLocal() as db:
            row = CandidateStage(
                candidate_id=ids["person"],
                job_id=ids["job"],
                stage=stage,
                moved_at=datetime.now(timezone.utc) + timedelta(minutes=minute),
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            sent = await notify_current_client_leads(
                db,
                new_stage=row,
                previous_stage=None,
                job=await db.get(Job, ids["job"]),
                candidate=await db.get(Candidate, ids["person"]),
                mover=None,
                hired_engagement="switch",
            )
            await db.commit()
            return sent

    assert await move(PipelineStage.hired, 0) == 1
    # Cofnięte z „Zatrudniony” i zatrudnione jeszcze raz — ten sam temat.
    assert await move(PipelineStage.client_interview, 1) == 0
    assert await move(PipelineStage.hired, 2) == 0

    async with AsyncSessionLocal() as db:
        titles = (
            await db.execute(
                select(Notification.title).where(
                    Notification.user_id == ids["lead"],
                    Notification.notification_type
                    == NotificationType.consultant_in_other_recruitment,
                )
            )
        ).scalars()
        assert [t.split(":")[0] for t in titles] == ["Zatrudnienie w innej rekrutacji"]
