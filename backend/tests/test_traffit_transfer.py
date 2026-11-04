"""Przeniesienie rekrutacji z Traffita do NEXUSA falami (11.10.2026) — Postgres.

Próba niczego nie zmienia; wykonanie poprawia stany wg listy osób z Traffita,
zdejmuje z aktywnych kolumn osoby usunięte u źródła i otwiera rekrutację tymi
samymi funkcjami co „Otwórz ponownie”. Bieżący etap pary, ograniczenie
wycofania (0068) i blokady siedzą w bazie, więc atrapa niczego by nie dowiodła.

Baza testowa jest wspólna i nieczyszczona — każdy test ma własnego klienta,
rekrutację i numery stanów; asercje tylko na własnych wierszach.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Optional

import pytest
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
    StageCategoryEnum,
)
from app.models.recruitment_pipeline import CandidateStage, PipelineStage

# Relacja `CortexSkillFact` → `Skill` (patrz test_traffit_managed_in_nexus).
from app.models.skill import Skill  # noqa: F401
from app.services import job_lifecycle
from app.services import traffit_transfer as transfer
from tests._job_factory import new_recruiter

UTC = timezone.utc


class _Resp:
    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _FakeTraffit:
    """Lista osób per stan jednej rekrutacji, jak oddaje ją Traffit."""

    def __init__(
        self, states: dict[str, list[str]], *, total: Optional[int] = None
    ) -> None:
        self.states = states
        self.total = total

    async def _get_raw(self, path: str, page: int = 1, page_size: int = 100) -> _Resp:
        return _Resp(200, [{"id": state, "name": state} for state in self.states])

    async def get_pages(
        self, path: str, *, page_size: int = 100
    ) -> AsyncIterator[tuple[int, list[dict[str, Any]]]]:
        state = path.strip("/").split("/")[3]
        people = self.states.get(state) or []
        if people:
            yield 1, [{"id": emp} for emp in people]

    async def total_count(self, path: str) -> int:
        if self.total is not None:
            return self.total
        return sum(len(people) for people in self.states.values())


async def _admin_id() -> int:
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as db:
        user = User(
            email=f"transfer-admin-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("not-a-login"),
            name="Transfer admin",
            role=UserRole.admin,
            roles=["admin"],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id


async def _seed() -> dict[str, Any]:
    """Zarchiwizowana rekrutacja z Traffita z pięcioma osobami.

    * ``ok``      — Screening, zgodnie z Traffitem;
    * ``tie``     — „Nowy” i „Screening” z tą samą datą; nowszy wpis ma niższe id;
    * ``nocard``  — kandydat znany NEXUSOWI, bez wiersza w tej rekrutacji;
    * ``gone``    — karta w NEXUSIE, w Traffit zdjęty z rekrutacji;
    * ``nexus``   — ostatni ruch zrobiony w NEXUSIE, w Traffit już go nie ma;
    * ``hired``   — zatrudniony, potem zdjęty z rekrutacji w Traffit.
    """
    unique = uuid.uuid4().hex[:8]
    when = datetime.now(UTC) - timedelta(days=2)
    async with AsyncSessionLocal() as db:
        template = PipelineTemplate(
            name=f"Transfer tpl {unique}",
            external_source="traffit",
            external_id=f"tt-tpl-{unique}",
        )
        client = Client(name=f"Transfer client {unique}")
        db.add_all([template, client])
        await db.flush()
        defs: dict[str, PipelineStageDef] = {}
        for order, (key, legacy) in enumerate(
            (
                ("new", "new"),
                ("screening", "screening"),
                ("sent", "cv_sent"),
                ("hired", "hired"),
            )
        ):
            defs[key] = PipelineStageDef(
                template_id=template.id,
                name=f"{key} {unique}",
                order=order,
                category=(
                    StageCategoryEnum.terminal
                    if key == "hired"
                    else StageCategoryEnum.internal
                ),
                legacy_enum_value=legacy,
                external_source="traffit",
                external_id=f"tt-{key}-{unique}",
            )
        job = Job(
            title=f"Transfer job {unique}",
            status=JobStatus.closed,
            client_id=client.id,
            external_source="traffit",
            external_id=f"tt-rec-{unique}",
            managed_in_nexus=False,
            is_open=False,
            work_state="finished",
            recruiter_id=await new_recruiter(),
        )
        people = {
            key: Candidate(
                name="Transfer",
                lastname=f"{key}-{unique}",
                external_source="traffit",
                external_id=f"tt-emp-{key}-{unique}",
            )
            for key in ("ok", "tie", "nocard", "gone", "nexus", "hired")
        }
        db.add_all([*defs.values(), job, *people.values()])
        await db.flush()

        def row(
            who: str, stage: str, legacy: PipelineStage, *, at=when, source="traffit"
        ):
            return CandidateStage(
                candidate_id=people[who].id,
                job_id=job.id,
                stage=legacy,
                stage_def_id=defs[stage].id if source == "traffit" else None,
                moved_at=at,
                external_source=source,
                external_id=f"tt-h-{uuid.uuid4().hex[:10]}"
                if source == "traffit"
                else None,
            )

        # Kolejność wstawiania = kolejność id: „Screening” przed „Nowy”.
        for stage_row in (
            row("ok", "screening", PipelineStage.screening),
            row("tie", "screening", PipelineStage.screening),
            row("tie", "new", PipelineStage.new),
            row("gone", "screening", PipelineStage.screening),
            row("hired", "hired", PipelineStage.hired),
            row("nexus", "new", PipelineStage.new),
            row(
                "nexus",
                "screening",
                PipelineStage.screening,
                at=when + timedelta(hours=1),
                source="manual",
            ),
        ):
            db.add(stage_row)
            await db.flush()
        await db.commit()
        return {
            "job_id": job.id,
            "client_id": client.id,
            "title": job.title,
            "rid": job.external_id,
            "people": {key: person.id for key, person in people.items()},
            "emp": {key: person.external_id for key, person in people.items()},
            "state": {key: stage_def.external_id for key, stage_def in defs.items()},
        }


def _traffit_for(seed: dict[str, Any], **kwargs: Any) -> _FakeTraffit:
    emp, state = seed["emp"], seed["state"]
    return _FakeTraffit(
        {
            state["new"]: [emp["nocard"]],
            state["screening"]: [emp["ok"], emp["tie"]],
            state["sent"]: [],
        },
        **kwargs,
    )


async def _latest(job_id: int, candidate_id: int) -> tuple[str, Optional[str]]:
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    "SELECT CAST(stage AS text), rejection_note FROM candidate_stages "
                    "WHERE job_id = :j AND candidate_id = :c "
                    "ORDER BY moved_at DESC, id DESC LIMIT 1"
                ),
                {"j": job_id, "c": candidate_id},
            )
        ).first()
        return (row[0], row[1]) if row else ("", None)


async def _job_state(job_id: int) -> tuple[str, bool, bool, str]:
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    "SELECT CAST(status AS text), is_open, managed_in_nexus, work_state "
                    "FROM jobs WHERE id = :i"
                ),
                {"i": job_id},
            )
        ).one()
        return row[0], row[1], row[2], row[3]


async def _run(
    seed: dict[str, Any], traffit: _FakeTraffit, *, dry_run: bool, actor: Optional[int]
) -> dict[str, Any]:
    scope = transfer.Scope(job_ids=(seed["job_id"],))
    async with AsyncSessionLocal() as db:
        return await transfer.process(
            db, traffit, scope, dry_run=dry_run, actor_user_id=actor, actor_label="test"
        )


@pytest.fixture
def post_commit_calls(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Efekty po commicie (migawka dopasowań, Qdrant) nie należą do tego testu."""
    calls: list[Any] = []

    async def _record(effects: Any) -> Any:
        calls.append(effects)
        return effects

    monkeypatch.setattr(job_lifecycle, "run_post_commit", _record)
    return calls


