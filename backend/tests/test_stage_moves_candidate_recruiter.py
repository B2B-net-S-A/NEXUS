"""Ruch etapu idzie do rekrutera kandydata, nie do każdego prowadzącego (10.11.2026).

Zgłoszenie: prowadzący rekrutację dostawał „Kandydat X → Odrzucony” o kandydacie
innego rekrutera. Na kopii produkcji z 14 dni to 1 751 z 3 579 dzwonków ruchu.
18.11.2026: dalej 808 z 1 320 (61%), bo kandydat w „Nowych” bez rekrutera był
liczony jako kandydat prowadzącego. Od tej daty prowadzący dostaje tylko swoich
kandydatów, bez wyjątku na Interview Klient, Akceptację i Zatrudnionego.
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
    ("owner", "pair", "wants_all", "expected"),
    [
        # Cudzy kandydat: tylko jego rekruter, na każdym etapie (18.11.2026).
        (OWNER, JULIA, False, [JULIA]),
        # Prowadzący wybrał „wszyscy kandydaci w rekrutacjach, które prowadzę”.
        (OWNER, JULIA, True, [OWNER, JULIA]),
        # Własny kandydat albo ruch bez rekrutera i bez osoby: prowadzący.
        (OWNER, OWNER, False, [OWNER]),
        (OWNER, None, False, [OWNER]),
        # Rekrutacja bez prowadzącego.
        (None, JULIA, False, [JULIA]),
        (None, None, False, []),
    ],
)
def test_job_recruiter_rule_targets_the_candidate_recruiter(
    owner, pair, wants_all, expected
) -> None:
    assert (
        resolver.job_recruiter_ids(
            owner_id=owner, pair_id=pair, owner_wants_all=wants_all
        )
        == expected
    )


@pytest.mark.parametrize("stage", ["client_interview", "acceptance", "hired"])
def test_important_stages_of_someone_elses_candidate_skip_the_owner(stage) -> None:
    # 10.11.2026 prowadzący dostawał te etapy cudzych kandydatów; 18.11.2026
    # decyzja Artura: „nawet jak ktoś prowadzi rekrutację, chce info tylko
    # o swoich ludziach”.
    assert not hasattr(resolver, "LEAD_STAGE_CODES")
    assert resolver.job_recruiter_ids(
        owner_id=OWNER, pair_id=JULIA, owner_wants_all=False
    ) == [JULIA]


@pytest.mark.parametrize(
    ("own", "mover", "expected"),
    [
        # Kandydat w „Nowych” bez rekrutera, odrzucony przez Julię: jej kandydat,
        # nie prowadzącego (zgłoszenie z 18.11.2026, rekrutacja 789202).
        (None, JULIA, JULIA),
        # „Prowadzi”, właściciel procesu albo weryfikator wygrywa z ruszającym.
        (OWNER, JULIA, OWNER),
        (JULIA, OWNER, JULIA),
        # Ruch bez osoby (system) i bez rekrutera: prowadzący rekrutacji.
        (None, None, OWNER),
    ],
)
@pytest.mark.asyncio
async def test_candidate_without_recruiter_belongs_to_whoever_moved_it(
    monkeypatch, own, mover, expected
) -> None:
    from app.services import interview_slots
    from app.services import stage_handoff_recipients as handoff

    calls: list[bool] = []

    async def chain(_db, pairs, *, job_fallback=True):
        calls.append(job_fallback)
        pair = list(pairs)[0]
        return {pair: own if not job_fallback else (own or OWNER)}

    monkeypatch.setattr(interview_slots, "default_recruiter_ids", chain)

    assert (
        await handoff.move_recruiter_id(
            None, candidate_id=7, job_id=789202, mover_id=mover
        )
        == expected
    )
    assert calls[0] is False


def _rule() -> resolver._RuleSnapshot:
    return resolver._RuleSnapshot(
        recipient_type=RecipientType.job_recruiter,
        specific_user_id=None,
        role=None,
        notify_inapp=True,
        notify_email=False,
    )


@pytest.mark.asyncio
async def test_rule_resolution_skips_the_owner_for_someone_elses_candidate(
    monkeypatch,
) -> None:
    async def owner(_db, _job):
        return OWNER

    movers: list[int | None] = []

    async def pair(_db, *, candidate_id, job_id, mover_id):
        movers.append(mover_id)
        return JULIA

    wants: list[int] = []

    async def wants_all(_db, user_id):
        wants.append(user_id)
        return False

    import app.services.job_previous_recruiters as previous

    monkeypatch.setattr(previous, "working_owner_id", owner)
    monkeypatch.setattr(resolver, "move_recruiter_id", pair)
    monkeypatch.setattr(resolver, "_owner_wants_all_moves", wants_all)
    job = SimpleNamespace(id=789202, recruiter_id=OWNER)
    candidate = SimpleNamespace(id=7)

    rejected = await resolver._resolve_user_ids_for_rule(
        None, rule=_rule(), job=job, candidate=candidate, mover_user_id=JULIA
    )

    assert rejected == [JULIA]
    assert movers == [JULIA]
    assert wants == [OWNER]


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
