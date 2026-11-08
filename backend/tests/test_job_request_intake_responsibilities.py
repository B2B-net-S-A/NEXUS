"""„Obowiązki” z requestu klienta: każdy obowiązek osobnym punktem po polsku.

Decyzja Artura z 07.11.2026 (wariant B): do tej daty odczyt maila streszczał
12–57 punktów obowiązków do jednego zdania (51 z 60 świeżych profili miało
„Obowiązki” w jednej linii), a Delivery Leadzi wklejali potem listę ręcznie.
"""

import pytest

from app.services import job_request_intake as intake
from app.services.job_request_intake import normalize_model_output


@pytest.fixture(autouse=True)
def _empty_skill_catalog(monkeypatch) -> None:
    from app.services import keyword_suggest

    monkeypatch.setattr(keyword_suggest, "_catalog", ())


REQUEST = "Project lead AMLR. Detailed description of work task to be carried out."

REPEATED = (
    "- Klasyfikowanie luk według krytyczności i wskazywanie działań tymczasowych."
)


def test_every_point_stays_and_repeated_points_are_dropped() -> None:
    raw = {
        "responsibilities": "\n".join(
            [
                "Obowiązki:",
                "Wymiana informacji w skali grupy:",
                "- Koordynacja interesariuszy biznesowych, compliance i prawnych.",
                REPEATED,
                "Pozyskiwanie i raportowanie danych:",
                "- Współpraca z GFCP przy wymaganiach danych dla TM, KYC, Fraud i Sanctions.",
                REPEATED,
                "Poprawa jakości danych:",
                REPEATED,
            ]
        )
    }

    result = normalize_model_output(raw, REQUEST)

    assert result.responsibilities == "\n".join(
        [
            "Wymiana informacji w skali grupy:",
            "- Koordynacja interesariuszy biznesowych, compliance i prawnych.",
            REPEATED,
            "Pozyskiwanie i raportowanie danych:",
            "- Współpraca z GFCP przy wymaganiach danych dla TM, KYC, Fraud i Sanctions.",
        ]
    )


def test_points_without_dash_are_normalized_to_one_list() -> None:
    raw = {
        "responsibilities": "• Projektowanie API GraphQL\n*  Code review\n\n– Dokumentacja"
    }

    result = normalize_model_output(raw, REQUEST)

    assert result.responsibilities == (
        "- Projektowanie API GraphQL\n- Code review\n- Dokumentacja"
    )


def test_list_from_the_model_becomes_points() -> None:
    raw = {"responsibilities": ["Projektowanie API GraphQL", "- Code review", ""]}

    result = normalize_model_output(raw, REQUEST)

    assert result.responsibilities == "- Projektowanie API GraphQL\n- Code review"


def test_prose_without_a_list_stays_as_written() -> None:
    raw = {"responsibilities": "Rozwój systemu płatności i współpraca z zespołem."}

    result = normalize_model_output(raw, REQUEST)

    assert (
        result.responsibilities == "Rozwój systemu płatności i współpraca z zespołem."
    )


def test_long_list_ends_on_a_whole_point_and_says_how_many_did_not_fit() -> None:
    point = "- " + "Projektowanie architektury integracji Dynamics 365 i Azure " * 2
    raw = {"responsibilities": "\n".join(f"{point}{i}." for i in range(60))}

    result = normalize_model_output(raw, REQUEST)

    kept = result.responsibilities.split("\n")
    assert len(result.responsibilities) <= intake.MAX_RESPONSIBILITIES_CHARS
    assert all(line.endswith(".") for line in kept)
    dropped = 60 - len(kept)
    assert dropped > 0
    assert any(
        note.startswith("Obowiązki: pominięte punkty") and f": {dropped} " in note
        for note in result.advisories
    )


def test_group_title_without_points_left_is_dropped() -> None:
    raw = {"responsibilities": f"Obszar A:\n{REPEATED}\nObszar B:\n{REPEATED}"}

    result = normalize_model_output(raw, REQUEST)

    assert result.responsibilities == f"Obszar A:\n{REPEATED}"


def test_prompt_asks_for_every_duty_in_polish_instead_of_a_summary() -> None:
    from app.services.llm_prompts import JOB_REQUEST_INTAKE

    rendered = JOB_REQUEST_INTAKE.render(
        client_name="Klient", client_context="brak", request_text="mail"
    )
    assert JOB_REQUEST_INTAKE.version >= 15
    assert "obowiązki, krótko po polsku" not in rendered
    assert "Jeden punkt = jeden obowiązek" in rendered
    assert "Nie kopiuj zdań klienta" in rendered
