"""Przywrócenie wygasłych zgód jednorazowych bez dokumentu (decyzja 23.10.2026).

Do 22.10.2026 `settlement.expire_stale` zamykał po 30 dniach także zgodę
„raz” bez faktury i paragonu (status rozliczenia ``expired``). Od F21 taka
zgoda nie wygasa; narzędzie przywraca te, które zdążyły wygasnąć, do stanu
sprzed wygaśnięcia (``open``, bez ``expires_on``). Dane syntetyczne.
"""

from __future__ import annotations

import json
import uuid
from collections import namedtuple
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import delete, select, text

from app.cli import hr_one_off_expiry_restore as script

REPORT_SQL = (
    Path(__file__).resolve().parents[1] / "scripts" / "hr_one_off_expired_report.sql"
)


def test_report_sql_is_read_only_and_carries_no_personal_columns() -> None:
    sql = REPORT_SQL.read_text(encoding="utf-8")
    assert sql.splitlines()[0] == "SET default_transaction_read_only = on;"
    body = "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    ).lower()
    for statement in ("insert ", "update ", "delete ", "alter ", "drop "):
        assert statement not in body
    # Repo i logi są publiczne: bez tytułu, celu, kwot i osób.
    for column in ("title", "purpose", "amount", "requester_user_id", ".name"):
        assert column not in body
    assert "approval_expired" in body
    assert "recurrence = 'once'" in body


def _item(rid: int, month, *, event: bool = True, doc: bool = False):
    return script.Item(
        request_id=rid, expired_month=month, has_expiry_event=event, has_document=doc
    )


def test_summary_splits_reasons_and_months_without_personal_data() -> None:
    report = script.summarize(
        [
            _item(3, "2026-10"),
            _item(1, "2026-09"),
            _item(2, "2026-10"),
            _item(4, "2026-10", doc=True),
            _item(5, None, event=False),
        ]
    )
    assert report["found"] == 5
    assert report["restorable"] == 3
    assert report["restorable_by_expiry_month"] == {"2026-09": 1, "2026-10": 2}
    assert report["request_ids"] == [1, 2, 3]
    assert report["skipped_with_document"] == [4]
    assert report["skipped_without_expiry_event"] == [5]
    assert set(report) == {
        "found",
        "restorable",
        "restorable_by_expiry_month",
        "request_ids",
        "skipped_with_document",
        "skipped_without_expiry_event",
    }


def test_restored_state_follows_rule_f21() -> None:
    """Zgoda „raz” po zatwierdzeniu jest ``open`` i nie ma terminu."""

    assert script.RESTORED_STATUS == "open"
    assert script.EXPIRED_ACTION == "approval_expired"


@pytest.mark.asyncio
async def test_apply_without_expected_is_refused_before_touching_database(
    capsys,
) -> None:
    assert await script.main(["--apply"]) == 2
    assert "--expected" in capsys.readouterr().err


class _FakeDb:
    """Sesja bez bazy: zwraca wiersze zgód pod blokadą i zbiera zapisy."""

    def __init__(self, rows) -> None:
        self.rows = rows
        self.statements: list = []
        self.added: list = []

    async def execute(self, stmt, *args):
        self.statements.append(stmt)
        result = MagicMock()
        result.all = lambda: list(self.rows)
        return result

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


Row = namedtuple("Row", "id requester_user_id expires_on")


@pytest.mark.asyncio
async def test_restore_clears_expiry_and_records_history_without_database() -> None:
    from sqlalchemy.dialects import postgresql

    db = _FakeDb([Row(7, 70, date(2026, 9, 19))])
    restored = await script.restore(
        db, [_item(7, "2026-10"), _item(8, None, event=False)]
    )
    assert restored == [7]
    locked, updated = db.statements
    assert locked._for_update_arg is not None
    sql = str(updated.compile(dialect=postgresql.dialect()))
    assert "settlement_status=" in sql and "expires_on=" in sql
    params = updated.compile(dialect=postgresql.dialect()).params
    assert params["settlement_status"] == "open"
    assert params["expires_on"] is None
    (event,) = db.added
    assert (event.action, event.entity_id, event.subject_user_id) == (
        "approval_expiry_reverted",
        "7",
        70,
    )
    assert event.details["expires_on_cleared"] == "2026-09-19"


@pytest.mark.asyncio
async def test_restore_stops_when_state_changed_since_plan() -> None:
    db = _FakeDb([])  # zgoda 7 nie jest już „expired”
    with pytest.raises(script.StateChanged):
        await script.restore(db, [_item(7, "2026-10")])
    assert len(db.statements) == 1 and db.added == []


# ── z bazą ──────────────────────────────────────────────────────────────────


