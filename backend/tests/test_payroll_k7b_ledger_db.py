"""K7b z bazą: dekret listy płac NEXUSA do księgi (LP) i jedno źródło LP w miesiącu.

Ścieżki odmowy: lista niezatwierdzona (409), LP z Enovy w tym miesiącu (409),
import z Enovy przy LP z NEXUSA (409), zatwierdzony LP (409 przy ponownym
dekrecie i przy anulowaniu listy). Kwoty fikcyjne.
"""

# ruff: noqa: F811  (fixture z innego pliku jako parametr testu)
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.hr_payroll import PayrollPeriod
from app.models.hr_payroll_lists import (
    PayrollList,
    PayrollListLine,
    PayrollParameterVersion,
)
from app.models.ledger import LedgerDocument
from app.services.hr.payroll_errors import PayrollConflict
from app.services.hr.payroll_lists import ledger_post, lists, params
from app.services.ledger.payroll_lists import NEXUS_SOURCE_TYPE
from tests.test_ledger_db import _set_ledger
from tests.test_ledger_sources_db import (  # noqa: F401  (fixture ``books``, ``client``)
    _approve_ids,
    _lines,
    _payroll_import,
    _payroll_settings,
    books,
    client,
)
from tests.test_finance_ledger_db import world  # noqa: F401  (fixture ``world``)

RESULT = {
    "gross": "10000.00",
    "pension_employee": "976.00",
    "disability_employee": "150.00",
    "sickness_employee": "245.00",
    "health": "776.61",
    "pit": "588.00",
    "ppk_employee": "200.00",
    "net": "7064.39",
    "pension_employer": "976.00",
    "disability_employer": "650.00",
    "accident_employer": "167.00",
    "labour_fund": "245.00",
    "fgsp": "10.00",
    "ppk_employer": "150.00",
}


@pytest_asyncio.fixture
async def nexus_list(world, books):
    year = books["year"]
    async with AsyncSessionLocal() as db:
        period = await db.scalar(
            select(PayrollPeriod).where(
                PayrollPeriod.year == year, PayrollPeriod.month == 3
            )
        )
        created_period = period is None
        if period is None:
            period = PayrollPeriod(
                year=year,
                month=3,
                status="closed",
                close_count=1,
                closed_at=datetime.now(timezone.utc),
            )
            db.add(period)
        version = PayrollParameterVersion(
            effective_from=date(year, 1, 1),
            params=dict(params.SEED_2026),
            status="confirmed",
            source="manual",
            confirmed_at=datetime(year, 1, 1, tzinfo=timezone.utc),
        )
        db.add(version)
        await db.flush()
        lst = PayrollList(
            period_id=period.id,
            year=year,
            month=3,
            number=f"LP/{year}/03",
            status="draft",
            pay_date=date(year, 4, 10),
            parameter_version_id=version.id,
            totals={},
            problems=[],
        )
        db.add(lst)
        await db.flush()
        db.add(
            PayrollListLine(
                list_id=lst.id,
                user_id=world["person"].id,
                person_name="Osoba A",
                kind="uop",
                source="salary",
                gross=RESULT["gross"],
                net=RESULT["net"],
                basis={},
                result=RESULT,
                problems=[],
            )
        )
        await db.commit()
        ids = {"list": lst.id, "period": period.id, "version": version.id}
    yield ids
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(LedgerDocument).where(
                LedgerDocument.source_type == NEXUS_SOURCE_TYPE,
                LedgerDocument.source_id.like(f"{year}-03:%"),
                LedgerDocument.status == "draft",
            )
        )
        await db.execute(
            delete(PayrollListLine).where(PayrollListLine.list_id == ids["list"])
        )
        await db.execute(delete(PayrollList).where(PayrollList.id == ids["list"]))
        await db.execute(
            delete(PayrollParameterVersion).where(
                PayrollParameterVersion.id == ids["version"]
            )
        )
        if created_period:
            await db.execute(
                delete(PayrollPeriod).where(PayrollPeriod.id == ids["period"])
            )
        await db.commit()


