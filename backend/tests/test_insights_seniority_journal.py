"""Dziennik obserwacji poziomu seniority — wykrywanie CICHYCH zmian.

Pod ochroną są własności, których złamanie nie rzuca wyjątkiem i nie widać go
na ekranie — czyli takie, które bez testu wracają cicho:

1. **Pierwsza obserwacja NIE jest awansem ani regresją.** `previous_level`
   musi być NULL, a nie „junior": start od najniższego poziomu zamieniłby
   każde pierwsze uruchomienie dziennika w falę fałszywych awansów.
2. **Brak zmiany = brak wiersza.** Bez tego dziennik rośnie o wiersz na osobę
   na dobę i realna regresja ginie wśród duplikatów. To jest cały powód, dla
   którego ta tabela nadaje się do czytania.
3. **Spadek poziomu jest stemplowany przy ZAPISIE.** Moduł liczący nie
   degraduje poziomu upływem czasu, więc spadek zawsze oznacza przepisaną
   historię atrybucji.
4. **Zmiana liczby placementów bez zmiany poziomu TEŻ jest zdarzeniem.**
   Cofnięta atrybucja, która nie zdążyła zmienić poziomu, jest pierwszym
   sygnałem tego samego problemu — pominięcie jej opóźnia wykrycie do chwili,
   w której ktoś już spadł.
5. **Odzyskany poziom znika z listy otwartych regresji.** Ostrzeżenie, które
   zostaje po naprawie, zamienia się w tło, którego nikt nie czyta.
6. **Odcisk progów jedzie na wierszu** — obniżenie poprzeczki przez operatora
   ma wyglądać inaczej niż cofnięta atrybucja przy tych samych progach.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.insights_seniority import SeniorityThresholds
from app.services.insights_seniority_journal import (
    load_journal_status,
    load_open_regressions,
    record_seniority_observations,
)

# Progi celowo niskie — test bada DZIENNIK, nie wysokość progu. Alternatywne
# nieosiągalne (999), żeby reguła LUB nie podniosła poziomu po cichu i test
# nie przestał mierzyć tego, co opisuje (ta sama decyzja co w teście obok).
LOW = SeniorityThresholds(
    senior_placements=2,
    senior_window_months=12,
    expert_placements=99,
    expert_window_months=12,
    senior_alt_placements=999,
    senior_alt_window_months=24,
    expert_alt_placements=999,
    expert_alt_window_months=24,
)
# Ten sam komplet z INNYM oknem seniora — daje inny `cache_suffix`, czyli inny
# odcisk progów, przy tej samej regule awansu.
LOW_OTHER_FINGERPRINT = SeniorityThresholds(
    senior_placements=2,
    senior_window_months=11,
    expert_placements=99,
    expert_window_months=12,
    senior_alt_placements=999,
    senior_alt_window_months=24,
    expert_alt_placements=999,
    expert_alt_window_months=24,
)

# Rok nieużywany przez żaden inny test (baza jest wspólna dla przebiegu):
#   grep -rhoE "datetime\(20[0-9]{2}|\"20[0-9]{2}-" backend/tests/ | sort -u
SEED_YEAR = 2002


async def _seed_recruiter() -> int:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"snrj-{unique}@example.com",
            name=f"Journal {unique}",
            password_hash=hash_password(f"T3st_{unique}!Jnl"),
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id


async def _seed_placements(user_id: int, months: list[int]) -> list[int]:
    """Jeden placement na miesiąc. Zwraca id wierszy `candidate_stages`."""
    created: list[int] = []
    async with AsyncSessionLocal() as db:
        client_row = Client(name=f"JnlCli-{uuid.uuid4().hex[:6]}")
        db.add(client_row)
        await db.commit()
        await db.refresh(client_row)

        for month in months:
            job = Job(
                title=f"Jnl {uuid.uuid4().hex[:6]}",
                location="Warszawa",
                status=JobStatus.published,
                remote_policy=RemotePolicy.hybrid,
                client_id=client_row.id,
            )
            candidate = Candidate(
                name=f"Jnl-{uuid.uuid4().hex[:4]}",
                lastname=f"Snap-{uuid.uuid4().hex[:4]}",
                email=f"jnl-{uuid.uuid4().hex[:8]}@example.com",
            )
            db.add_all([job, candidate])
            await db.commit()
            await db.refresh(job)
            await db.refresh(candidate)

            stage = CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage.hired,
                # Południe UTC w połowie miesiąca — żaden przelicznik na
                # Europe/Warsaw nie przerzuci tego do sąsiedniego kubełka.
                moved_at=datetime(SEED_YEAR, month, 15, 12, 0, tzinfo=timezone.utc),
                moved_by=user_id,
            )
            db.add(stage)
            await db.commit()
            await db.refresh(stage)
            created.append(stage.id)
    return created


async def _drop_placements(stage_ids: list[int]) -> None:
    """Cofnięcie atrybucji — dokładnie to, co robi przepisany import."""
    if not stage_ids:
        return
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM candidate_stages WHERE id = ANY(:ids)"),
            {"ids": stage_ids},
        )
        await db.commit()


async def _observe(thresholds: SeniorityThresholds = LOW) -> dict:
    async with AsyncSessionLocal() as db:
        return await record_seniority_observations(db, thresholds=thresholds)


async def _rows_for(user_id: int) -> list[dict]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text(
                """
                SELECT level, previous_level, total_placements,
                       previous_total_placements, is_regression,
                       thresholds_fingerprint
                FROM insights_seniority_snapshots
                WHERE user_id = :uid
                ORDER BY observed_at ASC, id ASC
                """
            ),
            {"uid": user_id},
        )
        return [dict(r) for r in result.mappings()]


@pytest.mark.asyncio
async def test_first_observation_is_not_a_promotion() -> None:
    """Pierwszy wiersz ma `previous_level = NULL`, nie „junior".

    Start od najniższego poziomu zamieniłby pierwsze uruchomienie dziennika
    w falę fałszywych awansów dla całego zespołu naraz.
    """
    user_id = await _seed_recruiter()
    await _seed_placements(user_id, [3, 6])

    await _observe()

    rows = await _rows_for(user_id)
    assert len(rows) == 1, rows
    assert rows[0]["level"] == "senior"
    assert rows[0]["previous_level"] is None
    assert rows[0]["previous_total_placements"] is None
    assert rows[0]["is_regression"] is False


@pytest.mark.asyncio
async def test_unchanged_level_writes_nothing() -> None:
    """Drugi przebieg bez zmian NIE dopisuje wiersza.

    To jest cały powód, dla którego ten dziennik nadaje się do czytania:
    wiersz na osobę na dobę utopiłby realną regresję w duplikatach.
    """
    user_id = await _seed_recruiter()
    await _seed_placements(user_id, [4, 5])

    await _observe()
    await _observe()
    await _observe()

    assert len(await _rows_for(user_id)) == 1


@pytest.mark.asyncio
async def test_level_drop_is_stamped_as_regression() -> None:
    """Spadek poziomu = `is_regression`, bo moduł liczący nie degraduje sam."""
    user_id = await _seed_recruiter()
    stage_ids = await _seed_placements(user_id, [2, 8])
    await _observe()

    # Cofnięcie atrybucji: zostaje jeden placement, czyli poniżej progu.
    await _drop_placements(stage_ids[:1])
    await _observe()

    rows = await _rows_for(user_id)
    assert len(rows) == 2, rows
    assert rows[1]["level"] == "junior"
    assert rows[1]["previous_level"] == "senior"
    assert rows[1]["total_placements"] == 1
    assert rows[1]["previous_total_placements"] == 2
    assert rows[1]["is_regression"] is True

    open_regressions = await _load_open(user_id)
    assert open_regressions is not None
    assert open_regressions["previous_level"] == "senior"
    assert open_regressions["level"] == "junior"


async def _load_open(user_id: int) -> dict | None:
    async with AsyncSessionLocal() as db:
        rows = await load_open_regressions(db, limit=200)
    return next((r for r in rows if r["user_id"] == user_id), None)


@pytest.mark.asyncio
async def test_placement_count_change_without_level_change_is_recorded() -> None:
    """Cofnięta atrybucja, która jeszcze nie zmieniła poziomu, TEŻ jest zdarzeniem.

    To pierwszy sygnał tego samego problemu; pominięcie go opóźnia wykrycie
    do chwili, w której ktoś już spadł.
    """
    user_id = await _seed_recruiter()
    stage_ids = await _seed_placements(user_id, [1, 4, 7])
    await _observe()

    # Zostają dwa placementy — nadal senior (próg = 2), ale liczba spadła.
    await _drop_placements(stage_ids[:1])
    await _observe()

    rows = await _rows_for(user_id)
    assert len(rows) == 2, rows
    assert rows[1]["level"] == "senior"
    assert rows[1]["previous_level"] == "senior"
    assert rows[1]["total_placements"] == 2
    assert rows[1]["previous_total_placements"] == 3
    # Poziom się nie zmienił, więc to NIE jest regresja — mimo że liczba spadła.
    assert rows[1]["is_regression"] is False
    assert await _load_open(user_id) is None


@pytest.mark.asyncio
async def test_recovered_level_leaves_the_open_regressions_list() -> None:
    """Po odzyskaniu poziomu ostrzeżenie znika — liczy się OSTATNIA obserwacja."""
    user_id = await _seed_recruiter()
    stage_ids = await _seed_placements(user_id, [2, 9])
    await _observe()

    await _drop_placements(stage_ids[:1])
    await _observe()
    assert await _load_open(user_id) is not None

    # Atrybucja wraca (np. poprawiony import) — poziom znowu senior.
    await _seed_placements(user_id, [11])
    await _observe()

    assert await _load_open(user_id) is None
    rows = await _rows_for(user_id)
    assert [r["level"] for r in rows] == ["senior", "junior", "senior"]


@pytest.mark.asyncio
async def test_threshold_change_is_visible_as_a_different_fingerprint() -> None:
    """Zmiana progu przez operatora ma inny odcisk niż cofnięta atrybucja.

    Bez odcisku obniżenie poprzeczki wygląda w dzienniku identycznie jak
    przepisana historia, czyli dziennik myli decyzję operatora z awarią danych.
    """
    user_id = await _seed_recruiter()
    await _seed_placements(user_id, [3, 10])

    await _observe(LOW)
    await _observe(LOW_OTHER_FINGERPRINT)

    rows = await _rows_for(user_id)
    assert len(rows) == 2, rows
    assert rows[0]["thresholds_fingerprint"] != rows[1]["thresholds_fingerprint"]
    # Poziom bez zmian — sam odcisk wystarczy, żeby zapisać obserwację.
    assert rows[1]["level"] == rows[0]["level"] == "senior"
    assert rows[1]["is_regression"] is False


@pytest_asyncio.fixture
async def jnl_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    _limiter.enabled = True


@pytest.mark.asyncio
async def test_endpoint_reports_journal_freshness(jnl_client: AsyncClient) -> None:
    """Odpowiedź niesie datę OSTATNIEJ obserwacji, nie tylko listę regresji.

    Bez tego `regressions: []` znaczy dwie różne rzeczy naraz: „sprawdzono
    i nikomu nic nie spadło" oraz „pętla dobowa nigdy nic nie zapisała". Front
    renderowałby oba jako ciszę, więc zepsuta pętla w nieskończoność mówiłaby
    „wszystko w porządku".

    Sonda w `/api/health/deep` tego nie zastępuje: sprawdza, że tabela
    ISTNIEJE, a pusta tabela istnieje tak samo dobrze jak zapełniona.
    """
    user_id = await _seed_recruiter()
    await _seed_placements(user_id, [3, 9])
    await _observe()

    async with AsyncSessionLocal() as db:
        status = await load_journal_status(db)
    assert status["last_observed_at"] is not None
    assert status["observations"] >= 1

    unique = uuid.uuid4().hex[:8]
    email = f"jnl-fresh-{unique}@example.com"
    password = f"T3st_{unique}!Jnl"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                name=f"Journal fresh {unique}",
                password_hash=hash_password(password),
                role=UserRole.recruiter,
                is_active=True,
            )
        )
        await db.commit()
    login = await jnl_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text

    resp = await jnl_client.get(
        "/api/insights/recruitment/seniority",
        params={"as_of": date(SEED_YEAR, 12, 31).isoformat()},
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert resp.status_code == 200, resp.text
    journal = resp.json()["journal"]
    assert journal is not None
    assert journal["last_observed_at"] is not None
    assert journal["observations"] >= 1


@pytest.mark.asyncio
async def test_freshness_failure_does_not_discard_regressions(
    jnl_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Padnięte zapytanie o ŚWIEŻOŚĆ nie może wyrzucić regresji, które mamy.

    Podprzypadek z recenzji #1325. Wspólny blok `try` zerował listę regresji,
    gdy padało drugie zapytanie — czyli chował realny spadek poziomu za
    komunikatem „nie wiadomo", mimo że dane były już w ręku.
    """
    from app.api import insights_recruitment as api_module

    user_id = await _seed_recruiter()
    stage_ids = await _seed_placements(user_id, [4, 10])
    await _observe()
    await _drop_placements(stage_ids[:1])
    await _observe()

    async def _boom(_db):
        raise RuntimeError("statement timeout")

    monkeypatch.setattr(api_module, "load_journal_status", _boom, raising=True)

    unique = uuid.uuid4().hex[:8]
    email = f"jnl-fresh-boom-{unique}@example.com"
    password = f"T3st_{unique}!Jnl"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                name=f"Journal fresh boom {unique}",
                password_hash=hash_password(password),
                role=UserRole.recruiter,
                is_active=True,
            )
        )
        await db.commit()
    login = await jnl_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text

    resp = await jnl_client.get(
        "/api/insights/recruitment/seniority",
        params={"as_of": date(SEED_YEAR, 12, 31).isoformat()},
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Świeżość nieznana...
    assert body["journal"] is None
    # ...ale regresja, którą już odczytaliśmy, ZOSTAJE.
    assert body["regressions"] is not None
    mine = next((r for r in body["regressions"] if r["user_id"] == user_id), None)
    assert mine is not None, body["regressions"]


@pytest.mark.asyncio
async def test_unreadable_journal_gives_null_not_empty_list(
    jnl_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Awaria dziennika NIE gasi sekcji i NIE udaje braku regresji.

    Dwie rzeczy naraz. Po pierwsze: brak jednej tabeli (prodowy alembic bywa
    osierocony) nie może wywalać CAŁEJ Ścieżki rozwoju, która działała bez tego
    dziennika — ostrzeżenie jest wobec tabeli poziomów poboczne.

    Po drugie: `[]` w tym miejscu byłoby awarią udającą wynik — czytelnik
    zobaczyłby ciszę i przeczytał ją jako „nikomu nic nie spadło". Dlatego
    `null`, który front renderuje jako zdanie o niewiedzy.
    """
    from app.api import insights_recruitment as api_module

    async def _boom(_db, **_kwargs):
        raise RuntimeError("relation insights_seniority_snapshots does not exist")

    monkeypatch.setattr(api_module, "load_open_regressions", _boom, raising=True)

    unique = uuid.uuid4().hex[:8]
    email = f"jnl-boom-{unique}@example.com"
    password = f"T3st_{unique}!Jnl"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                name=f"Journal boom {unique}",
                password_hash=hash_password(password),
                role=UserRole.recruiter,
                is_active=True,
            )
        )
        await db.commit()
    login = await jnl_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text

    resp = await jnl_client.get(
        "/api/insights/recruitment/seniority",
        params={"as_of": date(SEED_YEAR, 12, 31).isoformat()},
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["regressions"] is None, body["regressions"]
    # `journal` też musi zniknąć: świeżość dziennika obok komunikatu „nie dało
    # się go odczytać" byłaby wewnętrznie sprzeczna.
    assert body["journal"] is None, body["journal"]
    # Tabela poziomów MUSI dojechać — to jest właściwa treść sekcji.
    assert "entries" in body and "thresholds" in body


@pytest.mark.asyncio
async def test_endpoint_carries_regressions(jnl_client: AsyncClient) -> None:
    """`/api/insights/recruitment/seniority` niesie otwarte regresje, a nie tylko poziomy.

    Ostrzeżenie, po które trzeba sięgnąć do bazy, nie jest ostrzeżeniem.
    """
    user_id = await _seed_recruiter()
    stage_ids = await _seed_placements(user_id, [5, 12])
    await _observe()
    await _drop_placements(stage_ids[:1])
    await _observe()

    unique = uuid.uuid4().hex[:8]
    email = f"jnl-login-{unique}@example.com"
    password = f"T3st_{unique}!Jnl"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                name=f"Journal login {unique}",
                password_hash=hash_password(password),
                role=UserRole.recruiter,
                is_active=True,
            )
        )
        await db.commit()
    login = await jnl_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await jnl_client.get(
        "/api/insights/recruitment/seniority",
        params={"as_of": date(SEED_YEAR, 12, 31).isoformat()},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "regressions" in body
    mine = next((r for r in body["regressions"] if r["user_id"] == user_id), None)
    assert mine is not None, body["regressions"]
    assert mine["previous_level"] == "senior"
    assert mine["level"] == "junior"
