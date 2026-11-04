"""Bank pytań: kto edytuje pytania bez autora i kto przepina klienta (R9-X2-1).

Archiwum rozmów (0383, ``legacy_import``) i pytania z debriefów mają
``created_by = NULL`` — do rundy 9 edytował je i usuwał każdy z zapisem
Pipeline, a PUT zmieniał ``client_id`` bez walidacji (``NULL`` wpuszczał pytanie
klienta do prep-kitów innych klientów, kolizja hasha kończyła się 500).

In-process ``app_client``; baza wspólna i nieczyszczona — nazwy z uuid.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.api.interview_questions import _normalize_hash
from app.core.database import AsyncSessionLocal
from app.models.interview_question import InterviewQuestion, InterviewQuestionSource

pytestmark = pytest.mark.asyncio


async def _login_as(app_client: AsyncClient, role) -> dict[str, str]:
    from app.core.security import hash_password
    from app.models.user import User

    unique = uuid.uuid4().hex[:8]
    email = f"iq-r9-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Iq9"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"IQ r9 {role.value}",
                role=role,
                roles=[role.value],
                is_active=True,
            )
        )
        await db.commit()
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _client() -> int:
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        row = Client(name=f"IqR9Client-{uuid.uuid4().hex[:6]}")
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def _question(*, client_id, source, created_by=None, text=None) -> int:
    text = text or f"Pytanie archiwum {uuid.uuid4().hex[:8]}?"
    async with AsyncSessionLocal() as db:
        row = InterviewQuestion(
            text=text,
            client_id=client_id,
            source=source,
            normalized_text_hash=_normalize_hash(text),
            skill_tags=[],
            created_by=created_by,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def test_recruiter_cannot_edit_or_delete_authorless_archive_question(
    app_client: AsyncClient,
):
    from app.models.user import UserRole

    client_id = await _client()
    qid = await _question(
        client_id=client_id, source=InterviewQuestionSource.legacy_import
    )
    recruiter = await _login_as(app_client, UserRole.recruiter)

    edit = await app_client.put(
        f"/api/interview-questions/{qid}",
        json={"text": "Zmienione przez rekrutera?"},
        headers=recruiter,
    )
    assert edit.status_code == 403, edit.text
    delete = await app_client.delete(
        f"/api/interview-questions/{qid}", headers=recruiter
    )
    assert delete.status_code == 403, delete.text

    hor = await _login_as(app_client, UserRole.head_of_recruitment)
    ok = await app_client.put(
        f"/api/interview-questions/{qid}",
        json={"ideal_answer": "Poprawione przez HoR"},
        headers=hor,
    )
    assert ok.status_code == 200, ok.text


@pytest.mark.parametrize(
    "source",
    [InterviewQuestionSource.legacy_import, InterviewQuestionSource.client_debrief],
)
async def test_client_bound_question_cannot_move_to_global_bank(
    app_client: AsyncClient, app_auth_headers: dict[str, str], source
):
    client_id = await _client()
    other_client = await _client()
    qid = await _question(client_id=client_id, source=source)

    for target in (None, other_client):
        resp = await app_client.put(
            f"/api/interview-questions/{qid}",
            json={"client_id": target},
            headers=app_auth_headers,
        )
        assert resp.status_code == 422, resp.text

    async with AsyncSessionLocal() as db:
        row = await db.get(InterviewQuestion, qid)
        assert row.client_id == client_id


async def test_manual_question_client_change_colliding_hash_is_409(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    client_a = await _client()
    client_b = await _client()
    text = f"Wspólne pytanie {uuid.uuid4().hex[:8]}?"
    await _question(
        client_id=client_b, source=InterviewQuestionSource.manual, text=text
    )
    qid = await _question(
        client_id=client_a, source=InterviewQuestionSource.manual, text=text
    )

    resp = await app_client.put(
        f"/api/interview-questions/{qid}",
        json={"client_id": client_b},
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
    assert "już w banku" in resp.json()["detail"]
