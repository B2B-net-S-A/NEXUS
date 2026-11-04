"""Runy integracji (scrapery pracuj.pl / JJIT): kontrakt zapisu, odczytu i zastoju.

Trzy rzeczy, których złamanie jest defektem:

1. **Reguła zastoju jest jedna** — Insights i alert Slack liczą to samo
   (``services.integration_runs.is_stale``): brak udanego runu od N godzin
   ALBO źródło nigdy nie raportowało = zastój; run ``failed`` nie ratuje.
2. **Zapis wymaga roli operacyjnej, nie admina** — scraper raportuje tokenem
   klienta OAuth działającego jako user serwisowy (migracja 0311). Viewer
   ``user`` nie może wpisać runu (403), a start → zdarzenia → finish daje
   spójne podsumowanie z licznikami i błędami per kandydat.
3. **Alert ma cooldown w bazie** — po restarcie backendu (każdy deploy)
   drugi przebieg pętli nie wysyła drugiego alertu tego samego dnia.

Router montujemy na własnej instancji FastAPI (konwencja repo — patrz
``test_insights_performance_flags.py``), prefiksy = te z ``main.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.integration_run import IntegrationAlertState, IntegrationRun
from app.models.user import User, UserRole
from app.services.integration_runs import is_stale

_WRITE = "/api/integrations"
_READ = "/api/insights/integrations"


def _build_app() -> FastAPI:
    from app.api import integrations_runs

    test_app = FastAPI()
    test_app.include_router(integrations_runs.writer, prefix=_WRITE)
    test_app.include_router(integrations_runs.reader, prefix=_READ)
    return test_app


async def _seed_user(role: UserRole) -> User:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"integ-{role.value}-{unique}@example.com",
            name=f"Integ {role.value} {unique}",
            password_hash=hash_password(f"T3st_{unique}!Integ"),
            role=role,
            is_active=True,
            profile_completed=True,
        )
        user.ensure_roles_invariant()
        db.add(user)
        await db.commit()
        await db.refresh(user)
        db.expunge(user)
        return user


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(
        subject=user.id,
        role=user.role.value,
        roles=list(user.roles or []),
        authorization_version=user.authorization_version,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def integ_client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=_build_app(), raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


# ── 1. Reguła zastoju (bez bazy) ────────────────────────────────────────────


def test_stale_when_never_reported():
    assert is_stale(None, stale_after_hours=26) is True


def test_stale_boundary_is_hours_not_days():
    now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    fresh = now - timedelta(hours=25)
    old = now - timedelta(hours=27)
    assert is_stale(fresh, stale_after_hours=26, now=now) is False
    assert is_stale(old, stale_after_hours=26, now=now) is True


def test_naive_timestamp_is_treated_as_utc():
    now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    naive = datetime(2026, 9, 16, 10, 0)  # brak tz — jak z fixture/SQLite
    assert is_stale(naive, stale_after_hours=26, now=now) is False


# ── 2. Zapis przez rolę operacyjną, odczyt w Insights ───────────────────────


@pytest.mark.asyncio
async def test_viewer_cannot_report_a_run(integ_client: AsyncClient):
    headers = _headers(await _seed_user(UserRole.user))
    resp = await integ_client.post(
        f"{_WRITE}/runs", headers=headers, json={"source": "jjit", "mode": "import"}
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_run_lifecycle_shows_up_in_summary(integ_client: AsyncClient):
    """start → zdarzenia → finish; podsumowanie ma liczniki, błąd i rekrutację."""
    writer = _headers(await _seed_user(UserRole.talent_community_manager))
    reader = _headers(await _seed_user(UserRole.recruiter))

    started = await integ_client.post(
        f"{_WRITE}/runs",
        headers=writer,
        json={
            "source": "jjit",
            "mode": "import",
            "host": "mac-artur",
            "version": "1.0",
        },
    )
    assert started.status_code == 201, started.text
    run_id = started.json()["id"]
    assert started.json()["status"] == "running"

    events = await integ_client.post(
        f"{_WRITE}/runs/{run_id}/events",
        headers=writer,
        json=[
            {
                "action": "created",
                "external_id": "app-1",
                "traffit_id": 62601,
                "candidate_name": "Jan Testowy",
                "offer_title": "DevOps Engineer",
                "matched_jobs": [
                    {"job_id": 3, "title": "DevOps / Cloud Engineer", "score": 71.0}
                ],
            },
            {
                "action": "error",
                "external_id": "app-2",
                "candidate_name": "Anna Błąd",
                "offer_title": "Java Developer",
                "error": "LLM parse error",
            },
        ],
    )
    assert events.status_code == 201, events.text
    assert events.json()["inserted"] == 2

    finished = await integ_client.patch(
        f"{_WRITE}/runs/{run_id}",
        headers=writer,
        json={
            "status": "errors",
            "stats": {"created": 1, "duplicates": 0, "errors": 1, "nexus_jobs": 1},
        },
    )
    assert finished.status_code == 200, finished.text
    assert finished.json()["status"] == "errors"
    assert finished.json()["finished_at"] is not None

    summary = await integ_client.get(
        f"{_READ}/summary", headers=reader, params={"days": 1}
    )
    assert summary.status_code == 200, summary.text
    body = summary.json()
    jjit = next(s for s in body["sources"] if s["source"] == "jjit")
    assert jjit["stale"] is False, "run 'errors' to nadal udany run — scraper żyje"
    assert jjit["last_run"]["id"] == run_id
    assert jjit["totals"]["created"] >= 1
    assert jjit["totals"]["errors"] >= 1
    assert any(e["external_id"] == "app-2" for e in body["recent_errors"])
    assert any(j["job_id"] == 3 for j in body["top_jobs"])

    run_events = await integ_client.get(f"{_READ}/runs/{run_id}/events", headers=reader)
    assert run_events.status_code == 200
    assert {e["action"] for e in run_events.json()} == {"created", "error"}


@pytest.mark.asyncio
async def test_failed_run_does_not_count_as_success(integ_client: AsyncClient):
    writer = _headers(await _seed_user(UserRole.talent_community_manager))
    started = await integ_client.post(
        f"{_WRITE}/runs", headers=writer, json={"source": "pracuj", "mode": "import"}
    )
    run_id = started.json()["id"]
    await integ_client.patch(
        f"{_WRITE}/runs/{run_id}",
        headers=writer,
        json={"status": "failed", "error": "login failed"},
    )
    async with AsyncSessionLocal() as db:
        from app.services.integration_runs import last_success_per_source

        last = await last_success_per_source(db)
    # Mogą istnieć inne udane runy pracuj z innych testów — ale ten konkretny
    # (failed) nie może być tym, który podniósł znacznik.
    run = None
    async with AsyncSessionLocal() as db:
        run = await db.get(IntegrationRun, run_id)
    assert run is not None and run.status == "failed"
    assert last["pracuj"] is None or last["pracuj"] != run.finished_at


@pytest.mark.asyncio
async def test_unknown_source_is_rejected(integ_client: AsyncClient):
    writer = _headers(await _seed_user(UserRole.talent_community_manager))
    resp = await integ_client.post(
        f"{_WRITE}/runs", headers=writer, json={"source": "linkedin", "mode": "import"}
    )
    assert resp.status_code == 422


# ── 3. Cooldown alertu przeżywa restart ─────────────────────────────────────


@pytest.mark.asyncio
async def test_alert_cooldown_persists_in_db(monkeypatch):
    from app.tasks import integration_stale_alerts as task

    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        state = await db.get(IntegrationAlertState, "pracuj")
        if state is None:
            state = IntegrationAlertState(source="pracuj")
            db.add(state)
        state.last_alert_at = None
        await db.commit()

    first = await task.run_once(now=now)
    # Bez udanego runu pracuj w testowej bazie źródło jest w zastoju → 'stale'
    # (bez webhooka nie 'alerted'); jeśli inny test wpisał świeży run, 'ok'.
    assert first["pracuj"] in {"stale", "ok"}
    if first["pracuj"] == "stale":
        second = await task.run_once(now=now + timedelta(minutes=30))
        assert second["pracuj"] == "cooldown", (
            "drugi przebieg w tej samej dobie = cooldown"
        )


# ── 4. Run zabity bez `finish` nie wisi jako „trwa” (06.10.2026) ────────────


@pytest.mark.asyncio
async def test_stuck_running_run_is_closed_as_failed_after_6h(monkeypatch):
    from app.services.integration_runs import STUCK_RUN_ERROR
    from app.tasks import integration_stale_alerts as task

    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        stuck = IntegrationRun(
            source="pracuj", status="running", started_at=now - timedelta(hours=7)
        )
        fresh = IntegrationRun(
            source="pracuj", status="running", started_at=now - timedelta(hours=1)
        )
        db.add_all([stuck, fresh])
        await db.commit()
        stuck_id, fresh_id = stuck.id, fresh.id

    await task.run_once(now=now)

    async with AsyncSessionLocal() as db:
        closed = await db.get(IntegrationRun, stuck_id)
        running = await db.get(IntegrationRun, fresh_id)
        assert closed.status == "failed"
        assert closed.finished_at is not None
        assert closed.error == STUCK_RUN_ERROR
        assert running.status == "running" and running.finished_at is None


# ── 5. Lista błędów: tylko zgłoszenia wciąż niedokończone (03.11.2026) ──────


async def _report_events(
    client: AsyncClient,
    headers: dict[str, str],
    events: list[dict],
    *,
    source: str = "jjit",
    mode: str = "import",
) -> None:
    started = await client.post(
        f"{_WRITE}/runs", headers=headers, json={"source": source, "mode": mode}
    )
    assert started.status_code == 201, started.text
    run_url = f"{_WRITE}/runs/{started.json()['id']}"
    resp = await client.post(f"{run_url}/events", headers=headers, json=events)
    assert resp.status_code == 201, resp.text
    # Bieg zakończony: `running` na wspólnej bazie testowej blokuje każdy
    # późniejszy import JJIT (`RunInProgress`, kolejka 03.11.2026).
    finished = await client.patch(run_url, headers=headers, json={"status": "ok"})
    assert finished.status_code == 200, finished.text


def _event(external_id: str | None, action: str, minutes_ago: int) -> dict:
    occurred_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return {
        "action": action,
        "external_id": external_id,
        "occurred_at": occurred_at.isoformat(),
        "error": "NEXUS: ReadTimeout" if action == "error" else None,
    }


async def _errors_summary(client: AsyncClient, headers: dict[str, str]) -> dict:
    resp = await client.get(f"{_READ}/summary", headers=headers, params={"days": 1})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _unique_id() -> str:
    return f"lista-bledow-{uuid.uuid4().hex}"


@pytest.mark.asyncio
async def test_error_followed_by_success_leaves_the_list(integ_client: AsyncClient):
    """Zgłoszenie dokończone później nie jest na liście, tylko w liczniku."""
    writer = _headers(await _seed_user(UserRole.talent_community_manager))
    reader = _headers(await _seed_user(UserRole.recruiter))
    before = (await _errors_summary(integ_client, reader))["resolved_error_count"]
    done = _unique_id()

    await _report_events(integ_client, writer, [_event(done, "error", 30)])
    await _report_events(integ_client, writer, [_event(done, "created", 10)])

    body = await _errors_summary(integ_client, reader)
    assert done not in {e["external_id"] for e in body["recent_errors"]}
    assert body["resolved_error_count"] == before + 1


@pytest.mark.asyncio
async def test_two_errors_of_one_application_give_one_row(integ_client: AsyncClient):
    """Jeden wiersz: treść najnowszego błędu i liczba prób."""
    writer = _headers(await _seed_user(UserRole.talent_community_manager))
    reader = _headers(await _seed_user(UserRole.recruiter))
    stuck = _unique_id()
    older = {**_event(stuck, "error", 30), "error": "starszy błąd"}
    newer = {**_event(stuck, "error", 10), "error": "nowszy błąd"}

    await _report_events(integ_client, writer, [older])
    await _report_events(integ_client, writer, [newer])

    body = await _errors_summary(integ_client, reader)
    rows = [e for e in body["recent_errors"] if e["external_id"] == stuck]
    assert len(rows) == 1
    assert rows[0]["attempts"] == 2
    assert rows[0]["error"] == "nowszy błąd"
    assert body["unfinished_error_count"] >= 1


@pytest.mark.asyncio
@pytest.mark.parametrize("empty_id", [None, ""])
async def test_errors_without_external_id_stay_separate(
    integ_client: AsyncClient, empty_id: str | None
):
    """Bez identyfikatora nie wiadomo, czy to jedno zgłoszenie ani czy się udało."""
    writer = _headers(await _seed_user(UserRole.talent_community_manager))
    reader = _headers(await _seed_user(UserRole.recruiter))
    first, second = f"bez-id-{uuid.uuid4().hex}", f"bez-id-{uuid.uuid4().hex}"

    await _report_events(
        integ_client,
        writer,
        [
            {**_event(empty_id, "error", 30), "error": first},
            {**_event(empty_id, "error", 20), "error": second},
            # Sukces bez identyfikatora nie może zamknąć żadnego z tych błędów.
            _event(empty_id, "created", 10),
        ],
    )

    body = await _errors_summary(integ_client, reader)
    rows = [e for e in body["recent_errors"] if e["error"] in {first, second}]
    assert {e["error"] for e in rows} == {first, second}
    assert all(e["attempts"] == 1 for e in rows)


@pytest.mark.asyncio
async def test_error_after_success_counts_only_attempts_since_success(
    integ_client: AsyncClient,
):
    """Nawrót: wcześniejszy sukces niczego nie zamyka, a próby liczą się od niego."""
    writer = _headers(await _seed_user(UserRole.talent_community_manager))
    reader = _headers(await _seed_user(UserRole.recruiter))
    relapsed = _unique_id()

    await _report_events(
        integ_client,
        writer,
        [
            _event(relapsed, "error", 40),
            _event(relapsed, "created", 30),
            _event(relapsed, "error", 20),
            _event(relapsed, "error", 10),
        ],
    )

    body = await _errors_summary(integ_client, reader)
    rows = [e for e in body["recent_errors"] if e["external_id"] == relapsed]
    assert [e["attempts"] for e in rows] == [2]


@pytest.mark.asyncio
async def test_success_in_other_source_or_dry_run_does_not_close_error(
    integ_client: AsyncClient,
):
    """Próbny przebieg niczego nie zapisuje, a ID z innego portalu to inne zgłoszenie."""
    writer = _headers(await _seed_user(UserRole.talent_community_manager))
    reader = _headers(await _seed_user(UserRole.recruiter))
    stuck = _unique_id()

    await _report_events(integ_client, writer, [_event(stuck, "error", 30)])
    await _report_events(
        integ_client, writer, [_event(stuck, "created", 20)], mode="dry_run"
    )
    await _report_events(
        integ_client, writer, [_event(stuck, "created", 10)], source="pracuj"
    )

    body = await _errors_summary(integ_client, reader)
    assert stuck in {e["external_id"] for e in body["recent_errors"]}


@pytest.mark.asyncio
async def test_dry_run_error_is_not_on_the_list(integ_client: AsyncClient):
    writer = _headers(await _seed_user(UserRole.talent_community_manager))
    reader = _headers(await _seed_user(UserRole.recruiter))
    trial = _unique_id()

    await _report_events(
        integ_client, writer, [_event(trial, "error", 10)], mode="dry_run"
    )

    body = await _errors_summary(integ_client, reader)
    assert trial not in {e["external_id"] for e in body["recent_errors"]}


@pytest.mark.asyncio
async def test_error_list_hides_person_without_candidate_read(
    integ_client: AsyncClient,
):
    """Rada nadzorcza widzi Insights, ale nie kandydatów: zdarzenie zostaje bez osoby."""
    writer = _headers(await _seed_user(UserRole.talent_community_manager))
    board = _headers(await _seed_user(UserRole.board))
    recruiter = _headers(await _seed_user(UserRole.recruiter))
    stuck = _unique_id()

    await _report_events(
        integ_client,
        writer,
        [{**_event(stuck, "error", 10), "candidate_name": "Anna Testowa"}],
    )

    hidden = await _errors_summary(integ_client, board)
    row = next(e for e in hidden["recent_errors"] if e["external_id"] == stuck)
    assert row["candidate_name"] is None
    assert row["candidate_id"] is None

    shown = await _errors_summary(integ_client, recruiter)
    row = next(e for e in shown["recent_errors"] if e["external_id"] == stuck)
    assert row["candidate_name"] == "Anna Testowa"
