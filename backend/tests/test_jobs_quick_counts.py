"""Liczniki filtrów „Szybkie" listy rekrutacji (`GET /api/jobs/quick-counts`).

Sens tego pliku jest jeden: **licznik przy filtrze i lista, którą ten filtr
zwraca, muszą odpowiadać na to samo pytanie**. Dlatego testy nie sprawdzają
wpisanych na sztywno liczb — porównują każdy licznik z ``total`` odpowiedzi
``GET /api/jobs`` z tym samym filtrem. Asercja na stałą przeszłaby także wtedy,
gdyby OBA predykaty rozjechały się w tę samą stronę.

Rejestr jest ogólnofirmowy, więc w bazie testowej żyją też rekrutacje z innych
plików. Porównanie licznik ↔ ``total`` jest na to odporne: obie liczby są
globalne i liczone tym samym predykatem.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from app.core.scheduling import business_today


async def _seed_client() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        c = Client(name=f"QuickCntClient-{uuid.uuid4().hex[:6]}")
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_job(
    *,
    status: str = "published",
    recruiter_id: int | None = None,
    tac_id: int | None = None,
    needs_sourcing: bool = False,
    deadline: date | None = None,
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job, JobStatus

    client_id = await _seed_client()
    async with AsyncSessionLocal() as db:
        j = Job(
            title=f"QuickCnt-{uuid.uuid4().hex[:6]}",
            status=JobStatus(status),
            recruiter_id=recruiter_id,
            tac_id=tac_id,
            needs_sourcing=needs_sourcing,
            deadline=deadline,
            client_id=client_id,
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id


async def _add_collaborator(
    job_id: int, user_id: int, *, removed: bool = False
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.job_collaborator import JobCollaborator

    async with AsyncSessionLocal() as db:
        db.add(
            JobCollaborator(
                job_id=job_id,
                user_id=user_id,
                added_by=user_id,
                removed_from_auto_cc=removed,
            )
        )
        await db.commit()


async def _cleanup(job_ids: list[int]) -> None:
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        for jid in job_ids:
            await db.execute(delete(Job).where(Job.id == jid))
        await db.commit()


async def _me_id(app_client: AsyncClient, headers: dict) -> int:
    response = await app_client.get("/api/auth/me", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _list_total(app_client: AsyncClient, headers: dict, query: str) -> int:
    response = await app_client.get(f"/api/jobs?page_size=1&{query}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["total"]


async def _quick_counts(
    app_client: AsyncClient, headers: dict, query: str = ""
) -> dict:
    suffix = f"?{query}" if query else ""
    response = await app_client.get(f"/api/jobs/quick-counts{suffix}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_quick_counts_agree_with_the_list_the_same_filter_returns(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Każdy z sześciu liczników == ``total`` listy z tym samym filtrem.

    To jest cały kontrakt tego endpointu. Rozjazd oznacza, że kliknięcie
    filtra pokaże inną liczbę wierszy niż liczba wypisana obok jego nazwy —
    a obie będą wyglądać na poprawne.
    """
    me = await _me_id(app_client, app_auth_headers)
    today = business_today()
    window_to = today + timedelta(days=7)

    job_ids = [
        # „Moje projekty" — raz jako właściciel, raz jako współpracownik.
        await _seed_job(recruiter_id=me, tac_id=me),
        await _seed_job(needs_sourcing=True),
        await _seed_job(status="closed"),
        await _seed_job(status="draft", tac_id=None),
        await _seed_job(deadline=today + timedelta(days=3), tac_id=me),
        # Poza oknem „≤ 7 dni" — pilnuje, że górna granica naprawdę odcina.
        await _seed_job(deadline=today + timedelta(days=40), tac_id=me),
    ]
    await _add_collaborator(job_ids[1], me)
    try:
        window = (
            f"deadline_from={today.isoformat()}&deadline_to={window_to.isoformat()}"
        )
        counts = await _quick_counts(app_client, app_auth_headers, window)

        expected = {
            # Segment „Wszystkie" obok „Moje" — cały rejestr, bez filtra.
            "all": await _list_total(app_client, app_auth_headers, ""),
            "mine": await _list_total(app_client, app_auth_headers, "mine=true"),
            "open": await _list_total(app_client, app_auth_headers, "open_only=true"),
            "needs_sourcing": await _list_total(
                app_client, app_auth_headers, "needs_sourcing=true"
            ),
            "active_in_search": await _list_total(
                app_client, app_auth_headers, "active_in_search=true"
            ),
            "owner_missing": await _list_total(
                app_client, app_auth_headers, "owner_missing=true"
            ),
            "deadline_7d": await _list_total(app_client, app_auth_headers, window),
        }

        # Liczniki statusu requestu mają własny test (niżej), a stanu requestu
        # i przełączników paska — `test_jobs_list_stage_and_workers.py`.
        flat = {
            key: value
            for key, value in counts.items()
            if key
            not in (
                "request_status",
                "request_status_mine",
                "request_stage",
                "request_stage_mine",
                "attention",
                "attention_mine",
            )
        }
        assert flat == expected
        # Sanity: zasiane wiersze naprawdę weszły w te zbiory, więc test nie
        # przechodzi przez porównanie sześciu zer.
        assert counts["mine"] >= 2
        assert counts["needs_sourcing"] >= 1
        assert counts["owner_missing"] >= 1
        assert counts["deadline_7d"] >= 1
    finally:
        await _cleanup(job_ids)


