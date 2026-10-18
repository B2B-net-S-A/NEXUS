"""Czyste reguły luk z Compassa w urlopach (bez bazy).

* okno nieobecności z własnej autoodpowiedzi osoby (godziny graniczne jak
  w Compassie ``lib/oof/oof-dates.ts``: start od 15:00 = następny dzień,
  koniec do 9:00 = bez dnia końca, czas warszawski przy zmianie czasu),
* odcinki dni roboczych bez pokrycia (weekend nie przerywa, pokryty dzień tak),
* operacje Microsoft 365 po edycji zatwierdzonego wniosku.

Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.hr.leave_m365 import LeaveSnapshot, plan_edit
from app.services.hr.leave_outlook import missing_runs, note_for
from app.services.hr.m365 import oof_state

D = date


def _scheduled(start: str, end: str, *, tz: str = "UTC", body: str = "<p>Urlop</p>"):
    return {
        "status": "scheduled",
        "scheduledStartDateTime": {"dateTime": start, "timeZone": tz},
        "scheduledEndDateTime": {"dateTime": end, "timeZone": tz},
        "internalReplyMessage": body,
        "externalReplyMessage": body,
    }


def test_window_from_midnight_to_midnight_in_warsaw() -> None:
    # Outlook zapisuje „cały dzień” jako północ warszawską (22:00 UTC latem).
    setting = _scheduled("2026-10-18T22:00:00.0000000", "2026-10-23T22:00:00.0000000")
    assert oof_state.custom_absence_window(setting) == (
        D(2026, 10, 19),
        D(2026, 10, 23),
    )


def test_window_late_start_skips_first_day_and_early_end_skips_last() -> None:
    # Włączona o 16:30 w piątek, „wracam w poniedziałek o 8:00” (zima, UTC+1).
    setting = _scheduled("2026-11-06T15:30:00", "2026-11-16T07:00:00")
    assert oof_state.custom_absence_window(setting) == (D(2026, 11, 7), D(2026, 11, 15))


def test_window_end_after_nine_includes_the_day() -> None:
    setting = _scheduled(
        "2026-11-09T08:00:00", "2026-11-12T16:00:00", tz="Europe/Warsaw"
    )
    assert oof_state.custom_absence_window(setting) == (D(2026, 11, 9), D(2026, 11, 12))


def test_window_none_for_evening_only_always_enabled_ours_and_disabled() -> None:
    evening = _scheduled("2026-11-09T16:00:00", "2026-11-10T07:00:00")
    assert oof_state.custom_absence_window(evening) is None
    assert (
        oof_state.custom_absence_window(
            {"status": "alwaysEnabled", "internalReplyMessage": "<p>Mój</p>"}
        )
        is None
    )
    ours = _scheduled(
        "2026-11-08T23:00:00",
        "2026-11-13T23:00:00",
        body=f"{oof_state.NEXUS_OOF_MARKER}<p>x</p>",
    )
    assert oof_state.custom_absence_window(ours) is None
    compass = _scheduled(
        "2026-11-08T23:00:00",
        "2026-11-13T23:00:00",
        body=f"{oof_state.COMPASS_OOF_MARKER}<p>x</p>",
    )
    assert oof_state.custom_absence_window(compass) is None
    assert oof_state.custom_absence_window({"status": "disabled"}) is None
    assert oof_state.custom_absence_window(None) is None


def test_window_none_without_readable_dates() -> None:
    broken = {"status": "scheduled", "scheduledStartDateTime": {"dateTime": "x"}}
    assert oof_state.custom_absence_window(broken) is None


def test_missing_runs_weekend_joins_and_covered_day_splits() -> None:
    working = [
        D(2026, 11, 6),  # piątek
        D(2026, 11, 9),  # poniedziałek
        D(2026, 11, 10),
        D(2026, 11, 12),  # 11.11 — święto, nie ma go w dniach roboczych
        D(2026, 11, 13),
    ]
    assert missing_runs(working, set()) == [(D(2026, 11, 6), D(2026, 11, 13))]
    assert missing_runs(working, {D(2026, 11, 10)}) == [
        (D(2026, 11, 6), D(2026, 11, 9)),
        (D(2026, 11, 12), D(2026, 11, 13)),
    ]
    assert missing_runs(working, set(working)) == []
    assert missing_runs([], set()) == []


def test_note_names_the_window_and_the_next_step() -> None:
    uop = note_for(D(2026, 11, 9), D(2026, 11, 13), reported=False)
    assert uop.startswith("Wykryte z autoodpowiedzi w Outlooku (09.11–13.11.2026)")
    assert "zatwierdź albo odrzuć" in uop
    b2b = note_for(D(2026, 11, 9), D(2026, 11, 13), reported=True)
    assert "zgłoszenie przyjęte" in b2b
    assert "urlop" not in b2b.lower()


def _snap(start: date, end: date, **extra) -> LeaveSnapshot:
    values = {
        "id": "00000000-0000-0000-0000-00000000abcd",
        "user_id": 7,
        "start": start,
        "end": end,
        "half_day": None,
        "total_days": Decimal("5"),
        "substitute_user_id": None,
        "forward_mail_consent": False,
        "oof_internal_message": "Mój tekst",
        "oof_external_message": None,
        "return_on": end,
        **extra,
    }
    return LeaveSnapshot(**values)


def test_plan_edit_moved_window_clears_old_then_sets_new_and_moves_event() -> None:
    before = _snap(D(2026, 11, 9), D(2026, 11, 13))
    after = _snap(D(2026, 11, 16), D(2026, 11, 20))
    ops = plan_edit(before, after, today=D(2026, 11, 2), revision=4)
    assert [op.kind for op in ops] == [
        "clear_oof",
        "set_oof",
        "calendar_event_upsert",
    ]
    clear, set_oof, event = ops
    assert clear.payload == {"start": "2026-11-09", "end": "2026-11-13"}
    assert set_oof.payload["start"] == "2026-11-16"
    # Własny tekst autoodpowiedzi osoby zostaje po zmianie.
    assert set_oof.payload["internal_message"] == "Mój tekst"
    assert event.payload["transaction_id"] == f"nexus-leave-{after.id}"
    # Klucze różne od akceptacji i od poprzedniej zmiany.
    assert all(op.dedupe_key.endswith(":edit4") for op in ops)


def test_plan_edit_type_only_change_touches_only_the_event() -> None:
    before = _snap(D(2026, 11, 9), D(2026, 11, 13))
    ops = plan_edit(before, before, today=D(2026, 11, 2), revision=2)
    assert [op.kind for op in ops] == ["calendar_event_upsert"]


def test_plan_edit_to_half_day_drops_autoreply() -> None:
    before = _snap(D(2026, 11, 9), D(2026, 11, 9), total_days=Decimal("1"))
    after = _snap(
        D(2026, 11, 9), D(2026, 11, 9), total_days=Decimal("0.5"), half_day="morning"
    )
    kinds = [
        op.kind for op in plan_edit(before, after, today=D(2026, 11, 2), revision=1)
    ]
    assert kinds == ["clear_oof", "calendar_event_upsert"]


def test_plan_edit_with_consent_reopens_rule_for_new_substitute() -> None:
    before = _snap(
        D(2026, 11, 9), D(2026, 11, 13), substitute_user_id=8, forward_mail_consent=True
    )
    after = _snap(
        D(2026, 11, 9), D(2026, 11, 13), substitute_user_id=9, forward_mail_consent=True
    )
    ops = plan_edit(before, after, today=D(2026, 11, 2), revision=3)
    assert [op.kind for op in ops] == [
        "set_oof",  # nowy zastępca w treści autoodpowiedzi
        "calendar_event_upsert",
        "forward_rule_close",
        "forward_rule_open",
    ]
    assert ops[-1].payload["substitute_user_id"] == 9
    assert ops[-1].payload["rule_name"].endswith(after.id)


def test_plan_edit_dropping_substitute_closes_rule_without_reopening() -> None:
    before = _snap(
        D(2026, 11, 9), D(2026, 11, 13), substitute_user_id=8, forward_mail_consent=True
    )
    after = _snap(D(2026, 11, 9), D(2026, 11, 13))
    kinds = [
        op.kind for op in plan_edit(before, after, today=D(2026, 11, 2), revision=1)
    ]
    assert kinds[-1] == "forward_rule_close"
    assert "forward_rule_open" not in kinds


def test_plan_edit_moved_into_the_past_removes_event() -> None:
    before = _snap(D(2026, 11, 9), D(2026, 11, 13))
    after = _snap(D(2026, 10, 5), D(2026, 10, 9))
    kinds = [
        op.kind for op in plan_edit(before, after, today=D(2026, 10, 20), revision=1)
    ]
    assert kinds == ["clear_oof", "calendar_event_delete"]
