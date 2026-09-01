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
    assert scope["attribution"] == "first_hired_per_candidate_job_by_mover"
    for key in (
        "ranked_placements",
        "outside_role_placements",
        "unattributed_placements",
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
