"""Wymagania Championa po audycie 48 h (13.10.2026) — poprawki z 14.10.2026.

Czyste testy, bez bazy: „Wymagania do poprawy” (poziom i wersja przy
„Zatwierdź”, długie zdania, krytyczne słowem wiersza — decyzja B), zapis wierszy
(ostatnia krytyczna do rozmowy, „Docker/Kubernetes”), bramka przy „(lub inny …)”,
edycja samej listy „Rekruter sprawdza w rozmowie” i `keep_required` zapisu.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.champion_requirement_rows import (
    expand_patch,
    rows_from_legacy,
    separate_talk_items,
)
from app.services.requirement_cleanup import (
    REASON_TEXT,
    apply_payload,
    build_proposal,
)
from tests.taxonomy_fixture import PROD_LIKE_SKILLS, hydrated_taxonomy

SKILLS = {
    **PROD_LIKE_SKILLS,
    "SQL": ("database", ()),
    "Azure": ("cloud", ()),
    "RabbitMQ": ("messaging", ()),
}


def _job(profile, *, must=None, nice=None):
    return SimpleNamespace(
        id=7,
        title="Programista",
        champion_profile=profile,
        must_skills=[{"name": m} for m in must] if must else None,
        nice_skills=[{"name": n} for n in nice] if nice else None,
        matching_requirements=None,
        requirements_reviewed=False,
        delivery_lead_id=5,
        created_by=6,
    )


def _build(job):
    with hydrated_taxonomy(SKILLS):
        return build_proposal(job)


def _talk(proposal):
    return {
        item["name"]: item["level"]
        for kind in ("skills", "domains")
        for item in proposal.after["experience"].get(kind) or []
    }


# ── Pkt 20: „Zatwierdź” nie zmienia poziomu i nie gubi wersji ────────────────


def test_p20_legacy_conversion_says_which_sentences_were_nice():
    with hydrated_taxonomy(SKILLS):
        result = rows_from_legacy(
            must=["Java 17+", "doświadczenie w przetargach publicznych dla banku"],
            nice=[
                "Angular 15+",
                "doświadczenie w sektorze bankowym i ubezpieczeniowym",
            ],
            requirements=[],
        )
    assert result["descriptive_nice"] == [
        "Angular 15+",
        "doświadczenie w sektorze bankowym i ubezpieczeniowym",
    ]


def test_p20_nice_sentence_goes_to_talk_as_nice_not_must():
    job = _job(
        {
            "stack": {
                "must": [{"name": "Java"}, {"name": "SQL"}],
                "nice": [{"name": "doświadczenie w sektorze bankowym"}],
            }
        }
    )
    proposal = _build(job)
    assert proposal is not None
    assert _talk(proposal)["doświadczenie w sektorze bankowym"] == "nice"
    added = {t["name"]: t["level"] for t in proposal.after["talk"]}
    assert added["doświadczenie w sektorze bankowym"] == "nice"


def test_p20_version_survives_approval_in_the_talk_list():
    job = _job(
        {
            "stack": {
                "must": [{"name": "Java 17+"}, {"name": "Spring Boot"}],
                "nice": [
                    {"name": "Angular 15+"},
                    {"name": "doświadczenie w sektorze bankowym"},
                ],
            }
        }
    )
    proposal = _build(job)
    assert proposal is not None
    rows = {r["words"][0]: r["level"] for r in proposal.after["rows"]}
    assert rows["Java"] == "must" and rows["Angular"] == "nice"
    talk = _talk(proposal)
    assert talk["Java 17+"] == "must"
    assert talk["Angular 15+"] == "nice"
    payload_skills = [
        i["name"] for i in apply_payload(proposal)["experience"]["skills"]
    ]
    assert "Java 17+" in payload_skills and "Angular 15+" in payload_skills


def test_p20_version_alone_is_not_a_reason_for_a_proposal():
    """Stary profil z „Java 17+” czyta silnik bez wersji — sama wersja nie
    jest powodem, żeby dopisać rekrutację do „Wymagań do poprawy”."""
    job = _job({"stack": {"must": [{"name": "Java 17+"}, {"name": "SQL"}]}})
    assert _build(job) is None


# ── Pkt 21: nic nie znika — długie zdanie zostaje w całości w opisie ─────────


def test_p21_long_sentence_is_kept_whole_in_the_requirement_notes():
    long = (
        "Minimum 5 lat doświadczenia komercyjnego w projektowaniu i wdrażaniu "
        "hurtowni danych w sektorze bankowym oraz ubezpieczeniowym dla dużych "
        "klientów korporacyjnych w Polsce"
    )
    assert len(long) > 160
    job = _job({"stack": {"must": [{"name": "Java"}, {"name": long}]}})
    proposal = _build(job)
    assert proposal is not None
    assert all(len(name) <= 160 for name in _talk(proposal))
    notes = apply_payload(proposal)["stack"]["notes"]
    assert long in notes


# ── Decyzja B: krytyczna sprawdzalna słowami wiersza zostaje ────────────────


def test_b_critical_keyword_row_the_gate_can_check_is_not_demoted():
    """Bramka v9 szuka słów wiersza (decyzja 09.10): „architektura chmury”
    jako słowo jest sprawdzalne — o tym, czy krytyczna, decyduje DL."""
    job = _job(
        {
            "stack": {
                "rows": [
                    {"words": ["Azure"], "level": "must"},
                    {"words": ["architektura chmury"], "level": "must"},
                ],
                "must": [{"name": "Azure"}, {"name": "architektura chmury"}],
                "nice": [],
                "critical": ["Azure", "architektura chmury"],
            },
            "search": {"requirements": [["Azure"], ["architektura chmury"]]},
        }
    )
    assert _build(job) is None


def test_b_domain_and_name_outside_dictionary_stay_critical():
    with hydrated_taxonomy(SKILLS):
        patch = expand_patch(
            {
                "stack": {
                    "rows": [
                        {"words": ["Python"], "level": "must"},
                        {"words": ["Temenos T24"], "level": "must"},
                        {"words": ["bankowość", "bankow*"], "level": "must"},
                    ],
                    "critical": ["Python", "Temenos T24", "bankowość"],
                }
            }
        )
    job = _job({"stack": patch["stack"], "search": patch["search"]})
    proposal = _build(job)
    assert proposal is None or "critical_not_searchable" not in proposal.reasons


def test_b_sentence_left_as_critical_row_is_demoted_with_a_true_reason():
    """Zdanie zostaje wierszem tylko, gdy lista rozmowy jest pełna — wtedy
    bramka szukałaby całego zdania w CV i schodzi ono do „musi mieć”."""
    full_talk = [
        {"name": f"Pozycja do rozmowy numer {i}", "level": "must"} for i in range(20)
    ]
    sentence = "doświadczenie w przetargach publicznych"
    job = _job(
        {
            "stack": {
                "rows": [
                    {"words": ["Java"], "level": "must"},
                    {"words": [sentence], "level": "must"},
                ],
                "must": [{"name": "Java"}, {"name": sentence}],
                "nice": [],
                "critical": ["Java", sentence],
            },
            "search": {"requirements": [["Java"], [sentence]]},
            "experience": {"skills": full_talk},
        }
    )
    proposal = _build(job)
    assert proposal is not None
    assert "critical_not_searchable" in proposal.reasons
    levels = {r["words"][0]: r["level"] for r in proposal.after["rows"]}
    assert levels == {"Java": "critical", sentence: "must"}
    assert "zdani" in REASON_TEXT["critical_not_searchable"]


def test_b_only_critical_demoted_keeps_the_decision_as_none_chosen():
    """Bloker 3 z przeglądu 13.10 na nowym warunku: jedyna krytyczna schodzi do
    „musi mieć” → „Brak krytycznych” (`[]`), nie `None` (422 przy zapisie)."""
    full_talk = [
        {"name": f"Pozycja do rozmowy numer {i}", "level": "must"} for i in range(20)
    ]
    sentence = "doświadczenie w przetargach publicznych"
    job = _job(
        {
            "stack": {
                "rows": [
                    {"words": ["Java"], "level": "must"},
                    {"words": [sentence], "level": "must"},
                ],
                "must": [{"name": "Java"}, {"name": sentence}],
                "nice": [],
                "critical": [sentence],
            },
            "search": {"requirements": [["Java"], [sentence]]},
            "experience": {"skills": full_talk},
        }
    )
    proposal = _build(job)
    assert proposal is not None
    assert "critical_not_searchable" in proposal.reasons
    assert proposal.after["critical"] == []
    with hydrated_taxonomy(SKILLS):
        assert expand_patch(apply_payload(proposal))["stack"]["critical"] == []


# ── Drobne: zapis wierszy ────────────────────────────────────────────────────


def test_last_critical_sentence_moved_to_talk_keeps_the_decision_as_empty():
    """Edytor wysyła poziom w wierszu i `critical: null`. Gdy jedyna krytyczna
    to zdanie i idzie do rozmowy, decyzja DL zostaje „Brak krytycznych” —
    `None` dokładał blokadę `critical` i kończył zapis 422."""
    with hydrated_taxonomy(SKILLS):
        out, _notices = separate_talk_items(
            {
                "stack": {
                    "rows": [
                        {"words": ["komunikatywność"], "level": "critical"},
                        {"words": ["Java"], "level": "must"},
                    ],
                    "critical": None,
                }
            },
            previous_rows=[{"words": ["Java"], "level": "must"}],
            keep_required=True,
        )
        expanded = expand_patch(out)
    assert expanded["stack"]["critical"] == []
    assert [r["words"] for r in expanded["stack"]["rows"]] == [["Java"]]


def test_slash_alternative_is_not_reported_as_a_dropped_comment():
    from app.services.requirement_phrase import read_phrase

    with hydrated_taxonomy(SKILLS):
        reading = read_phrase("Docker/Kubernetes")
        out, notices = separate_talk_items(
            {"stack": {"rows": [{"words": ["Docker/Kubernetes"], "level": "must"}]}}
        )
    assert reading.comment is None
    assert not any("pominięty" in n for n in notices)
    rows = (out.get("stack") or {}).get("rows")
    assert rows == [{"words": ["Docker/Kubernetes"], "level": "must"}]


def test_slash_alternative_is_not_a_paren_reason_in_cleanup():
    job = _job(
        {
            "stack": {
                "rows": [{"words": ["Docker/Kubernetes"], "level": "must"}],
                "must": [{"name": "Docker lub Kubernetes"}],
                "nice": [],
            },
            "search": {"requirements": [["Docker/Kubernetes"]]},
        }
    )
    proposal = _build(job)
    assert proposal is None or "paren" not in proposal.reasons


def test_intro_around_two_names_is_still_a_comment():
    from app.services.requirement_phrase import read_phrase

    with hydrated_taxonomy(SKILLS):
        reading = read_phrase("Bardzo dobra znajomość Kafka lub RabbitMQ")
    assert reading.keyword == "Kafka lub RabbitMQ"
    assert reading.comment == "Bardzo dobra znajomość Kafka lub RabbitMQ"


# ── Drobne: bramka i „(lub inny …)” ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("label", "options"),
    [
        ("Kafka (lub inny broker)", ("Kafka",)),
        ("PostgreSQL (lub inna relacyjna baza)", ("PostgreSQL",)),
        ("Kafka (or another broker)", ("Kafka",)),
        ("Kafka (lub dowolny broker)", ("Kafka",)),
        ("Kafka (lub RabbitMQ)", ("Kafka", "RabbitMQ")),
        ("Kafka (lub podobne)", ("Kafka",)),
    ],
)
def test_vague_alternative_in_parentheses_is_not_an_option(label, options):
    from app.services.must_gate_terms import gate_requirement

    with hydrated_taxonomy(SKILLS):
        requirement = gate_requirement(label)
    assert requirement is not None
    assert requirement.options == options


# ── Drobne: edycja samej listy „Rekruter sprawdza w rozmowie” ────────────────


def test_editing_only_the_talk_list_does_not_restamp_the_profile():
    """Reguła „Dwie listy”: edycja listy nie odpala przeliczeń. Stempel
    `intake.applied_at` wchodzi do odcisku rankingu — nie może się zmienić."""
    from app.services import champion_view
    from app.services.champion_intake import user_edit

    with hydrated_taxonomy(SKILLS):
        base = user_edit(
            {},
            {"basics": {"title": "Analityk"}, "stack": {"must": [{"name": "SQL"}]}},
            1,
        )
        items = [
            {"name": f"Zdanie klienta numer {i}", "level": "must", "note": ""}
            for i in range(25)
        ]
        edited = user_edit(
            base, {"experience": {**base["experience"], "skills": items}}, 1
        )
    assert edited["intake"] == base["intake"]
    ignored = champion_view.RANKING_IGNORED_KEYS
    assert champion_view.requirement_source(
        edited, ignored=ignored
    ) == champion_view.requirement_source(base, ignored=ignored)
    # Lista dalej przechodzi normalizację zapisu (limit sekcji).
    assert len(edited["experience"]["skills"]) == 20


def test_editing_a_domain_still_restamps_the_profile():
    from app.services.champion_intake import user_edit

    with hydrated_taxonomy(SKILLS):
        base = user_edit({}, {"stack": {"must": [{"name": "SQL"}]}}, 1)
        edited = user_edit(
            base,
            {"experience": {**base["experience"], "domains": [{"name": "płatności"}]}},
            1,
        )
    assert edited["intake"]["applied_at"] != base["intake"]["applied_at"]


# ── Drobne: `keep_required` jak ochrona przed nowym brakiem ──────────────────


class _Stop(Exception):
    pass


@pytest.mark.parametrize(
    ("status", "is_open", "expected"),
    [("published", False, True), ("published", True, True), ("draft", False, False)],
)
async def test_keep_required_follows_the_regression_guard(
    monkeypatch, status, is_open, expected
):
    """Rekrutacja `published` bez `is_open` (np. z Traffita) jest chroniona przed
    nowym brakiem — przeniesienie ostatniego wiersza do rozmowy dawało 422."""
    from app.api import recruitment_access
    from app.models.job import JobStatus
    from app.services import champion_requirement_rows, job_lifecycle

    seen: dict = {}

    def capture(payload, **kwargs):
        seen.update(kwargs)
        raise _Stop

    async def allow(*_args, **_kwargs):
        return recruitment_access.JobEditLevel.full

    monkeypatch.setattr(champion_requirement_rows, "separate_talk_items", capture)
    monkeypatch.setattr(job_lifecycle, "handoff_blocker_codes", lambda job: set())
    monkeypatch.setattr(
        job_lifecycle,
        "_api",
        lambda: SimpleNamespace(_ensure_delivery_lead_job_visible=allow),
    )
    monkeypatch.setattr(recruitment_access, "ensure_champion_job_editor", allow)
    job = SimpleNamespace(
        id=1,
        status=JobStatus(status),
        is_open=is_open,
        champion_profile={},
    )
    user = SimpleNamespace(id=1, name="Test", email="test@example.com")
    with pytest.raises(_Stop):
        await job_lifecycle.save_champion_core(
            None, job, {"stack": {"rows": []}}, user, job_lifecycle.PostCommit()
        )
    assert seen["keep_required"] is expected


# ── Drobne: awaria listy ≠ pusta lista ───────────────────────────────────────


async def test_fixes_failure_is_none_not_an_empty_list(monkeypatch):
    from app.services import requirement_cleanup

    class _Nested:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def boom(db, user):
        raise RuntimeError("awaria")

    monkeypatch.setattr(requirement_cleanup, "load_fixes", boom)
    db = SimpleNamespace(begin_nested=lambda: _Nested())
    assert await requirement_cleanup.load_fixes_safely(db, SimpleNamespace()) is None
