"""Import wniosków urlopowych z Compassa: na sucho → zapis → drugi zapis bez zmian.

Paczki są fikcyjne (repo publiczne): osoby „Osoba <znacznik>”, e-maile
``@example.com``, identyfikatory Compassa losowe. Każdy test działa w jednej
sesji i kończy się rollbackiem — nic nie zostaje w bazie.

Ten plik niesie też pomocniki wspólne dla testów importu pozostałych modułów
(``make_bundle``, ``make_person``, ``run_import``, ``assert_report_clean``)
oraz test wiersza poleceń dla każdego modułu z rejestru.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.hr_leave import HrM365Operation, LeaveRequest, LeaveRequestDay
from app.models.hr_ops import HrImportIdMap
from app.models.hr_profile import EmployeeProfile
from app.models.notification import Notification
from app.models.user import User, UserRole
from app.services.hr import compass_import
from app.services.hr.compass_import import leave as leave_import

# ── Pomocniki wspólne dla testów importu ─────────────────────────────────────


def make_bundle(tables: dict[str, list[dict[str, Any]]]) -> compass_import.Bundle:
    raw = json.dumps(
        {
            "format": "compass-bundle",
            "version": 1,
            "exported_at": "2026-11-13T18:00:00+01:00",
            "tables": tables,
        },
        default=str,
    ).encode()
    return compass_import.parse_bundle(raw)


async def make_person(
    db,
    marker: str,
    *,
    role: UserRole = UserRole.recruiter,
    employment_type: str = "uop",
    default_location: str = "onsite",
    with_profile: bool = True,
    employment_status: str = "active",
    last_working_day: Optional[date] = None,
) -> tuple[User, str, dict[str, Any]]:
    """Konto (z kartoteką albo bez) + wiersz ``profiles`` Compassa tej osoby."""

    compass_id = str(uuid.uuid4())
    user = User(
        email=f"import-{marker}@example.com",
        name=f"Osoba {marker}",
        role=role,
        roles=[role.value],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    if with_profile:
        db.add(
            EmployeeProfile(
                user_id=user.id,
                employment_type=employment_type,
                employment_status=employment_status,
                default_location=default_location,
                last_working_day=last_working_day,
                compass_profile_id=uuid.UUID(compass_id),
            )
        )
        await db.flush()
    row = {
        "id": compass_id,
        "email": f"Import-{marker}@Example.com",
        "full_name": f"Osoba {marker}",
        "employment_status": employment_status,
        "termination_date": last_working_day.isoformat() if last_working_day else None,
    }
    return user, compass_id, row


async def run_import(db, module: str, bundle: compass_import.Bundle):
    """Na sucho, potem zapis tej samej paczki. Zwraca (raport na sucho, zapisane)."""

    importer = compass_import.IMPORTERS[module]
    batch, _ = await compass_import.dry_run(
        db, module=module, bundle=bundle, planner=importer.plan, actor_user_id=None
    )
    report = batch.report["dry_run"]
    written = await compass_import.apply(
        db,
        batch=batch,
        bundle=bundle,
        planner=importer.plan,
        applier=importer.apply,
        actor_user_id=None,
    )
    return batch, report, written


def assert_report_clean(report: dict[str, Any], *forbidden: str) -> None:
    """Raport partii bez imion, e-maili i podanych napisów (kwoty, treści)."""

    dumped = json.dumps(report, ensure_ascii=False, default=str)
    assert "Osoba" not in dumped
    assert "example.com" not in dumped.lower()
    for value in forbidden:
        assert value not in dumped, value


def leave_row(person: str, start: str, end: str, **values: Any) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "user_id": person,
        "leave_type": "vacation",
        "status": "approved",
        "start_date": start,
        "end_date": end,
        "half_day": None,
        "note": None,
        "substitute_id": None,
        "forward_mail_enabled": False,
        "created_by": person,
        "created_on_behalf": False,
        "decided_by": None,
        "decided_at": "2026-02-20T09:00:00+00:00",
        "paid_days": 0,
        "unpaid_days": 0,
        "source": None,
        "created_at": "2026-02-19T09:00:00+00:00",
        **values,
    }


# ── Testy ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_leave_dry_run_apply_and_second_apply_changes_nothing() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        try:
            worker, w_id, w_row = await make_person(db, f"{tag}-worker")
            boss, b_id, b_row = await make_person(
                db, f"{tag}-boss", role=UserRole.head_of_recruitment
            )
            contractor, c_id, c_row = await make_person(
                db, f"{tag}-b2b", employment_type="b2b"
            )
            _, n_id, n_row = await make_person(db, f"{tag}-none", with_profile=False)

            # Wniosek złożony już w NEXUSIE — nakładka z importem.
            native = LeaveRequest(
                id=uuid.uuid4(),
                user_id=contractor.id,
                leave_type="vacation",
                status="approved",
                start_date=date(2026, 5, 4),
                end_date=date(2026, 5, 4),
                source="self",
            )
            db.add(native)
            await db.flush()
            db.add(
                LeaveRequestDay(
                    leave_request_id=native.id,
                    user_id=contractor.id,
                    day=date(2026, 5, 4),
                    paid=True,
                    active=True,
                )
            )
            await db.flush()

            uop = leave_row(
                w_id,
                "2026-03-02",
                "2026-03-06",
                decided_by=b_id,
                substitute_id=b_id,
                forward_mail_enabled=True,
                paid_days=5,
                note="Urlop rodzinny",
            )
            b2b = leave_row(
                c_id, "2026-03-09", "2026-03-13", paid_days=3, unpaid_days=2
            )
            self_decided = leave_row(
                w_id,
                "2026-03-16",
                "2026-03-17",
                leave_type="sick_leave",
                decided_by=w_id,
            )
            overlapping = leave_row(
                w_id,
                "2026-03-05",
                "2026-03-06",
                status="pending",
                decided_at=None,
                created_at="2026-02-25T09:00:00+00:00",
            )
            cancelled_same_days = leave_row(
                w_id, "2026-03-05", "2026-03-05", status="cancelled"
            )
            on_behalf = leave_row(
                w_id,
                "2026-04-01",
                "2026-04-01",
                created_by=b_id,
                created_on_behalf=True,
                substitute_id=b_id,
                forward_mail_enabled=True,
                decided_by=b_id,
            )
            clash_native = leave_row(c_id, "2026-05-04", "2026-05-05", paid_days=2)
            no_profile = leave_row(n_id, "2026-03-02", "2026-03-02")
            rows = [
                uop,
                b2b,
                self_decided,
                overlapping,
                cancelled_same_days,
                on_behalf,
                clash_native,
                no_profile,
            ]
            bundle = make_bundle(
                {"profiles": [w_row, b_row, c_row, n_row], "leave_requests": rows}
            )
            importer = compass_import.IMPORTERS["leave"]

            batch, report, written = await run_import(db, "leave", bundle)
            assert report["counts"] == {"create": 5, "conflict": 2, "skip": 1}
            assert report["reasons"][leave_import.OVERLAP] == 2
            assert report["reasons"]["osoba bez kartoteki w NEXUSIE"] == 1
            assert report["reasons"][leave_import.SELF_DECISION] == 1
            assert report["reasons"][leave_import.FORWARD_ON_BEHALF] == 1
            attention = {item["source_id"] for item in report["attention"]}
            assert f"leave_requests:{overlapping['id']}" in attention
            assert_report_clean(batch.report, "Urlop rodzinny")
            assert written["requests_created"] == 5
            assert written["conflicts_at_write"] == 0

            request = await db.get(LeaveRequest, uuid.UUID(uop["id"]))
            assert request.source == "compass_import"
            assert request.user_id == worker.id
            assert request.decided_by == boss.id
            assert request.substitute_user_id == boss.id
            assert request.forward_mail_consent is True
            days = list(
                await db.scalars(
                    select(LeaveRequestDay)
                    .where(LeaveRequestDay.leave_request_id == request.id)
                    .order_by(LeaveRequestDay.day)
                )
            )
            assert [d.day.day for d in days] == [2, 3, 4, 5, 6]
            assert all(d.paid and d.active for d in days)

            contractor_request = await db.get(LeaveRequest, uuid.UUID(b2b["id"]))
            paid_flags = [
                d.paid
                for d in await db.scalars(
                    select(LeaveRequestDay)
                    .where(LeaveRequestDay.leave_request_id == contractor_request.id)
                    .order_by(LeaveRequestDay.day)
                )
            ]
            assert paid_flags == [True, True, True, False, False]
            assert contractor_request.paid_days == Decimal("3")
            assert contractor_request.unpaid_days == Decimal("2")

            # Samozatwierdzenie z Compassa nie przechodzi (CHECK by je odrzucił).
            sick = await db.get(LeaveRequest, uuid.UUID(self_decided["id"]))
            assert sick.decided_by is None
            assert sick.status == "approved"
            sick_days = list(
                await db.scalars(
                    select(LeaveRequestDay.paid).where(
                        LeaveRequestDay.leave_request_id == sick.id
                    )
                )
            )
            assert sick_days == [False, False]

            # Zgoda na przekierowanie z wpisu za pracownika — bez zgody.
            entered = await db.get(LeaveRequest, uuid.UUID(on_behalf["id"]))
            assert entered.forward_mail_consent is False
            assert entered.created_by == boss.id

            # Anulowany wniosek na te same dni — dni nieaktywne, bez konfliktu.
            cancelled = await db.get(LeaveRequest, uuid.UUID(cancelled_same_days["id"]))
            cancelled_active = await db.scalar(
                select(LeaveRequestDay.active).where(
                    LeaveRequestDay.leave_request_id == cancelled.id
                )
            )
            assert cancelled_active is False

            assert await db.get(LeaveRequest, uuid.UUID(overlapping["id"])) is None
            assert await db.get(LeaveRequest, uuid.UUID(clash_native["id"])) is None

            # Bez operacji Microsoft 365 i bez powiadomień.
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(HrM365Operation)
                    .where(HrM365Operation.user_id.in_([worker.id, contractor.id]))
                )
                == 0
            )
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(Notification)
                    .where(
                        Notification.user_id.in_([worker.id, boss.id, contractor.id])
                    )
                )
                == 0
            )
            mapped = await db.scalar(
                select(HrImportIdMap).where(
                    HrImportIdMap.module == "leave",
                    HrImportIdMap.source_id == f"leave_requests:{uop['id']}",
                )
            )
            assert mapped.target_id == uop["id"]

            # Drugi zapis tej samej paczki: same „bez zmian”.
            batch2, _ = await compass_import.dry_run(
                db,
                module="leave",
                bundle=bundle,
                planner=importer.plan,
                actor_user_id=None,
            )
            assert batch2.report["dry_run"]["counts"] == {
                "unchanged": 5,
                "conflict": 2,
                "skip": 1,
            }
            written2 = await compass_import.apply(
                db,
                batch=batch2,
                bundle=bundle,
                planner=importer.plan,
                applier=importer.apply,
                actor_user_id=None,
            )
            assert written2 == {
                "requests_created": 0,
                "requests_updated": 0,
                "days_written": 0,
                "conflicts_at_write": 0,
            }
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_leave_dry_run_writes_nothing() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        try:
            _, w_id, w_row = await make_person(db, f"{tag}-worker")
            row = leave_row(w_id, "2026-06-01", "2026-06-02")
            bundle = make_bundle({"profiles": [w_row], "leave_requests": [row]})
            importer = compass_import.IMPORTERS["leave"]
            batch, plan = await compass_import.dry_run(
                db,
                module="leave",
                bundle=bundle,
                planner=importer.plan,
                actor_user_id=None,
            )
            assert plan.counts() == {"create": 1}
            assert batch.status == "dry_run"
            assert await db.get(LeaveRequest, uuid.UUID(row["id"])) is None
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(HrImportIdMap)
                    .where(HrImportIdMap.source_id == f"leave_requests:{row['id']}")
                )
                == 0
            )
        finally:
            await db.rollback()


def test_contractor_paid_days_follow_compass_split_in_day_order() -> None:
    from app.services.hr.calendar import WorkCalendar

    days = leave_import.plan_request_days(
        WorkCalendar(),
        start=date(2026, 3, 9),
        end=date(2026, 3, 13),
        half_day=None,
        leave_type="vacation",
        employment_type="zlecenie",
        compass_paid_days=Decimal("2.5"),
    )
    # Pół dnia puli nie dzieli dnia: trzeci dzień idzie jako bezpłatny.
    assert [paid for _, _, paid in days] == [True, True, False, False, False]
    paid, unpaid = leave_import.split_totals(
        days, leave_type="vacation", employment_type="zlecenie"
    )
    assert (paid, unpaid) == (Decimal("2.0"), Decimal("3.0"))
    # Rodzaj spoza puli nigdy nie jest „płatny z puli”.
    other = leave_import.plan_request_days(
        WorkCalendar(),
        start=date(2026, 3, 9),
        end=date(2026, 3, 9),
        half_day="morning",
        leave_type="childcare",
        employment_type="uop",
        compass_paid_days=Decimal("1"),
    )
    assert other == [(date(2026, 3, 9), Decimal("0.5"), False)]


# ── Wiersz poleceń ───────────────────────────────────────────────────────────


def _cli_module():
    path = Path(__file__).resolve().parent.parent / "scripts" / "hr_compass_import.py"
    spec = importlib.util.spec_from_file_location("hr_compass_import_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("module", sorted(compass_import.IMPORTERS))
def test_cli_accepts_every_registered_module(
    module: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    cli = _cli_module()
    bad = tmp_path / "paczka.json"
    bad.write_text(json.dumps({"format": "inny", "version": 1, "tables": {}}))
    monkeypatch.setattr(
        sys, "argv", ["hr_compass_import.py", "--bundle", str(bad), "--module", module]
    )
    # Moduł przeszedł przez argparse; odmowa przyszła dopiero z walidacji paczki.
    assert cli.main() == 2
    assert "To nie jest paczka eksportu Compassa." in capsys.readouterr().err


def test_cli_refuses_unknown_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = _cli_module()
    monkeypatch.setattr(
        sys,
        "argv",
        ["hr_compass_import.py", "--bundle", str(tmp_path / "x.json"), "--module", "x"],
    )
    with pytest.raises(SystemExit) as refused:
        cli.main()
    assert refused.value.code == 2


def test_importers_follow_dependency_order() -> None:
    assert list(compass_import.IMPORTERS) == [
        "profiles",
        "leave",
        "time",
        "payroll",
        "lifecycle",
        "cases",
        "care",
    ]
