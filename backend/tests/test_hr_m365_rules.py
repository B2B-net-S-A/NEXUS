"""Microsoft 365 dla urlopów — czyste reguły (bez bazy i sieci).

Okno autoodpowiedzi w datach warszawskich (zmiana czasu), znaczniki NEXUSA
i Compassa, treść bez rodzaju nieobecności (D6), filtr i nazwy reguł
przekierowania, godziny połówki dnia, kategorie błędów i dokładne żądania
trybu symulacji. Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.services.hr.leave_policy import LEAVE_TYPE_LABELS
from app.services.hr.m365 import calendar_event, forward_rules, oof_state, oof_template
from app.services.hr.m365.ops import MailboxError, categorize
from app.services.hr.m365.simulated import SimulatedMailboxOps

LEAVE_ID = "3f1c2a9e-1b2c-4d5e-8f90-123456789abc"


def _utc(value: str) -> dict:
    return {"dateTime": value, "timeZone": "UTC"}


def _ours(start: dict, end: dict, marker: str = oof_state.NEXUS_OOF_MARKER) -> dict:
    return {
        "status": "scheduled",
        "scheduledStartDateTime": start,
        "scheduledEndDateTime": end,
        "internalReplyMessage": f"{marker}\n<p>x</p>",
        "externalReplyMessage": f"{marker}\n<p>x</p>",
    }


# ── Okno autoodpowiedzi ──────────────────────────────────────────────────────


def test_window_matches_across_october_dst_change() -> None:
    # 23–26.10.2026: start w czasie letnim (UTC+2), koniec po zmianie (UTC+1).
    setting = _ours(
        _utc("2026-10-22T22:00:00.0000000"), _utc("2026-10-26T23:00:00.0000000")
    )
    assert oof_state.scheduled_window(setting) == (
        date(2026, 10, 23),
        date(2026, 10, 27),
    )
    assert oof_state.matches_leave(setting, date(2026, 10, 23), date(2026, 10, 26))
    # Stałe przesunięcie +1 h dałoby dzień wcześniej — tego nie wolno uznać.
    assert not oof_state.matches_leave(setting, date(2026, 10, 22), date(2026, 10, 26))


def test_window_matches_across_march_dst_change() -> None:
    # 26–29.03.2027: start w czasie zimowym (UTC+1), koniec w letnim (UTC+2).
    setting = _ours(
        _utc("2027-03-25T23:00:00.0000000"), _utc("2027-03-29T22:00:00.0000000")
    )
    assert oof_state.matches_leave(setting, date(2027, 3, 26), date(2027, 3, 29))


def test_schedule_setting_uses_warsaw_wall_time_not_utc() -> None:
    setting = oof_template.schedule_setting(
        start=date(2026, 10, 23),
        end=date(2026, 10, 26),
        internal_html="<p>a</p>",
        external_html="<p>b</p>",
    )
    assert setting["scheduledStartDateTime"] == {
        "dateTime": "2026-10-23T00:00:00",
        "timeZone": "Europe/Warsaw",
    }
    assert setting["scheduledEndDateTime"] == {
        "dateTime": "2026-10-27T00:00:00",
        "timeZone": "Europe/Warsaw",
    }
    assert setting["externalAudience"] == "all"
    assert setting["internalReplyMessage"].startswith(oof_state.NEXUS_OOF_MARKER)


def test_compass_marker_counts_as_ours() -> None:
    setting = _ours(
        {"dateTime": "2026-11-02T00:00:00", "timeZone": "Europe/Warsaw"},
        {"dateTime": "2026-11-07T00:00:00", "timeZone": "Europe/Warsaw"},
        marker=oof_state.COMPASS_OOF_MARKER,
    )
    assert oof_state.owner(setting) == "compass"
    assert oof_state.matches_leave(setting, date(2026, 11, 2), date(2026, 11, 6))
    assert not oof_state.user_custom_active(
        setting, datetime(2026, 11, 3, tzinfo=timezone.utc)
    )


def test_user_custom_oof_is_protected_until_it_ends() -> None:
    now = datetime(2026, 10, 20, 10, tzinfo=timezone.utc)
    assert oof_state.user_custom_active({"status": "alwaysEnabled"}, now)
    running = {
        "status": "scheduled",
        "scheduledEndDateTime": _utc("2026-10-25T00:00:00"),
        "internalReplyMessage": "<p>Mój tekst</p>",
    }
    assert oof_state.user_custom_active(running, now)
    expired = {**running, "scheduledEndDateTime": _utc("2026-10-19T00:00:00")}
    assert not oof_state.user_custom_active(expired, now)
    unknown_end = {"status": "scheduled", "internalReplyMessage": "<p>x</p>"}
    assert oof_state.user_custom_active(unknown_end, now)
    assert not oof_state.user_custom_active({"status": "disabled"}, now)


def test_running_oof_of_other_leave_blocks_a_later_leave_only() -> None:
    # Nasza autoodpowiedź na 19–23.10 (koniec wyłączny 24.10).
    current = _ours(
        {"dateTime": "2026-10-19T00:00:00", "timeZone": "Europe/Warsaw"},
        {"dateTime": "2026-10-24T00:00:00", "timeZone": "Europe/Warsaw"},
    )
    until = oof_state.blocking_until(current, date(2026, 10, 26), date(2026, 10, 20))
    assert until == datetime(2026, 10, 23, 22, tzinfo=timezone.utc)
    # Wcześniejszy urlop ma pierwszeństwo — nadpisuje.
    assert (
        oof_state.blocking_until(current, date(2026, 10, 16), date(2026, 10, 15))
        is None
    )
    # Okno już minęło — nic nie blokuje.
    assert (
        oof_state.blocking_until(current, date(2026, 10, 26), date(2026, 10, 24))
        is None
    )


# ── Treść ────────────────────────────────────────────────────────────────────


def test_default_text_never_names_the_absence_type() -> None:
    setting = oof_template.build_setting(
        start=date(2026, 12, 21),
        end=date(2026, 12, 31),
        return_on=date(2027, 1, 4),
        employee_name="Anna Przykładowa",
        contact=oof_template.Contact(
            "substitute", "ola.zastepca@example.com", "Ola Zastępca"
        ),
    )
    body = (setting["internalReplyMessage"] + setting["externalReplyMessage"]).lower()
    for label in LEAVE_TYPE_LABELS.values():
        assert label.lower() not in body
    for word in ("urlop", "l4", "chorob", "zwolnien", "sick", "vacation", "leave"):
        assert word not in body
    assert "4 stycznia 2027" in setting["internalReplyMessage"]
    assert "4 January 2027" in setting["externalReplyMessage"]
    assert "Ola Zastępca" in setting["internalReplyMessage"]
    assert "mailto:ola.zastepca@example.com" in setting["externalReplyMessage"]


def test_custom_text_is_stripped_of_html() -> None:
    html = oof_template.custom_html(
        'Wracam w poniedziałek <script>alert(1)</script><img src=x onerror=1>\n\nPilne: <a href="javascript:x">tu</a> & tam'
    )
    assert html is not None
    assert "<script" not in html and "<img" not in html and "<a " not in html
    assert "&amp; tam" in html
    assert html.count("<p>") == 2
    assert oof_template.custom_html("   ") is None
    setting = oof_template.build_setting(
        start=date(2026, 11, 2),
        end=date(2026, 11, 6),
        return_on=date(2026, 11, 9),
        employee_name="Anna Przykładowa",
        contact=None,
        internal_custom="Jestem na szkoleniu.",
    )
    assert "Jestem na szkoleniu." in setting["internalReplyMessage"]
    assert setting["internalReplyMessage"].startswith(oof_state.NEXUS_OOF_MARKER)
    # Bez własnego tekstu zewnętrznego — domyślny, bez linii kontaktu.
    assert "W pilnych sprawach" not in setting["externalReplyMessage"]


def test_contact_lines_follow_the_chain_kind() -> None:
    manager = oof_template.Contact("manager", "szef@example.com", "Jan Przełożony")
    office = oof_template.Contact("office", "biuro@example.com")
    internal_manager, _ = oof_template.default_messages(
        employee_name="A",
        end=date(2026, 11, 6),
        return_on=date(2026, 11, 9),
        contact=manager,
    )
    internal_office, external_office = oof_template.default_messages(
        employee_name="A",
        end=date(2026, 11, 6),
        return_on=date(2026, 11, 9),
        contact=office,
    )
    assert "proszę o kontakt: <strong>Jan Przełożony</strong>" in internal_manager
    assert 'z biurem: <a href="mailto:biuro@example.com">' in internal_office
    assert "our office" in external_office


# ── Przekierowanie ───────────────────────────────────────────────────────────


def test_rule_names_of_nexus_and_compass_are_recognised() -> None:
    assert forward_rules.rule_name(LEAVE_ID) == f"NEXUS · zastępstwo · {LEAVE_ID}"
    assert forward_rules.parse_leave_id(f"NEXUS · zastępstwo · {LEAVE_ID}") == LEAVE_ID
    assert (
        forward_rules.parse_leave_id(f"COMPASS · zastępstwo · {LEAVE_ID.upper()}")
        == LEAVE_ID
    )
    assert forward_rules.is_compass_rule(f"COMPASS · zastępstwo · {LEAVE_ID}")
    # Cudza reguła z podobnym początkiem, ale bez UUID — nie nasza.
    assert forward_rules.parse_leave_id("NEXUS · zastępstwo · moja") is None
    assert forward_rules.parse_leave_id("NEXUS - zastępstwo - " + LEAVE_ID) is None
    assert forward_rules.parse_leave_id(None) is None


def test_rule_filter_excludes_company_domain_from_config() -> None:
    body = forward_rules.rule_body(
        leave_id=LEAVE_ID,
        substitute_email="ola.zastepca@example.com",
        substitute_name="Ola Zastępca",
        company_domains=["Example.com", " example.org "],
    )
    excluded = body["exceptions"]["senderContains"]
    assert excluded[:2] == ["@example.com", "@example.org"]
    for fragment in (
        "noreply",
        "teams.mail.microsoft",
        "sharepointonline.com",
        "microsoft.com",
    ):
        assert fragment in excluded
    assert body["exceptions"]["headerContains"] == ["List-Unsubscribe"]
    for flag in (
        "isAutomaticReply",
        "isAutomaticForward",
        "isMeetingRequest",
        "isMeetingResponse",
        "isReadReceipt",
        "isNonDeliveryReport",
    ):
        assert body["exceptions"][flag] is True
    assert body["conditions"] == {"sentToOrCcMe": True}
    assert (
        body["actions"]["forwardTo"][0]["emailAddress"]["address"]
        == "ola.zastepca@example.com"
    )
    assert body["actions"]["stopProcessingRules"] is False


def test_forward_window_is_the_leave_itself() -> None:
    start, end = date(2026, 11, 2), date(2026, 11, 6)
    assert forward_rules.window_state(start, end, date(2026, 11, 1)) == "before"
    assert forward_rules.window_state(start, end, date(2026, 11, 2)) == "open"
    assert forward_rules.window_state(start, end, date(2026, 11, 6)) == "open"
    assert forward_rules.window_state(start, end, date(2026, 11, 7)) == "after"


# ── Wydarzenie ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("half_day", "hours"),
    [("morning", ("08:00:00", "12:00:00")), ("afternoon", ("12:00:00", "16:00:00"))],
)
def test_half_day_event_keeps_hours_on_create_and_on_update(half_day, hours) -> None:
    day = date(2026, 11, 4)
    created = calendar_event.event_body(
        start=day, end=day, half_day=half_day, transaction="t"
    )
    patched = calendar_event.event_body(start=day, end=day, half_day=half_day)
    for body in (created, patched):
        assert body["isAllDay"] is False
        assert body["start"]["dateTime"] == f"2026-11-04T{hours[0]}"
        assert body["end"]["dateTime"] == f"2026-11-04T{hours[1]}"
    assert created["transactionId"] == "t"
    assert "transactionId" not in patched


def test_event_is_private_neutral_and_all_day() -> None:
    body = calendar_event.event_body(
        start=date(2026, 11, 2),
        end=date(2026, 11, 6),
        half_day=None,
        transaction="nexus-leave-x",
    )
    assert body["subject"] == "Poza biurem"
    assert body["sensitivity"] == "private"
    assert body["showAs"] == "oof"
    assert body["categories"] == ["NEXUS"]
    assert body["isAllDay"] is True
    assert body["end"]["dateTime"] == "2026-11-07T00:00:00"
    assert body["body"]["content"] == ""
    assert calendar_event.known_transaction_ids(LEAVE_ID) == {
        f"nexus-leave-{LEAVE_ID}",
        f"leave-{LEAVE_ID}",
    }


# ── Błędy i symulacja ────────────────────────────────────────────────────────


def test_error_categories_and_retry_policy() -> None:
    assert categorize(403) == "forbidden"
    assert categorize(429) == "throttled"
    assert categorize(503) == "server_error"
    assert categorize(599) == "timeout"
    assert categorize(None) == "network"
    assert categorize(404, "MailboxNotEnabledForRESTAPI") == "no_mailbox"
    assert categorize(400) == "bad_request"
    assert MailboxError(403).retryable and MailboxError(429).retryable
    assert MailboxError(502).retryable and MailboxError(None).retryable
    assert not MailboxError(400).retryable and not MailboxError(404).retryable
    assert MailboxError(403).label == "forbidden (403)"


async def test_simulation_records_exact_graph_requests() -> None:
    ops = SimulatedMailboxOps()
    upn = "anna.przykladowa@example.com"
    assert (await ops.get_auto_replies(upn))["status"] == "disabled"
    setting = oof_template.schedule_setting(
        start=date(2026, 11, 2),
        end=date(2026, 11, 6),
        internal_html="a",
        external_html="b",
    )
    await ops.set_auto_replies(upn, setting)
    created = await ops.create_event(upn, {"subject": "Poza biurem"})
    await ops.delete_rule(upn, "rule/1")
    assert created["id"].startswith("simulated-")
    assert ops.requests[0] == {
        "method": "GET",
        "path": "/users/anna.przykladowa@example.com/mailboxSettings/automaticRepliesSetting",
    }
    assert ops.requests[1] == {
        "method": "PATCH",
        "path": "/users/anna.przykladowa@example.com/mailboxSettings",
        "body": {"automaticRepliesSetting": setting},
    }
    assert ops.requests[2]["path"] == "/users/anna.przykladowa@example.com/events"
    assert ops.requests[3] == {
        "method": "DELETE",
        "path": "/users/anna.przykladowa@example.com/mailFolders/inbox/messageRules/rule%2F1",
    }
    assert await ops.list_rules(upn) == []
