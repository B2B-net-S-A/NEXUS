"""Przetargi z BZP i TED na bazie: bramka zakłada szanse (wariant B), odsiane, zamykanie
po terminie, zmiany ogłoszeń (TED i BZP), stan biegu i trasy ``/api/sales/tenders``.

Numery ogłoszeń i nazwy firm niosą losowy znacznik — baza testowa jest wspólna dla
przebiegu. → docs/claude/sprzedaz/przetargi-z-rejestrow.md
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import DEFAULT_TZ, business_date, business_today
from app.models.app_setting import AppSetting
from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesOpportunity,
    SalesOpportunityEvent,
    SalesPipeline,
    SalesPipelineStage,
    SalesTenderNotice,
)
from app.services.sales.tenders import flow, rules, sources
from app.services.sales.tenders.rules import Notice, TenderRules
from tests.test_sales_companies_api import _headers, _user

URL = "/api/sales/tenders"
STAGES = (
    ("tender-identified", "Identyfikacja", 0, 10, "open"),
    ("tender-analysis", "Analiza SIWZ", 1, 20, "open"),
    ("tender-won", "Wygrane", 5, 100, "won"),
    ("tender-lost", "Przegrane", 6, 0, "lost"),
)


def _marker() -> str:
    return uuid.uuid4().hex[:8]


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
async def _clean_settings():
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(AppSetting).where(
                AppSetting.key.in_((flow.STATE_KEY, rules.RULES_KEY))
            )
        )
        await db.commit()
    yield


async def _stages() -> dict[str, int]:
    """Lejek Przetargi z Atlasa (na produkcji id 9) — w bazie testowej zakładamy go raz."""

    async with AsyncSessionLocal() as db:
        pipeline = (
            await db.execute(
                select(SalesPipeline).where(
                    SalesPipeline.key == flow.TENDER_PIPELINE_KEY
                )
            )
        ).scalar_one_or_none()
        if pipeline is None:
            pipeline = SalesPipeline(
                key=flow.TENDER_PIPELINE_KEY, name="Przetargi", position=9
            )
            db.add(pipeline)
            await db.flush()
            for key, name, position, probability, outcome in STAGES:
                db.add(
                    SalesPipelineStage(
                        pipeline_id=pipeline.id,
                        key=key,
                        name=name,
                        position=position,
                        probability=probability,
                        outcome=outcome,
                    )
                )
            await db.commit()
        rows = (
            await db.execute(
                select(SalesPipelineStage.key, SalesPipelineStage.id).where(
                    SalesPipelineStage.pipeline_id == pipeline.id
                )
            )
        ).all()
    return {key: stage_id for key, stage_id in rows}


def _notice(**fields: Any) -> Notice:
    marker = _marker()
    base: dict[str, Any] = {
        "source": "bzp",
        "number": f"2026/BZP T{marker}",
        "title": f"Usługi programistów w modelu body leasing {marker}",
        "buyer_name": f"Ministerstwo Przetargów {marker}",
        "published_at": _now() - timedelta(hours=3),
        "buyer_nip": None,
        "buyer_city": "Warszawa",
        "cpv_codes": ("72200000",),
        "cpv_label": "72200000-7 (Usługi programowania)",
        "order_type": "services",
        "url": f"https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/{marker}",
        "deadline_date": business_today() + timedelta(days=10),
    }
    base.update(fields)
    return Notice(**base)


async def _process(*notices: Notice, owner: Optional[int] = None) -> flow.RunCounts:
    await _stages()
    counts = flow.RunCounts()
    async with AsyncSessionLocal() as db:
        await flow.process(
            db,
            list(notices),
            TenderRules(owner_user_id=owner),
            now=_now(),
            today=business_today(),
            counts=counts,
        )
        await db.commit()
    return counts


async def _row(notice: Notice) -> SalesTenderNotice:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(SalesTenderNotice).where(
                    SalesTenderNotice.source == notice.source,
                    SalesTenderNotice.number == notice.number,
                )
            )
        ).scalar_one()


async def _opportunities(notice: Notice) -> list[SalesOpportunity]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(SalesOpportunity).where(
                        SalesOpportunity.external_ref
                        == flow.external_ref(notice.source, notice.number)
                    )
                )
            ).scalars()
        )


# ── Bramka zakłada szansę (wariant B) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_gate_creates_an_opportunity_in_identification() -> None:
    owner = await _user("sales_edit")
    notice = _notice(buyer_nip="5261662005")
    counts = await _process(notice, owner=owner.id)
    assert (counts.it, counts.created, counts.rejected) == (1, 1, 0)

    stages = await _stages()
    [opportunity] = await _opportunities(notice)
    assert opportunity.stage_id == stages["tender-identified"]
    assert opportunity.status == "open"
    assert opportunity.owner_user_id == owner.id
    assert opportunity.created_by_user_id is None
    assert opportunity.expected_close_date == notice.deadline_date
    assert opportunity.source == "tender"
    assert opportunity.title == notice.title
    assert opportunity.custom_fields["tender"]["url"] == notice.url

    row = await _row(notice)
    assert (row.status, row.opportunity_id) == ("created", opportunity.id)
    assert row.match_detail == "fraza „body leasing”"
    async with AsyncSessionLocal() as db:
        company = await db.get(SalesCompany, opportunity.company_id)
        assert (company.nip, company.source) == ("5261662005", "tender")
        events = list(
            (
                await db.execute(
                    select(SalesOpportunityEvent).where(
                        SalesOpportunityEvent.opportunity_id == opportunity.id
                    )
                )
            ).scalars()
        )
        assert [(e.kind, e.field) for e in events] == [("created", "stage_id")]
        note = (
            await db.execute(
                select(SalesActivity).where(
                    SalesActivity.opportunity_id == opportunity.id
                )
            )
        ).scalar_one()
    assert note.kind == "note"
    assert notice.number in note.body and notice.url in note.body
    assert "Termin składania ofert" in note.body


@pytest.mark.asyncio
async def test_same_notice_twice_gives_one_opportunity() -> None:
    notice = _notice()
    await _process(notice)
    counts = await _process(notice)
    assert (counts.created, counts.skipped) == (0, 1)
    assert len(await _opportunities(notice)) == 1


@pytest.mark.asyncio
async def test_rejected_notice_is_kept_with_its_rule_and_makes_nothing() -> None:
    notice = _notice(buyer_name=f"Gmina Przetargowo {_marker()}")
    counts = await _process(notice)
    assert (counts.created, counts.rejected) == (0, 1)
    row = await _row(notice)
    assert (row.status, row.rule, row.rule_detail) == ("rejected", "buyer", "gmina")
    assert row.opportunity_id is None
    assert await _opportunities(notice) == []


@pytest.mark.asyncio
async def test_notice_outside_it_is_not_stored() -> None:
    notice = _notice(title="Remont dachu", cpv_codes=("45261000",))
    counts = await _process(notice)
    assert counts.it == 0
    async with AsyncSessionLocal() as db:
        found = await db.scalar(
            select(SalesTenderNotice.id).where(
                SalesTenderNotice.number == notice.number
            )
        )
    assert found is None


@pytest.mark.asyncio
async def test_buyer_card_is_found_by_nip_then_by_name() -> None:
    marker = _marker()
    nip = f"99{uuid.uuid4().int % 10**8:08d}"
    async with AsyncSessionLocal() as db:
        by_nip = SalesCompany(
            name=f"Karta po NIP {marker}",
            normalized_name=f"karta po nip {marker}",
            nip=f"{nip[:3]}-{nip[3:6]}-{nip[6:8]}-{nip[8:]}",
        )
        by_name = SalesCompany(
            name=f"Centrum Informatyki {marker} S.A.",
            normalized_name=f"centrum informatyki {marker}",
        )
        db.add_all([by_nip, by_name])
        await db.commit()
    first = _notice(buyer_nip=nip, buyer_name=f"Inna nazwa {marker}")
    second = _notice(source="ted", buyer_name=f"CENTRUM INFORMATYKI {marker}")
    await _process(first, second)
    [opp_nip] = await _opportunities(first)
    [opp_name] = await _opportunities(second)
    assert opp_nip.company_id == by_nip.id
    assert opp_name.company_id == by_name.id


@pytest.mark.asyncio
async def test_owner_without_sales_edit_is_not_given_opportunities() -> None:
    recruiter = await _user()
    notice = _notice()
    await _process(notice, owner=recruiter.id)
    [opportunity] = await _opportunities(notice)
    assert opportunity.owner_user_id is None


# ── Zmiana postępowania (TED: nowa publikacja, ten sam identyfikator) ─────────


def _change_pair(**fields: Any) -> tuple[Notice, Notice]:
    procedure = str(uuid.uuid4())
    first = _notice(
        source="ted",
        number=f"{uuid.uuid4().int % 10**6}-2026",
        procedure_id=procedure,
        published_at=_now() - timedelta(days=6),
        deadline_date=business_today() + timedelta(days=3),
        **fields,
    )
    second = replace(
        first,
        number=f"{uuid.uuid4().int % 10**6}-2027",
        published_at=_now() - timedelta(days=1),
        deadline_date=business_today() + timedelta(days=8),
    )
    return first, second


@pytest.mark.asyncio
async def test_change_notice_moves_the_deadline_of_the_one_opportunity() -> None:
    first, second = _change_pair()
    counts = await _process(second, first)
    assert (counts.created, counts.updated) == (1, 1)
    [opportunity] = await _opportunities(first)
    assert await _opportunities(second) == []
    assert opportunity.expected_close_date == second.deadline_date
    assert opportunity.custom_fields["tender"]["number"] == second.number
    row = await _row(second)
    assert (row.status, row.opportunity_id) == ("created", opportunity.id)
    async with AsyncSessionLocal() as db:
        notes = list(
            (
                await db.execute(
                    select(SalesActivity.subject).where(
                        SalesActivity.opportunity_id == opportunity.id
                    )
                )
            ).scalars()
        )
        fields = {
            e.field
            for e in (
                await db.execute(
                    select(SalesOpportunityEvent).where(
                        SalesOpportunityEvent.opportunity_id == opportunity.id
                    )
                )
            ).scalars()
        }
    assert any(subject.startswith("Zmiana przetargu TED") for subject in notes)
    assert "expected_close_date" in fields

    again = await _process(first)
    assert (again.created, again.updated, again.skipped) == (0, 0, 1)
    [same] = await _opportunities(first)
    assert same.expected_close_date == second.deadline_date


@pytest.mark.asyncio
async def test_change_after_the_old_deadline_reopens_the_closed_opportunity() -> None:
    first, second = _change_pair()
    await _process(first)
    [opportunity] = await _opportunities(first)
    yesterday = business_today() - timedelta(days=1)
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(SalesTenderNotice).where(
                    SalesTenderNotice.number == first.number
                )
            )
        ).scalar_one()
        row.deadline_date = yesterday
        (await db.get(SalesOpportunity, opportunity.id)).expected_close_date = yesterday
        await db.commit()
    async with AsyncSessionLocal() as db:
        await flow.close_expired(db, today=business_today(), now=_now())
        await db.commit()
    [closed] = await _opportunities(first)
    assert (closed.status, closed.lost_reason) == ("lost", flow.EXPIRED_REASON)

    counts = await _process(second)
    assert counts.updated == 1
    stages = await _stages()
    [reopened] = await _opportunities(first)
    assert reopened.status == "open"
    assert reopened.stage_id == stages["tender-identified"]
    assert reopened.lost_reason is None
    assert reopened.expected_close_date == second.deadline_date


@pytest.mark.asyncio
async def test_expired_notice_whose_change_extends_the_deadline_gets_an_opportunity() -> (
    None
):
    first, second = _change_pair()
    first = replace(first, deadline_date=business_today() - timedelta(days=1))
    counts = await _process(first)
    assert counts.rejected == 1
    counts = await _process(second)
    assert counts.created == 1
    row = await _row(second)
    assert row.status == "created" and row.opportunity_id is not None
    [opportunity] = await _opportunities(second)
    assert opportunity.expected_close_date == second.deadline_date


# ── Zmiana ogłoszenia BZP (ogłoszenie o zmianie z nowym terminem) ───────────


def _at(day: date, hour: int = 10) -> datetime:
    """Termin z godziną jak w BZP: czas warszawski zapisany w UTC."""

    return datetime.combine(day, time(hour, 0), ZoneInfo(DEFAULT_TZ)).astimezone(
        timezone.utc
    )


def _bzp_notice(**fields: Any) -> Notice:
    deadline_at = fields.pop("deadline_at", _at(business_today() + timedelta(days=3)))
    return _notice(
        procedure_id=f"ocds-148610-{uuid.uuid4()}",
        deadline_at=deadline_at,
        deadline_date=business_date(deadline_at),
        **fields,
    )


def _bzp_change(
    notice: Notice, deadline_at: datetime, *, hours_ago: int = 1
) -> sources.BzpChange:
    marker = _marker()
    return sources.BzpChange(
        number=f"2026/BZP C{marker}",
        procedure_id=notice.procedure_id or "",
        published_at=_now() - timedelta(hours=hours_ago),
        deadline_date=business_date(deadline_at),
        deadline_at=deadline_at,
        url=f"https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/c{marker}",
    )


async def _process_changes(*changes: sources.BzpChange) -> flow.RunCounts:
    await _stages()
    counts = flow.RunCounts()
    async with AsyncSessionLocal() as db:
        await flow.process_bzp_changes(
            db,
            list(changes),
            TenderRules(),
            now=_now(),
            today=business_today(),
            counts=counts,
        )
        await db.commit()
    return counts


async def _notes(opportunity_id: int) -> list[SalesActivity]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(SalesActivity)
                    .where(SalesActivity.opportunity_id == opportunity_id)
                    .order_by(SalesActivity.id)
                )
            ).scalars()
        )


@pytest.mark.asyncio
async def test_bzp_change_moves_the_deadline_and_leaves_one_note() -> None:
    notice = _bzp_notice()
    await _process(notice)
    new_deadline = _at(business_today() + timedelta(days=9), hour=12)
    change = _bzp_change(notice, new_deadline)

    counts = await _process_changes(change)
    assert (counts.updated, counts.created) == (1, 0)
    row = await _row(notice)
    assert (row.deadline_date, row.deadline_at) == (
        change.deadline_date,
        new_deadline,
    )
    # Przetarg to dalej ogłoszenie o zamówieniu: numer i link zostają.
    assert (row.number, row.url) == (notice.number, notice.url)
    [opportunity] = await _opportunities(notice)
    assert opportunity.expected_close_date == change.deadline_date
    tender = opportunity.custom_fields["tender"]
    assert (tender["number"], tender["url"]) == (notice.number, notice.url)
    assert sources.parse_instant(tender["deadline_at"]) == new_deadline

    created, note = await _notes(opportunity.id)
    assert note.subject == f"Zmiana przetargu BZP {notice.number}"
    assert f"Ogłoszenie o zmianie BZP {change.number}" in note.body
    assert "→" in note.body and ", 12:00" in note.body
    assert change.url in note.body and note.web_link == change.url
    async with AsyncSessionLocal() as db:
        fields = {
            e.field
            for e in (
                await db.execute(
                    select(SalesOpportunityEvent).where(
                        SalesOpportunityEvent.opportunity_id == opportunity.id
                    )
                )
            ).scalars()
        }
    assert "expected_close_date" in fields

    again = await _process_changes(change)
    assert again.updated == 0
    assert len(await _notes(opportunity.id)) == 2


@pytest.mark.asyncio
async def test_bzp_change_after_the_old_deadline_reopens_the_closed_opportunity() -> (
    None
):
    """Przedłużenie przyszło, gdy automat już zamknął szansę po pierwotnym terminie."""

    yesterday = business_today() - timedelta(days=1)
    notice = _bzp_notice()
    await _process(notice)
    [opportunity] = await _opportunities(notice)
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(SalesTenderNotice).where(
                    SalesTenderNotice.number == notice.number
                )
            )
        ).scalar_one()
        row.deadline_at = _at(yesterday)
        row.deadline_date = yesterday
        (await db.get(SalesOpportunity, opportunity.id)).expected_close_date = yesterday
        await db.commit()
    async with AsyncSessionLocal() as db:
        await flow.close_expired(db, today=business_today(), now=_now())
        await db.commit()
    [closed] = await _opportunities(notice)
    assert (closed.status, closed.lost_reason) == ("lost", flow.EXPIRED_REASON)

    # Termin, który minął już dziś (z godziną), szansy nie przywraca.
    passed = _bzp_change(notice, _now() - timedelta(hours=1), hours_ago=2)
    assert (await _process_changes(passed)).updated == 1
    [still] = await _opportunities(notice)
    assert (still.status, still.lost_reason) == ("lost", flow.EXPIRED_REASON)

    change = _bzp_change(notice, _at(business_today() + timedelta(days=4)))
    counts = await _process_changes(change)
    assert counts.updated == 1
    stages = await _stages()
    [reopened] = await _opportunities(notice)
    assert reopened.status == "open"
    assert reopened.stage_id == stages["tender-identified"]
    assert reopened.lost_reason is None
    assert reopened.expected_close_date == change.deadline_date
    note = (await _notes(opportunity.id))[-1]
    assert "Szansa wraca do „Identyfikacji”." in note.body


@pytest.mark.asyncio
async def test_bzp_change_keeps_a_close_date_set_by_hand() -> None:
    notice = _bzp_notice()
    await _process(notice)
    [opportunity] = await _opportunities(notice)
    by_hand = business_today() + timedelta(days=30)
    async with AsyncSessionLocal() as db:
        (await db.get(SalesOpportunity, opportunity.id)).expected_close_date = by_hand
        await db.commit()

    change = _bzp_change(notice, _at(business_today() + timedelta(days=6)))
    assert (await _process_changes(change)).updated == 1
    assert (await _row(notice)).deadline_date == change.deadline_date
    [same] = await _opportunities(notice)
    assert same.expected_close_date == by_hand
    assert same.custom_fields["tender"]["deadline_date"] == (
        change.deadline_date.isoformat()
    )


@pytest.mark.asyncio
async def test_bzp_change_of_an_unknown_procedure_is_not_stored() -> None:
    stranger = _bzp_notice()
    change = _bzp_change(stranger, _at(business_today() + timedelta(days=5)))
    counts = await _process_changes(change)
    assert (counts.updated, counts.created) == (0, 0)
    async with AsyncSessionLocal() as db:
        rows = await db.scalar(
            select(SalesTenderNotice.id).where(
                SalesTenderNotice.procedure_id == change.procedure_id
            )
        )
        notes = await db.scalar(
            select(SalesActivity.id).where(
                SalesActivity.external_ref == f"tender-note:bzp:{change.number}"
            )
        )
    assert rows is None and notes is None


@pytest.mark.asyncio
async def test_bzp_change_already_in_the_notice_changes_nothing() -> None:
    """BZP podaje w ogłoszeniu termin po zmianach, które były przed pobraniem."""

    notice = _bzp_notice()
    await _process(notice)
    assert notice.deadline_at is not None
    counts = await _process_changes(_bzp_change(notice, notice.deadline_at))
    assert counts.updated == 0
    [opportunity] = await _opportunities(notice)
    assert len(await _notes(opportunity.id)) == 1


@pytest.mark.asyncio
async def test_only_the_latest_bzp_change_of_a_procedure_counts() -> None:
    notice = _bzp_notice()
    await _process(notice)
    first = _bzp_change(notice, _at(business_today() + timedelta(days=5)), hours_ago=2)
    latest = _bzp_change(notice, _at(business_today() + timedelta(days=8)))

    counts = await _process_changes(latest, first)
    assert counts.updated == 1
    assert (await _row(notice)).deadline_date == latest.deadline_date
    [opportunity] = await _opportunities(notice)
    created, note = await _notes(opportunity.id)
    assert note.external_ref == f"tender-note:bzp:{latest.number}"


@pytest.mark.asyncio
async def test_rejected_bzp_notice_whose_change_extends_the_deadline_gets_an_opportunity() -> (
    None
):
    """Ogłoszenie weszło samym kodem CPV i odpadło po terminie; po przedłużeniu
    bramka znów widzi kod CPV i zakłada szansę."""

    notice = _bzp_notice(
        title=f"Utrzymanie systemu ewidencji {_marker()}",
        cpv_codes=("72267000",),
        cpv_label="72267000-4 (Usługi w zakresie konserwacji oprogramowania)",
        deadline_at=_now() - timedelta(hours=1),
    )
    counts = await _process(notice)
    assert counts.rejected == 1
    row = await _row(notice)
    assert (row.rule, row.match_detail) == ("expired", "CPV 72267000")

    change = _bzp_change(notice, _at(business_today() + timedelta(days=7)))
    counts = await _process_changes(change)
    assert (counts.created, counts.updated) == (1, 0)
    row = await _row(notice)
    assert row.status == "created" and row.opportunity_id is not None
    [opportunity] = await _opportunities(notice)
    assert opportunity.id == row.opportunity_id
    assert opportunity.expected_close_date == change.deadline_date


# ── Zamykanie po terminie ───────────────────────────────────────────────────


async def _gate_opportunity(*, deadline: date, stage: str, ref: bool = True) -> int:
    stages = await _stages()
    marker = _marker()
    async with AsyncSessionLocal() as db:
        company = SalesCompany(
            name=f"Termin {marker}", normalized_name=f"termin {marker}"
        )
        db.add(company)
        await db.flush()
        pipeline_id = await db.scalar(
            select(SalesPipeline.id).where(
                SalesPipeline.key == flow.TENDER_PIPELINE_KEY
            )
        )
        opportunity = SalesOpportunity(
            company_id=company.id,
            pipeline_id=pipeline_id,
            stage_id=stages[stage],
            title=f"Przetarg {marker}",
            expected_close_date=deadline,
            external_ref=flow.external_ref("bzp", f"2026/BZP E{marker}")
            if ref
            else None,
        )
        db.add(opportunity)
        await db.commit()
        return opportunity.id


@pytest.mark.asyncio
async def test_expired_gate_opportunity_in_identification_closes_itself() -> None:
    today = business_today()
    expired = await _gate_opportunity(
        deadline=today - timedelta(days=1), stage="tender-identified"
    )
    worked_on = await _gate_opportunity(
        deadline=today - timedelta(days=1), stage="tender-analysis"
    )
    manual = await _gate_opportunity(
        deadline=today - timedelta(days=1), stage="tender-identified", ref=False
    )
    upcoming = await _gate_opportunity(deadline=today, stage="tender-identified")

    async with AsyncSessionLocal() as db:
        closed = await flow.close_expired(db, today=today, now=_now())
        await db.commit()
    assert closed >= 1
    stages = await _stages()
    async with AsyncSessionLocal() as db:
        rows = {
            opp.id: opp
            for opp in (
                await db.execute(
                    select(SalesOpportunity).where(
                        SalesOpportunity.id.in_((expired, worked_on, manual, upcoming))
                    )
                )
            ).scalars()
        }
        events = list(
            (
                await db.execute(
                    select(SalesOpportunityEvent).where(
                        SalesOpportunityEvent.opportunity_id == expired
                    )
                )
            ).scalars()
        )
    assert rows[expired].status == "lost"
    assert rows[expired].stage_id == stages["tender-lost"]
    assert rows[expired].lost_reason == flow.EXPIRED_REASON
    assert {e.field for e in events} >= {"stage_id", "status", "lost_reason"}
    assert all(e.user_id is None for e in events)
    assert rows[worked_on].status == "open"
    assert rows[manual].status == "open"
    assert rows[upcoming].status == "open"


# ── Bieg: stan i awaria rejestru ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_keeps_the_cursor_of_a_failed_register(monkeypatch) -> None:
    await _stages()
    ted_notice = _notice(source="ted", number=f"{uuid.uuid4().int % 10**6}-2026")

    async def broken_bzp(client, *, since, until):
        raise sources.SourceError("bzp: ConnectError")

    async def no_changes_without_notices(client, *, since, until):
        raise AssertionError("bez ogłoszeń BZP bieg nie pyta o zmiany")

    async def fine_ted(client, *, since, until):
        return [ted_notice]

    monkeypatch.setattr(sources, "fetch_bzp", broken_bzp)
    monkeypatch.setattr(sources, "fetch_bzp_changes", no_changes_without_notices)
    monkeypatch.setattr(sources, "fetch_ted", fine_ted)
    result = await flow.run(trigger="manual")

    assert result.status == "failed"
    assert result.counts.created == 1
    assert len(await _opportunities(ted_notice)) == 1
    async with AsyncSessionLocal() as db:
        state = await flow.load_state(db)
    assert "bzp_cursor" not in state
    assert "bzp_update_cursor" not in state
    assert state["ted_day"] == business_today().isoformat()
    assert state["last_run"]["status"] == "failed"
    assert state["last_run"]["error"] == "Rejestr BZP nie odpowiedział."
    assert state["last_run"]["counts"]["created"] == 1


@pytest.mark.asyncio
async def test_run_advances_cursor_after_success(monkeypatch) -> None:
    await _stages()
    cursor = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
    update_cursor = datetime(2026, 11, 24, 12, 30, tzinfo=timezone.utc)

    async def bzp(client, *, since, until):
        return sources.BzpBatch([], cursor, 1)

    async def bzp_changes(client, *, since, until):
        return sources.BzpChangeBatch([], update_cursor, 1)

    async def ted(client, *, since, until):
        return []

    monkeypatch.setattr(sources, "fetch_bzp", bzp)
    monkeypatch.setattr(sources, "fetch_bzp_changes", bzp_changes)
    monkeypatch.setattr(sources, "fetch_ted", ted)
    result = await flow.run(trigger="schedule")
    assert result.status == "ok"
    async with AsyncSessionLocal() as db:
        state = await flow.load_state(db)
    assert sources.parse_instant(state["bzp_cursor"]) == cursor
    assert sources.parse_instant(state["bzp_update_cursor"]) == update_cursor
    assert state["last_run"]["trigger"] == "schedule"


@pytest.mark.asyncio
async def test_run_follows_a_bzp_change_with_its_own_cursor(monkeypatch) -> None:
    """Zmiana z tego samego biegu przesuwa szansę ogłoszenia założonego chwilę wcześniej;
    bez kursora zmian okno zaczyna się przy najstarszym ogłoszeniu BZP w bazie."""

    await _stages()
    notice = _bzp_notice()
    change = _bzp_change(notice, _at(business_today() + timedelta(days=12)))
    cursor = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
    update_cursor = datetime(2026, 11, 24, 12, 30, tzinfo=timezone.utc)
    asked: list[datetime] = []

    async def bzp(client, *, since, until):
        return sources.BzpBatch([notice], cursor, 1)

    async def bzp_changes(client, *, since, until):
        asked.append(since)
        return sources.BzpChangeBatch([change], update_cursor, 1)

    async def ted(client, *, since, until):
        return []

    monkeypatch.setattr(sources, "fetch_bzp", bzp)
    monkeypatch.setattr(sources, "fetch_bzp_changes", bzp_changes)
    monkeypatch.setattr(sources, "fetch_ted", ted)
    result = await flow.run(trigger="manual")
    assert result.status == "ok", result.errors
    counts = result.counts
    assert (counts.created, counts.updated, counts.bzp_changes) == (1, 1, 1)
    [opportunity] = await _opportunities(notice)
    assert opportunity.expected_close_date == change.deadline_date
    async with AsyncSessionLocal() as db:
        state = await flow.load_state(db)
    assert sources.parse_instant(state["bzp_update_cursor"]) == update_cursor
    assert state["last_run"]["counts"]["updated"] == 1
    started = sources.parse_instant(state["last_run"]["started_at"])
    assert started is not None
    assert started - timedelta(days=flow.INITIAL_DAYS) <= asked[0] <= started


@pytest.mark.asyncio
async def test_run_keeps_the_update_cursor_when_bzp_changes_fail(monkeypatch) -> None:
    await _stages()
    cursor = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)

    async def bzp(client, *, since, until):
        return sources.BzpBatch([], cursor, 1)

    async def broken_changes(client, *, since, until):
        raise sources.SourceError("bzp: ReadTimeout")

    async def ted(client, *, since, until):
        return []

    monkeypatch.setattr(sources, "fetch_bzp", bzp)
    monkeypatch.setattr(sources, "fetch_bzp_changes", broken_changes)
    monkeypatch.setattr(sources, "fetch_ted", ted)
    result = await flow.run(trigger="schedule")
    assert result.status == "failed"
    async with AsyncSessionLocal() as db:
        state = await flow.load_state(db)
    assert sources.parse_instant(state["bzp_cursor"]) == cursor
    assert "bzp_update_cursor" not in state
    assert state["last_run"]["error"] == flow.CHANGES_FAILED


# ── Trasy ───────────────────────────────────────────────────────────────────


async def _rejected_row(**fields: Any) -> int:
    await _stages()
    marker = _marker()
    values: dict[str, Any] = {
        "source": "bzp",
        "number": f"2026/BZP R{marker}",
        "title": f"Utrzymanie systemu {marker}",
        "buyer_name": f"Szpital Przetargowy {marker}",
        "published_at": _now() - timedelta(days=1),
        "deadline_date": business_today() + timedelta(days=5),
        "order_type": "services",
        "status": "rejected",
        "rule": "buyer",
        "rule_detail": "szpital",
        "match_detail": "CPV 72250000",
    }
    values.update(fields)
    async with AsyncSessionLocal() as db:
        row = SalesTenderNotice(**values)
        db.add(row)
        await db.commit()
        return row.id


@pytest.mark.asyncio
async def test_list_needs_sales_view_and_shows_rejected_with_rule(app_client) -> None:
    row_id = await _rejected_row()
    recruiter = await _user()
    resp = await app_client.get(URL, headers=_headers(recruiter))
    assert resp.status_code == 403

    viewer = await _user("sales_view")
    resp = await app_client.get(
        URL, params={"status": "rejected"}, headers=_headers(viewer)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["can_edit"] is False and body["can_run"] is False
    item = next(i for i in body["items"] if i["id"] == row_id)
    assert (item["rule_label"], item["rule_detail"]) == ("Zamawiający", "szpital")
    assert body["rejected"] >= 1


@pytest.mark.asyncio
async def test_restore_creates_the_opportunity_for_the_person(app_client) -> None:
    row_id = await _rejected_row()
    viewer = await _user("sales_view")
    resp = await app_client.post(f"{URL}/{row_id}/restore", headers=_headers(viewer))
    assert resp.status_code == 403

    seller = await _user("sales_edit")
    resp = await app_client.post(f"{URL}/{row_id}/restore", headers=_headers(seller))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "created"
    assert body["opportunity_status"] == "open"
    assert body["restored_by"] == seller.name
    async with AsyncSessionLocal() as db:
        opportunity = await db.get(SalesOpportunity, body["opportunity_id"])
    assert opportunity.owner_user_id == seller.id
    assert opportunity.created_by_user_id == seller.id

    again = await app_client.post(f"{URL}/{row_id}/restore", headers=_headers(seller))
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_restore_refuses_a_notice_after_its_deadline(app_client) -> None:
    row_id = await _rejected_row(deadline_date=business_today() - timedelta(days=1))
    seller = await _user("sales_edit")
    resp = await app_client.post(f"{URL}/{row_id}/restore", headers=_headers(seller))
    assert resp.status_code == 409
    assert "Termin składania ofert minął" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_rules_are_edited_by_sales_edit_with_a_sales_owner(app_client) -> None:
    viewer = await _user("sales_view")
    resp = await app_client.get(f"{URL}/rules", headers=_headers(viewer))
    assert resp.status_code == 200
    assert resp.json()["phrases"] == list(rules.DEFAULT_PHRASES)
    assert resp.json()["owners"] == []

    payload = {
        "phrases": ["body leasing", "zespół IT"],
        "reject_subject": ["dostawa"],
        "reject_buyer": ["gmina"],
        "only_services": True,
        "owner_user_id": None,
    }
    resp = await app_client.put(f"{URL}/rules", json=payload, headers=_headers(viewer))
    assert resp.status_code == 403

    seller = await _user("sales_edit")
    recruiter = await _user()
    resp = await app_client.put(
        f"{URL}/rules",
        json={**payload, "owner_user_id": recruiter.id},
        headers=_headers(seller),
    )
    assert resp.status_code == 422
    resp = await app_client.put(
        f"{URL}/rules",
        json={**payload, "phrases": ["x" * 61]},
        headers=_headers(seller),
    )
    assert resp.status_code == 422

    resp = await app_client.put(
        f"{URL}/rules",
        json={**payload, "owner_user_id": seller.id},
        headers=_headers(seller),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["phrases"] == ["body leasing", "zespół IT"]
    assert (body["owner_user_id"], body["owner_name"]) == (seller.id, seller.name)
    assert any(owner["id"] == seller.id for owner in body["owners"])


@pytest.mark.asyncio
async def test_manual_run_is_for_admin_and_runs_in_the_background(
    app_client, monkeypatch
) -> None:
    started: list[str] = []

    async def fake_run(*, trigger: str) -> flow.RunResult:
        started.append(trigger)
        return flow.RunResult(status="ok")

    monkeypatch.setattr(flow, "run", fake_run)
    seller = await _user("sales_edit")
    resp = await app_client.post(f"{URL}/run", headers=_headers(seller))
    assert resp.status_code == 403

    admin = await _user(role="admin")
    resp = await app_client.post(f"{URL}/run", headers=_headers(admin))
    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "running"
    for _ in range(20):
        if started:
            break
        await asyncio.sleep(0.05)
    assert started == ["manual"]


@pytest.mark.asyncio
async def test_manual_run_refuses_while_another_run_is_going(app_client) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            AppSetting(
                key=flow.STATE_KEY,
                value={
                    "last_run": {"status": "running", "started_at": _now().isoformat()}
                },
            )
        )
        await db.commit()
    admin = await _user(role="admin")
    resp = await app_client.post(f"{URL}/run", headers=_headers(admin))
    assert resp.status_code == 409
