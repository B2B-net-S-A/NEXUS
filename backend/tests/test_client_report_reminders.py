"""Przypomnienia o terminach raportów dla klienta (decyzja Artura 15.11.2026).

Czysta funkcja ``client_reports.reminders.plan_reminders`` i rejestracja typu
``client_report_due`` — bez bazy.
"""

from __future__ import annotations

import asyncio
import importlib.util
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.models.client_report import ClientReportDefinition
from app.models.notification import NotificationType
from app.services.client_reports import reminders
from app.services.client_reports.catalog import Assignment
from app.services.client_reports.reminders import OVERDUE, UPCOMING, plan_reminders
from app.services.notification_access import NOTIFICATION_SECTION_BY_TYPE
from app.services.notification_categories import (
    CATEGORY_BY_TYPE,
    NotificationCategory,
    is_mutable,
)
from app.services.notification_substitution import CURRENT_WORK_TYPES
from app.services.section_permissions import ProductSection
from app.tasks import client_report_reminders as task

_BACKEND = Path(__file__).resolve().parents[1]
_WARSAW = ZoneInfo("Europe/Warsaw")

CLIENT = 41
DL_A = 7
DL_B = 8
PREPARER = 15


def _definition(**overrides) -> ClientReportDefinition:
    values = dict(
        id=100,
        client_id=CLIENT,
        name="Raport miesięczny",
        family="management",
        rhythm="monthly",
        # Okres październik 2026 → termin czwartek 19.11.2026.
        due_rule={"type": "day_of_month", "day": 19},
        preparer="dl",
        preparer_user_id=None,
        source_kind="dl",
        status="active",
        valid_from=date(2026, 1, 1),
        valid_to=None,
    )
    values.update(overrides)
    return ClientReportDefinition(**values)


ASSIGNMENTS = {
    CLIENT: [
        Assignment(CLIENT, DL_A, "DL A", True),
        Assignment(CLIENT, DL_B, "DL B", False),
    ]
}


def _plan(definitions, today, *, sent=None, assignments=ASSIGNMENTS, already=None):
    return plan_reminders(
        definitions,
        today=today,
        sent=sent or {},
        assignments=assignments,
        already_sent=already or {},
    )


# ── Pasmo przed terminem ────────────────────────────────────────────────────


def test_three_workdays_before_due_starts_the_band():
    # Pon 16.11 + 3 dni robocze = czw 19.11 = termin.
    planned = _plan([_definition()], date(2026, 11, 16))
    assert [(r.user_id, r.kind, r.period_key, r.due) for r in planned] == [
        (DL_A, UPCOMING, "2026-10", date(2026, 11, 19)),
        (DL_B, UPCOMING, "2026-10", date(2026, 11, 19)),
    ]


def test_before_the_band_nothing_goes():
    # Pt 13.11 + 3 dni robocze = śr 18.11 < termin.
    assert _plan([_definition()], date(2026, 11, 13)) == []


def test_due_today_is_still_in_the_band():
    [first, _] = _plan([_definition()], date(2026, 11, 19))
    assert first.kind == UPCOMING
    assert reminders.title(first, date(2026, 11, 19)).startswith(
        "Raport dla klienta — termin dziś"
    )


def test_band_counts_workdays_across_the_weekend():
    # Termin w sobotę 05.12 (listopad, 5. dzień): w środę 02.12 pasmo sięga
    # poniedziałku 07.12, więc obejmuje sobotę.
    definition = _definition(due_rule={"type": "day_of_month", "day": 5})
    planned = _plan([definition], date(2026, 12, 2))
    assert {(r.period_key, r.kind) for r in planned} == {("2026-11", UPCOMING)}


def test_end_of_period_rule_reminds_about_the_current_period():
    definition = _definition(due_rule={"type": "end_of_period"})
    planned = _plan([definition], date(2026, 11, 26))
    assert {(r.period_key, r.due) for r in planned} == {("2026-11", date(2026, 11, 30))}


# ── Po terminie ─────────────────────────────────────────────────────────────


def test_day_after_due_sends_overdue():
    planned = _plan([_definition()], date(2026, 11, 20))
    assert {(r.kind, r.period_key) for r in planned} == {(OVERDUE, "2026-10")}
    assert reminders.title(planned[0], date(2026, 11, 20)).startswith(
        "Raport dla klienta — termin minął"
    )


def test_overdue_catches_up_a_missed_day_then_stops():
    # Termin czw 19.11; siatka do wt 24.11 (3 dni robocze), potem cisza.
    assert _plan([_definition()], date(2026, 11, 24))
    assert _plan([_definition()], date(2026, 11, 25)) == []


def test_overdue_goes_first():
    weekly = _definition(
        id=101, rhythm="weekly", due_rule={"type": "business_days_after", "days": 1}
    )
    planned = _plan([_definition(), weekly], date(2026, 11, 20))
    assert planned[0].kind == OVERDUE


# ── Wysłany okres, tracking_start, status ───────────────────────────────────


def test_sent_period_gets_no_reminder():
    sent = {100: {"2026-10"}}
    assert _plan([_definition()], date(2026, 11, 16), sent=sent) == []
    assert _plan([_definition()], date(2026, 11, 20), sent=sent) == []


