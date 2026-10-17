"""Znacznik „Pracuje u nas” na prawdziwym schemacie (12.10.2026).

Regułę sprawdza ``test_employment_marker_rule.py`` (bez bazy). Tu: zapytania
ładujące źródła i zamówienia, Delivery Lead klienta, filtr listy
``employment=ending_soon`` oraz pole ``employment_marker`` w odpowiedziach,
które do tej zmiany nie mówiły, że osoba u nas pracuje.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from httpx import AsyncClient

from app.core.scheduling import business_today


async def _seed_world() -> dict:
    """Dwóch klientów i pięć osób — po jednej na każdy stan znacznika.

    * ``ending``   — umowa u A, zamówienie kończy się za 10 dni bez kontynuacji,
    * ``extended`` — umowa u A, zamówienie za 10 dni + przedłużenie na 200 dni,
    * ``starting`` — umowa u B aktywna, start za 14 dni,
    * ``hired``    — bez umowy, bieżący etap „Zatrudniony” w rekrutacji klienta B,
    * ``idle``     — nic.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus, RateUnit
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    tag = uuid.uuid4().hex[:8]
    today = business_today()
    async with AsyncSessionLocal() as db:
        client_a = Client(name=f"MarkerA-{tag}")
        client_b = Client(name=f"marker-b-{tag}", display_name=f"Marker B {tag}")
        people = {
            key: Candidate(
                name=key.capitalize(),
                lastname=f"Marker-{tag}",
                email=f"marker-{key}-{tag}@example.com",
            )
            for key in ("ending", "extended", "starting", "hired", "idle")
        }
        db.add_all([client_a, client_b, *people.values()])
        await db.flush()

        job_a = Job(
            title=f"MarkerJobA-{tag}", status=JobStatus.published, client_id=client_a.id
        )
        job_b = Job(
            title=f"MarkerJobB-{tag}", status=JobStatus.published, client_id=client_b.id
        )
        contracts = {
            "ending": Contract(
                candidate_id=people["ending"].id,
                client_id=client_a.id,
                start_date=today - timedelta(days=200),
                status=ContractStatus.active,
            ),
            "extended": Contract(
                candidate_id=people["extended"].id,
                client_id=client_a.id,
                start_date=today - timedelta(days=200),
                status=ContractStatus.active,
            ),
            "starting": Contract(
                candidate_id=people["starting"].id,
                client_id=client_b.id,
                start_date=today + timedelta(days=14),
                status=ContractStatus.active,
            ),
        }
        db.add_all([job_a, job_b, *contracts.values()])
        await db.flush()

        def order(key: str, *, start: date, end: date) -> ClientOrder:
            return ClientOrder(
                client_id=client_a.id,
                contract_id=contracts[key].id,
                title=f"Marker-{key}-{tag}",
                status=ClientOrderStatus.active,
                start_date=start,
                end_date=end,
                rate_client=Decimal("150"),
                rate_unit=RateUnit.hourly,
            )

        db.add_all(
            [
                order(
                    "ending",
                    start=today - timedelta(days=200),
                    end=today + timedelta(days=10),
                ),
                order(
                    "extended",
                    start=today - timedelta(days=200),
                    end=today + timedelta(days=10),
                ),
                order(
                    "extended",
                    start=today + timedelta(days=11),
                    end=today + timedelta(days=200),
                ),
                CandidateStage(
                    candidate_id=people["hired"].id,
                    job_id=job_b.id,
                    stage=PipelineStage.hired,
                    moved_at=datetime.now(timezone.utc),
                ),
            ]
        )
        await db.commit()
        return {
            "today": today,
            "a": client_a.id,
            "b": client_b.id,
            "b_name": f"Marker B {tag}",
            "job_a": job_a.id,
            "job_b": job_b.id,
            **{key: person.id for key, person in people.items()},
        }


async def _markers(world: dict, *, job_client_id: int | None = None) -> dict:
    from app.core.database import AsyncSessionLocal
    from app.services.employment_marker import load_employment_markers

    keys = ("ending", "extended", "starting", "hired", "idle")
    async with AsyncSessionLocal() as db:
        found = await load_employment_markers(
            db,
            [world[key] for key in keys],
            today=world["today"],
            job_client_id=job_client_id,
        )
    return {key: found[world[key]] for key in keys}


# ── ładowanie ───────────────────────────────────────────────────────────────


