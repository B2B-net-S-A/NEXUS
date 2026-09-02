"""GET /api/insights/recruitment/funnel — lejek org-level.

Trzy rzeczy pod ochroną, każda odpowiadająca konkretnemu defektowi
z docs/insights-dynareporter-migration-plan.md:

1. Okno jest PÓŁOTWARTE [start, end). Legacy `_period_start` nie miał górnej
   granicy, więc „poprzedni miesiąc" znaczył „od poprzedniego miesiąca do dziś".
2. Lejek NIE stosuje predykatów atrybucji. Filtr `kpi_eligible IS TRUE`
   obcinał kafle do ~4% prawdy i podawał ten ułamek jako pewny.
3. Konwersja przy zerowym mianowniku to `None`, nie `0.0`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.cache import cache_invalidate
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.invite_link import CandidateInviteLink
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.models.user_activity import UserActionType, UserActivity


async def _seed_user(role: UserRole, label: str) -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"insf-{label}-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Funnel"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            name=f"Funnel {label} {unique}",
            password_hash=hash_password(password),
            role=role,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id, email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def fx_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


async def _seed_stage(stage: PipelineStage, moved_at: datetime, external_source: str):
    """Wstaw ruch etapu — zasila zarówno `candidate_stages`, jak i widok kamieni."""
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"FunnelCli-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=f"Funnel {uuid.uuid4().hex[:6]}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            client_id=cli.id,
        )
        cand = Candidate(
            name=f"Fun-{uuid.uuid4().hex[:4]}",
            lastname=f"Nel-{uuid.uuid4().hex[:4]}",
            email=f"funnel-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add_all([job, cand])
        await db.commit()
        await db.refresh(job)
        await db.refresh(cand)
        db.add(
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=stage,
                moved_at=moved_at,
                external_source=external_source,
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_funnel_is_reachable_for_every_logged_in_role(fx_client: AsyncClient):
    """Decyzja D7: /insights widzi KAŻDA zalogowana rola, także `sourcer`."""
    for role in (
        UserRole.admin,
        UserRole.head_of_recruitment,
        UserRole.delivery_lead,
        UserRole.talent_community_manager,
        UserRole.tac,
        UserRole.sourcer,
        UserRole.recruiter,
        UserRole.finance,
        UserRole.user,
    ):
        _, email, password = await _seed_user(role, "rbac")
        headers = await _login(fx_client, email, password)
        resp = await fx_client.get("/api/insights/recruitment/funnel", headers=headers)
        assert resp.status_code == 200, f"{role.value}: {resp.text}"


@pytest.mark.asyncio
async def test_funnel_requires_authentication(fx_client: AsyncClient):
    """„Wszyscy" znaczy „każdy ZALOGOWANY", nie „każdy z internetu"."""
    resp = await fx_client.get("/api/insights/recruitment/funnel")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_window_is_half_open_and_excludes_the_next_period(
    fx_client: AsyncClient,
):
    """Ruch z NASTĘPNEGO okresu nie może wpaść do bieżącego.

    Legacy `_period_start` nie miał górnej granicy — to jest regresja na
    dokładnie ten defekt.
    """
    await cache_invalidate("insights:recruitment:funnel:")
    _, email, password = await _seed_user(UserRole.admin, "halfopen")
    headers = await _login(fx_client, email, password)

    resp = await fx_client.get(
        "/api/insights/recruitment/funnel",
        headers=headers,
        params={"period": "custom", "date_from": "2019-01-01", "date_to": "2019-01-31"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["period"]["start"].startswith("2019-01-01")
    # end = 1 lutego, czyli PIERWSZY dzień POZA oknem (półotwarte).
    assert body["period"]["end"].startswith("2019-02-01")


@pytest.mark.asyncio
async def test_conversion_with_zero_denominator_is_none_not_zero(
    fx_client: AsyncClient,
):
    """Brak mianownika to luka, nie zero.

    0.0 czyta się jako „policzyliśmy i wyszło zero"; None mówi „nie było
    czego dzielić". Na ekranie oceniającym ludzi to jest różnica.
    """
    _, email, password = await _seed_user(UserRole.admin, "zerodiv")
    headers = await _login(fx_client, email, password)

    resp = await fx_client.get(
        "/api/insights/recruitment/funnel",
        headers=headers,
        params={"period": "custom", "date_from": "2018-01-01", "date_to": "2018-01-31"},
    )
    assert resp.status_code == 200, resp.text
    for conv in resp.json()["conversions"]:
        if conv["denominator"] == 0:
            assert conv["pct"] is None, conv


@pytest.mark.asyncio
async def test_stages_flag_the_ones_traffit_never_maps(fx_client: AsyncClient):
    """Etapy nieobecne w imporcie muszą być ODZNACZONE, nie tylko zerowe.

    Gołe „0" przy „Akceptacja" czyta się jako „klienci nas nie akceptują",
    a znaczy „nie odnotowujemy akceptacji".
    """
    _, email, password = await _seed_user(UserRole.admin, "unmapped")
    headers = await _login(fx_client, email, password)

    body = (
        await fx_client.get("/api/insights/recruitment/funnel", headers=headers)
    ).json()

    unmapped = {s["stage"] for s in body["stages"] if not s["mapped_from_traffit"]}
    # Dokladnie te piec, ktorych `traffit/mappers.py:404-449` NIE mapuje.
    assert unmapped == {
        "acceptance",
        "client_interview",
        "negotiation",
        "onboarding",
        "prep_call",
    }
    assert set(body["coverage"]["stages_not_mapped_from_traffit"]) == unmapped

    # Etapy, ktore SA mapowane z Traffita, nie moga byc oznaczone jako
    # nieodnotowywane — inaczej UI kazaloby nie ufac jedynym liczbom, ktore
    # naprawde pochodza z zewnatrz.
    mapped = {s["stage"] for s in body["stages"] if s["mapped_from_traffit"]}
    assert {"new", "screening", "verified", "cv_sent", "hired"} <= mapped


@pytest.mark.asyncio
async def test_stage_source_matches_what_the_milestone_view_actually_carries(
    fx_client: AsyncClient,
):
    """Widok kamieni niesie DOKLADNIE szesc etapow — reszta idzie z logu.

    To jest regresja na blad, w ktorym lejek listowal 13 etapow jako pochodzace
    z widoku. Siedem z nich nie moglo miec tam danych NIGDY, wiec API twierdzilo,
    ze ich zero to obserwacja — a przy „Akceptacja", ktora w widoku JEST,
    twierdzilo odwrotnie. Zrodlo musi byc zgodne z `pg_get_viewdef`.
    """
    _, email, password = await _seed_user(UserRole.admin, "stage-source")
    headers = await _login(fx_client, email, password)
    body = (
        await fx_client.get("/api/insights/recruitment/funnel", headers=headers)
    ).json()

    from_view = {s["stage"] for s in body["stages"] if s["source"] == "milestones"}
    assert from_view == {
        "verified",
        "cv_sent",
        "interview",
        "client_interview",
        "acceptance",
        "hired",
    }
    # Gora i dol lejka MUSZA byc oznaczone jako inne zrodlo — inaczej ktos
    # zsumuje je z kamieniami pod jednym naglowkiem.
    from_log = {s["stage"] for s in body["stages"] if s["source"] == "stage_log"}
    assert {"new", "screening", "rejected", "withdrawn"} <= from_log
    assert from_view.isdisjoint(from_log)


@pytest.mark.asyncio
async def test_coverage_counts_manual_moves_by_external_source(
    fx_client: AsyncClient,
):
    """Dyskryminator to `external_source='manual'`, NIE `IS NULL`.

    Kolumna ma ORM-owy default 'manual', a importer wpisuje 'traffit' —
    liczenie po NULL dałoby zero ruchu własnego przy każdym pomiarze.
    """
    await cache_invalidate("insights:recruitment:funnel:")
    # Okno UNIKALNE dla tego przebiegu. Baza testowa jest wspoldzielona miedzy
    # uruchomieniami, wiec staly miesiac zbieralby wiersze z poprzednich runow
    # i asercja na dokladna liczbe przestalaby byc prawdziwa przy drugim
    # uruchomieniu — czyli test bylby zielony raz.
    slot = int(uuid.uuid4().hex[:6], 16) % 900
    year = 1100 + slot  # rok bez zadnych innych danych
    when = datetime(year, 6, 15, 12, tzinfo=timezone.utc)
    await _seed_stage(PipelineStage.verified, when, "manual")
    await _seed_stage(PipelineStage.verified, when + timedelta(days=1), "traffit")

    _, email, password = await _seed_user(UserRole.admin, "coverage")
    headers = await _login(fx_client, email, password)

    body = (
        await fx_client.get(
            "/api/insights/recruitment/funnel",
            headers=headers,
            params={
                "period": "custom",
                "date_from": f"{year}-06-01",
                "date_to": f"{year}-06-30",
            },
        )
    ).json()

    cov = body["coverage"]
    assert cov["stage_moves_total"] == 2
    assert cov["stage_moves_manual"] == 1
    assert cov["manual_pct"] == 50.0


@pytest.mark.asyncio
async def test_cache_key_carries_the_window(fx_client: AsyncClient):
    """Dwa różne okna nie mogą dzielić klucza cache'u.

    Gdyby dzieliły, liczby jednego miesiąca wyszłyby pod etykietą drugiego
    i nikt by tego nie zauważył — obie są wiarygodne.
    """
    _, email, password = await _seed_user(UserRole.admin, "cachekey")
    headers = await _login(fx_client, email, password)

    a = await fx_client.get(
        "/api/insights/recruitment/funnel",
        headers=headers,
        params={"period": "custom", "date_from": "2016-01-01", "date_to": "2016-01-31"},
    )
    b = await fx_client.get(
        "/api/insights/recruitment/funnel",
        headers=headers,
        params={"period": "custom", "date_from": "2016-02-01", "date_to": "2016-02-29"},
    )
    assert a.json()["period"]["start"] != b.json()["period"]["start"]


@pytest.mark.asyncio
async def test_invalid_period_returns_422_not_500(fx_client: AsyncClient):
    _, email, password = await _seed_user(UserRole.admin, "badperiod")
    headers = await _login(fx_client, email, password)
    resp = await fx_client.get(
        "/api/insights/recruitment/funnel",
        headers=headers,
        params={"period": "custom"},  # brak date_from/date_to
    )
    assert resp.status_code == 422


# ── time-to-hire ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_time_to_hire_is_open_to_every_role(fx_client: AsyncClient):
    for role in (
        UserRole.admin,
        UserRole.head_of_recruitment,
        UserRole.delivery_lead,
        UserRole.talent_community_manager,
        UserRole.tac,
        UserRole.recruiter,
        UserRole.sourcer,
        UserRole.finance,
        UserRole.user,
    ):
        _, email, password = await _seed_user(role, "tth-rbac")
        headers = await _login(fx_client, email, password)
        resp = await fx_client.get(
            "/api/insights/recruitment/time-to-hire", headers=headers
        )
        assert resp.status_code == 200, f"{role.value}: {resp.text}"


@pytest.mark.asyncio
async def test_time_to_hire_measures_from_the_real_process_start(
    fx_client: AsyncClient,
):
    """Start procesu bierzemy z CAŁEJ historii pary, nie z okna.

    To jest regresja na `phase3.py:404-432`, gdzie `items[0].moved_at`
    pochodziło wyłącznie z etapów WEWNĄTRZ okna — więc proces zaczęty przed
    oknem dostawał sztucznie krótki czas, i tym krótszy, im dłużej naprawdę
    trwał.
    """
    await cache_invalidate("insights:recruitment:tth:")

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"TthCli-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=f"Tth {uuid.uuid4().hex[:6]}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            client_id=cli.id,
        )
        cand = Candidate(
            name=f"Tth-{uuid.uuid4().hex[:4]}",
            lastname=f"Case-{uuid.uuid4().hex[:4]}",
            email=f"tth-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add_all([job, cand])
        await db.commit()
        await db.refresh(job)
        await db.refresh(cand)

        # Proces startuje 100 dni PRZED oknem, zatrudnienie wpada do okna.
        hired_at = datetime(2015, 6, 15, 12, tzinfo=timezone.utc)
        db.add_all(
            [
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job.id,
                    stage=PipelineStage.new,
                    moved_at=hired_at - timedelta(days=100),
                    external_source="manual",
                ),
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job.id,
                    stage=PipelineStage.hired,
                    moved_at=hired_at,
                    external_source="manual",
                ),
            ]
        )
        await db.commit()

    _, email, password = await _seed_user(UserRole.admin, "tth-window")
    headers = await _login(fx_client, email, password)
    body = (
        await fx_client.get(
            "/api/insights/recruitment/time-to-hire",
            headers=headers,
            params={
                "period": "custom",
                "date_from": "2015-06-01",
                "date_to": "2015-06-30",
                "min_hires": 1,
            },
        )
    ).json()

    assert body["totals"]["hires"] >= 1
    # Gdyby start był liczony od okna, mediana wyszłaby <= ~15 dni.
    medians = [
        e["median_days"] for e in body["entries"] if e["median_days"] is not None
    ]
    if medians:
        assert max(medians) >= 90, body


