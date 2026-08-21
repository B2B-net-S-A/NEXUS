"""Cztery endpointy, które ciągnęły do pamięci procesu więcej, niż wypisywały.

Wspólny wzorzec defektu: pętla `for x in rows: await db.scalar(...)` albo
`select(Model)` bez limitu i bez projekcji. Każdy z nich przechodził recenzje,
bo odpowiedź jest POPRAWNA — kosztuje tylko tyle, ile nie widać w teście
sprawdzającym samą treść. Dlatego te testy patrzą na WYKONANY SQL i na liczbę
round-tripów, a nie na kształt JSON-a:

* ``GET /api/fireflies/status``      — liczba w kafelku liczona przez `count()`,
  a nie przez wciągnięcie wszystkich transkryptów (`Note.content` = Text).
* ``GET /api/clients/{id}/orders``   — dwa SELECT-y na KAŻDE zamówienie znikają;
  kandydat i rekrutacja przychodzą z `selectinload`.
* ``GET /api/calendar/events``       — trzy SELECT-y na KAŻDE wydarzenie znikają;
  dochodzi twardy sufit odpowiedzi i realny sens `upcoming`.
* ``GET /api/export/candidates``     — projekcja 14 kolumn + strumień zamiast
  ~49 tys. pełnych wierszy ORM (z `raw_cv_text`) w RAM-ie.

Prawdziwy Postgres (in-process ``app_client``), bo dowód ma przechodzić przez
tę samą warstwę, która była zepsuta — zliczanie zapytań na atrapie sesji
mierzyłoby atrapę.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import event

from app.core.database import AsyncSessionLocal, engine
from app.core.security import hash_password
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus
from app.models.job import Job, JobStatus
from app.models.note import Note, NoteType
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio


# ── Podsłuch SQL ────────────────────────────────────────────────────────────


@contextmanager
def capture_sql():
    """Zbiera surowy SQL wysłany do sterownika w obrębie bloku.

    Podpięcie idzie na `engine.sync_engine`, bo `before_cursor_execute` jest
    zdarzeniem warstwy Core — wersja async tylko ją opakowuje. Fixture
    ``app_client`` nie odpala lifespanu, więc w tle nie kręcą się pętle zadań,
    które dosypywałyby cudzych zapytań do licznika.
    """
    seen: list[str] = []

    def _on(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _on)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _on)


def _selects_from(statements: list[str], table: str) -> list[str]:
    """SELECT-y, których źródłem (FROM/JOIN) jest dana tabela."""
    pattern = re.compile(rf"\b(?:FROM|JOIN)\s+{table}\b", re.IGNORECASE)
    return [
        s
        for s in statements
        if s.lstrip().upper().startswith("SELECT") and pattern.search(s)
    ]


# ── Seedy ───────────────────────────────────────────────────────────────────


async def _seed_user(role: UserRole, tag: str) -> tuple[int, str, str]:
    suffix = uuid.uuid4().hex[:8]
    email = f"qbudget-{tag}-{suffix}@example.com"
    password = f"QBud_{suffix}!Pw"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name=f"{tag} {suffix}",
            role=role,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id, email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    r = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ── /api/fireflies/status ───────────────────────────────────────────────────


async def test_fireflies_status_counts_notes_in_the_database(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Kafelek dostaje liczbę z `count()`, a nie z długości wciągniętej listy.

    Poprzednia wersja robiła `select(Note)` bez limitu i `len(...all())`, więc
    żeby pokazać jedną liczbę, przeciągała przez sieć komplet transkryptów
    spotkań (`Note.content` to Text).
    """
    marker = uuid.uuid4().hex
    async with AsyncSessionLocal() as db:
        db.add(
            Note(
                content=f"# Spotkanie {marker}\n" + ("x" * 500),
                note_type=NoteType.meeting,
                source_ref=f"qbudget:{marker}",
            )
        )
        await db.commit()

    try:
        with capture_sql() as statements:
            resp = await app_client.get(
                "/api/fireflies/status", headers=app_auth_headers
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["transcript_count"] >= 1

        note_selects = _selects_from(statements, "notes")
        assert note_selects, "endpoint w ogóle nie odpytał tabeli notes"
        assert all("count(" in s.lower() for s in note_selects), note_selects
        # Treść notatki nie ma prawa opuścić bazy dla licznika w kafelku.
        assert not any("notes.content" in s for s in note_selects), note_selects
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                Note.__table__.delete().where(Note.source_ref == f"qbudget:{marker}")
            )
            await db.commit()


# ── /api/clients/{id}/orders ────────────────────────────────────────────────


