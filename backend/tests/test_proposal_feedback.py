"""Powód „Pomiń”, raport „Propozycje AI” i poniedziałkowy skrót — części bez bazy.

Trasy z bazą: ``test_job_proposals.py`` (powód w wierszu) i
``test_insights_proposals.py`` (raport, zakres DL-a).
"""

from datetime import datetime, timezone
from typing import get_args

import pytest
from fastapi import HTTPException

from app.api.job_proposals import (
    DismissProposalBody,
    DismissReason,
    validated_dismiss_feedback,
)
from app.services import job_proposals as proposals
from app.services import proposal_outcomes as outcomes
from app.services import proposals_digest as digest
from app.services.jarvis import tools as jarvis_tools
from app.services.job_proposal_feedback_schema import DISMISS_REASONS

# ── Powód „Pomiń” ────────────────────────────────────────────────────────────


def test_dismiss_reason_literal_mirrors_the_check():
    assert tuple(get_args(DismissReason)) == DISMISS_REASONS
    assert tuple(jarvis_tools._DISMISS_REASON_PL) == DISMISS_REASONS


@pytest.mark.parametrize(
    "body",
    [None, DismissProposalBody(), DismissProposalBody(source="recommendation")],
)
def test_missing_reason_is_a_polish_422(body):
    with pytest.raises(HTTPException) as err:
        validated_dismiss_feedback(body)
    assert err.value.status_code == 422
    assert "powód" in err.value.detail


@pytest.mark.parametrize("note", [None, "", "   "])
def test_other_needs_a_note(note):
    with pytest.raises(HTTPException) as err:
        validated_dismiss_feedback(DismissProposalBody(reason="other", note=note))
    assert err.value.status_code == 422 and "Inne" in err.value.detail


def test_note_is_trimmed_and_bounded():
    assert validated_dismiss_feedback(
        DismissProposalBody(reason="other", note="  Klient nie chce B2B  ")
    ) == ("other", "Klient nie chce B2B")
    assert validated_dismiss_feedback(
        DismissProposalBody(reason="too_expensive", note=" ")
    ) == ("too_expensive", None)
    with pytest.raises(HTTPException) as err:
        validated_dismiss_feedback(DismissProposalBody(reason="other", note="x" * 501))
    assert err.value.status_code == 422


def test_unknown_reason_is_refused_by_the_model_and_the_service():
    with pytest.raises(ValueError):
        DismissProposalBody(reason="bo tak")
    with pytest.raises(ValueError):
        proposals._dismiss_reason("bo tak")
    assert proposals._dismiss_reason(None) is None
    assert proposals._dismiss_note("   ") is None


def test_jarvis_dismiss_tool_sends_the_reason():
    tool = jarvis_tools.TOOLS_BY_NAME["dismiss_job_proposal"]
    assert "reason" in tool.input_schema["required"]
    spec = tool.build(
        {"job_id": 5, "candidate_id": 7, "reason": "too_junior", "note": " "}
    )
    assert spec.json.get("reason") == "too_junior"
    preview = tool.preview({"job_id": 5, "candidate_id": 7, "reason": "too_junior"})
    assert "za mało doświadczenia" in preview


# ── Raport „Propozycje AI” ───────────────────────────────────────────────────


def _row(job, cand, source, status, reason=None, title=None):
    return outcomes.ProposalRow(job, title or f"R{job}", cand, source, status, reason)


def test_summary_counts_people_in_totals_and_rows_per_source():
    report = outcomes.summarize(
        [
            # Osoba z dwóch źródeł = jedna decyzja w sumach.
            _row(1, 10, "full_base", "added"),
            _row(1, 10, "new_cv", "added"),
            _row(1, 11, "full_base", "dismissed", "too_expensive"),
            _row(1, 12, "full_base", "proposed"),
            _row(2, 20, "job_board", "dismissed", None),  # sprzed 0405
            _row(2, 21, "job_board", "dismissed", "other"),
        ]
    )
    totals = report["totals"]
    assert (
        totals["proposed"],
        totals["added"],
        totals["dismissed"],
        totals["pending"],
    ) == (
        5,
        1,
        3,
        1,
    )
    assert totals["dismissed_by_reason"]["too_expensive"] == 1
    assert totals["dismissed_by_reason"]["other"] == 1
    assert totals["dismissed_by_reason"][outcomes.NO_REASON] == 1
    sources = {s["source"]: s for s in report["by_source"]}
    assert sources["full_base"]["proposed"] == 3
    assert sources["new_cv"]["added"] == 1
    assert sources["job_board"]["dismissed"] == 2
    # Najpierw rekrutacje z czekającymi.
    assert [j["job_id"] for j in report["jobs"]] == [1, 2]
    assert report["jobs"][0]["pending"] == 1 and report["jobs"][0]["title"] == "R1"


def test_empty_window_is_zeros_not_missing_keys():
    report = outcomes.summarize([])
    assert report["totals"]["proposed"] == 0
    assert set(report["totals"]["dismissed_by_reason"]) == set(outcomes.REASON_KEYS)
    assert report["jobs"] == [] and report["by_source"] == []


