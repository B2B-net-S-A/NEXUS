"""Liczba z żądania większa niż kolumna bazy: odmowa 422, nie 500.

Python przyjmuje dowolnie duży ``int``, a kolumny identyfikatorów to int4.
asyncpg nie umie zakodować takiego parametru (``OverflowError`` → ``DataError``
→ ``DBAPIError``), więc ``/api/…/99999999999`` albo ``{"job_id": 99999999999}``
kończyło się 500 i zdarzeniem w Sentry. Do 02.10.2026 łatano to trasa po trasie
(cztery różne stałe w ``jobs``, ``candidates``, ``clients``, ``contracts``);
ciała żądań i większość tras zostały bez granicy.

Trzy poziomy:

1. rozpoznanie wyjątku — bez bazy,
2. siatka błędów aplikacji (``UnhandledErrorMiddleware``) — bez bazy,
3. trasy przez ``app_client``: ciało, ścieżka i parametr zapytania (baza; CI).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import DBAPIError, IntegrityError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route

from app.core.database import AsyncSessionLocal
from app.core.integer_range import OUT_OF_RANGE, is_integer_out_of_range
from app.main import UnhandledErrorMiddleware

TOO_BIG = 99_999_999_999


# ── 1. Rozpoznanie wyjątku ───────────────────────────────────────────────────


def _driver_error(width: int = 32) -> DBAPIError:
    """Łańcuch jak z asyncpg + SQLAlchemy dla parametru spoza zakresu."""
    overflow = OverflowError(f"value out of int{width} range")
    encode = ValueError(f"invalid input for query argument $1: {TOO_BIG} ({overflow})")
    encode.__cause__ = overflow
    translated = Exception(f"<class 'asyncpg.exceptions.DataError'>: {encode}")
    translated.__cause__ = encode
    error = DBAPIError("SELECT 1 WHERE id = $1", None, translated)
    error.__cause__ = translated
    return error


@pytest.mark.parametrize("width", [16, 32, 64])
def test_integer_that_does_not_fit_the_column_is_recognised(width: int) -> None:
    assert is_integer_out_of_range(_driver_error(width))


def test_bare_encoder_overflow_is_recognised() -> None:
    assert is_integer_out_of_range(OverflowError("value out of int32 range"))


@pytest.mark.parametrize(
    "error",
    [
        OverflowError("date value out of range"),
        OverflowError("cannot convert float infinity to integer"),
        ValueError("value out of int32 range"),
        DBAPIError("SELECT 1", None, Exception("connection is closed")),
        IntegrityError("INSERT", None, Exception("duplicate key value")),
        RuntimeError("boom"),
    ],
)
def test_other_errors_stay_server_errors(error: BaseException) -> None:
    assert not is_integer_out_of_range(error)


def test_an_error_handled_on_the_way_does_not_count() -> None:
    """``__context__`` to błąd obsłużony wcześniej — nie przyczyna tego."""
    try:
        try:
            raise OverflowError("value out of int32 range")
        except OverflowError:
            raise RuntimeError("inna awaria")  # noqa: B904 - celowo bez `from`
    except RuntimeError as error:
        assert not is_integer_out_of_range(error)


def test_a_cycle_in_the_chain_ends() -> None:
    first, second = RuntimeError("a"), RuntimeError("b")
    first.__cause__, second.__cause__ = second, first
    assert not is_integer_out_of_range(first)


# ── 2. Siatka błędów aplikacji ───────────────────────────────────────────────


async def _raises(request: Request):
    if request.query_params.get("kind") == "range":
        raise _driver_error()
    raise RuntimeError("boom")


def _mini_app() -> Starlette:
    app = Starlette(routes=[Route("/x", _raises)])
    app.add_middleware(UnhandledErrorMiddleware)
    return app


async def test_out_of_range_integer_is_a_polish_422_without_the_value() -> None:
    transport = ASGITransport(app=_mini_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/x", params={"kind": "range"})
    assert resp.status_code == 422, resp.text
    assert resp.json() == {"detail": OUT_OF_RANGE}
    assert str(TOO_BIG) not in resp.text


async def test_out_of_range_integer_is_not_reported_as_a_server_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sentry_sdk

    captured: list[BaseException] = []
    monkeypatch.setattr(sentry_sdk, "capture_exception", captured.append)
    transport = ASGITransport(app=_mini_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/x", params={"kind": "range"})
        assert captured == []
        other = await client.get("/x")
    assert other.status_code == 500
    assert len(captured) == 1


# ── 3. Trasy (baza) ──────────────────────────────────────────────────────────


def _refused(resp) -> None:
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == OUT_OF_RANGE


async def _seed_note_and_job() -> tuple[int, int]:
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.note import Note, NoteType

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Zakres Demo {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Zakres {tag}", status=JobStatus.published, client_id=client.id
        )
        note = Note(content="# Spotkanie\nTreść.", note_type=NoteType.meeting)
        db.add_all([job, note])
        await db.commit()
        return note.id, job.id


async def test_id_in_the_body_beyond_the_column_is_refused(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from app.models.note import Note
    from app.models.recruitment_pipeline import CandidateStage
    from sqlalchemy import func, select

    note_id, job_id = await _seed_note_and_job()

    _refused(
        await app_client.post(
            f"/api/notes/{note_id}/link-job",
            headers=app_auth_headers,
            json={"job_id": TOO_BIG},
        )
    )
    _refused(
        await app_client.post(
            f"/api/jobs/{job_id}/candidates",
            headers=app_auth_headers,
            json={"candidate_id": TOO_BIG},
        )
    )

    async with AsyncSessionLocal() as db:
        assert (await db.get(Note, note_id)).job_id is None
        stages = await db.scalar(
            select(func.count())
            .select_from(CandidateStage)
            .where(CandidateStage.job_id == job_id)
        )
    assert stages == 0


async def test_id_in_the_path_or_query_beyond_the_column_is_refused(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    _, job_id = await _seed_note_and_job()

    _refused(
        await app_client.post(
            f"/api/notes/{TOO_BIG}/link-job",
            headers=app_auth_headers,
            json={"job_id": job_id},
        )
    )
    _refused(
        await app_client.get(
            "/api/notes", headers=app_auth_headers, params={"candidate_id": TOO_BIG}
        )
    )


async def test_the_next_request_works_after_a_refusal(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Odmowa nie zostawia zepsutego połączenia w puli."""
    _, job_id = await _seed_note_and_job()
    for _ in range(3):
        _refused(
            await app_client.get(
                "/api/notes", headers=app_auth_headers, params={"job_id": TOO_BIG}
            )
        )
    ok = await app_client.get(
        "/api/notes", headers=app_auth_headers, params={"job_id": job_id}
    )
    assert ok.status_code == 200, ok.text
