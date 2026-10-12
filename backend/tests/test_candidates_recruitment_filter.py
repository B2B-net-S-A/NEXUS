"""Tests for `GET /api/candidates?recruitment_id=...&recruitment_match=...`.

Filters candidates by assignment (or lack of it) to specific recruitments
(jobs). "Assigned" mirrors talent-pool membership: a candidate counts when they
have ANY `candidate_stages` row for the job — any stage, including terminal
(`rejected`/`withdrawn`) — distinct from the `employment` filter which only
counts a LATEST `hired` stage.

* `recruitment_match=assigned` (default) — in the pipeline of ANY selected job.
* `recruitment_match=not_assigned`        — in NONE of the selected jobs.

Blok „Rekrutacje” (12.10.2026) dokłada do tego samego pytania:

* `recruitment_client_id` — zakres „wszystkie rekrutacje klienta”, łączony LUB
  z `recruitment_id`, kierunek z `recruitment_match`;
* `recruitment_presence` — `never` / `ever` (był w jakiejkolwiek rekrutacji)
  i `not_in_process` (reguła kolumny „W procesie”);
* listę rekrutacji do wyboru: `GET /api/jobs-lookup/search`
  (`app/api/phase5.py`, `app/services/job_lookup.py`).

Predykaty żyją w `app/services/candidate_recruitment_filter.py`; ich kształt
SQL sprawdzają testy bez bazy na końcu pliku.

Uses the in-process `app_client` / `app_auth_headers` fixtures from conftest.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pytest
from httpx import AsyncClient


async def _seed_candidate(*, name_suffix: str = "", cohort: str = "Recr") -> int:
    """`cohort` (imię) pozwala zawęzić listę do osób testu przez `q=`."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name=cohort,
            lastname=f"Test-{uuid.uuid4().hex[:6]}{name_suffix}",
            email=f"recr-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_job(
    *,
    client_id: Optional[int] = None,
    closed: bool = False,
    title: Optional[str] = None,
    working_title: Optional[str] = None,
    client_name: Optional[str] = None,
    client_hidden: bool = False,
) -> tuple[int, int]:
    """Create a Job (and its Client unless `client_id` is given).

    Returns (job_id, client_id).
    """
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        if client_id is None:
            cli = Client(
                name=client_name or f"RecrClient-{uuid.uuid4().hex[:6]}",
                hidden=client_hidden,
            )
            db.add(cli)
            await db.commit()
            await db.refresh(cli)
            client_id = cli.id
        j = Job(
            title=title or f"Recr-Job-{uuid.uuid4().hex[:6]}",
            working_title=working_title,
            status=JobStatus.closed if closed else JobStatus.published,
            client_id=client_id,
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id, client_id


async def _seed_stage(
    candidate_id: int,
    job_id: int,
    stage_value: str,
    *,
    moved_at: Optional[datetime] = None,
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        row = CandidateStage(
            candidate_id=candidate_id,
            job_id=job_id,
            stage=PipelineStage(stage_value),
        )
        if moved_at is not None:
            row.moved_at = moved_at
        db.add(row)
        await db.commit()


async def _cleanup(
    *, candidate_ids: list[int], job_ids: list[int], client_ids: list[int]
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage
    from sqlalchemy import delete

    async with AsyncSessionLocal() as db:
        for cid in candidate_ids:
            await db.execute(
                delete(CandidateStage).where(CandidateStage.candidate_id == cid)
            )
            await db.execute(delete(Candidate).where(Candidate.id == cid))
        for jid in job_ids:
            await db.execute(delete(CandidateStage).where(CandidateStage.job_id == jid))
            await db.execute(delete(Job).where(Job.id == jid))
        for cli in client_ids:
            await db.execute(delete(Client).where(Client.id == cli))
        await db.commit()


def _ids(payload: dict) -> list[int]:
    return [it["id"] for it in payload["items"]]


async def _cohort_ids(
    app_client: AsyncClient,
    headers: dict,
    cohort: str,
    params: Optional[list[tuple[str, str]]] = None,
) -> set[int]:
    """Lista zawężona do osób testu — pozwala porównywać CAŁE zbiory."""
    r = await app_client.get(
        "/api/candidates",
        params=[("q", cohort), ("page_size", "100"), *(params or [])],
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return set(_ids(r.json()))


@pytest.mark.asyncio
async def test_assigned_includes_only_pipeline_members(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`recruitment_id={job}` (assigned default) returns the candidate in that
    job's pipeline and excludes one who is not."""
    job_id, client_id = await _seed_job()
    member = await _seed_candidate(name_suffix="-M")
    outsider = await _seed_candidate(name_suffix="-O")
    await _seed_stage(member, job_id, "screening")
    try:
        r = await app_client.get(
            f"/api/candidates?recruitment_id={job_id}&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = _ids(r.json())
        assert member in ids, "candidate in the pipeline must match"
        assert outsider not in ids, "candidate not in the pipeline must not match"
    finally:
        await _cleanup(
            candidate_ids=[member, outsider],
            job_ids=[job_id],
            client_ids=[client_id],
        )


@pytest.mark.asyncio
async def test_not_assigned_is_complement(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`recruitment_match=not_assigned` is the exact complement — the pipeline
    member drops out, the outsider stays in."""
    job_id, client_id = await _seed_job()
    member = await _seed_candidate(name_suffix="-M")
    outsider = await _seed_candidate(name_suffix="-O")
    await _seed_stage(member, job_id, "screening")
    try:
        r = await app_client.get(
            f"/api/candidates?recruitment_id={job_id}"
            "&recruitment_match=not_assigned&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = _ids(r.json())
        assert member not in ids, "pipeline member must NOT match not_assigned"
        assert outsider in ids, "non-member must match not_assigned"
    finally:
        await _cleanup(
            candidate_ids=[member, outsider],
            job_ids=[job_id],
            client_ids=[client_id],
        )


@pytest.mark.asyncio
async def test_assigned_or_combines_multiple_recruitments(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Multiple `recruitment_id` values are OR-combined: a candidate in EITHER
    job's pipeline matches; one in neither does not."""
    job_a, client_a = await _seed_job()
    job_b, client_b = await _seed_job()
    in_a = await _seed_candidate(name_suffix="-A")
    in_b = await _seed_candidate(name_suffix="-B")
    in_neither = await _seed_candidate(name_suffix="-N")
    await _seed_stage(in_a, job_a, "new")
    await _seed_stage(in_b, job_b, "new")
    try:
        r = await app_client.get(
            f"/api/candidates?recruitment_id={job_a}&recruitment_id={job_b}"
            "&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = _ids(r.json())
        assert in_a in ids and in_b in ids, "either-pipeline candidates match"
        assert in_neither not in ids, "candidate in neither pipeline must not match"
    finally:
        await _cleanup(
            candidate_ids=[in_a, in_b, in_neither],
            job_ids=[job_a, job_b],
            client_ids=[client_a, client_b],
        )


@pytest.mark.asyncio
async def test_assigned_counts_terminal_stage(
    app_client: AsyncClient, app_auth_headers: dict
):
    """ "Assigned" means present in the pipeline at ANY stage — a candidate whose
    only stage is terminal (`rejected`) still counts (unlike employment=at_client)."""
    job_id, client_id = await _seed_job()
    rejected = await _seed_candidate(name_suffix="-R")
    await _seed_stage(rejected, job_id, "rejected")
    try:
        r = await app_client.get(
            f"/api/candidates?recruitment_id={job_id}&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        assert rejected in _ids(r.json()), "rejected-stage candidate is still assigned"
    finally:
        await _cleanup(
            candidate_ids=[rejected], job_ids=[job_id], client_ids=[client_id]
        )


@pytest.mark.asyncio
async def test_recruitment_match_invalid_value_returns_422(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`recruitment_match` only accepts `assigned`/`not_assigned`."""
    r = await app_client.get(
        "/api/candidates?recruitment_id=1&recruitment_match=bogus",
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_stage_filter_is_matched_on_the_selected_recruitment(
    app_client: AsyncClient, app_auth_headers: dict
):
    """UAT B-B06: `recruitment_id` + `pipeline_stage` = etap W TEJ rekrutacji.

    Kandydat „Nowy” w innej rekrutacji, a w wybranej na innym etapie, nie może
    trafić do listy „Nowi” wybranej rekrutacji (inaczej lista nie zgadza się
    z kolumną kanbanu).
    """
    job_a, client_a = await _seed_job()
    job_b, client_b = await _seed_job()
    new_here = await _seed_candidate(name_suffix="-N")
    new_elsewhere = await _seed_candidate(name_suffix="-E")
    await _seed_stage(new_here, job_a, "new")
    await _seed_stage(new_elsewhere, job_a, "screening")
    await _seed_stage(new_elsewhere, job_b, "new")
    try:
        r = await app_client.get(
            f"/api/candidates?recruitment_id={job_a}&pipeline_stage=new&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = _ids(r.json())
        assert new_here in ids
        assert new_elsewhere not in ids

        # Druga rekrutacja widzi „Nowego” u siebie.
        r = await app_client.get(
            f"/api/candidates?recruitment_id={job_b}&pipeline_stage=new&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        assert new_elsewhere in _ids(r.json())

        # `not_assigned` nie zawęża etapu do rekrutacji, z której wyklucza.
        r = await app_client.get(
            f"/api/candidates?recruitment_id={job_a}&recruitment_match=not_assigned"
            "&pipeline_stage=new&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = _ids(r.json())
        assert new_here not in ids and new_elsewhere not in ids
    finally:
        await _cleanup(
            candidate_ids=[new_here, new_elsewhere],
            job_ids=[job_a, job_b],
            client_ids=[client_a, client_b],
        )


# ── Blok „Rekrutacje”: obecność, proces w toku, zakres klienta ──────────────


@pytest.mark.asyncio
async def test_presence_never_and_ever_split_on_any_stage_row(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`never` = brak jakiegokolwiek wiersza etapu; etap końcowy też jest
    udziałem w rekrutacji (jak w „przypisany”)."""
    cohort = f"RecrPresence{uuid.uuid4().hex[:10]}"
    job_id, client_id = await _seed_job()
    fresh = await _seed_candidate(cohort=cohort, name_suffix="-F")
    rejected = await _seed_candidate(cohort=cohort, name_suffix="-R")
    await _seed_stage(rejected, job_id, "rejected")
    try:
        never = await _cohort_ids(
            app_client, app_auth_headers, cohort, [("recruitment_presence", "never")]
        )
        ever = await _cohort_ids(
            app_client, app_auth_headers, cohort, [("recruitment_presence", "ever")]
        )
        assert never == {fresh}
        assert ever == {rejected}
    finally:
        await _cleanup(
            candidate_ids=[fresh, rejected], job_ids=[job_id], client_ids=[client_id]
        )


@pytest.mark.asyncio
async def test_not_in_process_follows_the_latest_row_of_each_pair(
    app_client: AsyncClient, app_auth_headers: dict
):
    """„Bez procesu w toku” w ośmiu układach + zgodność z kolumną „W procesie”
    (te same osoby, ta sama odpowiedź listy z `include_active_recruitments`)."""
    cohort = f"RecrIdle{uuid.uuid4().hex[:10]}"
    t0 = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
    later = t0 + timedelta(days=1)
    people: dict[str, int] = {}
    job_ids: list[int] = []
    client_ids: list[int] = []
    try:
        for closed in (False, False, True):
            job_id, client_id = await _seed_job(closed=closed)
            job_ids.append(job_id)
            client_ids.append(client_id)
        open_job, other_job, closed_job = job_ids
        for key in (
            "no_rows",
            "in_progress",
            "rejected_after",
            "back_in",
            "tie_ended",
            "tie_running",
            "on_closed",
            "two_jobs",
        ):
            people[key] = await _seed_candidate(cohort=cohort, name_suffix=f"-{key}")

        await _seed_stage(people["in_progress"], open_job, "screening", moved_at=t0)
        await _seed_stage(people["rejected_after"], open_job, "screening", moved_at=t0)
        await _seed_stage(
            people["rejected_after"], open_job, "rejected", moved_at=later
        )
        await _seed_stage(people["back_in"], open_job, "rejected", moved_at=t0)
        await _seed_stage(people["back_in"], open_job, "screening", moved_at=later)
        # Remis czasu rozstrzyga `id` — wygrywa wiersz dopisany później.
        # („Wycofany” wymaga w bazie powodu, więc etap końcowy to „Odrzucony”.)
        await _seed_stage(people["tie_ended"], open_job, "screening", moved_at=t0)
        await _seed_stage(people["tie_ended"], open_job, "rejected", moved_at=t0)
        await _seed_stage(people["tie_running"], open_job, "rejected", moved_at=t0)
        await _seed_stage(people["tie_running"], open_job, "screening", moved_at=t0)
        await _seed_stage(people["on_closed"], closed_job, "screening", moved_at=t0)
        await _seed_stage(people["two_jobs"], open_job, "rejected", moved_at=t0)
        await _seed_stage(people["two_jobs"], other_job, "interview", moved_at=t0)

        idle = await _cohort_ids(
            app_client,
            app_auth_headers,
            cohort,
            [("recruitment_presence", "not_in_process")],
        )
        assert idle == {
            people["no_rows"],
            people["rejected_after"],
            people["tie_ended"],
            people["on_closed"],
        }

        r = await app_client.get(
            "/api/candidates",
            params=[
                ("q", cohort),
                ("page_size", "100"),
                ("include_active_recruitments", "true"),
            ],
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert {it["id"] for it in items} == set(people.values())
        terminal = {"rejected", "withdrawn", "hired"}
        column_says_idle = {
            it["id"]
            for it in items
            if not any(
                rec["stage"] not in terminal
                for rec in (it.get("active_recruitments") or [])
            )
        }
        assert column_says_idle == idle
    finally:
        await _cleanup(
            candidate_ids=list(people.values()),
            job_ids=job_ids,
            client_ids=client_ids,
        )


@pytest.mark.asyncio
async def test_client_scope_covers_every_recruitment_of_the_client(
    app_client: AsyncClient, app_auth_headers: dict
):
    cohort = f"RecrClientScope{uuid.uuid4().hex[:10]}"
    job_x1, client_x = await _seed_job()
    job_x2, _ = await _seed_job(client_id=client_x, closed=True)
    job_y, client_y = await _seed_job()
    in_x1 = await _seed_candidate(cohort=cohort, name_suffix="-x1")
    in_x2 = await _seed_candidate(cohort=cohort, name_suffix="-x2")
    in_y = await _seed_candidate(cohort=cohort, name_suffix="-y")
    nowhere = await _seed_candidate(cohort=cohort, name_suffix="-none")
    await _seed_stage(in_x1, job_x1, "new")
    await _seed_stage(in_x2, job_x2, "screening")
    await _seed_stage(in_x2, job_y, "new")
    await _seed_stage(in_y, job_y, "new")
    scope = ("recruitment_client_id", str(client_x))
    try:
        ids = await _cohort_ids(app_client, app_auth_headers, cohort, [scope])
        assert ids == {in_x1, in_x2}, "zamknięta rekrutacja klienta też się liczy"

        ids = await _cohort_ids(
            app_client,
            app_auth_headers,
            cohort,
            [scope, ("recruitment_match", "not_assigned")],
        )
        assert ids == {in_y, nowhere}

        # Rekrutacje z listy i cały klient to JEDEN zakres (LUB).
        ids = await _cohort_ids(
            app_client,
            app_auth_headers,
            cohort,
            [scope, ("recruitment_id", str(job_y))],
        )
        assert ids == {in_x1, in_x2, in_y}

        # Etap razem z zakresem „przypisany” = etap w rekrutacji z zakresu:
        # `in_x2` jest „Nowy” tylko u innego klienta.
        ids = await _cohort_ids(
            app_client, app_auth_headers, cohort, [scope, ("pipeline_stage", "new")]
        )
        assert ids == {in_x1}
    finally:
        await _cleanup(
            candidate_ids=[in_x1, in_x2, in_y, nowhere],
            job_ids=[job_x1, job_x2, job_y],
            client_ids=[client_x, client_y],
        )


@pytest.mark.asyncio
async def test_presence_combines_with_scope_like_the_job_window(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Okno „Szukaj ręcznie” wymusza „nie w tej rekrutacji” i może dołożyć
    tryb — oba warunki łączy I."""
    cohort = f"RecrWindow{uuid.uuid4().hex[:10]}"
    this_job, client_a = await _seed_job()
    other_job, client_b = await _seed_job()
    in_this = await _seed_candidate(cohort=cohort, name_suffix="-this")
    busy_elsewhere = await _seed_candidate(cohort=cohort, name_suffix="-busy")
    free = await _seed_candidate(cohort=cohort, name_suffix="-free")
    await _seed_stage(in_this, this_job, "new")
    await _seed_stage(busy_elsewhere, other_job, "interview")
    window = [
        ("recruitment_id", str(this_job)),
        ("recruitment_match", "not_assigned"),
    ]
    try:
        ids = await _cohort_ids(
            app_client,
            app_auth_headers,
            cohort,
            [*window, ("recruitment_presence", "not_in_process")],
        )
        assert ids == {free}
        ids = await _cohort_ids(
            app_client,
            app_auth_headers,
            cohort,
            [*window, ("recruitment_presence", "ever")],
        )
        assert ids == {busy_elsewhere}
    finally:
        await _cleanup(
            candidate_ids=[in_this, busy_elsewhere, free],
            job_ids=[this_job, other_job],
            client_ids=[client_a, client_b],
        )


@pytest.mark.asyncio
async def test_recruitment_presence_invalid_value_returns_422(
    app_client: AsyncClient, app_auth_headers: dict
):
    r = await app_client.get(
        "/api/candidates?recruitment_presence=sometimes", headers=app_auth_headers
    )
    assert r.status_code == 422, r.text


# ── Lista rekrutacji do wyboru: `GET /api/jobs-lookup/search` ───────────────


async def _lookup(
    app_client: AsyncClient, headers: dict, params: list[tuple[str, str]]
) -> dict:
    r = await app_client.get("/api/jobs-lookup/search", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_lookup_finds_by_name_client_and_number(
    app_client: AsyncClient, app_auth_headers: dict
):
    token = f"Lkp{uuid.uuid4().hex[:10]}"
    client_name = f"LookupKlient {token}"
    open_job, client_id = await _seed_job(
        title=f"Od klienta {token}",
        working_title=f"Robocza {token}",
        client_name=client_name,
    )
    closed_job, _ = await _seed_job(
        client_id=client_id, closed=True, title=f"Druga {token}"
    )
    try:
        found = await _lookup(
            app_client, app_auth_headers, [("q", token), ("status", "all")]
        )
        by_id = {item["id"]: item for item in found["items"]}
        assert set(by_id) == {open_job, closed_job}
        assert found["total"] == 2
        # Ekrany wewnętrzne pokazują nazwę roboczą, a bez niej nazwę od klienta.
        assert by_id[open_job]["title"] == f"Robocza {token}"
        assert by_id[closed_job]["title"] == f"Druga {token}"
        assert by_id[open_job]["client_name"] == client_name
        assert by_id[open_job]["status"] == "open"
        assert by_id[closed_job]["status"] == "closed"
        # Nazwa klienta pasuje do tekstu → pozycja „cały klient” z liczbą
        # wszystkich jego rekrutacji.
        assert found["clients"] == [
            {"id": client_id, "name": client_name, "jobs_count": 2}
        ]

        only_open = await _lookup(app_client, app_auth_headers, [("q", token)])
        assert [item["id"] for item in only_open["items"]] == [open_job]
        only_closed = await _lookup(
            app_client, app_auth_headers, [("q", token), ("status", "closed")]
        )
        assert [item["id"] for item in only_closed["items"]] == [closed_job]

        # Numer rekrutacji (także z „#”) stawia ją na początku listy.
        for text in (str(closed_job), f"#{closed_job}"):
            numbered = await _lookup(
                app_client, app_auth_headers, [("q", text), ("status", "all")]
            )
            assert numbered["items"][0]["id"] == closed_job, text

        first_page = await _lookup(
            app_client,
            app_auth_headers,
            [("q", token), ("status", "all"), ("limit", "1")],
        )
        assert len(first_page["items"]) == 1
        assert first_page["total"] == 2
    finally:
        await _cleanup(
            candidate_ids=[], job_ids=[open_job, closed_job], client_ids=[client_id]
        )


@pytest.mark.asyncio
async def test_lookup_skips_hidden_clients_in_search_but_still_labels_them(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Rekrutacja ukrytego klienta nie jest do wyboru (jak w rejestrze `/jobs`),
    ale wybrana wcześniej dalej filtruje listę — jej etykieta musi wracać."""
    token = f"LkpHidden{uuid.uuid4().hex[:10]}"
    job_id, client_id = await _seed_job(
        title=f"Ukryta {token}", client_name=f"Schowany {token}", client_hidden=True
    )
    try:
        found = await _lookup(
            app_client, app_auth_headers, [("q", token), ("status", "all")]
        )
        assert found == {"items": [], "clients": [], "total": 0}

        labels = await _lookup(
            app_client,
            app_auth_headers,
            [("ids", str(job_id)), ("client_ids", str(client_id))],
        )
        assert [item["id"] for item in labels["items"]] == [job_id]
        assert labels["items"][0]["title"] == f"Ukryta {token}"
        assert labels["clients"] == [
            {"id": client_id, "name": f"Schowany {token}", "jobs_count": 1}
        ]
    finally:
        await _cleanup(candidate_ids=[], job_ids=[job_id], client_ids=[client_id])


@pytest.mark.asyncio
async def test_lookup_rejects_an_unknown_status(
    app_client: AsyncClient, app_auth_headers: dict
):
    r = await app_client.get(
        "/api/jobs-lookup/search?status=draft", headers=app_auth_headers
    )
    assert r.status_code == 422, r.text


# ── Bez bazy: kształt SQL predykatów bloku „Rekrutacje” ─────────────────────


def _sql(clause) -> str:
    from sqlalchemy.dialects import postgresql

    return str(
        clause.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def test_scope_by_ids_is_the_same_exists_as_before() -> None:
    from app.services import candidate_recruitment_filter as recruitment_filter

    assigned = _sql(recruitment_filter.scope_clause([3, 7], None, "assigned"))
    assert assigned.startswith("EXISTS (SELECT 1")
    assert "candidate_stages.candidate_id = candidates.id" in assigned
    assert "candidate_stages.job_id IN (3, 7)" in assigned
    assert "jobs" not in assigned, "sam wybór rekrutacji nie sięga do tabeli jobs"

    excluded = _sql(recruitment_filter.scope_clause([3, 7], [], "not_assigned"))
    assert excluded == f"NOT ({assigned})"


def test_client_scope_joins_ids_inside_one_exists() -> None:
    from app.services import candidate_recruitment_filter as recruitment_filter

    sql = _sql(recruitment_filter.scope_clause([3], [9, 11], "not_assigned"))
    assert sql.count("EXISTS") == 1, sql
    assert "candidate_stages.job_id IN (3)" in sql
    assert "jobs.client_id IN (9, 11)" in sql
    assert " OR " in sql

    only_client = _sql(recruitment_filter.scope_clause(None, [9], "assigned"))
    assert "jobs.client_id IN (9)" in only_client
    assert " OR " not in only_client


def test_empty_scope_gives_no_clause() -> None:
    from app.services import candidate_recruitment_filter as recruitment_filter

    assert recruitment_filter.scope_clause(None, None, "not_assigned") is None
    assert recruitment_filter.scope_clause([], [], "assigned") is None
    assert recruitment_filter.presence_clause(None) is None


def test_never_is_the_negation_of_ever() -> None:
    from app.services import candidate_recruitment_filter as recruitment_filter

    ever = _sql(recruitment_filter.presence_clause("ever"))
    assert ever.startswith("EXISTS (SELECT 1")
    assert "candidate_stages.candidate_id = candidates.id" in ever
    assert "job_id" not in ever, "„był w jakiejkolwiek” nie pyta o rekrutację"
    assert _sql(recruitment_filter.presence_clause("never")) == f"NOT ({ever})"


def test_not_in_process_reads_the_latest_row_of_each_pair_on_open_jobs() -> None:
    from app.services import candidate_recruitment_filter as recruitment_filter

    sql = _sql(recruitment_filter.presence_clause("not_in_process"))
    assert sql.startswith("NOT (EXISTS")
    assert "DISTINCT ON (candidate_stages.candidate_id, candidate_stages.job_id)" in sql
    assert "candidate_stages.moved_at DESC, candidate_stages.id DESC" in sql
    assert "jobs.status != 'closed'" in sql
    # Etap końcowy odsiewa się PO wyborze najnowszego wiersza pary: osoba
    # odrzucona po screeningu nie ma procesu w toku, choć była na screeningu.
    terminal = sql.index("NOT IN ('hired', 'rejected', 'withdrawn')")
    assert terminal > sql.index("ORDER BY"), sql


def test_terminal_stages_match_the_process_column_on_the_list() -> None:
    """Kolumna „W procesie” odsiewa etapy końcowe we froncie
    (`candidate-row-format.ts`); filtr „Bez procesu w toku” musi czytać ten sam
    zbiór, inaczej lista pokaże proces u osoby z filtra „bez procesu”."""
    from app.services import candidate_recruitment_filter as recruitment_filter

    source = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "components"
        / "v2"
        / "candidates"
        / "candidate-row-format.ts"
    ).read_text(encoding="utf-8")
    block = re.search(r"const TERMINAL_STAGES = new Set\(\[(.*?)\]\)", source, re.S)
    assert block is not None, "nie znaleziono TERMINAL_STAGES w candidate-row-format.ts"
    frontend = set(re.findall(r'"([a-z_]+)"', block.group(1)))
    backend = {stage.value for stage in recruitment_filter.TERMINAL_STAGES}
    assert backend == frontend


def test_stage_filter_narrows_to_the_whole_scope() -> None:
    """Etap razem z zakresem „przypisany” dotyczy rekrutacji z zakresu — także
    tych wskazanych klientem, nie tylko wybranych z listy."""
    from app.models.recruitment_pipeline import CandidateStage
    from app.services import candidate_recruitment_filter as recruitment_filter

    assert recruitment_filter.job_in_scope(CandidateStage.job_id, None, []) is None
    sql = _sql(recruitment_filter.job_in_scope(CandidateStage.job_id, [], [5]))
    assert sql.startswith("candidate_stages.job_id IN (SELECT jobs.id")
    assert "jobs.client_id IN (5)" in sql


# ── Bez bazy: lista rekrutacji do wyboru (`job_lookup`) ─────────────────────


def test_lookup_reads_a_number_only_from_short_plain_digits() -> None:
    from app.services import job_lookup

    assert job_lookup.job_id_from_text("12") == 12
    assert job_lookup.job_id_from_text(" #12 ") == 12
    # `"²".isdigit()` jest prawdą, a `int("²")` rzuca — to byłoby 500.
    assert job_lookup.job_id_from_text("²") is None
    # Ponad zakres identyfikatora: to tekst do szukania, nie numer rekrutacji.
    assert job_lookup.job_id_from_text("99999999999") is None
    assert job_lookup.job_id_from_text("java 12") is None
    assert job_lookup.job_id_from_text("#") is None


def test_lookup_search_escapes_wildcards_and_does_not_read_skills() -> None:
    from app.services import job_lookup

    sql = _sql(job_lookup.search_clause("50%_x"))
    # `%` i `_` z pola szukania są dosłowne (podgląd SQL podwaja `%`).
    assert re.search(r"50\\+%+\\+_x", sql), sql
    assert "must_skills" not in sql
    assert "jobs.id =" not in sql
    for column in ("jobs.title", "jobs.working_title", "jobs.reference_number"):
        assert column in sql
    assert "clients.display_name" in sql and "clients.name" in sql

    by_number = _sql(job_lookup.search_clause("#2143"))
    assert "jobs.id = 2143" in by_number

    assert _sql(job_lookup.search_clause("   ")) == "true"


def test_lookup_search_lists_what_the_jobs_register_lists() -> None:
    from app.services import job_lookup

    sql = _sql(job_lookup.search_statement("bank", "open", 50))
    assert "jobs.status != 'closed'" in sql
    assert "clients.hidden IS false" in sql and "clients.deleted_at IS NULL" in sql
    assert sql.rstrip().endswith("LIMIT 50")
    assert "coalesce(jobs.working_title, jobs.title)" in sql

    closed = _sql(job_lookup.search_statement("", "closed", 20))
    assert "jobs.status = 'closed'" in closed
    everything = _sql(job_lookup.search_statement("", "all", 20))
    assert "jobs.status" not in everything.split("WHERE", 1)[1]

    # Dokładny numer idzie na górę listy.
    numbered = _sql(job_lookup.search_statement("2143", "all", 20))
    assert "ORDER BY jobs.id = 2143 DESC, jobs.id DESC" in numbered


def test_lookup_labels_ignore_visibility_and_status() -> None:
    """Zapisany wcześniej identyfikator dalej filtruje listę kandydatów, więc
    jego etykieta nie może zniknąć, gdy klient został ukryty."""
    from app.services import job_lookup

    sql = _sql(job_lookup.jobs_by_id_statement([5, 9]))
    assert "jobs.id IN (5, 9)" in sql
    assert "hidden" not in sql and "jobs.status !=" not in sql
