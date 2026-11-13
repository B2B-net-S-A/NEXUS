"""Historia karty od botów (decyzja Artura z 13.11.2026), bez bazy. Dane fikcyjne."""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.sales import bot_card_history as history

SRC = "https://rejestr.example/firma"
T1 = datetime(2026, 11, 13, 2, 14, tzinfo=timezone.utc)
T2 = datetime(2026, 11, 13, 2, 16, tzinfo=timezone.utc)


def _enrich_payload() -> dict:
    return {
        "fields": {
            "nip": {"value": "1234563218", "source": SRC},
            "hq_city": {"value": "Kraków", "source": SRC},
            "domain": {"value": "firma.example", "source": SRC},
            "tier": {"value": "enterprise", "employees": "1000+", "source": SRC},
        },
        "outcomes": {
            "nip": {"result": "applied", "previous": None},
            "hq_city": {"result": "kept", "current": "Gdańsk"},
            "domain": {"result": "taken", "other_id": 8, "other_name": "Inna Karta"},
            "tier": {"result": "applied", "previous": "smb"},
        },
    }


def test_enrich_lines_show_what_changed_what_stayed_and_why() -> None:
    lines = {line.label: line for line in history.enrich_lines(_enrich_payload())}
    assert (lines["NIP"].before, lines["NIP"].after, lines["NIP"].note) == (
        None,
        "1234563218",
        None,
    )
    assert (lines["Miasto"].before, lines["Miasto"].after) == ("Gdańsk", "Kraków")
    assert lines["Miasto"].note == history.KEPT_NOTE
    assert (lines["Domena"].other_company_id, lines["Domena"].other_company_name) == (
        8,
        "Inna Karta",
    )
    assert (lines["Wielkość"].before, lines["Wielkość"].after) == ("Mała", "Duża")
    assert lines["NIP"].source == SRC


def test_old_manual_results_show_only_accepted_fields() -> None:
    payload = {
        "fields": {
            "nip": {"value": "1234563218", "source": SRC},
            "hq_city": {"value": "Kraków", "source": SRC},
        },
        "decisions": {"nip": "accepted", "hq_city": "rejected"},
    }
    assert [line.label for line in history.enrich_lines(payload)] == ["NIP"]


def test_people_lines_list_only_people_added_to_the_map() -> None:
    payload = {
        "people": [
            {
                "line": 1,
                "full_name": "Anna Przykładowa",
                "title": "CTO",
                "source_url": SRC,
            },
            {"line": 2, "full_name": "Ewa Testowa", "title": "CIO", "source_url": SRC},
        ],
        "outcomes": {"1": "added", "2": "on_map"},
    }
    [line] = history.people_lines(payload)
    assert (line.label, line.after, line.source) == ("Anna Przykładowa", "CTO", SRC)


def test_build_sorts_newest_first_and_hides_people_without_edit() -> None:
    rows = [
        ("enrich", T1, _enrich_payload()),
        (
            "people",
            T2,
            {"people": [{"line": 1, "full_name": "Anna"}], "outcomes": {"1": "added"}},
        ),
        ("enrich", T2, {"fields": {}, "outcomes": {}}),
    ]
    full = history.build(rows, with_people=True)
    assert [(e.bot, e.at) for e in full] == [("Kontakty", T2), ("Dane firm", T1)]
    viewer = history.build(rows, with_people=False)
    assert [e.bot for e in viewer] == ["Dane firm"]