@pytest.mark.asyncio
async def test_dry_run_reports_corrections_and_changes_nothing(
    post_commit_calls: list[Any],
) -> None:
    seed = await _seed()

    report = await _run(seed, _traffit_for(seed), dry_run=True, actor=None)

    (job,) = report["jobs"]
    assert job["status"] == "ready"
    assert (job["people"], job["matched"]) == (3, 1)
    assert (job["promote"], job["insert"], job["remove"]) == (1, 1, 1)
    assert job["nexus_on_top"] == 1
    assert job["already_closed"] == 1
    assert job["columns"] == {"new": 1, "screening": 2}
    assert report["totals"]["by_status"] == {"ready": 1}
    # Zero zmian: rekrutacja dalej w archiwum, karty jak były.
    assert await _job_state(seed["job_id"]) == ("closed", False, False, "finished")
    assert (await _latest(seed["job_id"], seed["people"]["tie"]))[0] == "new"
    assert (await _latest(seed["job_id"], seed["people"]["nocard"]))[0] == ""
    assert (await _latest(seed["job_id"], seed["people"]["gone"]))[0] == "screening"
    assert post_commit_calls == []


@pytest.mark.asyncio
async def test_transfer_fixes_states_and_opens_the_recruitment(
    post_commit_calls: list[Any],
) -> None:
    seed = await _seed()
    actor = await _admin_id()

    report = await _run(seed, _traffit_for(seed), dry_run=False, actor=actor)

    (job,) = report["jobs"]
    assert job["status"] == "transferred", job
    people, job_id = seed["people"], seed["job_id"]
    # Remis czasu: wygrywa wiersz stanu, na którym osoba stoi w Traffit.
    assert (await _latest(job_id, people["tie"]))[0] == "screening"
    # Brakujący wiersz dopisany.
    assert (await _latest(job_id, people["nocard"]))[0] == "new"
    # Osoba zdjęta w Traffit schodzi z aktywnych kolumn — ze śladem, bez kasowania.
    assert await _latest(job_id, people["gone"]) == ("withdrawn", transfer.REMOVED_NOTE)
    # Ruch zrobiony w NEXUSIE zostaje.
    assert (await _latest(job_id, people["nexus"]))[0] == "screening"
    # Zatrudniony zdjęty w Traffit nie staje się „Wycofanym”.
    assert (await _latest(job_id, people["hired"]))[0] == "hired"
    assert (await _latest(job_id, people["ok"]))[0] == "screening"
    assert await _job_state(job_id) == ("published", True, True, "searching")
    assert len(post_commit_calls) == 1

    async with AsyncSessionLocal() as db:
        actions = {
            row[0]
            for row in await db.execute(
                text(
                    "SELECT action FROM activities "
                    "WHERE entity_type = 'job' AND entity_id = :i"
                ),
                {"i": job_id},
            )
        }
        kept_rows = (
            await db.execute(
                text(
                    "SELECT count(*) FROM candidate_stages "
                    "WHERE job_id = :j AND candidate_id = :c"
                ),
                {"j": job_id, "c": people["gone"]},
            )
        ).scalar_one()
    assert {"traffit_transfer", "managed_in_nexus_changed", "published"} <= actions
    assert kept_rows == 2  # dawny wiersz został, doszedł wiersz wycofania

    # Przeniesiona rekrutacja nie wraca do fali — drugi bieg niczego nie dubluje.
    again = await _run(seed, _traffit_for(seed), dry_run=True, actor=None)
    assert again["jobs"] == []


