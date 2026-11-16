"""F51 ``role_fit``: wejście dla modelu, odczyt werdyktu i liczby testu na historii."""

from __future__ import annotations

from datetime import date

from app.services import role_fit
from scripts.eval_role_fit import Decision, sample, simulate, verdict_table

AS_OF = date(2026, 11, 10)


def _exp(role, start, end=None, current=False, **kw):
    return {"role": role, "start": start, "end": end, "is_current": current, **kw}


# ── Wejście ─────────────────────────────────────────────────────────────────


def test_recent_experience_keeps_last_three_years_newest_first():
    items, recent = role_fit.recent_experience(
        [
            _exp("Tester", "2015-01", "2019-12"),
            _exp("QA Lead", "2023-03", current=True),
            _exp("Tester", "2020-01", "2024-02"),
        ],
        as_of=AS_OF,
    )
    assert recent is True
    assert [i["role"] for i in items] == ["QA Lead", "Tester"]


def test_recent_experience_falls_back_to_last_known_when_nothing_recent():
    items, recent = role_fit.recent_experience(
        [
            _exp("A", "2010-01", "2012-01"),
            _exp("B", "2012-02", "2018-05"),
            _exp("C", "2005-01", "2009-01"),
        ],
        as_of=AS_OF,
    )
    assert recent is False
    assert [i["role"] for i in items] == ["B", "A"]


def test_recent_experience_skips_work_started_after_the_decision():
    items, _ = role_fit.recent_experience(
        [
            _exp("Później", "2026-12", current=True),
            _exp("Wtedy", "2022-01", current=True),
        ],
        as_of=AS_OF,
    )
    assert [i["role"] for i in items] == ["Wtedy"]


def test_recent_experience_ignores_junk_items():
    items, recent = role_fit.recent_experience(
        [None, "x", {"start": "2024-01"}], as_of=AS_OF
    )
    assert items == [] and recent is False


def test_person_block_says_when_cv_has_no_experience():
    block = role_fit.person_block([], None, as_of=AS_OF)
    assert "Brak doświadczenia zawodowego" in block


def test_job_block_prefers_one_liner_over_about():
    block = role_fit.job_block(
        "Tester", one_liner="Zdanie.", about="Opis", critical=["Selenium"]
    )
    assert "W skrócie: Zdanie." in block
    assert "O projekcie" not in block
    assert "Krytyczne umiejętności: Selenium" in block


# ── Wyjście ─────────────────────────────────────────────────────────────────


def test_parse_reads_json_in_code_fence():
    assert role_fit.parse(
        '```json\n{"verdict": "NIE", "why": " inna  rola "}\n```'
    ) == (
        "nie",
        "inna rola",
    )


def test_parse_refuses_unknown_verdict_and_garbage():
    assert role_fit.parse('{"verdict": "może", "why": "x"}') is None
    assert role_fit.parse("brak") is None
    assert role_fit.parse(None) is None


def test_assess_returns_none_when_the_model_fails(monkeypatch):
    def boom(_prompt):
        raise RuntimeError("down")

    monkeypatch.setattr(role_fit, "call_model", boom)
    assert role_fit.assess("p") is None


# ── Liczby testu ────────────────────────────────────────────────────────────


def _d(stage_id, job, stage, score, verdict, reason=None, day="2026-11-10"):
    return Decision(stage_id, job, stage_id, stage, day, score, reason, verdict=verdict)


def test_sample_takes_every_role_rejection_and_weights_strata():
    rows = [_d(i, 1, "screening", 70, None) for i in range(10)]
    rows += [
        _d(100 + i, 1, "rejected", 70, None, "other_level_or_role") for i in range(3)
    ]
    rows += [_d(200 + i, 1, "rejected", 70, None, "missing_skill") for i in range(8)]
    picked = sample(rows, pasuje=5, other_rejected=2, seed=1)
    strata = [r.stratum for r in picked]
    assert strata.count("inna_rola") == 3
    assert {r.weight for r in picked if r.stratum == "pasuje"} == {2.0}
    assert {r.weight for r in picked if r.stratum == "inne_odrzucenie"} == {4.0}
    assert sample(rows, pasuje=5, other_rejected=2, seed=1) == picked


def test_verdict_table_counts_fit_and_role_share():
    rows = [
        _d(1, 1, "screening", 70, "tak"),
        _d(2, 1, "rejected", 70, "nie", "other_level_or_role"),
        _d(3, 1, "rejected", 70, "nie", "missing_skill"),
    ]
    table = {r["verdict"]: r for r in verdict_table(rows)}
    assert table["tak"]["pasuje_proba_pct"] == 100.0
    assert table["nie"]["pasuje_proba_pct"] == 0.0
    assert table["nie"]["inna_rola_wsrod_odrzucen_proba_pct"] == 50.0


def test_simulate_moves_nie_out_of_the_top_half():
    rows = [
        _d(1, 1, "rejected", 90, "nie", "other_level_or_role"),
        _d(2, 1, "screening", 60, "tak"),
        _d(3, 1, "rejected", 50, "pokrewna"),
        _d(4, 1, "rejected", 40, "nie"),
        _d(5, 2, "screening", 99, "tak"),  # sama w grupie — pomijana
    ]
    sim = simulate(rows)
    assert sim["grup"] == 1
    assert sim["wynik"]["pasuje_proba_pct"] == 50.0  # 90 (nie) i 60 (tak)
    assert sim["z_rola"]["pasuje_proba_pct"] == 50.0  # tak i pokrewna
    assert sim["bez_nie"]["kart"] == 2