async def _seed(db, tag: str) -> dict[str, int]:
    from app.models.hr_approval import ApprovalRequest
    from app.models.hr_ops import HrAuditEvent
    from app.models.user import User, UserRole

    author = User(
        email=f"restore-author-{tag}@example.com",
        name="Synthetic author",
        role=UserRole.employee,
        roles=["employee"],
        is_active=True,
    )
    boss = User(
        email=f"restore-boss-{tag}@example.com",
        name="Synthetic approver",
        role=UserRole.admin,
        roles=["admin"],
        is_active=True,
    )
    db.add_all([author, boss])
    await db.flush()
    decided = datetime(2026, 8, 20, 9, tzinfo=timezone.utc)

    def request(recurrence: str, settlement: str, kind: str = "training"):
        return ApprovalRequest(
            kind=kind,
            status="approved",
            title="Szkolenie",
            purpose="Syntetyczny wydatek",
            amount=Decimal("300.00"),
            recurrence=recurrence,
            requester_user_id=author.id,
            decided_by=boss.id,
            decided_at=decided,
            settlement_status=settlement,
            expires_on=datetime(2026, 9, 19).date(),
        )

    restorable = request("once", "expired")
    no_event = request("once", "expired")
    monthly = request("monthly", "expired", kind="subscription")
    still_open = request("once", "open")
    db.add_all([restorable, no_event, monthly, still_open])
    await db.flush()
    for row in (restorable, monthly):
        db.add(
            HrAuditEvent(
                actor_user_id=None,
                subject_user_id=author.id,
                entity_type="approval_request",
                entity_id=str(row.id),
                action="approval_expired",
                details={"days": 30},
                # 30.09 23:30 UTC = 01.10 w czasie firmy.
                created_at=datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc),
            )
        )
    await db.commit()
    return {
        "restorable": restorable.id,
        "no_event": no_event.id,
        "monthly": monthly.id,
        "still_open": still_open.id,
    }


@pytest.mark.asyncio
async def test_plan_picks_only_one_off_requests_expired_by_the_old_rule() -> None:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        ids = await _seed(db, uuid.uuid4().hex[:10])
        items = await script.plan(db, request_ids=list(ids.values()))
    report = script.summarize(items)
    assert report["request_ids"] == [ids["restorable"]]
    assert report["restorable_by_expiry_month"] == {"2026-10": 1}
    assert report["skipped_without_expiry_event"] == [ids["no_event"]]
    assert report["found"] == 2  # cykliczna i otwarta nie wchodzą


@pytest.mark.asyncio
async def test_apply_restores_once_writes_history_and_receipt(
    monkeypatch, capsys
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.hr_approval import ApprovalRequest
    from app.models.hr_ops import HrAuditEvent

    key = f"test_hr_one_off_expiry_restore_{uuid.uuid4().hex[:10]}"
    monkeypatch.setattr(script, "RECEIPT_KEY", key)
    async with AsyncSessionLocal() as db:
        ids = await _seed(db, uuid.uuid4().hex[:10])
    scope = list(ids.values())
    try:
        # Próba na sucho niczego nie zmienia.
        assert await script.main([], request_ids=scope) == 0
        # Inna liczba niż w próbie przerywa bieg przed zapisem.
        assert await script.main(["--apply", "--expected", "2"], request_ids=scope) == 2
        async with AsyncSessionLocal() as db:
            row = await db.get(ApprovalRequest, ids["restorable"])
            assert row.settlement_status == "expired"
        capsys.readouterr()

        assert await script.main(["--apply", "--expected", "1"], request_ids=scope) == 0
        printed = capsys.readouterr().out
        receipt_line = json.loads(printed.strip().splitlines()[-1])
        assert receipt_line["restored"] == 1
        assert receipt_line["request_ids"] == [ids["restorable"]]
        assert "Szkolenie" not in printed and "Syntetyczny" not in printed

        async with AsyncSessionLocal() as db:
            restored = await db.get(ApprovalRequest, ids["restorable"])
            assert (restored.settlement_status, restored.expires_on) == ("open", None)
            for other in ("no_event", "monthly"):
                assert (
                    await db.get(ApprovalRequest, ids[other])
                ).settlement_status == ("expired")
            trail = (
                await db.scalars(
                    select(HrAuditEvent).where(
                        HrAuditEvent.entity_type == "approval_request",
                        HrAuditEvent.entity_id == str(ids["restorable"]),
                        HrAuditEvent.action == script.RESTORED_ACTION,
                    )
                )
            ).all()
            assert len(trail) == 1
            assert trail[0].details["from"] == "expired"
            assert trail[0].details["to"] == "open"
            assert trail[0].details["expires_on_cleared"] == "2026-09-19"
            receipt = await db.scalar(
                text("SELECT value FROM app_settings WHERE key = :k"), {"k": key}
            )
            assert receipt["restored"] == 1

        # Paragon blokuje ponowne --apply.
        assert await script.main(["--apply", "--expected", "0"], request_ids=scope) == 2
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("DELETE FROM app_settings WHERE key = :k"), {"k": key}
            )
            await db.execute(
                delete(HrAuditEvent).where(
                    HrAuditEvent.entity_type == "approval_request",
                    HrAuditEvent.entity_id.in_([str(i) for i in scope]),
                )
            )
            await db.commit()
