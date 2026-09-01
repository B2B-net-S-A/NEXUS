"""`/api/insights/campaigns` — baner kampanii rekrutacyjnej.

Każdy test broni jednej konkretnej reguły, a nie „że endpoint działa":

1. **Brak kampanii to `null`, nie pusty baner ani błąd** — konsument musi
   odróżnić „nie ma kampanii" od „serwer nie odpowiedział".
2. **`progress_pct` przy celu 0 to `None`, nie `0.0`** — „nie da się
   policzyć" znaczy co innego niż „zero postępu".
3. **`progress_pct` NIE jest przycinane do 100** — przekroczony cel jest
   faktem, a pełny pasek pod liczbą 130% byłby ukryciem sukcesu.
4. **Placement = D2** — pierwsze `hired` per para (kandydat, oferta)
   z `analytics_first_milestones`. Powrót na etap nie liczy się drugi raz.
5. **Rezygnacja liczy się po DNIU FAKTYCZNEGO ZAKOŃCZENIA**
   (`COALESCE(terminated_at, end_date)`), a szkic i anulowanie nie liczą się
   wcale — kontrakt, który nigdy nie ruszył, nie może być odejściem.
6. **CRUD tylko admin, odczyt każdy (D7).**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update

from app.core.cache import cache_invalidate
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_campaign import RecruitmentCampaign
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole

ACTIVE_URL = "/api/insights/campaigns/active"
CRUD_URL = "/api/insights/campaigns"


def _ensure_campaigns_router_mounted(app) -> None:
    """Zamontuj router, jeśli integrator jeszcze tego nie zrobił.

    Właścicielem `app/main.py` jest integrator, a ten plik powstaje równolegle
    z jego montażem. Warunek jest jednorazowy i staje się no-opem w chwili,
    gdy montaż wejdzie do `main.py` — dzięki temu testy sprawdzają realny
    router pod DOCELOWYM URL-em, zamiast mierzyć coś innego niż to, co
    pojedzie na produkcję.
    """
    if any(getattr(r, "path", None) == ACTIVE_URL for r in app.routes):
        return
    from app.api import insights_campaigns

    app.include_router(
        insights_campaigns.router, prefix="/api/insights/campaigns", tags=["insights"]
    )


@pytest_asyncio.fixture
async def camp_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _ensure_campaigns_router_mounted(app)
    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


# ── Seedy ───────────────────────────────────────────────────────────────────


async def _seed_user(role: UserRole) -> tuple[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"camp-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Camp"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                name=f"Camp {role.value} {unique}",
                password_hash=hash_password(password),
                role=role,
                is_active=True,
            )
        )
        await db.commit()
    return email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _admin_headers(client: AsyncClient) -> dict[str, str]:
    email, password = await _seed_user(UserRole.admin)
    return await _login(client, email, password)


async def _deactivate_all_campaigns() -> None:
    """Zdejmij flagę ze wszystkich kampanii — punkt startowy „brak banera".

    Baza testowa jest współdzielona między plikami, więc bez tego „brak
    aktywnej kampanii" zależałoby od kolejności testów.
    """
    async with AsyncSessionLocal() as db:
        await db.execute(update(RecruitmentCampaign).values(is_active=False))
        await db.commit()
    await cache_invalidate("insights:campaigns")


async def _fresh_window(*, days: int = 30) -> tuple[date, date]:
    """Okno, którego nie użył żaden wcześniejszy przebieg tego pliku.

    Baza testowa jest TRWAŁA, a liczniki kampanii są ORGANIZACYJNE — nie mają
    żadnego predykatu, który odciąłby wiersze zasiane przez poprzedni przebieg.
    Okno o stałych datach akumuluje więc placementy z każdego uruchomienia;
    zaobserwowane wprost jako `assert 9 == 3` w trzecim przebiegu, czyli trzy
    komplety tych samych seedów w tym samym oknie. Zielony pierwszy przebieg
    i czerwony drugi to najgorszy możliwy wariant: wygląda jak regresja kodu,
    a jest brakiem izolacji testu.

    Kotwica: najpóźniejsza data końca ISTNIEJĄCEJ kampanii. Każdy seed trafia
    do okna własnej kampanii, więc okno zaczynające się za nimi wszystkimi jest
    z definicji puste — deterministycznie, bez losowania dat (losowanie kupuje
    izolację za cenę testu, który czasem pada bez zmiany w kodzie).
    """
    async with AsyncSessionLocal() as db:
        latest = (
            await db.execute(select(func.max(RecruitmentCampaign.end_date)))
        ).scalar()
    # Podłoga 2037: test licznika dni świadomie zakłada kampanię z 2011 roku
    # i nie może ściągnąć kotwicy w przeszłość.
    anchor = max(latest or date(2037, 1, 1), date(2037, 1, 1))
    # 90 dni odstępu, bo test granicy okna zasiewa CELOWO dzień za swoim
    # oknem — ten wiersz nie może wpaść w okno testu następnego w kolejności.
    start = anchor + timedelta(days=90)
    return start, start + timedelta(days=days)


def _at(day: date, hour: int = 10) -> datetime:
    """Konkretna godzina UTC danego dnia — moment wejścia na etap."""
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=timezone.utc)


async def _seed_client_job_candidate() -> tuple[int, int, int]:
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"CampCli-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=f"Camp {uuid.uuid4().hex[:6]}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            client_id=cli.id,
        )
        cand = Candidate(
            name=f"Ca-{uuid.uuid4().hex[:4]}",
            lastname=f"Mp-{uuid.uuid4().hex[:4]}",
            email=f"camp-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add_all([job, cand])
        await db.commit()
        await db.refresh(job)
        await db.refresh(cand)
        return cli.id, job.id, cand.id


async def _seed_hired(moved_at: datetime) -> None:
    """Jeden placement: pierwsze `hired` dla świeżej pary (kandydat, oferta)."""
    _, job_id, candidate_id = await _seed_client_job_candidate()
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=candidate_id,
                job_id=job_id,
                stage=PipelineStage.hired,
                moved_at=moved_at,
                external_source="manual",
            )
        )
        await db.commit()


async def _seed_contract(
    *,
    status: ContractStatus,
    start: date,
    end: date | None,
    terminated_at: date | None = None,
) -> int:
    client_id, _job_id, candidate_id = await _seed_client_job_candidate()
    async with AsyncSessionLocal() as db:
        contract = Contract(
            candidate_id=candidate_id,
            client_id=client_id,
            start_date=start,
            end_date=end,
            terminated_at=terminated_at,
            rate_client=200,
            rate_candidate=150,
            rate_unit=RateUnit.monthly,
            status=status,
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return contract.id


async def _create_campaign(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    start: str,
    end: str,
    target_net: int,
    name: str = "Kampania testowa",
) -> dict:
    resp = await client.post(
        CRUD_URL,
        headers=headers,
        json={
            "name": name,
            "emoji": "🏖️",
            "start_date": start,
            "end_date": end,
            "target_net": target_net,
            "is_active": True,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── 1. Brak kampanii ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_active_campaign_returns_null(camp_client: AsyncClient):
    """Brak kampanii to 200 z `null` — nie 404 i nie pusty obiekt.

    404 czytałoby się jako „endpoint nie istnieje", a pusty obiekt kazałby
    frontowi renderować baner bez treści. `null` znaczy dokładnie jedno:
    nie ma czego pokazać.
    """
    await _deactivate_all_campaigns()
    email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(camp_client, email, password)

    resp = await camp_client.get(ACTIVE_URL, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() is None


# ── 2/3. Arytmetyka postępu ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_zero_target_yields_none_not_zero(camp_client: AsyncClient):
    """Cel 0 → `progress_pct` to `None`.

    `0.0` twierdziłoby, że policzyliśmy postęp i wyszło zero. Nie ma czego
    dzielić — i to jest inna informacja.
    """
    await _deactivate_all_campaigns()
    headers = await _admin_headers(camp_client)
    body = await _create_campaign(
        camp_client,
        headers,
        start="2037-01-01",
        end="2037-01-31",
        target_net=0,
        name="Cel zerowy",
    )
    assert body["target_net"] == 0
    assert body["progress_pct"] is None


@pytest.mark.asyncio
async def test_exceeded_target_is_not_clipped_to_100(camp_client: AsyncClient):
    """Przekroczony cel pokazuje się jako >100%, nie jako pełny pasek.

    Przycięcie do 100 zamieniłoby najlepszy możliwy wynik w wynik dokładnie
    wystarczający — i nikt by się nie dowiedział, o ile go pobito.
    """
    await _deactivate_all_campaigns()
    window_start, window_end = await _fresh_window()
    # Trzy placementy, zero rezygnacji, cel 2 → 150%.
    for offset in (4, 9, 14):
        await _seed_hired(_at(window_start + timedelta(days=offset)))

    headers = await _admin_headers(camp_client)
    body = await _create_campaign(
        camp_client,
        headers,
        start=window_start.isoformat(),
        end=window_end.isoformat(),
        target_net=2,
        name="Cel pobity",
    )
    assert body["placements"] == 3, body
    assert body["net"] == 3
    assert body["progress_pct"] == 150.0
    assert body["progress_pct"] > 100
    # Ujemna reszta = cel przekroczony o tyle. Świadomie NIE zerowana.
    assert body["remaining_to_target"] == -1


# ── 4/5. Definicje liczników ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_placement_pair_counted_once(camp_client: AsyncClient):
    """Powrót na etap `hired` nie liczy się drugi raz (D2)."""
    await _deactivate_all_campaigns()
    window_start, window_end = await _fresh_window()
    _, job_id, candidate_id = await _seed_client_job_candidate()
    async with AsyncSessionLocal() as db:
        for offset in (3, 10):
            db.add(
                CandidateStage(
                    candidate_id=candidate_id,
                    job_id=job_id,
                    stage=PipelineStage.hired,
                    moved_at=_at(window_start + timedelta(days=offset), hour=9),
                    external_source="manual",
                )
            )
        await db.commit()

    headers = await _admin_headers(camp_client)
    body = await _create_campaign(
        camp_client,
        headers,
        start=window_start.isoformat(),
        end=window_end.isoformat(),
        target_net=10,
        name="Dedup placementów",
    )
    assert body["placements"] == 1, body
    assert body["placements_definition"] == "first_hired_per_candidate_job"


@pytest.mark.asyncio
async def test_resignation_uses_terminated_at_over_end_date(camp_client: AsyncClient):
    """Zerwanie przed czasem liczy się w dniu ZERWANIA, nie planowanego końca.

    `terminated_at` bywa wcześniejszy niż `end_date` — i to on jest dniem,
    w którym kontraktor zniknął ze stanu. Liczenie po `end_date` przesunęłoby
    odejście na miesiąc, w którym tej osoby już nie było.
    """
    await _deactivate_all_campaigns()
    window_start, window_end = await _fresh_window()
    await _seed_contract(
        status=ContractStatus.ended,
        start=window_start - timedelta(days=30),
        end=window_end + timedelta(days=60),  # planowany koniec POZA oknem
        terminated_at=window_start + timedelta(days=9),  # zerwanie W oknie
    )

    headers = await _admin_headers(camp_client)
    body = await _create_campaign(
        camp_client,
        headers,
        start=window_start.isoformat(),
        end=window_end.isoformat(),
        target_net=5,
        name="Zerwanie przed czasem",
    )
    assert body["resignations"] == 1, body
    assert body["net"] == -1
    assert (
        body["resignations_definition"] == "ended_engagement_by_effective_end_date_v2"
    )
    assert "rezygnacja" in body["resignations_definition_note"].lower()


@pytest.mark.asyncio
async def test_future_scheduled_end_is_not_a_resignation_yet(camp_client: AsyncClient):
    """Zaplanowane odejście nie jest odejściem, dopóki dzień nie nadszedł.

    `active`/`ending` są w katalogu rezygnacji po to, żeby złapać kontrakty,
    których nocny `_promote_statuses` jeszcze nie przestemplował. Bez sufitu
    na dziś ta sama reguła wciąga też kontrakty z datą końca w PRZYSZŁOŚCI —
    a wtedy trzymiesięczna kampania ma pierwszego dnia policzone wszystkie
    odejścia z miesiąca drugiego i trzeciego. Netto trwającej kampanii jest
    wtedy systematycznie zaniżone, i to dokładnie wtedy, gdy zespół na baner
    patrzy.

    Okna testowe leżą w 2037 roku, czyli CAŁE w przyszłości — więc każdy
    kontrakt `active` z datą końca w oknie jest tu z definicji planem.
    """
    await _deactivate_all_campaigns()
    window_start, window_end = await _fresh_window()

    # Plan: pracuje, koniec zaplanowany w oknie, ale dzień jeszcze nie nadszedł.
    await _seed_contract(
        status=ContractStatus.active,
        start=window_start - timedelta(days=30),
        end=window_start + timedelta(days=10),
    )
    # Fakt: status mówi „zakończony", więc data jest zapisem, nie planem —
    # ten wiersz liczy się bez względu na sufit.
    await _seed_contract(
        status=ContractStatus.ended,
        start=window_start - timedelta(days=30),
        end=window_start + timedelta(days=11),
    )

    headers = await _admin_headers(camp_client)
    body = await _create_campaign(
        camp_client,
        headers,
        start=window_start.isoformat(),
        end=window_end.isoformat(),
        target_net=5,
        name="Zaplanowane odejscie",
    )
    assert body["resignations"] == 1, (
        "zaplanowane odejście policzyło się, zanim dzień nadszedł — netto "
        f"trwającej kampanii jest zaniżone: {body}"
    )
    assert body["net"] == -1


@pytest.mark.asyncio
async def test_draft_and_void_are_not_resignations(camp_client: AsyncClient):
    """Szkic i anulowanie nie są odejściem.

    Szkic nigdy nie ruszył — jego data końca to plan, nie fakt. `void` to
    anulowanie ZAPISU z zachowaniem dokumentów, a nie zakończenie
    współpracy: policzone byłoby odejściem kogoś, kto nigdy nie został
    policzony jako przyjście.
    """
    await _deactivate_all_campaigns()
    window_start, window_end = await _fresh_window()
    for contract_status in (ContractStatus.draft, ContractStatus.void):
        await _seed_contract(
            status=contract_status,
            start=window_start,
            end=window_start + timedelta(days=19),
        )
    # Kontrolna próbka: zakończony kontrakt w tym samym oknie MA się liczyć,
    # inaczej zielony test nie odróżniałby filtra od zapytania, które nic
    # nie znajduje.
    await _seed_contract(
        status=ContractStatus.ended,
        start=window_start,
        end=window_start + timedelta(days=24),
    )

    headers = await _admin_headers(camp_client)
    body = await _create_campaign(
        camp_client,
        headers,
        start=window_start.isoformat(),
        end=window_end.isoformat(),
        target_net=5,
        name="Szkic i anulowanie",
    )
    assert body["resignations"] == 1, body


@pytest.mark.asyncio
async def test_net_is_placements_minus_resignations(camp_client: AsyncClient):
    """Kafle i pasek muszą się zgadzać: netto = placementy − rezygnacje."""
    await _deactivate_all_campaigns()
    window_start, window_end = await _fresh_window()
    for offset in (2, 5, 8, 11):
        await _seed_hired(_at(window_start + timedelta(days=offset), hour=8))
    await _seed_contract(
        status=ContractStatus.ended,
        start=window_start - timedelta(days=200),
        end=window_start + timedelta(days=14),
    )

    headers = await _admin_headers(camp_client)
    body = await _create_campaign(
        camp_client,
        headers,
        start=window_start.isoformat(),
        end=window_end.isoformat(),
        target_net=6,
        name="Netto",
    )
    assert body["placements"] == 4, body
    assert body["resignations"] == 1, body
    assert body["net"] == 3
    assert body["progress_pct"] == 50.0
    assert body["remaining_to_target"] == 3
    assert body["net_definition_note"] == "netto = placementy − rezygnacje"


@pytest.mark.asyncio
async def test_window_is_half_open_on_both_sources(camp_client: AsyncClient):
    """Dzień po oknie nie wchodzi — ani placement, ani rezygnacja."""
    await _deactivate_all_campaigns()
    window_start, window_end = await _fresh_window()
    day_after = window_end + timedelta(days=1)
    await _seed_hired(_at(day_after, hour=12))
    await _seed_contract(
        status=ContractStatus.ended,
        start=window_start - timedelta(days=200),
        end=day_after,
    )

    headers = await _admin_headers(camp_client)
    body = await _create_campaign(
        camp_client,
        headers,
        start=window_start.isoformat(),
        end=window_end.isoformat(),
        target_net=4,
        name="Granica okna",
    )
    assert body["placements"] == 0, body
    assert body["resignations"] == 0, body


# ── 6. Uprawnienia (D7 na odczycie, admin na zapisie) ───────────────────────


@pytest.mark.parametrize(
    "role",
    [UserRole.sourcer, UserRole.recruiter, UserRole.finance, UserRole.admin],
)
@pytest.mark.asyncio
async def test_every_role_can_read_the_banner(camp_client: AsyncClient, role: UserRole):
    """Cel kampanii to ogłoszenie dla całej firmy (D7).

    Baner, którego nie widzi połowa zespołu, nie jest kampanią. Liczniki są
    zagregowane — nie ma tu ani jednego nazwiska.
    """
    await _deactivate_all_campaigns()
    admin_headers = await _admin_headers(camp_client)
    await _create_campaign(
        camp_client,
        admin_headers,
        start="2038-01-01",
        end="2038-03-31",
        target_net=60,
        name="Wakacyjna integracja",
    )

    email, password = await _seed_user(role)
    headers = await _login(camp_client, email, password)
    resp = await camp_client.get(ACTIVE_URL, headers=headers)
    assert resp.status_code == 200, f"{role.value}: {resp.text}"
    body = resp.json()
    assert body is not None
    assert body["name"] == "Wakacyjna integracja"
    assert body["target_net"] == 60


@pytest.mark.asyncio
async def test_read_requires_login(camp_client: AsyncClient):
    """D7 znaczy „każda ZALOGOWANA rola", nie „każdy"."""
    resp = await camp_client.get(ACTIVE_URL)
    assert resp.status_code in (401, 403), resp.text


@pytest.mark.parametrize(
    "role", [UserRole.sourcer, UserRole.recruiter, UserRole.finance]
)
@pytest.mark.asyncio
async def test_crud_is_admin_only(camp_client: AsyncClient, role: UserRole):
    """Cel kampanii rozlicza zespół — ustawia go admin, nie zespół."""
    await _deactivate_all_campaigns()
    admin_headers = await _admin_headers(camp_client)
    created = await _create_campaign(
        camp_client,
        admin_headers,
        start="2038-05-01",
        end="2038-05-31",
        target_net=12,
        name="Tylko admin",
    )

    email, password = await _seed_user(role)
    headers = await _login(camp_client, email, password)

    listing = await camp_client.get(CRUD_URL, headers=headers)
    assert listing.status_code == 403, listing.text

    creating = await camp_client.post(
        CRUD_URL,
        headers=headers,
        json={
            "name": "Podszywka",
            "start_date": "2038-06-01",
            "end_date": "2038-06-30",
            "target_net": 1,
            "is_active": True,
        },
    )
    assert creating.status_code == 403, creating.text

    patching = await camp_client.patch(
        f"{CRUD_URL}/{created['id']}", headers=headers, json={"target_net": 1}
    )
    assert patching.status_code == 403, patching.text

    deleting = await camp_client.delete(f"{CRUD_URL}/{created['id']}", headers=headers)
    assert deleting.status_code == 403, deleting.text


@pytest.mark.asyncio
async def test_admin_crud_roundtrip_and_single_active(camp_client: AsyncClient):
    """Aktywna jest DOKŁADNIE jedna kampania, a PATCH jest częściowy."""
    await _deactivate_all_campaigns()
    headers = await _admin_headers(camp_client)

    first = await _create_campaign(
        camp_client,
        headers,
        start="2038-07-01",
        end="2038-07-31",
        target_net=10,
        name="Pierwsza",
    )
    second = await _create_campaign(
        camp_client,
        headers,
        start="2038-08-01",
        end="2038-08-31",
        target_net=20,
        name="Druga",
    )

    active = (await camp_client.get(ACTIVE_URL, headers=headers)).json()
    assert active["id"] == second["id"], "druga aktywacja musi zgasić pierwszą"

    # PATCH częściowy: zmieniamy sam cel, nazwa i okno zostają.
    patched = await camp_client.patch(
        f"{CRUD_URL}/{second['id']}", headers=headers, json={"target_net": 33}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["target_net"] == 33
    assert patched.json()["name"] == "Druga"
    assert patched.json()["start_date"] == "2038-08-01"

    listing = (await camp_client.get(CRUD_URL, headers=headers)).json()
    ids = {c["id"] for c in listing["campaigns"]}
    assert {first["id"], second["id"]} <= ids
    assert sum(1 for c in listing["campaigns"] if c["is_active"]) == 1

    removed = await camp_client.delete(f"{CRUD_URL}/{second['id']}", headers=headers)
    assert removed.status_code == 204, removed.text
    gone = await camp_client.patch(
        f"{CRUD_URL}/{second['id']}", headers=headers, json={"target_net": 1}
    )
    assert gone.status_code == 404, gone.text


@pytest.mark.asyncio
async def test_invalid_window_is_rejected_in_polish(camp_client: AsyncClient):
    """Okno odwrócone i okno dłuższe niż `custom` kończą się czytelnym 422.

    Bez tej bramki dałoby się zapisać kampanię, której własny odczyt kończy
    się błędem — `resolve_period(kind="custom")` dopuszcza najwyżej 366 dni.
    """
    headers = await _admin_headers(camp_client)

    reversed_window = await camp_client.post(
        CRUD_URL,
        headers=headers,
        json={
            "name": "Odwrócone okno",
            "start_date": "2038-10-31",
            "end_date": "2038-10-01",
            "target_net": 1,
        },
    )
    assert reversed_window.status_code == 422, reversed_window.text
    assert "wcześniejsza" in reversed_window.json()["detail"]

    too_long = await camp_client.post(
        CRUD_URL,
        headers=headers,
        json={
            "name": "Za długa",
            "start_date": "2038-01-01",
            "end_date": "2040-01-01",
            "target_net": 1,
        },
    )
    assert too_long.status_code == 422, too_long.text
    assert "366" in too_long.json()["detail"]


@pytest.mark.asyncio
async def test_days_remaining_never_negative(camp_client: AsyncClient):
    """Licznik dni po terminie pokazuje 0, nie liczbę ujemną."""
    await _deactivate_all_campaigns()
    headers = await _admin_headers(camp_client)
    body = await _create_campaign(
        camp_client,
        headers,
        start="2011-01-01",
        end="2011-03-31",
        target_net=5,
        name="Kampania zamknięta",
    )
    assert body["days_remaining"] == 0
    assert body["has_started"] is True