def test_window_starts_at_warsaw_midnight():
    # 30.09.2026 00:30 w Warszawie = 29.09 22:30 UTC; okno 1 dnia = od 30.09.
    now = datetime(2026, 9, 29, 22, 30, tzinfo=timezone.utc)
    assert outcomes.window_start(now, 1) == datetime(
        2026, 9, 29, 22, 0, tzinfo=timezone.utc
    )
    assert outcomes.window_start(now, 7) == datetime(
        2026, 9, 23, 22, 0, tzinfo=timezone.utc
    )


def test_report_route_gate_and_scope():
    from app.api import insights_proposals
    from app.models.user import User, UserRole

    def user(*roles):
        u = User(role=roles[0], roles=[r.value for r in roles])
        return u

    assert insights_proposals.sees_all_jobs(user(UserRole.admin))
    assert insights_proposals.sees_all_jobs(user(UserRole.head_of_recruitment))
    assert insights_proposals.sees_all_jobs(
        user(UserRole.delivery_lead, UserRole.head_of_recruitment)
    )
    assert not insights_proposals.sees_all_jobs(user(UserRole.delivery_lead))


# ── Poniedziałkowy skrót ─────────────────────────────────────────────────────


def test_digest_only_on_warsaw_monday():
    # Niedziela 23:30 UTC = poniedziałek 01:30 w Warszawie.
    assert digest.is_digest_day(datetime(2026, 9, 27, 23, 30, tzinfo=timezone.utc))
    assert not digest.is_digest_day(datetime(2026, 9, 27, 21, 0, tzinfo=timezone.utc))
    assert not digest.is_digest_day(datetime(2026, 9, 29, 8, 0, tzinfo=timezone.utc))


def test_week_key_is_the_iso_week_in_warsaw():
    monday = datetime(2026, 9, 27, 23, 30, tzinfo=timezone.utc)
    assert digest.week_key(monday) == 202640
    assert digest.week_key(datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)) == 202640
    assert digest.week_key(datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)) == 202641


def test_plan_groups_jobs_per_delivery_lead():
    plans = digest.plan_digests(
        [
            digest.PendingJob(1, "Java", 7, 10),
            digest.PendingJob(2, "Python", 7, 2),
            digest.PendingJob(3, "QA", 8, 1),
            digest.PendingJob(4, "Pusta", 9, 0),
        ]
    )
    assert set(plans) == {7, 8}
    assert plans[7].total == 12
    assert plans[7].title == "W Twoich rekrutacjach 12 propozycji czeka na decyzję"
    assert plans[7].link == "/jobs?mine=1"
    assert "„Java” (10)" in plans[7].message
    assert plans[8].title == "W Twoich rekrutacjach 1 propozycja czeka na decyzję"
    assert plans[8].link == "/jobs/3?tab=similar"


def test_message_caps_listed_titles():
    plan = digest.plan_digests(
        [digest.PendingJob(i, f"R{i}", 1, 10 - i) for i in range(1, 6)]
    )[1]
    assert "R1" in plan.message and "R4" not in plan.message
    assert "i 2 inne" in plan.message


@pytest.mark.parametrize(
    "count,phrase",
    [
        (1, "1 propozycja czeka"),
        (3, "3 propozycje czekają"),
        (5, "5 propozycji czeka"),
        (12, "12 propozycji czeka"),
        (22, "22 propozycje czekają"),
    ],
)
def test_pending_phrase(count, phrase):
    assert digest.pending_phrase(count) == phrase


async def test_digest_is_a_no_op_outside_monday():
    class _NoDb:
        async def execute(self, *_a, **_k):  # pragma: no cover — nie może paść
            raise AssertionError("poza poniedziałkiem nie pytamy bazy")

    sent = await digest.send_pending_proposals_digest(
        _NoDb(), datetime(2026, 9, 29, 8, 0, tzinfo=timezone.utc)
    )
    assert sent == 0


# ── Telemetria `reject` ──────────────────────────────────────────────────────


async def test_reject_telemetry_carries_the_reason_and_never_raises(monkeypatch):
    from app.api import job_proposals as api_module
    from app.services import match_telemetry_service

    calls = []

    async def record(db, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(match_telemetry_service, "emit_match_outcome", record)
    await api_module._emit_reject_outcome(
        object(), job_id=3, candidate_id=9, reason="outdated_cv"
    )
    assert calls == [
        {
            "event_type": "reject",
            "candidate_id": 9,
            "job_id": 3,
            "reason_code": "outdated_cv",
        }
    ]
    assert "reject" in match_telemetry_service.OUTCOME_EVENTS

    async def broken(db, **kwargs):
        raise RuntimeError("telemetria leży")

    monkeypatch.setattr(match_telemetry_service, "emit_match_outcome", broken)
    await api_module._emit_reject_outcome(
        object(), job_id=3, candidate_id=9, reason="other"
    )
