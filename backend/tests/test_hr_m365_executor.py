"""Wykonawca kolejki Microsoft 365 na ``FakeMailboxOps`` (bez sieci).

Własna autoodpowiedź zostaje, autoodpowiedź Compassa jest przejmowana,
trwający urlop nie traci swojej, okno w strefie Warszawy, przekierowanie
otwierane pierwszego dnia i zamykane po ostatnim, godziny połówki przy
zmianie, ponowienia po 403, tryby ``off`` / ``simulate`` / ``live`` z listą
skrzynek i rezerwacja bez podwójnego wykonania. Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import select, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_day_start_utc
from app.models.hr_leave import HrM365MailboxState, HrM365Operation
from app.services.hr.leave_policy import LEAVE_TYPE_LABELS
from app.services.hr.m365 import executor, oof_state, oof_template, outbox
from tests.hr.fakes import FakeMailboxOps
from tests.hr.m365_helpers import (
    at,
    make_due,
    make_leave,
    make_user,
    of_kind,
    operations,
    plan,
)

D = date


def _setting_written(fake: FakeMailboxOps, upn: str) -> list[dict]:
    return [
        body
        for name, box, body in fake.writes
        if name == "set_auto_replies" and box == upn.lower()
    ]


async def _state(user_id: int) -> HrM365MailboxState | None:
    async with AsyncSessionLocal() as check:
        return await check.get(HrM365MailboxState, user_id)


# ── Autoodpowiedź ─────────────────────────────────────────────────────────────


async def test_user_custom_oof_is_kept_skipped_and_flagged() -> None:
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        user = await make_user(db)
        leave = await make_leave(db, user, D(2026, 11, 2), D(2026, 11, 6))
        await plan(db, leave, "approved", today=D(2026, 10, 20))
        await make_due(db, [user.id])
        await db.commit()
        fake.set_oof(
            user.email,
            {"status": "alwaysEnabled", "internalReplyMessage": "<p>Mój tekst</p>"},
        )

        result = await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 20)), user_ids=[user.id]
        )
        ops = await operations(db, user.id)

    (set_oof,) = of_kind(ops, "set_oof")
    assert set_oof.status == "skipped"
    assert set_oof.last_error == "user_custom"
    assert _setting_written(fake, user.email) == []
    assert (
        fake.auto_replies[user.email.lower()]["internalReplyMessage"]
        == "<p>Mój tekst</p>"
    )
    assert (await _state(user.id)).custom_oof_detected is True
    assert result["skipped"] == 1


async def test_compass_oof_is_taken_over_and_cleared_on_cancel() -> None:
    fake = FakeMailboxOps()
    compass_window = oof_template.schedule_setting(
        start=D(2026, 11, 2),
        end=D(2026, 11, 6),
        internal_html="<p>x</p>",
        external_html="<p>x</p>",
    )
    compass_setting = {
        **compass_window,
        "internalReplyMessage": f"{oof_state.COMPASS_OOF_MARKER}\n<p>Compass</p>",
        "externalReplyMessage": f"{oof_state.COMPASS_OOF_MARKER}\n<p>Compass</p>",
    }
    async with AsyncSessionLocal() as db:
        # (a) urlop z importu, autoodpowiedź Compassa — NEXUS ustawia swoją.
        taken = await make_user(db)
        leave = await make_leave(
            db, taken, D(2026, 11, 2), D(2026, 11, 6), source="compass_import"
        )
        await plan(db, leave, "approved", today=D(2026, 10, 20))
        # (b) urlop z importu anulowany w NEXUSIE — znika autoodpowiedź Compassa.
        cancelled_owner = await make_user(db)
        cancelled = await make_leave(
            db, cancelled_owner, D(2026, 11, 2), D(2026, 11, 6), source="compass_import"
        )
        cancelled.status = "cancelled"
        await plan(db, cancelled, "cancelled", today=D(2026, 10, 20))
        await make_due(db, [taken.id, cancelled_owner.id])
        await db.commit()
        fake.set_oof(taken.email, compass_setting)
        fake.set_oof(cancelled_owner.email, compass_setting)

        await executor.run_once(
            db,
            ops=fake,
            mode="live",
            now=at(D(2026, 10, 20)),
            user_ids=[taken.id, cancelled_owner.id],
        )
        taken_ops = await operations(db, taken.id)
        cancelled_ops = await operations(db, cancelled_owner.id)

    assert of_kind(taken_ops, "set_oof")[0].status == "done"
    (written,) = _setting_written(fake, taken.email)
    assert written["internalReplyMessage"].startswith(oof_state.NEXUS_OOF_MARKER)
    assert oof_state.COMPASS_OOF_MARKER not in written["internalReplyMessage"]

    (clear,) = of_kind(cancelled_ops, "clear_oof")
    assert clear.status == "done"
    assert fake.auto_replies[cancelled_owner.email.lower()]["status"] == "disabled"


async def test_running_oof_of_other_leave_defers_until_it_ends() -> None:
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        user = await make_user(db)
        running = await make_leave(db, user, D(2026, 10, 19), D(2026, 10, 23))
        later = await make_leave(db, user, D(2026, 10, 26), D(2026, 10, 30))
        await plan(db, later, "approved", today=D(2026, 10, 20))
        await make_due(db, [user.id])
        await db.commit()
        fake.set_oof(
            user.email,
            oof_template.schedule_setting(
                start=running.start_date,
                end=running.end_date,
                internal_html="<p>a</p>",
                external_html="<p>b</p>",
            ),
        )

        await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 20)), user_ids=[user.id]
        )
        (deferred,) = of_kind(await operations(db, user.id), "set_oof")
        assert deferred.status == "pending"
        assert deferred.last_error == "other_leave_oof"
        assert deferred.attempts == 0
        assert deferred.next_attempt_at == local_day_start_utc(D(2026, 10, 24))
        assert _setting_written(fake, user.email) == []

        # Po północy kończącej trwający urlop — autoodpowiedź późniejszego.
        await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 24), 0, 5), user_ids=[user.id]
        )
        (done,) = of_kind(await operations(db, user.id), "set_oof")

    assert done.status == "done"
    current = await fake.get_auto_replies(user.email)
    assert oof_state.matches_leave(current, D(2026, 10, 26), D(2026, 10, 30))


async def test_oof_window_across_dst_change_is_set_and_cleared() -> None:
    fake = FakeMailboxOps()  # Graph oddaje harmonogram w UTC
    async with AsyncSessionLocal() as db:
        user = await make_user(db)
        leave = await make_leave(db, user, D(2026, 10, 23), D(2026, 10, 26))
        await plan(db, leave, "approved", today=D(2026, 10, 20))
        await make_due(db, [user.id])
        await db.commit()
        await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 20)), user_ids=[user.id]
        )

        (written,) = _setting_written(fake, user.email)
        assert written["scheduledStartDateTime"]["dateTime"] == "2026-10-23T00:00:00"
        assert written["scheduledEndDateTime"]["dateTime"] == "2026-10-27T00:00:00"
        echoed = await fake.get_auto_replies(user.email)
        assert echoed["scheduledEndDateTime"]["dateTime"].startswith(
            "2026-10-26T23:00:00"
        )

        leave.status = "cancelled"
        await plan(db, leave, "cancelled", today=D(2026, 10, 21))
        await make_due(db, [user.id])
        await db.commit()
        await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 21)), user_ids=[user.id]
        )
        (clear,) = of_kind(await operations(db, user.id), "clear_oof")

    assert clear.status == "done"
    assert fake.auto_replies[user.email.lower()]["status"] == "disabled"


async def test_oof_text_hides_absence_type_and_falls_back_to_manager_then_office(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "ADMIN_CASES_MAILBOX", "biuro@example.com")
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        boss = await make_user(db, name="Jan Przełożony")
        sick = await make_user(db, name="Anna Przykładowa", manager_user_id=boss.id)
        alone = await make_user(db, name="Ewa Samodzielna")
        for person in (sick, alone):
            leave = await make_leave(
                db, person, D(2026, 11, 2), D(2026, 11, 6), leave_type="sick_leave"
            )
            await plan(db, leave, "approved", today=D(2026, 10, 30))
        await make_due(db, [sick.id, alone.id])
        await db.commit()
        await executor.run_once(
            db,
            ops=fake,
            mode="live",
            now=at(D(2026, 10, 30)),
            user_ids=[sick.id, alone.id],
        )

    (with_manager,) = _setting_written(fake, sick.email)
    (with_office,) = _setting_written(fake, alone.email)
    for setting in (with_manager, with_office):
        text = (
            setting["internalReplyMessage"] + setting["externalReplyMessage"]
        ).lower()
        for label in LEAVE_TYPE_LABELS.values():
            assert label.lower() not in text
        assert "l4" not in text and "chorob" not in text and "sick" not in text
        assert "9 listopada 2026" in setting["internalReplyMessage"]
    assert "Jan Przełożony" in with_manager["internalReplyMessage"]
    assert "mailto:biuro@example.com" in with_office["internalReplyMessage"]


async def test_late_clear_does_not_remove_oof_of_a_new_leave_in_the_same_days() -> None:
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        user = await make_user(db)
        old = await make_leave(
            db, user, D(2026, 11, 2), D(2026, 11, 6), status="cancelled"
        )
        new = await make_leave(db, user, D(2026, 11, 2), D(2026, 11, 6))
        # Zdjęcie autoodpowiedzi starego wniosku czekało na ponowienie, a nowy
        # wniosek w tych samych dniach już ją ustawił.
        await plan(db, old, "cancelled", today=D(2026, 10, 20))
        await make_due(db, [user.id])
        await db.commit()
        fake.set_oof(
            user.email,
            oof_template.schedule_setting(
                start=new.start_date,
                end=new.end_date,
                internal_html="<p>a</p>",
                external_html="<p>b</p>",
            ),
        )
        await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 21)), user_ids=[user.id]
        )
        (clear,) = of_kind(await operations(db, user.id), "clear_oof")

    assert (clear.status, clear.last_error) == ("skipped", "other_leave_same_window")
    assert fake.auto_replies[user.email.lower()]["status"] == "scheduled"


async def test_cancelled_leave_does_not_get_writes_from_a_late_operation() -> None:
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        user = await make_user(db)
        leave = await make_leave(db, user, D(2026, 11, 2), D(2026, 11, 6))
        await plan(db, leave, "approved", today=D(2026, 10, 20))
        leave.status = "cancelled"
        await make_due(db, [user.id])
        await db.commit()
        await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 20)), user_ids=[user.id]
        )
        ops = await operations(db, user.id)

    assert {op.kind: (op.status, op.last_error) for op in ops} == {
        "set_oof": ("skipped", "leave_not_active"),
        "calendar_event_upsert": ("skipped", "leave_not_active"),
    }
    assert fake.writes == []


# ── Kalendarz ─────────────────────────────────────────────────────────────────


async def test_half_day_event_keeps_hours_after_an_update() -> None:
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        user = await make_user(db)
        leave = await make_leave(
            db, user, D(2026, 11, 4), D(2026, 11, 4), half_day="morning"
        )
        kinds = await plan(db, leave, "approved", today=D(2026, 10, 20))
        assert kinds == ["calendar_event_upsert"]  # pół dnia — bez autoodpowiedzi
        await make_due(db, [user.id])
        await db.commit()
        await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 20)), user_ids=[user.id]
        )

        (event,) = fake.events[user.email.lower()].values()
        assert event["isAllDay"] is False
        assert event["start"]["dateTime"] == "2026-11-04T08:00:00"
        assert event["end"]["dateTime"] == "2026-11-04T12:00:00"
        state = await _state(user.id)
        transaction = f"nexus-leave-{leave.id}"
        assert state.state["events"][transaction] == event["id"]

        # Zmiana połówki — PATCH tego samego wydarzenia, dalej z godzinami.
        await outbox.enqueue(
            db,
            user_id=user.id,
            kind="calendar_event_upsert",
            dedupe_key=f"leave:{leave.id}:calendar_event_upsert:edit-1",
            payload={
                "start": "2026-11-04",
                "end": "2026-11-04",
                "half_day": "afternoon",
                "transaction_id": transaction,
            },
            leave_request_id=leave.id,
        )
        await make_due(db, [user.id])
        await db.commit()
        await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 21)), user_ids=[user.id]
        )

    (updated,) = fake.events[user.email.lower()].values()
    assert updated["id"] == event["id"]
    assert updated["isAllDay"] is False
    assert updated["start"]["dateTime"] == "2026-11-04T12:00:00"
    assert updated["end"]["dateTime"] == "2026-11-04T16:00:00"
    assert [name for name, *_ in fake.writes] == ["create_event", "update_event"]


async def test_lost_create_response_is_recovered_by_transaction_id() -> None:
    """Compass przy 409 (powtórzony ``transactionId``) zostawał bez id wydarzenia
    i nie umiał go potem usunąć — tu wydarzenie jest odszukiwane i zapamiętane."""

    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        user = await make_user(db)
        leave = await make_leave(db, user, D(2026, 11, 2), D(2026, 11, 6))
        transaction = f"nexus-leave-{leave.id}"
        # Poprzednia próba utworzyła wydarzenie, ale odpowiedź zginęła.
        existing = fake.add_event(
            user.email,
            transaction,
            local_day_start_utc(D(2026, 11, 2)),
            local_day_start_utc(D(2026, 11, 7)),
        )
        await plan(db, leave, "approved", today=D(2026, 10, 20))
        await make_due(db, [user.id])
        await db.commit()
        await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 20)), user_ids=[user.id]
        )
        (upsert,) = of_kind(await operations(db, user.id), "calendar_event_upsert")

    assert upsert.status == "done"
    assert len(fake.events[user.email.lower()]) == 1
    assert fake.events[user.email.lower()][existing]["subject"] == "Poza biurem"
    assert (await _state(user.id)).state["events"][transaction] == existing


async def test_calendar_delete_removes_compass_event_and_404_counts_as_done() -> None:
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        user = await make_user(db)
        leave = await make_leave(
            db, user, D(2026, 11, 2), D(2026, 11, 6), source="compass_import"
        )
        fake.add_event(
            user.email,
            f"leave-{leave.id}",
            local_day_start_utc(D(2026, 11, 2)),
            local_day_start_utc(D(2026, 11, 7)),
        )
        # Id zapamiętane, ale osoba usunęła wydarzenie w Outlooku (→ 404).
        await executor.save_mailbox_state(
            db, user.id, events={f"nexus-leave-{leave.id}": "event-gone"}
        )
        leave.status = "cancelled"
        await plan(db, leave, "cancelled", today=D(2026, 10, 20))
        await make_due(db, [user.id])
        await db.commit()
        await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 20)), user_ids=[user.id]
        )
        (delete,) = of_kind(await operations(db, user.id), "calendar_event_delete")

    assert delete.status == "done"
    assert fake.events[user.email.lower()] == {}
    assert (await _state(user.id)).state["events"] == {}


# ── Przekierowanie ────────────────────────────────────────────────────────────


async def test_forward_rule_opens_on_first_day_and_closes_after_last_day(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "SSO_ALLOWED_DOMAINS", "example.com")
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        substitute = await make_user(db, name="Ola Zastępca")
        user = await make_user(db)
        leave = await make_leave(
            db,
            user,
            D(2026, 11, 2),
            D(2026, 11, 6),
            substitute=substitute,
            consent=True,
        )
        await plan(db, leave, "approved", today=D(2026, 10, 20))
        await make_due(db, [user.id])
        await db.commit()

        # Akceptacja z wyprzedzeniem — poczta jeszcze nie płynie.
        await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 20)), user_ids=[user.id]
        )
        (opening,) = of_kind(await operations(db, user.id), "forward_rule_open")
        assert opening.status == "pending"
        assert opening.last_error == "waiting_for_window"
        assert opening.next_attempt_at == local_day_start_utc(D(2026, 11, 2))
        assert fake.rules[user.email.lower()] == {}

        await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 11, 2), 0, 1), user_ids=[user.id]
        )
        (rule,) = fake.rules[user.email.lower()].values()
        assert rule["displayName"] == f"NEXUS · zastępstwo · {leave.id}"
        assert (
            rule["actions"]["forwardTo"][0]["emailAddress"]["address"]
            == substitute.email
        )
        assert rule["exceptions"]["senderContains"][0] == "@example.com"
        ops = await operations(db, user.id)
        assert of_kind(ops, "forward_rule_open")[0].status == "done"
        (closing,) = of_kind(ops, "forward_rule_close")
        assert closing.status == "pending"
        assert closing.next_attempt_at == local_day_start_utc(D(2026, 11, 7))

        # Ostatni dzień urlopu — reguła jeszcze działa.
        await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 11, 6), 18), user_ids=[user.id]
        )
        assert len(fake.rules[user.email.lower()]) == 1

        await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 11, 7), 0, 1), user_ids=[user.id]
        )
        (closed,) = of_kind(await operations(db, user.id), "forward_rule_close")

    assert closed.status == "done"
    assert fake.rules[user.email.lower()] == {}


async def test_forward_close_removes_compass_rule_and_keeps_own_rules() -> None:
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        substitute = await make_user(db)
        user = await make_user(db)
        leave = await make_leave(
            db,
            user,
            D(2026, 10, 19),
            D(2026, 10, 23),
            substitute=substitute,
            consent=True,
            source="compass_import",
        )
        fake.add_rule(user.email, f"COMPASS · zastępstwo · {leave.id}")
        own = fake.add_rule(user.email, "Faktury do folderu")
        leave.status = "cancelled"
        await plan(db, leave, "cancelled", today=D(2026, 10, 20))
        await make_due(db, [user.id])
        await db.commit()
        await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 20)), user_ids=[user.id]
        )
        (closing,) = of_kind(await operations(db, user.id), "forward_rule_close")

    assert closing.status == "done"
    assert list(fake.rules[user.email.lower()]) == [own]


async def test_forward_open_without_consent_is_skipped() -> None:
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        substitute = await make_user(db)
        user = await make_user(db)
        leave = await make_leave(
            db,
            user,
            D(2026, 10, 19),
            D(2026, 10, 23),
            substitute=substitute,
            consent=True,
        )
        await plan(db, leave, "approved", today=D(2026, 10, 19))
        leave.forward_mail_consent = False  # osoba cofnęła zgodę, zanim kolejka ruszyła
        await make_due(db, [user.id])
        await db.commit()
        await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 20)), user_ids=[user.id]
        )
        (opening,) = of_kind(await operations(db, user.id), "forward_rule_open")

    assert (opening.status, opening.last_error) == ("skipped", "no_consent")
    assert fake.rules[user.email.lower()] == {}


# ── Ponowienia, tryby, rezerwacja ─────────────────────────────────────────────


async def test_forbidden_is_retried_with_backoff_and_fails_after_six_attempts() -> None:
    fake = FakeMailboxOps()
    fake.fail_always("get_auto_replies", 403)
    async with AsyncSessionLocal() as db:
        user = await make_user(db)
        leave = await make_leave(db, user, D(2026, 11, 2), D(2026, 11, 6))
        await plan(db, leave, "approved", today=D(2026, 10, 20))
        await make_due(db, [user.id])
        await db.commit()

        now = at(D(2026, 10, 20))
        expected = [
            timedelta(minutes=5),
            timedelta(minutes=30),
            timedelta(hours=2),
            timedelta(hours=6),
            timedelta(hours=6),
        ]
        for attempt, delay in enumerate(expected, start=1):
            await executor.run_once(
                db, ops=fake, mode="live", now=now, user_ids=[user.id]
            )
            (op,) = of_kind(await operations(db, user.id), "set_oof")
            assert (op.status, op.attempts, op.last_error) == (
                "pending",
                attempt,
                "forbidden (403)",
            )
            assert op.next_attempt_at == now + delay
            now = op.next_attempt_at
        await executor.run_once(db, ops=fake, mode="live", now=now, user_ids=[user.id])
        (op,) = of_kind(await operations(db, user.id), "set_oof")

    assert (op.status, op.attempts) == ("failed", 6)
    assert op.done_at == now
    # Nieudany odczyt to „nie wiadomo”, nie „pusto” — żadnego zapisu na ślepo.
    assert _setting_written(fake, user.email) == []
    assert (await _state(user.id)).last_error == "forbidden (403)"


async def test_simulate_records_exact_requests_and_leaves_mailbox_state_alone() -> None:
    async with AsyncSessionLocal() as db:
        user = await make_user(db, name="Anna Przykładowa")
        leave = await make_leave(db, user, D(2026, 11, 2), D(2026, 11, 6))
        await plan(db, leave, "approved", today=D(2026, 10, 20))
        await make_due(db, [user.id])
        await db.commit()
        result = await executor.run_once(
            db, mode="simulate", now=at(D(2026, 10, 20)), user_ids=[user.id]
        )
        ops = await operations(db, user.id)

    assert result["simulated"] == 2
    path = f"/users/{user.email}"
    (set_oof,) = of_kind(ops, "set_oof")
    assert set_oof.status == "simulated"
    assert set_oof.simulated_request["mailbox"] == user.email
    get, patch = set_oof.simulated_request["requests"]
    assert get == {
        "method": "GET",
        "path": f"{path}/mailboxSettings/automaticRepliesSetting",
    }
    assert patch["method"] == "PATCH" and patch["path"] == f"{path}/mailboxSettings"
    setting = patch["body"]["automaticRepliesSetting"]
    assert setting["scheduledStartDateTime"] == {
        "dateTime": "2026-11-02T00:00:00",
        "timeZone": "Europe/Warsaw",
    }
    assert setting["internalReplyMessage"].startswith(oof_state.NEXUS_OOF_MARKER)
    (event,) = of_kind(ops, "calendar_event_upsert")
    (post,) = event.simulated_request["requests"]
    assert post["method"] == "POST" and post["path"] == f"{path}/events"
    assert post["body"]["transactionId"] == f"nexus-leave-{leave.id}"
    assert post["body"]["subject"] == "Poza biurem"
    assert await _state(user.id) is None


async def test_off_mode_leaves_the_queue_untouched() -> None:
    async with AsyncSessionLocal() as db:
        user = await make_user(db)
        leave = await make_leave(db, user, D(2026, 11, 2), D(2026, 11, 6))
        await plan(db, leave, "approved", today=D(2026, 10, 20))
        await make_due(db, [user.id])
        await db.commit()
        result = await executor.run_once(
            db, mode="off", now=at(D(2026, 10, 20)), user_ids=[user.id]
        )
        ops = await operations(db, user.id)

    assert result == {"status": "disabled"}
    assert {(op.status, op.attempts, op.simulated_request) for op in ops} == {
        ("pending", 0, None)
    }


async def test_live_writes_only_to_allowlisted_mailboxes(monkeypatch) -> None:
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        allowed = await make_user(db)
        other = await make_user(db)
        for person in (allowed, other):
            leave = await make_leave(db, person, D(2026, 11, 2), D(2026, 11, 6))
            await plan(db, leave, "approved", today=D(2026, 10, 20))
        await make_due(db, [allowed.id, other.id])
        await db.commit()
        monkeypatch.setattr(
            settings, "HR_M365_MAILBOX_ALLOWLIST", f" {allowed.email.upper()} ,"
        )
        now = at(D(2026, 10, 20))
        await executor.run_once(
            db, ops=fake, mode="live", now=now, user_ids=[allowed.id, other.id]
        )
        allowed_ops = await operations(db, allowed.id)
        other_ops = await operations(db, other.id)

    assert {op.status for op in allowed_ops} == {"done"}
    assert {(op.status, op.last_error, op.attempts) for op in other_ops} == {
        ("pending", "not_allowlisted", 0)
    }
    assert {op.next_attempt_at for op in other_ops} == {
        now + executor.NOT_ALLOWLISTED_DELAY
    }
    assert all(box != other.email.lower() for _, box in fake.calls)


async def test_two_workers_never_claim_the_same_operation() -> None:
    async with AsyncSessionLocal() as db:
        user = await make_user(db)
        substitute = await make_user(db)
        leave = await make_leave(
            db,
            user,
            D(2026, 11, 2),
            D(2026, 11, 6),
            substitute=substitute,
            consent=True,
        )
        await plan(db, leave, "approved", today=D(2026, 10, 20))
        await make_due(db, [user.id])
        await db.commit()
        ids = [op.id for op in await operations(db, user.id)]
    assert len(ids) == 3
    now = at(D(2026, 10, 20))

    async with AsyncSessionLocal() as first, AsyncSessionLocal() as second:
        locked = (
            await first.execute(
                select(HrM365Operation.id)
                .where(HrM365Operation.id == ids[0])
                .with_for_update()
            )
        ).scalar_one()
        taken_by_second = await executor.claim(second, now, user_ids=[user.id])
        await first.rollback()
        taken_by_first = await executor.claim(first, now, user_ids=[user.id])
        # Dzierżawa trwa — trzeci przebieg nie dostaje niczego.
        taken_again = await executor.claim(
            second, now + timedelta(minutes=1), user_ids=[user.id]
        )

    assert locked not in taken_by_second
    assert sorted(taken_by_second) == sorted(ids[1:])
    assert taken_by_first == [locked]
    assert taken_again == []


async def test_running_operation_returns_after_its_lease_expires() -> None:
    async with AsyncSessionLocal() as db:
        user = await make_user(db)
        leave = await make_leave(db, user, D(2026, 11, 2), D(2026, 11, 6))
        await plan(db, leave, "approved", today=D(2026, 10, 20))
        await make_due(db, [user.id])
        await db.commit()
        now = at(D(2026, 10, 20))
        first = await executor.claim(db, now, user_ids=[user.id])
        # Przebieg przerwany (wdrożenie) — po dzierżawie operacje wracają.
        assert (
            await executor.claim(
                db, now + executor.LEASE - timedelta(seconds=1), user_ids=[user.id]
            )
            == []
        )
        again = await executor.claim(db, now + executor.LEASE, user_ids=[user.id])
        await db.execute(
            update(HrM365Operation)
            .where(HrM365Operation.id.in_(again))
            .values(status="pending")
        )
        await db.commit()

    assert sorted(first) == sorted(again) and len(first) == 2


async def test_broken_payload_fails_without_touching_the_mailbox() -> None:
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        user = await make_user(db)
        await outbox.enqueue(
            db,
            user_id=user.id,
            kind="set_oof",
            dedupe_key=f"test:{uuid.uuid4()}",
            payload={"start": "nie-data"},
        )
        await make_due(db, [user.id])
        await db.commit()
        await executor.run_once(
            db, ops=fake, mode="live", now=at(D(2026, 10, 20)), user_ids=[user.id]
        )
        (op,) = await operations(db, user.id)

    assert (op.status, op.last_error, op.attempts) == ("failed", "bad_payload", 1)
    assert fake.calls == []
