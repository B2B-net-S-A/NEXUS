"""Układanie treści ogłoszenia: materiał, prompt, parser, złożenie bez modelu.

Bez bazy. Kontrakty przeniesione ze starego generatora (``ai_writer``):
wywołanie idzie wspólnym klientem i jest zadeklarowane, a awaria dostawcy
nie może wyjść jako wynik AI ani nieść zmyślonych pól.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from app.models.ai_feature import AIFeatureKey
from app.models.job import Job
from app.services.ai_models import model_for
from app.services.job_ad import fixed_blocks, generate, material
from app.services.job_ad_schema import SOURCE_AI, SOURCE_TEMPLATE


def _job(**champion) -> Job:
    profile = {
        "basics": {
            "rate_value": 175,
            "rate_raw": "175 zł/h",
            "language": "polski, angielski B2",
            "start_date": "listopad 2026",
            "contract_length": "12 miesięcy",
            "work_mode": "hybrid",
            "onsite_days_per_week": 2,
            "candidate_location_pref": "Warszawa",
        },
        "client": {"about": "Kwarcowy Bank", "selling_points": "premia od klienta"},
        "project": {
            "about": "Nowy system rozliczeń",
            "responsibilities": "rozwój mikroserwisów\nprzeglądy kodu",
        },
        "stack": {
            "must": [{"name": "Java"}, {"name": "Kafka"}],
            "nice": [{"name": "Kubernetes"}, {"name": "java"}],
            "critical": ["Java"],
        },
        "insights": [
            {"text": "projekt na lata", "audience": "candidate"},
            {"text": "klient marudzi o stawkę", "audience": "team"},
        ],
    }
    profile.update(champion)
    return Job(
        title="Kwarcowy: Senior Java Developer (ZOB-3003)", champion_profile=profile
    )


def _material(job: Job | None = None) -> material.AdMaterial:
    return material.build_material(job or _job(), "Senior Java Developer")


# ── Materiał: co wolno wziąć z rekrutacji ───────────────────────────────────


def test_material_carries_no_client_rate_or_team_notes():
    mat = _material()
    blob = repr(mat)
    assert "Kwarcowy" not in blob and "175" not in blob
    assert "premia od klienta" not in blob and "marudzi" not in blob
    assert mat.title == "Senior Java Developer"
    assert mat.pitch == "projekt na lata"
    assert mat.language == "polski, angielski B2"
    assert (mat.start, mat.duration) == ("listopad 2026", "12 miesięcy")
    assert (mat.remote_policy, mat.onsite_days_per_week, mat.city) == (
        "hybrid",
        2,
        "Warszawa",
    )


def test_material_marks_critical_only_from_the_delivery_lead_decision():
    assert _material().critical == ("Java",)
    undecided = _job(stack={"must": [{"name": "Java"}], "nice": []})
    assert _material(undecided).critical == ()


def test_nice_to_have_never_repeats_a_required_technology():
    mat = _material()
    assert mat.must == ("Java", "Kafka")
    assert mat.nice == ("Kubernetes",)


def test_empty_champion_gives_empty_fields_not_placeholder_words():
    mat = material.build_material(Job(title="Tester", champion_profile={}), "Tester")
    assert mat.about == "" and mat.responsibilities == "" and mat.pitch == ""
    assert mat.must == () and mat.start is None and mat.language is None
    assert [r["key"] for r in material.readiness(mat) if r["present"]] == []
    assert material.facts(mat) == [
        {"key": "contract", "label": "Współpraca", "value": "B2B"}
    ]


def test_description_left_by_the_old_draft_loses_the_client_line():
    """Stary „Szkic ogłoszenia” zapisywał w opisie rekrutacji „## Tytuł”
    i „Klient: <nazwa>”; bez Championa ten opis wchodzi do materiału."""
    job = Job(
        title="Tester",
        champion_profile={},
        description=(
            "## Senior Tester\n\nKlient: Kwarcowy Bank\n\n## Wymagania\n\nSelenium"
        ),
        requirements="klient: Kwarcowy Bank\nSelenium, Java",
    )
    mat = material.build_material(job, "Tester")
    assert "Kwarcowy" not in mat.description + mat.requirements_text
    assert "#" not in mat.description
    assert "Senior Tester" in mat.description and "Selenium" in mat.description
    assert mat.requirements_text == "Selenium, Java"


def test_facts_and_readiness_describe_what_the_recruitment_has():
    mat = _material()
    facts = {f["key"]: f["value"] for f in material.facts(mat)}
    assert facts["workplace"] == "hybrydowo, 2 dni w tygodniu w biurze"
    assert facts["requirements"] == "1 krytyczne, 1 wymagane, 1 mile widziane"
    ready = {r["key"]: r["present"] for r in material.readiness(mat)}
    assert ready["about"] and ready["must"] and ready["start"] and ready["workplace"]
    assert not ready["seniority"]


def test_material_hash_changes_with_the_recruitment():
    first = material.material_hash(_material())
    assert first == material.material_hash(_material())
    changed = _job()
    changed.champion_profile["basics"]["onsite_days_per_week"] = 3
    assert material.material_hash(_material(changed)) != first


def test_material_hash_covers_an_explicit_versioned_field_list():
    """Nowe pole ``AdMaterial`` nie może samo oznaczyć wszystkich zapisanych
    ogłoszeń jako nieaktualnych — dopisanie go do odcisku to zmiana wersji."""
    import dataclasses

    fields = {f.name for f in dataclasses.fields(material.AdMaterial)}
    # `location` wchodzi do odcisku pod kluczem `city` (niżej).
    assert set(material._HASH_FIELDS) | {"location"} == fields
    assert material._HASH_VERSION == "v1"


def test_cutting_the_street_from_the_city_does_not_mark_ads_as_outdated():
    """28.10.2026 miasto ogłoszenia traci adres biura. Odcisk liczy się dalej
    z lokalizacji wpisanej w rekrutacji — inaczej każde ogłoszenie z adresem
    dostałoby „Rekrutacja zmieniła się… Przygotuj ponownie”, a to nadpisuje
    ręczne poprawki."""
    import dataclasses

    job = _job()
    job.location = "Warszawa, ul. Chmielna 89"
    mat = _material(job)
    assert mat.city == "Warszawa"
    before = dataclasses.replace(mat, city="Warszawa, ul. Chmielna 89", location=None)
    assert material.material_hash(mat) == material.material_hash(before)


# ── Prompt ──────────────────────────────────────────────────────────────────


def test_prompt_carries_the_material_but_no_client_or_rate():
    prompt = generate.prompt_for(_material(), "pl")
    assert "Kwarcowy" not in prompt and "175" not in prompt
    assert "Nowy system rozliczeń" in prompt
    assert "Technologie krytyczne: Java" in prompt
    assert "Co wolno powiedzieć kandydatowi: projekt na lata" in prompt
    assert "JĘZYK WYJŚCIA: polski." in prompt
    assert "JĘZYK WYJŚCIA: angielski." in generate.prompt_for(_material(), "en")


def test_polish_prompt_does_not_hand_terms_to_the_model():
    """Tryb, miasto, start i długość dokleja kod — model ich nie dostaje."""
    prompt = generate.prompt_for(_material(), "pl")
    material_part = prompt.split("MATERIAŁ:", 1)[1]
    for value in ("Warszawa", "listopad 2026", "12 miesięcy", "hybrid"):
        assert value not in material_part
    assert "DO PRZETŁUMACZENIA" not in prompt


def test_english_prompt_asks_only_for_a_translation_of_the_terms():
    prompt = generate.prompt_for(_material(), "en")
    assert "DO PRZETŁUMACZENIA:" in prompt
    assert "start: listopad 2026" in prompt
    assert "język pracy: polski, angielski B2" in prompt
    assert '"start": "…", "duration": "…", "language": "…"}' in prompt
    # Miasta i trybu model nie dostaje także po angielsku.
    assert "Warszawa" not in prompt and "hybrid" not in prompt


# ── Parser odpowiedzi modelu ────────────────────────────────────────────────


def test_saved_content_drops_invisible_characters_but_keeps_emoji():
    """Miękki łącznik i spacja zerowej szerokości z Worda nie trafiają na
    portal; łącznik sklejający emoji zostaje."""
    content = generate.clean_content(
        {
            "about": "Plat\u00adforma płat\u200bności.\ufeff",
            "requirements": ["Ja\u200bva 17", "zespół \U0001f469\u200d\U0001f4bb"],
        },
        title="Dev\u200bOps",
    )
    assert content["title"] == "DevOps"
    assert content["about"] == "Platforma płatności."
    assert content["requirements"] == ["Java 17", "zespół \U0001f469\u200d\U0001f4bb"]


def test_city_is_saved_only_when_typed():
    """Odcisk treści liczy się z całego słownika — pusty klucz w każdej
    zapisanej treści zapaliłby „Do aktualizacji” przy oznaczonych ogłoszeniach."""
    assert "city" not in generate.clean_content({"city": "  "}, title="Dev")
    assert (
        generate.clean_content({"city": " Warszawa  lub Lublin"}, title="Dev")["city"]
        == "Warszawa lub Lublin"
    )


def test_parser_reads_fenced_json_and_cleans_bullets():
    parsed = generate.parse_generated(
        '```json\n{"lead": " Szukamy  osoby ", "about": "Projekt.", '
        '"responsibilities": ["- rozwój", "• rozwój", "2) testy", ""], '
        '"requirements": ["Java"], "nice_to_have": [], "offer": []}\n```'
    )
    assert parsed["lead"] == "Szukamy osoby"
    assert parsed["responsibilities"] == ["rozwój", "testy"]
    assert parsed["requirements"] == ["Java"]


def test_parser_clamps_lengths():
    items = ", ".join(f'"{i} {"x" * 1000}"' for i in range(40))
    parsed = generate.parse_generated(f'{{"about": "a", "requirements": [{items}]}}')
    assert len(parsed["requirements"]) == generate.LIST_LIMITS["requirements"]
    assert all(len(item) == generate.ITEM_MAX for item in parsed["requirements"])


@pytest.mark.parametrize(
    "text",
    ["", "przepraszam, nie mogę", '["lista"]', '{"lead": "sam wstęp"}', "{zepsuty"],
)
def test_parser_rejects_output_without_content(text):
    with pytest.raises(ValueError):
        generate.parse_generated(text)


def test_model_cannot_set_title_or_polish_terms():
    content = generate.with_terms(
        {
            "title": "Tytuł z modelu",
            "start": "jutro",
            "duration": "wiecznie",
            "language": "klingoński",
            "about": "Projekt.",
        },
        _material(),
        lang="pl",
    )
    assert content["title"] == "Senior Java Developer"
    assert (content["start"], content["duration"], content["language"]) == (
        "listopad 2026",
        "12 miesięcy",
        "polski, angielski B2",
    )


def test_english_terms_are_the_model_translation_of_existing_values_only():
    mat = material.build_material(
        _job(
            basics={
                "start_date": "listopad 2026",
                "contract_length": "",
                "language": "polski, angielski B2",
            }
        ),
        "Senior Java Developer",
    )
    content = generate.with_terms(
        {
            "about": "Project.",
            "start": "November 2026",
            "duration": "12 months",  # rekrutacja nie ma długości — odrzucone
            "language": "",  # puste tłumaczenie — zostaje wartość źródłowa
        },
        mat,
        lang="en",
    )
    assert content["start"] == "November 2026"
    assert content["duration"] == ""
    assert content["language"] == "polski, angielski B2"


# ── Złożenie bez modelu ─────────────────────────────────────────────────────


def test_template_uses_only_recruitment_fields_and_no_placeholders():
    content = generate.with_terms(
        generate.template_content(_material()), _material(), lang="pl"
    )
    assert content["lead"] == ""
    assert content["about"] == "Nowy system rozliczeń"
    assert content["responsibilities"] == ["rozwój mikroserwisów", "przeglądy kodu"]
    assert content["requirements"] == ["Java", "Kafka"]
    assert content["nice_to_have"] == ["Kubernetes"]
    assert content["offer"] == []
    blob = repr(content).casefold()
    assert "uzupełnij" not in blob and "brak" not in blob and "zł" not in blob


def test_template_puts_critical_technologies_first():
    job = _job(
        stack={
            "must": [{"name": "Kafka"}, {"name": "Java"}],
            "nice": [],
            "critical": ["Java"],
        }
    )
    assert generate.template_content(_material(job))["requirements"] == [
        "Java",
        "Kafka",
    ]


# ── Wywołanie modelu ────────────────────────────────────────────────────────


class _FakeDb:
    async def commit(self) -> None:
        return None


_REPLY = (
    '{"lead": "Szukamy osoby.", "about": "Projekt rozliczeń.", '
    '"responsibilities": ["rozwój mikroserwisów"], '
    '"requirements": ["doświadczenie w Javie"], "nice_to_have": [], "offer": []}'
)


def _patch_ai(monkeypatch, *, key=True, reply=None, error=None):
    captured: dict[str, object] = {}

    @asynccontextmanager
    async def fake_feature(db, feature, *, user_id=None, units=1):
        captured["feature"] = feature
        captured["user_id"] = user_id
        yield None

    class _Block:
        type = "text"
        text = reply or ""

    class _Message:
        content = [_Block()]

    def fake_call_claude(**kwargs):
        captured.update(kwargs)
        if error is not None:
            raise error
        return _Message()

    monkeypatch.setattr("app.services.ai_quota.ai_feature", fake_feature)
    monkeypatch.setattr("app.services.claude_client.call_claude", fake_call_claude)
    monkeypatch.setattr(
        "app.services.llm_providers.api_key_configured", lambda model: key
    )
    return captured


async def _generate(lang="pl", allow_template=True):
    return await generate.generate_content(
        _FakeDb(),
        _material(),
        lang=lang,
        user_id=7,
        log_ref="job=test",
        allow_template=allow_template,
    )


@pytest.mark.asyncio
async def test_model_call_is_declared_and_goes_through_the_shared_client(monkeypatch):
    captured = _patch_ai(monkeypatch, reply=_REPLY)
    content, source = await _generate()
    assert source == SOURCE_AI
    assert content["about"] == "Projekt rozliczeń."
    assert content["title"] == "Senior Java Developer"
    assert captured["feature"] == AIFeatureKey.job_description_generator
    assert captured["user_id"] == 7
    assert captured["model"] == model_for(AIFeatureKey.job_description_generator)
    # Sonnet 5 liczy tokeny thinking do max_tokens i ucinał JSON.
    assert captured["thinking"] == {"type": "disabled"}


@pytest.mark.asyncio
async def test_missing_key_gives_a_labelled_template_without_calling_the_model(
    monkeypatch,
):
    captured = _patch_ai(monkeypatch, key=False)
    content, source = await _generate()
    assert source == SOURCE_TEMPLATE
    assert "model" not in captured
    assert content["requirements"] == ["Java", "Kafka"]


_FAILURES = [
    (None, RuntimeError("529 overloaded_error")),
    ("to nie jest JSON", None),
    ('{"lead": "sam wstęp"}', None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("reply,error", _FAILURES)
async def test_provider_failure_never_comes_out_as_an_ai_result(
    monkeypatch, reply, error
):
    """Poprzedni generator oddawał w tej sytuacji szablon ze zmyślonymi
    widełkami, nie do odróżnienia od wyjścia AI."""
    _patch_ai(monkeypatch, reply=reply, error=error)
    content, source = await _generate()
    assert source == SOURCE_TEMPLATE
    assert content["about"] == "Nowy system rozliczeń"
    assert "uzupełnij" not in repr(content)


@pytest.mark.asyncio
@pytest.mark.parametrize("reply,error", _FAILURES)
async def test_failure_raises_when_a_saved_ad_must_not_be_replaced(
    monkeypatch, reply, error
):
    """Chwilowa awaria modelu nie może zastąpić złożeniem treści, którą
    rekruter już poprawił — trasa odpowiada wtedy 503 i niczego nie zapisuje."""
    _patch_ai(monkeypatch, reply=reply, error=error)
    with pytest.raises(generate.AdGenerationFailed):
        await _generate(allow_template=False)


@pytest.mark.asyncio
async def test_english_ad_is_never_assembled_from_polish_fields(monkeypatch):
    _patch_ai(monkeypatch, key=False)
    with pytest.raises(generate.AdGenerationFailed):
        await _generate(lang="en", allow_template=True)


# ── Stałe części ogłoszenia ─────────────────────────────────────────────────


def test_broken_setting_reads_as_defaults_instead_of_failing():
    for value in (
        None,
        {},
        {"title_suffix": "xyz", "pl": "tekst"},
        {"pl": {"offer": [1]}},
    ):
        assert fixed_blocks.parse_blocks(value) == fixed_blocks.DEFAULTS


def test_setting_round_trips_and_keeps_an_emptied_block_empty():
    saved = fixed_blocks.validate_blocks(
        {
            "title_suffix": "km",
            "pl": {"offer": [" opieka  medyczna "], "process": [], "about": ""},
            "en": {"offer": [], "process": ["Call"], "about": "We connect people."},
        }
    )
    assert saved.pl.offer == ("opieka medyczna",)
    assert saved.pl.process == () and saved.pl.about == ""
    assert fixed_blocks.parse_blocks(saved.as_dict()) == saved
    assert saved.for_lang("en").process == ("Call",)
    assert saved.for_lang("pl") is saved.pl


@pytest.mark.parametrize(
    "patch,message",
    [
        ({"title_suffix": "inny"}, "dopisek"),
        ({"pl": {"offer": ["a"] * 9, "process": [], "about": ""}}, "Co oferujemy"),
        ({"pl": {"offer": [], "process": ["a"] * 7, "about": ""}}, "proces"),
        ({"pl": {"offer": ["x" * 201], "process": [], "about": ""}}, "za długi"),
        ({"en": {"offer": [], "process": [], "about": "x" * 601}}, "Zdanie o firmie"),
        ({"en": None}, "angielski"),
    ],
)
def test_strict_validation_explains_the_problem_in_polish(patch, message):
    value = {**fixed_blocks.DEFAULTS.as_dict(), **patch}
    with pytest.raises(ValueError, match=message):
        fixed_blocks.validate_blocks(value)
