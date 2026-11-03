"""Jednorazowa poprawka CV etapu z nazwą usługi w nagłówku i pliku (03.11.2026)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.cv_service_title_repair import MARKER, planned_change

ROLE = "Senior Fullstack Developer (.NET + React)"
OLD_FILE = "ZOB-3156_usługi programistyczne_Ewa Fikcyjna.docx"
NEW_FILE = f"ZOB-3156_{ROLE}_Ewa Fikcyjna.docx"


def _html(header: str) -> str:
    return f'<article class="cv"><h1>{header}</h1><hr><p>usługi programistyczne</p></article>'


def _plan(html, filename=OLD_FILE, role=ROLE, blind=False, custom=False):
    return planned_change(html, filename, role, blind=blind, custom_filename=custom)


def test_bad_header_and_file_get_the_role_and_keep_the_person():
    change = _plan(_html("usługi programistyczne – Ewa Fikcyjna"))
    assert change.html == _html(f"{ROLE} – Ewa Fikcyjna")
    assert change.filename == NEW_FILE
    assert change.old_position == "usługi programistyczne"


def test_only_the_header_changes_in_the_body():
    change = _plan(_html("usługi programistyczne – Ewa Fikcyjna"))
    assert change.html.endswith("<p>usługi programistyczne</p></article>")


def test_dash_inside_the_service_name_stays_out_of_the_person():
    change = _plan(
        _html("Usługi programistycznej – Bazy Danych – Ewa Fikcyjna"),
        filename="ZOB-3109_Usługi programistycznej – Bazy Danych_Ewa Fikcyjna.docx",
    )
    assert change.html == _html(f"{ROLE} – Ewa Fikcyjna")


def test_blind_header_has_no_person_to_keep():
    change = _plan(_html("usługi programistyczne"), blind=True)
    assert change.html == _html(ROLE)


def test_header_fixed_by_a_person_stays_and_the_file_follows_it():
    change = _plan(_html("Programista Fullstack – Ewa Fikcyjna"))
    assert change.html is None
    assert change.filename == "ZOB-3156_Programista Fullstack_Ewa Fikcyjna.docx"


def test_without_a_role_the_bad_header_and_file_stay():
    bad = _html("usługi programistyczne – Ewa")
    assert _plan(bad, role="usługi programistyczne") is None
    assert _plan(bad, role="") is None


def test_filename_set_by_hand_stays():
    change = _plan(_html("usługi programistyczne – Ewa Fikcyjna"), custom=True)
    assert change.filename is None
    assert change.html == _html(f"{ROLE} – Ewa Fikcyjna")


def test_reserved_characters_leave_the_filename_and_the_header_is_escaped():
    change = _plan(
        _html("usługi programistyczne – Ewa Fikcyjna"),
        role="Data & BI Engineer (SQL / SSIS)",
    )
    assert "<h1>Data &amp; BI Engineer (SQL / SSIS) – Ewa Fikcyjna</h1>" in change.html
    assert change.filename == "ZOB-3156_Data & BI Engineer (SQL SSIS)_Ewa Fikcyjna.docx"


def test_header_with_markup_is_not_guessed():
    change = _plan("<h1><span>usługi programistyczne</span> – Ewa</h1>")
    assert change.html is None
    assert change.filename == NEW_FILE


@pytest.mark.parametrize("filename", [None, "CV_Ewa.docx", "ZOB-1_Tester_Ewa.docx"])
def test_other_files_stay(filename):
    assert _plan(_html("Tester – Ewa"), filename=filename) is None


def test_entrypoint_runs_the_repair_once():
    entrypoint = (Path(__file__).parents[1] / "entrypoint.sh").read_text()
    assert f'run_unless_marked "{MARKER}"' in entrypoint