async def _seed_client_with_orders(order_count: int) -> tuple[int, int, int, int]:
    """Klient + kandydat + kontrakt + N zamówień, każde z własną rekrutacją."""
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"QBudget Client {suffix}")
        cand = Candidate(name=f"QBudget {suffix}", lastname=f"Tester{suffix}")
        db.add_all([client, cand])
        await db.flush()
        job = Job(
            title=f"QBudget Job {suffix}",
            status=JobStatus.published,
            client_id=client.id,
        )
        db.add(job)
        await db.flush()
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            start_date=date.today() - timedelta(days=30),
            rate_client=15000,
            rate_candidate=12000,
            status=ContractStatus.active,
        )
        db.add(contract)
        await db.flush()
        for i in range(order_count):
            db.add(
                ClientOrder(
                    client_id=client.id,
                    contract_id=contract.id,
                    job_id=job.id,
                    title=f"Zamówienie {i} {suffix}",
                    status=ClientOrderStatus.active,
                    start_date=date.today() - timedelta(days=30 * (i + 1)),
                )
            )
        await db.commit()
        return client.id, cand.id, contract.id, job.id


async def _cleanup_client(client_id: int, cand_id: int, job_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            ClientOrder.__table__.delete().where(ClientOrder.client_id == client_id)
        )
        await db.execute(
            Contract.__table__.delete().where(Contract.client_id == client_id)
        )
        await db.execute(Job.__table__.delete().where(Job.id == job_id))
        await db.execute(Client.__table__.delete().where(Client.id == client_id))
        await db.execute(Candidate.__table__.delete().where(Candidate.id == cand_id))
        await db.commit()


