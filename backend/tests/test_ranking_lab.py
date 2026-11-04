"""Pomiar i podgląd wag „Dop.” (``ranking_lab``) — bez bazy.

Najważniejsze: „Dop.” złożone ze składników policzonych profilem sondy musi
być DOKŁADNIE tym, co silnik liczy wagami szkicu. Inaczej podgląd na żywo
i pomiar na historii pokazywałyby ranking, którego nie ma.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.core.scheduling import business_today
from app.services import ranking_lab as lab
from app.services import ranking_weights as rw
from app.services import scoring_service as scoring
from app.services.request_matching_context import build_request_context
from tests.test_scoring_service import make_candidate, make_job

_JOB = dict(
    title="Senior Python Developer",
    must_skills=["Python", "Django", "PostgreSQL"],
    nice_skills=["Docker", "Kubernetes"],
    salary_min=120,
    salary_max=160,
    location="Kraków",
    remote_policy=SimpleNamespace(value="hybrid"),
)

_PEOPLE = [
    dict(skills=["Python", "Django", "PostgreSQL", "Docker"], location="Kraków"),
    dict(skills=["Python"], location="Gdańsk", expected_rate_hourly=200),
    dict(skills=[], location=None),
    dict(
        skills=["Django", "Kubernetes"],
        location="Kraków",
        expected_rate_hourly=130,
        availability_offset_days=90,
    ),
    dict(skills=["Python", "PostgreSQL"], location="Warszawa"),
]


def _job():
    # Daty liczone przy wywołaniu, nie przy imporcie (test_no_import_time_dates).
    return make_job(**_JOB, deadline=business_today() + timedelta(days=30))


def _candidate(**person):
    offset = person.pop("availability_offset_days", None)
    if offset is not None:
        person["availability_date"] = business_today() + timedelta(days=offset)
    return make_candidate(**person)


_DRAFTS = [
    rw.PanelWeights(60, 10, 5, 70),
    rw.PanelWeights(60, 30, 5, 70),
    rw.PanelWeights(60, 10, 20, 70),
    rw.PanelWeights(100, 0, 0, 70),
    rw.PanelWeights(0, 50, 50, 70),
]


async def _score(candidate, job, profile, similarity):
    context = build_request_context(job, profile)
    return await scoring.score_candidate_job(
        candidate,
        context.as_job(),
        None,
        semantic_similarity=similarity,
        profile=context.profile(),
        base_fit=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("renormalize", [False, True])
@pytest.mark.parametrize(
    "draft", _DRAFTS, ids=lambda d: f"{d.semantic}-{d.skills}-{d.location}"
)
async def test_components_rebuild_the_engine_score_for_any_weights(
    monkeypatch, renormalize, draft
):
    monkeypatch.setattr(settings, "SCORE_RENORMALIZE_UNSCORED_LAYERS", renormalize)
    job = _job()
    weights = rw.engine_weights(draft)
    target = scoring.WeightProfile(id=7, name="szkic", **weights)
    for index, person in enumerate(_PEOPLE):
        candidate = _candidate(id=index + 1, **person)
        similarity = 0.35 + index * 0.1
        probe = await _score(candidate, job, lab.PROBE, similarity)
        components = lab.components_of(probe, renormalize=renormalize)
        direct = await _score(candidate, job, target, similarity)
        rebuilt = lab.score(components, weights, renormalize=renormalize)
        assert rebuilt == pytest.approx(direct.total, abs=1e-6), (index, person)


@pytest.mark.asyncio
async def test_published_built_in_weights_rebuild_exactly(monkeypatch):
    monkeypatch.setattr(settings, "SCORE_RENORMALIZE_UNSCORED_LAYERS", False)
    job = _job()
    candidate = _candidate(**_PEOPLE[0])
    probe = await _score(candidate, job, lab.PROBE, 0.6)
    direct = await _score(candidate, job, scoring.DEFAULT_PROFILE, 0.6)
    built_in = {name: getattr(scoring.DEFAULT_PROFILE, name) for name in rw.BASE_LAYERS}
    assert lab.score(
        lab.components_of(probe, renormalize=False), built_in, renormalize=False
    ) == pytest.approx(direct.total, abs=1e-6)


@pytest.mark.asyncio
async def test_seniority_penalty_survives_in_the_factor(monkeypatch):
    monkeypatch.setattr(settings, "SCORE_RENORMALIZE_UNSCORED_LAYERS", False)
    monkeypatch.setattr(
        scoring, "_champion_seniority_factor", lambda *_: (0.84, "za mało lat")
    )
    job = _job()
    candidate = _candidate(**_PEOPLE[0])
    probe = await _score(candidate, job, lab.PROBE, 0.7)
    components = lab.components_of(probe, renormalize=False)
    assert components.factor == pytest.approx(0.84)
    weights = rw.engine_weights(rw.PanelWeights(60, 30, 5, 70))
    target = scoring.WeightProfile(**weights)
    direct = await _score(candidate, job, target, 0.7)
    assert lab.score(components, weights, renormalize=False) == pytest.approx(
        direct.total, abs=1e-6
    )


def _components(cid: int, sem: float, sk: float, *, matched=1, total=2):
    return lab.Components(
        candidate_id=cid,
        layers={
            "semantic": (sem, 1.0, True),
            "skills": (sk, 1.0, True),
            "salary": (0.65, 1.0, True),
            "location": (1.0, 1.0, True),
            "availability": (0.0, 1.0, True),
        },
        extra=None,
        factor=1.0,
        matched_must=matched,
        must_total=total,
    )


def _case(job_id=1):
    # Osoba 3 (wysłana do klienta) ma pełny stack, ale słabsze CV.
    head = {
        1: _components(1, 0.95, 0.2),
        2: _components(2, 0.90, 0.3),
        3: _components(3, 0.70, 1.0),
        4: _components(4, 0.60, 0.1, matched=0),
    }
    order = [1, 2, 3, 4] + list(range(100, 160))
    return lab.Case(
        job_id=job_id,
        title="Rekrutacja testowa",
        location=None,
        order=order,
        positives=frozenset({3, 150}),
        head=head,
        renormalize=False,
    )


def test_more_skills_moves_the_sent_person_up():
    case = _case()
    now = rw.engine_weights(rw.PanelWeights(60, 10, 5, 70))
    skills = rw.engine_weights(rw.PanelWeights(60, 60, 5, 70))
    assert case.ranked(now)[:4] == [1, 2, 3, 4]
    assert case.ranked(skills)[0] == 3
    # Poza „głową” kolejność wektora zostaje.
    assert case.ranked(skills)[4:] == case.order[4:]


def test_metrics_and_compare():
    cases = [_case(1), _case(2)]
    now = rw.engine_weights(rw.PanelWeights(60, 10, 5, 70))
    skills = rw.engine_weights(rw.PanelWeights(60, 60, 5, 70))
    before = lab.metrics(cases, now, 70)
    assert before["page1_hit"] == 100.0
    assert before["median_first"] == 3
    # Właściwe na pozycjach 3 i 51 → połowa w top 50.
    assert before["top50_share"] == 50.0

    result = lab.compare(cases, now, 70, skills, 70)
    assert result["jobs"] == 2
    assert result["after"]["median_first"] == 1
    assert result["needs_reason"] is False
    assert result["biggest_changes"][0]["before"] == 3
    assert result["biggest_changes"][0]["after"] == 1


def test_drop_over_two_points_needs_reason():
    good = _case(1)
    bad = _case(2)
    bad.positives = frozenset({4})  # najsłabsze CV, bez trafionego must
    cases = [good, bad]
    now = rw.engine_weights(rw.PanelWeights(60, 10, 5, 70))
    worse = rw.engine_weights(rw.PanelWeights(100, 0, 0, 70))
    result = lab.compare(cases, now, 70, worse, 70)
    assert result["needs_reason"] is (result["max_drop_pt"] > lab.MAX_DROP_PT)


def test_proposals_follow_threshold_and_must():
    case = _case()
    weights = rw.engine_weights(rw.PanelWeights(60, 10, 5, 70))
    scores = {
        cid: lab.score(c, weights, renormalize=False) for cid, c in case.head.items()
    }
    expected = sum(
        1
        for cid, value in scores.items()
        if value >= 60 and case.head[cid].matched_must
    )
    assert case.proposals(weights, 60) == expected
    assert case.proposals(weights, 99) == 0


def test_components_payload_is_json_ready():
    payload = _components(1, 0.5, 0.5).as_dict()
    assert payload["layers"]["semantic"] == [0.5, 1.0, True]
    assert payload["factor"] == 1.0


def test_must_words_take_two_first_technologies():
    words = lab.must_words(
        [{"name": "Java"}, "Spring Boot z doświadczeniem", {"name": "Kafka"}, "SQL"]
    )
    assert len(words) == 2


def test_probe_weights_every_layer():
    for name in rw.BASE_LAYERS:
        assert getattr(lab.PROBE, name) > 0


def test_normalized_rejects_all_zero():
    with pytest.raises(ValueError):
        lab.normalized({name: 0 for name in rw.BASE_LAYERS})


def test_replace_profile_keeps_shape():
    # Sonda jest zwykłym profilem — ``build_request_context`` ją przyjmuje.
    context = build_request_context(_job(), replace(lab.PROBE))
    assert context.weights["champion_fit"] == 0


class _NotesDb:
    def __init__(self):
        self.calls = []

    async def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return [(1,)] if len(self.calls) == 1 else [(1, "Java w projekcie", None)]


@pytest.mark.asyncio
async def test_measurement_reads_only_notes_written_before_the_job_opened():
    """Notatki ze screeningu tej rekrutacji to etykieta, nie dane z dnia
    otwarcia — bez daty pomiar faworyzowałby wagę umiejętności."""
    from datetime import datetime, timezone

    from app.services import must_text_evidence as mte

    db = _NotesDb()
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
    await mte._load_notes(db, [1], "java", before=t0)
    assert len(db.calls) == 2
    for sql, params in db.calls:
        assert "coalesce(source_created_at, created_at) < :before" in sql
        assert params["before"] == t0

    plain = _NotesDb()
    await mte._load_notes(plain, [1], "java")
    for sql, params in plain.calls:
        assert ":before" not in sql and "before" not in params


def test_measurement_and_preview_pass_the_opening_day():
    source = (Path(lab.__file__)).read_text(encoding="utf-8")
    assert "reviewed_evidence=False, evidence_before=t0" in source
    fit = (Path(lab.__file__).with_name("canonical_fit.py")).read_text(encoding="utf-8")
    assert "attach_prior_screening(db, job, candidates, before=evidence_before)" in fit
    assert "before=before" in fit


@pytest.mark.parametrize(
    ("snapshot", "ok"),
    [
        (
            {
                "weights": {"semantic": 60},
                "user_id": None,
                "client_id": None,
                "active": True,
            },
            True,
        ),
        ({"weights": {"semantic": 60}, "client_id": 42}, False),
        ({"weights": {"semantic": 60}, "user_id": 7}, False),
        ({"weights": {"semantic": 60}, "active": False}, False),
    ],
)
def test_restore_takes_only_global_active_profiles(snapshot, ok):
    from app.services.ranking_publish import is_global_snapshot

    assert is_global_snapshot(snapshot) is ok


_CASES = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "lib"
    / "__fixtures__"
    / "ranking-score-cases.json"
)


@pytest.mark.skipif(not _CASES.is_file(), reason="brak katalogu frontend w checkoucie")
def test_shared_cases_with_the_front_match_python():
    """Ten sam plik czyta ``rankingMath.test.ts`` — podgląd w przeglądarce
    liczy „Dop.” tak samo jak pomiar na serwerze."""
    cases = json.loads(_CASES.read_text(encoding="utf-8"))["cases"]
    assert len(cases) >= 20
    for case in cases:
        raw = case["components"]
        components = lab.Components(
            candidate_id=raw["candidate_id"],
            layers={k: (v[0], v[1], v[2]) for k, v in raw["layers"].items()},
            extra=tuple(raw["extra"]) if raw["extra"] else None,
            factor=raw["factor"],
            matched_must=raw["matched_must"],
            must_total=raw["must_total"],
        )
        assert lab.score(
            components, case["weights"], renormalize=case["renormalize"]
        ) == pytest.approx(case["expected"], abs=1e-3)
        assert rw.engine_weights(rw.PanelWeights.from_dict(case["panel"])) == {
            **case["weights"],
            "champion_fit": rw.CHAMPION_RESERVE,
        }
