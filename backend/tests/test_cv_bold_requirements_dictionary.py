"""Pogrubianie wymagań przez słownik umiejętności (G2, 07.11.2026).

Pomiar na 326 zatwierdzonych CV z kopii produkcji: rekruterzy dopisywali ręcznie
pogrubienia wymagań, których generator nie pogrubiał — narzędzi ze słownika
(Pega, Appium, VMware), innego zapisu („SailPoint IIQ” ↔ „SailPoint IdentityIQ”),
nazw w wymaganiu-zdaniu („…z wykorzystaniem Espresso, JUnit oraz MockK”)
i nazw produktów („Kafka Streams”). „Pogrub wymagania” w edytorze liczy tak samo.
"""

from __future__ import annotations

import pytest

from app.services import cv_qc as qc
from app.services import dz_review as dz
from app.services.cv_generator_b2b.docx_renderer import (
    compile_keyword_patterns,
    highlight_spans,
)
from tests.taxonomy_fixture import hydrated_taxonomy

SKILLS: dict[str, tuple[str, tuple[str, ...]]] = {
    "Java": ("language", ()),
    "Go": ("language", ("golang", "go")),
    "PostgreSQL": ("database", ("postgres", "pg")),
    "Elasticsearch": ("database", ("es",)),
    "AWS S3": ("cloud", ("s3",)),
    "C#": ("language", ("c#",)),
    "Kotlin": ("language", ()),
    "Android": ("mobile", ()),
    "JUnit": ("qa", ("junit 5",)),
    "Apache Kafka": ("data", ("kafka",)),
    "Apache Airflow": ("data", ("airflow",)),
    "Apache HTTPD": ("devops", ("apache", "httpd")),
    "Apache Spark": ("data", ("spark", "pyspark")),
    "Pega": ("tools", ("pegasystems",)),
    "SailPoint IdentityIQ": ("tools", ("sailpoint iiq", "iiq")),
    "Appium": ("tools", ()),
    "VMware": ("tools", ("vsphere",)),
    "Microsoft Project": ("tools", ("ms project", "project")),
    "Microsoft Access": ("database", ("ms access", "access")),
    "BPMN": ("standards", ("bpmn 2.0",)),
    "LLM": ("ai", ("large language models", "llms")),
    "Scrum": ("methodology", ()),
    "Agile": ("methodology", ()),
    "User Stories": ("practice", ()),
    "Anti-Money Laundering": ("domain", ()),
    "Project Management": ("role_management", ("zarządzanie projektami",)),
    "Software developer": ("role_dev", ("developer",)),
}


def _bold(chips: list[str], text: str) -> list[str]:
    return [
        text[s:e] for s, e in highlight_spans(text, compile_keyword_patterns(chips))
    ]


@pytest.fixture(autouse=True)
def _taxonomy():
    with hydrated_taxonomy(SKILLS):
        yield


# ── Generator: krótkie nazwy (CV-5, 08.11.2026) ─────────────────────────────


def test_go_does_not_bold_the_polish_pronoun() -> None:
    text = "Napisał moduł w Go i wdrożył go na produkcję."
    assert _bold(["Go"], text) == ["Go"]


def test_short_names_keep_their_written_case_for_lowercase_chips() -> None:
    assert _bold(["go"], "Usługi w Go, przetestował go.") == ["Go"]


def test_short_aliases_do_not_bold_university_or_country_codes() -> None:
    text = "Politechnika Gdańska (PG), kurs w ES, baza PostgreSQL i Elasticsearch."
    assert _bold(["PostgreSQL", "Elasticsearch"], text) == [
        "PostgreSQL",
        "Elasticsearch",
    ]


def test_short_alias_with_a_digit_still_bolds_in_its_own_spelling() -> None:
    assert _bold(["AWS S3"], "Pliki w S3.") == ["S3"]


@pytest.mark.parametrize(
    ("chip", "text", "bolded"),
    [
        ("k6", "Testy w k6 oraz K6.", ["k6", "K6"]),
        ("K6", "Testy w k6.", ["k6"]),
        ("c#", "Aplikacje w C# oraz c#.", ["C#", "c#"]),
    ],
)
def test_short_name_with_digit_or_sign_ignores_case(
    chip: str, text: str, bolded: list[str]
) -> None:
    assert _bold([chip], text) == bolded


# ── Generator: lista słów i wzorce ──────────────────────────────────────────


def test_tool_from_requirements_bolds_with_its_dictionary_variants() -> None:
    text = "Rozwijał procesy w Pega (Pegasystems 8.x), testy mobilne w Appium, VMware."
    assert _bold(["Pega", "Appium", "VMware"], text) == [
        "Pega",
        "Pegasystems",
        "Appium",
        "VMware",
    ]


def test_requirement_written_differently_bolds_the_cv_spelling() -> None:
    text = "Wdrażał SailPoint IdentityIQ dla 40 tys. kont."
    assert _bold(["SailPoint IIQ"], text) == ["SailPoint IdentityIQ"]


def test_standard_and_ai_requirements_bold_too() -> None:
    text = "Modelował procesy w BPMN 2.0 i budował agentów na LLMs."
    assert _bold(["BPMN", "LLM"], text) == ["BPMN 2.0", "LLMs"]


