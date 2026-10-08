"""Wiersze wymagań — jedna lista słów kluczowych zamiast trzech pól (02.10.2026)."""

from __future__ import annotations

from copy import deepcopy

from app.schemas.champion import ChampionProfile
from app.services import champion_requirement_rows as rows_service
from app.services.champion_intake import copy_profile, user_edit, validation
from app.services.champion_requirement_rows import expand_patch
from app.services.champion_view import requirement_source
from tests.taxonomy_fixture import hydrated_taxonomy


def _row(*words: str, level: str = "must") -> dict:
    return {"words": list(words), "level": level}


def _save(old: dict, patch: dict) -> dict:
    """Zapis tak, jak robi go handler: najpierw wiersze → pola, potem edycja."""
    previous = (old.get("stack") or {}).get("notes")
    return user_edit(old, expand_patch(patch, previous_notes=previous), actor_id=1)


ROWS = [
    _row("Java", level="critical"),
    _row("Kafka", "RabbitMQ"),
    _row("płatności", "płatnoś*", "payments"),
    _row("Kubernetes", "k8s", level="nice"),
]


def test_rows_become_the_fields_the_rest_of_the_system_reads():
    with hydrated_taxonomy():
        saved = _save({}, {"stack": {"rows": ROWS}})
    stack, search = saved["stack"], saved["search"]
    # RabbitMQ nie ma w słowniku testowym, więc nie jest „różną technologią”.
    assert [item["name"] for item in stack["must"]] == ["Java", "Kafka", "płatności"]
    assert [item["name"] for item in stack["nice"]] == ["Kubernetes"]
    assert stack["critical"] == ["Java"]
    assert search["requirements"] == [
        ["Java"],
        ["Kafka", "RabbitMQ"],
        ["płatności", "płatnoś*", "payments"],
    ]
    # Krytyczne mają jedno źródło: w zapisanych wierszach poziom to must / nice.
    assert [row["level"] for row in stack["rows"]] == ["must", "must", "must", "nice"]


def test_distinct_dictionary_technologies_are_joined_as_alternatives():
    with hydrated_taxonomy():
        assert rows_service.row_label(["Kafka", "Docker"]) == "Kafka lub Docker"
        # Inna pisownia tej samej technologii zostaje tylko w wierszu.
        assert rows_service.row_label(["PostgreSQL", "postgres"]) == "PostgreSQL"
        # Rdzeń z gwiazdką i odpowiednik nigdy nie trafiają do etykiety.
        assert rows_service.row_label(["bankowości", "bankow*", "banking"]) == (
            "bankowości"
        )
        assert rows_service.row_label(["bankow*", "banking"]) == "banking"
        assert rows_service.row_label(["płatnoś*"]) == "płatnoś"


def test_no_critical_row_means_undecided_unless_the_dl_said_none():
    rows = [_row("Java"), _row("Kafka")]
    undecided = _save({}, {"stack": {"rows": rows}})
    assert "critical" not in undecided["stack"]
    none = _save({}, {"stack": {"rows": rows, "critical": []}})
    assert none["stack"]["critical"] == []


def test_saved_profile_sent_back_keeps_its_critical_decision():
    """W zapisie poziom wiersza to must / nice, a krytyczne mówi lista etykiet."""
    with hydrated_taxonomy():
        saved = _save({}, {"stack": {"rows": ROWS}})
        again = _save(saved, {"stack": deepcopy(saved["stack"])})
        assert again["stack"]["critical"] == ["Java"]
        # Etykieta bez wiersza znika, a jawne „nie zdecydowano” zdejmuje decyzję.
        other = _save(saved, {"stack": {**saved["stack"], "critical": ["Scala"]}})
        assert "critical" not in other["stack"]
        cleared = _save(saved, {"stack": {**saved["stack"], "critical": None}})
        assert "critical" not in cleared["stack"]


def test_a_fourth_critical_row_is_stored_as_must():
    saved = _save(
        {},
        {
            "stack": {
                "rows": [
                    _row("Java", level="critical"),
                    _row("Kafka", level="critical"),
                    _row("Docker", level="critical"),
                    _row("Kubernetes", level="critical"),
                ]
            }
        },
    )
    assert saved["stack"]["critical"] == ["Java", "Kafka", "Docker"]
    assert len(saved["stack"]["must"]) == 4


