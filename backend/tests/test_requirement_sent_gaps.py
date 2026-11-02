"""Wiersze „musi mieć”, których nie ma nikt z wysłanych (02.11.2026).

Czysta logika: który wiersz jest brakiem, kiedy ostrzeżenie w ogóle się pojawia,
jakie słowa z odczytu CV przechodzą dalej i co robi z tym propozycja porządków.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services import requirement_sent_gaps as gaps
from app.services.requirement_cleanup import build_proposal, _hidden


def _row(any_of, status="unknown", level="must", basis="no_evidence"):
    return {
        "any_of": tuple(any_of),
        "level": level,
        "status": status,
        "evidence_basis": basis,
    }


class TestRowsNobodyHas:
    def test_row_missing_at_everyone_is_a_gap(self):
        people = [
            [_row(["risk mgmt."])],
            [_row(["risk mgmt."])],
            [_row(["risk mgmt."])],
        ]
        result = gaps.rows_nobody_has(people)
        assert result.sent == 3
        assert [r.label for r in result.rows] == ["risk mgmt."]

    def test_one_person_with_the_row_means_no_gap(self):
        people = [
            [_row(["java"])],
            [_row(["java"], status="met", basis="text_mention")],
            [_row(["java"])],
        ]
        assert gaps.rows_nobody_has(people).rows == ()

    def test_stale_technology_is_not_a_gap(self):
        # Technologia sprzed 3 lat to „?” z rokiem, ale osoba ją miała.
        people = [
            [_row(["cobol"], basis="stale_profile_signal")],
            [_row(["cobol"])],
            [_row(["cobol"])],
        ]
        assert gaps.rows_nobody_has(people).rows == ()

    def test_nice_rows_never_warn(self):
        people = [[_row(["kafka"], level="nice")] for _ in range(3)]
        assert gaps.rows_nobody_has(people).rows == ()

    @pytest.mark.parametrize("sent", [0, 1, 2])
    def test_fewer_than_three_sent_says_nothing(self, sent):
        people = [[_row(["kafka"])] for _ in range(sent)]
        result = gaps.rows_nobody_has(people)
        assert result.rows == ()
        assert result.sent == sent

    def test_any_of_variants_stay_together(self):
        people = [[_row(["azure", "aws"])] for _ in range(3)]
        assert gaps.rows_nobody_has(people).rows[0].words == ("azure", "aws")


class TestParseReply:
    def test_reads_rows(self):
        raw = json.dumps({"rows": [{"i": 1, "v": "met", "words": ["risk management"]}]})
        assert gaps.parse_reply(raw, ["risk mgmt."]) == {
            "risk mgmt.": ("met", ("risk management",))
        }

    @pytest.mark.parametrize(
        "raw",
        ["", "nie umiem", "{zły json", json.dumps({"rows": "x"}), json.dumps([1])],
    )
    def test_bad_reply_is_none(self, raw):
        assert gaps.parse_reply(raw, ["a"]) is None

    def test_index_out_of_range_and_unknown_verdict_are_skipped(self):
        raw = json.dumps(
            {
                "rows": [
                    {"i": 9, "v": "met", "words": ["x"]},
                    {"i": 1, "v": "?", "words": ["y"]},
                ]
            }
        )
        assert gaps.parse_reply(raw, ["a"]) == {}

    def test_non_text_words_are_dropped(self):
        raw = json.dumps(
            {"rows": [{"i": 1, "v": "met", "words": ["ok", 5, None, " "]}]}
        )
        assert gaps.parse_reply(raw, ["a"]) == {"a": ("met", ("ok",))}


class TestPickHints:
    def _hits(self, table):
        return lambda word: table.get(word, 0)

    def test_sorted_by_people_caught_then_mentions(self):
        out = gaps.pick_hints(
            {"aa": 1, "bb": 3, "cc": 2},
            row_words=["x"],
            hits=self._hits({"aa": 5, "bb": 2, "cc": 5}),
        )
        assert [h.word for h in out] == ["cc", "aa", "bb"]

    def test_word_the_engine_does_not_find_is_dropped(self):
        # Model napisał słowo, którego silnik nie znajdzie, więc dopisanie nic nie da.
        out = gaps.pick_hints({"aa": 3}, row_words=["x"], hits=self._hits({"aa": 0}))
        assert out == ()

    def test_row_own_word_and_too_long_or_short_are_dropped(self):
        long_word = "z" * (gaps.HINT_WORD_MAX_CHARS + 1)
        out = gaps.pick_hints(
            {"Risk Mgmt.": 3, long_word: 3, "q": 3},
            row_words=["risk mgmt."],
            hits=self._hits({"Risk Mgmt.": 4, long_word: 4, "q": 4}),
        )
        assert out == ()

    def test_at_most_three(self):
        words = {f"w{i}": 1 for i in range(6)}
        out = gaps.pick_hints(words, row_words=["x"], hits=lambda _w: 2)
        assert len(out) == gaps.HINTS_MAX

    def test_word_from_a_single_cv_is_not_a_pattern(self):
        out = gaps.pick_hints({"qra": 1}, row_words=["x"], hits=self._hits({"qra": 1}))
        assert out == ()


def _job(rows, job_id=7, critical=None):
    stack = {"rows": rows}
    if critical is not None:
        stack["critical"] = critical
    return SimpleNamespace(
        id=job_id,
        champion_profile={"stack": stack},
        must_skills=[],
        nice_skills=[],
        matching_requirements=None,
        requirements_reviewed=False,
        title="Rola",
    )


def _no_counts(_words, _exclude):
    return 100


def _gap(*labels, sent=8):
    result = gaps.SentGaps(
        sent=sent,
        rows=tuple(gaps.SentGapRow(label=item, words=(item,)) for item in labels),
    )
    return lambda _job: result


class TestProposalReason:
    def test_gap_row_goes_to_talk_with_reason(self):
        job = _job(
            [
                {"words": ["java"], "level": "must"},
                {"words": ["data sourcing"], "level": "must"},
            ]
        )
        proposal = build_proposal(
            job, row_count=_no_counts, sent_gaps=_gap("data sourcing")
        )
        assert "no_sent_match" in proposal.reasons
        assert [r["words"] for r in proposal.after["rows"]] == [["java"]]
        assert proposal.after["sent_gap"] == [{"words": ["data sourcing"], "sent": 8}]
        assert any(t["name"] == "data sourcing" for t in proposal.after["talk"])
        # Wiersz schodzący przez ten powód nie udaje „zdania w wierszach”.
        assert "prose_rows" not in proposal.reasons

    def test_reason_text_says_how_many_and_of_how_many(self):
        job = _job(
            [
                {"words": ["java"], "level": "must"},
                {"words": ["data sourcing"], "level": "must"},
            ]
        )
        proposal = build_proposal(
            job, row_count=_no_counts, sent_gaps=_gap("data sourcing")
        )
        text = next(
            r["text"]
            for r in proposal.as_dict()["reasons"]
            if r["code"] == "no_sent_match"
        )
        assert "8 wysłanych" in text and text.endswith(": 1")

    def test_last_search_word_stays(self):
        job = _job([{"words": ["data sourcing"], "level": "must"}])
        proposal = build_proposal(
            job, row_count=_no_counts, sent_gaps=_gap("data sourcing")
        )
        assert proposal is None or "no_sent_match" not in proposal.reasons

    def test_critical_row_is_never_moved(self):
        job = _job(
            [
                {"words": ["java"], "level": "must"},
                {"words": ["data sourcing"], "level": "critical"},
            ],
            critical=["data sourcing"],
        )
        proposal = build_proposal(
            job, row_count=_no_counts, sent_gaps=_gap("data sourcing")
        )
        assert proposal is None or "no_sent_match" not in proposal.reasons

    def test_no_data_means_no_reason(self):
        job = _job(
            [
                {"words": ["java"], "level": "must"},
                {"words": ["data sourcing"], "level": "must"},
            ]
        )
        assert (
            build_proposal(job, row_count=_no_counts, sent_gaps=lambda _j: None) is None
        )

    def test_rare_row_stays_under_rare_reason_only(self):
        job = _job(
            [
                {"words": ["java"], "level": "must"},
                {"words": ["crisis plans"], "level": "must"},
            ]
        )
        proposal = build_proposal(
            job,
            row_count=lambda words, _e: 0 if words == ["crisis plans"] else 100,
            sent_gaps=_gap("crisis plans"),
        )
        assert "rare_word" in proposal.reasons
        assert "no_sent_match" not in proposal.reasons

    def test_applied_decision_on_same_profile_does_not_hide_new_reason(self):
        job = _job(
            [
                {"words": ["java"], "level": "must"},
                {"words": ["data sourcing"], "level": "must"},
            ]
        )
        proposal = build_proposal(
            job, row_count=_no_counts, sent_gaps=_gap("data sourcing")
        )
        assert not _hidden((proposal.profile_hash, "applied"), proposal)
        assert _hidden((proposal.profile_hash, "dismissed"), proposal)


class TestCache:
    def setup_method(self):
        gaps.clear()

    def test_profile_change_is_a_miss(self):
        job = _job([{"words": ["java"], "level": "must"}])
        gaps.store(job, gaps.SentGaps(sent=3, rows=()))
        assert gaps.cached(job) == gaps.SentGaps(sent=3, rows=())
        job.champion_profile = {
            "stack": {"rows": [{"words": ["kotlin"], "level": "must"}]}
        }
        assert gaps.cached(job) is None
