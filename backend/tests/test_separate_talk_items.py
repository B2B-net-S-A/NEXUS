"""Zapis Championa: zdanie nie zostaje słowem do szukania (wariant A, 13.10.2026).

Czyste testy `champion_requirement_rows.separate_talk_items` i tego, co z jego
wyniku wyprowadza `expand_patch`. Bez bazy.
"""

from app.services.champion_requirement_rows import expand_patch, separate_talk_items
from tests.taxonomy_fixture import PROD_LIKE_SKILLS, hydrated_taxonomy

SKILLS = {**PROD_LIKE_SKILLS, "SQL": ("database", ()), "Azure": ("cloud", ())}


def _patch(rows, **stack):
    return {"stack": {"rows": rows, **stack}}


def _run(patch, **kwargs):
    with hydrated_taxonomy(SKILLS):
        return separate_talk_items(patch, **kwargs)


def test_sentence_row_moves_to_the_talk_list_with_a_notice():
    out, notices = _run(
        _patch(
            [
                {"words": ["Azure"], "level": "must"},
                {"words": ["doświadczenie w przetargach"], "level": "must"},
            ]
        )
    )
    assert [r["words"] for r in out["stack"]["rows"]] == [["Azure"]]
    skills = out["experience"]["skills"]
    assert [s["name"] for s in skills] == ["doświadczenie w przetargach"]
    assert skills[0]["level"] == "must"
    assert any("doświadczenie w przetargach" in n for n in notices)


def test_language_goes_to_the_language_field_not_the_talk_list():
    out, notices = _run(
        {
            **_patch(
                [
                    {"words": ["Java"], "level": "must"},
                    {"words": ["Język angielski min. B2"], "level": "must"},
                ]
            ),
            "basics": {"language": "polski"},
        }
    )
    assert out["basics"]["language"] == "polski, Język angielski min. B2"
    assert "skills" not in out["experience"]
    assert notices == ["„Język angielski min. B2” przeniesione do pola „Język”."]


def test_comment_in_parentheses_is_split_and_critical_follows_the_row():
    out, notices = _run(
        _patch(
            [{"words": ["SQL (bardzo dobra znajomość)"], "level": "must"}],
            critical=["SQL (bardzo dobra znajomość)"],
        )
    )
    assert out["stack"]["rows"][0]["words"] == ["SQL"]
    assert out["stack"]["critical"] == ["SQL"]
    assert out["experience"]["skills"][0]["name"] == "SQL — bardzo dobra znajomość"
    expanded = expand_patch(out)
    assert expanded["stack"]["critical"] == ["SQL"]
    assert expanded["stack"]["must"] == [{"name": "SQL"}]


def test_mixed_row_keeps_its_keywords_and_drops_only_the_sentence():
    out, _ = _run(
        _patch(
            [
                {
                    "words": ["doświadczenie w bankowości", "bankow*", "banking"],
                    "level": "must",
                }
            ]
        )
    )
    assert out["stack"]["rows"][0]["words"] == ["bankow*", "banking"]
    assert out["experience"]["domains"][0]["name"] == "doświadczenie w bankowości"


def test_rows_already_saved_are_not_touched():
    rows = [{"words": ["doświadczenie w przetargach"], "level": "must"}]
    out, notices = _run(_patch(rows), previous_rows=rows)
    assert out == _patch(rows)
    assert notices == []


def test_handed_off_job_keeps_its_only_required_row():
    rows = [{"words": ["doświadczenie w przetargach"], "level": "must"}]
    out, notices = _run(_patch(rows), keep_required=True)
    assert out == _patch(rows)
    assert notices and "co najmniej jedno słowo do szukania" in notices[0]


def test_new_job_with_only_sentences_ends_without_rows():
    out, _ = _run(_patch([{"words": ["Stakeholder management"], "level": "must"}]))
    assert out["stack"]["rows"] == []


def test_talk_items_are_appended_to_stored_experience():
    previous = {
        "domains": [{"name": "sektor publiczny", "level": "must"}],
        "skills": [{"name": "komunikacja z klientem", "level": "nice"}],
    }
    out, _ = _run(
        _patch([{"words": ["doświadczenie w przetargach"], "level": "nice"}]),
        previous_experience=previous,
    )
    assert out["experience"]["domains"] == previous["domains"]
    assert [s["name"] for s in out["experience"]["skills"]] == [
        "komunikacja z klientem",
        "doświadczenie w przetargach",
    ]
    assert out["experience"]["skills"][1]["level"] == "nice"


def test_payload_without_rows_is_untouched():
    patch = {"stack": {"notes": "x"}}
    assert _run(patch) == (patch, [])


def test_raw_text_is_cut_to_row_limits_before_reading(monkeypatch):
    """Przegląd bezpieczeństwa 13.10.2026: surowy tekst wiersza (do 30 MB ciała
    żądania) szedł do `read_phrase` przed limitami schematu — jedno żądanie
    zamrażało API. Odczyt dostaje słowa po sicie wiersza: ≤ 20 słów po ≤ 100
    znaków, a wierszy najwyżej tyle, ile zmieści zapis z nadmiarem."""
    from app.services import requirement_phrase

    seen: list[str] = []
    real = requirement_phrase.read_phrase

    def spy(text):
        seen.append(text)
        return real(text)

    monkeypatch.setattr(requirement_phrase, "read_phrase", spy)
    huge = "doświadczenie " * 100_000
    rows = [{"words": [huge], "level": "must"}] + [
        {"words": [f"słowo{i}-{j}" for j in range(500)], "level": "nice"}
        for i in range(200)
    ]
    _run(_patch(rows))
    assert seen and max(len(text) for text in seen) <= 100
    assert len(seen) <= 60 * 20
