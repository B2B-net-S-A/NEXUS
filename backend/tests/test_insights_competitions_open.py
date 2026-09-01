"""Odczyty konkursów są otwarte dla każdej zalogowanej roli (D7).

Liga Mistrzów, wyścigi miesięczne i Hall of Fame są częścią /insights, a ta
powierzchnia została jawnie otwarta decyzją Artura z 2026-08-31.

Dlaczego akurat TEN endpoint wolno było poszerzyć na miejscu, a innych nie:
jego konsumenci we froncie to `ChampionsSection.tsx` i `InsightsHallOfFame.tsx`,
czyli sama zakładka Insights. `/api/reports/*`, `/api/admin/clients-overview` i
`/api/dashboard/v2/*` są współdzielone z innymi stronami — tam poszerzenie
guardu otworzyłoby powierzchnie, na które nikt nie dawał zgody, więc Insights
dostaje własne `/api/insights/*`.

Zapisy (freeze) MUSZĄ zostać admin-only: zamrożone podium jest write-once
(`competitions.py` compose/freeze), więc pomyłka jest nieodwracalna.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole

_READ_ONLY_ROLES = [
    UserRole.sourcer,
    UserRole.recruiter,
    UserRole.tac,
    UserRole.finance,
    UserRole.delivery_lead,
    UserRole.head_of_recruitment,
    UserRole.admin,
]


async def _seed_user(role: UserRole) -> tuple[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"comp-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Comp"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                name=f"Comp {role.value} {unique}",
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


async def _seed_hall_of_fame_people(count: int) -> list[dict]:
    """`count` rekruterów, każdy z jednym placementem (para kandydat × oferta).

    Hall of Fame liczy z widoku `analytics_first_milestones`, więc wystarczy
    jeden wiersz `hired` na osobę, żeby wpadła do rankingu.
    """
    from datetime import datetime, timedelta, timezone

    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus, RemotePolicy
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    people: list[dict] = []
    async with AsyncSessionLocal() as db:
        client_row = Client(name=f"HofCli-{uuid.uuid4().hex[:6]}")
        db.add(client_row)
        await db.commit()
        await db.refresh(client_row)

        for i in range(count):
            unique = uuid.uuid4().hex[:8]
            email = f"hof-{unique}@example.com"
            password = f"T3st_{unique}!Hof"
            user = User(
                email=email,
                name=f"Hof {unique}",
                password_hash=hash_password(password),
                role=UserRole.recruiter,
                is_active=True,
            )
            job = Job(
                title=f"Hof {uuid.uuid4().hex[:6]}",
                location="Warszawa",
                status=JobStatus.published,
                remote_policy=RemotePolicy.hybrid,
                client_id=client_row.id,
            )
            candidate = Candidate(
                name=f"Hof-{uuid.uuid4().hex[:4]}",
                lastname=f"Fame-{uuid.uuid4().hex[:4]}",
                email=f"hof-cand-{uuid.uuid4().hex[:8]}@example.com",
            )
            db.add_all([user, job, candidate])
            await db.commit()
            await db.refresh(user)
            await db.refresh(job)
            await db.refresh(candidate)

            # Rok nieużywany przez inne testy — baza jest wspólna, a te wiersze
            # mają `moved_by`, więc wchodzą też do imiennych raportów sąsiadów.
            db.add(
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    stage=PipelineStage.hired,
                    moved_at=datetime(2004, 6, 15, 12, 0, tzinfo=timezone.utc)
                    + timedelta(days=i),
                    moved_by=user.id,
                )
            )
            await db.commit()
            people.append({"id": user.id, "email": email, "password": password})
    return people


@pytest_asyncio.fixture
async def comp_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.mark.parametrize("role", _READ_ONLY_ROLES)
@pytest.mark.asyncio
async def test_every_role_reads_the_quarterly_league(
    comp_client: AsyncClient, role: UserRole
):
    email, password = await _seed_user(role)
    headers = await _login(comp_client, email, password)
    resp = await comp_client.get(
        "/api/competitions/current",
        headers=headers,
        params={"type": "quarterly_champions_recruiter"},
    )
    assert resp.status_code == 200, f"{role.value}: {resp.text}"


@pytest.mark.parametrize("role", [UserRole.sourcer, UserRole.finance])
@pytest.mark.asyncio
async def test_every_role_reads_races_and_history(
    comp_client: AsyncClient, role: UserRole
):
    email, password = await _seed_user(role)
    headers = await _login(comp_client, email, password)

    races = await comp_client.get("/api/competitions/monthly-races", headers=headers)
    assert races.status_code == 200, races.text

    # /history poszerzone do CurrentUser 2026-09-01, gdy powstal jego pierwszy
    # konsument: sekcja „Hall of Fame" na /insights (InsightsHallOfFame.tsx).
    # Asercja jest TWARDA (== 200), a nie „200 albo 403": luzna przepuszczala
    # cichy powrot weszego guardu, po ktorym sekcja renderowalaby komunikat
    # o braku uprawnien zamiast zamknietych okresow.
    history = await comp_client.get(
        "/api/competitions/history",
        headers=headers,
        params={"type": "quarterly_champions_recruiter"},
    )
    assert history.status_code == 200, f"{role.value}: {history.text}"


@pytest.mark.asyncio
async def test_hall_of_fame_sql_actually_runs_against_the_real_schema(
    comp_client: AsyncClient,
):
    """Zapytanie Hall of Fame WYKONUJE się na prawdziwym schemacie.

    Testy jednostkowe tej funkcji podmieniają `db.execute` i asertują KSZTAŁT
    SQL-a — nigdy go nie uruchamiają. Po przepisaniu atrybucji z
    `VERIFIER_ANCHORED_CTE` na `analytics_first_milestones` (2026-09-01) taki
    komplet byłby zielony także wtedy, gdyby nowe zapytanie miało literówkę
    w nazwie kolumny albo odwoływało się do widoku, którego na migrowanej
    bazie nie ma: 500 zobaczyłby dopiero użytkownik.

    Ten test przechodzi CAŁĄ ścieżkę: router -> serwis -> Postgres, i dotyka
    OBU zapytań (ranking + `hall_of_fame_scope`), bo `/current` liczy je razem.
    """
    email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(comp_client, email, password)

    resp = await comp_client.get(
        "/api/competitions/current",
        headers=headers,
        params={"type": "hall_of_fame"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body["full_ranking"], list)

    # `scope` to jedyne miejsce, z którego UI wie, ile dorobku stoi POZA
    # rankingiem. Bez niego lista przycięta do TOP 5 czyta się jako komplet.
    scope = body["scope"]
    assert scope is not None, "Hall of Fame bez `scope` — TOP 5 udaje całość"
    # DOKŁADNIE ten sam kod co w /placement-analysis — własny wariant
    # („..._by_mover") dawałby maszynowo „różne" tam, gdzie reguła jest ta sama.
    assert scope["attribution"] == "first_hired_per_candidate_job"
    for key in (
        "ranked_placements",
        "outside_role_placements",
        "unattributed_placements",
        # Mianownik dla „TOP 5" — bez niego lista pięciu wierszy stoi nad
        # liczbą, której te wiersze nie sumują.
        "ranked_people",
    ):
        assert isinstance(scope[key], int), key
    # Zakres ról jest CZĘŚCIĄ kontraktu: to on, a nie atrybucja, oddziela
    # „kto dowiózł" od „kto masowo domknął pipeline".
    assert "admin" not in scope["roles"]
    assert "delivery_lead" in scope["roles"]

    # Trzy kubełki MUSZĄ domykać się do wszystkich placementów. Pierwsza
    # wersja liczyła „poza rankingiem" jako `NOT (predykat ról)`, więc kamień
    # przypisany do konta, którego już nie ma w `users`, wypadał z obu
    # kubełków przez trójwartościową logikę — a repo zna ten przypadek
    # (tabela zespołu opisuje go wprost). Zdanie „poza rankingiem: N" było
    # wtedy po cichu zaniżone.
    #
    # Sumę czytamy WPROST z widoku, a nie z drugiego endpointu: ten drugi ma
    # własny sufit okna (`MAX_CUSTOM_PERIOD_DAYS`), więc porównanie przez
    # niego albo pomijałoby się po cichu przy 422, albo mierzyło inne okno.
    async with AsyncSessionLocal() as db:
        total = (
            await db.execute(
                text(
                    "SELECT count(*) FROM analytics_first_milestones "
                    "WHERE stage::text = 'hired'"
                )
            )
        ).scalar_one()

    assert (
        scope["ranked_placements"]
        + scope["outside_role_placements"]
        + scope["unattributed_placements"]
    ) == int(total), "suma kubełków `scope` nie domyka się do wszystkich placementów"


@pytest.mark.asyncio
async def test_hall_of_fame_agrees_with_placement_analysis_number_by_number(
    comp_client: AsyncClient,
):
    """Zgodność z sąsiadem jest DOWODZONA, nie deklarowana.

    Hall of Fame i „Analiza placementów" liczą tę samą rzecz, ale robią to
    DWOMA osobnymi zapytaniami w dwóch plikach. Sam wspólny kod definicji
    (`placements_definition`) jest obietnicą — i wystarczy jedna literówka
    w predykacie, żeby obie powierzchnie rozjechały się cicho, nadal
    deklarując tę samą regułę.

    Ten test bierze te same dane z jednego i drugiego SQL-a i porównuje je
    LICZBA PO LICZBIE dla osób, które wchodzą do obu populacji.
    """
    email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(comp_client, email, password)

    hof = await comp_client.get(
        "/api/competitions/current",
        headers=headers,
        params={"type": "hall_of_fame"},
    )
    assert hof.status_code == 200, hof.text
    hof_body = hof.json()

    # Kod definicji MUSI być identyczny — inaczej maszynowe porównanie da
    # „różne" tam, gdzie reguła jest ta sama.
    analysis = await comp_client.get(
        "/api/insights/charts/placement-analysis",
        headers=headers,
        params={"period": "year", "offset": 0},
    )
    assert analysis.status_code == 200, analysis.text
    assert (
        hof_body["scope"]["attribution"] == analysis.json()["placements_definition"]
    ), "Hall of Fame i Analiza placementów deklarują RÓŻNE definicje placementu"

    # Ranking HoF jest all-time, a analiza okresowa — więc porównujemy to, co
    # porównywalne: liczba z HoF nie może być MNIEJSZA niż liczba tej samej
    # osoby w oknie zawartym w all-time. Stara, verifier-anchored reguła
    # liczyła per PRÓBĘ PROCESU, więc potrafiła dać liczbę wyższą niż suma
    # placementów firmy; po przejściu na D2 taki wiersz jest niemożliwy.
    per_person = {
        row["user_id"]: row["placements"]
        for row in analysis.json()["by_person"]
        if row.get("attributed") and row.get("user_id") is not None
    }
    for entry in hof_body["full_ranking"]:
        in_window = per_person.get(entry["user_id"])
        if in_window is None:
            continue
        assert entry["metric_value"] >= in_window, (
            f"{entry['name']}: all-time ({entry['metric_value']}) < okno "
            f"({in_window}) — dwa zapytania liczą różnie"
        )


@pytest.mark.asyncio
async def test_my_position_ranks_below_the_presentation_limit(
    comp_client: AsyncClient,
):
    """`total` opisuje RANKING, a nie długość listy, którą akurat pobrano.

    `/my-position` brał `hall_of_fame(db, limit=50)` i zwracał `total:
    len(ranked)`. Produkcyjny ranking ma dziś 59 osób, więc mianownik był
    zaniżony dla KAŻDEGO czytelnika, a 51. osoba dostawała dodatkowo
    `rank: None` — „nie ma cię w rankingu", mimo że ma placementy.

    Test porównuje `total` z `scope.ranked_people` z `/current` — z liczbą,
    którą UI renderuje pod TOP 5. Rozjazd znaczy, że jedna z nich opisuje inny
    zbiór niż druga.

    UWAGA na zakres dowodu: samego PRZYCIĘCIA ten test nie odtwarza, bo baza
    testowa nie ma 51 osób w rankingu i `limit=50` zwróciłby tu wszystkich.
    Decyzji „pytaj o pełną listę" broni `test_my_position_asks_for_the_whole_ranking`.
    """
    people = await _seed_hall_of_fame_people(3)
    # Osoba z NAJMNIEJSZĄ liczbą placementów wśród zasianych — czyli ta, którą
    # przycinanie listy odcina najpierw.
    last = people[-1]
    headers = await _login(comp_client, last["email"], last["password"])

    current = await comp_client.get(
        "/api/competitions/current",
        headers=headers,
        params={"type": "hall_of_fame"},
    )
    assert current.status_code == 200, current.text
    ranked_people = current.json()["scope"]["ranked_people"]

    mine = await comp_client.get(
        "/api/competitions/my-position",
        headers=headers,
        params={"type": "hall_of_fame"},
    )
    assert mine.status_code == 200, mine.text
    body = mine.json()

    # Kontrakt: mianownik opisuje RANKING, nie długość przyciętej listy.
    assert body["total"] == ranked_people, (
        "`total` w /my-position opisuje inny zbiór niż mianownik pod TOP 5"
    )
    # Osoba z placementem MA pozycję. Bez tego poprzednia asercja przeszłaby
    # także wtedy, gdyby endpoint przestał kogokolwiek znajdować.
    assert body["rank"] is not None, body
    assert 1 <= body["rank"] <= ranked_people


@pytest.mark.asyncio
async def test_my_position_asks_for_the_whole_ranking(
    comp_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Endpoint prosi o PEŁNY ranking, nie o pierwsze N wierszy.

    Test białoskrzynkowy i to jest świadome. Skutku przycięcia nie da się
    odtworzyć czarnoskrzynkowo bez zasiania 51 osób z placementami w bazie
    współdzielonej przez cały przebieg — a to zmieniłoby liczby w sąsiednich
    testach imiennych raportów. Zamiast tego pilnujemy samej decyzji: dowolny
    sufit prezentacyjny wstawiony tu z powrotem odpowiadałby komuś „nie ma cię
    w rankingu" na pytanie o własną pozycję.
    """
    from app.api import competitions as comp_api

    seen: list[object] = []
    original = comp_api.comp_service.hall_of_fame_with_scope

    async def _spy(db, limit=5):
        seen.append(limit)
        return await original(db, limit=limit)

    monkeypatch.setattr(
        comp_api.comp_service, "hall_of_fame_with_scope", _spy, raising=True
    )

    email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(comp_client, email, password)
    resp = await comp_client.get(
        "/api/competitions/my-position",
        headers=headers,
        params={"type": "hall_of_fame"},
    )

    assert resp.status_code == 200, resp.text
    assert seen == [None], f"/my-position pobrał ranking z limitem {seen}"


