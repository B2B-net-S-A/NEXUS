"""Raport obecności Teams: oba języki eksportu, kodowania, separatory, dopasowanie osób.

Fikstury odwzorowują układ pliku „… - Raport obecności 10-07-26.csv” z Teams
(sekcje 1–3); osoby i adresy są fikcyjne.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.trainings import attendance
from app.services.trainings.attendance import (
    AttendanceRow,
    parse_duration,
    parse_teams_report,
)

EN_REPORT = "\n".join(
    [
        "1. Summary",
        "Meeting title\tB2B Tech Sessions #01 | Cybersecurity w erze AI",
        "Attended participants\t4",
        "Start time\t7/10/26, 9:58:12 AM",
        "End time\t7/10/26, 11:30:45 AM",
        "Meeting duration\t1h 32m 33s",
        "Average attendance time\t1h 2m 10s",
        "",
        "2. Participants",
        "Name\tFirst Join\tLast Leave\tIn-Meeting Duration\tEmail\tParticipant ID (UPN)\tRole",
        "Anna Testowa\t7/10/26, 9:58:12 AM\t7/10/26, 11:30:45 AM\t1h 32m 33s\tAnna.Testowa@Example.PL\tanna.testowa@example.pl\tOrganizer",
        "Jan Próbny\t7/10/26, 10:01:00 AM\t7/10/26, 11:00:00 AM\t59m 0s\t\tjan.probny@example.pl\tPresenter",
        "Gość Zewnętrzny (Guest)\t7/10/26, 10:05:00 AM\t7/10/26, 10:20:29 AM\t15m 29s\t\t\tAttendee",
        "\t\t\t\t\t\t",
        "Ewa Krótka\t7/10/26, 10:05:00 AM\t7/10/26, 10:05:20 AM\t20s\tewa@example.pl\tewa@example.pl\tAttendee",
        "",
        "3. In-Meeting Activities",
        "Name\tJoin Time\tLeave Time\tDuration\tEmail\tRole",
        "Anna Testowa\t7/10/26, 9:58:12 AM\t7/10/26, 11:30:45 AM\t1h 32m 33s\tanna.testowa@example.pl\tOrganizer",
    ]
)

PL_REPORT = "\r\n".join(
    [
        "1. Podsumowanie",
        "Tytuł spotkania\tB2B Tech Sessions #01 _ Cybersecurity w erze AI",
        "Uczestnicy, którzy wzięli udział\t3",
        "Czas rozpoczęcia\t10.07.2026, 09:58:12",
        "Czas trwania spotkania\t1 h 32 min 33 s",
        "",
        "2. Uczestnicy",
        "Imię i nazwisko\tPierwsze dołączenie\tOstatnie opuszczenie\tCzas w spotkaniu\tAdres e-mail\tIdentyfikator uczestnika (UPN)\tRola",
        "Anna Testowa\t10.07.2026, 09:58:12\t10.07.2026, 11:30:45\t1 h 32 min 33 s\tanna.testowa@example.pl\tanna.testowa@example.pl\tOrganizator",
        "Łukasz Żółć\t10.07.2026, 10:01:00\t10.07.2026, 11:00:00\t59 min 1 s\tlukasz.zolc@example.pl\tlukasz.zolc@example.pl\tUczestnik",
        "Marta Bez Maila\t10.07.2026, 10:30:00\t10.07.2026, 10:45:00\t15 min\t\t\tUczestnik",
        "",
        "3. Działania podczas spotkania",
        "Imię i nazwisko\tCzas dołączenia\tCzas opuszczenia\tCzas trwania\tAdres e-mail\tRola",
        "Anna Testowa\t10.07.2026, 09:58:12\t10.07.2026, 11:30:45\t1 h 32 min 33 s\tanna.testowa@example.pl\tOrganizator",
    ]
)


def _utf16(text: str) -> bytes:
    return b"\xff\xfe" + text.encode("utf-16-le")


def test_english_report_in_utf16_takes_participants_section():
    rows = parse_teams_report(_utf16(EN_REPORT))
    assert rows == [
        AttendanceRow("Anna Testowa", "anna.testowa@example.pl", 93),
        AttendanceRow("Jan Próbny", "jan.probny@example.pl", 59),  # adres z UPN
        AttendanceRow("Gość Zewnętrzny (Guest)", "", 15),
        AttendanceRow("Ewa Krótka", "ewa@example.pl", 0),
    ]


def test_polish_report_in_utf8_with_bom_and_crlf():
    rows = parse_teams_report(b"\xef\xbb\xbf" + PL_REPORT.encode("utf-8"))
    assert rows == [
        AttendanceRow("Anna Testowa", "anna.testowa@example.pl", 93),
        AttendanceRow("Łukasz Żółć", "lukasz.zolc@example.pl", 59),
        AttendanceRow("Marta Bez Maila", "", 15),
    ]


def test_polish_report_in_utf16_without_bom():
    rows = parse_teams_report(PL_REPORT.encode("utf-16-le"))
    assert [row.name for row in rows] == [
        "Anna Testowa",
        "Łukasz Żółć",
        "Marta Bez Maila",
    ]


def test_comma_separated_with_quotes():
    text = "\n".join(
        [
            '"1. Summary"',
            '"Meeting title","Szkolenie, część 1"',
            "",
            '"2. Participants"',
            '"Name","First Join","Last Leave","In-Meeting Duration","Email","Participant ID (UPN)","Role"',
            '"Kowalska, Anna","7/10/26, 9:58 AM","7/10/26, 10:58 AM","1h 0m 0s","a.k@example.pl","a.k@example.pl","Attendee"',
            ",,,,,,",
        ]
    )
    assert parse_teams_report(text.encode("utf-8")) == [
        AttendanceRow("Kowalska, Anna", "a.k@example.pl", 60)
    ]


def test_without_participants_section_sums_activities():
    text = "\n".join(
        [
            "1. Summary",
            "Meeting title\tX",
            "3. In-Meeting Activities",
            "Name\tJoin Time\tLeave Time\tDuration\tEmail\tRole",
            "Anna\t9:00\t9:30\t30m 0s\tanna@example.pl\tAttendee",
            "Anna\t9:40\t10:00\t20m 0s\tANNA@example.pl\tAttendee",
            "Jan\t9:00\t9:10\t10m\tjan@example.pl\tAttendee",
        ]
    )
    assert parse_teams_report(text.encode("utf-8")) == [
        AttendanceRow("Anna", "anna@example.pl", 50),
        AttendanceRow("Jan", "jan@example.pl", 10),
    ]


def test_old_format_without_sections():
    text = "\n".join(
        [
            "Meeting Summary",
            "Total Number of Participants\t2",
            "Full Name\tJoin Time\tLeave Time\tDuration\tEmail\tRole",
            "Anna\t9:00\t9:30\t30m\tanna@example.pl\tAttendee",
            "Jan\t9:00\t9:45\t45m\tjan@example.pl\tAttendee",
        ]
    )
    assert [(r.name, r.minutes) for r in parse_teams_report(text.encode("utf-8"))] == [
        ("Anna", 30),
        ("Jan", 45),
    ]


def test_duplicate_participant_keeps_longest_time():
    text = "\n".join(
        [
            "2. Participants",
            "Name\tIn-Meeting Duration\tEmail",
            "Anna\t30m\tanna@example.pl",
            "Anna (telefon)\t50m\tanna@example.pl",
        ]
    )
    assert parse_teams_report(text.encode("utf-8")) == [
        AttendanceRow("Anna", "anna@example.pl", 50)
    ]


@pytest.mark.parametrize(
    ("value", "minutes"),
    [
        ("1 h 23 min 5 s", 83),
        ("1h 23m 5s", 83),
        ("1h 23m 31s", 84),
        ("45 min", 45),
        ("2 godz. 5 min", 125),
        ("59 s", 1),
        ("29s", 0),
        ("01:23:05", 83),
        ("", None),
        ("brak", None),
    ],
)
def test_parse_duration(value, minutes):
    assert parse_duration(value) == minutes


def test_garbage_gives_no_rows():
    assert parse_teams_report(b"") == []
    assert parse_teams_report(b"to nie jest raport\nani tabela") == []


class _Result:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def all(self) -> list[tuple]:
        return self._rows


class FakeDb:
    def __init__(self, users: list[tuple], contracts: list[tuple]) -> None:
        self._results = [_Result(users), _Result(contracts)]
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _Result:
        self.statements.append(statement)
        return self._results.pop(0)


async def test_match_fills_user_and_contract_and_skips_ambiguous():
    rows = [
        AttendanceRow("Anna", "anna@example.pl", 90),
        AttendanceRow("Konsultant", "Kons@Example.pl", 60),
        AttendanceRow("Wspólna skrzynka", "biuro@example.pl", 30),
        AttendanceRow("Gość", "", 10),
    ]
    db = FakeDb(
        users=[(1, "anna@example.pl")],
        contracts=[
            (11, 500, "kons@example.pl"),  # nowszy kontrakt tej samej osoby
            (10, 500, "kons@example.pl"),
            (20, 600, "biuro@example.pl"),  # dwie różne osoby pod jednym adresem
            (21, 601, "biuro@example.pl"),
        ],
    )
    matched = await attendance.match(db, rows)
    assert [(r.user_id, r.contract_id) for r in matched] == [
        (1, None),
        (None, 11),
        (None, None),
        (None, None),
    ]
    compiled = str(db.statements[1].compile(compile_kwargs={"literal_binds": True}))
    assert "lower(contracts.candidate_email) IN" in compiled
    assert "'active'" in compiled and "'ending'" in compiled


async def test_match_without_emails_does_not_query():
    class NoDb:
        async def execute(self, statement: Any) -> None:  # pragma: no cover
            raise AssertionError("bez adresów nie ma zapytań")

    rows = [AttendanceRow("Gość", "", 10)]
    assert await attendance.match(NoDb(), rows) == rows
