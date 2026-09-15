"""Akceptacja szkicu Championa zasila kolumny rekrutacji (UAT B62).

Zapis z edytora (`update_champion_profile`) od dawna przepisywał stack do
`must_skills`/`nice_skills` i stawkę do `rate_budget_hourly`. Akceptacja
szkicu AI zapisywała wyłącznie JSONB profilu, więc AI Matching tej samej
rekrutacji pokazywał „Musi mieć · 0” i „budżet nieokreślony”.
"""

from types import SimpleNamespace

from app.schemas.champion import ChampionProfile
from app.services.champion_draft_service import _sync_job_columns_from_applied_sections


def _job(**overrides):
    profile = ChampionProfile.model_validate(
        {
            "basics": {"rate_value": 160, "onsite_days_per_week": 2},
            "stack": {
                "must": [{"name": "Python"}, {"name": "PostgreSQL"}, {"name": "Docker"}],
                "nice": [{"name": "Kubernetes"}],
            },
        }
    ).model_dump(mode="json")
    base = dict(
        champion_profile=profile,
        must_skills=None,
        nice_skills=None,
        matching_requirements=None,
        rate_budget_hourly=None,
        onsite_days_per_week=None,
        remote_policy=None,
        location=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_accepted_stack_and_basics_reach_job_columns() -> None:
    job = _job()

    _sync_job_columns_from_applied_sections(job, ["basics", "stack"])

    assert [s["name"] for s in job.must_skills] == ["Python", "PostgreSQL", "Docker"]
    assert [s["name"] for s in job.nice_skills] == ["Kubernetes"]
    assert job.rate_budget_hourly == 160
    assert job.onsite_days_per_week == 2


def test_sections_not_accepted_leave_columns_untouched() -> None:
    job = _job()

    _sync_job_columns_from_applied_sections(job, ["project"])

    assert job.must_skills is None
    assert job.rate_budget_hourly is None


def test_manual_budget_is_never_overwritten() -> None:
    job = _job(rate_budget_hourly=140)

    _sync_job_columns_from_applied_sections(job, ["basics"])

    assert job.rate_budget_hourly == 140
