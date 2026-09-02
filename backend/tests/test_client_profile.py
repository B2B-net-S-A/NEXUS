"""Smoke tests for GET /api/clients/{id}/profile.

Uses the in-process `app_client` fixture so tests run in CI without needing a
live uvicorn. We don't seed full pipeline/contract data — we rely on the
seed.py output that runs in the CI postgres container. Focus: endpoint
response shape + auth + 404 behavior. Deeper unit tests for the aggregation
math should go in a dedicated test_client_profile_math.py once seed data
guarantees enough contracts per client.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


pytestmark = pytest.mark.asyncio


async def test_profile_requires_auth(app_client: AsyncClient) -> None:
    resp = await app_client.get("/api/clients/1/profile")
    assert resp.status_code in (401, 403)


async def test_profile_404_for_missing_client(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    resp = await app_client.get(
        "/api/clients/99999999/profile", headers=app_auth_headers
    )
    assert resp.status_code == 404


async def test_profile_returns_expected_shape(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    # Pick any existing client from the list endpoint.
    listing = await app_client.get("/api/clients?page_size=1", headers=app_auth_headers)
    assert listing.status_code == 200
    items = listing.json().get("items") or []
    if not items:
        pytest.skip("No clients seeded — cannot exercise profile shape.")
    client_id = items[0]["id"]

    resp = await app_client.get(
        f"/api/clients/{client_id}/profile", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Top-level contract
    assert set(body.keys()) >= {
        "summary",
        "open_jobs",
        "active_consultants",
        "historical",
    }
    assert isinstance(body["open_jobs"], list)
    assert isinstance(body["active_consultants"], list)
    assert isinstance(body["historical"], dict)
    assert "placements" in body["historical"]
    assert "lost_jobs" in body["historical"]

    # Summary shape
    summary = body["summary"]
    for key in (
        "open_jobs",
        "active_consultants",
        "active_contracts",
        "total_placements",
        "active_mrr",
        "ltv",
    ):
        assert key in summary, f"missing summary.{key}"
        assert isinstance(summary[key], int)
    # avg_time_to_fill_days is Optional[float]
    assert summary.get("avg_time_to_fill_days") is None or isinstance(
        summary["avg_time_to_fill_days"], (int, float)
    )

    # Summary counters must match list lengths (the endpoint doesn't paginate
    # within a single call — it's cheaper than reconciling in UI).
    assert summary["open_jobs"] == len(body["open_jobs"])
    assert summary["active_consultants"] <= summary["active_contracts"]
    # Detached contracts have no candidate row to render, but remain contracts.
    assert summary["active_contracts"] >= len(body["active_consultants"])
    assert summary["total_placements"] == len(body["active_consultants"]) + len(
        body["historical"]["placements"]
    )


async def test_profile_active_consultants_have_candidate_brief(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """If the seed has at least one active contract, verify the candidate payload."""
    listing = await app_client.get(
        "/api/clients?page_size=25", headers=app_auth_headers
    )
    clients = listing.json().get("items") or []
    for c in clients:
        resp = await app_client.get(
            f"/api/clients/{c['id']}/profile", headers=app_auth_headers
        )
        actives = resp.json().get("active_consultants") or []
        if not actives:
            continue
        row = actives[0]
        assert "contract_id" in row
        assert isinstance(row["candidate"], dict)
        assert "id" in row["candidate"] and "name" in row["candidate"]
        return
    pytest.skip("No active consultants in any client — seed.py did not produce them.")


# ── Stawki: harmonogram, nie kolumna legacy ─────────────────────────────────
#
# Kolumna `contracts.rate_*` niesie wartość zapisaną przy ostatnim ZAPISIE
# kontraktu. Krok harmonogramu, którego data już nadeszła, zmienia stawkę BEZ
# żadnego zapisu — i to jest dokładnie ta różnica, którą profil dotąd gubił,
# pokazując starą kwotę, złą marżę i zaniżone „Aktywne MRR".


async def _seed_scheduled_contract(*, ended: bool) -> tuple[int, int]:
    """Kontrakt ze stawką, która zmieniła się w PRZESZŁOŚCI, i drugą w PRZYSZŁOŚCI.

    Zwraca ``(client_id, contract_id)``. Kolumny legacy celowo trzymają kwotę
    z pierwszego okresu — gdyby endpoint czytał je zamiast harmonogramu, testy
    niżej zobaczyłyby właśnie tę, przedawnioną wartość.
    """
    import uuid
    from datetime import date, timedelta
    from decimal import Decimal

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus
    from app.models.contract_candidate_rate import ContractCandidateRate
    from app.models.contract_client_rate import ContractClientRate
    from app.models.job import Job

    today = date.today()
    start = today - timedelta(days=400)
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Harmonogram",
            lastname=f"S-{uuid.uuid4().hex[:6]}",
            email=f"sched-{uuid.uuid4().hex[:8]}@example.com",
        )
        client = Client(name=f"SchedClient-{uuid.uuid4().hex[:6]}")
        db.add_all([cand, client])
        await db.commit()
        await db.refresh(cand)
        await db.refresh(client)

        job = Job(title="Projekt z harmonogramem", client_id=client.id)
        db.add(job)
        await db.commit()
        await db.refresh(job)

        end_date = today - timedelta(days=30) if ended else today + timedelta(days=200)
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            job_id=job.id,
            status=ContractStatus.ended if ended else ContractStatus.active,
            start_date=start,
            end_date=end_date,
            # Kolumny legacy = pierwszy okres.
            rate_candidate=Decimal("10000.000"),
            rate_client=Decimal("15000.000"),
            margin=Decimal("5000.000"),
            rate_unit="monthly",
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)

        db.add_all(
            [
                # Okres 1 (od startu) — zgodny z kolumną legacy.
                ContractCandidateRate(
                    contract_id=contract.id,
                    rate=Decimal("10000.000"),
                    effective_from=start,
                ),
                ContractClientRate(
                    contract_id=contract.id,
                    rate=Decimal("15000.000"),
                    effective_from=start,
                ),
                # Okres 2 — data już minęła, także przed zakończeniem umowy.
                ContractCandidateRate(
                    contract_id=contract.id,
                    rate=Decimal("12000.000"),
                    effective_from=today - timedelta(days=200),
                ),
                ContractClientRate(
                    contract_id=contract.id,
                    rate=Decimal("18000.000"),
                    effective_from=today - timedelta(days=200),
                ),
                # Okres 3 — data w przyszłości, NIE ma prawa pojawić się nigdzie.
                ContractCandidateRate(
                    contract_id=contract.id,
                    rate=Decimal("99000.000"),
                    effective_from=today + timedelta(days=365),
                ),
                ContractClientRate(
                    contract_id=contract.id,
                    rate=Decimal("99000.000"),
                    effective_from=today + timedelta(days=365),
                ),
            ]
        )
        await db.commit()
        return client.id, contract.id


async def test_active_consultant_rates_come_from_the_schedule(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    client_id, contract_id = await _seed_scheduled_contract(ended=False)

    resp = await app_client.get(
        f"/api/clients/{client_id}/profile", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    row = next(r for r in body["active_consultants"] if r["contract_id"] == contract_id)

    assert row["monthly_rate_candidate"] == 12000
    assert row["monthly_rate_client"] == 18000
    assert row["monthly_margin"] == 6000
    # Kafel liczy się z tego samego źródła co wiersze — inaczej suma nie
    # zgadzałaby się z tym, co widać pod nią.
    assert body["summary"]["active_mrr"] == 6000


async def test_archive_rates_are_resolved_at_the_end_date(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Archiwum to zapis historyczny, nie migawka „na dziś"."""
    client_id, contract_id = await _seed_scheduled_contract(ended=True)

    resp = await app_client.get(
        f"/api/clients/{client_id}/profile", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    row = next(
        r
        for r in resp.json()["historical"]["placements"]
        if r["contract_id"] == contract_id
    )

    assert row["monthly_rate_candidate"] == 12000
    assert row["monthly_rate_client"] == 18000
    assert row["monthly_margin"] == 6000
    # Rekrutacja linkowalna także w archiwum (dotąd był sam tytuł).
    assert row["job_id"] is not None
    assert row["job_title"] == "Projekt z harmonogramem"


async def test_archive_money_is_redacted_without_view_finance(
    app_client: AsyncClient,
) -> None:
    """Nowe pola archiwum muszą podlegać tej samej redakcji co wiersz aktywny —
    inaczej rola bez VIEW_FINANCE zobaczyłaby w archiwum dokładnie te kwoty,
    które ukrywamy jej w zakładce obok."""
    import uuid

    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    client_id, contract_id = await _seed_scheduled_contract(ended=True)

    unique = uuid.uuid4().hex[:8]
    email = f"pytest-hor-{unique}@example.com"
    password = f"T3st_{unique}!PassX"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="Pytest HoR",
                role=UserRole.head_of_recruitment,
                is_active=True,
            )
        )
        await db.commit()

    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await app_client.get(f"/api/clients/{client_id}/profile", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    row = next(
        r for r in body["historical"]["placements"] if r["contract_id"] == contract_id
    )
    assert row["monthly_rate_candidate"] is None
    assert row["monthly_rate_client"] is None
    assert row["monthly_margin"] is None
    assert row["total_revenue"] is None
    assert body["summary"]["active_mrr"] is None


# ── Fallback rekrutacji na zamówienie + zgodność kafla MRR z sumą kolumny ────


async def _seed_contract_with_order_job(*, contract_has_job: bool) -> tuple[int, int]:
    """Kontrakt + zamówienie wskazujące rekrutację. Zwraca ``(client_id, contract_id)``.

    ``contract_has_job=False`` odtwarza stan CAŁEJ bazy produkcyjnej: `Contract.job_id`
    pusty, ale `ClientOrder.job_id` wypełniony (zmierzone 2026-08-14 na 10 klientach).
    """
    import uuid
    from datetime import date, timedelta
    from decimal import Decimal

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus
    from app.models.job import Job

    today = date.today()
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Fallback",
            lastname=f"J-{uuid.uuid4().hex[:6]}",
            email=f"fb-{uuid.uuid4().hex[:8]}@example.com",
        )
        client = Client(name=f"FallbackClient-{uuid.uuid4().hex[:6]}")
        db.add_all([cand, client])
        await db.commit()
        await db.refresh(cand)
        await db.refresh(client)

        job_contract = Job(title="Rekrutacja kontraktu", client_id=client.id)
        job_order = Job(title="Rekrutacja zamówienia", client_id=client.id)
        db.add_all([job_contract, job_order])
        await db.commit()
        await db.refresh(job_contract)
        await db.refresh(job_order)

        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            job_id=job_contract.id if contract_has_job else None,
            status=ContractStatus.active,
            start_date=today - timedelta(days=100),
            end_date=today + timedelta(days=100),
            rate_candidate=Decimal("10000.000"),
            rate_client=Decimal("15000.000"),
            rate_unit="monthly",
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)

        db.add(
            ClientOrder(
                client_id=client.id,
                contract_id=contract.id,
                job_id=job_order.id,
                title="Zamówienie testowe",
                status=ClientOrderStatus.active,
                start_date=today - timedelta(days=50),
            )
        )
        await db.commit()
        return client.id, contract.id


