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


# ── Koszt w „Moich następnych krokach” (loop_stall 25.11.2026) ─────────────


class _BoardsDb:
    """Atrapa sesji ``steps_for_jobs``: osoby z ``select(Candidate)``, oś
    technologii z wierszy ``(candidate_id, skill_canonical, months)``."""

    def __init__(self, people, usage=()):
        self.people = list(people)
        self.usage = list(usage)

    async def scalars(self, _query):
        return SimpleNamespace(all=lambda: list(self.people))

    async def execute(self, _query):
        return SimpleNamespace(all=lambda: list(self.usage))


def _person(cid, cv="", skills=()):
    return SimpleNamespace(
        id=cid,
        raw_cv_text=cv,
        skills=list(skills),
        verified_tech=[],
        tags=[],
        cv_extracted_data=None,
        skills_manually_curated=False,
    )


def _board_job(jid, must, nice=(), critical=()):
    stack = {
        "critical": list(critical),
        "must": [{"name": m} for m in must],
        "nice": [{"name": n} for n in nice],
    }
    return SimpleNamespace(id=jid, champion_profile={"stack": stack})


@pytest.mark.asyncio
async def test_boards_check_each_person_only_against_own_requirements(monkeypatch):
    """25.11.2026 strażnik pętli zdarzeń złapał 34 zastoje „Moich następnych
    kroków” w ``evidence_for`` → ``_text_hit``: każda osoba ze wszystkich
    Tablic szła przez słowa wszystkich rekrutacji. Kopia z 25.11, rekruter
    z 25 Tablicami: 850 osób × 204 słowa = 173 400 par i 33 s CPU w pętli,
    a Tablice potrzebują 12 123 par (osoba × słowa jej rekrutacji)."""
    from app.services import scoring_service

    monkeypatch.setattr(rb.settings, "REVIEW_BATCH_ENABLED", True, raising=False)
    boards, people = {}, []
    for jid in range(1, 6):
        cids = [100 * jid + i for i in range(10)]
        people += [_person(cid) for cid in cids]
        words = [f"narzędzie{jid}{k}" for k in range(4)]
        boards[jid] = (_board_job(jid, words[:3], nice=words[3:]), cids)
    checked = []
    real = scoring_service.skill_present

    def counting(required, skills, **kwargs):
        checked.append(required)
        return real(required, skills, **kwargs)

    monkeypatch.setattr(scoring_service, "skill_present", counting)
    got = await steps_mod.steps_for_jobs(_BoardsDb(people), boards)
    assert {jid: len(per) for jid, per in got.items()} == {j: 10 for j in boards}
    # 5 Tablic × 10 osób × 4 słowa, a nie 50 osób × 20 słów wszystkich Tablic.
    assert len(checked) == 5 * 10 * 4


@pytest.mark.asyncio
async def test_boards_give_the_same_steps_as_each_board_alone(monkeypatch):
    """Wynik ``my-next-steps`` bez zmian: każda Tablica ma te same schodki co
    ``steps_for`` liczone dla niej samej. Osoba 7 stoi na dwóch Tablicach,
    słowa się powtarzają, wiersz „Postman lub Swagger” spełnia jedno słowo."""
    monkeypatch.setattr(rb.settings, "REVIEW_BATCH_ENABLED", True, raising=False)
    people = [
        _person(7, cv="testy api w postman, java 17, kafka", skills=["Docker"]),
        _person(8, cv="javascript, react, node.js"),
        _person(9, cv="c++ i c#, .net core; sql server"),
        _person(10, cv=""),
    ]
    usage = [(7, "kafka", 30), (10, "java", 14)]
    boards = {
        1: (
            _board_job(1, ["Java", "Postman lub Swagger"], nice=["Kafka"]),
            [7, 8, 10, 7],
        ),
        2: (
            _board_job(
                2, ["Docker", "C#"], nice=[".NET", "React"], critical=["Docker"]
            ),
            [7, 9],
        ),
        3: (_board_job(3, ["SQL Server"], nice=["Java"]), [9, 10, 8]),
    }
    db = _BoardsDb(people, usage)
    by_id = {p.id: p for p in people}
    got = await steps_mod.steps_for_jobs(db, boards)
    for jid, (job, cids) in boards.items():
        alone = await steps_mod.steps_for(
            db, job, [by_id[c] for c in dict.fromkeys(cids)]
        )
        assert got[jid] == alone, jid
    assert got[1][7].must == (("Java", "mention"), ("Postman lub Swagger", "mention"))
    assert got[1][7].nice == (("Kafka", "experience"),)
    assert got[1][8].must == (("Java", "none"), ("Postman lub Swagger", "none"))
    assert got[2][9].nice == ((".NET", "mention"), ("React", "none"))
