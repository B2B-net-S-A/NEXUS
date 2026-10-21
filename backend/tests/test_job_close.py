"""Smoke tests for POST /api/jobs/{id}/close.

Covers the happy path (published → closed with reason + notes), the RBAC
requirement (DeliveryLeadPlus — recruiters shouldn't be able to close), and 404.

Migration 0048_job_close_reason adds the `close_reason`/`close_notes` columns
plus `jobclosereason` enum. If this test fails with "column does not exist"
the deploy missed the migration — re-run alembic or hit the safety net in
entrypoint.sh.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


pytestmark = pytest.mark.asyncio


async def _create_draft_job(
    app_client: AsyncClient, headers: dict[str, str], title: str
) -> int:
    """Create a job through the API — returns its id. Requires DeliveryLeadPlus.

    Seeds a throwaway client first (migration 0120 forces NOT NULL on
    `jobs.client_id`).
    """
    import uuid

    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"CloseTestClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        cli_id = cli.id

    # Rekrutacja bez szkiców (04.10.2026): API zakłada od razu rekrutację
    # opublikowaną i przekazaną do searchu — komplet z `_job_factory`.
    from tests._job_factory import complete_job_payload

    payload = await complete_job_payload(cli_id, title=title, work_mode="fulltime")
    resp = await app_client.post("/api/jobs", json=payload, headers=headers)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def test_close_job_with_reason(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    job_id = await _create_draft_job(
        app_client, app_auth_headers, "pytest-close-happy-path"
    )

    close_resp = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={"reason": "budget", "notes": "Klient wstrzymał budżet Q2"},
        headers=app_auth_headers,
    )
    assert close_resp.status_code == 200, close_resp.text
    body = close_resp.json()
    assert body["status"] == "closed"
    assert body["close_reason"] == "budget"
    assert body["close_notes"] == "Klient wstrzymał budżet Q2"
    assert body["closed_at"] is not None


async def test_close_job_404(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    resp = await app_client.post(
        "/api/jobs/99999999/close",
        json={"reason": "competitor"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 404


async def test_close_job_invalid_reason(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    job_id = await _create_draft_job(
        app_client, app_auth_headers, "pytest-close-invalid-reason"
    )
    resp = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={"reason": "not_a_valid_enum_value"},
        headers=app_auth_headers,
    )
    # 422 = Pydantic validation error on the enum field.
    assert resp.status_code == 422


async def test_close_without_auth(app_client: AsyncClient) -> None:
    resp = await app_client.post("/api/jobs/1/close", json={"reason": "competitor"})
    assert resp.status_code in (401, 403)


async def test_close_job_reason_optional_notes(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """`notes` is optional for a reason that counts in hit ratio."""
    job_id = await _create_draft_job(
        app_client, app_auth_headers, "pytest-close-no-notes"
    )
    resp = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={"reason": "competitor"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["close_notes"] is None


# ── Osoby w toku przy zamykaniu (13.10.2026) ─────────────────────────────────


async def test_active_cards_summary_counts_only_people_in_progress() -> None:
    from datetime import datetime, timezone

    from app.services.job_active_cards import summarize

    older = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)
    # 22:30 UTC to w kalendarzu firmy już następny dzień.
    newest = datetime(2026, 10, 12, 22, 30, tzinfo=timezone.utc)
    active = summarize(
        [
            ("screening", older),
            ("new", newest),
            ("new", older),
            ("closed", newest),
            ("hired", newest),
        ]
    )
    assert active.total == 3
    # Kolejność kolumn Tablicy, nie kolejność wierszy.
    assert list(active.columns.items()) == [("new", 2), ("screening", 1)]
    assert active.last_moved_at == newest
    assert active.message() == (
        "W tej rekrutacji są 3 osoby w toku (ostatni ruch karty 13.10.2026). "
        "Zamknięcie nie zamyka kart — zostaną w zamkniętej rekrutacji."
    )
    detail = active.warning_detail()
    assert detail["code"] == "active_cards_warning"
    assert detail["active_cards"] == 3
    assert detail["columns"] == {"new": 2, "screening": 1}

    assert summarize([("closed", older), ("hired", older)]).total == 0


async def test_active_cards_message_declines_the_count() -> None:
    from datetime import datetime, timezone

    from app.services.job_active_cards import summarize

    moved = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
    for total, words in (
        (1, "jest 1 osoba"),
        (2, "są 2 osoby"),
        (5, "jest 5 osób"),
        (12, "jest 12 osób"),
        (22, "są 22 osoby"),
    ):
        message = summarize([("new", moved)] * total).message()
        assert message.startswith(f"W tej rekrutacji {words} w toku"), message


async def _seed_candidate_in_job(job_id: int, *stages: str) -> int:
    """Osoba z kartą w rekrutacji — kolejne etapy przez komendę procesu."""
    import uuid

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.recruitment_pipeline import PipelineStage
    from app.services.recruitment_process_commands import transition_process

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Zamknij",
            lastname=f"Osoba{unique}",
            email=f"close-active-{unique}@example.com",
        )
        db.add(candidate)
        await db.flush()
        for stage in stages:
            await transition_process(
                db,
                candidate_id=candidate.id,
                job_id=job_id,
                stage=PipelineStage(stage),
                actor_user_id=None,
                # Etap końcowy niesie stronę, która zamknęła kartę.
                **({"ended_by": "recruiter"} if stage == "rejected" else {}),
            )
        await db.commit()
        return candidate.id


async def test_close_with_people_in_progress_asks_for_confirmation(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Zgłoszenie 12.10.2026: duplikat requestu zamknięto z pięcioma kartami
    w toku i nikt tego nie zauważył."""
    job_id = await _create_draft_job(
        app_client, app_auth_headers, "pytest-close-active-cards"
    )
    await _seed_candidate_in_job(job_id, "new")
    await _seed_candidate_in_job(job_id, "new", "screening")
    await _seed_candidate_in_job(job_id, "new", "rejected")

    warned = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={"reason": "competitor"},
        headers=app_auth_headers,
    )
    assert warned.status_code == 409, warned.text
    detail = warned.json()["detail"]
    assert detail["code"] == "active_cards_warning"
    assert detail["active_cards"] == 2
    assert detail["columns"] == {"new": 1, "screening": 1}
    assert detail["message"].startswith("W tej rekrutacji są 2 osoby w toku")

    still_open = await app_client.get(f"/api/jobs/{job_id}", headers=app_auth_headers)
    assert still_open.json()["status"] == "published"

    closed = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={"reason": "competitor", "acknowledge_active_cards": True},
        headers=app_auth_headers,
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"


