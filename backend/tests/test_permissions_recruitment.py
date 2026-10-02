"""Uprawnienie „Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta”.

O tych operacjach decyduje to, co admin zaznaczył na ekranie Osoby i role,
a nie rola konta:

* posiadacz spoza ról domyślnych (rekruter z nadaniem) zakłada, publikuje
  i zamyka rekrutację, zmienia pola cyklu życia, wysyła CV do klienta, wpisuje
  stawkę do klienta i obchodzi QC CV;
* Delivery Lead z wyłączonym przełącznikiem redaguje już tylko treść;
* konto TAC zachowuje pełną redakcję rekrutacji (decyzja 22.09.2026), ale
  cyklu życia tras nie dostaje;
* Champion (weryfikacja, briefing, generowanie) zostaje przy roli;
* odmowa nazywa brakujące uprawnienie.

Pierwsza część pliku sprawdza reguły na kontach z dołączoną polityką (bez
bazy), druga — te same reguły przez trasy (`app_client`; baza testowa jest
wspólna i nieczyszczona, więc każdy test pracuje na własnych wierszach).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import get_args, get_type_hints

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.api import job_request_intake, jobs
from app.api.candidate_access import (
    client_rate_write_allowed,
    client_rate_write_denied,
    user_can_write_client_rate,
)
from app.api.recruitment_access import (
    JOB_FULL_EDIT_LEGACY_ROLES,
    JobEditLevel,
    ensure_job_editor,
    job_edit_level,
)
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User, UserRole
from app.services import permission_catalog as catalog
from app.services import pipeline_move_rules as rules
from tests._permission_grants import grant_permissions, role_permission

RM = "recruitment_manage"
RM_LABEL = "Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta"


def _assert_names_the_permission(detail: object) -> None:
    assert isinstance(detail, dict), detail
    assert detail["code"] == "permission_denied"
    assert detail["permission"] == RM
    assert detail["permissions"] == [RM]
    assert detail["label"] == RM_LABEL
    assert RM_LABEL in detail["message"]


# ── Reguły na kontach z dołączoną polityką (bez bazy) ───────────────────────


def _account(
    *roles: UserRole,
    permissions: tuple[str, ...] = (),
    sourcing: str = "write",
    pipeline: str = "write",
) -> User:
    """Konto z polityką jak po uwierzytelnieniu: uprawnienia i sekcje razem."""

    user = User(
        id=920_000 + len(permissions),
        email=f"{roles[0].value}@permissions-recruitment.test",
        name=roles[0].value,
        role=roles[0],
        roles=[role.value for role in roles],
        is_active=True,
        profile_completed=True,
    )
    held = catalog.close(permissions)
    user.effective_action_access = {key: "manage" for key in held}
    user.effective_section_access = {
        "sourcing": sourcing,
        "pipeline": pipeline,
        "insights": "read",
        **catalog.derive_sections(held),
    }
    return user


def _job() -> Job:
    return Job(id=1, title="Rekrutacja", client_id=5, tac_id=None)


async def test_full_edit_follows_the_permission_not_the_role() -> None:
    job = _job()

    # Nadanie osobie spoza domyślnych ról daje pełną redakcję…
    holder = _account(UserRole.recruiter, permissions=(RM,))
    assert await job_edit_level(None, holder, job) is JobEditLevel.full
    lead = _account(UserRole.delivery_lead, permissions=(RM,))
    assert await job_edit_level(None, lead, job) is JobEditLevel.full

    # …a Delivery Lead z wyłączonym przełącznikiem redaguje już tylko treść.
    lead_without = _account(UserRole.delivery_lead)
    assert await job_edit_level(None, lead_without, job) is JobEditLevel.member
    assert await job_edit_level(None, _account(UserRole.recruiter), job) is (
        JobEditLevel.member
    )
    assert await job_edit_level(None, _account(UserRole.user), job) is None


async def test_tac_keeps_full_edit_through_the_legacy_branch() -> None:
    job = _job()
    for role in JOB_FULL_EDIT_LEGACY_ROLES:
        legacy = _account(role)
        assert await job_edit_level(None, legacy, job) is JobEditLevel.full
        # Powierzchnia Championa: TAC przechodzi tylko jak członek zespołu.
        assert await job_edit_level(None, legacy, job, tac_unscoped=False) is (
            JobEditLevel.member
        )
    # Uprawnienie nie zależy od tego wyjątku.
    holder = _account(UserRole.tac, permissions=(RM,))
    assert await job_edit_level(None, holder, job, tac_unscoped=False) is (
        JobEditLevel.full
    )


async def test_locked_field_refusal_names_the_permission() -> None:
    job = _job()
    recruiter = _account(UserRole.recruiter)

    with pytest.raises(HTTPException) as denied:
        await ensure_job_editor(None, recruiter, job, fields={"status"})
    assert denied.value.status_code == 403
    _assert_names_the_permission(denied.value.detail)
    # Komunikat mówi też, KTÓRE pola zatrzymały zapis.
    assert denied.value.detail["message"].startswith("Status, klienta")

    assert (
        await ensure_job_editor(None, recruiter, job, fields={"description"})
        is JobEditLevel.member
    )
    holder = _account(UserRole.recruiter, permissions=(RM,))
    assert (
        await ensure_job_editor(None, holder, job, fields={"status", "deadline"})
        is JobEditLevel.full
    )


def test_sending_a_cv_to_the_client_needs_the_permission_then_the_rate() -> None:
    for outsider in (_account(UserRole.recruiter), _account(UserRole.delivery_lead)):
        with pytest.raises(HTTPException) as denied:
            rules.assert_client_send_allowed(outsider, Decimal("170"))
        assert denied.value.status_code == 403
        _assert_names_the_permission(denied.value.detail)

    holder = _account(UserRole.recruiter, permissions=(RM,))
    for missing_rate in (None, Decimal("0")):
        with pytest.raises(HTTPException) as no_rate:
            rules.assert_client_send_allowed(holder, missing_rate)
        assert no_rate.value.status_code == 422
    rules.assert_client_send_allowed(holder, Decimal("170"))


def test_client_rate_write_follows_the_permission_and_section_write() -> None:
    holder = _account(UserRole.recruiter, permissions=(RM,))
    assert user_can_write_client_rate(holder) is True
    assert client_rate_write_allowed(holder) is True

    # Uprawnienie bez zapisu w kandydatach ani w pipelinie nie zapisuje stawki.
    read_only = _account(
        UserRole.recruiter, permissions=(RM,), sourcing="read", pipeline="read"
    )
    assert user_can_write_client_rate(read_only) is True
    assert client_rate_write_allowed(read_only) is False

    lead_without = _account(UserRole.delivery_lead)
    assert user_can_write_client_rate(lead_without) is False
    assert client_rate_write_allowed(lead_without) is False

    denied = client_rate_write_denied()
    assert denied.status_code == 403
    _assert_names_the_permission(denied.detail)


_PERMISSION_ROUTES = (
    jobs.create_job,
    jobs.delete_job,
    jobs.close_job,
    jobs.publish_job,
    jobs.get_job_readiness,
    jobs.handoff_job_to_search,
    jobs.assign_owner,
    jobs.release_owner,
    job_request_intake.read_request,
    job_request_intake.read_request_file,
    job_request_intake.public_draft,
    job_request_intake.handoff_options,
)

# Champion i „Dodaj championa” zostają przy roli (admin / Delivery Lead).
_ROLE_BOUND_ROUTES = (
    jobs.update_champion_verification,
    jobs.generate_champion_from_history,
    jobs.add_candidate_from_history,
)


def _route_gate(endpoint):
    annotation = get_type_hints(endpoint, include_extras=True)["current_user"]
    return get_args(annotation)[1].dependency


@pytest.mark.parametrize("endpoint", _PERMISSION_ROUTES, ids=lambda e: e.__name__)
async def test_lifecycle_routes_ask_for_the_permission(endpoint) -> None:
    gate = _route_gate(endpoint)

    for holder in (
        _account(UserRole.admin, permissions=catalog.KEYS),
        _account(UserRole.delivery_lead, permissions=(RM,)),
        _account(UserRole.recruiter, permissions=(RM,)),
    ):
        assert await gate(holder) is holder

    for outsider in (
        _account(UserRole.delivery_lead),
        _account(UserRole.tac),
        _account(UserRole.head_of_recruitment),
        _account(UserRole.recruiter),
    ):
        with pytest.raises(HTTPException) as denied:
            await gate(outsider)
        assert denied.value.status_code == 403
        _assert_names_the_permission(denied.value.detail)


@pytest.mark.parametrize("endpoint", _ROLE_BOUND_ROUTES, ids=lambda e: e.__name__)
async def test_the_permission_does_not_open_role_bound_champion_routes(
    endpoint,
) -> None:
    gate = _route_gate(endpoint)

    with pytest.raises(HTTPException) as denied:
        await gate(_account(UserRole.recruiter, permissions=(RM,)))
    assert denied.value.status_code == 403

    lead_without = _account(UserRole.delivery_lead)
    assert await gate(lead_without) is lead_without


# ── Te same reguły przez trasy (HTTP + baza) ────────────────────────────────


async def _seed_user(app_client: AsyncClient, role: str) -> tuple[dict[str, str], int]:
    unique = uuid.uuid4().hex[:8]
    email = f"perm-rm-{role}-{unique}@example.com"
    password = f"T3st_{unique}!Perm"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Perm RM {role} {unique}",
            role=UserRole(role),
            roles=[role],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, user_id


async def _seed_client() -> int:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"PermRmClient-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.commit()
        await db.refresh(client)
        return client.id


async def _seed_job(*, recruiter_id: int | None = None, traffit: bool = False) -> int:
    client_id = await _seed_client()
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"PermRm-{uuid.uuid4().hex[:6]}",
            description="Opis startowy",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            client_id=client_id,
            recruiter_id=recruiter_id,
            external_source="traffit" if traffit else None,
            external_id=uuid.uuid4().hex if traffit else None,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_candidate() -> int:
    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Perm",
            lastname=f"Osoba{unique}",
            email=f"perm-rm-cand-{unique}@example.com",
        )
        db.add(candidate)
        await db.commit()
        return candidate.id


async def _cleanup(candidate_id: int, job_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CandidateStage).where(CandidateStage.candidate_id == candidate_id)
        )
        await db.execute(delete(Candidate).where(Candidate.id == candidate_id))
        await db.execute(delete(Job).where(Job.id == job_id))
        await db.commit()


async def _add(
    app_client: AsyncClient, headers: dict[str, str], job_id: int, candidate_id: int
) -> None:
    added = await app_client.post(
        f"/api/jobs/{job_id}/proposals/bulk",
        headers=headers,
        json={
            "candidate_ids": [candidate_id],
            "initial_stage_legacy": "new",
            "source": "manual_search",
        },
    )
    assert added.status_code == 200, added.text
    assert added.json()["added"] == [candidate_id], added.text


async def _add_and_verify(
    app_client: AsyncClient, headers: dict[str, str], job_id: int, candidate_id: int
) -> None:
    """Osoba w „Zweryfikowanym” — stąd idzie do klienta."""

    await _add(app_client, headers, job_id, candidate_id)
    verified = await app_client.post(
        "/api/pipeline/move",
        headers=headers,
        json={"candidate_id": candidate_id, "job_id": job_id, "stage": "verified"},
    )
    assert verified.status_code == 200, verified.text


async def _latest_client_rate(candidate_id: int, job_id: int) -> Decimal | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CandidateStage.client_rate_value)
            .where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )


def _assert_named_denial(resp) -> None:
    assert resp.status_code == 403, resp.text
    _assert_names_the_permission(resp.json()["detail"])


async def test_granted_recruiter_runs_the_recruitment_lifecycle(
    app_client: AsyncClient,
) -> None:
    headers, user_id = await _seed_user(app_client, "recruiter")
    payload = {
        "title": f"Perm RM {uuid.uuid4().hex[:6]}",
        "client_id": await _seed_client(),
    }

    _assert_named_denial(
        await app_client.post("/api/jobs", headers=headers, json=payload)
    )
    _assert_named_denial(
        await app_client.get("/api/job-intake/handoff-options", headers=headers)
    )

    await grant_permissions(user_id, RM)

    options = await app_client.get("/api/job-intake/handoff-options", headers=headers)
    assert options.status_code == 200, options.text
    created = await app_client.post("/api/jobs", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]

    published = await app_client.post(f"/api/jobs/{job_id}/publish", headers=headers)
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"

    # Pole cyklu życia przez PATCH — dotąd tylko admin, Delivery Lead i TAC.
    patched = await app_client.patch(
        f"/api/jobs/{job_id}", headers=headers, json={"headcount": 3}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["headcount"] == 3

    detail = await app_client.get(f"/api/jobs/{job_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["can_edit"] is True
    assert detail.json()["can_manage"] is True

    readiness = await app_client.get(f"/api/jobs/{job_id}/readiness", headers=headers)
    assert readiness.status_code == 200, readiness.text

    closed = await app_client.post(
        f"/api/jobs/{job_id}/close", headers=headers, json={"reason": "budget"}
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"


async def test_recruiter_without_the_permission_gets_named_refusals(
    app_client: AsyncClient,
) -> None:
    headers, user_id = await _seed_user(app_client, "recruiter")
    job_id = await _seed_job(recruiter_id=user_id)

    for method, path, body in (
        ("POST", f"/api/jobs/{job_id}/close", {"reason": "budget"}),
        ("POST", f"/api/jobs/{job_id}/publish", None),
        ("GET", f"/api/jobs/{job_id}/readiness", None),
        ("POST", f"/api/jobs/{job_id}/handoff", {"assignment_mode": "automatic"}),
        ("POST", f"/api/jobs/{job_id}/owner", {"user_id": user_id}),
        ("DELETE", f"/api/jobs/{job_id}/owner", None),
        ("DELETE", f"/api/jobs/{job_id}", None),
        # Pole cyklu życia: prowadzący rekrutację redaguje treść, nie status.
        ("PATCH", f"/api/jobs/{job_id}", {"status": "closed"}),
    ):
        resp = await app_client.request(method, path, headers=headers, json=body)
        assert resp.status_code == 403, (method, path, resp.text)
        _assert_names_the_permission(resp.json()["detail"])

    detail = await app_client.get(f"/api/jobs/{job_id}", headers=headers)
    assert detail.json()["status"] == "published"
    assert detail.json()["can_edit"] is True
    assert detail.json()["can_manage"] is False
    assert detail.json()["can_write_client_rate"] is False


async def test_delivery_lead_without_the_permission_edits_content_only(
    app_client: AsyncClient,
) -> None:
    headers, lead_id = await _seed_user(app_client, "delivery_lead")
    job_id = await _seed_job(recruiter_id=lead_id)
    candidate_id = await _seed_candidate()
    new_job = {
        "title": f"Perm RM {uuid.uuid4().hex[:6]}",
        "client_id": await _seed_client(),
    }
    send = {
        "candidate_id": candidate_id,
        "job_id": job_id,
        "stage": "cv_sent",
        "client_rate_value": "170",
        "client_rate_unit": "hourly",
    }
    try:
        await _add_and_verify(app_client, headers, job_id, candidate_id)

        async with role_permission("delivery_lead", RM, granted=False):
            _assert_named_denial(
                await app_client.post("/api/jobs", headers=headers, json=new_job)
            )
            _assert_named_denial(
                await app_client.post(
                    f"/api/jobs/{job_id}/close",
                    headers=headers,
                    json={"reason": "budget"},
                )
            )
            _assert_named_denial(
                await app_client.patch(
                    f"/api/jobs/{job_id}", headers=headers, json={"status": "closed"}
                )
            )
            _assert_named_denial(
                await app_client.post("/api/pipeline/move", headers=headers, json=send)
            )

            # Treść rekrutacji redaguje dalej — jak każda rola wewnętrzna.
            content = await app_client.patch(
                f"/api/jobs/{job_id}",
                headers=headers,
                json={"description": "Opis od Delivery Leada"},
            )
            assert content.status_code == 200, content.text
            detail = (
                await app_client.get(f"/api/jobs/{job_id}", headers=headers)
            ).json()
            assert detail["can_edit"] is True
            assert detail["can_manage"] is False
            assert detail["can_write_client_rate"] is False
            tasks = await app_client.get("/api/board-tasks", headers=headers)
            assert tasks.status_code == 200, tasks.text
            assert tasks.json()["can_send_to_client"] is False

        # Przełącznik wraca — ta sama sesja znowu wysyła i zamyka.
        tasks = await app_client.get("/api/board-tasks", headers=headers)
        assert tasks.json()["can_send_to_client"] is True
        sent = await app_client.post("/api/pipeline/move", headers=headers, json=send)
        assert sent.status_code == 200, sent.text
        closed = await app_client.post(
            f"/api/jobs/{job_id}/close", headers=headers, json={"reason": "budget"}
        )
        assert closed.status_code == 200, closed.text
    finally:
        await _cleanup(candidate_id, job_id)


async def test_sending_a_cv_to_the_client_follows_the_permission(
    app_client: AsyncClient,
) -> None:
    headers, user_id = await _seed_user(app_client, "recruiter")
    job_id = await _seed_job(recruiter_id=user_id)
    candidate_id = await _seed_candidate()
    move = {"candidate_id": candidate_id, "job_id": job_id, "stage": "cv_sent"}
    with_rate = {**move, "client_rate_value": "170", "client_rate_unit": "hourly"}
    try:
        await _add_and_verify(app_client, headers, job_id, candidate_id)

        # Bez uprawnienia odmowa jest nazwana — także gdy stawka jest podana.
        _assert_named_denial(
            await app_client.post("/api/pipeline/move", headers=headers, json=with_rate)
        )
        _assert_named_denial(
            await app_client.post(
                "/api/pipeline/bulk-move",
                headers=headers,
                json={
                    "job_id": job_id,
                    "candidate_ids": [candidate_id],
                    "stage": "cv_sent",
                    "client_rate_value": "170",
                },
            )
        )
        tasks = await app_client.get("/api/board-tasks", headers=headers)
        assert tasks.json()["can_send_to_client"] is False

        await grant_permissions(user_id, RM)

        tasks = await app_client.get("/api/board-tasks", headers=headers)
        assert tasks.json()["can_send_to_client"] is True
        without_rate = await app_client.post(
            "/api/pipeline/move", headers=headers, json=move
        )
        assert without_rate.status_code == 422, without_rate.text
        sent = await app_client.post(
            "/api/pipeline/move", headers=headers, json=with_rate
        )
        assert sent.status_code == 200, sent.text
        assert await _latest_client_rate(candidate_id, job_id) == Decimal("170")
    finally:
        await _cleanup(candidate_id, job_id)


async def test_client_rate_write_and_its_flag_follow_the_permission(
    app_client: AsyncClient,
) -> None:
    headers, user_id = await _seed_user(app_client, "recruiter")
    job_id = await _seed_job(recruiter_id=user_id)
    candidate_id = await _seed_candidate()
    path = f"/api/candidates/{candidate_id}/recruitments/{job_id}/client-rate"
    body = {"rate_value": 180, "rate_unit": "hourly"}
    try:
        await _add(app_client, headers, job_id, candidate_id)

        _assert_named_denial(await app_client.patch(path, headers=headers, json=body))
        # Stawka do klienta w zwykłym ruchu przechodzi tę samą bramkę.
        _assert_named_denial(
            await app_client.post(
                "/api/pipeline/move",
                headers=headers,
                json={
                    "candidate_id": candidate_id,
                    "job_id": job_id,
                    "stage": "verified",
                    "client_rate_value": "180",
                },
            )
        )
        detail = await app_client.get(f"/api/jobs/{job_id}", headers=headers)
        assert detail.json()["can_write_client_rate"] is False
        assert await _latest_client_rate(candidate_id, job_id) is None

        await grant_permissions(user_id, RM)

        saved = await app_client.patch(path, headers=headers, json=body)
        assert saved.status_code == 200, saved.text
        assert saved.json()["client_rate"] == {
            "value": 180.0,
            "unit": "hourly",
            "currency": "PLN",
        }
        detail = await app_client.get(f"/api/jobs/{job_id}", headers=headers)
        assert detail.json()["can_write_client_rate"] is True
        history = await app_client.get(
            f"/api/candidates/{candidate_id}/history", headers=headers
        )
        assert history.status_code == 200, history.text
        assert history.json()["can_write_client_rate"] is True
    finally:
        await _cleanup(candidate_id, job_id)


async def test_tac_keeps_full_edit_but_not_the_lifecycle_routes(
    app_client: AsyncClient,
) -> None:
    headers, _ = await _seed_user(app_client, "tac")
    job_id = await _seed_job()

    patched = await app_client.patch(
        f"/api/jobs/{job_id}", headers=headers, json={"headcount": 2}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["headcount"] == 2
    detail = await app_client.get(f"/api/jobs/{job_id}", headers=headers)
    assert detail.json()["can_manage"] is True

    _assert_named_denial(
        await app_client.post(
            f"/api/jobs/{job_id}/close", headers=headers, json={"reason": "budget"}
        )
    )


async def test_return_to_traffit_and_qc_override_follow_the_permission(
    app_client: AsyncClient,
) -> None:
    headers, user_id = await _seed_user(app_client, "recruiter")
    job_id = await _seed_job(traffit=True)
    switch = f"/api/jobs/{job_id}/manage-in-nexus"
    # Etapu nie ma: odmowa uprawnienia pada przed jego odczytem, a posiadacz
    # dochodzi do 404.
    override = "/api/pipeline/stages/999999999/qc/override"
    reason = {"reason": "Klient zna kandydata z poprzedniego projektu."}

    enabled = await app_client.post(switch, headers=headers, json={"enabled": True})
    assert enabled.status_code == 200, enabled.text
    _assert_named_denial(
        await app_client.post(switch, headers=headers, json={"enabled": False})
    )
    _assert_named_denial(await app_client.post(override, headers=headers, json=reason))

    await grant_permissions(user_id, RM)

    reverted = await app_client.post(switch, headers=headers, json={"enabled": False})
    assert reverted.status_code == 200, reverted.text
    assert reverted.json()["managed_in_nexus"] is False
    missing_stage = await app_client.post(override, headers=headers, json=reason)
    assert missing_stage.status_code == 404, missing_stage.text
