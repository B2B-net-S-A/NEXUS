"""Kompletność usunięcia kandydata (RODO art. 17) — to, co przeżywało DELETE.

Trzy niezmienniki, każdy pilnujący CICHEJ regresji: usunięcie zwraca 204 i
wygląda na udane także wtedy, gdy nie posprzątało.

1. Publiczny link do WYGENEROWANEGO CV jest odwoływany. `cv_generated_documents
   .candidate_id` to `ON DELETE SET NULL`, a token kaskaduje z DOKUMENTU, nie z
   kandydata — więc bez jawnego odwołania `/api/public/cv-i/{token}` dalej
   serwował pełne CV usuniętej osoby hiring managerowi u klienta (do 90 dni).
2. Strażnik po stronie publicznego endpointu — niezależny od punktu 1, żeby
   każda PRZYSZŁA ścieżka odpinająca dokument nie otwierała tej dziury na nowo.
3. Kasowanie wektora ma TRWAŁY retry w `match_index_outbox` (ten sam kontrakt
   co kwarantanna tożsamości). `delete_candidate_embedding` nie rzuca — zwraca
   `False` — więc bez wiersza outboxu nieudane sprzątanie ginęło bez śladu, a
   nazwisko i fragmenty CV zostawały w indeksie semantycznym na zawsze.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal


def _render_payload() -> dict[str, Any]:
    return {
        "name": "Ewa Usunieta",
        "first_name": "Ewa",
        "position": "Data Engineer",
        "why_points": ["Hurtownie danych"],
        "education": [],
        "skills": [{"label": "Data", "content": "Spark"}],
        "certifications": [],
        "languages": ["polski"],
        "experience": [
            {
                "dates": "2020-2024",
                "company": "Acme",
                "industry": "fintech",
                "position": "Data Engineer",
                "responsibilities": ["Budowa pipeline'ów"],
                "technologies": ["Spark"],
            }
        ],
        "language": "pl",
        "blind_cv": False,
        "content_mode": "polished",
        "highlight_keywords": [],
        "considered_for": "Data Engineer",
    }


async def _seed_candidate_with_public_cv_link() -> tuple[int, int, str, str]:
    """(candidate_id, document_id, raw_secret, revoke_key)."""
    from app.models.candidate import Candidate
    from app.models.cv_generated_document import CvGeneratedDocument
    from app.models.cv_generated_share import CvGeneratedShareToken

    raw = secrets.token_urlsafe(36)
    revoke_key = f"v2${uuid.uuid4().hex}"

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Ewa",
            lastname=f"Usunieta-{uuid.uuid4().hex[:6]}",
            email=f"erasure-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(cand)
        await db.flush()
        doc = CvGeneratedDocument(
            candidate_id=cand.id,
            job_id=None,
            candidate_name="Ewa Usunieta",
            position="Data Engineer",
            language="pl",
            blind=False,
            mode="new",
            filename="DE_Ewa.docx",
            status="ready",
            render_payload=_render_payload(),
        )
        db.add(doc)
        await db.flush()
        db.add(
            CvGeneratedShareToken(
                token=revoke_key,
                token_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                generated_document_id=doc.id,
            )
        )
        await db.commit()
        return cand.id, doc.id, raw, revoke_key


async def test_hard_delete_revokes_the_public_generated_cv_link(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.models.cv_generated_share import CvGeneratedShareToken

    candidate_id, _doc_id, raw, revoke_key = await _seed_candidate_with_public_cv_link()

    # Przed usunięciem link ŻYJE — inaczej 404 niżej niczego by nie dowodziło.
    before = await app_client.get(f"/api/public/cv-i/{raw}")
    assert before.status_code == 200, before.text
    assert "Usunieta" in before.text or "Ewa" in before.text

    r = await app_client.delete(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert r.status_code == 204, r.text

    after = await app_client.get(f"/api/public/cv-i/{raw}")
    assert after.status_code == 404, (
        "publiczny link do CV usuniętej osoby nadal serwuje jej dane: "
        f"{after.status_code} {after.text[:300]}"
    )

    async with AsyncSessionLocal() as db:
        token = await db.scalar(
            select(CvGeneratedShareToken).where(
                CvGeneratedShareToken.token == revoke_key
            )
        )
    # Runda 6 audytu (RODO-02): samo wygenerowane CV znika razem z osobą, więc
    # token kaskaduje z dokumentu. Odwołanie zostaje w dowodzie wykonania
    # (`share_tokens_revoked`, test niżej).
    assert token is None, "wygenerowane CV usuniętej osoby przeżyło usunięcie"


async def test_public_generated_cv_404s_for_a_detached_new_mode_document(
    app_client: AsyncClient,
):
    """Strażnik działa nawet gdy token NIE został odwołany.

    Symuluje każdą przyszłą ścieżkę, która odepnie dokument od kandydata z
    pominięciem endpointu kasującego: `candidate_id = NULL` przy `mode="new"`
    znaczy dokładnie „ta osoba już nie istnieje" (generacja w trybie „new"
    zawsze startuje z istniejącego kandydata).
    """
    from app.models.cv_generated_document import CvGeneratedDocument

    _cand_id, doc_id, raw, _revoke = await _seed_candidate_with_public_cv_link()

    async with AsyncSessionLocal() as db:
        doc = await db.get(CvGeneratedDocument, doc_id)
        doc.candidate_id = None
        await db.commit()

    resp = await app_client.get(f"/api/public/cv-i/{raw}")
    assert resp.status_code == 404, resp.text


async def test_hard_delete_stages_a_durable_vector_delete_retry(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.models.candidate import Candidate
    from app.models.index_outbox import IndexOutboxEvent

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Retry",
            lastname=f"Outbox-{uuid.uuid4().hex[:6]}",
            email=f"outbox-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(cand)
        await db.commit()
        candidate_id = cand.id

    r = await app_client.delete(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert r.status_code == 204, r.text

    async with AsyncSessionLocal() as db:
        events = (
            (
                await db.execute(
                    select(IndexOutboxEvent).where(
                        IndexOutboxEvent.entity_type == "candidate",
                        IndexOutboxEvent.entity_id == candidate_id,
                        IndexOutboxEvent.operation == "delete",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert events, (
        "brak wiersza outboxu — nieudane kasowanie wektora nie ma jak zostać "
        "ponowione, a `delete_candidate_embedding` zwraca False zamiast rzucać"
    )


async def test_hard_delete_audit_records_revoked_share_links(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Dowód wykonania żądania z art. 17 musi wymieniać odwołane linki."""
    from app.models.activity import Activity
    from app.services import candidate_audit

    candidate_id, _doc_id, _raw, _revoke = await _seed_candidate_with_public_cv_link()

    r = await app_client.delete(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert r.status_code == 204, r.text

    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "candidate",
                Activity.entity_id == candidate_id,
                Activity.action == candidate_audit.HARD_DELETED,
            )
        )
    assert row is not None
    assert row.details.get("share_tokens_revoked") == 1


