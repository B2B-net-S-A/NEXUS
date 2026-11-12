"""Reguła rekrutacji z powtarzanych braków (R1, decyzja Artura 12.11.2026).

Kontrakty: 3 odrzucenia z tą samą pozycją w jednej rekrutacji tworzą regułę;
same „brak” = wymagany ślad, choć jedna „tylko wzmianka” = wymagane
doświadczenie; „za mało lat” reguły nie tworzy; najwyżej 3 reguły.
"""

from __future__ import annotations

import uuid

from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.models.autofill_feedback import AutofillFeedback
from app.models.candidate import Candidate
from app.models.candidate_skill_usage import CandidateSkillUsage
from app.services import job_learned_rules as rules
from app.services import new_column_autofill as autofill


def _gap(label, kind="missing"):
    return [{"label": label, "kind": kind}]


def test_three_rejections_make_a_rule_and_mention_raises_the_bar():
    out = rules.rules_from_gaps(
        [
            _gap("Angular"),
            _gap("angular"),
            _gap("Angular", "mention"),
            _gap("Kafka"),
            _gap("Kafka"),
        ]
    )
    assert out == [rules.LearnedRule(label="Angular", level="experience", count=3)]
    only_missing = rules.rules_from_gaps([_gap("KYC"), _gap("KYC"), _gap("kyc")])
    assert only_missing == [rules.LearnedRule(label="KYC", level="trace", count=3)]


def test_too_few_years_and_duplicates_in_one_rejection_do_not_count():
    assert rules.rules_from_gaps([_gap("Java", "too_few_years")] * 5) == []
    doubled = [
        [{"label": "SQL", "kind": "missing"}, {"label": "sql", "kind": "mention"}]
    ] * 2
    assert rules.rules_from_gaps(doubled) == []


def test_at_most_three_rules_strongest_first():
    rows = [_gap(label) for label in ("A", "B", "C", "D") for _ in range(3)] + [
        _gap("D")
    ]
    assert [r.label for r in rules.rules_from_gaps(rows)] == ["D", "A", "B"]


def test_rule_levels():
    trace = rules.LearnedRule("KYC", "trace", 3)
    experience = rules.LearnedRule("Angular", "experience", 3)
    assert (
        trace.passes("mention")
        and trace.passes("experience")
        and not trace.passes("none")
    )
    assert experience.passes("experience") and not experience.passes("mention")


async def test_engine_follows_the_rule_from_three_rejections(monkeypatch):
    from tests.test_autofill_feedback import _client_with_jobs, _fill, _people, _pool

    monkeypatch.setattr(autofill, "TARGET", 5)
    _client, (job_id,) = await _client_with_jobs(1)
    rejected = await _people(3)
    experienced, mention_only, nothing = await _people(3)
    tag = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        for i, cid in enumerate(rejected):
            db.add(
                AutofillFeedback(
                    job_id=job_id,
                    candidate_id=cid,
                    reason="missing_skill",
                    learned_from="profile",
                    bucket="search",
                    gaps=_gap(f"Angular{tag}", "mention" if i == 0 else "missing"),
                )
            )
        await db.execute(
            update(Candidate)
            .where(Candidate.id == mention_only)
            .values(raw_cv_text=f"Projekt: Java, Angular{tag}")
        )
        db.add(
            CandidateSkillUsage(
                candidate_id=experienced,
                skill_canonical=f"angular{tag}",
                skill_raw=f"Angular{tag}",
                months=30,
            )
        )
        await db.commit()
    await _pool(job_id, {nothing: 95, mention_only: 90, experienced: 80})

    assert await _fill(job_id) == [experienced]