@pytest.mark.asyncio
async def test_hall_of_fame_without_limit_returns_the_whole_ranking(
    comp_client: AsyncClient,
):
    """`limit=None` zwraca PEŁNY ranking, a `limit=1` naprawdę przycina.

    Porównanie „pełna lista vs TOP 5" nic nie dowodzi na bazie testowej, gdzie
    w rankingu bywa mniej niż pięć osób — obie listy byłyby wtedy identyczne.
    Dlatego przycinamy do JEDNEGO wiersza i wymagamy, żeby lista bez limitu
    była DŁUŻSZA; warunek jest spełnialny, bo test sam zasiewa trzy osoby.

    Czego ten test NIE dowodzi: że `/my-position` prosi o pełną listę. To jest
    osobna decyzja i broni jej `test_my_position_asks_for_the_whole_ranking`.
    """
    from app.services import competitions as comp_service

    await _seed_hall_of_fame_people(3)

    async with AsyncSessionLocal() as db:
        top1, scope = await comp_service.hall_of_fame_with_scope(db, limit=1)
        everyone, _ = await comp_service.hall_of_fame_with_scope(db, limit=None)

    assert len(top1) == 1, "limit=1 nie przyciął listy"
    assert scope.ranked_people >= 3, scope.ranked_people
    # To jest zdanie, które pada w kodzie sprzed poprawki, gdy limit jest
    # sztywny: pełna lista musi mieć tyle wierszy, ile mówi mianownik.
    assert len(everyone) == scope.ranked_people
    assert len(everyone) > len(top1)