@pytest.mark.asyncio
async def test_incomplete_roster_from_traffit_leaves_the_recruitment_alone(
    post_commit_calls: list[Any],
) -> None:
    seed = await _seed()
    actor = await _admin_id()

    # Skład rekrutacji mówi o 4 osobach, listy stanów oddały 3.
    report = await _run(seed, _traffit_for(seed, total=4), dry_run=False, actor=actor)

    (job,) = report["jobs"]
    assert (job["status"], job["skip_reason"]) == ("skipped", "roster_incomplete")
    assert await _job_state(seed["job_id"]) == ("closed", False, False, "finished")
    assert (await _latest(seed["job_id"], seed["people"]["gone"]))[0] == "screening"


@pytest.mark.asyncio
async def test_recruitment_with_a_twin_created_in_nexus_is_skipped(
    post_commit_calls: list[Any],
) -> None:
    seed = await _seed()
    actor = await _admin_id()
    async with AsyncSessionLocal() as db:
        twin = Job(
            title=seed["title"].upper(),
            status=JobStatus.published,
            client_id=seed["client_id"],
            external_source="manual",
        )
        db.add(twin)
        await db.commit()
        twin_id = twin.id

    report = await _run(seed, _traffit_for(seed), dry_run=False, actor=actor)

    (job,) = report["jobs"]
    assert (job["status"], job["skip_reason"]) == ("skipped", "twin_in_nexus")
    assert job["twin_job_id"] == twin_id
    assert await _job_state(seed["job_id"]) == ("closed", False, False, "finished")