async def test_orders_list_does_not_query_once_per_order(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Lista zamówień nie skaluje liczby zapytań liczbą zamówień.

    ``_order_to_read`` dopytywał kandydata i rekrutację dla KAŻDEGO wiersza,
    mimo że zewnętrzne zapytanie miało już te dane z `selectinload`. Klient z
    30 kontraktorami po 5 zamówień płacił ~300 round-tripów za dane leżące
    obok, w pamięci.
    """
    order_count = 5
    client_id, cand_id, _contract_id, job_id = await _seed_client_with_orders(
        order_count
    )
    try:
        with capture_sql() as statements:
            resp = await app_client.get(
                f"/api/clients/{client_id}/orders", headers=app_auth_headers
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        orders = body["contractors"][0]["orders"]
        assert len(orders) == order_count
        # Pola, za które płaciliśmy dwoma zapytaniami na wiersz, nadal są
        # wypełnione — to nie jest fix „przez usunięcie danych".
        assert all(o["candidate_name"] for o in orders)
        assert all(o["job_title"] for o in orders)

        cand_selects = _selects_from(statements, "candidates")
        job_selects = _selects_from(statements, "jobs")
        # `selectin` to JEDNO zapytanie na relację, niezależnie od liczby
        # zamówień. Przed fixem: po jednym na zamówienie (czyli 5 + 5).
        assert len(cand_selects) <= 1, cand_selects
        assert len(job_selects) <= 1, job_selects
    finally:
        await _cleanup_client(client_id, cand_id, job_id)


# ── /api/calendar/events ────────────────────────────────────────────────────


async def _seed_events(
    owner_id: int,
    starts: list[datetime],
    *,
    candidate_id: int | None = None,
    job_id: int | None = None,
    client_id: int | None = None,
) -> list[int]:
    async with AsyncSessionLocal() as db:
        rows = [
            CalendarEvent(
                title=f"QBudget {i}",
                event_type=EventType.interview,
                start_time=start,
                end_time=start + timedelta(hours=1),
                attendees=[],
                created_by=owner_id,
                status=EventStatus.scheduled,
                candidate_id=candidate_id,
                job_id=job_id,
                client_id=client_id,
            )
            for i, start in enumerate(starts)
        ]
        db.add_all(rows)
        await db.commit()
        return [r.id for r in rows]


async def _cleanup_events(event_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            CalendarEvent.__table__.delete().where(CalendarEvent.id.in_(event_ids))
        )
        await db.commit()


async def test_calendar_list_does_not_query_once_per_event(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Nazwy kandydata/rekrutacji/klienta idą jednym `IN`-em na całą stronę.

    Przed fixem każde wydarzenie kosztowało trzy osobne SELECT-y, a że
    endpoint nie miał limitu ani domyślnego okna dat, konto widzące wszystko
    (admin / head_of_recruitment) generowało ich tysiące.
    """
    owner_id, email, password = await _seed_user(UserRole.recruiter, "cal-n1")
    headers = await _login(app_client, email, password)
    client_id, cand_id, _contract_id, job_id = await _seed_client_with_orders(1)

    base = datetime(2033, 4, 11, 9, 0, tzinfo=timezone.utc)
    event_ids = await _seed_events(
        owner_id,
        [base + timedelta(hours=i) for i in range(6)],
        candidate_id=cand_id,
        job_id=job_id,
        client_id=client_id,
    )
    try:
        with capture_sql() as statements:
            resp = await app_client.get(
                "/api/calendar/events",
                params={
                    "from_date": base.isoformat(),
                    "to_date": (base + timedelta(days=1)).isoformat(),
                },
                headers=headers,
            )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert len(payload) == len(event_ids)
        # Wzbogacenie nadal działa — inaczej „mniej zapytań" znaczyłoby
        # „mniej danych".
        assert all(ev["candidate_name"] for ev in payload)
        assert all(ev["job_title"] for ev in payload)
        assert all(ev["client_name"] for ev in payload)

        assert len(_selects_from(statements, "candidates")) <= 1
        assert len(_selects_from(statements, "jobs")) <= 1
        assert len(_selects_from(statements, "clients")) <= 1
    finally:
        await _cleanup_events(event_ids)
        await _cleanup_client(client_id, cand_id, job_id)


async def test_calendar_list_has_a_hard_ceiling(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Odpowiedź jest ograniczona i nie da się poprosić o więcej niż sufit."""
    owner_id, email, password = await _seed_user(UserRole.recruiter, "cal-cap")
    headers = await _login(app_client, email, password)
    base = datetime(2033, 5, 11, 9, 0, tzinfo=timezone.utc)
    event_ids = await _seed_events(
        owner_id, [base + timedelta(hours=i) for i in range(4)]
    )
    try:
        resp = await app_client.get(
            "/api/calendar/events", params={"limit": 2}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        assert len(resp.json()) == 2

        over = await app_client.get(
            "/api/calendar/events", params={"limit": 100_000}, headers=headers
        )
        assert over.status_code == 422, over.text

        # Brak `limit` = sufit, a nie „bez ograniczeń": zapytanie idzie z LIMIT-em.
        with capture_sql() as statements:
            plain = await app_client.get("/api/calendar/events", headers=headers)
        assert plain.status_code == 200, plain.text
        event_selects = _selects_from(statements, "calendar_events")
        assert event_selects, statements
        assert all("LIMIT" in s.upper() for s in event_selects), event_selects
    finally:
        await _cleanup_events(event_ids)


async def test_calendar_upcoming_returns_the_nearest_events_not_the_oldest(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """`upcoming` i `start_from` nie są już po cichu ignorowane.

    FastAPI odrzucał nieznane parametry zapytania w milczeniu, więc wołający
    proszący o „5 najbliższych" dostawał 5 NAJSTARSZYCH wydarzeń w bazie —
    posortowanych rosnąco od początku historii.
    """
    owner_id, email, password = await _seed_user(UserRole.recruiter, "cal-up")
    headers = await _login(app_client, email, password)
    now = datetime.now(timezone.utc)
    past = [now - timedelta(days=400), now - timedelta(days=200)]
    future = [now + timedelta(days=30), now + timedelta(days=60)]
    event_ids = await _seed_events(owner_id, past + future)
    try:
        without = await app_client.get("/api/calendar/events", headers=headers)
        assert without.status_code == 200, without.text
        assert len(without.json()) == 4, "domyślne zachowanie ma zostać bez zmian"

        resp = await app_client.get(
            "/api/calendar/events",
            params={"upcoming": True, "limit": 1},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["id"] == event_ids[2], "zwrócono nie-najbliższe wydarzenie"

        explicit = await app_client.get(
            "/api/calendar/events",
            params={"start_from": (now + timedelta(days=45)).isoformat()},
            headers=headers,
        )
        assert explicit.status_code == 200, explicit.text
        assert [r["id"] for r in explicit.json()] == [event_ids[3]]
    finally:
        await _cleanup_events(event_ids)


# ── /api/export/candidates ──────────────────────────────────────────────────


async def test_candidate_export_projects_columns_and_streams(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Eksport pobiera 14 kolumn, które wypisuje — nie całe wiersze ORM.

    ``select(Candidate)`` bez projekcji i bez limitu ładowało ~49 tys. pełnych
    kandydatów (z `raw_cv_text` i JSONB-ami profilu) do pamięci procesu. Przy
    `mem_limit` kontenera realne było ubicie backendu, a wtedy 502 dostają
    WSZYSCY zalogowani, nie tylko eksportujący.
    """
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=f"Export{suffix}",
            lastname=f"Budget{suffix}",
            email=f"export-{suffix}@example.com",
            raw_cv_text="ŻYCIORYS " * 200,
        )
        db.add(cand)
        await db.commit()
        cand_id = cand.id

    try:
        with capture_sql() as statements:
            resp = await app_client.get(
                "/api/export/candidates", headers=app_auth_headers
            )
            body = resp.content
        assert resp.status_code == 200, resp.text

        cand_selects = _selects_from(statements, "candidates")
        assert cand_selects, statements
        # Kolumny, których CSV nie ma, nie mają po co jechać przez sieć.
        assert not any("raw_cv_text" in s for s in cand_selects), cand_selects

        text = body.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text))
        header = next(reader)
        assert header[:4] == ["id", "name", "lastname", "email"]
        assert f"Export{suffix}" in text
        # Strumień: rozmiaru nie znamy z góry, więc nagłówka Content-Length
        # nie ma. Zgadnięty ucinałby plik.
        assert "content-length" not in {k.lower() for k in resp.headers}
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                Candidate.__table__.delete().where(Candidate.id == cand_id)
            )
            await db.commit()
