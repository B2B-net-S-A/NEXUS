"""Schodki po wymaganiach w kolejce kart od systemu (decyzja Artura 23.11.2026, wariant B)."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services import requirement_steps as steps_mod
from app.services import review_batch as rb
from app.services import review_batch_order as order
from app.services.requirement_steps import Steps

NOW = datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc)


def _card(pid, score, *, steps=None, missing_must=(), cautions=()):
    return rb.PendingCard(
        process_id=pid,
        job_id=1,
        candidate_id=pid,
        owner_id=None,
        score=score,
        opened_at=NOW,
        missing_must=tuple(missing_must),
        cautions=tuple(cautions),
        facts=order.OrderFacts(steps=steps),
    )


def _steps(must_met, must_total, nice_met=0, nice_total=0, critical_missing=0):
    must = tuple(
        (f"m{i}", "experience" if i < must_met else "none") for i in range(must_total)
    )
    nice = tuple(
        (f"n{i}", "mention" if i < nice_met else "none") for i in range(nice_total)
    )
    return Steps(critical_missing=critical_missing, must=must, nice=nice)


def test_more_must_have_met_goes_first_even_with_lower_score():
    # Kolejka z kopii 23.11 (10 musi mieć): 7/10 stało 4., za osobami z 3/10.
    six = _card(1, 68.1, steps=_steps(6, 10))
    three = _card(2, 65.5, steps=_steps(3, 10))
    seven = _card(4, 68.8, steps=_steps(7, 10, 2, 7))
    five = _card(8, 67.3, steps=_steps(5, 10, 3, 7))
    ordered = order.order_cards([six, three, seven, five])
    assert [c.process_id for c in ordered] == [4, 1, 8, 2]


def test_nice_to_have_only_breaks_a_tie_then_score():
    a = _card(1, 80.0, steps=_steps(5, 5, 0, 3))
    b = _card(2, 66.0, steps=_steps(5, 5, 2, 3))
    c = _card(3, 70.0, steps=_steps(5, 5, 2, 3))
    assert [x.process_id for x in order.order_cards([a, b, c])] == [3, 2, 1]


def test_missing_critical_still_goes_last():
    full = _card(1, 60.0, steps=_steps(2, 4))
    gap = _card(2, 90.0, steps=_steps(4, 4, critical_missing=1))
    assert [c.process_id for c in order.order_cards([gap, full])] == [1, 2]


def test_engine_unknown_must_does_not_push_back_when_steps_known():
    # „?” silnika w ``missing_must`` to nie brak: liczy dowód z CV.
    unknown = _card(1, 70.0, steps=_steps(4, 4), missing_must=("python",))
    weaker = _card(2, 75.0, steps=_steps(2, 4))
    assert [c.process_id for c in order.order_cards([weaker, unknown])] == [1, 2]


def test_without_steps_order_is_as_before():
    gap = _card(1, 90.0, missing_must=("Java",))
    clean = _card(2, 70.0)
    assert [c.process_id for c in order.order_cards([gap, clean])] == [2, 1]


def test_job_requirements_split_critical_must_and_nice():
    job = SimpleNamespace(
        champion_profile={
            "stack": {
                "critical": ["SoapUI"],
                "must": [{"name": "SoapUI"}, {"name": "Postman lub Swagger"}],
                "nice": [{"name": "Xray"}],
            }
        }
    )
    reqs = steps_mod.job_requirements(job)
    assert [r.label for r in reqs.critical] == ["SoapUI"]
    assert [(r.label, r.words) for r in reqs.must] == [
        ("Postman lub Swagger", ("Postman", "Swagger"))
    ]
    assert [r.label for r in reqs.nice] == ["Xray"]


def test_job_without_profile_has_no_requirements():
    assert steps_mod.job_requirements(SimpleNamespace(champion_profile=None)).empty


@pytest.mark.asyncio
async def test_steps_count_any_word_of_the_row(monkeypatch):
    job = SimpleNamespace(
        champion_profile={
            "stack": {
                "critical": [],
                "must": [{"name": "Postman lub Swagger"}, {"name": "Kibana"}],
                "nice": [{"name": "Xray"}],
            }
        }
    )

    async def fake_evidence(db, people, labels):
        return {(7, "Swagger"): ("mention", 0), (7, "Xray"): ("experience", 12)}

    monkeypatch.setattr("app.services.review_batch_facts.evidence_for", fake_evidence)
    got = await steps_mod.steps_for(None, job, [SimpleNamespace(id=7)])
    assert got[7].counts() == {
        "critical_missing": 0,
        "must_met": 1,
        "must_total": 2,
        "nice_met": 1,
        "nice_total": 1,
    }
    assert got[7].as_dict()["must"][0] == {
        "label": "Postman lub Swagger",
        "state": "mention",
    }


@pytest.mark.asyncio
async def test_steps_are_off_without_batch(monkeypatch):
    monkeypatch.setattr(rb.settings, "REVIEW_BATCH_ENABLED", False, raising=False)
    job = SimpleNamespace(champion_profile={"stack": {"must": [{"name": "Java"}]}})
    assert await steps_mod.steps_if_enabled(None, job, [1]) == {}


@pytest.mark.asyncio
async def test_pool_window_puts_more_must_have_first(monkeypatch):
    """Dobór z puli: ten sam klucz, więc do porcji wchodzą najpierw spełniający."""
    from app.services import new_column_autofill as nca

    class FakeDb:
        async def scalar(self, _query):
            return None

        async def get(self, _model, _id):
            return SimpleNamespace(id=_id)

    async def no_facts(*_a, **_k):
        return {}

    async def no_bonus(*_a, **_k):
        return {}

    async def fake_steps(_db, _job, ids):
        return {
            1: _steps(3, 10),
            2: _steps(7, 10),
            3: _steps(7, 10, critical_missing=1),
            4: _steps(3, 10),
        }

    monkeypatch.setattr("app.services.known_queue_points.facts_for", no_facts)
    monkeypatch.setattr(order, "pick_bonuses", no_bonus)
    monkeypatch.setattr(steps_mod, "steps_if_enabled", fake_steps)
    picks = [
        nca.Pick(
            candidate_id=cid, score=score, run_id=None, matched_must=(), missing_must=()
        )
        for cid, score in ((1, 80.0), (2, 66.0), (3, 90.0), (4, 70.0))
    ]
    ordered = await nca._with_known_points(FakeDb(), 5, picks)
    # 7/10 przed 3/10 mimo niższego wyniku; brak krytycznej na końcu mimo 90%.
    assert [p.candidate_id for p in ordered] == [2, 1, 4, 3]
