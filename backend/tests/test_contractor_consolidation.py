"""Konsolidacja kontraktorów pracujących u wielu klientów naraz (2026-08-25).

Cztery zazębiające się kontrakty zachowań z jednego PR-a:

1. ``GET /api/contracts?group_by_candidate=true`` — jeden wiersz na OSOBĘ,
   wszystkie jej umowy w ``group_members`` (rozbicie okresu/stawek per klient),
   ``total`` liczy grupy; tryb płaski bez zmian.
2. ``GET /api/contracts/{id}`` — ``related_contracts`` (pozostałe umowy tej
   samej osoby, bez ``void``) zasila zakładki nazwane po kliencie.
3. ``POST /api/contracts`` — duplikat kontraktora wykrywany po E-MAILU
   (case-insensitive), nie po nazwisku; blokuje wyłącznie parę osoba+klient
   w żywym statusie. Drugi klient tej samej osoby NIE jest duplikatem.
4. ``DELETE /api/contracts/{id}`` — usuwa kontrakt w każdym statusie (poza
   PODPISANYMI dowodami: ukończony podpis kwalifikowany / umowa B2B
   ``signed_both``), odpinając NIEPODPISANE wygenerowane umowy B2B
   (FK RESTRICT) zamiast wywracać się 500-tką; rejestr „Wygenerowane umowy"
   i kandydat zostają nietknięci.

Wszystkie seedy niosą unikalny marker w nazwisku, więc asercje list idą przez
``?q=<marker>`` i nie widzą danych z sąsiednich testów na współdzielonej bazie.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import (
    Contract,
    ContractStatus,
    ContractType,
    ContractWorkMode,
    RateUnit,
)
from app.models.job import Job

pytestmark = pytest.mark.asyncio


# ── Seed helpers ─────────────────────────────────────────────────────────────


async def _seed_candidate(
    marker: str,
    *,
    email: str | None,
    suffix: str = "",
    first_name: str = "Multi",
    last_name: str | None = None,
) -> int:
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=first_name,
            lastname=last_name if last_name is not None else f"{marker}{suffix}",
            email=email,
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        return cand.id


async def _seed_client(name: str, *, display_name: str | None = None) -> int:
    async with AsyncSessionLocal() as db:
        cli = Client(name=name, display_name=display_name)
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        return cli.id


async def _seed_job(client_id: int, marker: str) -> int:
    async with AsyncSessionLocal() as db:
        job = Job(title=f"Rekrutacja {marker}", client_id=client_id)
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_contract(
    candidate_id: int,
    client_id: int,
    *,
    status: ContractStatus = ContractStatus.active,
    rate_candidate: int | None = 125,
    rate_client: int | None = 175,
) -> int:
    async with AsyncSessionLocal() as db:
        contract = Contract(
            candidate_id=candidate_id,
            client_id=client_id,
            contract_type=ContractType.b2b,
            status=status,
            start_date=date.today() - timedelta(days=30),
            end_date=date.today() + timedelta(days=90),
            rate_candidate=rate_candidate,
            rate_client=rate_client,
            rate_unit=RateUnit.hourly,
            work_mode=ContractWorkMode.remote,
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return contract.id


async def _role_headers(
    app_client: AsyncClient,
    role_value: str,
    *,
    assigned_client_id: int | None = None,
) -> dict[str, str]:
    """Zaloguj świeży rolowy login; DL dostaje opcjonalne przypisanie klienta."""
    from app.core.security import hash_password
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole

    email = f"cons-{role_value}-{uuid.uuid4().hex[:8]}@example.com"
    password = f"P4ss_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Cons {role_value}",
            role=UserRole(role_value),
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.flush()
        if assigned_client_id is not None:
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=user.id,
                    client_id=assigned_client_id,
                )
            )
        await db.commit()
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _tac_headers(app_client: AsyncClient) -> dict[str, str]:
    """Zaloguj świeżego TAC-a (rola bez VIEW_FINANCE) — do testu redakcji."""
    return await _role_headers(app_client, "tac")


# ── 1. Zgrupowana lista ──────────────────────────────────────────────────────


async def test_grouped_list_one_row_per_person(app_client, app_auth_headers):
    marker = f"Grp{uuid.uuid4().hex[:6]}"
    cand_multi = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    cand_solo = await _seed_candidate(
        marker, email=f"{marker.lower()}-solo@example.com", suffix="Solo"
    )
    c1 = await _seed_client(f"BP {marker}", display_name=f"Bank Pocztowy S.A. {marker}")
    c2 = await _seed_client(f"Velo {marker}", display_name=f"VeloBank S.A. {marker}")
    c3 = await _seed_client(f"Trzeci {marker}")
    id_a = await _seed_contract(cand_multi, c1, rate_client=175, rate_candidate=125)
    id_b = await _seed_contract(cand_multi, c2, rate_client=163, rate_candidate=120)
    id_solo = await _seed_contract(cand_solo, c3)

    grouped = await app_client.get(
        "/api/contracts",
        params={"q": marker, "group_by_candidate": "true", "page_size": 50},
        headers=app_auth_headers,
    )
    assert grouped.status_code == 200, grouped.text
    body = grouped.json()
    # Dwie OSOBY, nie trzy umowy.
    assert body["total"] == 2
    assert body["contractors_total"] == 2
    assert body["contracts_total"] == 3
    rows = {row["candidate_id"]: row for row in body["items"]}
    assert set(rows) == {cand_multi, cand_solo}

    multi_row = rows[cand_multi]
    assert multi_row["client_name"] in {
        f"Bank Pocztowy S.A. {marker}",
        f"VeloBank S.A. {marker}",
    }
    members = multi_row["group_members"]
    assert {m["id"] for m in members} == {id_a, id_b}
    assert {m["client_name"] for m in members} == {
        f"Bank Pocztowy S.A. {marker}",
        f"VeloBank S.A. {marker}",
    }
    # Rozbicie stawek per klient (kosztowa = kandydata, przychodowa = klienta).
    by_client = {m["client_name"]: m for m in members}
    assert by_client[f"Bank Pocztowy S.A. {marker}"]["rate_client"] == 175
    assert by_client[f"Bank Pocztowy S.A. {marker}"]["rate_candidate"] == 125
    assert by_client[f"Bank Pocztowy S.A. {marker}"]["margin"] == 50
    assert by_client[f"VeloBank S.A. {marker}"]["rate_client"] == 163

    solo_row = rows[cand_solo]
    assert [m["id"] for m in solo_row["group_members"]] == [id_solo]

    # Tryb płaski (domyślny) bez zmian: trzy wiersze, bez członków grupy.
    flat = await app_client.get(
        "/api/contracts",
        params={"q": marker, "page_size": 50},
        headers=app_auth_headers,
    )
    assert flat.status_code == 200, flat.text
    assert flat.json()["total"] == 3
    assert flat.json()["contractors_total"] == 2
    assert flat.json()["contracts_total"] == 3
    assert all(row["group_members"] == [] for row in flat.json()["items"])


async def test_list_metadata_deduplicates_duplicate_piotr_profiles(
    app_client, app_auth_headers
):
    marker = f"CntPiotr{uuid.uuid4().hex[:6]}"
    piotr_a = await _seed_candidate(
        marker,
        email=f"first-{marker.lower()}@example.com",
        first_name=" Piotr ",
        last_name="Klimczak",
    )
    piotr_b = await _seed_candidate(
        marker,
        email=f"second-{marker.lower()}@example.com",
        # Exercises the SQL identity path's special-character transliteration
        # (the Python helper uses the same Piøtr -> piotr rule).
        first_name="PIØTR",
        last_name="Klim-czak",
    )
    client_a = await _seed_client(f"A {marker}")
    client_b = await _seed_client(f"B {marker}")
    await _seed_contract(piotr_a, client_a)
    await _seed_contract(piotr_b, client_b)

    response = await app_client.get(
        "/api/contracts",
        params={
            "q": marker,
            "status": "active",
            "group_by_candidate": "true",
            "page_size": 50,
        },
        headers=app_auth_headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    # Pagination still has two candidate-id groups, while the headline applies
    # the business identity key across both profiles.
    assert body["total"] == 2
    assert body["contractors_total"] == 1
    assert body["contracts_total"] == 2


async def test_list_metadata_keeps_two_filip_jablonski_emails_separate(
    app_client, app_auth_headers
):
    marker = f"CntFilip{uuid.uuid4().hex[:6]}"
    filip_a = await _seed_candidate(
        marker,
        email=f"first-{marker.lower()}@example.com",
        first_name="Filip",
        last_name="Jabłoński",
    )
    filip_b = await _seed_candidate(
        marker,
        email=f"second-{marker.lower()}@example.com",
        first_name=" FILIP ",
        last_name="JABLONSKI",
    )
    client_a = await _seed_client(f"A {marker}")
    client_b = await _seed_client(f"B {marker}")
    await _seed_contract(filip_a, client_a)
    await _seed_contract(filip_b, client_b)

    response = await app_client.get(
        "/api/contracts",
        params={
            "q": marker,
            "status": "active",
            "group_by_candidate": "true",
            "page_size": 50,
        },
        headers=app_auth_headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    assert body["contractors_total"] == 2
    assert body["contracts_total"] == 2


async def test_list_metadata_deduplicates_non_latin_names(app_client, app_auth_headers):
    marker = f"CntUnicode{uuid.uuid4().hex[:6]}"
    candidate_a = await _seed_candidate(
        marker,
        email=f"first-{marker.lower()}@example.com",
        first_name="Олена",
        last_name="Коваль",
    )
    candidate_b = await _seed_candidate(
        marker,
        email=f"second-{marker.lower()}@example.com",
        first_name=" ОЛЕНА ",
        last_name="КОВАЛЬ",
    )
    client_a = await _seed_client(f"A {marker}")
    client_b = await _seed_client(f"B {marker}")
    await _seed_contract(candidate_a, client_a)
    await _seed_contract(candidate_b, client_b)

    response = await app_client.get(
        "/api/contracts",
        params={
            "q": marker,
            "status": "active",
            "group_by_candidate": "true",
            "page_size": 50,
        },
        headers=app_auth_headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    assert body["contractors_total"] == 1
    assert body["contracts_total"] == 2


async def test_grouped_list_respects_filters_within_group(app_client, app_auth_headers):
    """Filtr statusu zawęża też CZŁONKÓW grupy — wiersz pod nagłówkiem
    „aktywne" nie może przemycać zakończonej umowy w rozbiciu per klient."""
    marker = f"Grf{uuid.uuid4().hex[:6]}"
    cand = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    c1 = await _seed_client(f"Aktywny {marker}")
    c2 = await _seed_client(f"Zakonczony {marker}")
    id_active = await _seed_contract(cand, c1, status=ContractStatus.active)
    await _seed_contract(cand, c2, status=ContractStatus.ended)

    resp = await app_client.get(
        "/api/contracts",
        params={
            "q": marker,
            "group_by_candidate": "true",
            "status": "active",
            "page_size": 50,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    members = body["items"][0]["group_members"]
    assert [m["id"] for m in members] == [id_active]


async def test_grouped_list_redacts_member_rates_for_non_finance(app_client):
    marker = f"Grr{uuid.uuid4().hex[:6]}"
    cand = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    c1 = await _seed_client(f"RedA {marker}")
    c2 = await _seed_client(f"RedB {marker}")
    await _seed_contract(cand, c1)
    await _seed_contract(cand, c2)

    headers = await _role_headers(app_client, "talent_community_manager")
    resp = await app_client.get(
        "/api/contracts",
        params={"q": marker, "group_by_candidate": "true", "page_size": 50},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    [row] = resp.json()["items"]
    assert len(row["group_members"]) == 2
    for member in row["group_members"]:
        # Operacyjnie widoczny (klient, okres, status)…
        assert member["client_name"]
        assert member["status"] == "active"
        # …ale kwoty per klient wyzerowane jak wiersz główny.
        assert member["rate_candidate"] is None
        assert member["rate_client"] is None
        assert member["margin"] is None


async def test_grouped_list_and_siblings_give_dl_all_clients_with_redaction(app_client):
    """DL widzi umowy obu klientów, ale finanse tylko klienta przypisanego."""
    marker = f"Dls{uuid.uuid4().hex[:6]}"
    cand = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    client_a = await _seed_client(f"PortfelDL {marker}")
    client_b = await _seed_client(f"ObcyKlient {marker}")
    id_a = await _seed_contract(cand, client_a)
    id_b = await _seed_contract(cand, client_b)

    dl_headers = await _role_headers(
        app_client, "delivery_lead", assigned_client_id=client_a
    )

    grouped = await app_client.get(
        "/api/contracts",
        params={"q": marker, "group_by_candidate": "true", "page_size": 50},
        headers=dl_headers,
    )
    assert grouped.status_code == 200, grouped.text
    body = grouped.json()
    assert body["total"] == 1
    [row] = body["items"]
    members = {member["id"]: member for member in row["group_members"]}
    assert set(members) == {id_a, id_b}
    assert members[id_a]["rate_client"] is not None
    assert members[id_b]["rate_client"] is None

    detail = await app_client.get(f"/api/contracts/{id_a}", headers=dl_headers)
    assert detail.status_code == 200, detail.text
    assert [item["id"] for item in detail.json()["related_contracts"]] == [id_b]

    # Kontrakt poza portfelem finansowym jest widoczny, ale bez kwot.
    outside = await app_client.get(f"/api/contracts/{id_b}", headers=dl_headers)
    assert outside.status_code == 200, outside.text
    assert outside.json()["rate_client"] is None
    assert outside.json()["rate_candidate"] is None


# ── 2. Zakładki per klient w szczegółach ─────────────────────────────────────


async def test_detail_lists_sibling_contracts_of_same_person(
    app_client, app_auth_headers
):
    marker = f"Sib{uuid.uuid4().hex[:6]}"
    cand = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    c1 = await _seed_client(
        f"Pierwszy {marker}", display_name=f"Pierwszy Klient S.A. {marker}"
    )
    c2 = await _seed_client(
        f"Drugi {marker}", display_name=f"Drugi Klient S.A. {marker}"
    )
    c3 = await _seed_client(f"Anulowany {marker}")
    id_a = await _seed_contract(cand, c1)
    id_b = await _seed_contract(cand, c2)
    await _seed_contract(cand, c3, status=ContractStatus.void)

    detail = await app_client.get(f"/api/contracts/{id_a}", headers=app_auth_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["client_name"] == f"Pierwszy Klient S.A. {marker}"
    related = detail.json()["related_contracts"]
    # Rodzeństwo = druga umowa tej osoby; `void` nie jest zakładką.
    assert [r["id"] for r in related] == [id_b]
    assert related[0]["client_name"] == f"Drugi Klient S.A. {marker}"
    assert related[0]["status"] == "active"

    # Symetria: z perspektywy drugiej umowy widać pierwszą.
    detail_b = await app_client.get(f"/api/contracts/{id_b}", headers=app_auth_headers)
    assert [r["id"] for r in detail_b.json()["related_contracts"]] == [id_a]


# ── 3. Duplikat kontraktora po e-mailu ───────────────────────────────────────


async def _post_contract(app_client, headers, candidate_id, client_id, **extra):
    payload = {
        "candidate_id": candidate_id,
        "client_id": client_id,
        "start_date": date.today().isoformat(),
        **extra,
    }
    return await app_client.post("/api/contracts", json=payload, headers=headers)


async def test_duplicate_same_person_same_client_blocked(app_client, app_auth_headers):
    marker = f"Dup{uuid.uuid4().hex[:6]}"
    email = f"{marker.lower()}@example.com"
    cand = await _seed_candidate(marker, email=email)
    cli = await _seed_client(f"DupKlient {marker}")

    first = await _post_contract(app_client, app_auth_headers, cand, cli)
    assert first.status_code == 201, first.text

    second = await _post_contract(app_client, app_auth_headers, cand, cli)
    assert second.status_code == 409, second.text
    detail = second.json()["detail"]
    assert detail["code"] == "duplicate_contractor"
    assert email in detail["message"]
    assert detail["existing_contract_id"] == first.json()["id"]


async def test_duplicate_detected_by_email_across_candidate_records(
    app_client, app_auth_headers
):
    """Ta sama osoba pod DWOMA rekordami kandydata (różnice wielkości liter
    w e-mailu, literówka w nazwisku) — to jest właśnie duplikat, którego
    porównanie po nazwisku nie łapie."""
    marker = f"Dpe{uuid.uuid4().hex[:6]}"
    cand_a = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    cand_b = await _seed_candidate(
        marker, email=f"{marker.upper()}@EXAMPLE.COM", suffix="Literowka"
    )
    cli = await _seed_client(f"DupEmail {marker}")

    first = await _post_contract(app_client, app_auth_headers, cand_a, cli)
    assert first.status_code == 201, first.text

    second = await _post_contract(app_client, app_auth_headers, cand_b, cli)
    assert second.status_code == 409, second.text
    assert second.json()["detail"]["code"] == "duplicate_contractor"


async def test_second_client_is_not_a_duplicate(app_client, app_auth_headers):
    """Feature wieloklientowy: druga umowa TEJ SAMEJ osoby u INNEGO klienta
    przechodzi — to jest „+ Dodaj kolejny projekt", nie duplikat."""
    marker = f"Dk2{uuid.uuid4().hex[:6]}"
    cand = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    cli_a = await _seed_client(f"KlientA {marker}")
    cli_b = await _seed_client(f"KlientB {marker}")

    first = await _post_contract(app_client, app_auth_headers, cand, cli_a)
    assert first.status_code == 201, first.text
    second = await _post_contract(app_client, app_auth_headers, cand, cli_b)
    assert second.status_code == 201, second.text


async def test_add_project_active_creates_linked_draft_order_without_signature(
    app_client, app_auth_headers, monkeypatch
):
    """„Dodaj kolejny projekt” is one transaction: active Contract + draft Order."""

    monkeypatch.setattr(settings, "SIGNING_ENABLED", True)
    marker = f"Ord{uuid.uuid4().hex[:6]}"
    cand = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    cli_a = await _seed_client(f"Pierwszy {marker}")
    cli_b = await _seed_client(f"Kolejny {marker}")
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, cand)
        assert candidate is not None
        candidate.name = "?"
        candidate.lastname = "?"
        await db.commit()
    source_contract_id = await _seed_contract(cand, cli_a)

    response = await _post_contract(
        app_client,
        app_auth_headers,
        cand,
        cli_b,
        status="active",
        contract_type="b2b",
        work_mode="remote",
        rate_candidate=125,
        rate_client=175,
        source_contract_id=source_contract_id,
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "active"
    assert isinstance(response.json()["draft_order_id"], int)
    contract_id = response.json()["id"]
    async with AsyncSessionLocal() as db:
        orders = list(
            (
                await db.scalars(
                    select(ClientOrder).where(
                        ClientOrder.contract_id == contract_id,
                        ClientOrder.client_id == cli_b,
                    )
                )
            ).all()
        )
    assert len(orders) == 1
    [order] = orders
    assert response.json()["draft_order_id"] == order.id
    assert order.status == ClientOrderStatus.draft
    assert order.filled_at is None
    assert order.title == "(bez numeru)"
    assert order.job_id is None  # rekrutacja w dialogu jest opcjonalna
    assert f"kandydata id={cand}" in (order.notes or "")
    assert "? ?" not in (order.notes or "")


async def test_add_project_does_not_create_invisible_draft_for_cost_order_client(
    app_client, app_auth_headers, monkeypatch
):
    """Cost-order clients need an explicit order type, so no orphan draft."""

    marker = f"Cst{uuid.uuid4().hex[:6]}"
    cand = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    cli_a = await _seed_client(f"Pierwszy {marker}")
    cli_b = await _seed_client(f"Kosztowy {marker}")
    source_contract_id = await _seed_contract(cand, cli_a)
    monkeypatch.setattr(settings, "COST_ORDER_CLIENT_IDS", str(cli_b))

    response = await _post_contract(
        app_client,
        app_auth_headers,
        cand,
        cli_b,
        status="active",
        contract_type="b2b",
        work_mode="remote",
        rate_candidate=125,
        rate_client=175,
        source_contract_id=source_contract_id,
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "active"
    assert response.json()["draft_order_id"] is None
    async with AsyncSessionLocal() as db:
        order_id = await db.scalar(
            select(ClientOrder.id).where(
                ClientOrder.contract_id == response.json()["id"]
            )
        )
    assert order_id is None


async def test_add_project_rejects_recruitment_from_another_client(
    app_client, app_auth_headers
):
    marker = f"Job{uuid.uuid4().hex[:6]}"
    cand = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    cli_a = await _seed_client(f"Pierwszy {marker}")
    cli_b = await _seed_client(f"Kolejny {marker}")
    source_contract_id = await _seed_contract(cand, cli_a)
    wrong_job_id = await _seed_job(cli_a, marker)

    response = await _post_contract(
        app_client,
        app_auth_headers,
        cand,
        cli_b,
        job_id=wrong_job_id,
        source_contract_id=source_contract_id,
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "job_client_mismatch"
    async with AsyncSessionLocal() as db:
        created_id = await db.scalar(
            select(Contract.id).where(
                Contract.candidate_id == cand,
                Contract.client_id == cli_b,
            )
        )
    assert created_id is None


async def test_add_project_rejects_terminal_status_before_creating_order(
    app_client, app_auth_headers
):
    marker = f"Sts{uuid.uuid4().hex[:6]}"
    cand = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    cli_a = await _seed_client(f"Pierwszy {marker}")
    cli_b = await _seed_client(f"Kolejny {marker}")
    source_contract_id = await _seed_contract(cand, cli_a)

    response = await _post_contract(
        app_client,
        app_auth_headers,
        cand,
        cli_b,
        status="ended",
        source_contract_id=source_contract_id,
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "add_project_status_invalid"
    async with AsyncSessionLocal() as db:
        created_id = await db.scalar(
            select(Contract.id).where(
                Contract.candidate_id == cand,
                Contract.client_id == cli_b,
            )
        )
    assert created_id is None


async def test_concurrent_add_project_creates_one_contract_and_one_order(
    app_client, app_auth_headers
):
    marker = f"Rac{uuid.uuid4().hex[:6]}"
    cand = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    cli_a = await _seed_client(f"Pierwszy {marker}")
    cli_b = await _seed_client(f"Kolejny {marker}")
    source_contract_id = await _seed_contract(cand, cli_a)
    payload = {
        "status": "active",
        "contract_type": "b2b",
        "work_mode": "remote",
        "rate_candidate": 125,
        "rate_client": 175,
        "source_contract_id": source_contract_id,
    }

    first, second = await asyncio.gather(
        _post_contract(app_client, app_auth_headers, cand, cli_b, **payload),
        _post_contract(app_client, app_auth_headers, cand, cli_b, **payload),
    )

    assert sorted([first.status_code, second.status_code]) == [201, 409]
    conflict = first if first.status_code == 409 else second
    assert conflict.json()["detail"]["code"] == "duplicate_contractor"
    async with AsyncSessionLocal() as db:
        contracts = list(
            (
                await db.scalars(
                    select(Contract).where(
                        Contract.candidate_id == cand,
                        Contract.client_id == cli_b,
                    )
                )
            ).all()
        )
        orders = list(
            (
                await db.scalars(
                    select(ClientOrder).where(ClientOrder.client_id == cli_b)
                )
            ).all()
        )
    assert len(contracts) == 1
    assert len(orders) == 1
    assert orders[0].contract_id == contracts[0].id
    assert orders[0].status == ClientOrderStatus.draft


async def test_concurrent_add_project_serializes_duplicate_candidate_records(
    app_client, app_auth_headers
):
    """The e-mail identity lock also covers two imported Candidate rows."""

    marker = f"EmR{uuid.uuid4().hex[:6]}"
    shared_email = f"{marker.lower()}@example.com"
    cand_a = await _seed_candidate(marker, email=shared_email)
    cand_b = await _seed_candidate(
        marker, email=f"  {shared_email.upper()}\n", suffix="Import"
    )
    source_client_a = await _seed_client(f"Pierwszy A {marker}")
    source_client_b = await _seed_client(f"Pierwszy B {marker}")
    target_client = await _seed_client(f"Kolejny {marker}")
    source_contract_a = await _seed_contract(cand_a, source_client_a)
    source_contract_b = await _seed_contract(cand_b, source_client_b)

    first, second = await asyncio.gather(
        _post_contract(
            app_client,
            app_auth_headers,
            cand_a,
            target_client,
            source_contract_id=source_contract_a,
        ),
        _post_contract(
            app_client,
            app_auth_headers,
            cand_b,
            target_client,
            source_contract_id=source_contract_b,
        ),
    )

    assert sorted([first.status_code, second.status_code]) == [201, 409]
    conflict = first if first.status_code == 409 else second
    assert conflict.json()["detail"]["code"] == "duplicate_contractor"
    async with AsyncSessionLocal() as db:
        contracts = list(
            (
                await db.scalars(
                    select(Contract).where(
                        Contract.client_id == target_client,
                        Contract.candidate_id.in_([cand_a, cand_b]),
                    )
                )
            ).all()
        )
        orders = list(
            (
                await db.scalars(
                    select(ClientOrder).where(ClientOrder.client_id == target_client)
                )
            ).all()
        )
    assert len(contracts) == 1
    assert len(orders) == 1
    assert orders[0].contract_id == contracts[0].id


async def test_return_after_ended_contract_is_not_a_duplicate(
    app_client, app_auth_headers
):
    marker = f"Dke{uuid.uuid4().hex[:6]}"
    cand = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    cli = await _seed_client(f"Powrot {marker}")
    await _seed_contract(cand, cli, status=ContractStatus.ended)

    resp = await _post_contract(app_client, app_auth_headers, cand, cli)
    assert resp.status_code == 201, resp.text


async def test_create_with_unknown_candidate_is_a_clean_404(
    app_client, app_auth_headers
):
    """Nieistniejące id ma zwracać czytelny polski komunikat, nie FK-500."""
    cli = await _seed_client(f"Ghost {uuid.uuid4().hex[:6]}")
    resp = await _post_contract(app_client, app_auth_headers, 99_999_999, cli)
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["code"] == "candidate_not_found"


# ── 4. DELETE odpina wygenerowane umowy B2B ──────────────────────────────────


async def _seed_generated(
    marker: str,
    contract_id: int,
    candidate_id: int,
    *,
    signature_status: str,
    client_id: int | None = None,
) -> int:
    """``client_id=None`` odwzorowuje wiersz historyczny (0196 bez backfillu)
    i umowę standalone — obie NIE mówią, którego projektu dotyczy podpis."""
    async with AsyncSessionLocal() as db:
        generated = B2BGeneratedContract(
            year=2026,
            seq=int(uuid.uuid4().hex[:6], 16),
            contract_number=f"B2B/TEST/{marker}",
            partner_name=f"Multi {marker}",
            signature_status=signature_status,
            contract_id=contract_id,
            candidate_id=candidate_id,
            client_id=client_id,
        )
        db.add(generated)
        await db.commit()
        await db.refresh(generated)
        return generated.id


async def test_shared_hard_delete_service_applies_fk_policies_and_audits():
    """Batch callers get the same detach/CASCADE/SET NULL/audit contract.

    This calls the lifecycle helper directly, so moving logic back into the
    HTTP endpoint cannot silently make one-off maintenance less safe.
    """
    from decimal import Decimal

    from sqlalchemy import select

    from app.models.activity import Activity
    from app.models.contract_candidate_rate import ContractCandidateRate
    from app.models.note import Note
    from app.services.contract_lifecycle import hard_delete_contract

    marker = f"Dsvc{uuid.uuid4().hex[:6]}"
    cand = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    cli = await _seed_client(f"DeleteService {marker}")
    cid = await _seed_contract(cand, cli, status=ContractStatus.ended)
    generated_id = await _seed_generated(
        marker, cid, cand, signature_status="unsigned", client_id=cli
    )

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, cid)
        assert contract is not None
        rate = ContractCandidateRate(
            contract_id=cid,
            rate=Decimal("125.000"),
            effective_from=date.today(),
        )
        note = Note(content=f"History {marker}", contract_id=cid, candidate_id=cand)
        db.add_all([rate, note])
        await db.flush()
        rate_id = rate.id
        note_id = note.id

        outcome = await hard_delete_contract(db, contract, actor_id=None)
        assert outcome.contract_id == cid
        assert outcome.detached_generated_contracts == 1
        assert outcome.settled_order_group_ids == ()
        await db.commit()

    async with AsyncSessionLocal() as db:
        assert await db.get(Contract, cid) is None
        # Project-owned schedule follows CASCADE.
        assert await db.get(ContractCandidateRate, rate_id) is None
        # Cross-module history follows SET NULL.
        surviving_note = await db.get(Note, note_id)
        assert surviving_note is not None
        assert surviving_note.contract_id is None
        # The generated agreement remains in its register, detached.
        generated = await db.get(B2BGeneratedContract, generated_id)
        assert generated is not None
        assert generated.contract_id is None
        audit = await db.scalar(
            select(Activity)
            .where(
                Activity.entity_type == "contract",
                Activity.entity_id == cid,
                Activity.action == "deleted",
            )
            .order_by(Activity.id.desc())
        )
        assert audit is not None
        assert audit.details == {
            "status": "ended",
            "candidate_id": cand,
            "client_id": cli,
        }


async def test_shared_hard_delete_service_keeps_protective_signed_b2b():
    """The batch helper must fail before detaching a same-client signature."""
    from app.services.contract_lifecycle import (
        ContractHardDeleteBlocked,
        hard_delete_contract,
    )

    marker = f"Dsvcs{uuid.uuid4().hex[:6]}"
    cand = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    cli = await _seed_client(f"DeleteSigned {marker}")
    cid = await _seed_contract(cand, cli, status=ContractStatus.draft)
    generated_id = await _seed_generated(
        marker, cid, cand, signature_status="signed_both", client_id=cli
    )

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, cid)
        assert contract is not None
        with pytest.raises(ContractHardDeleteBlocked) as caught:
            await hard_delete_contract(db, contract, actor_id=None)
        assert caught.value.reason == "signed_generated_contract"
        assert caught.value.status_code == 409
        assert caught.value.detail["code"] == "contract_has_signed_generated_contract"
        await db.rollback()

    async with AsyncSessionLocal() as db:
        assert await db.get(Contract, cid) is not None
        generated = await db.get(B2BGeneratedContract, generated_id)
        assert generated is not None
        assert generated.contract_id == cid


async def test_shared_hard_delete_parent_lock_serializes_new_fk_children(
    monkeypatch,
):
    """A new child cannot appear after blockers have been evaluated.

    PostgreSQL checks a new FK with KEY SHARE on the parent.  The shared
    helper must already hold FOR UPDATE on that parent, so the insert waits;
    once the delete commits, the waiting insert fails instead of creating a
    signature/agreement in the guard-to-DELETE race window.
    """
    import asyncio

    from sqlalchemy import select, text
    from sqlalchemy.exc import IntegrityError

    import app.services.contract_lifecycle as lifecycle

    marker = f"Dlock{uuid.uuid4().hex[:6]}"
    cand = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    cli = await _seed_client(f"DeleteLock {marker}")
    cid = await _seed_contract(cand, cli, status=ContractStatus.draft)

    locks_held = asyncio.Event()
    release_delete = asyncio.Event()
    original_blocker = lifecycle.hard_delete_blocker

    async def paused_blocker(db, contract):
        # ``hard_delete_contract`` calls the blocker only after locking the
        # parent and both child tables. Hold it here so the second transaction
        # can prove that a new FK insert is waiting on the parent lock.
        locks_held.set()
        await release_delete.wait()
        return await original_blocker(db, contract)

    monkeypatch.setattr(lifecycle, "hard_delete_blocker", paused_blocker)

    async def delete_in_first_transaction():
        async with AsyncSessionLocal() as db:
            contract = await db.get(Contract, cid)
            assert contract is not None
            outcome = await lifecycle.hard_delete_contract(db, contract, actor_id=None)
            await db.commit()
            return outcome

    insert_pid = asyncio.get_running_loop().create_future()

    async def insert_in_second_transaction() -> str:
        async with AsyncSessionLocal() as db:
            pid = await db.scalar(text("SELECT pg_backend_pid()"))
            insert_pid.set_result(int(pid))
            db.add(
                B2BGeneratedContract(
                    year=2026,
                    seq=int(uuid.uuid4().hex[:6], 16),
                    contract_number=f"B2B/LOCK/{marker}",
                    partner_name=f"Lock {marker}",
                    signature_status="unsigned",
                    contract_id=cid,
                    candidate_id=cand,
                    client_id=cli,
                )
            )
            try:
                await db.flush()
            except IntegrityError:
                await db.rollback()
                return "fk_rejected"
            await db.commit()
            return "inserted"

    delete_task = asyncio.create_task(delete_in_first_transaction())
    insert_task = None
    try:
        await asyncio.wait_for(locks_held.wait(), timeout=5)
        insert_task = asyncio.create_task(insert_in_second_transaction())
        pid = await asyncio.wait_for(insert_pid, timeout=5)

        # Use PostgreSQL's lock graph rather than a timing-only assertion. If
        # FOR UPDATE is removed from the helper, the insert commits and this
        # condition is never observed.
        blocked = False
        deadline = asyncio.get_running_loop().time() + 5
        async with AsyncSessionLocal() as observer:
            while asyncio.get_running_loop().time() < deadline:
                blocker_count = await observer.scalar(
                    text("SELECT cardinality(pg_blocking_pids(:pid))"),
                    {"pid": pid},
                )
                if int(blocker_count or 0) > 0:
                    blocked = True
                    break
                if insert_task.done():
                    break
                await asyncio.sleep(0.02)
        assert blocked, "new FK child did not wait on the locked contract parent"

        release_delete.set()
        outcome = await asyncio.wait_for(delete_task, timeout=5)
        assert outcome.contract_id == cid
        assert await asyncio.wait_for(insert_task, timeout=5) == "fk_rejected"
    finally:
        release_delete.set()
        tasks = [delete_task]
        if insert_task is not None:
            tasks.append(insert_task)
        await asyncio.gather(*tasks, return_exceptions=True)

    async with AsyncSessionLocal() as db:
        assert await db.get(Contract, cid) is None
        inserted = await db.scalar(
            select(B2BGeneratedContract.id).where(
                B2BGeneratedContract.contract_number == f"B2B/LOCK/{marker}"
            )
        )
        assert inserted is None


async def test_hard_delete_serializes_stale_cost_group_settlement(monkeypatch):
    """A stale settlement waits for delete and recomputes from fresh rows.

    This exercises PostgreSQL's real lock graph. The second session loads the
    group before hard-delete removes its only line, then calls ``settle_group``
    while delete holds the group row. It must wait and refresh rather than
    overwriting the post-delete budget with a result from the old line set.
    """
    import asyncio
    from decimal import Decimal

    from sqlalchemy import text

    import app.services.contract_lifecycle as lifecycle
    import app.services.cost_orders as cost_orders
    from app.models.client_order import ClientOrder
    from app.models.client_order_group import ClientOrderGroup
    from app.models.md_consumption import ClientOrderInvoiceConsumption

    marker = f"Dsettle{uuid.uuid4().hex[:6]}"
    cand = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    cli = await _seed_client(f"DeleteSettle {marker}")
    cid = await _seed_contract(cand, cli, status=ContractStatus.draft)

    async with AsyncSessionLocal() as db:
        group = ClientOrderGroup(
            client_id=cli,
            order_number=f"LOCK/{marker}",
            start_date=date.today() - timedelta(days=30),
            is_cost_based=True,
            budget_amount=Decimal("1000.00"),
            budget_remaining=Decimal("1000.00"),
        )
        db.add(group)
        await db.flush()
        line = ClientOrder(
            client_id=cli,
            contract_id=cid,
            title=f"Locked line {marker}",
            order_group_id=group.id,
        )
        db.add(line)
        await db.flush()
        db.add(
            ClientOrderInvoiceConsumption(
                order_id=line.id,
                period_month="2026-08",
                invoice_amount=Decimal("400.00"),
                source="import",
            )
        )
        await db.flush()
        assert await cost_orders.settle_group(db, group) == Decimal("600.00")
        await db.commit()
        group_id = group.id

    delete_holds_group = asyncio.Event()
    release_delete = asyncio.Event()
    start_stale_settlement = asyncio.Event()
    stale_loaded = asyncio.Event()
    stale_pid = asyncio.get_running_loop().create_future()
    original_settle = cost_orders.settle_group

    async def paused_delete_settle(db, group):
        # hard_delete_contract locks the affected group immediately before this
        # call. Pausing here exposes that lock to the competing session.
        delete_holds_group.set()
        await release_delete.wait()
        return await original_settle(db, group)

    monkeypatch.setattr(cost_orders, "settle_group", paused_delete_settle)

    async def delete_in_first_transaction():
        async with AsyncSessionLocal() as db:
            contract = await db.get(Contract, cid)
            assert contract is not None
            outcome = await lifecycle.hard_delete_contract(db, contract, actor_id=None)
            await db.commit()
            return outcome

    async def settle_stale_group_in_second_transaction():
        async with AsyncSessionLocal() as db:
            stale_group = await db.get(ClientOrderGroup, group_id)
            assert stale_group is not None
            pid = await db.scalar(text("SELECT pg_backend_pid()"))
            stale_pid.set_result(int(pid))
            stale_loaded.set()
            await start_stale_settlement.wait()
            remaining = await original_settle(db, stale_group)
            await db.commit()
            return remaining

    stale_task = asyncio.create_task(settle_stale_group_in_second_transaction())
    delete_task = None
    try:
        await asyncio.wait_for(stale_loaded.wait(), timeout=5)
        delete_task = asyncio.create_task(delete_in_first_transaction())
        await asyncio.wait_for(delete_holds_group.wait(), timeout=5)
        start_stale_settlement.set()
        pid = await asyncio.wait_for(stale_pid, timeout=5)

        blocked = False
        deadline = asyncio.get_running_loop().time() + 5
        async with AsyncSessionLocal() as observer:
            while asyncio.get_running_loop().time() < deadline:
                blocker_count = await observer.scalar(
                    text("SELECT cardinality(pg_blocking_pids(:pid))"),
                    {"pid": pid},
                )
                if int(blocker_count or 0) > 0:
                    blocked = True
                    break
                if stale_task.done():
                    break
                await asyncio.sleep(0.02)
        assert blocked, "stale settlement did not wait on the locked order group"

        release_delete.set()
        outcome = await asyncio.wait_for(delete_task, timeout=5)
        assert outcome.settled_order_group_ids == (group_id,)
        assert await asyncio.wait_for(stale_task, timeout=5) == Decimal("1000.00")
    finally:
        release_delete.set()
        start_stale_settlement.set()
        tasks = [stale_task]
        if delete_task is not None:
            tasks.append(delete_task)
        await asyncio.gather(*tasks, return_exceptions=True)

    async with AsyncSessionLocal() as db:
        assert await db.get(Contract, cid) is None
        refreshed = await db.get(ClientOrderGroup, group_id)
        assert refreshed is not None
        assert refreshed.budget_remaining == Decimal("1000.00")


async def test_delete_contract_unlinks_generated_b2b_and_keeps_candidate(
    app_client, app_auth_headers
):
    """NIEPODPISANA umowa wygenerowana nie blokuje kasowania kontraktu — jest
    odpinana (contract_id → NULL). Do 2026-08-25 taki DELETE przechodził guard
    „tylko szkic" (dla szkiców) i wywracał się dopiero na FK RESTRICT → 500."""
    marker = f"Del{uuid.uuid4().hex[:6]}"
    cand = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    cli = await _seed_client(f"DelKlient {marker}")
    cid = await _seed_contract(cand, cli, status=ContractStatus.ended)
    generated_id = await _seed_generated(marker, cid, cand, signature_status="unsigned")

    resp = await app_client.delete(f"/api/contracts/{cid}", headers=app_auth_headers)
    assert resp.status_code == 204, resp.text

    async with AsyncSessionLocal() as db:
        # Kontrakt zniknął z modułu Kontrakty…
        assert await db.get(Contract, cid) is None
        # …kandydat został w module Kandydaci…
        assert await db.get(Candidate, cand) is not None
        # …a wygenerowana umowa została w rejestrze, odpięta od projektu.
        surviving = await db.get(B2BGeneratedContract, generated_id)
        assert surviving is not None
        assert surviving.contract_id is None
        assert surviving.contract_number == f"B2B/TEST/{marker}"


async def test_delete_contract_resettles_cost_order_group(app_client, app_auth_headers):
    """Kaskada DELETE usuwa linię grupy kosztowej i jej konsumpcje, a
    `budget_remaining`/`settled_amount` są kolumnami ZAPISANYMI, przeliczanymi
    wyłącznie przez `settle_group` — endpoint musi je przeliczyć, inaczej grupa
    do najbliższego importu pokazuje kwoty pomniejszone o skasowane faktury."""
    from decimal import Decimal

    from app.models.client_order import ClientOrder
    from app.models.client_order_group import ClientOrderGroup
    from app.models.md_consumption import ClientOrderInvoiceConsumption
    from app.services.cost_orders import settle_group

    marker = f"Dcg{uuid.uuid4().hex[:6]}"
    cand_a = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    cand_b = await _seed_candidate(
        marker, email=f"{marker.lower()}-b@example.com", suffix="Drugi"
    )
    cli = await _seed_client(f"CostKlient {marker}")
    cid_deleted = await _seed_contract(cand_a, cli)
    cid_stays = await _seed_contract(cand_b, cli)

    async with AsyncSessionLocal() as db:
        group = ClientOrderGroup(
            client_id=cli,
            order_number=f"GRP/{marker}",
            start_date=date.today() - timedelta(days=60),
            is_cost_based=True,
            budget_amount=Decimal("1000.00"),
            # CHECK cost_coherence wymaga niepustej reszty przy insercie;
            # settle_group niżej i tak przelicza ją od zera.
            budget_remaining=Decimal("1000.00"),
        )
        db.add(group)
        await db.flush()
        line_deleted = ClientOrder(
            client_id=cli,
            contract_id=cid_deleted,
            title=f"Linia kasowana {marker}",
            order_group_id=group.id,
        )
        line_stays = ClientOrder(
            client_id=cli,
            contract_id=cid_stays,
            title=f"Linia zostaje {marker}",
            order_group_id=group.id,
        )
        db.add_all([line_deleted, line_stays])
        await db.flush()
        db.add_all(
            [
                ClientOrderInvoiceConsumption(
                    order_id=line_deleted.id,
                    period_month="2026-07",
                    invoice_amount=Decimal("400.00"),
                    source="import",
                ),
                ClientOrderInvoiceConsumption(
                    order_id=line_stays.id,
                    period_month="2026-07",
                    invoice_amount=Decimal("300.00"),
                    source="import",
                ),
            ]
        )
        # Sesje repo mają autoflush=False — bez jawnego flusha SELECT wewnątrz
        # settle_group nie widziałby dopiero co dodanych konsumpcji.
        await db.flush()
        await settle_group(db, group)
        await db.commit()
        group_id = group.id
        assert group.budget_remaining == Decimal("300.00")

    resp = await app_client.delete(
        f"/api/contracts/{cid_deleted}", headers=app_auth_headers
    )
    assert resp.status_code == 204, resp.text

    async with AsyncSessionLocal() as db:
        refreshed = await db.get(ClientOrderGroup, group_id)
        assert refreshed is not None
        # Faktury skasowanej linii (400) już nie obciążają puli: 1000 − 300.
        assert refreshed.budget_remaining == Decimal("700.00")


async def test_delete_contract_with_signed_both_generated_refused_in_polish(
    app_client, app_auth_headers
):
    """Umowa potwierdzona jako podpisana OBUSTRONNIE blokuje kasowanie —
    kontrakt z audytowanego `confirm-fully-signed` to zapis prawnie wykonanego
    zobowiązania (symetria z nieedytowalnością wiersza `signed_both`).
    Odmowa jest po polsku i wskazuje alternatywę (void)."""
    marker = f"Dsb{uuid.uuid4().hex[:6]}"
    cand = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    cli = await _seed_client(f"SignedKlient {marker}")
    cid = await _seed_contract(cand, cli, status=ContractStatus.active)
    generated_id = await _seed_generated(
        marker,
        cid,
        cand,
        signature_status="signed_both",
        # JAWNIE bez klienta — wiersz historyczny/standalone. Taki podpis nie
        # mówi, którego projektu dotyczy, więc MUSI blokować (fail-closed).
        # Podstawienie tu `cli` skasowałoby pokrycie tej gałęzi.
        client_id=None,
    )

    resp = await app_client.delete(f"/api/contracts/{cid}", headers=app_auth_headers)
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "contract_has_signed_generated_contract"
    assert "podpisana" in detail["message"]
    assert "void_endpoint" in detail
    assert detail["requires_admin_confirmation"] is True
    assert detail["admin_only"] is True
    assert detail["force_delete_endpoint"] == (
        f"/api/contracts/{cid}/force-delete-signed"
    )
    assert detail["confirmation_options"] == ["contractor_name", "contract_id"]

    async with AsyncSessionLocal() as db:
        assert await db.get(Contract, cid) is not None
        surviving = await db.get(B2BGeneratedContract, generated_id)
        assert surviving is not None
        assert surviving.contract_id == cid  # link audytowy nietknięty


async def test_force_delete_signed_requires_admin_and_exact_confirmation(
    app_client, app_auth_headers
):
    """Break-glass B2B delete is admin-only and rejects every fuzzy mismatch."""
    marker = f"Fsd{uuid.uuid4().hex[:6]}"
    cand = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    cli = await _seed_client(f"ForceSigned {marker}")
    cid = await _seed_contract(cand, cli, status=ContractStatus.active)
    generated_id = await _seed_generated(
        marker, cid, cand, signature_status="signed_both", client_id=cli
    )

    tac_headers = await _tac_headers(app_client)
    denied = await app_client.post(
        f"/api/contracts/{cid}/force-delete-signed",
        json={"confirmation": f"Multi {marker}"},
        headers=tac_headers,
    )
    assert denied.status_code == 403, denied.text

    mismatch = await app_client.post(
        f"/api/contracts/{cid}/force-delete-signed",
        # No typo tolerance for an irreversible operation.
        json={"confirmation": f"Multi {marker}x"},
        headers=app_auth_headers,
    )
    assert mismatch.status_code == 422, mismatch.text
    assert mismatch.json()["detail"]["code"] == ("signed_delete_confirmation_mismatch")

    async with AsyncSessionLocal() as db:
        assert await db.get(Contract, cid) is not None
        generated = await db.get(B2BGeneratedContract, generated_id)
        assert generated is not None
        assert generated.contract_id == cid


async def test_admin_force_delete_signed_by_name_preserves_register_and_audits(
    app_client, app_auth_headers
):
    """Exact name confirmation detaches signed B2B and leaves durable audit."""
    from app.models.activity import Activity

    marker = f"Fsn{uuid.uuid4().hex[:6]}"
    cand = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    cli = await _seed_client(f"ForceName {marker}")
    cid = await _seed_contract(cand, cli, status=ContractStatus.active)
    generated_id = await _seed_generated(
        marker, cid, cand, signature_status="signed_both", client_id=cli
    )

    response = await app_client.post(
        f"/api/contracts/{cid}/force-delete-signed",
        # Leading/trailing whitespace + case are normalised; spelling and
        # diacritics are not fuzzed.
        json={"confirmation": f"  multi {marker.upper()}  "},
        headers=app_auth_headers,
    )
    assert response.status_code == 204, response.text

    async with AsyncSessionLocal() as db:
        assert await db.get(Contract, cid) is None
        assert await db.get(Candidate, cand) is not None
        generated = await db.get(B2BGeneratedContract, generated_id)
        assert generated is not None
        assert generated.contract_id is None
        assert generated.signature_status == "signed_both"

        audit = await db.scalar(
            select(Activity)
            .where(
                Activity.entity_type == "contract",
                Activity.entity_id == cid,
                Activity.action == "force_deleted_signed",
            )
            .order_by(Activity.id.desc())
        )
        assert audit is not None
        assert audit.user_id is not None
        assert audit.created_at is not None
        assert audit.details == {
            "status": "active",
            "candidate_id": cand,
            "client_id": cli,
            "contract_id": cid,
            "forced_despite_signed": True,
            "blocker": "signed_generated_contract",
            "confirmation_method": "contractor_name",
        }


@pytest.mark.parametrize("prefix", ["", "#"])
async def test_admin_force_delete_signed_accepts_exact_contract_number(
    app_client, app_auth_headers, prefix
):
    marker = f"Fsi{uuid.uuid4().hex[:6]}"
    cand = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    cli = await _seed_client(f"ForceId {marker}")
    cid = await _seed_contract(cand, cli, status=ContractStatus.active)
    generated_id = await _seed_generated(
        marker, cid, cand, signature_status="signed_both", client_id=cli
    )

    response = await app_client.post(
        f"/api/contracts/{cid}/force-delete-signed",
        json={"confirmation": f"  {prefix}{cid}  "},
        headers=app_auth_headers,
    )
    assert response.status_code == 204, response.text

    async with AsyncSessionLocal() as db:
        assert await db.get(Contract, cid) is None
        generated = await db.get(B2BGeneratedContract, generated_id)
        assert generated is not None
        assert generated.contract_id is None


async def test_force_delete_signed_is_not_a_second_generic_delete(
    app_client, app_auth_headers
):
    marker = f"Fsu{uuid.uuid4().hex[:6]}"
    cand = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    cli = await _seed_client(f"ForceUnsigned {marker}")
    cid = await _seed_contract(cand, cli, status=ContractStatus.draft)
    generated_id = await _seed_generated(
        marker, cid, cand, signature_status="unsigned", client_id=cli
    )

    response = await app_client.post(
        f"/api/contracts/{cid}/force-delete-signed",
        json={"confirmation": str(cid)},
        headers=app_auth_headers,
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == (
        "contract_not_protected_by_signed_generated_contract"
    )

    async with AsyncSessionLocal() as db:
        assert await db.get(Contract, cid) is not None
        generated = await db.get(B2BGeneratedContract, generated_id)
        assert generated is not None
        assert generated.contract_id == cid


async def test_delete_contract_blocked_by_signed_generated_of_same_client(
    app_client, app_auth_headers
):
    """Podpis wskazujący TEGO SAMEGO klienta co kontrakt nadal blokuje.

    Poluzowanie blockera o „link jawnie rozjechany" ma zdjąć ochronę wyłącznie
    z linków wskazujących INNEGO klienta — nie z prawidłowo podpisanych umów."""
    marker = f"Dsc{uuid.uuid4().hex[:6]}"
    cand = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    cli = await _seed_client(f"SameKlient {marker}")
    cid = await _seed_contract(cand, cli, status=ContractStatus.active)
    generated_id = await _seed_generated(
        marker, cid, cand, signature_status="signed_both", client_id=cli
    )

    resp = await app_client.delete(f"/api/contracts/{cid}", headers=app_auth_headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "contract_has_signed_generated_contract"

    async with AsyncSessionLocal() as db:
        surviving = await db.get(B2BGeneratedContract, generated_id)
        assert surviving is not None
        assert surviving.contract_id == cid


async def test_delete_contract_not_blocked_by_signature_of_another_project(
    app_client, app_auth_headers
):
    """Podpis należący do INNEGO projektu nie chroni tego wiersza.

    Produkcja: reaktywacja umowy z zawieszenia przepisywała `client_id` na nowy
    projekt, zostawiając `contract_id` na kontrakcie poprzedniego — projekt
    poprzedniego klienta stawał się nieusuwalny, choć nikt go nie podpisywał.
    Sam blocker nie wystarcza: FK jest RESTRICT, więc odpinanie przed DELETE
    musi iść DOKŁADNIE tym samym predykatem, inaczej operacja pada 500-tką albo
    trafia w TOCTOU-guard raportujący każdy pozostały link jako „signed"."""
    marker = f"Dxp{uuid.uuid4().hex[:6]}"
    cand = await _seed_candidate(marker, email=f"{marker.lower()}@example.com")
    cli_stale = await _seed_client(f"StaryKlient {marker}")
    cli_current = await _seed_client(f"NowyKlient {marker}")
    cid = await _seed_contract(cand, cli_stale, status=ContractStatus.draft)
    generated_id = await _seed_generated(
        marker,
        cid,
        cand,
        signature_status="signed_both",
        client_id=cli_current,
    )

    resp = await app_client.delete(f"/api/contracts/{cid}", headers=app_auth_headers)
    assert resp.status_code == 204, resp.text

    async with AsyncSessionLocal() as db:
        assert await db.get(Contract, cid) is None
        # Wiersz w rejestrze zostaje — kasujemy projekt, nie podpisaną umowę.
        surviving = await db.get(B2BGeneratedContract, generated_id)
        assert surviving is not None
        assert surviving.contract_id is None
        assert surviving.signature_status == "signed_both"
