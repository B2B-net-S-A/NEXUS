"""Stanowisko i opis roli w zaproszeniu na prep (26.10.2026, D1–D3).

Kształty Championa z produkcji, nazwy i treści fikcyjne.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import prep_role

CHAMPION = {
    "basics": {
        "role_name": "Senior ETL / Snowflake Engineer",
        "work_mode": "hybrydowo",
        "onsite_days_per_week": 3,
        "candidate_location_pref": "Warszawa, Gdańsk",
        "rate_value": 180.0,
    },
    "project": {
        "about": "Projekt hurtowni danych dla banku.",
        "responsibilities": "Projektowanie procesów ETL/ELT; analiza wymagań; "
        "uzgadnianie logiki z interesariuszami.",
    },
    "stack": {
        "must": [{"name": "Snowflake"}, {"name": "SQL"}],
        "nice": [{"name": "Data Vault"}, {"name": "SQL"}, {"name": "Basel"}],
        "notes": "Long English stack notes that never reach the candidate.",
    },
    "experience": {
        "domains": [
            {"name": "Risk Management", "level": "must"},
            {"name": "Treasury", "level": "nice"},
        ],
        "regulations": [{"name": "Basel", "level": "nice"}],
    },
    "search": {"disqualifiers": ["Tylko body leasing"]},
    "client": {"selling_points": "Stawka do negocjacji z klientem"},
}


def _job(champion=CHAMPION, **overrides):
    values = dict(
        title="PL_IT_Developer_expert_TP#40379 (43020)",
        client_reference="43020",
        client_id=None,
        champion_profile=champion,
        must_skills=[],
        nice_skills=[],
        remote_policy=None,
        onsite_days_per_week=None,
        onsite_days_per_month=None,
        location=None,
        seniority=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


async def test_title_prefers_the_champion_role_name(monkeypatch) -> None:
    async def names(db, client_id):
        return ["Bank Północny"]

    monkeypatch.setattr(prep_role, "_client_names", names)
    assert await prep_role.title(None, _job()) == (
        "Senior ETL / Snowflake Engineer",
        prep_role.SOURCE_CHAMPION,
    )


async def test_code_in_the_champion_falls_back_to_the_cleaned_client_title(
    monkeypatch,
) -> None:
    async def names(db, client_id):
        return []

    monkeypatch.setattr(prep_role, "_client_names", names)
    champion = {**CHAMPION, "basics": {"role_name": "RITM0867849 Senior Developer"}}
    assert await prep_role.title(None, _job(champion)) == (
        "IT Developer expert",
        prep_role.SOURCE_CLIENT,
    )
    assert await prep_role.title(None, _job({})) == (
        "IT Developer expert",
        prep_role.SOURCE_CLIENT,
    )


@pytest.mark.parametrize(
    "value,expected",
    [
        ("PL_IT_Developer_expert_TP#40379", True),
        ("IngestOps - CoreCDP - Replacement for Jan K", True),
        ("Senior Developer RITM0867849", True),
        ("(43020)", True),
        ("", True),
        ("Senior ETL / Snowflake Engineer", False),
        ("SQL Server 2019 Administrator", False),
        # Przegląd PR-a: „#” to kod tylko z numerem — „C#”, „F#” to role.
        ("C# Developer", False),
        ("Senior C#/.NET Developer", False),
        ("F# Engineer", False),
        ("Developer TP# 40379", True),
    ],
)
def test_looks_like_code(value, expected) -> None:
    assert prep_role.looks_like_code(value) is expected


def test_description_is_built_from_the_champion_without_money_or_team_notes() -> None:
    text = prep_role.description(_job())
    assert text.split("\n\n") == [
        "Projekt hurtowni danych dla banku.",
        "Zakres obowiązków:\n• Projektowanie procesów ETL/ELT\n• analiza wymagań\n"
        "• uzgadnianie logiki z interesariuszami",
        "Wymagania kluczowe: Snowflake, SQL\n"
        "Doświadczenie: Risk Management\n"
        "Mile widziane: Data Vault, Basel, Treasury\n"
        "Tryb pracy: hybrydowo, 3 dni w tygodniu w biurze · Warszawa, Gdańsk",
    ]
    for hidden in ("180", "Stawka", "body leasing", "English stack notes"):
        assert hidden not in text


def test_no_project_and_no_duties_means_no_description() -> None:
    champion = {**CHAMPION, "project": {}}
    assert prep_role.description(_job(champion)) == ""
    assert prep_role.description(_job({})) == ""


def test_nice_to_have_is_capped() -> None:
    champion = {
        **CHAMPION,
        "stack": {"must": [], "nice": [{"name": f"Tool {i}"} for i in range(12)]},
        "experience": {},
    }
    line = prep_role.description(_job(champion)).split("Mile widziane: ")[1]
    assert line.split("\n")[0].count(",") == prep_role.NICE_MAX - 1


def test_findings_catch_amounts_and_contacts() -> None:
    assert prep_role.findings("Stawka 180 zł/h, pisz na jan@example.com")
    assert prep_role.findings(prep_role.description(_job())) == []