@pytest.mark.asyncio
async def test_other_competition_types_have_no_scope(comp_client: AsyncClient):
    """`scope` opisuje WYŁĄCZNIE Hall of Fame.

    Pozostałe rankingi są okresowe i mają własny warunek udziału
    w `requirement`. Gdyby `scope` wyciekł na nie, front pokazałby pod
    wyścigiem zdanie o wykluczonych rolach, którego ten wyścig nie stosuje.
    """
    email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(comp_client, email, password)

    resp = await comp_client.get(
        "/api/competitions/current",
        headers=headers,
        params={"type": "monthly_placements"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["scope"] is None


@pytest.mark.asyncio
async def test_reads_still_require_a_session(comp_client: AsyncClient):
    """„Wszyscy" znaczy „każdy ZALOGOWANY", nie „każdy z internetu"."""
    resp = await comp_client.get(
        "/api/competitions/current", params={"type": "quarterly_champions_recruiter"}
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_freeze_stays_admin_only(comp_client: AsyncClient):
    """Zamrożenie podium jest nieodwracalne — D7 go NIE otwiera."""
    email, password = await _seed_user(UserRole.sourcer)
    headers = await _login(comp_client, email, password)
    resp = await comp_client.post(
        "/api/competitions/freeze",
        headers=headers,
        params={"type": "quarterly_champions_recruiter"},
    )
    assert resp.status_code in (403, 404, 405, 422), resp.text
    assert resp.status_code != 200


@pytest.mark.asyncio
async def test_hall_of_fame_cannot_be_frozen_even_by_admin(comp_client: AsyncClient):
    """Hall of Fame NIE MA okresu do zamknięcia — i broni tego API, nie baza.

    `POST /freeze` przyjmuje dowolny `CompetitionType`, a
    `competition_winners.competition_type` to `String(50)` BEZ CHECK-a, więc
    baza tego nie zatrzyma. Bez tej bramki jeden admin z curl-em zapisuje
    wiersze z `prize_pln = 0`, których nie da się usunąć (write-once), a
    `/history` podaje je potem KAŻDEJ zalogowanej roli jako „zamknięty okres".

    Test celowo loguje ADMINA: `test_freeze_stays_admin_only` obok sprawdza
    tylko, że nie-admin nie przejdzie — czyli przeszedłby także wtedy, gdyby
    tej bramki w ogóle nie było.
    """
    email, password = await _seed_user(UserRole.admin)
    headers = await _login(comp_client, email, password)

    resp = await comp_client.post(
        "/api/competitions/freeze",
        headers=headers,
        params={"type": "hall_of_fame", "period": "all_time"},
    )

    assert resp.status_code == 422, resp.text
    assert "nie ma okresu do zamknięcia" in resp.json()["detail"]

    # I NIC nie wylądowało w tabeli nagród — bramka ma zatrzymać zapis,
    # a nie tylko zwrócić błąd po jego wykonaniu.
    history = await comp_client.get(
        "/api/competitions/history",
        headers=headers,
        params={"type": "hall_of_fame"},
    )
    assert history.status_code == 200, history.text
    assert history.json()["periods"] == []