@pytest.mark.asyncio
async def test_transfer_without_an_actor_fails_before_any_write(
    post_commit_calls: list[Any],
) -> None:
    seed = await _seed()

    report = await _run(seed, _traffit_for(seed), dry_run=False, actor=None)

    (job,) = report["jobs"]
    assert job["status"] == "failed"
    assert await _job_state(seed["job_id"]) == ("closed", False, False, "finished")
    assert (await _latest(seed["job_id"], seed["people"]["tie"]))[0] == "new"


@pytest.mark.asyncio
async def test_execution_needs_a_fresh_dry_run_of_the_same_wave() -> None:
    wave = transfer.Scope(job_ids=(987_654_321,))
    other = transfer.Scope(job_ids=(987_654_322,))
    started = datetime.now(UTC)
    report = {
        "dry_run": True,
        "scope": wave.as_dict(),
        "scope_key": wave.key(),
        "actor": "test",
        "totals": {},
        "jobs": [],
    }
    async with AsyncSessionLocal() as db:
        await transfer.finish_run(db, report, started=started)
        assert await transfer.fresh_dry_run_exists(db, wave)
        assert not await transfer.fresh_dry_run_exists(db, other)
        # Stara próba nie wystarcza: stan w Traffit zmienia się z dnia na dzień.
        await transfer._write_setting(  # noqa: SLF001
            db,
            transfer.DRY_RUN_KEY,
            {
                **report,
                "finished_at": (started - timedelta(hours=25)).isoformat(),
            },
        )
        await db.commit()
        assert not await transfer.fresh_dry_run_exists(db, wave)


@pytest.mark.asyncio
async def test_twin_can_be_transferred_with_the_team_of_the_nexus_recruitment(
    post_commit_calls: list[Any],
) -> None:
    from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource

    seed = await _seed()
    actor = await _admin_id()
    owner, lead, helper = (
        await new_recruiter(),
        await new_recruiter(),
        await new_recruiter(),
    )
    async with AsyncSessionLocal() as db:
        twin = Job(
            title=seed["title"],
            status=JobStatus.published,
            client_id=seed["client_id"],
            external_source="manual",
            recruiter_id=owner,
            delivery_lead_id=lead,
        )
        db.add(twin)
        await db.flush()
        db.add(
            JobCollaborator(
                job_id=twin.id, user_id=helper, source=JobCollaboratorSource.manual
            )
        )
        await db.commit()
        twin_id = twin.id

    scope = transfer.Scope(job_ids=(seed["job_id"],), include_twins=True)
    async with AsyncSessionLocal() as db:
        report = await transfer.process(
            db,
            _traffit_for(seed),
            scope,
            dry_run=False,
            actor_user_id=actor,
            actor_label="test",
        )

    (job,) = report["jobs"]
    assert job["status"] == "transferred", job
    assert job["twin_job_id"] == twin_id and job["twin_exact"] is True
    assert job["recruiter_from_twin"] == owner
    assert await _job_state(seed["job_id"]) == ("published", True, True, "searching")
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text("SELECT recruiter_id, delivery_lead_id FROM jobs WHERE id = :i"),
                {"i": seed["job_id"]},
            )
        ).one()
        helpers = (
            await db.execute(
                text("SELECT user_id FROM job_collaborators WHERE job_id = :i"),
                {"i": seed["job_id"]},
            )
        ).scalars()
        assert (row[0], row[1]) == (owner, lead)
        assert helper in set(helpers)
        # Rekrutacja założona w NEXUSIE zostaje nietknięta.
        twin_state = (
            await db.execute(
                text(
                    "SELECT CAST(status AS text), recruiter_id FROM jobs WHERE id = :i"
                ),
                {"i": twin_id},
            )
        ).one()
        assert (twin_state[0], twin_state[1]) == ("published", owner)


