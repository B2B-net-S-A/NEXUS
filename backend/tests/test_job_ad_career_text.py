"""Strona kariery z ogłoszenia (21.10.2026) — mapowanie treści, bez bazy.

Reguły: ``docs/claude/rekrutacja-tworzenie/ogloszenie-jedna-tresc-strona-kariery.md``.
"""

from __future__ import annotations

from app.services import job_public_profile as jpp
from app.services.job_ad.career import career_text


def test_lead_becomes_subtitle_and_duties_follow_the_project():
    text = career_text(
        {
            "lead": "Szukamy osoby do zespołu płatności.",
            "about": "Zespół buduje mikroserwisy.\n\nPraca w Scrumie.",
            "responsibilities": ["rozwój w Javie.", "przeglądy kodu;", "  "],
        },
        "pl",
    )
    assert text.subtitle == "Szukamy osoby do zespołu płatności"
    assert text.about == (
        "Zespół buduje mikroserwisy.\n\nPraca w Scrumie.\n\n"
        "Czym się zajmiesz: rozwój w Javie; przeglądy kodu."
    )


def test_english_ad_gets_an_english_duties_heading():
    text = career_text({"responsibilities": ["code reviews"]}, "en")
    assert text.subtitle is None
    assert text.about == "What you will do: code reviews."


def test_empty_ad_gives_nothing_to_publish():
    text = career_text({"lead": " ", "about": "", "responsibilities": []}, "pl")
    assert text.subtitle is None and text.about is None


def test_invisible_characters_never_reach_the_page():
    # „‮” odwraca kierunek tekstu: kontrola czyta tekst bez niego.
    text = career_text({"lead": "Stawka‮ 081 zł‬", "about": "A­B"}, "pl")
    assert "‮" not in (text.subtitle or "")
    assert text.about == "AB"


def test_about_is_cut_at_a_paragraph_never_mid_sentence():
    long_paragraph = "x" * (jpp.ABOUT_MAX - 10)
    text = career_text(
        {"about": f"{long_paragraph}\n\nDrugi akapit, który się nie zmieści."}, "pl"
    )
    assert text.about == long_paragraph


# ── „Wymagane” z punktów ogłoszenia (29.10.2026) ────────────────────────────


def _job_with_search_words():
    from types import SimpleNamespace

    return SimpleNamespace(
        client_id=7,
        title="Kierownik Projektów",
        champion_profile={},
        must_skills=["bankowości", "dostawców zewnętrznych"],
        nice_skills=["Ferryt"],
        location="Warszawa",
        remote_policy=None,
        onsite_days_per_week=None,
        onsite_days_per_month=None,
        seniority=None,
    )


def _payload(sections, **kwargs):
    return jpp.public_job_payload(
        _job_with_search_words(),
        title="Kierownik Projektów",
        link_slug="kierownik-projektow",
        subtitle=None,
        about="Opis.",
        sections=sections,
        **kwargs,
    )


def test_ad_points_are_cleaned_and_limited():
    from app.services.job_ad.career import career_points

    points = career_points(
        {
            "requirements": [
                "Doświadczenie   w zarządzaniu projektami w bankowości",
                "  ",
                *[f"Punkt {i}" for i in range(20)],
            ],
            "nice_to_have": ["Znajomość ‮systemu Ferryt"],
        }
    )
    assert points is not None
    assert points["must"][0] == "Doświadczenie w zarządzaniu projektami w bankowości"
    assert len(points["must"]) == 15
    assert points["nice"] == ["Znajomość systemu Ferryt"]


def test_ad_without_points_keeps_search_words_on_the_page():
    from app.services.job_ad.career import career_points

    assert career_points({"requirements": [], "nice_to_have": [" "]}) is None
    payload = _payload(jpp.normalize_sections(None))
    assert [m["name"] for m in payload["must"]] == [
        "bankowości",
        "dostawców zewnętrznych",
    ]


def test_page_shows_ad_points_saved_at_approval_instead_of_search_words():
    points = jpp.requirement_points(
        ["Doświadczenie w zarządzaniu projektami w sektorze bankowym"],
        ["Znajomość systemu Ferryt"],
    )
    snapshot = {
        "must": ["bankowości"],
        "nice": ["Ferryt"],
        jpp.APPROVED_POINTS_KEY: points,
    }
    sections = jpp.sections_with_approved_content(None, snapshot)

    page = _payload(sections, points=jpp.approved_points(sections))
    assert page["must"] == [
        {
            "name": "Doświadczenie w zarządzaniu projektami w sektorze bankowym",
            "note": None,
        }
    ]
    assert page["nice"] == ["Znajomość systemu Ferryt"]
    # Tablica, plakat i portale dalej dostają słowa z migawki.
    assert [m["name"] for m in _payload(sections)["must"]] == ["bankowości"]


def test_hidden_requirements_section_hides_ad_points_too():
    points = jpp.requirement_points(["Doświadczenie w bankowości"], [])
    sections = jpp.sections_with_approved_content(
        {"must": False}, {"must": [], "nice": [], jpp.APPROVED_POINTS_KEY: points}
    )
    assert _payload(sections, points=jpp.approved_points(sections))["must"] == []


def test_malformed_points_in_snapshot_fall_back_to_search_words():
    sections = jpp.sections_with_approved_content(
        None, {"must": ["bankowości"], "nice": [], jpp.APPROVED_POINTS_KEY: ["x"]}
    )
    assert jpp.approved_points(sections) is None