async def test_loader_returns_every_id_and_one_phase_per_state():
    world = await _seed_world()

    markers = await _markers(world)

    assert markers["idle"] is None
    assert (markers["ending"].phase, markers["ending"].source) == ("ending", "contract")
    assert markers["ending"].clients[0].order_end_date == world["today"] + timedelta(
        days=10
    )
    assert (markers["starting"].phase, markers["starting"].source) == (
        "starting",
        "contract",
    )
    assert markers["starting"].clients[0].starts_on == world["today"] + timedelta(
        days=14
    )
    # 17.10.2026: „Zatrudniony” bez umowy nie daje znacznika — tylko umowa.
    assert markers["hired"] is None
    assert all(marker.elsewhere is None for marker in markers.values() if marker)


async def test_extension_moves_the_end_of_cooperation():
    """Zamówienie do końca miesiąca z przedłużeniem nie daje „kończy”."""
    world = await _seed_world()

    marker = (await _markers(world))["extended"]

    assert marker.phase == "working"
    assert marker.clients[0].order_end_date == world["today"] + timedelta(days=200)


async def test_elsewhere_is_relative_to_the_recruitment_client():
    world = await _seed_world()

    at_a = await _markers(world, job_client_id=world["a"])

    assert at_a["ending"].elsewhere is False
    assert at_a["starting"].elsewhere is True
    assert at_a["hired"] is None


async def test_delivery_lead_is_the_active_head_with_the_role():
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole
    from app.services.employment_marker import client_delivery_leads

    tag = uuid.uuid4().hex[:8]

    def user(name: str, role: UserRole, *, active: bool = True) -> User:
        return User(
            email=f"marker-{name}-{tag}@example.com",
            password_hash="test-only",
            name=f"{name} {tag}",
            role=role,
            roles=[role.value],
            is_active=active,
        )

    async with AsyncSessionLocal() as db:
        with_head = Client(name=f"MarkerHead-{tag}")
        without_head = Client(name=f"MarkerNoHead-{tag}")
        nobody = Client(name=f"MarkerNobody-{tag}")
        head = user("head", UserRole.delivery_lead)
        deputy = user("deputy", UserRole.delivery_lead)
        former = user("former", UserRole.recruiter)
        inactive = user("inactive", UserRole.delivery_lead, active=False)
        db.add_all([with_head, without_head, nobody, head, deputy, former, inactive])
        await db.flush()

        def assign(client: Client, lead: User, *, is_head: bool = False):
            return DeliveryLeadClientAssignment(
                delivery_lead_user_id=lead.id, client_id=client.id, is_head=is_head
            )

        db.add_all(
            [
                assign(with_head, deputy),
                assign(with_head, head, is_head=True),
                # Sam wiersz przypisania nie jest grantem: zmieniona rola
                # i nieaktywne konto nie są Delivery Leadem klienta.
                assign(without_head, former, is_head=True),
                assign(without_head, inactive),
                assign(without_head, deputy),
            ]
        )
        await db.commit()
        ids = [with_head.id, without_head.id, nobody.id]
        leads = await client_delivery_leads(db, ids)

    assert leads == {ids[0]: f"head {tag}", ids[1]: f"deputy {tag}"}


# ── API: lista kandydatów ───────────────────────────────────────────────────


