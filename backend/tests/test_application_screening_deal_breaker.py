"""„Odpada, gdy…” w przeglądzie zgłoszeń AI (04.10.2026) — plakietka, nie bramka.

Bez bazy.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services import application_screening as svc
from app.services.process_entry_meta import (
    application_screening_badge,
    application_screening_entry_meta,
)

CV = "Tester manualny. Szukam wyłącznie pracy zdalnej, bez wyjazdów do biura."
JOB = SimpleNamespace(
    title="Tester automatyzujący",
    working_title=None,
    champion_profile={
        "screening_questions": [
            {"id": "q1", "question": "Biuro?", "deal_breaker": "Tylko praca zdalna."},
            {"id": "q2", "question": "Selenium?", "deal_breaker": ""},
            {
                "id": "q3",
                "question": "Znowu biuro?",
                "deal_breaker": "Tylko praca zdalna.",
            },
        ]
    },
    must_skills=[],
    nice_skills=[],
)


def test_conditions_come_from_champion_questions_without_duplicates() -> None:
    assert svc.deal_breaker_conditions(JOB) == ["Tylko praca zdalna."]
    assert svc.deal_breaker_conditions(SimpleNamespace(champion_profile=None)) == []


def test_job_block_lists_the_conditions(monkeypatch) -> None:
    import app.services.requirement_contract as contract

    monkeypatch.setattr(contract, "requirements_for_job", lambda job: [])
    monkeypatch.setattr(contract, "requirement_labels", lambda reqs: {})
    block = svc.job_prompt_block(JOB)
    assert "Odpada, gdy:" in block
    assert "- Tylko praca zdalna." in block


def test_hit_needs_a_known_condition_and_a_quote_from_the_cv() -> None:
    raw = (
        '{"verdict": "unclear", "reasons": [], "deal_breaker": '
        '{"condition": "tylko praca zdalna.", "quote": "wyłącznie pracy zdalnej"}}'
    )
    hit = svc.keep_quoted_deal_breaker(raw, ["Tylko praca zdalna."], [CV])
    assert hit == {
        "condition": "Tylko praca zdalna.",
        "quote": "wyłącznie pracy zdalnej",
    }

    invented_quote = raw.replace("wyłącznie pracy zdalnej", "nie lubi biura")
    assert (
        svc.keep_quoted_deal_breaker(invented_quote, ["Tylko praca zdalna."], [CV])
        is None
    )

    unknown_condition = raw.replace("tylko praca zdalna.", "Brak Selenium.")
    assert (
        svc.keep_quoted_deal_breaker(unknown_condition, ["Tylko praca zdalna."], [CV])
        is None
    )
    assert svc.keep_quoted_deal_breaker('{"deal_breaker": null}', ["x"], [CV]) is None
    assert svc.keep_quoted_deal_breaker("bez JSON-a", ["x"], [CV]) is None


def test_decide_ignores_the_deal_breaker() -> None:
    # Werdykt nie zależy od trafienia — `decide` nie ma takiego wejścia.
    assert (
        svc.decide(model_verdict="fits", kept_reasons=[], must_found=0, must_total=0)
        == "fits"
    )


def test_entry_meta_and_badge_carry_the_hit() -> None:
    meta = application_screening_entry_meta(
        verdict="fits",
        assessed=True,
        must_found=1,
        must_total=2,
        deal_breaker="Tylko praca zdalna.",
    )
    assert meta["deal_breaker_hit"] is True
    badge = application_screening_badge(meta)
    assert badge["deal_breaker_hit"] is True
    assert badge["deal_breaker"] == "Tylko praca zdalna."

    clean = application_screening_entry_meta(
        verdict="fits", assessed=True, must_found=1, must_total=2
    )
    assert "deal_breaker_hit" not in clean
    assert application_screening_badge(clean)["deal_breaker_hit"] is False


def test_entry_meta_from_result_passes_the_condition() -> None:
    result = svc.ScreeningResult(
        verdict="unclear",
        model="m",
        deal_breaker={"condition": "Tylko praca zdalna.", "quote": "x"},
    )
    meta = svc.entry_meta(result)
    assert meta["deal_breaker"] == "Tylko praca zdalna."
    # Cytat z CV nie trafia do entry_meta procesu.
    assert "quote" not in str(meta)


def test_prompt_v2_asks_for_a_quoted_deal_breaker() -> None:
    from app.services.llm_prompts import APPLICATION_SCREENING

    assert APPLICATION_SCREENING.version == 2
    rendered = APPLICATION_SCREENING.render(job="rola", cv="cv")
    assert '"deal_breaker"' in rendered