def test_periods_before_tracking_start_are_ignored():
    # „Obowiązuje od” po terminie październikowym: NEXUS go nie pilnował.
    late = _definition(valid_from=date(2026, 11, 20))
    assert _plan([late], date(2026, 11, 20)) == []
    # Bez „obowiązuje od” liczy się dzień dodania.
    added = _definition(valid_from=None, created_at=datetime(2026, 11, 20, 10, 0))
    assert _plan([added], date(2026, 11, 20)) == []


def test_only_active_calendar_definitions_with_a_due_rule():
    today = date(2026, 11, 16)
    assert _plan([_definition(status="proposal")], today) == []
    assert _plan([_definition(status="archived")], today) == []
    assert _plan([_definition(rhythm="on_request")], today) == []
    assert _plan([_definition(due_rule={"type": "none"})], today) == []
    assert _plan([_definition(due_rule={})], today) == []
    # Rok umowy bez daty początku: ScheduleError, nie wyjątek w pętli.
    no_anchor = _definition(rhythm="contract_year", valid_from=None)
    assert _plan([no_anchor], today) == []


def test_period_after_valid_to_is_ignored():
    ended = _definition(valid_to=date(2026, 9, 30))
    assert _plan([ended], date(2026, 11, 16)) == []


# ── Odbiorca ────────────────────────────────────────────────────────────────


def test_named_preparer_wins_over_dl_and_role():
    for preparer in ("dl", "finance", "board"):
        definition = _definition(preparer=preparer, preparer_user_id=PREPARER)
        planned = _plan([definition], date(2026, 11, 16))
        assert [r.user_id for r in planned] == [PREPARER]


def test_no_recipient_means_nothing():
    today = date(2026, 11, 16)
    # DL bez przypisanych DL-ów u klienta.
    assert _plan([_definition()], today, assignments={}) == []
    # Zespół albo strona spoza NEXUSA bez wskazanej osoby.
    for preparer in ("finance", "board", "iod", "consultant", "client"):
        assert _plan([_definition(preparer=preparer)], today) == []


def test_recipients_are_unique_per_definition():
    doubled = {CLIENT: [*ASSIGNMENTS[CLIENT], Assignment(CLIENT, DL_A, "DL A", False)]}
    assert reminders.recipients(_definition(), doubled) == [DL_A, DL_B]


# ── Dedup epizodu ───────────────────────────────────────────────────────────


def test_episode_already_sent_is_not_repeated():
    today = date(2026, 11, 17)
    [first, _] = _plan([_definition()], today)
    previous = reminders.message(first, "Klient")
    already = {(DL_A, 100): [previous]}
    planned = _plan([_definition()], today, already=already)
    assert [r.user_id for r in planned] == [DL_B]


def test_overdue_is_a_new_episode_after_the_upcoming_one():
    [upcoming, _] = _plan([_definition()], date(2026, 11, 16))
    already = {(DL_A, 100): [reminders.message(upcoming, None)]}
    planned = _plan([_definition()], date(2026, 11, 20), already=already)
    assert {(r.user_id, r.kind) for r in planned} == {
        (DL_A, OVERDUE),
        (DL_B, OVERDUE),
    }


def test_episode_phrases_do_not_contain_each_other():
    due = date(2026, 11, 19)
    before = reminders.episode_phrase(UPCOMING, "2026-10", due)
    after = reminders.episode_phrase(OVERDUE, "2026-10", due)
    assert before not in after and after not in before


def test_message_carries_the_phrase_link_and_short_title():
    long_name = "R" * 200
    [reminder, _] = _plan([_definition(name=long_name)], date(2026, 11, 16))
    assert reminder.phrase in reminders.message(reminder, None)
    assert reminders.message(reminder, None).startswith("klient: ")
    assert reminders.link(reminder) == f"/clients/{CLIENT}?tab=raporty"
    assert len(reminders.title(reminder, date(2026, 11, 16))) <= 255
    assert "za 3 dni" in reminders.title(
        _plan([_definition(name="X")], date(2026, 11, 16))[0], date(2026, 11, 16)
    )


# ── Pętla: dni wolne i godzina ──────────────────────────────────────────────


def test_loop_skips_weekend_holiday_and_early_morning():
    for moment in (
        datetime(2026, 11, 21, 10, 0, tzinfo=_WARSAW),  # sobota
        datetime(2026, 11, 11, 10, 0, tzinfo=_WARSAW),  # Święto Niepodległości
        datetime(2026, 11, 16, 8, 59, tzinfo=_WARSAW),  # przed 9:00
    ):
        assert asyncio.run(task.run_once(moment)) == 0


# ── Rejestracja typu ────────────────────────────────────────────────────────


def test_type_is_registered_for_reports_category_delivery_and_substitution():
    ntype = NotificationType.client_report_due
    assert CATEGORY_BY_TYPE[ntype] is NotificationCategory.client_reports
    assert is_mutable(NotificationCategory.client_reports)
    assert NOTIFICATION_SECTION_BY_TYPE[ntype] is ProductSection.delivery
    assert ntype in CURRENT_WORK_TYPES


def test_entrypoint_mirrors_the_enum_value_of_0708():
    path = _BACKEND / "alembic" / "versions" / "0709_client_reports.py"
    spec = importlib.util.spec_from_file_location("m0708", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    entrypoint = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    enum_block = entrypoint.split("_ENUM_STATEMENTS = [", 1)[1].split("\n]", 1)[0]
    assert f'"{migration.ADD_NOTIFICATION_TYPE}"' in enum_block
    assert "'client_report_due'" in migration.ADD_NOTIFICATION_TYPE
