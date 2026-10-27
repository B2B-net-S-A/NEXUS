"""„Wymagania do poprawy” — porządki otwartych rekrutacji (D4, 13.10.2026).

Czyste testy `requirement_cleanup.build_proposal` na kształtach z produkcji:
kolumna z prozą zamiast Championa, nawias przy technologii, zdania w must,
krytyczne spoza bramki, rekrutacja bez słów do szukania. Plus lustro DDL.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace

from app.models.user import UserRole
from app.services.requirement_cleanup import (
    apply_payload,
    build_proposal,
    can_decide,
)
from tests.taxonomy_fixture import PROD_LIKE_SKILLS, hydrated_taxonomy

SKILLS = {
    **PROD_LIKE_SKILLS,
    "SQL": ("database", ()),
    "Azure": ("cloud", ()),
    "Git": ("devops", ()),
}
BACKEND = Path(__file__).resolve().parents[1]


def _job(profile, *, must=None, nice=None, **extra):
    return SimpleNamespace(
        id=7,
        title="Data Engineer",
        champion_profile=profile,
        must_skills=[{"name": m} for m in must] if must else None,
        nice_skills=[{"name": n} for n in nice] if nice else None,
        matching_requirements=None,
        requirements_reviewed=False,
        delivery_lead_id=5,
        created_by=6,
        **extra,
    )


def _build(job):
    with hydrated_taxonomy(SKILLS):
        return build_proposal(job)


def test_clean_profile_needs_no_proposal():
    job = _job({"stack": {"must": [{"name": "Java"}, {"name": "SQL"}]}})
    assert _build(job) is None


def test_prose_column_is_replaced_by_champion_words_and_talk_items():
    job = _job(
        {"stack": {"must": [{"name": "SQL"}, {"name": "Python"}, {"name": "Git"}]}},
        must=[
            "Bardzo dobra znajomość SQL",
            "Python",
            "Git",
            "Minimum 5 lat doświadczenia jako Data Engineer",
        ],
    )
    proposal = _build(job)
    assert proposal is not None
    assert "prose_column" in proposal.reasons
    words = [row["words"][0] for row in proposal.after["rows"]]
    assert words[:3] == ["SQL", "Python", "Git"]
    talk = [t["name"] for t in proposal.after["talk"]]
    assert "Minimum 5 lat doświadczenia jako Data Engineer" in talk
    assert proposal.before["must"][0] == "Bardzo dobra znajomość SQL"
    assert proposal.can_apply


def test_parenthesis_in_rows_is_split():
    job = _job(
        {
            "stack": {
                "rows": [{"words": ["SQL (bardzo dobra znajomość)"], "level": "must"}],
                "must": [{"name": "SQL (bardzo dobra znajomość)"}],
                "nice": [],
            },
            "search": {"requirements": [["SQL (bardzo dobra znajomość)"]]},
        }
    )
    proposal = _build(job)
    assert proposal is not None and "paren" in proposal.reasons
    assert proposal.after["rows"][0]["words"] == ["SQL"]
    assert proposal.after["talk"][0]["name"] == "SQL — bardzo dobra znajomość"


def test_critical_keyword_row_the_gate_checks_is_not_demoted():
    """Decyzja B (14.10.2026): krytyczna, którą bramka sprawdza słowami wiersza
    („architektura chmury”), zostaje krytyczna — do 14.10 propozycja zdejmowała
    ją z nieprawdziwym powodem „wyszukiwanie nie sprawdzi” (audyt 13.10.2026)."""
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


def test_only_sentences_means_nothing_to_search_and_no_apply():
    job = _job({"stack": {"must": [{"name": "Praca w zespole"}]}})
    proposal = _build(job)
    assert proposal is not None
    assert "no_search_words" in proposal.reasons
    assert proposal.can_apply is False
    assert proposal.as_dict()["can_apply"] is False


def test_language_in_must_moves_to_the_language_field():
    job = _job(
        {
            "stack": {"must": [{"name": "Java"}, {"name": "Język angielski min. B2"}]},
            "basics": {"language": "polski"},
        }
    )
    proposal = _build(job)
    assert proposal is not None
    assert proposal.after["language"] == "polski, Język angielski min. B2"
    assert apply_payload(proposal)["basics"] == {
        "language": "polski, Język angielski min. B2"
    }


def _user(uid, *roles):
    return SimpleNamespace(
        id=uid,
        has_role=lambda role: role in roles,
        has_any_role=lambda *wanted: any(r in roles for r in wanted),
    )


def test_only_the_jobs_delivery_lead_or_hor_decides():
    job = _job({})
    assert can_decide(_user(5, UserRole.delivery_lead), job)
    assert can_decide(_user(6, UserRole.delivery_lead), job)
    assert not can_decide(_user(9, UserRole.delivery_lead), job)
    assert not can_decide(_user(5, UserRole.recruiter), job)
    assert can_decide(_user(1, UserRole.head_of_recruitment), job)
    assert can_decide(_user(2, UserRole.admin), job)


def test_migration_chains_and_entrypoint_imports_the_single_ddl_source():
    path = BACKEND / "alembic" / "versions" / "0438_requirement_cleanup_decisions.py"
    spec = importlib.util.spec_from_file_location("m0438", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.down_revision == "0437_candidate_source_created_at"
    text = (BACKEND / "entrypoint.sh").read_text()
    assert "from app.services import requirement_cleanup_schema" in text
    assert "*_REQUIREMENT_CLEANUP_DDL," in text

    from app.services.requirement_cleanup_schema import TABLE_DDL

    for statement in TABLE_DDL:
        assert "IF NOT EXISTS" in re.sub(r"\s+", " ", statement)
    assert "'applied','dismissed'" in TABLE_DDL[0]


def _kept(proposal, texts):
    """Pozycje, których nie ma ani w wierszach, ani w rozmowie, ani w języku,
    ani w opisie wymagań po zatwierdzeniu."""
    from app.services.champion_requirement_rows import expand_patch

    stack = expand_patch(apply_payload(proposal))["stack"]
    words = {w.casefold() for r in proposal.after["rows"] for w in r["words"]}
    talk = " | ".join(
        i["name"]
        for kind in ("skills", "domains")
        for i in proposal.after["experience"].get(kind) or []
    ).casefold()
    notes = str(stack.get("notes") or "").casefold()
    language = str(proposal.after["language"] or "").casefold()
    return [
        t
        for t in texts
        if t.casefold() not in words
        and t.casefold() not in talk
        and t.casefold() not in notes
        and t.casefold() not in language
    ]


def test_sentence_read_as_category_goes_to_talk_not_nowhere():
    """Przegląd 13.10.2026, bloker 1: zdanie czytane jako kategoria albo rola
    („… management”, „… business analysis”) znikało po „Zatwierdź”."""
    sentences = [
        "Knowledge of card lifecycle management",
        "Flexible approach to switch between technical development and business analysis",
    ]
    job = _job(
        {"stack": {"must": [{"name": "Java"}, *({"name": s} for s in sentences)]}}
    )
    proposal = _build(job)
    assert proposal is not None
    assert [r["words"] for r in proposal.after["rows"]] == [["Java"]]
    assert _kept(proposal, sentences) == []


def test_rows_over_the_limits_land_in_the_requirement_notes():
    """Przegląd 13.10.2026, bloker 2: ponad 10 „musi mieć” + 20 „mile widziane”
    znikało bez notki „Nie zmieściło się w wymaganiach”."""
    words = [f"system{i:02d}" for i in range(35)]
    job = _job(
        {
            "stack": {
                "must": [{"name": w} for w in words]
                + [{"name": "doświadczenie w przetargach"}],
                "notes": "Projekt dla banku.",
            }
        }
    )
    proposal = _build(job)
    assert proposal is not None
    assert len(proposal.after["rows"]) == 30
    assert _kept(proposal, [*words, "doświadczenie w przetargach"]) == []
    notes = apply_payload(proposal)["stack"]["notes"]
    assert notes.startswith("Projekt dla banku.")
    assert "Nie zmieściło się w wymaganiach" in notes


def test_talk_items_over_the_section_limit_stay_in_the_notes():
    """Zrzut produkcji 13.10.2026 (324353, 404749): lista „Rekruter sprawdza
    w rozmowie” ma limit 20 — kolejne zdania trafiają do opisu wymagań."""
    sentences = [f"Doświadczenie w projekcie numer {i} dla klienta" for i in range(25)]
    job = _job(
        {"stack": {"must": [{"name": "Java"}, *({"name": s} for s in sentences)]}}
    )
    proposal = _build(job)
    assert proposal is not None
    assert len(proposal.after["experience"]["skills"]) == 20
    assert _kept(proposal, sentences) == []
    assert "Do sprawdzenia w rozmowie:" in apply_payload(proposal)["stack"]["notes"]


# ── Rzadkie słowo „musi mieć” (27.10.2026) ──────────────────────────────────
# Pomiar na 129 profilach z wierszami (kopia z 22.10): 49 z 886 wierszy
# „musi mieć” miało mniej niż 10 osób w bazie, 12 — zero („Crisis plans”),
# a „SoapUI/ReadyAPI” 5 obok SoapUI 2 289.


def _counts(people: dict[str, int]):
    """Licznik osób jak lista kandydatów: wiersz = LUB jego słów."""
    calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    def count(words, exclude):
        calls.append((tuple(words), tuple(exclude)))
        return max((people.get(w, 500) for w in words), default=None)

    count.calls = calls
    return count


def _rows_profile(*rows, critical=None, exclude=None):
    profile = {
        "stack": {
            "rows": [{"words": list(words), "level": level} for words, level in rows],
            "critical": critical,
        }
    }
    if exclude:
        profile["search"] = {"exclude": exclude}
    return profile


def _build_counted(job, people):
    with hydrated_taxonomy(SKILLS):
        return build_proposal(job, row_count=_counts(people))


def test_rare_must_row_moves_to_talk():
    job = _job(
        _rows_profile((["Java"], "must"), (["Crisis plans"], "must"), critical=[])
    )
    proposal = _build_counted(job, {"Crisis plans": 0})
    assert proposal is not None
    assert proposal.reasons == ("rare_word",)
    assert [r["words"] for r in proposal.after["rows"]] == [["Java"]]
    assert [t["name"] for t in proposal.after["talk"]] == ["Crisis plans"]
    assert proposal.after["rare"] == [
        {"words": ["Crisis plans"], "people": 0, "action": "talk", "parts": None}
    ]
    assert proposal.can_apply
    skills = apply_payload(proposal)["experience"]["skills"]
    assert [s["name"] for s in skills] == ["Crisis plans"]


def test_rows_with_enough_people_need_no_proposal():
    job = _job(_rows_profile((["Java"], "must"), (["SQL"], "must"), critical=[]))
    assert _build_counted(job, {"SQL": 20}) is None
    # Bez liczby (nie policzono jeszcze) nie ma powodu — nic nie zgadujemy.
    assert _build(job) is None


def test_glued_variants_are_split_when_parts_find_people():
    job = _job(
        _rows_profile(
            (["Java"], "must"),
            (["SoapUI/ReadyAPI"], "must"),
            (["GitOps (ArgoCD/FluxCD)"], "must"),
            critical=[],
        )
    )
    proposal = _build_counted(
        job,
        {
            "SoapUI/ReadyAPI": 5,
            "SoapUI": 2289,
            "ReadyAPI": 40,
            "GitOps (ArgoCD/FluxCD)": 0,
            "GitOps": 3,
            "ArgoCD": 2,
            "FluxCD": 1,
        },
    )
    assert proposal is not None
    assert proposal.reasons == ("rare_word",)
    assert [r["words"] for r in proposal.after["rows"]] == [
        ["Java"],
        ["SoapUI", "ReadyAPI"],
    ]
    # Części GitOps razem dalej < 20 osób — całość idzie do rozmowy.
    assert [t["name"] for t in proposal.after["talk"]] == ["GitOps (ArgoCD/FluxCD)"]
    assert [r["action"] for r in proposal.after["rare"]] == ["split", "talk"]


def test_rare_rule_skips_critical_and_nice_rows():
    """AI filtruje tylko po krytycznych — tego nie zmieniamy; mile widziane
    niczego nie zawężają."""
    job = _job(
        _rows_profile(
            (["Java"], "must"),
            (["Kotlin"], "critical"),
            (["Crisis plans"], "nice"),
            critical=["Kotlin"],
        )
    )
    assert _build_counted(job, {"Kotlin": 3, "Crisis plans": 0}) is None


def test_last_required_row_is_never_moved_to_talk():
    """Rekrutacja nie traci ostatniego słowa do szukania — zostaje wiersz
    z największą liczbą osób, reszta rzadkich idzie do rozmowy."""
    job = _job(
        _rows_profile(
            (["Crisis plans"], "must"), (["SteerCo Reporting"], "must"), critical=[]
        )
    )
    proposal = _build_counted(job, {"Crisis plans": 0, "SteerCo Reporting": 9})
    assert proposal is not None
    assert [r["words"] for r in proposal.after["rows"]] == [["SteerCo Reporting"]]
    assert [t["name"] for t in proposal.after["talk"]] == ["Crisis plans"]
    assert proposal.can_apply

    single = _job(_rows_profile((["Crisis plans"], "must"), critical=[]))
    assert _build_counted(single, {"Crisis plans": 0}) is None


def test_rare_count_uses_the_profile_exclude_words():
    job = _job(
        _rows_profile(
            (["Java"], "must"), (["Crisis plans"], "must"), critical=[], exclude=["PHP"]
        )
    )
    count = _counts({"Crisis plans": 0})
    with hydrated_taxonomy(SKILLS):
        build_proposal(job, row_count=count)
    assert (("Crisis plans",), ("PHP",)) in count.calls


def test_glued_variants_mirror_the_editor():
    from app.services.requirement_cleanup import glued_variants

    assert glued_variants("SoapUI/ReadyAPI") == ["SoapUI", "ReadyAPI"]
    assert glued_variants("GitOps (ArgoCD/FluxCD)") == ["GitOps", "ArgoCD", "FluxCD"]
    assert glued_variants("Java") is None
    assert glued_variants("C/C++") is None  # „C” ma mniej niż 2 znaki


def test_applied_decision_does_not_hide_a_new_rare_word():
    """23 z 24 decyzji na otwartych rekrutacjach (kopia z 22.10) to „Zatwierdź”
    starej propozycji — rzadkie słowo jest nową informacją. „Odrzuć” chowa."""
    from app.services.requirement_cleanup import _hidden

    job = _job(
        _rows_profile((["Java"], "must"), (["Crisis plans"], "must"), critical=[])
    )
    proposal = _build_counted(job, {"Crisis plans": 0})
    digest = proposal.profile_hash
    assert _hidden(None, proposal) is False
    assert _hidden((digest, "applied"), proposal) is False
    assert _hidden((digest, "dismissed"), proposal) is True
    assert _hidden(("b" * 64, "dismissed"), proposal) is False
    other = _build(_job({"stack": {"must": [{"name": "Praca w zespole"}]}}))
    assert _hidden((other.profile_hash, "applied"), other) is True


async def test_row_counts_cache_counts_only_missing_rows_within_the_deadline(
    monkeypatch,
):
    import time

    from app.services import requirement_row_counts as counts

    counts.clear()
    asked: list[list[str]] = []

    async def fake_count(db, words, exclude):
        asked.append(list(words))
        return 3

    class _Db:
        def begin_nested(self):
            class _Tx:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *exc):
                    return False

            return _Tx()

    monkeypatch.setattr(counts, "count_row", fake_count)
    rows = [(["Crisis plans"], []), (["crisis  PLANS"], []), (["Java"], ["PHP"])]
    done = await counts.ensure(_Db(), rows, deadline=time.monotonic() + 60)
    assert done == 2 and asked == [["Crisis plans"], ["Java"]]
    assert counts.cached(["Crisis plans"], []) == 3
    assert counts.cached(["Java"], []) is None  # inne „Wyklucz” = inna liczba
    assert await counts.ensure(_Db(), rows, deadline=time.monotonic() + 60) == 0
    # Wpis bliski wygaśnięcia pętla liczy ponownie.
    assert (
        await counts.ensure(
            _Db(),
            rows,
            deadline=time.monotonic() + 60,
            fresh_for=counts.CACHE_TTL_SECONDS,
        )
        == 2
    )
    counts.clear()
    assert await counts.ensure(_Db(), rows, deadline=time.monotonic() - 1) == 0
    counts.clear()


def test_rare_row_with_full_talk_list_lands_in_the_notes():
    """Przegląd 27.10: przy pełnej liście rozmowy (20) rzadki wiersz znikał —
    schodził z wierszy, a do opisu wymagań nie trafiał."""
    profile = _rows_profile((["Java"], "must"), (["Crisis plans"], "must"), critical=[])
    profile["experience"] = {
        "skills": [{"name": f"Temat {i}", "level": "must"} for i in range(20)]
    }
    proposal = _build_counted(_job(profile), {"Crisis plans": 0})
    assert proposal is not None
    assert "Crisis plans" in apply_payload(proposal)["stack"]["notes"]


def test_long_rare_row_is_capped_on_the_talk_list_and_kept_whole_in_notes():
    words = [f"LongToolNameAlphaXYZ{i}Suite" for i in range(7)]
    job = _job(_rows_profile((["Java"], "must"), (words, "must"), critical=[]))
    proposal = _build_counted(job, {w: 0 for w in words})
    names = [s["name"] for s in apply_payload(proposal)["experience"]["skills"]]
    assert names and all(len(n) <= 160 for n in names)
    assert " / ".join(words) in apply_payload(proposal)["stack"]["notes"]


def test_split_row_never_reuses_the_head_of_another_row():
    """Zapis zostawia jeden wiersz na pierwsze słowo (`split_rows`) — wiersz
    po rozdzieleniu nie może zaczynać się od słowa innego wiersza."""
    from app.services.champion_requirement_rows import clean_rows

    job = _job(
        _rows_profile(
            (["Java"], "must"),
            (["SoapUI"], "must"),
            (["SoapUI/ReadyAPI"], "must"),
            critical=[],
        )
    )
    proposal = _build_counted(
        job, {"SoapUI/ReadyAPI": 3, "SoapUI": 500, "ReadyAPI": 40}
    )
    saved = clean_rows(apply_payload(proposal)["stack"]["rows"])
    assert [r["words"] for r in saved] == [["Java"], ["SoapUI"], ["ReadyAPI", "SoapUI"]]

    clash = _job(
        _rows_profile(
            (["SoapUI"], "must"),
            (["ReadyAPI"], "nice"),
            (["SoapUI/ReadyAPI"], "must"),
            critical=[],
        )
    )
    proposal = _build_counted(
        clash, {"SoapUI/ReadyAPI": 3, "SoapUI": 500, "ReadyAPI": 40}
    )
    assert [r["action"] for r in proposal.after["rare"]] == ["talk"]
    assert [t["name"] for t in proposal.after["talk"]] == ["SoapUI/ReadyAPI"]


def test_digest_changes_when_the_counts_change_the_proposal():
    """„Zatwierdź” niesie odcisk tego, co DL widział — liczby osób nie wchodzą
    do odcisku profilu, więc sam `profile_hash` nie wystarcza (przegląd 27.10)."""
    job = _job(
        _rows_profile(
            (["Java"], "must"),
            (["SQL (bardzo dobra znajomość)"], "must"),
            (["Crisis plans"], "must"),
            critical=[],
        )
    )
    rare = _build_counted(job, {"Crisis plans": 0})
    plain = _build_counted(job, {"Crisis plans": 25})
    assert rare.profile_hash == plain.profile_hash
    assert rare.digest != plain.digest
    assert rare.as_dict()["digest"] == rare.digest
    assert _build_counted(job, {"Crisis plans": 0}).digest == rare.digest