async def test_job_falls_back_to_the_order_when_contract_has_none(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Bez tego fallbacku kolumna „rekrutacja" nie pokazałaby NICZEGO u nikogo.

    `Contract.job_id` jest pusty w całej bazie produkcyjnej (zmierzone na 10
    klientach), a `ClientOrder.job_id` bywa wypełniony."""
    client_id, contract_id = await _seed_contract_with_order_job(contract_has_job=False)

    resp = await app_client.get(
        f"/api/clients/{client_id}/profile", headers=app_auth_headers
    )
    row = next(
        r for r in resp.json()["active_consultants"] if r["contract_id"] == contract_id
    )
    assert row["job_title"] == "Rekrutacja zamówienia"
    assert row["job_id"] is not None
    # Flaga niesie INNĄ PROWENIENCJĘ — UI musi móc to rozróżnić, a nie milcząco
    # zlać dwa znaczenia w jednej kolumnie.
    assert row["job_from_order"] is True


async def test_contract_job_wins_over_the_order(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """`Contract.job_id` jest kanoniczny — fallback wchodzi tylko przy jego braku."""
    client_id, contract_id = await _seed_contract_with_order_job(contract_has_job=True)

    resp = await app_client.get(
        f"/api/clients/{client_id}/profile", headers=app_auth_headers
    )
    row = next(
        r for r in resp.json()["active_consultants"] if r["contract_id"] == contract_id
    )
    assert row["job_title"] == "Rekrutacja kontraktu"
    assert row["job_from_order"] is False


async def test_active_mrr_equals_the_sum_of_the_visible_margin_column(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Kafel ma być sumą tego, co użytkownik WIDZI pod nim.

    Każdy wiersz zaokrągla `WholePLN` osobno (half-up). Sumowanie surowych
    `Decimal`-i i zaokrąglenie raz na końcu dawało rozjazd o złotówkę (zmierzone
    na prodzie: Alior 59 211 vs 59 212) — dwie liczby obok siebie, z których
    użytkownik nie ma jak zgadnąć, która jest prawdziwa.

    Stawka GODZINOWA z groszami jest tu istotna: przy równych kwotach
    zaokrąglanie nie ma czego zepsuć i test przechodziłby także dla starej,
    błędnej implementacji.
    """
    import uuid
    from datetime import date, timedelta
    from decimal import Decimal

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus

    today = date.today()
    async with AsyncSessionLocal() as db:
        client = Client(name=f"MrrClient-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.commit()
        await db.refresh(client)
        for i in range(3):
            cand = Candidate(
                name="Mrr",
                lastname=f"C{i}-{uuid.uuid4().hex[:6]}",
                email=f"mrr-{uuid.uuid4().hex[:8]}@example.com",
            )
            db.add(cand)
            await db.commit()
            await db.refresh(cand)
            db.add(
                Contract(
                    candidate_id=cand.id,
                    client_id=client.id,
                    status=ContractStatus.active,
                    start_date=today - timedelta(days=30),
                    # 0,50 zł/h × 160 h = 80,00 zł marży — ale wprost:
                    # 100,003 × 160 = 16 000,48 → 16 000; 120,006 × 160 =
                    # 19 200,96 → 19 201. Marża surowa 3200,48 → 3200.
                    rate_candidate=Decimal("100.003"),
                    rate_client=Decimal("120.006"),
                    rate_unit="hourly",
                    billing_hours_per_month=160,
                )
            )
        await db.commit()

    resp = await app_client.get(
        f"/api/clients/{client.id}/profile", headers=app_auth_headers
    )
    body = resp.json()
    widoczna_suma = sum(r["monthly_margin"] for r in body["active_consultants"])
    assert body["summary"]["active_mrr"] == widoczna_suma


# ── Delivery Lead widzi finanse WŁASNEGO portfela ────────────────────────────
#
# „Obecni konsultanci" to obsada Delivery Leada, a stawka kosztowa,
# przychodowa i marża to trzy z pięciu kolumn tej tabeli. DL nie ma capability
# VIEW_FINANCE (steruje 40+ innymi powierzchniami, więc nie nadajemy jej
# globalnie) i do czasu tej zmiany widział w nich wyłącznie „—".


async def _seed_delivery_lead(
    client_id: int | None,
    *,
    extra_roles: list[str] | None = None,
    primary_role: str = "delivery_lead",
) -> tuple[str, str]:
    """Użytkownik z personą DL (+ opcjonalne przypisanie do klienta).

    ``client_id=None`` = DL bez przypisania do TEGO klienta — granica portfela
    zostaje pusta i trasa musi go odciąć.
    """
    import uuid

    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex[:8]
    email = f"pytest-dl-{unique}@example.com"
    password = f"T3st_{unique}!PassX"
    roles = [primary_role] + list(extra_roles or [])
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name="Pytest Delivery Lead",
            role=UserRole(primary_role),
            roles=roles,
            is_active=True,
            # `delivery_lead` ma bramkę onboardingu — bez tego nie przejdzie
            # nawet do redakcji, a test mierzyłby coś innego niż mierzy.
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        if client_id is not None:
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=user.id,
                    client_id=client_id,
                )
            )
            await db.commit()
    return email, password