@pytest.mark.parametrize(
    "chip, text",
    [
        ("Scrum", "Pracował w Scrum jako developer."),
        ("Agile", "Zespół Agile, sprinty dwutygodniowe."),
        ("User Stories", "Pisał User Stories i kryteria akceptacji."),
        ("Project Management", "Project Management w programie wdrożeniowym."),
        ("bankowość", "Dziesięć lat w bankowość korporacyjna."),
    ],
)
def test_methodology_practice_role_and_domain_do_not_bold(chip, text) -> None:
    # Pogrubiamy technologie, narzędzia, standardy i AI — nie sposób pracy,
    # praktykę, rolę ani dziedzinę (audyt pogrubień 13.07.2026).
    assert _bold([chip], text) == []


def test_names_inside_a_sentence_requirement_bold_without_the_prose() -> None:
    chip = "Doświadczenie w testowaniu aplikacji z wykorzystaniem Espresso, JUnit oraz MockK"
    text = (
        "Testowanie aplikacji: Espresso, JUnit, MockK. Doświadczenie w testowaniu UI."
    )
    # Espresso nie jest w słowniku — zostaje bez pogrubienia, tak jak słowa
    # zdania („testowaniu”, „aplikacji”). „MockK” pogrubia się jak dotąd po
    # zapisie (mała i wielka litera w środku nazwy).
    assert _bold([chip], text) == ["JUnit", "MockK"]


def test_sentence_requirement_bolds_dictionary_languages_and_platforms() -> None:
    chip = "Minimum 6 lat doświadczenia w programowaniu w Kotlin na platformę Android"
    text = "Tech Lead zespołu Android, moduły w Kotlin i Javie."
    assert _bold([chip], text) == ["Android", "Kotlin"]


@pytest.mark.parametrize(
    "chip, text",
    [
        # Alias „project” (MS Project) i „access” (MS Access) w zdaniu znaczą
        # co innego — pomiar dawał 42 fałszywe „access”.
        ("Doświadczenie w Project Management", "Prowadził project meetings."),
        ("Privileged Access Management", "Nadawał access do systemów."),
        ("Identity and Access Management", "Przeglądy access co kwartał."),
        # „Apache” z „Apache Iceberg” to nie serwer Apache.
        ("Apache Iceberg", "Przetwarzanie w Apache Spark."),
    ],
)
def test_ambiguous_dictionary_words_in_a_requirement_do_not_bold(chip, text) -> None:
    assert _bold([chip], text) == []


def test_product_name_after_a_technology_bolds_whole() -> None:
    text = "Integracja przez Kafka Connect, przetwarzanie w Kafka Streams."
    assert _bold(["Kafka Streams", "Kafka Connect"], text) == [
        "Kafka Connect",
        "Kafka Streams",
    ]


@pytest.mark.parametrize("chip", ["Java Developer", "Kafka Senior", "Java Scrum"])
def test_role_or_methodology_after_a_technology_is_not_a_product(chip) -> None:
    second = chip.split()[1]
    text = f"Pracował jako {chip}. {second} w zespole."
    assert second not in " ".join(_bold([chip], text))


def test_spaced_slash_splits_two_names_but_keeps_short_acronyms() -> None:
    text = "DAG-i w Cloud Composer i Apache Airflow, pipeline CI / CD."
    assert _bold(["Cloud Composer / Apache Airflow"], text) == ["Apache Airflow"]
    assert _bold(["CI / CD"], "Utrzymywał CI / CD w GitLab.") == ["CI / CD"]


def test_requirement_outside_the_dictionary_stays_as_before() -> None:
    # Słownik nie zna „Cisco” — bez zmian względem zachowania sprzed G2.
    assert _bold(["Cisco"], "Konfiguracja przełączników Cisco.") == []


# ── QC: „Pogrub wymagania” liczy tak samo jak generator ─────────────────────


def _reqs(*names: str) -> list[dz.Requirement]:
    return [dz.Requirement(label=n, alternatives=(n,), terms=(n,)) for n in names]


def test_bold_all_bolds_tool_variants_and_skips_headings() -> None:
    html = (
        "<h2>Pega</h2>"
        "<p>Procesy w Pega i Pegasystems, testy w Appium.</p>"
        "<ul><li>Agile i Scrum.</li></ul>"
    )
    out, count = qc.bold_all(html, _reqs("Pega", "Appium", "Scrum"))
    assert count == 3
    assert "<h2>Pega</h2>" in out
    assert "<b>Pega</b>" in out and "<b>Pegasystems</b>" in out
    assert "<b>Appium</b>" in out
    assert "<b>Scrum</b>" not in out


def test_unbolded_tool_requirement_counts_where_bold_all_would_bold() -> None:
    html = "<p>Procesy w <b>Pega</b>, migracja z Pegasystems 7.</p>"
    blocks = dz.html_blocks(html)
    [pega] = _reqs("Pega")
    assert qc._has_unbolded(blocks, pega)
    fixed, count = qc.bold_all(html, [pega])
    assert count == 1
    assert not qc._has_unbolded(dz.html_blocks(fixed), pega)


def test_qc_expects_the_same_requirements_the_generator_bolds() -> None:
    for name in ("Pega", "SailPoint IIQ", "BPMN", "Kotlin"):
        assert qc._bold_patterns(_reqs(name)[0]), name
    for name in ("Scrum", "User Stories", "Project Management"):
        assert not qc._bold_patterns(_reqs(name)[0]), name