async def test_hard_delete_cleans_private_job_source_via_ledger_with_retry(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Awaria storage nie blokuje usunięcia — plik czeka w rejestrze kasowań.

    Do 14.09.2026 handler kasował obiekty PRZED commitem: awaria w środku
    pętli dawała 503 i rollback wiersza, ale nie obiektów skasowanych chwilę
    wcześniej (audyt Codexa, F04). Teraz w żądaniu storage nie jest wołany
    wcale: klucz źródła prywatnego ląduje w `cv_source_cleanup` w tej samej
    transakcji co usunięcie, a kasuje go pętla tła — z ponowieniem, gdy
    storage akurat pada.
    """
    from unittest.mock import Mock

    from sqlalchemy import select

    from app.models.candidate import Candidate
    from app.models.cv_generation_job import CvGenerationJob
    from app.models.cv_source_cleanup import CvSourceCleanup
    from app.services import cv_source_cleanup, object_storage

    (
        candidate_id,
        document_id,
        _raw,
        _revoke_key,
    ) = await _seed_candidate_with_public_cv_link()
    async with AsyncSessionLocal() as db:
        job = CvGenerationJob(
            generated_id=document_id,
            kind="new",
            status="complete",
            input_storage_key="synthetic-private-source",
            input_sha256="a" * 64,
        )
        db.add(job)
        await db.commit()
        job_id = job.id
    monkeypatch.setattr(object_storage, "is_available", lambda: True)
    in_request = Mock(side_effect=RuntimeError("temporary storage failure"))
    monkeypatch.setattr(object_storage, "delete_cv", in_request)

    response = await app_client.delete(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert response.status_code == 204, response.text
    in_request.assert_not_called()
    async with AsyncSessionLocal() as db:
        assert await db.get(Candidate, candidate_id) is None
        assert await db.get(CvGenerationJob, job_id) is None
        intent = await db.scalar(
            select(CvSourceCleanup).where(
                CvSourceCleanup.storage_key == "synthetic-private-source"
            )
        )
        assert intent is not None, "klucz źródła musi czekać w rejestrze"
        assert intent.attempts == 0

    # Pętla tła: pierwsza próba pada → wiersz zostaje z ponowieniem,
    # druga (storage wrócił) → obiekt skasowany, wiersz zdjęty.
    calls: list[str] = []
    storage_down = True

    async def _fake_run(fn, key):
        assert fn is object_storage.delete_cv
        if storage_down:
            raise RuntimeError("temporary storage failure")
        calls.append(key)

    monkeypatch.setattr(cv_source_cleanup, "run_in_threadpool", _fake_run)
    async with AsyncSessionLocal() as db:
        await cv_source_cleanup.clean_pending_sources(db, limit=200)
    async with AsyncSessionLocal() as db:
        intent = await db.scalar(
            select(CvSourceCleanup).where(
                CvSourceCleanup.storage_key == "synthetic-private-source"
            )
        )
        assert intent is not None
        assert intent.attempts == 1
        # Ponowienie jest odłożone w czasie — test nie czeka, tylko je przybliża.
        intent.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()

    storage_down = False
    async with AsyncSessionLocal() as db:
        await cv_source_cleanup.clean_pending_sources(db, limit=200)
    assert calls == ["synthetic-private-source"]
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(CvSourceCleanup).where(
                    CvSourceCleanup.storage_key == "synthetic-private-source"
                )
            )
            is None
        )


async def test_hard_delete_waits_for_active_cv_generation(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from unittest.mock import Mock
    from app.models.candidate import Candidate
    from app.models.cv_generation_job import CvGenerationJob
    from app.services import object_storage

    (
        candidate_id,
        document_id,
        _raw,
        _revoke_key,
    ) = await _seed_candidate_with_public_cv_link()
    async with AsyncSessionLocal() as db:
        job = CvGenerationJob(
            generated_id=document_id,
            kind="new",
            status="running",
            input_storage_key="synthetic-active-source",
            input_sha256="b" * 64,
        )
        db.add(job)
        await db.commit()
        job_id = job.id
    cleanup = Mock()
    monkeypatch.setattr(object_storage, "delete_cv", cleanup)
    try:
        response = await app_client.delete(
            f"/api/candidates/{candidate_id}", headers=app_auth_headers
        )
        assert response.status_code == 409, response.text
        cleanup.assert_not_called()
        async with AsyncSessionLocal() as db:
            assert await db.get(Candidate, candidate_id) is not None
            assert (await db.get(CvGenerationJob, job_id)).status == "running"
    finally:
        # This intentionally running fixture must not occupy global worker
        # capacity in the next test, even if an assertion above fails.
        from sqlalchemy import delete

        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CvGenerationJob).where(CvGenerationJob.id == job_id)
            )
            await db.commit()