async def _list(app_client: AsyncClient, headers: dict, employment: str) -> dict:
    resp = await app_client.get(
        f"/api/candidates?employment={employment}&page_size=100", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return {item["id"]: item for item in resp.json()["items"]}


async def test_list_marker_exists_exactly_when_employment_says_employed(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Stare pole i znacznik nie mogą sobie przeczyć na tej samej stronie."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.contract import Contract, ContractStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    world = await _seed_world()
    # Były konsultant (audyt 13.10, pkt 13; 14.10.2026): stary „Zatrudniony”
    # u klienta A, umowa u A zakończona rok po zatrudnieniu. Znacznik, stare
    # pole i filtr mówią to samo — nie pracuje u nas.
    async with AsyncSessionLocal() as db:
        former = Candidate(
            name="Former",
            lastname=f"Marker-{uuid.uuid4().hex[:8]}",
            email=f"marker-former-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(former)
        await db.flush()
        db.add_all(
            [
                CandidateStage(
                    candidate_id=former.id,
                    job_id=world["job_a"],
                    stage=PipelineStage.hired,
                    moved_at=datetime.now(timezone.utc) - timedelta(days=730),
                ),
                Contract(
                    candidate_id=former.id,
                    client_id=world["a"],
                    job_id=world["job_a"],
                    start_date=world["today"] - timedelta(days=700),
                    end_date=world["today"] - timedelta(days=365),
                    terminated_at=world["today"] - timedelta(days=365),
                    status=ContractStatus.ended,
                ),
            ]
        )
        await db.commit()
        former_id = former.id

    at_client = await _list(app_client, app_auth_headers, "at_client")
    available = await _list(app_client, app_auth_headers, "available")

    assert former_id not in at_client
    assert available[former_id]["employment"]["state"] == "on_bench"
    assert available[former_id]["employment_marker"] is None

    for key, phase in (
        ("ending", "ending"),
        ("extended", "working"),
        # Umowa ze startem w przyszłości: „nasza”, ale jeszcze nie pracuje.
        ("starting", "starting"),
    ):
        item = at_client[world[key]]
        assert item["employment"]["state"] == "employed_at_client", key
        assert item["employment_marker"]["phase"] == phase, key
        assert world[key] not in available, key
    idle = available[world["idle"]]
    assert idle["employment"]["state"] != "employed_at_client"
    assert idle["employment_marker"] is None
    # 17.10.2026: „Zatrudniony” bez umowy — nie pracuje u nas (tylko umowa).
    hired = available[world["hired"]]
    assert hired["employment"]["state"] == "on_bench"
    assert hired["employment_marker"] is None


async def test_ending_soon_filter_lists_only_people_without_continuation(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _seed_world()

    ending_soon = await _list(app_client, app_auth_headers, "ending_soon")

    assert world["ending"] in ending_soon
    for key in ("extended", "starting", "hired", "idle"):
        assert world[key] not in ending_soon, key


async def test_employment_filter_ignores_combined_values(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Filtr działa dla jednej wartości; połączenie = bez filtra, jak dotąd."""
    world = await _seed_world()

    resp = await app_client.get(
        "/api/candidates?employment=ending_soon&employment=available&page_size=100",
        headers=app_auth_headers,
    )

    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()["items"]}
    assert {world["ending"], world["idle"]} <= ids


async def test_detail_and_quick_view_carry_the_marker(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _seed_world()

    detail = await app_client.get(
        f"/api/candidates/{world['ending']}", headers=app_auth_headers
    )
    quick = await app_client.get(
        f"/api/candidates/{world['ending']}/quick-view", headers=app_auth_headers
    )

    assert detail.status_code == 200, detail.text
    assert quick.status_code == 200, quick.text
    assert detail.json()["employment_marker"]["phase"] == "ending"
    assert (
        quick.json()["candidate"]["employment_marker"]["clients"][0]["client_id"]
        == (world["a"])
    )


# ── API: Tablica ────────────────────────────────────────────────────────────


def _cards(board: dict) -> dict[int, dict]:
    cards = [card for column in board["columns"] for card in column["items"]]
    bucket = board.get("off_template")
    if bucket:
        cards.extend(bucket["items"])
    return {card["candidate_id"]: card for card in cards}


async def test_board_card_says_the_person_works_for_another_client(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Karta w rekrutacji klienta B: osoba ma trwającą umowę u klienta A."""
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    world = await _seed_world()
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                CandidateStage(
                    candidate_id=world[key],
                    job_id=world["job_b"],
                    stage=PipelineStage.new,
                    moved_at=datetime.now(timezone.utc),
                )
                for key in ("ending", "idle")
            ]
        )
        await db.commit()

    resp = await app_client.get(
        f"/api/pipeline/kanban/{world['job_b']}", headers=app_auth_headers
    )

    assert resp.status_code == 200, resp.text
    cards = _cards(resp.json())
    marker = cards[world["ending"]]["employment_marker"]
    assert (marker["phase"], marker["elsewhere"]) == ("ending", True)
    assert marker["clients"][0]["client_id"] == world["a"]
    assert cards[world["idle"]]["employment_marker"] is None
    # Osoba zatrudniona w tej rekrutacji bez umowy: bez znacznika, za to
    # karta mówi, że w Kontraktach brakuje umowy (17.10.2026).
    assert cards[world["hired"]]["employment_marker"] is None
    assert cards[world["hired"]]["missing_contract"] is True
    assert cards[world["ending"]]["missing_contract"] is False
