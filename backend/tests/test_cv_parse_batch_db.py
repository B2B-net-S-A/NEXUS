"""Odczyt CV z integracji wsadem na Postgresie (`cv_parse_batch`, 22.11.2026).

Scenariusze:

- wgranie przez integrację wstawia CV do kolejki bez modelu, a profil pokazuje
  „czytamy CV” (`cv_read_queued_at`); wgranie przez człowieka czyta na żywo;
- obrót pętli wysyła paczkę, odbiera wynik i zapisuje go w profilu;
- błąd utworzenia paczki i brak wyniku po limicie czasu dają odczyt na żywo,
  a paczka bez czekających CV jest anulowana;
- nowsze CV zamyka starsze w kolejce.

Klient Message Batches API jest atrapą: żadne żądanie nie wychodzi.
Baza wspólna, więc każdy test zakłada własne wiersze i po sobie sprząta.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Optional

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, update

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.models.cv_parse_batch import CvParseBatchItem
from app.services import cv_parse_batch
from app.services.claude_client import batch_request_params
from app.services.cv_parser import claude_cv_request_params

CV_TEXT = "Jan Testowy\nJava Developer\nBank X 2020-01 – obecnie: Java, Kafka\n"


def _parsed(position: str) -> dict[str, Any]:
    return {
        "first_name": "Jan",
        "last_name": "Testowy",
        "current_position": position,
        "skills": ["Java", "Kafka"],
    }


class _FakeBatches:
    def __init__(self) -> None:
        self.created: list[list[dict]] = []
        self.status = "in_progress"
        self.results_by_batch: dict[str, list[Any]] = {}
        self.cancelled: list[str] = []
        self.fail_create: Optional[Exception] = None

    def create(self, *, requests):
        if self.fail_create is not None:
            raise self.fail_create
        self.created.append(requests)
        return SimpleNamespace(id=f"msgbatch_test_{uuid.uuid4().hex[:8]}")

    def retrieve(self, batch_id):
        return SimpleNamespace(id=batch_id, processing_status=self.status)

    def results(self, batch_id):
        return iter(self.results_by_batch.get(batch_id, []))

    def cancel(self, batch_id):
        self.cancelled.append(batch_id)
        return SimpleNamespace(id=batch_id, processing_status="canceling")


def _client() -> tuple[Any, _FakeBatches]:
    batches = _FakeBatches()
    return SimpleNamespace(messages=SimpleNamespace(batches=batches)), batches


def _succeeded(custom_id: str, payload: dict) -> SimpleNamespace:
    message = SimpleNamespace(
        id=f"msg_{uuid.uuid4().hex[:8]}",
        model="claude-sonnet-5-5",
        content=[SimpleNamespace(text=json.dumps(payload))],
        stop_reason="end_turn",
        usage=SimpleNamespace(
            input_tokens=2000,
            output_tokens=3000,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            cache_creation=None,
        ),
    )
    return SimpleNamespace(
        custom_id=custom_id, result=SimpleNamespace(type="succeeded", message=message)
    )


@pytest.fixture
def wired(monkeypatch):
    """Kolejka otwarta, model na żywo policzony, wektory i dopasowanie wyciszone."""
    from app.services import cv_text_extractor

    live_calls: list[str] = []

    async def _live(cv_text: str, **_kw: Any):
        live_calls.append(cv_text)
        return _parsed("Live Developer")

    async def _noop(*_a: Any, **_kw: Any):
        return None

    monkeypatch.setattr(cv_parse_batch, "enabled", lambda: True)
    monkeypatch.setattr("app.services.cv_parser._parse_with_claude", _live)
    monkeypatch.setattr(
        cv_text_extractor, "extract_text", lambda *_a, **_kw: CV_TEXT, raising=True
    )
    monkeypatch.setattr("app.services.embedding_service.embed_candidate", _noop)
    return live_calls


async def _seed(content: bytes = CV_TEXT.encode()) -> tuple[int, int, str]:
    digest = hashlib.sha256(content + uuid.uuid4().bytes).hexdigest()
    async with AsyncSessionLocal() as db:
        candidate = Candidate(name="Jan", lastname="Testowy")
        db.add(candidate)
        await db.flush()
        document = CandidateDocument(
            candidate_id=candidate.id,
            filename=f"cv-{uuid.uuid4().hex[:6]}.txt",
            document_kind=CandidateDocumentKind.cv,
            is_primary=True,
            content_sha256=digest,
            file_content=content,
        )
        db.add(document)
        await db.commit()
        return candidate.id, document.id, digest


async def _cleanup(candidate_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CvParseBatchItem).where(
                CvParseBatchItem.candidate_id == candidate_id
            )
        )
        await db.execute(
            delete(CandidateDocument).where(
                CandidateDocument.candidate_id == candidate_id
            )
        )
        row = await db.get(Candidate, candidate_id)
        if row is not None:
            await db.delete(row)
        await db.commit()


async def _queue(candidate_id: int, document_id: int, digest: str) -> int:
    async with AsyncSessionLocal() as db:
        assert await cv_parse_batch.enqueue(
            db,
            candidate_id=candidate_id,
            document_id=document_id,
            content_sha256=digest,
            raw_text=CV_TEXT,
            trigger="cv_upload",
            actor_user_id=None,
            replaced_primary=None,
        )
        await db.commit()
        return await db.scalar(
            select(CvParseBatchItem.id)
            .where(CvParseBatchItem.candidate_id == candidate_id)
            .order_by(CvParseBatchItem.id.desc())
        )


async def _item(item_id: int) -> CvParseBatchItem:
    async with AsyncSessionLocal() as db:
        return await db.get(CvParseBatchItem, item_id)


async def _candidate(candidate_id: int) -> Candidate:
    async with AsyncSessionLocal() as db:
        return await db.get(Candidate, candidate_id)


async def test_batch_result_lands_in_the_profile(wired):
    candidate_id, document_id, digest = await _seed()
    try:
        item_id = await _queue(candidate_id, document_id, digest)
        async with AsyncSessionLocal() as db:
            assert await cv_parse_batch.queued_since(db, candidate_id) is not None
        client, batches = _client()

        await cv_parse_batch.run_tick(client)
        item = await _item(item_id)
        assert item.status == "submitted"
        [requests] = batches.created
        assert [r["custom_id"] for r in requests] == [f"cvp-{item_id}"]
        # To samo żądanie co odczyt na żywo, po translacji dla paczki.
        assert requests[0]["params"] == batch_request_params(
            claude_cv_request_params(CV_TEXT, model=cv_parse_batch.batch_model())
        )

        # Paczka w toku: nic się nie dzieje, CV dalej czeka.
        await cv_parse_batch.run_tick(client)
        assert (await _item(item_id)).status == "submitted"

        batches.status = "ended"
        batches.results_by_batch[item.batch_id] = [
            _succeeded(f"cvp-{item_id}", _parsed("Batch Developer"))
        ]
        await cv_parse_batch.run_tick(client)

        item = await _item(item_id)
        assert item.status == "done"
        assert item.raw_text is None
        assert item.finished_at is not None
        candidate = await _candidate(candidate_id)
        assert candidate.raw_cv_text == CV_TEXT
        assert candidate.cv_parsed_at is not None
        assert (candidate.cv_extracted_data or {}).get("current_position") == (
            "Batch Developer"
        )
        assert wired == []  # żadnego odczytu na żywo
        async with AsyncSessionLocal() as db:
            assert await cv_parse_batch.queued_since(db, candidate_id) is None
    finally:
        await _cleanup(candidate_id)


async def test_batch_create_failure_reads_live(wired):
    candidate_id, document_id, digest = await _seed()
    try:
        item_id = await _queue(candidate_id, document_id, digest)
        client, batches = _client()
        batches.fail_create = RuntimeError("503")

        stats = await cv_parse_batch.run_tick(client)

        assert stats.live == 1
        item = await _item(item_id)
        assert item.status == "live"
        assert item.error == "batch_create_failed:RuntimeError"
        assert item.raw_text is None
        assert wired == [CV_TEXT]
        candidate = await _candidate(candidate_id)
        assert (candidate.cv_extracted_data or {}).get("current_position") == (
            "Live Developer"
        )
    finally:
        await _cleanup(candidate_id)


async def test_no_result_after_the_limit_reads_live_and_cancels(wired):
    candidate_id, document_id, digest = await _seed()
    try:
        item_id = await _queue(candidate_id, document_id, digest)
        client, batches = _client()
        await cv_parse_batch.run_tick(client)
        batch_id = (await _item(item_id)).batch_id
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(CvParseBatchItem)
                .where(CvParseBatchItem.id == item_id)
                .values(queued_at=datetime.now(timezone.utc) - timedelta(hours=7))
            )
            await db.commit()

        stats = await cv_parse_batch.run_tick(client)

        assert stats.timed_out == 1
        assert batches.cancelled == [batch_id]
        item = await _item(item_id)
        assert item.status == "live"
        assert item.error == "timeout"
        assert wired == [CV_TEXT]

        # Wynik spóźnionej paczki nie zapisuje się drugi raz.
        batches.status = "ended"
        batches.results_by_batch[batch_id] = [
            _succeeded(f"cvp-{item_id}", _parsed("Batch Developer"))
        ]
        await cv_parse_batch.run_tick(client)
        candidate = await _candidate(candidate_id)
        assert (candidate.cv_extracted_data or {}).get("current_position") == (
            "Live Developer"
        )
    finally:
        await _cleanup(candidate_id)


async def test_newer_cv_closes_the_older_one_in_the_queue(wired):
    candidate_id, document_id, digest = await _seed()
    try:
        first = await _queue(candidate_id, document_id, digest)
        second = await _queue(candidate_id, document_id, digest)
        assert (await _item(first)).status == "superseded"
        assert (await _item(first)).raw_text is None
        assert (await _item(second)).status == "queued"
    finally:
        await _cleanup(candidate_id)


async def test_result_for_a_replaced_file_writes_nothing(wired):
    candidate_id, document_id, digest = await _seed()
    try:
        item_id = await _queue(candidate_id, document_id, digest)
        client, batches = _client()
        await cv_parse_batch.run_tick(client)
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(CandidateDocument)
                .where(CandidateDocument.id == document_id)
                .values(is_primary=False)
            )
            await db.commit()
        batches.status = "ended"
        batches.results_by_batch[(await _item(item_id)).batch_id] = [
            _succeeded(f"cvp-{item_id}", _parsed("Batch Developer"))
        ]
        await cv_parse_batch.run_tick(client)

        item = await _item(item_id)
        assert (item.status, item.error) == ("done", "not_applied")
        assert (await _candidate(candidate_id)).cv_parsed_at is None
        assert wired == []
    finally:
        await _cleanup(candidate_id)


async def _upload(client: AsyncClient, headers: dict, candidate_id: int):
    return await client.post(
        f"/api/candidates/{candidate_id}/cv",
        headers=headers,
        files={
            "file": ("cv.pdf", b"%PDF-1.4 " + uuid.uuid4().bytes, "application/pdf")
        },
    )


async def test_integration_upload_waits_in_the_queue(
    app_client: AsyncClient, app_auth_headers: dict, wired, monkeypatch
):
    from app.services import candidate_claim

    monkeypatch.setattr(candidate_claim, "is_integration_request", lambda _r: True)
    candidate_id, _document_id, _digest = await _seed()
    try:
        resp = await _upload(app_client, app_auth_headers, candidate_id)
        assert resp.status_code == 200, resp.text
        assert wired == []  # bez odczytu na żywo
        async with AsyncSessionLocal() as db:
            items = (
                await db.scalars(
                    select(CvParseBatchItem).where(
                        CvParseBatchItem.candidate_id == candidate_id
                    )
                )
            ).all()
        assert [i.status for i in items] == ["queued"]
        assert items[0].raw_text == CV_TEXT

        detail = await app_client.get(
            f"/api/candidates/{candidate_id}", headers=app_auth_headers
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["cv_read_queued_at"] is not None
    finally:
        await _cleanup(candidate_id)


async def test_human_upload_still_reads_live(
    app_client: AsyncClient, app_auth_headers: dict, wired
):
    candidate_id, _document_id, _digest = await _seed()
    try:
        resp = await _upload(app_client, app_auth_headers, candidate_id)
        assert resp.status_code == 200, resp.text
        assert wired == [CV_TEXT]
        async with AsyncSessionLocal() as db:
            queued = await db.scalar(
                select(CvParseBatchItem.id).where(
                    CvParseBatchItem.candidate_id == candidate_id
                )
            )
        assert queued is None
        detail = await app_client.get(
            f"/api/candidates/{candidate_id}", headers=app_auth_headers
        )
        assert detail.json()["cv_read_queued_at"] is None
    finally:
        await _cleanup(candidate_id)