@pytest.mark.asyncio
async def test_owner_missing_narrows_the_list_in_both_directions(
    app_client: AsyncClient, app_auth_headers: dict
):
    """``owner_missing`` filtruje po ``tac_id``, nie po właścicielu prowadzącym.

    Do 09.2026 ten filtr żył wyłącznie w przeglądarce i zawężał już wczytaną
    stronę; „63" znaczyło „63 na dwudziestu widocznych wierszach".
    """
    me = await _me_id(app_client, app_auth_headers)
    without_owner = await _seed_job(recruiter_id=me, tac_id=None)
    with_owner = await _seed_job(recruiter_id=me, tac_id=me)
    try:
        response = await app_client.get(
            "/api/jobs?owner_missing=true&page_size=100&mine=true",
            headers=app_auth_headers,
        )
        assert response.status_code == 200, response.text
        ids = {row["id"] for row in response.json()["items"]}
        assert without_owner in ids
        assert with_owner not in ids

        response = await app_client.get(
            "/api/jobs?owner_missing=false&page_size=100&mine=true",
            headers=app_auth_headers,
        )
        assert response.status_code == 200, response.text
        ids = {row["id"] for row in response.json()["items"]}
        assert with_owner in ids
        assert without_owner not in ids
    finally:
        await _cleanup([without_owner, with_owner])