def test_limits_and_duplicates():
    many = [_row(f"Tech{i}") for i in range(14)] + [_row("tech0", "inne")]
    cleaned = rows_service.clean_rows(many)
    # 06.10.2026 (N3): 11.+ „musi mieć” schodzi do „mile widziane”, nie znika.
    assert [row["level"] for row in cleaned] == ["must"] * 10 + ["nice"] * 4
    assert rows_service.clean_rows([_row("C"), _row("  "), {"words": "x"}]) == []
    assert rows_service.clean_rows("nie lista") == []
    nice = rows_service.clean_rows([_row(f"N{i}x", level="nice") for i in range(25)])
    assert len(nice) == 20


def test_profile_round_trips_and_legacy_profiles_keep_their_shape():
    saved = _save({}, {"stack": {"rows": ROWS}})
    again = ChampionProfile.model_validate(saved).model_dump(mode="json")
    assert again["stack"]["rows"] == saved["stack"]["rows"]
    legacy = ChampionProfile.model_validate(
        {"stack": {"must": [{"name": "Java"}]}}
    ).model_dump(mode="json")
    assert "rows" not in legacy["stack"]


def test_a_write_through_the_old_fields_returns_the_profile_to_them():
    """Import dokumentu, szkic AI i stary edytor piszą wprost do `must`."""
    saved = _save({}, {"stack": {"rows": ROWS}})
    edited = user_edit(
        saved, {"stack": {"must": [{"name": "Java"}, {"name": "Scala"}]}}, actor_id=1
    )
    assert "rows" not in edited["stack"]
    assert [item["name"] for item in edited["stack"]["must"]] == ["Java", "Scala"]
    # To samo przy zmianie samych wierszy wyszukiwania starym edytorem.
    searched = user_edit(saved, {"search": {"requirements": [["Go"]]}}, actor_id=1)
    assert "rows" not in searched["stack"]


def test_changing_only_a_variant_is_not_a_requirement_change():
    saved = _save({}, {"stack": {"rows": [_row("Java"), _row("Kafka")]}})
    edited = _save(
        saved, {"stack": {"rows": [_row("Java"), _row("Kafka", "Apache Kafka")]}}
    )
    assert edited["search"]["requirements"] == [["Java"], ["Kafka", "Apache Kafka"]]
    assert requirement_source(edited) == requirement_source(saved)
    # Bez nowego stempla `intake` — odcisk rankingu zostaje ten sam.
    assert edited.get("intake") == saved.get("intake")


def test_set_aside_legacy_items_do_not_come_back_into_rows():
    old = {
        "stack": {"must": [{"name": "Java"}]},
        "intake": {"unresolved": {"stack.must": "Oracle Forms"}},
    }
    saved = _save(old, {"stack": {"rows": [_row("Java"), _row("Kafka")]}})
    assert [item["name"] for item in saved["stack"]["must"]] == ["Java", "Kafka"]
    assert saved["stack"]["rows"] is not None
    assert "stack.must" not in (saved["intake"].get("unresolved") or {})


def test_template_copy_keeps_rows_and_drops_the_critical_decision():
    saved = _save({}, {"stack": {"rows": ROWS}})
    copied = copy_profile(saved, actor_id=2)
    assert "critical" not in copied["stack"]
    assert copied["stack"]["rows"] == saved["stack"]["rows"]


def test_payload_without_rows_is_untouched():
    patch = {"stack": {"must": [{"name": "Java"}]}, "basics": {"language": "EN"}}
    assert expand_patch(patch) is patch
    assert expand_patch(None) is None


def test_legacy_fields_convert_to_rows_and_sentences():
    with hydrated_taxonomy():
        result = rows_service.rows_from_legacy(
            must=[
                "Java 17+",
                "Kafka lub Docker",
                "bankowość",
                "Doświadczenie we wdrażaniu funkcjonalności w systemach bankowych",
            ],
            nice=["Kubernetes", "Java"],
            requirements=[["Java"], ["bankow*", "banking"]],
            critical=["Java 17+"],
        )
    by_head = {row["words"][0]: row for row in result["rows"]}
    assert by_head["Java"]["level"] == "critical"
    assert by_head["Kafka"]["words"] == ["Kafka", "Docker"]
    assert by_head["bankowość"]["level"] == "must"
    assert by_head["Kubernetes"]["level"] == "nice"
    # „Java” z nice nie tworzy drugiego wiersza — jest już w must.
    assert [row["words"][0] for row in result["rows"]].count("Java") == 1
    assert result["descriptive"] == [
        "Java 17+",
        "Doświadczenie we wdrażaniu funkcjonalności w systemach bankowych",
    ]
    assert result["no_critical"] is False


