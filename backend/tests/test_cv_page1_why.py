"""Zdania 1–3 „Dlaczego nasz kandydat” na stronę 1 Nowego CV — sprawdzenie i bieg.

Bez bazy: kontrola zdań modelu (`cv_page1_why_checks`), scalenie slotów
z poprawkami rekrutera, wybór odpowiedzi screeningu, łańcuch HTML → model →
sloty z atrapą modelu i sesji. Trasa `PATCH …/cv/page1` z `why`:
`test_cv_page1.py`. Dane fikcyjne.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import pytest

from app.core.config import settings
from app.services import cv_page1_results as service
from app.services import cv_page1_why as why_service
from app.services.cv_generator_b2b.html_export import render_interactive_html
from app.services.cv_layout import compose_page1_why
from app.services.cv_page1_result_checks import RoleSource
from app.services.cv_page1_why_checks import (
    ISSUE_BAD_ROLES,
    ISSUE_COMPANY_NAMED,
    ISSUE_GENDERED,
    ISSUE_LABEL,
    ISSUE_METHOD_NOT_IN_CV,
    ISSUE_MUST_NOT_IN_QUOTE,
    ISSUE_MUST_UNKNOWN,
    ISSUE_MUST_WITHOUT_PROOF,
    ISSUE_NO_INPUT,
    ISSUE_NOT_ONE_SENTENCE,
    ISSUE_NUMBER_NOT_IN_CV,
    ISSUE_QUOTE_NOT_IN_CV,
    ISSUE_TOO_LONG,
    WhyContext,
    WhyInputs,
    auto_texts,
    check_experience,
    check_key_task,
    check_requirements,
    merged_why,
    verify_why,
)

ROLES = (
    RoleSource(
        index=0,
        company="Acme Bank",
        position="Test Manager",
        dates="01.2021 - 12.2025",
        duties=(
            "Prowadzenie zespołu 6 testerów w programie migracji systemu płatności "
            "do chmury w metodyce Scrum.",
            "Automatyzacja testów API w Postman i Java, 1 200 przypadków testowych.",
        ),
        technologies=("Postman", "Java", "Jira"),
    ),
    RoleSource(
        index=1,
        company="Example Logistics",
        position="Tester",
        dates="01.2017 - 12.2020",
        duties=("Testy regresyjne systemu magazynowego w Selenium i Java.",),
        technologies=("Selenium", "Java"),
    ),
    RoleSource(
        index=2,
        company="Sklep Przykład",
        position="Sprzedawca",
        dates="2015 - 2016",
        duties=("Obsługa klientów sklepu.",),
        technologies=(),
    ),
)
# 2021–2025: 5 lat; 2017–2025 bez przerw: 9 lat.
SPANS = ((2021.0, 2026.0), (2017.0, 2021.0), (2015.0, 2016.0))
WHY = ("Ponad 8 lat doświadczenia jako tester", "Postman, Java i Selenium")
INPUTS = WhyInputs(
    must=("Java", "Postman", "Kubernetes"),
    key_task="Migracja systemu płatności do chmury",
    answer="Przy migracji przenieśliśmy 40 usług bez przestoju w ciągu pół roku.",
)


def _ctx(*, blind: bool = False, inputs: WhyInputs = INPUTS) -> WhyContext:
    return WhyContext(
        roles=ROLES,
        spans=SPANS,
        why_points=WHY,
        cv_text=" ".join(r.text for r in ROLES),
        language="pl",
        blind=blind,
        inputs=inputs,
    )


EXPERIENCE = {
    "text": "{LATA_IT} w IT, w tym {LATA_ROLA} jako Test Manager, w bankowości "
    "i logistyce, przez ten czas w zespołach pracujących w Scrum",
    "it_roles": [0, 1],
    "role_roles": [0],
}
REQUIREMENTS = {
    "text": "**Java i Postman** w testach API systemu płatności w Acme Bank",
    "evidence": [
        {
            "must": "Java",
            "quote": "Automatyzacja testów API w Postman i Java",
            "company": "Acme Bank",
        },
        {
            "must": "postman",
            "quote": "testów API w Postman i Java, 1 200 przypadków",
            "company": "Acme Bank",
        },
    ],
}
KEY_TASK_CV = {
    "text": "Migracja systemu płatności do chmury w Acme Bank z zespołem "
    "**6 testerów**",
    "quote": "zespołu 6 testerów w programie migracji systemu płatności do chmury",
    "source": "cv",
    "company": "Acme Bank",
}


# ── Zdanie 1: lata z dat, metodyka z CV ─────────────────────────────────────


def test_years_come_from_dates_not_from_the_model():
    out = check_experience(EXPERIENCE, _ctx())
    assert out["verified"] is True, out
    assert out["text"].startswith("**9 lat** w IT, w tym **5 lat** jako Test Manager")
    assert out["roles"] == [0, 1]


def test_retail_job_is_not_counted_when_the_model_leaves_it_out():
    with_shop = {**EXPERIENCE, "it_roles": [0, 1, 2]}
    # 2015–2016 + 2017–2025 = 10 lat; bez sklepu 9.
    assert check_experience(with_shop, _ctx())["text"].startswith("**10 lat** w IT")


def test_number_typed_by_the_model_must_be_in_point_1_or_dates():
    typed = {**EXPERIENCE, "text": "12 lat w IT jako Test Manager"}
    assert check_experience(typed, _ctx())["issue"] == ISSUE_NUMBER_NOT_IN_CV
    from_point = {**EXPERIENCE, "text": "Ponad 8 lat w IT jako Test Manager"}
    assert check_experience(from_point, _ctx())["verified"] is True
    since = {**EXPERIENCE, "text": "{LATA_IT} w IT, od 2017 jako tester"}
    assert check_experience(since, _ctx())["verified"] is True


@pytest.mark.parametrize(
    "item",
    [
        {**EXPERIENCE, "it_roles": [9]},
        {**EXPERIENCE, "it_roles": "0"},
        {**EXPERIENCE, "role_roles": []},
        {**EXPERIENCE, "text": "{LATA_XX} w IT"},
    ],
)
def test_bad_role_indexes_or_tokens_are_refused(item):
    assert check_experience(item, _ctx())["issue"] == ISSUE_BAD_ROLES


def test_methodology_must_stand_in_the_cv():
    kanban = {**EXPERIENCE, "text": "{LATA_IT} w IT, w zespołach pracujących w Kanban"}
    assert check_experience(kanban, _ctx())["issue"] == ISSUE_METHOD_NOT_IN_CV


def test_gendered_form_is_refused():
    gendered = {**EXPERIENCE, "text": "{LATA_IT} w IT, pracował w zespołach Scrum"}
    assert check_experience(gendered, _ctx())["issue"] == ISSUE_GENDERED


def test_year_only_dates_and_short_tenure():
    ctx = _ctx()
    short = WhyContext(**{**ctx.__dict__, "spans": ((2025.0, 2025.5),) + SPANS[1:]})
    item = {"text": "{LATA_ROLA} jako Test Manager", "it_roles": [], "role_roles": [0]}
    assert check_experience(item, short)["text"].startswith("**6 mies.** jako")
    no_dates = WhyContext(**{**ctx.__dict__, "spans": (None,) + SPANS[1:]})
    assert check_experience(item, no_dates)["issue"] == ISSUE_BAD_ROLES


# ── Zdanie 2: MUST potwierdzone cytatem ─────────────────────────────────────


def test_requirements_with_quotes_are_verified():
    out = check_requirements(REQUIREMENTS, _ctx())
    assert out["verified"] is True, out
    assert {e["must"] for e in out["evidence"]} == {"Java", "Postman"}
    assert out["evidence"][0]["company"] == "Acme Bank"


def test_must_named_without_proof_is_refused():
    item = {**REQUIREMENTS, "text": "**Java, Postman i Kubernetes** w Acme Bank"}
    assert check_requirements(item, _ctx())["issue"] == ISSUE_MUST_WITHOUT_PROOF


def test_evidence_must_name_a_must_from_the_profile():
    item = {
        **REQUIREMENTS,
        "evidence": [{**REQUIREMENTS["evidence"][0], "must": "Selenium"}],
    }
    assert check_requirements(item, _ctx())["issue"] == ISSUE_MUST_UNKNOWN


def test_quote_must_be_in_the_cv_and_carry_the_must():
    invented = {
        **REQUIREMENTS,
        "evidence": [
            {
                "must": "Java",
                "quote": "Budowa mikroserwisów w Java od zera",
                "company": "",
            }
        ],
    }
    assert check_requirements(invented, _ctx())["issue"] == ISSUE_QUOTE_NOT_IN_CV
    # Cytat z roli bez Javy w punkcie ani w technologiach roli.
    shop = WhyContext(
        **{
            **_ctx().__dict__,
            "roles": ROLES[:1]
            + (
                RoleSource(
                    1, "Example Logistics", "Tester", "2017", ROLES[1].duties, ()
                ),
            ),
        }
    )
    other = {
        "text": "**Java** w Example Logistics",
        "evidence": [
            {
                "must": "Java",
                "quote": "Testy regresyjne systemu magazynowego w Selenium",
                "company": "Example Logistics",
            }
        ],
    }
    assert check_requirements(other, shop)["issue"] == ISSUE_MUST_NOT_IN_QUOTE


def test_no_must_in_profile_means_no_sentence_2():
    out = check_requirements(REQUIREMENTS, _ctx(inputs=WhyInputs()))
    assert out["issue"] == ISSUE_NO_INPUT


def test_label_from_the_mockup_is_refused():
    item = {**REQUIREMENTS, "text": "Z wymagań klienta: **Java i Postman** w Acme Bank"}
    assert check_requirements(item, _ctx())["issue"] == ISSUE_LABEL


# ── Zdanie 3: najważniejsze zadanie z dowodem ───────────────────────────────


def test_key_task_with_cv_proof_is_verified():
    out = check_key_task(KEY_TASK_CV, _ctx())
    assert out["verified"] is True, out
    assert out["company"] == "Acme Bank"
    assert out["source"] == "cv"


def test_key_task_with_screening_proof_is_verified():
    item = {
        "text": "Migracja systemu płatności do chmury — **40 usług** przeniesionych "
        "bez przestoju",
        "quote": "przenieśliśmy 40 usług bez przestoju",
        "source": "screening",
        "company": "",
    }
    out = check_key_task(item, _ctx())
    assert out["verified"] is True, out
    wrong = {**item, "quote": "przenieśliśmy 50 usług bez przestoju"}
    assert check_key_task(wrong, _ctx())["issue"] == ISSUE_QUOTE_NOT_IN_CV
    invented = {**item, "text": "Migracja systemu płatności — **400 usług** w chmurze"}
    assert check_key_task(invented, _ctx())["issue"] == ISSUE_NUMBER_NOT_IN_CV


def test_key_task_label_and_two_sentences_are_refused():
    label = {
        **KEY_TASK_CV,
        "text": "Najważniejsze zadanie w tej roli to migracja w Acme Bank",
    }
    assert check_key_task(label, _ctx())["issue"] == ISSUE_LABEL
    two = {**KEY_TASK_CV, "text": "Migracja w Acme Bank. Zespół 6 testerów."}
    assert check_key_task(two, _ctx())["issue"] == ISSUE_NOT_ONE_SENTENCE
    long = {**KEY_TASK_CV, "text": "Migracja " + "systemu płatności " * 20}
    assert check_key_task(long, _ctx())["issue"] == ISSUE_TOO_LONG


def test_profile_without_key_task_means_no_sentence_3():
    out = check_key_task(KEY_TASK_CV, _ctx(inputs=WhyInputs(must=("Java",))))
    assert out["issue"] == ISSUE_NO_INPUT


def test_blind_cv_sentences_never_name_a_company():
    for check, item in (
        (check_requirements, REQUIREMENTS),
        (check_key_task, KEY_TASK_CV),
    ):
        assert check(item, _ctx(blind=True))["issue"] == ISSUE_COMPANY_NAMED
    anon = {**KEY_TASK_CV, "text": "Migracja systemu płatności do chmury w banku"}
    assert check_key_task(anon, _ctx(blind=True))["verified"] is True


# ── Sloty, scalenie, strona 1 ───────────────────────────────────────────────


def test_unverified_sentence_falls_back_to_todays_point():
    generated = verify_why(
        {
            "experience": EXPERIENCE,
            "requirements": {**REQUIREMENTS, "text": "Z wymagań klienta: Java"},
            "key_task": KEY_TASK_CV,
        },
        _ctx(),
    )
    assert [g["verified"] for g in generated] == [True, False, True]
    extras = merged_why(None, generated, "sha")
    assert extras["why"][1] == ""
    page1 = compose_page1_why(list(WHY) + ["Punkt 3."], extras)
    assert page1[0].startswith("**9 lat** w IT")
    assert page1[1] == WHY[1]
    assert page1[2].startswith("Migracja systemu płatności")


def test_merge_keeps_slots_edited_by_the_recruiter():
    first = [
        {"slot": "experience", "text": "Stare 1.", "verified": True},
        {"slot": "requirements", "text": "Stare 2.", "verified": True},
        {"slot": "key_task", "text": "", "verified": False, "issue": "empty"},
    ]
    extras = merged_why({"wreath": "cert"}, first, "a")
    assert extras["why"] == ["Stare 1.", "Stare 2.", ""]
    extras["why"] = ["Stare 1.", "Moje 2.", ""]
    second = [
        {"slot": "experience", "text": "Nowe 1.", "verified": True},
        {"slot": "requirements", "text": "Nowe 2.", "verified": True},
        {"slot": "key_task", "text": "Nowe 3.", "verified": True},
    ]
    after = merged_why(extras, second, "b")
    assert after["why"] == ["Nowe 1.", "Moje 2.", "Nowe 3."]
    assert after["wreath"] == "cert"
    assert after["why_source_sha"] == "b"
    assert auto_texts(after["why_generated"]) == ["Nowe 1.", "Nowe 2.", "Nowe 3."]


def test_parse_response_refuses_broken_answers():
    assert why_service.parse_response('```json\n{"experience": {}}\n```')
    for raw in ("", "[]", '{"x": 1}', "nie JSON"):
        with pytest.raises((ValueError, json.JSONDecodeError)):
            why_service.parse_response(raw)


# ── Wejście: odpowiedź na pytanie oznaczone `key_task` ──────────────────────

PROFILE = {
    "stack": {"must": [{"name": "Java"}, "Postman"]},
    "project": {"key_task": "Migracja systemu płatności do chmury"},
    "screening_questions": [
        {"id": "q1", "question": "Ile lat z Javą?"},
        {"id": "q2", "question": "Jak wyglądała Twoja migracja?", "key_task": True},
    ],
}


def test_answer_is_matched_by_stamped_question_text_then_id():
    sheet = {
        "answers": [
            # Pytania są pozycyjne: q1 tej odpowiedzi to dziś pytanie o migrację.
            {
                "question_id": "q1",
                "question_text": "Jak wyglądała Twoja migracja?",
                "response": "Przenieśliśmy 40 usług. Stawka 180 zł/h.",
            },
            {"question_id": "q2", "question_text": "Inne", "response": "Nie to."},
        ]
    }
    answer = why_service.key_task_answer(PROFILE, sheet)
    assert answer.startswith("Przenieśliśmy 40 usług.")
    assert "180" not in answer
    old_sheet = {"answers": [{"question_id": "q2", "response": "Bez przestoju."}]}
    assert why_service.key_task_answer(PROFILE, old_sheet) == "Bez przestoju."


def test_skipped_answer_never_reaches_the_model():
    sheet = {
        "answers": [
            {"question_id": "q2", "response": "Tajne.", "skipped": True},
        ]
    }
    assert why_service.key_task_answer(PROFILE, sheet) == ""
    inputs = why_service.inputs_from(PROFILE, sheet)
    assert inputs.must == ("Java", "Postman")
    assert inputs.key_task == "Migracja systemu płatności do chmury"
    assert inputs.answer == ""
    no_task = why_service.inputs_from({**PROFILE, "project": {}}, sheet)
    assert no_task.key_task == "" and no_task.answer == ""


def test_inputs_sha_changes_with_the_profile():
    a = why_service.inputs_sha("<p>x</p>", INPUTS)
    b = why_service.inputs_sha("<p>x</p>", WhyInputs(must=("Java",)))
    assert a != b
    assert a == why_service.inputs_sha("<p>x</p>", INPUTS)


def test_prompts_ask_for_tokens_and_no_labels():
    for lang in ("pl", "en"):
        prompt = why_service.system_prompt(lang, blind=False)
        assert "{LATA_IT}" in prompt and "{LATA_ROLA}" in prompt
    assert "Z wymagań klienta" in why_service.system_prompt("pl", blind=False)
    assert "Blind" in why_service.system_prompt("pl", blind=True)


# ── Bieg: HTML → model → sloty ──────────────────────────────────────────────

PAYLOAD = {
    "candidate_name": "Jan Przykładowy",
    "position": "Test Manager",
    "language": "pl",
    "blind": False,
    "highlight_keywords": [],
    "why_points": list(WHY) + ["Doświadczenie w testach API"],
    "education": [],
    "skills": [{"label": "Testowanie:", "content": "Postman, Selenium"}],
    "certifications": [],
    "languages": ["Polski - ojczysty"],
    "experience": [
        {
            "position": role.position,
            "dates": role.dates,
            "company": role.company,
            "technologies": list(role.technologies),
            "responsibilities": list(role.duties),
        }
        for role in ROLES[:2]
    ],
}
HTML = render_interactive_html(PAYLOAD, None, document_only=True)


class _FakeSession:
    def __init__(self, csv):
        self.csv = csv

    async def get(self, model, key):
        return self.csv if key == self.csv.id else None

    async def scalar(self, statement):
        return self.csv

    async def commit(self):
        pass

    async def rollback(self):
        pass


class _Csv:
    def __init__(self, **values):
        self.id = 7
        self.cv_layout = "new"
        self.branded_status = "draft"
        self.branded_draft_html = HTML
        self.branded_language = "pl"
        self.branded_template = "standard"
        self.page1_extras = None
        self.__dict__.update(values)


@pytest.fixture
def models(monkeypatch):
    seen: dict[str, list[str]] = {"why": [], "results": []}

    @asynccontextmanager
    async def no_quota(db, feature, *, user_id=None, units=1):
        yield None

    def why_model(system, content, request_id):
        seen["why"].append(content)
        return json.dumps(
            {
                "experience": EXPERIENCE,
                "requirements": REQUIREMENTS,
                "key_task": KEY_TASK_CV,
            },
            ensure_ascii=False,
        )

    def results_model(system, content, request_id):
        seen["results"].append(content)
        return json.dumps({"results": []})

    async def inputs(db, csv):
        return INPUTS, None

    monkeypatch.setattr(service, "ai_feature", no_quota)
    monkeypatch.setattr(service, "_call_model", results_model)
    monkeypatch.setattr(service, "_call_why_model", why_model)
    monkeypatch.setattr(service, "load_why_inputs", inputs)
    monkeypatch.setattr(service, "api_key_configured", lambda model: True)
    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", True)
    return seen


@pytest.mark.asyncio
async def test_refresh_writes_three_checked_sentences(models):
    csv = _Csv(page1_extras={"highlight": {"mode": "off"}})
    outcome = await service.refresh_stage_cv(_FakeSession(csv), csv.id)
    assert outcome.status == service.UPDATED
    extras = csv.page1_extras
    assert [g["verified"] for g in extras["why_generated"]] == [True, True, True]
    assert extras["why"][1].startswith("**Java i Postman**")
    assert extras["highlight"] == {"mode": "off"}
    sent = models["why"][0]
    assert "Jan Przykładowy" not in sent
    assert "Migracja systemu płatności do chmury" in sent
    assert "przenieśliśmy 40 usług" in sent.lower()
    # Drugi bieg bez zmian w HTML-u i profilu nie woła modelu.
    again = await service.refresh_stage_cv(_FakeSession(csv), csv.id)
    assert again.status == service.UNCHANGED
    assert len(models["why"]) == 1


@pytest.mark.asyncio
async def test_new_profile_reruns_only_the_sentences(models, monkeypatch):
    csv = _Csv()
    await service.refresh_stage_cv(_FakeSession(csv), csv.id)

    async def other(db, csv):
        return WhyInputs(must=("Java",), key_task="Inne zadanie"), None

    monkeypatch.setattr(service, "load_why_inputs", other)
    await service.refresh_stage_cv(_FakeSession(csv), csv.id)
    assert len(models["why"]) == 2
    assert len(models["results"]) == 1


@pytest.mark.asyncio
async def test_both_calls_failing_leaves_extras_untouched(models, monkeypatch):
    def broken(system, content, request_id):
        raise TimeoutError("model nie odpowiedział")

    monkeypatch.setattr(service, "_call_model", broken)
    monkeypatch.setattr(service, "_call_why_model", broken)
    before = {"why": ["Moje.", "", ""]}
    csv = _Csv(page1_extras=dict(before))
    outcome = await service.refresh_stage_cv(_FakeSession(csv), csv.id, force=True)
    assert outcome.status == service.FAILED
    assert csv.page1_extras == before


# ── Dopasowanie MUST: odmiana, alternatywy, frazy (pomiar 25.11.2026) ───────


@pytest.mark.parametrize(
    ("must", "text", "hit"),
    [
        # Pomiar na kopii produkcji: 17 z 25 zdań 2 odpadło na dosłownej frazie.
        ("Kredyty hipoteczne", "sprzedaży kredytów hipotecznych oraz obsługi", True),
        (
            "regression testing",
            "functional, regression, integration and e2e testing",
            True,
        ),
        ("Postman lub Swagger", "documented REST APIs with Postman", True),
        ("Python Flask", "business logic using Python and Flask", True),
        ("Web Testing (UI)", "exploratory, UI and API testing", True),
        ("Project Management", "Managed FinTech programs across CEE", False),
        ("Java", "JavaScript and TypeScript front-end", False),
        ("SQL", "PostgreSQL i MySQL", False),
        ("SQL", "zapytania SQL do hurtowni", True),
        ("API testing", "manual testing of mobile apps", False),
    ],
)
def test_must_matches_inflection_and_alternatives(must, text, hit):
    from app.services.cv_page1_why_checks import must_matches

    assert must_matches(must, text) is hit


def test_inflected_must_with_quote_is_verified():
    ctx = _ctx(inputs=WhyInputs(must=("Migracja systemu płatności",)))
    item = {
        "text": "**Migracje systemów płatności** w Acme Bank",
        "evidence": [
            {
                "must": "Migracja systemu płatności",
                "quote": "w programie migracji systemu płatności do chmury",
                "company": "Acme Bank",
            }
        ],
    }
    assert check_requirements(item, ctx)["verified"] is True


def test_number_glued_to_a_cv_name_is_not_a_figure():
    """Pomiar 25.11.2026: „PRINCE2” odrzucało zdanie 1 jako liczbę spoza CV."""
    ctx = _ctx()
    ctx = WhyContext(**{**ctx.__dict__, "cv_text": ctx.cv_text + " PRINCE2 Agile"})
    item = {
        **EXPERIENCE,
        "text": "{LATA_IT} w IT, w zespołach pracujących w Scrum i PRINCE2",
    }
    assert check_experience(item, ctx)["verified"] is True
    outside = {
        **EXPERIENCE,
        "text": "{LATA_IT} w IT, w zespołach pracujących w Scrum i ITIL4",
    }
    assert check_experience(outside, ctx)["issue"] == ISSUE_NUMBER_NOT_IN_CV


def test_token_inside_model_bold_keeps_one_bold_span():
    item = {
        **EXPERIENCE,
        "text": "**{LATA_IT} w IT**, w tym {LATA_ROLA} jako Test Manager",
    }
    out = check_experience(item, _ctx())
    assert out["verified"] is True, out
    assert out["text"].startswith("**9 lat w IT**, w tym **5 lat** jako Test Manager")