@pytest.mark.asyncio
async def test_deadline_window_defaults_to_the_next_seven_days(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Bez parametrów okno to [dziś, dziś + 7] — lustro presetu „next7" w UI."""
    today = business_today()
    inside = await _seed_job(deadline=today + timedelta(days=2))
    outside = await _seed_job(deadline=today + timedelta(days=30))
    try:
        default_counts = await _quick_counts(app_client, app_auth_headers)
        explicit_counts = await _quick_counts(
            app_client,
            app_auth_headers,
            f"deadline_from={today.isoformat()}"
            f"&deadline_to={(today + timedelta(days=7)).isoformat()}",
        )
        assert default_counts["deadline_7d"] == explicit_counts["deadline_7d"]

        # Wiersz spoza okna nie może podbijać licznika — inaczej „≤ 7 dni"
        # znaczyłoby „ma jakikolwiek termin".
        narrow = await _quick_counts(
            app_client,
            app_auth_headers,
            f"deadline_from={today.isoformat()}&deadline_to={today.isoformat()}",
        )
        assert narrow["deadline_7d"] < default_counts["deadline_7d"]
    finally:
        await _cleanup([inside, outside])


@pytest.mark.asyncio
async def test_quick_counts_route_is_not_swallowed_by_the_job_id_path(
    app_client: AsyncClient, app_auth_headers: dict
):
    """„quick-counts" nie może trafić do ``GET /{job_id}``.

    Kolejność deklaracji tras w FastAPI jest tu jedyną obroną: zarejestrowana
    po ``/{job_id}`` ścieżka literalna nigdy by się nie dopasowała, a objawem
    byłoby 422 o niepoprawnym ``job_id`` zamiast liczników.
    """
    response = await app_client.get("/api/jobs/quick-counts", headers=app_auth_headers)
    assert response.status_code == 200, response.text
    assert set(response.json()) == {
        "all",
        "mine",
        "open",
        "needs_sourcing",
        "active_in_search",
        "owner_missing",
        "deadline_7d",
        "request_status",
        "request_status_mine",
        "request_stage",
        "request_stage_mine",
        "attention",
        "attention_mine",
    }


@pytest.mark.asyncio
async def test_request_status_counts_agree_with_the_status_filter(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Liczba przy pigułce statusu == ``total`` listy z ``request_status``.

    Oba liczą się tym samym wyrażeniem (``request_status_expr``); licznik
    „moich" == lista z ``mine=true`` i tym samym statusem.
    """
    from app.services.job_similarity import REQUEST_STATUSES

    me = await _me_id(app_client, app_auth_headers)
    job_ids = [
        await _seed_job(status="draft", recruiter_id=me),
        await _seed_job(status="closed"),
        await _seed_job(recruiter_id=me),
    ]
    try:
        counts = await _quick_counts(app_client, app_auth_headers)
        assert set(counts["request_status"]) == set(REQUEST_STATUSES)
        assert set(counts["request_status_mine"]) == set(REQUEST_STATUSES)
        for value in REQUEST_STATUSES:
            assert counts["request_status"][value] == await _list_total(
                app_client, app_auth_headers, f"request_status={value}"
            ), value
            assert counts["request_status_mine"][value] == await _list_total(
                app_client, app_auth_headers, f"request_status={value}&mine=true"
            ), value
        # Suma po statusach = cały rejestr (każda rekrutacja ma dokładnie jeden).
        assert sum(counts["request_status"].values()) == counts["all"]
        assert sum(counts["request_status_mine"].values()) == counts["mine"]
        assert counts["request_status"]["incomplete"] >= 1
        assert counts["request_status_mine"]["searching"] >= 1
    finally:
        await _cleanup(job_ids)


@pytest.mark.asyncio
async def test_request_status_subquery_skips_closed_jobs(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch: pytest.MonkeyPatch
):
    """Ostatnie etapy par liczymy tylko dla rekrutacji niezamkniętych.

    Audyt 24.09.2026: ``request_status_subquery`` przeliczał ``DISTINCT ON``
    po ``candidate_stages`` CAŁEGO rejestru (~4,3 tys. rekrutacji, w tym
    zamknięte z Traffita) przy każdym wejściu na ``/jobs``. Status „closed”
    wynika z samego ``jobs.status`` (pierwsza gałąź ``request_status_expr``),
    więc zamknięte nie potrzebują podzapytania — liczby się nie zmieniają
    (pilnuje tego test wyżej).
    """
    from sqlalchemy.dialects import postgresql

    from app.services import job_similarity

    captured: list = []
    original = job_similarity.request_status_subquery

    def spy(job_ids):
        captured.append(job_ids)
        return original(job_ids)

    monkeypatch.setattr(job_similarity, "request_status_subquery", spy)
    closed_id = await _seed_job(status="closed")
    try:
        counts = await _quick_counts(app_client, app_auth_headers)
        assert counts["request_status"]["closed"] >= 1
        assert captured, "quick-counts nie policzył statusów requestu"
        compiled = captured[-1].compile(dialect=postgresql.dialect())
        sql = str(compiled)
        assert "jobs.status !=" in sql or "jobs.status <>" in sql, sql
        values = {str(getattr(v, "value", v)) for v in compiled.params.values()}
        assert "closed" in values, compiled.params
    finally:
        await _cleanup([closed_id])