async def _set_status(list_id: int, status: str) -> None:
    async with AsyncSessionLocal() as db:
        lst = await db.get(PayrollList, list_id)
        lst.status = status
        lst.approved_at = datetime.now(timezone.utc) if status == "approved" else None
        await db.commit()


async def _post(world, list_id: int):
    async with AsyncSessionLocal() as db:
        lst = await db.get(PayrollList, list_id)
        result = await ledger_post.post(db, actor=world["accountant"], lst=lst)
        await db.commit()
        return result


@pytest.mark.asyncio
async def test_nexus_list_goes_to_buffer_as_payroll_lp(
    client, world, books, nexus_list
):
    year, acc = books["year"], books["acc"]
    await _set_ledger(
        {
            **_payroll_settings(world, books),
            "modules": {"ledger": True, "automations": True, "payroll": True},
        }
    )
    with pytest.raises(PayrollConflict):
        await _post(world, nexus_list["list"])  # szkic listy — jeszcze nie do księgi
    await _set_status(nexus_list["list"], "approved")
    first = await _post(world, nexus_list["list"])
    async with AsyncSessionLocal() as db:
        doc = await db.get(LedgerDocument, first["document"]["id"])
        assert doc.doc_type == "LP" and doc.sensitivity == "payroll"
        assert doc.source_type == NEXUS_SOURCE_TYPE and doc.op_date == date(year, 3, 31)
        assert doc.doc_date == date(year, 4, 10)
    lines = await _lines(first["document"]["id"])
    assert ("debit", acc["wages"], 1_000_000) in lines
    assert ("debit", acc["insurance"], 219_800) in lines  # 976+650+167+245+10+150
    debit = sum(amount for side, _, amount in lines if side == "debit")
    assert debit == sum(amount for side, _, amount in lines if side == "credit")
    assert first["totals"]["net"] == 706_439
    # Import z Enovy za ten sam miesiąc odmawia — jedno źródło LP.
    enova = await _payroll_import(client, world, books, save=True)
    assert enova.status_code == 409 and "jedno źródło" in enova.json()["detail"]
    # Ponowny dekret przebudowuje szkic.
    again = await _post(world, nexus_list["list"])
    assert again["document"]["id"] != first["document"]["id"]
    await _approve_ids(client, world, [again["document"]["id"]])
    with pytest.raises(PayrollConflict, match="storn"):
        await _post(world, nexus_list["list"])
    async with AsyncSessionLocal() as db:
        with pytest.raises(PayrollConflict, match="storno"):
            await lists.cancel(
                db, actor=world["accountant"], list_id=nexus_list["list"], reason="test"
            )
        await db.rollback()


@pytest.mark.asyncio
async def test_enova_lp_blocks_nexus_lp_for_the_month(client, world, books, nexus_list):
    await _set_ledger(
        {
            **_payroll_settings(world, books),
            "modules": {"ledger": True, "automations": True, "payroll": True},
        }
    )
    saved = await _payroll_import(client, world, books, save=True)
    assert saved.status_code == 200, saved.text
    await _set_status(nexus_list["list"], "approved")
    with pytest.raises(PayrollConflict, match="Enovy"):
        await _post(world, nexus_list["list"])


@pytest.mark.asyncio
async def test_cancel_removes_draft_lp(client, world, books, nexus_list):
    await _set_ledger(
        {
            **_payroll_settings(world, books),
            "modules": {"ledger": True, "automations": True, "payroll": True},
        }
    )
    await _set_status(nexus_list["list"], "approved")
    posted = await _post(world, nexus_list["list"])
    async with AsyncSessionLocal() as db:
        await lists.cancel(
            db, actor=world["accountant"], list_id=nexus_list["list"], reason="test"
        )
        await db.commit()
        assert await db.get(LedgerDocument, posted["document"]["id"]) is None
