"""Uzgadnianie skrzynek o 7:00 na ``FakeMailboxOps`` (bez sieci).

Brakująca autoodpowiedź trwającego urlopu wraca, wyłączona przez osobę nie
wraca, reguły po urlopie i sieroty (NEXUSA i Compassa) są zamykane, reguła
Compassa trwającego urlopu przejmowana, brakująca otwierana; drugi przebieg
tego samego dnia nic nie robi. Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.models.hr_leave import HrM365MailboxState, HrM365Operation
from app.models.hr_profile import EmployeeProfile
from app.services.hr.m365 import executor, oof_state, oof_template, reconcile
from tests.hr.fakes import FakeMailboxOps
from tests.hr.m365_helpers import (
    at,
    make_due,
    make_leave,
    make_user,
    of_kind,
    operations,
    plan,
    reset_reconcile_runs,
)

D = date


async def test_missing_oof_of_running_leave_is_enqueued_once_a_day() -> None:
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        await reset_reconcile_runs(db)
        user = await make_user(db)
        # Urlop z importu: zatwierdzony w Compassie, w NEXUSIE bez operacji.
        leave = await make_leave(
            db, user, D(2026, 10, 19), D(2026, 10, 23), source="compass_import"
        )
        await db.commit()

        early = await reconcile.run_once(
            db,
            ops=fake,
            mode="live",
            now=at(D(2026, 10, 20), 6, 55),
            user_ids=[user.id],
        )
        assert early["skipped"] == "before_07"
        assert await operations(db, user.id) == []

        now = at(D(2026, 10, 20), 7, 5)
        first = await reconcile.run_once(
            db, ops=fake, mode="live", now=now, user_ids=[user.id]
        )
        second = await reconcile.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 20), 15), user_ids=[user.id]
        )
        ops = await operations(db, user.id)
        state = await db.get(HrM365MailboxState, user.id)

    assert first["oof_enqueued"] == 1
    assert second == {"mode": "live", "skipped": "already_ran"}
    (set_oof,) = ops
    assert set_oof.kind == "set_oof"
    assert set_oof.dedupe_key == f"leave:{leave.id}:set_oof:reconcile:2026-10-20"
    assert set_oof.payload["start"] == "2026-10-19"
    assert set_oof.payload["return_on"] == "2026-10-26"
    assert state.last_reconciled_at == now
    assert fake.writes == []  # uzgadnianie samo nie pisze w skrzynce


async def test_oof_turned_off_by_the_person_or_custom_is_left_alone() -> None:
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        await reset_reconcile_runs(db)
        returned_early = await make_user(db)
        own_text = await make_user(db)
        overwritten = await make_user(db)
        for person in (returned_early, own_text, overwritten):
            leave = await make_leave(db, person, D(2026, 10, 19), D(2026, 10, 23))
            await plan(db, leave, "approved", today=D(2026, 10, 15))
        await db.execute(
            update(HrM365Operation)
            .where(
                HrM365Operation.user_id.in_(
                    [returned_early.id, own_text.id, overwritten.id]
                ),
            )
            .values(status="done")
        )
        await db.commit()
        # Osoba wróciła wcześniej i sama wyłączyła autoodpowiedź.
        fake.set_oof(returned_early.email, {"status": "disabled"})
        fake.set_oof(
            own_text.email,
            {"status": "alwaysEnabled", "internalReplyMessage": "<p>Mój</p>"},
        )
        # Nasza autoodpowiedź innego okna (np. nadpisana przez wcześniejszy urlop).
        fake.set_oof(
            overwritten.email,
            oof_template.schedule_setting(
                start=D(2026, 10, 12),
                end=D(2026, 10, 16),
                internal_html="a",
                external_html="b",
            ),
        )
        people = [returned_early.id, own_text.id, overwritten.id]
        await reconcile.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 20), 7, 30), user_ids=people
        )
        added = {
            person: [
                op
                for op in await operations(db, person)
                if ":reconcile:" in op.dedupe_key
            ]
            for person in people
        }

    assert added[returned_early.id] == []
    assert added[own_text.id] == []
    assert [op.kind for op in added[overwritten.id]] == ["set_oof"]


async def test_rules_after_leave_and_orphans_are_closed_and_compass_rule_taken_over() -> (
    None
):
    fake = FakeMailboxOps()
    orphan_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        await reset_reconcile_runs(db)
        substitute = await make_user(db, name="Ola Zastępca")
        user = await make_user(db)
        ended = await make_leave(
            db,
            user,
            D(2026, 10, 12),
            D(2026, 10, 16),
            substitute=substitute,
            consent=True,
        )
        running = await make_leave(
            db,
            user,
            D(2026, 10, 19),
            D(2026, 10, 23),
            substitute=substitute,
            consent=True,
            source="compass_import",
        )
        # Druga osoba: trwający urlop ze zgodą, a reguły brak.
        other = await make_user(db)
        missing = await make_leave(
            db,
            other,
            D(2026, 10, 19),
            D(2026, 10, 22),
            substitute=substitute,
            consent=True,
        )
        await db.commit()
        fake.add_rule(user.email, f"NEXUS · zastępstwo · {ended.id}")
        fake.add_rule(user.email, f"COMPASS · zastępstwo · {orphan_id}")
        own = fake.add_rule(user.email, "Faktury do folderu")
        compass_rule = fake.add_rule(user.email, f"COMPASS · zastępstwo · {running.id}")
        fake.set_oof(
            user.email,
            {
                **oof_template.schedule_setting(
                    start=running.start_date,
                    end=running.end_date,
                    internal_html="x",
                    external_html="y",
                ),
                "internalReplyMessage": f"{oof_state.COMPASS_OOF_MARKER}<p>x</p>",
                "externalReplyMessage": f"{oof_state.COMPASS_OOF_MARKER}<p>y</p>",
            },
        )

        now = at(D(2026, 10, 20), 7, 15)
        counts = await reconcile.run_once(
            db, ops=fake, mode="live", now=now, user_ids=[user.id, other.id]
        )
        user_ops = await operations(db, user.id)
        other_ops = await operations(db, other.id)

        assert counts["forward_close_enqueued"] == 2
        assert counts["forward_takeover"] == 1
        assert counts["forward_open_enqueued"] == 1
        closes = {
            op.payload["reason"]: op for op in of_kind(user_ops, "forward_rule_close")
        }
        assert closes["ended"].leave_request_id == ended.id
        assert closes["orphan"].leave_request_id is None
        assert closes["orphan"].payload["leave_id"] == orphan_id
        (takeover,) = of_kind(user_ops, "forward_rule_open")
        assert takeover.dedupe_key == f"leave:{running.id}:forward_rule_open:takeover"
        # Autoodpowiedź Compassa trwającego urlopu jest „nasza” — bez nowej operacji.
        assert of_kind(user_ops, "set_oof") == []
        (opening,) = of_kind(other_ops, "forward_rule_open")
        assert opening.leave_request_id == missing.id

        await make_due(db, [user.id, other.id])
        await db.commit()
        await executor.run_once(
            db,
            ops=fake,
            mode="live",
            now=at(D(2026, 10, 20), 7, 20),
            user_ids=[user.id, other.id],
        )

    rules = fake.rules[user.email.lower()]
    assert set(rules) == {own, compass_rule}
    assert rules[compass_rule]["displayName"] == f"NEXUS · zastępstwo · {running.id}"
    assert (
        rules[compass_rule]["actions"]["forwardTo"][0]["emailAddress"]["address"]
        == substitute.email
    )
    (other_rule,) = fake.rules[other.email.lower()].values()
    assert other_rule["displayName"] == f"NEXUS · zastępstwo · {missing.id}"


async def test_read_error_concludes_nothing_and_is_recorded() -> None:
    fake = FakeMailboxOps()
    fake.fail_always("list_rules", 403)
    async with AsyncSessionLocal() as db:
        await reset_reconcile_runs(db)
        user = await make_user(db)
        await make_leave(
            db, user, D(2026, 10, 19), D(2026, 10, 23), source="compass_import"
        )
        await db.commit()
        counts = await reconcile.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 20), 8), user_ids=[user.id]
        )
        state = await db.get(HrM365MailboxState, user.id)
        ops = await operations(db, user.id)

    assert counts["read_errors"] == 1
    assert state.last_error == "forbidden (403)"
    assert state.last_reconciled_at is None
    assert [op.kind for op in ops] == ["set_oof"]  # odczyt autoodpowiedzi się udał


async def test_simulated_reconcile_does_not_repeat_itself_the_next_day() -> None:
    async with AsyncSessionLocal() as db:
        await reset_reconcile_runs(db)
        user = await make_user(db)
        await make_leave(
            db, user, D(2026, 10, 19), D(2026, 10, 23), source="compass_import"
        )
        await db.commit()
        await reconcile.run_once(
            db, mode="simulate", now=at(D(2026, 10, 20), 7, 1), user_ids=[user.id]
        )
        await make_due(db, [user.id])
        await db.commit()
        await executor.run_once(
            db, mode="simulate", now=at(D(2026, 10, 20), 7, 2), user_ids=[user.id]
        )
        await reconcile.run_once(
            db, mode="simulate", now=at(D(2026, 10, 21), 7, 1), user_ids=[user.id]
        )
        ops = await operations(db, user.id)
        state = await db.get(HrM365MailboxState, user.id)

    assert [(op.kind, op.status) for op in ops] == [("set_oof", "simulated")]
    assert state is None  # symulacja nie zapisuje stanu skrzynki


async def _leaver(db, *, active: bool, profile: bool):
    """Osoba po odejściu: konto wyłączone i/albo kartoteka ``exited``."""

    user = await make_user(db, profile=profile)
    user.is_active = active
    if profile:
        await db.execute(
            update(EmployeeProfile)
            .where(EmployeeProfile.user_id == user.id)
            .values(employment_status="exited")
        )
    return user


@pytest.mark.parametrize(
    ("active", "profile"),
    [(False, True), (True, True), (False, False)],
    ids=["inactive_exited", "active_exited", "inactive_no_profile"],
)
async def test_leave_owner_who_left_is_skipped_not_read(active, profile) -> None:
    # Prod 19.10.2026: urlop z Compassa osoby, która odeszła — skrzynka poza
    # grupą aplikacji, odczyt = 403 i fałszywy „błąd odczytu” co rano.
    fake = FakeMailboxOps()
    fake.fail_always("get_auto_replies", 403)
    fake.fail_always("list_rules", 403)
    async with AsyncSessionLocal() as db:
        await reset_reconcile_runs(db)
        leaver = await _leaver(db, active=active, profile=profile)
        await make_leave(
            db, leaver, D(2026, 10, 16), D(2026, 10, 19), source="compass_import"
        )
        await db.commit()
        counts = await reconcile.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 19), 8), user_ids=[leaver.id]
        )
        ops = await operations(db, leaver.id)
        state = await db.get(HrM365MailboxState, leaver.id)

    assert counts.get("read_errors", 0) == 0
    assert counts.get("mailboxes", 0) == 0
    assert counts["skipped_exited"] == 1
    assert fake.calls == []
    assert ops == []
    assert state is None


async def test_leave_owner_without_profile_still_gets_reconciled() -> None:
    # Właściciel urlopu spoza kartoteki (aktywne konto) to celowy wyjątek.
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        await reset_reconcile_runs(db)
        user = await make_user(db, profile=False)
        await make_leave(
            db, user, D(2026, 10, 19), D(2026, 10, 23), source="compass_import"
        )
        await db.commit()
        counts = await reconcile.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 20), 8), user_ids=[user.id]
        )
        ops = await operations(db, user.id)

    assert counts["mailboxes"] == 1
    assert "skipped_exited" not in counts
    assert [op.kind for op in ops] == ["set_oof"]
