"""Ruch etapu idzie do rekrutera kandydata, nie do każdego prowadzącego (10.11.2026).

Zgłoszenie: prowadzący rekrutację dostawał „Kandydat X → Odrzucony” o kandydacie
innego rekrutera. Na kopii produkcji z 14 dni to 1 751 z 3 579 dzwonków ruchu.
Reguła w ``docs/claude/powiadomienia/ruch-etapu-do-rekrutera-kandydata.md``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.stage_notification import RecipientType
from app.services import stage_notification_emitter as emitter
from app.services import stage_notification_resolver as resolver

OWNER, JULIA = 91, 184


@pytest.mark.parametrize(
    ("owner", "pair", "stage", "wants_all", "expected"),
    [
        # Cudzy kandydat na codziennym etapie: tylko jego rekruter.
        (OWNER, JULIA, "rejected", False, [JULIA]),
        (OWNER, JULIA, "screening", False, [JULIA]),
        (OWNER, JULIA, "cv_sent", False, [JULIA]),
        # Etapy ważne dla całej rekrutacji: prowadzący też.
        (OWNER, JULIA, "client_interview", False, [OWNER, JULIA]),
        (OWNER, JULIA, "acceptance", False, [OWNER, JULIA]),
        (OWNER, JULIA, "hired", False, [OWNER, JULIA]),
        # Prowadzący wybrał „wszyscy kandydaci w rekrutacjach, które prowadzę”.
        (OWNER, JULIA, "rejected", True, [OWNER, JULIA]),
        # Własny kandydat albo kandydat bez rekrutera: prowadzący, jak dotąd.
        (OWNER, OWNER, "rejected", False, [OWNER]),
        (OWNER, None, "rejected", False, [OWNER]),
        # Rekrutacja bez prowadzącego.
        (None, JULIA, "rejected", False, [JULIA]),
        (None, None, "rejected", False, []),
    ],
)
def test_job_recruiter_rule_targets_the_candidate_recruiter(
    owner, pair, stage, wants_all, expected
) -> None:
    assert (
        resolver.job_recruiter_ids(
            owner_id=owner, pair_id=pair, stage_code=stage, owner_wants_all=wants_all
        )
        == expected
    )


def _rule() -> resolver._RuleSnapshot:
    return resolver._RuleSnapshot(
        recipient_type=RecipientType.job_recruiter,
        specific_user_id=None,
        role=None,
        notify_inapp=True,
        notify_email=False,
    )


@pytest.mark.asyncio
async def test_rule_resolution_skips_the_owner_for_someone_elses_rejection(
    monkeypatch,
) -> None:
    async def owner(_db, _job):
        return OWNER

    async def pair(_db, *, candidate_id, job_id):
        return JULIA

    wants: list[int] = []

    async def wants_all(_db, user_id):
        wants.append(user_id)
        return False

    import app.services.job_previous_recruiters as previous

    monkeypatch.setattr(previous, "working_owner_id", owner)
    monkeypatch.setattr(resolver, "pair_recruiter_id", pair)
    monkeypatch.setattr(resolver, "_owner_wants_all_moves", wants_all)
    job = SimpleNamespace(id=789202, recruiter_id=OWNER)
    candidate = SimpleNamespace(id=7)

    rejected = await resolver._resolve_user_ids_for_rule(
        None, rule=_rule(), job=job, candidate=candidate, stage_code="rejected"
    )
    interview = await resolver._resolve_user_ids_for_rule(
        None, rule=_rule(), job=job, candidate=candidate, stage_code="client_interview"
    )

    assert rejected == [JULIA]
    assert interview == [OWNER, JULIA]
    assert wants == [OWNER, OWNER]


def _plain(**extra):
    return emitter._inapp_content(
        reason=None,
        candidate=SimpleNamespace(id=9),
        candidate_full_name="Jan Testowy",
        stage_display_name="Interview Klient",
        job=SimpleNamespace(id=3, title="ZOB-1 Java", working_title="Java · Spring"),
        mover=SimpleNamespace(name="Julia S."),
        **extra,
    )


def test_bell_about_someone_elses_candidate_names_their_recruiter() -> None:
    title, message, link = _plain(candidate_recruiter="Julia S.")
    assert title == "Kandydat Jan Testowy → Interview Klient"
    # Pierwsze słowa są widoczne w jednej linii okienka „Rekrutacje”.
    assert message == (
        "Julia S. (prowadzi kandydata) przesunął(-ęła) kartę na etap "
        "„Interview Klient” w rekrutacji „Java · Spring”."
    )
    assert "na etap „Interview Klient” w rekrutacji „Java · Spring”" in message
    assert link == "/jobs/3?candidate=9"


def test_bell_moved_by_someone_else_names_both() -> None:
    _title, message, _link = emitter._inapp_content(
        reason=None,
        candidate=SimpleNamespace(id=9),
        candidate_full_name="Jan Testowy",
        stage_display_name="Interview Klient",
        job=SimpleNamespace(id=3, title="ZOB-1 Java", working_title="Java · Spring"),
        mover=SimpleNamespace(name="Marcin K."),
        candidate_recruiter="Julia S.",
    )
    # Pierwsze słowa są widoczne w jednej linii okienka „Rekrutacje”.
    assert message.startswith("Kandydata prowadzi Julia S. Marcin K. przesunął")


def test_plain_bell_says_recruitment_and_hides_the_internal_id() -> None:
    _title, message, _link = _plain()
    assert message == (
        "Kandydat Jan Testowy przeszedł na etap „Interview Klient” "
        "w rekrutacji „Java · Spring” przez Julia S."
    )
    assert "ofercie" not in message
    assert "#3" not in message


def test_preference_column_has_migration_and_entrypoint_mirror() -> None:
    backend = Path(__file__).resolve().parents[1]
    statement = (
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS stage_moves_all_led_jobs "
        "BOOLEAN NOT NULL DEFAULT false"
    )
    migrations = [
        p.read_text(encoding="utf-8")
        for p in (backend / "alembic" / "versions").glob(
            "*stage_moves_all_led_jobs*.py"
        )
    ]
    assert len(migrations) == 1
    assert statement in " ".join(migrations[0].split())
    assert statement in (backend / "entrypoint.sh").read_text(encoding="utf-8")


def test_preferences_api_carries_the_choice() -> None:
    from app.api.users import UserPreferencesResponse, UserPreferencesUpdate

    assert "stage_moves_all_led_jobs" in UserPreferencesUpdate.model_fields
    assert "stage_moves_all_led_jobs" in UserPreferencesResponse.model_fields


@pytest.mark.asyncio
async def test_account_saves_and_reads_back_the_choice(app_client) -> None:
    from app.models.user import UserRole
    from tests._jarvis_helpers import make_user

    _uid, headers = await make_user(UserRole.recruiter)
    start = await app_client.get("/api/users/me/preferences", headers=headers)
    assert start.status_code == 200, start.text
    # Domyślnie tylko własni kandydaci.
    assert start.json()["stage_moves_all_led_jobs"] is False

    on = await app_client.patch(
        "/api/users/me/preferences",
        json={"stage_moves_all_led_jobs": True},
        headers=headers,
    )
    assert on.status_code == 200, on.text
    assert on.json()["stage_moves_all_led_jobs"] is True
    again = await app_client.get("/api/users/me/preferences", headers=headers)
    assert again.json()["stage_moves_all_led_jobs"] is True