async def test_close_with_only_closed_cards_needs_no_confirmation(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    job_id = await _create_draft_job(
        app_client, app_auth_headers, "pytest-close-closed-cards"
    )
    await _seed_candidate_in_job(job_id, "new", "rejected")

    closed = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={"reason": "competitor"},
        headers=app_auth_headers,
    )
    assert closed.status_code == 200, closed.text


async def test_closing_from_the_edit_window_warns_the_same_way(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Pole „Status” w oknie edycji to trzecia droga zamknięcia (lustro
    ``close_job``) — bez tej samej odmowy ostrzeżenie dałoby się ominąć."""
    job_id = await _create_draft_job(
        app_client, app_auth_headers, "pytest-close-edit-window"
    )
    await _seed_candidate_in_job(job_id, "new")

    warned = await app_client.patch(
        f"/api/jobs/{job_id}", json={"status": "closed"}, headers=app_auth_headers
    )
    assert warned.status_code == 409, warned.text
    detail = warned.json()["detail"]
    assert detail["code"] == "active_cards_warning"
    assert detail["columns"] == {"new": 1}

    still_open = await app_client.get(f"/api/jobs/{job_id}", headers=app_auth_headers)
    assert still_open.json()["status"] == "published"

    closed = await app_client.patch(
        f"/api/jobs/{job_id}",
        params={"acknowledge_active_cards": "true"},
        json={"status": "closed"},
        headers=app_auth_headers,
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"