@pytest.mark.asyncio
async def test_similar_title_does_not_move_the_team(
    post_commit_calls: list[Any],
) -> None:
    # Tytuł tylko PODOBNY: rekrutacja jest przenoszona, ale zostaje przy
    # swoim prowadzącym — przypisane osoby mają się nie zmieniać.
    seed = await _seed()
    actor = await _admin_id()
    other_owner = await new_recruiter()
    async with AsyncSessionLocal() as db:
        before = (
            await db.execute(
                text("SELECT recruiter_id FROM jobs WHERE id = :i"),
                {"i": seed["job_id"]},
            )
        ).scalar_one()
        twin = Job(
            title=seed["title"] + " II",
            status=JobStatus.published,
            client_id=seed["client_id"],
            external_source="manual",
            recruiter_id=other_owner,
        )
        db.add(twin)
        await db.commit()

    scope = transfer.Scope(job_ids=(seed["job_id"],), include_twins=True)
    async with AsyncSessionLocal() as db:
        report = await transfer.process(
            db,
            _traffit_for(seed),
            scope,
            dry_run=False,
            actor_user_id=actor,
            actor_label="test",
        )

    (job,) = report["jobs"]
    assert job["status"] == "transferred" and job["twin_exact"] is False, job
    assert "recruiter_from_twin" not in job
    async with AsyncSessionLocal() as db:
        after = (
            await db.execute(
                text("SELECT recruiter_id FROM jobs WHERE id = :i"),
                {"i": seed["job_id"]},
            )
        ).scalar_one()
    assert after == before


async def _delivery_lead_id() -> int:
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as db:
        user = User(
            email=f"transfer-dl-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("not-a-login"),
            name="Transfer DL",
            role=UserRole.delivery_lead,
            roles=["delivery_lead"],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id


async def _owner_and_lead(job_id: int) -> tuple[Optional[int], Optional[int]]:
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text("SELECT recruiter_id, delivery_lead_id FROM jobs WHERE id = :i"),
                {"i": job_id},
            )
        ).one()
        return row[0], row[1]


async def _active_assignments(job_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                text(
                    "SELECT count(*) FROM job_work_assignments "
                    "WHERE job_id = :i AND state = 'active'"
                ),
                {"i": job_id},
            )
        ).scalar_one()


@pytest.mark.asyncio
async def test_delivery_lead_from_traffit_does_not_become_the_recruiter(
    post_commit_calls: list[Any],
) -> None:
    # W Traffit „osobą odpowiedzialną” jest Delivery Lead; po otwarciu nie
    # może zostać policzony jako rekruter requestu (12.10.2026).
    seed = await _seed()
    actor = await _admin_id()
    lead = await _delivery_lead_id()
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE jobs SET recruiter_id = :u WHERE id = :i"),
            {"u": lead, "i": seed["job_id"]},
        )
        await db.commit()

    report = await _run(seed, _traffit_for(seed), dry_run=False, actor=actor)

    (job,) = report["jobs"]
    assert job["status"] == "transferred", job
    assert job["owner_without_recruiter_role"] == lead
    assert await _owner_and_lead(seed["job_id"]) == (None, lead)
    assert await _active_assignments(seed["job_id"]) == 0


