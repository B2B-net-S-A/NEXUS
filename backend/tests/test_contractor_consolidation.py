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

import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import (
    Contract,
    ContractStatus,
    ContractType,
    ContractWorkMode,
    RateUnit,
)

pytestmark = pytest.mark.asyncio


# ── Seed helpers ─────────────────────────────────────────────────────────────


async def _seed_candidate(
    marker: str, *, email: str | None, suffix: str = ""
) -> int:
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Multi",
            lastname=f"{marker}{suffix}",
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
    c1 = await _seed_client(
        f"BP {marker}", display_name=f"Bank Pocztowy S.A. {marker}"
    )
    c2 = await _seed_client(
        f"Velo {marker}", display_name=f"VeloBank S.A. {marker}"
    )
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
    assert all(row["group_members"] == [] for row in flat.json()["items"])


async def test_grouped_list_respects_filters_within_group(
    app_client, app_auth_headers
):
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

    headers = await _tac_headers(app_client)
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


async def test_grouped_list_and_siblings_respect_delivery_lead_scope(app_client):
    """DL przypisany do klienta A nie może przez konsolidację odczytać, że
    konsultant pracuje też u klienta B: zgrupowany wiersz zawiera wyłącznie
    umowy z portfela DL-a, a `related_contracts` nie wystawia chipa klienta
    spoza scope'u."""
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
    assert [m["id"] for m in row["group_members"]] == [id_a]
    assert all(
        f"ObcyKlient {marker}" != (m["client_name"] or "")
        for m in row["group_members"]
    )

    detail = await app_client.get(f"/api/contracts/{id_a}", headers=dl_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["related_contracts"] == []

    # Kontrakt spoza portfela pozostaje niedostępny wprost.
    outside = await app_client.get(f"/api/contracts/{id_b}", headers=dl_headers)
    assert outside.status_code == 403, outside.text


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

    detail = await app_client.get(
        f"/api/contracts/{id_a}", headers=app_auth_headers
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["client_name"] == f"Pierwszy Klient S.A. {marker}"
    related = detail.json()["related_contracts"]
    # Rodzeństwo = druga umowa tej osoby; `void` nie jest zakładką.
    assert [r["id"] for r in related] == [id_b]
    assert related[0]["client_name"] == f"Drugi Klient S.A. {marker}"
    assert related[0]["status"] == "active"

    # Symetria: z perspektywy drugiej umowy widać pierwszą.
    detail_b = await app_client.get(
        f"/api/contracts/{id_b}", headers=app_auth_headers
    )
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


async def test_duplicate_same_person_same_client_blocked(
    app_client, app_auth_headers
):
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
    generated_id = await _seed_generated(
        marker, cid, cand, signature_status="unsigned"
    )

    resp = await app_client.delete(
        f"/api/contracts/{cid}", headers=app_auth_headers
    )
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


async def test_delete_contract_resettles_cost_order_group(
    app_client, app_auth_headers
):
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

    resp = await app_client.delete(
        f"/api/contracts/{cid}", headers=app_auth_headers
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "contract_has_signed_generated_contract"
    assert "podpisana" in detail["message"]
    assert "void_endpoint" in detail

    async with AsyncSessionLocal() as db:
        assert await db.get(Contract, cid) is not None
        surviving = await db.get(B2BGeneratedContract, generated_id)
        assert surviving is not None
        assert surviving.contract_id == cid  # link audytowy nietknięty


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

    resp = await app_client.delete(
        f"/api/contracts/{cid}", headers=app_auth_headers
    )
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

    resp = await app_client.delete(
        f"/api/contracts/{cid}", headers=app_auth_headers
    )
    assert resp.status_code == 204, resp.text

    async with AsyncSessionLocal() as db:
        assert await db.get(Contract, cid) is None
        # Wiersz w rejestrze zostaje — kasujemy projekt, nie podpisaną umowę.
        surviving = await db.get(B2BGeneratedContract, generated_id)
        assert surviving is not None
        assert surviving.contract_id is None
        assert surviving.signature_status == "signed_both"