def test_conversion_remembers_an_explicit_no_critical_decision():
    result = rows_service.rows_from_legacy(
        must=["Java"], nice=[], requirements=[], critical=[]
    )
    assert result["no_critical"] is True
    assert (
        rows_service.rows_from_legacy(must=["Java"], nice=[], requirements=[])[
            "no_critical"
        ]
        is False
    )


def test_overflowing_must_rows_move_to_nice_and_the_rest_to_notes():
    """Audyt 06.10.2026 (N3): 749969 straciło „CI/CD” i „automated testing”,
    bo 11. i 12. wiersz „musi mieć” znikał po cichu."""
    many = [_row(f"Must{i}") for i in range(12)]
    many += [_row(f"Nice{i}", level="nice") for i in range(19)]
    rows, dropped = rows_service.split_rows(many)
    assert [r["words"][0] for r in rows if r["level"] == "must"] == [
        f"Must{i}" for i in range(10)
    ]
    nice = [r["words"][0] for r in rows if r["level"] == "nice"]
    # Nadmiar must wchodzi do „mile widziane”, dopóki jest miejsce (limit 20).
    assert nice == [f"Nice{i}" for i in range(19)] + ["Must10"]
    assert dropped == ["Must11"]
    saved = _save({"stack": {"notes": "Java 17+"}}, {"stack": {"rows": many}})
    assert "Must11" in saved["stack"]["notes"]
    assert saved["stack"]["notes"].startswith("Java 17+")


def test_word_with_or_is_split_into_variants():
    """Audyt 06.10.2026 (P3): „Kafka lub RabbitMQ” w jednym słowie kasowało
    `stack.rows` przy walidacji (etykieta nie pasowała do słów)."""
    rows = rows_service.clean_rows([_row("Kafka lub RabbitMQ", "AMQ or IBM MQ")])
    assert rows[0]["words"] == ["Kafka", "RabbitMQ", "AMQ", "IBM MQ"]
    saved = _save({}, {"stack": {"rows": [_row("Kafka lub RabbitMQ")]}})
    assert saved["stack"]["rows"][0]["words"] == ["Kafka", "RabbitMQ"]


def test_star_is_removed_from_a_dictionary_technology():
    """Audyt 06.10.2026 (P5): „Java*” łapie JavaScript."""
    with hydrated_taxonomy():
        rows = rows_service.clean_rows([_row("Java*", "bankow*")])
    assert rows[0]["words"] == ["Java", "bankow*"]


def test_single_letter_dictionary_skill_is_a_valid_word():
    """Audyt 06.10.2026 (P4): „C” i „R” nie dało się wpisać."""
    from tests.test_skill_inflection import WITH_C

    with hydrated_taxonomy(WITH_C):
        rows = rows_service.clean_rows([_row("C"), _row("X", "Rust")])
    assert [row["words"] for row in rows] == [["C"], ["Rust"]]


def test_long_word_is_cut_at_a_word_boundary():
    long = "automatyzacja " * 10
    rows = rows_service.clean_rows([_row(long)])
    word = rows[0]["words"][0]
    assert len(word) <= 100
    assert word.endswith("automatyzacja")


def _issue_codes(profile: dict) -> list[str]:
    return [issue["code"] for issue in validation(profile)["issues"]]


def test_rows_are_the_reviewed_alternatives_so_notes_do_not_ask_again():
    """„lub” w uwagach przy wierszach wymagań nie jest brakiem (08.10.2026).

    Wiersz = wymaganie, słowa = warianty, więc alternatywy są zapisane wprost.
    Uwaga „Sprawdź i zatwierdź alternatywy” stała przy takim profilu na
    czerwono, a w rekrutacji nie było czym jej zdjąć.
    """
    notes = "Must-have Python LUB Java (Spring Boot), idealnie oba."
    with hydrated_taxonomy():
        with_rows = _save({}, {"stack": {"rows": ROWS}, "search": {"notes": notes}})
    assert with_rows["stack"]["rows"]
    assert "review_alternatives" not in _issue_codes(with_rows)

    # Profil na starych polach (bez wierszy) pyta jak dotąd.
    legacy = user_edit(
        {},
        {"stack": {"must": [{"name": "Python"}]}, "search": {"notes": notes}},
        actor_id=1,
    )
    assert "rows" not in legacy["stack"]
    assert "review_alternatives" in _issue_codes(legacy)