async def _login_headers(
    app_client: AsyncClient, email: str, password: str
) -> dict[str, str]:
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_delivery_lead_sees_rates_and_margin_for_own_client(
    app_client: AsyncClient,
) -> None:
    """Trzy kolumny finansowe „Obecnych konsultantów" dla przypisanego DL."""
    client_id, contract_id = await _seed_scheduled_contract(ended=False)
    email, password = await _seed_delivery_lead(client_id)
    headers = await _login_headers(app_client, email, password)

    resp = await app_client.get(f"/api/clients/{client_id}/profile", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    row = next(r for r in body["active_consultants"] if r["contract_id"] == contract_id)

    assert row["monthly_rate_candidate"] == 12000, "brak stawki kosztowej dla DL"
    assert row["monthly_rate_client"] == 18000, "brak stawki przychodowej dla DL"
    # Marża = przychodowa − kosztowa, nie kolumna `contracts.margin` (ta niesie
    # kwotę z ostatniego ZAPISU kontraktu, czyli tu przedawnione 5000).
    assert row["monthly_margin"] == 6000
    assert (
        row["monthly_margin"]
        == row["monthly_rate_client"] - row["monthly_rate_candidate"]
    )
    # Kafel jest sumą kolumny „Marża" pod nim — częściowa redakcja rozjeżdżałaby
    # ten ekran ze sobą samym.
    assert body["summary"]["active_mrr"] == 6000


async def test_delivery_lead_sees_the_same_columns_in_the_archive(
    app_client: AsyncClient,
) -> None:
    """„Archiwum konsultantów" ma DOKŁADNIE te same trzy kolumny co „Obecni".

    Odsłonięcie jednej zakładki bez drugiej dałoby ten sam rozjazd co redakcja
    tylko jednej z nich, w drugą stronę.
    """
    client_id, contract_id = await _seed_scheduled_contract(ended=True)
    email, password = await _seed_delivery_lead(client_id)
    headers = await _login_headers(app_client, email, password)

    resp = await app_client.get(f"/api/clients/{client_id}/profile", headers=headers)
    assert resp.status_code == 200, resp.text
    row = next(
        r
        for r in resp.json()["historical"]["placements"]
        if r["contract_id"] == contract_id
    )
    assert row["monthly_rate_candidate"] == 12000
    assert row["monthly_rate_client"] == 18000
    assert row["monthly_margin"] == 6000


async def test_delivery_lead_outside_the_portfolio_gets_403_not_rates(
    app_client: AsyncClient,
) -> None:
    """Finanse DL kończą się na granicy JEGO portfela.

    Trasa odcina obcego klienta wcześniej niż redakcja, więc to 403, nie
    wyzerowane kwoty — ale granica musi być zmierzona, bo to na niej stoi
    zawężenie zamiast globalnej capability.
    """
    client_id, _ = await _seed_scheduled_contract(ended=False)
    email, password = await _seed_delivery_lead(None)
    headers = await _login_headers(app_client, email, password)

    resp = await app_client.get(f"/api/clients/{client_id}/profile", headers=headers)
    assert resp.status_code == 403, resp.text


async def test_head_of_recruitment_with_dl_role_sees_rates_only_in_dl_portfolio(
    app_client: AsyncClient,
) -> None:
    """Hybryda HoR+DL dziedziczy stawki DL wyłącznie we własnym portfelu.

    Sama rola HoR pozostaje poza Delivery i finansami. Dodatkowa rola DL daje
    wejście do Delivery, lecz resolver nadal zwraca konkretny zbiór przypisań,
    więc nie może rozszerzyć kwot na całą organizację.
    """
    client_id, contract_id = await _seed_scheduled_contract(ended=False)
    email, password = await _seed_delivery_lead(
        client_id,
        primary_role="head_of_recruitment",
        extra_roles=["delivery_lead"],
    )
    headers = await _login_headers(app_client, email, password)

    resp = await app_client.get(f"/api/clients/{client_id}/profile", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    row = next(r for r in body["active_consultants"] if r["contract_id"] == contract_id)
    assert row["monthly_rate_candidate"] == 12000
    assert row["monthly_rate_client"] == 18000
    assert row["monthly_margin"] == 6000
    assert body["summary"]["active_mrr"] == 18000