@pytest.mark.asyncio
async def test_recruiter_from_traffit_stays_the_recruiter(
    post_commit_calls: list[Any],
) -> None:
    seed = await _seed()
    actor = await _admin_id()
    before = await _owner_and_lead(seed["job_id"])

    report = await _run(seed, _traffit_for(seed), dry_run=False, actor=actor)

    (job,) = report["jobs"]
    assert "owner_without_recruiter_role" not in job
    assert (await _owner_and_lead(seed["job_id"]))[0] == before[0]


@pytest.mark.asyncio
async def test_next_run_repairs_recruitments_opened_with_a_delivery_lead_as_owner(
    post_commit_calls: list[Any],
) -> None:
    from app.models.activity import Activity
    from app.models.job_work_assignment import JobWorkAssignment

    seed = await _seed()
    actor = await _admin_id()
    lead = await _delivery_lead_id()
    # Stan po pierwszej fali: rekrutacja otwarta, DL jako prowadzący
    # z aktywnym przypisaniem „Rekruter”.
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE jobs SET status = 'published', is_open = true, "
                "managed_in_nexus = true, work_state = 'searching', "
                "recruiter_id = :u WHERE id = :i"
            ),
            {"u": lead, "i": seed["job_id"]},
        )
        db.add(
            Activity(
                entity_type="job",
                entity_id=seed["job_id"],
                action="traffit_transfer",
                user_id=actor,
            )
        )
        db.add(
            JobWorkAssignment(
                job_id=seed["job_id"],
                user_id=lead,
                role="recruiter",
                source="owner",
                state="active",
            )
        )
        await db.commit()
    assert await _active_assignments(seed["job_id"]) == 1

    async with AsyncSessionLocal() as db:
        preview = await transfer.repair_transferred_owners(
            db, actor_user_id=None, dry_run=True
        )
    assert seed["job_id"] in preview["owners_settled_job_ids"]
    assert await _owner_and_lead(seed["job_id"]) == (lead, None)

    async with AsyncSessionLocal() as db:
        done = await transfer.repair_transferred_owners(
            db, actor_user_id=actor, dry_run=False
        )
    assert seed["job_id"] in done["owners_settled_job_ids"]
    assert await _owner_and_lead(seed["job_id"]) == (None, lead)
    assert await _active_assignments(seed["job_id"]) == 0


@pytest.mark.asyncio
async def test_recruitment_switched_by_hand_but_still_closed_is_opened_when_listed(
    post_commit_calls: list[Any],
) -> None:
    # Ktoś kliknął „Przełącz do NEXUSA” i nie otworzył rekrutacji: import jej
    # już nie rusza, a w NEXUSIE dalej jest zamknięta.
    seed = await _seed()
    actor = await _admin_id()
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE jobs SET managed_in_nexus = true WHERE id = :i"),
            {"i": seed["job_id"]},
        )
        await db.commit()

    report = await _run(seed, _traffit_for(seed), dry_run=False, actor=actor)

    (job,) = report["jobs"]
    assert job["status"] == "transferred", job
    assert await _job_state(seed["job_id"]) == ("published", True, True, "searching")


@pytest.mark.asyncio
@pytest.mark.parametrize(("auto_filled", "replaced"), [(True, True), (False, False)])
async def test_delivery_lead_from_traffit_replaces_only_an_auto_filled_lead(
    post_commit_calls: list[Any], auto_filled: bool, replaced: bool
) -> None:
    # Automat wpisuje głównego DL-a klienta; u klienta z kilkoma DL-ami
    # rekrutację prowadzi ten z Traffita. DL wpisany przez człowieka zostaje.
    seed = await _seed()
    actor = await _admin_id()
    lead, other = await _delivery_lead_id(), await _delivery_lead_id()
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE jobs SET recruiter_id = :u, delivery_lead_id = :o, "
                "delivery_lead_auto_filled = :a WHERE id = :i"
            ),
            {"u": lead, "o": other, "a": auto_filled, "i": seed["job_id"]},
        )
        await db.commit()

    report = await _run(seed, _traffit_for(seed), dry_run=False, actor=actor)

    (job,) = report["jobs"]
    assert job["status"] == "transferred", job
    assert await _owner_and_lead(seed["job_id"]) == (None, lead if replaced else other)