@pytest.mark.asyncio
async def test_time_to_hire_reports_unattributed_instead_of_hiding_it(
    fx_client: AsyncClient,
):
    """Kamień bez autora musi być POLICZONY OSOBNO, nie wycięty po cichu.

    Wycięty sprawia, że suma kolumny per osoba nie zgadza się z lejkiem —
    a tabela wygląda wtedy na zepsutą, nie na niekompletną.
    """
    _, email, password = await _seed_user(UserRole.admin, "tth-unattr")
    headers = await _login(fx_client, email, password)
    body = (
        await fx_client.get("/api/insights/recruitment/time-to-hire", headers=headers)
    ).json()

    totals = body["totals"]
    assert "unattributed_hires" in totals
    assert totals["attributed_hires"] + totals["unattributed_hires"] == totals["hires"]


# ── team-activity (odpowiednik /api/activities/leaderboard) ─────────────────


async def _seed_activity(
    user_id: int, action: UserActionType, created_at: datetime
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            UserActivity(
                user_id=user_id,
                action_type=action,
                entity_type="candidate",
                entity_id=1,
                created_at=created_at,
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_team_activity_is_open_to_every_logged_in_role(fx_client: AsyncClient):
    """D7 — także dla `user`, którego capability `VIEW_RECRUITMENT_RANKING`
    NIE obejmuje (`analytics/capabilities.py` daje mu pustą frozenset).

    To jest dokładnie ta rola, dla której legacy `/api/activities/leaderboard`
    zwraca 403 — a sekcja na `/insights` renderowała ten 403 jako „brak
    danych o zespole".
    """
    for role in (
        UserRole.admin,
        UserRole.user,
        UserRole.head_of_recruitment,
        UserRole.delivery_lead,
        UserRole.talent_community_manager,
        UserRole.tac,
        UserRole.sourcer,
        UserRole.recruiter,
        UserRole.finance,
    ):
        _, email, password = await _seed_user(role, "ta-rbac")
        headers = await _login(fx_client, email, password)
        resp = await fx_client.get(
            "/api/insights/recruitment/team-activity", headers=headers
        )
        assert resp.status_code == 200, f"{role.value}: {resp.text}"


@pytest.mark.asyncio
async def test_team_activity_requires_authentication(fx_client: AsyncClient):
    resp = await fx_client.get("/api/insights/recruitment/team-activity")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_legacy_leaderboard_guard_was_not_widened(fx_client: AsyncClient):
    """Otwarcie `/insights` NIE MOŻE otworzyć powierzchni legacy.

    `/api/activities/leaderboard` jest współdzielony (dashboard rekrutera),
    a `VIEW_RECRUITMENT_RANKING` steruje kilkoma innymi ekranami. Ten test
    jest strażnikiem granicy: gdyby ktoś „uprościł" refaktor, podmieniając
    tam guard na `CurrentUser`, zmiana przeszłaby niezauważona.
    """
    _, email, password = await _seed_user(UserRole.user, "legacy-guard")
    headers = await _login(fx_client, email, password)
    resp = await fx_client.get("/api/activities/leaderboard", headers=headers)
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_team_activity_window_is_half_open(fx_client: AsyncClient):
    """Aktywność z NASTĘPNEGO okresu nie może wpaść do bieżącego.

    Legacy liczy okno KROCZĄCE (`now - 30 dni`, bez sufitu), więc „poprzedni
    miesiąc" znaczy tam „od poprzedniego miesiąca do dziś". To jest regresja
    na tę właśnie różnicę.
    """
    await cache_invalidate("insights:recruitment:team-activity:")
    # Rok bez innych danych i unikalny per przebieg — baza testowa jest
    # współdzielona, więc stałe okno zbierałoby wiersze z poprzednich runów.
    year = 1300 + int(uuid.uuid4().hex[:6], 16) % 200
    actor_id, email, password = await _seed_user(UserRole.recruiter, "ta-window")
    headers = await _login(fx_client, email, password)

    inside = datetime(year, 6, 15, 12, tzinfo=timezone.utc)
    after = datetime(year, 7, 2, 12, tzinfo=timezone.utc)
    await _seed_activity(actor_id, UserActionType.candidate_added, inside)
    await _seed_activity(actor_id, UserActionType.call_made, after)

    body = (
        await fx_client.get(
            "/api/insights/recruitment/team-activity",
            headers=headers,
            params={
                "period": "custom",
                "date_from": f"{year}-06-01",
                "date_to": f"{year}-06-30",
            },
        )
    ).json()

    mine = [e for e in body["entries"] if e["user_id"] == actor_id]
    assert len(mine) == 1, body
    assert mine[0]["total_actions"] == 1
    assert mine[0]["candidates_added"] == 1
    # Telefon z lipca NIE może wejść do czerwca.
    assert mine[0]["calls"] == 0


@pytest.mark.asyncio
async def test_team_activity_counters_match_the_legacy_shape(fx_client: AsyncClient):
    """Te same liczniki co legacy — serwis jest jeden, nie dwa podobne SQL-e."""
    await cache_invalidate("insights:recruitment:team-activity:")
    year = 1500 + int(uuid.uuid4().hex[:6], 16) % 200
    actor_id, email, password = await _seed_user(UserRole.recruiter, "ta-shape")
    headers = await _login(fx_client, email, password)

    when = datetime(year, 3, 10, 9, tzinfo=timezone.utc)
    for action in (
        UserActionType.candidate_added,
        UserActionType.screening_done,
        UserActionType.interview_scheduled,
        UserActionType.placement_closed,
        UserActionType.call_made,
    ):
        await _seed_activity(actor_id, action, when)

    body = (
        await fx_client.get(
            "/api/insights/recruitment/team-activity",
            headers=headers,
            params={
                "period": "custom",
                "date_from": f"{year}-03-01",
                "date_to": f"{year}-03-31",
            },
        )
    ).json()

    row = next(e for e in body["entries"] if e["user_id"] == actor_id)
    assert row["candidates_added"] == 1
    assert row["screenings"] == 1
    assert row["interviews"] == 1
    assert row["placements"] == 1
    assert row["calls"] == 1
    assert row["total_actions"] == 5
    # Kafel jest FOLDEM po widocznej liście — musi dać się sprawdzić dodając
    # kolumnę na ekranie.
    assert body["totals"]["actions"] == sum(e["total_actions"] for e in body["entries"])
    assert body["totals"]["users"] == len(body["entries"])


@pytest.mark.asyncio
async def test_team_activity_empty_window_has_no_fabricated_zero_share(
    fx_client: AsyncClient,
):
    """Puste okno: zero wierszy i ŻADNEGO `share_pct` równego 0.0."""
    _, email, password = await _seed_user(UserRole.admin, "ta-empty")
    headers = await _login(fx_client, email, password)
    body = (
        await fx_client.get(
            "/api/insights/recruitment/team-activity",
            headers=headers,
            params={
                "period": "custom",
                "date_from": "1801-01-01",
                "date_to": "1801-01-31",
            },
        )
    ).json()
    assert body["entries"] == []
    assert body["totals"]["actions"] == 0
    # Pusty ranking to nie „zespół nic nie robił" — koperta musi to powiedzieć.
    assert body["coverage"]["source"] == "user_activities"
    assert "NEXUSIE" in body["coverage"]["note"]


# ── invite-links (odpowiednik /api/reports/invite-links) ────────────────────


async def _seed_invite_link(
    creator_id: int,
    job_id: int,
    label: str | None,
    use_count: int,
    created_at: datetime,
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateInviteLink(
                token=uuid.uuid4().hex,
                created_by=creator_id,
                job_id=job_id,
                label=label,
                expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
                use_count=use_count,
                created_at=created_at,
            )
        )
        await db.commit()


async def _seed_job() -> int:
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"IlCli-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=f"Il {uuid.uuid4().hex[:6]}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            client_id=cli.id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


@pytest.mark.asyncio
async def test_invite_links_is_open_to_every_logged_in_role(fx_client: AsyncClient):
    """D7 — także dla `recruiter`, `sourcer`, `tac`, TCM i `user`.

    Legacy `/api/reports/invite-links` nadal odrzuca role wykonawcze
    (`recruiter`, `sourcer`, `tac`, `user`), ale przyjmuje leadership readers,
    w tym TCM.
    """
    for role in (
        UserRole.admin,
        UserRole.head_of_recruitment,
        UserRole.delivery_lead,
        UserRole.talent_community_manager,
        UserRole.finance,
        UserRole.recruiter,
        UserRole.sourcer,
        UserRole.tac,
        UserRole.user,
    ):
        _, email, password = await _seed_user(role, "il-rbac")
        headers = await _login(fx_client, email, password)
        resp = await fx_client.get(
            "/api/insights/recruitment/invite-links", headers=headers
        )
        assert resp.status_code == 200, f"{role.value}: {resp.text}"


@pytest.mark.asyncio
async def test_legacy_invite_links_guard_was_not_widened(fx_client: AsyncClient):
    """Otwarcie `/insights` NIE MOŻE otworzyć powierzchni legacy."""
    _, email, password = await _seed_user(UserRole.recruiter, "il-legacy")
    headers = await _login(fx_client, email, password)
    resp = await fx_client.get("/api/reports/invite-links", headers=headers)
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_invite_links_window_is_half_open_and_flags_unlabelled(
    fx_client: AsyncClient,
):
    """Link z NASTĘPNEGO okresu odpada; link bez etykiety jest OZNACZONY.

    Sam string „Bez etykiety" nie wystarcza — to jest legalna nazwa kanału
    i po samym tekście nie da się odróżnić kubełka od kanału tak nazwanego.
    """
    await cache_invalidate("insights:recruitment:invite-links:")
    year = 1700 + int(uuid.uuid4().hex[:6], 16) % 90
    creator_id, email, password = await _seed_user(UserRole.recruiter, "il-window")
    headers = await _login(fx_client, email, password)
    job_id = await _seed_job()

    label = f"LinkedIn-{uuid.uuid4().hex[:6]}"
    await _seed_invite_link(
        creator_id, job_id, label, 4, datetime(year, 5, 10, tzinfo=timezone.utc)
    )
    await _seed_invite_link(
        creator_id, job_id, None, 2, datetime(year, 5, 20, tzinfo=timezone.utc)
    )
    # Poza oknem — nie może wejść do maja.
    await _seed_invite_link(
        creator_id, job_id, label, 99, datetime(year, 6, 5, tzinfo=timezone.utc)
    )

    body = (
        await fx_client.get(
            "/api/insights/recruitment/invite-links",
            headers=headers,
            params={
                "period": "custom",
                "date_from": f"{year}-05-01",
                "date_to": f"{year}-05-31",
            },
        )
    ).json()

    by_label = {c["channel"]: c for c in body["channels"]}
    assert by_label[label]["links_count"] == 1
    assert by_label[label]["applications"] == 4
    assert by_label[label]["unlabelled"] is False
    assert by_label["Bez etykiety"]["unlabelled"] is True
    assert by_label["Bez etykiety"]["applications"] == 2
    # Kafel = fold po widocznej liście.
    assert body["totals"]["links"] == sum(c["links_count"] for c in body["channels"])
    assert body["totals"]["applications"] == 6
    # Koperta MUSI powiedzieć, że licznik aplikacji jest kumulatywny na linku.
    assert body["window_scope"]["applications_are_lifetime_per_link"] is True


@pytest.mark.asyncio
async def test_invite_links_conversion_is_none_not_zero_on_empty_window(
    fx_client: AsyncClient,
):
    """Zero linków → `None`, nie `0.0`.

    Legacy `_safe_pct` zwraca tu 0.0, czyli twierdzi, że kanały miały zerową
    konwersję — a nie było ani jednego linku. Ta różnica jest powodem, dla
    którego procenty liczy router, a nie współdzielony serwis.
    """
    _, email, password = await _seed_user(UserRole.admin, "il-zero")
    headers = await _login(fx_client, email, password)
    body = (
        await fx_client.get(
            "/api/insights/recruitment/invite-links",
            headers=headers,
            params={
                "period": "custom",
                "date_from": "1802-01-01",
                "date_to": "1802-01-31",
            },
        )
    ).json()
    assert body["channels"] == []
    assert body["totals"]["links"] == 0
    assert body["totals"]["conversion_pct"] is None
