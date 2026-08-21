"""Integration testy endpointów PDF zamówienia (in-process ``app_client``).

- ``POST /orders/extract`` — odczyt PDF (mockowany extract_text + parser),
  finanse widoczne dla admina, walidacja rozszerzenia.
- ``GET /order-documents/by-contract|by-candidate`` — jeden plik PO widoczny w
  dwóch widokach (kontrakt + osoba).

Weryfikuje też, że migracja 0214 (seed ``ai_features.order_parser``) zadziałała —
bez niej ``check_and_increment`` zwróciłby 503 zamiast 200.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient

_TODAY = date(2026, 8, 5)


async def _seed_client(name: str | None = None) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        client = Client(name=name or f"OrdClient-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.commit()
        await db.refresh(client)
        return client.id


async def _dl_headers(app_client: AsyncClient, client_id: int) -> dict[str, str]:
    """Delivery Lead przypisany do klienta (bez VIEW_FINANCE) — zalogowany."""
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole

    email = f"dl-ord-{uuid.uuid4().hex[:8]}@example.com"
    password = f"P4ss_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name="DL Ord",
            role=UserRole.delivery_lead,
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.flush()
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=user.id, client_id=client_id
            )
        )
        await db.commit()
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _seed_graph_with_order() -> dict[str, int]:
    """Client + Candidate + Contract + ClientOrder z plikiem PO."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Ord",
            lastname=f"C-{uuid.uuid4().hex[:6]}",
            email=f"ordc-{uuid.uuid4().hex[:8]}@example.com",
        )
        client = Client(name=f"OrdClient-{uuid.uuid4().hex[:6]}")
        db.add_all([cand, client])
        await db.commit()
        await db.refresh(cand)
        await db.refresh(client)

        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=_TODAY - timedelta(days=10),
            end_date=_TODAY + timedelta(days=90),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("150.000"),
            margin=Decimal("50.000"),
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)

        order = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title="PO-777",
            status=ClientOrderStatus.active,
            filename="po.pdf",
            file_path="client_orders/0/dummy-po.pdf",
            content_type="application/pdf",
            size_bytes=1234,
        )
        db.add(order)
        await db.commit()
        await db.refresh(order)

        return {
            "client_id": client.id,
            "candidate_id": cand.id,
            "contract_id": contract.id,
            "order_id": order.id,
        }


async def test_extract_order_pdf_admin_sees_finance(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.api import client_orders as co
    from app.services.order_pdf_parser import OrderExtraction

    client_id = await _seed_client()

    # Mock ekstrakcji tekstu (sync, wołany przez run_in_threadpool) i parsera AI.
    monkeypatch.setattr(
        co, "extract_text", lambda path, filename: "Zamówienie PO-999 treść"
    )

    async def _fake_parse(text: str) -> OrderExtraction:
        return OrderExtraction(
            title="PO-999",
            start_date="2026-06-01",
            end_date="2026-12-31",
            rate_client=Decimal("17000"),
            rate_unit="month",
            total_value=Decimal("102000"),
            currency="PLN",
            confidence={},
            uncertain=True,
            uncertain_reasons=["Nie znaleziono jednoznacznej daty końca"],
            source="claude",
        )

    monkeypatch.setattr(co, "parse_order_document", _fake_parse)

    files = {"file": ("order.pdf", b"%PDF-1.4 dummy bytes", "application/pdf")}
    resp = await app_client.post(
        f"/api/clients/{client_id}/orders/extract",
        files=files,
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["title"] == "PO-999"
    assert data["start_date"] == "2026-06-01"
    assert data["end_date"] == "2026-12-31"
    # Admin ma VIEW_FINANCE → kwoty NIE zredagowane.
    assert Decimal(str(data["rate_client"])) == Decimal("17000")
    assert Decimal(str(data["total_value"])) == Decimal("102000")
    assert data["uncertain"] is True
    assert data["uncertain_reasons"]


async def test_nordea_endpoint_forces_call_off_agreement_number(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.api import client_orders as co
    from app.services.order_pdf_parser import OrderExtraction

    client_id = await _seed_client("Nordea Bank ABP")
    monkeypatch.setattr(
        co,
        "extract_text",
        lambda path, filename: (
            "Offer number: OFFER-999\n"
            "Project number: PROJECT-123\n"
            "Call Off Agreement number: COA-4500030222"
        ),
    )

    async def _wrong_ai_choice(text: str) -> OrderExtraction:
        return OrderExtraction(
            title="OFFER-999",
            start_date="2026-06-01",
            end_date="2026-12-31",
            confidence={"title": 0.99},
            uncertain=False,
            source="claude",
        )

    monkeypatch.setattr(co, "parse_order_document", _wrong_ai_choice)
    response = await app_client.post(
        f"/api/clients/{client_id}/orders/extract",
        files={"file": ("nordea.pdf", b"%PDF-1.4 dummy", "application/pdf")},
        headers=app_auth_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["title"] == "COA-4500030222"


async def test_extract_rejects_bad_extension(
    app_client: AsyncClient, app_auth_headers: dict
):
    client_id = await _seed_client()
    files = {"file": ("notatka.txt", b"hello", "text/plain")}
    resp = await app_client.post(
        f"/api/clients/{client_id}/orders/extract",
        files=files,
        headers=app_auth_headers,
    )
    assert resp.status_code == 415


async def test_order_document_visible_in_both_views(
    app_client: AsyncClient, app_auth_headers: dict
):
    ids = await _seed_graph_with_order()

    r1 = await app_client.get(
        f"/api/clients/order-documents/by-contract/{ids['contract_id']}",
        headers=app_auth_headers,
    )
    assert r1.status_code == 200, r1.text
    by_contract = {d["order_id"] for d in r1.json()["documents"]}

    r2 = await app_client.get(
        f"/api/clients/order-documents/by-candidate/{ids['candidate_id']}",
        headers=app_auth_headers,
    )
    assert r2.status_code == 200, r2.text
    by_candidate = {d["order_id"] for d in r2.json()["documents"]}

    # Ten sam plik (order_id) w obu widokach — jeden plik, dwa widoki, bez kopii.
    assert ids["order_id"] in by_contract
    assert ids["order_id"] in by_candidate


async def test_order_documents_by_contract_404(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/clients/order-documents/by-contract/99999999",
        headers=app_auth_headers,
    )
    assert resp.status_code == 404


async def _hor_headers(app_client: AsyncClient) -> dict[str, str]:
    """Head of Recruitment — BEZ przypisania, a mimo to przechodzi guard trasy.

    ``require_dl_assigned_or_admin`` przepuszcza HoR globalnie, więc to jedyna
    rola, która dociera do tego endpointu bez prawa do kwot. Dlatego właśnie na
    niej trzymamy dowód redakcji kanałów pobocznych.
    """
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    email = f"hor-ord-{uuid.uuid4().hex[:8]}@example.com"
    password = f"P4ss_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="HoR Ord",
                role=UserRole.head_of_recruitment,
                roles=[UserRole.head_of_recruitment.value],
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_extract_redacts_finance_and_metadata_for_head_of_recruitment(
    app_client: AsyncClient, monkeypatch
):
    """HoR: kwoty ORAZ kanały poboczne (fields_confidence finansowe +
    uncertain_reasons cytujące/nazywające finanse) muszą być zredagowane.

    Wcześniej ten dowód stał na Delivery Leadzie; po poszerzeniu uprawnień
    PRZYPISANY DL kwoty widzi (patrz test niżej), więc rolą bez dostępu, która
    wciąż dociera do tego endpointu, jest head_of_recruitment — przepuszcza go
    guard trasy, ale nie predykat finansowy.
    """
    from app.api import client_orders as co
    from app.services.order_pdf_parser import OrderExtraction

    client_id = await _seed_client()
    dl_headers = await _hor_headers(app_client)

    monkeypatch.setattr(co, "extract_text", lambda path, filename: "treść zamówienia")

    async def _fake_parse(text: str) -> OrderExtraction:
        return OrderExtraction(
            title="PO-DL",
            start_date="2026-06-01",
            end_date=None,
            rate_client=Decimal("17000"),
            rate_unit="month",
            total_value=Decimal("102000"),
            currency="PLN",
            confidence={
                "title": 0.95,
                "start_date": 0.9,
                "rate_client": 0.97,
                "total_value": 0.9,
                "currency": 0.9,
            },
            uncertain=True,
            uncertain_reasons=[
                "Stawka 17000 PLN wydaje się nietypowa",
                "Niepewny odczyt: stawka (klient płaci)",
            ],
            source="claude",
        )

    monkeypatch.setattr(co, "parse_order_document", _fake_parse)

    files = {"file": ("order.pdf", b"%PDF-1.4 x", "application/pdf")}
    resp = await app_client.post(
        f"/api/clients/{client_id}/orders/extract",
        files=files,
        headers=dl_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Wartości finansowe zredagowane.
    assert data["rate_client"] is None
    assert data["total_value"] is None
    assert data["currency"] is None
    assert data["rate_unit"] is None

    # fields_confidence bez kluczy finansowych, niefinansowe zostają.
    conf = data["fields_confidence"]
    assert "rate_client" not in conf
    assert "total_value" not in conf
    assert "currency" not in conf
    assert "rate_unit" not in conf
    assert "title" in conf

    # uncertain_reasons NIE cytuje kwot ani nie nazywa pól finansowych,
    # ale baner „Sprawdź dane!" zostaje (uncertain=True).
    joined = " ".join(data["uncertain_reasons"]).lower()
    assert "17000" not in joined
    assert "stawka" not in joined
    assert data["uncertain"] is True

    # Pola operacyjne przechodzą.
    assert data["title"] == "PO-DL"
    assert data["start_date"] == "2026-06-01"


async def test_extract_shows_finance_to_assigned_delivery_lead(
    app_client: AsyncClient, monkeypatch
):
    """Przypisany DL widzi kwoty ORAZ ich pewność odczytu — jedną bramką.

    Kanał poboczny (`fields_confidence`) musi iść za wartościami: dwa
    niezależne sprawdzenia dałyby stan, w którym DL widzi stawkę, ale nie
    pewność jej odczytu (albo odwrotnie), czyli baner „Sprawdź dane!" bez
    informacji, co właściwie sprawdzić.
    """
    from app.api import client_orders as co
    from app.services.order_pdf_parser import OrderExtraction

    client_id = await _seed_client()
    dl_headers = await _dl_headers(app_client, client_id)

    monkeypatch.setattr(co, "extract_text", lambda path, filename: "treść zamówienia")

    async def _fake_parse(text: str) -> OrderExtraction:
        return OrderExtraction(
            title="PO-DL",
            start_date="2026-06-01",
            end_date=None,
            rate_client=Decimal("17000"),
            rate_unit="month",
            total_value=Decimal("102000"),
            currency="PLN",
            confidence={"title": 0.95, "rate_client": 0.97},
            uncertain=True,
            uncertain_reasons=["Niepewny odczyt: stawka (klient płaci)"],
            source="claude",
        )

    monkeypatch.setattr(co, "parse_order_document", _fake_parse)

    resp = await app_client.post(
        f"/api/clients/{client_id}/orders/extract",
        files={"file": ("order.pdf", b"%PDF-1.4 x", "application/pdf")},
        headers=dl_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["rate_client"] == "17000"
    assert data["total_value"] == "102000"
    assert data["currency"] == "PLN"
    assert "rate_client" in data["fields_confidence"]


async def test_candidate_order_documents_dl_not_assigned_sees_nothing(
    app_client: AsyncClient,
):
    """Poufność: Delivery Lead NIE przypisany do klienta nie widzi jego PO w
    widoku osoby (PO zawiera stawki). Testuje filtr access w
    ``list_candidate_order_documents`` (ścieżka security-critical — testy happy
    path lecą na adminie, który omija filtr)."""
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    ids = await _seed_graph_with_order()

    email = f"dl-unassigned-{uuid.uuid4().hex[:8]}@example.com"
    password = f"P4ss_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="DL Unassigned",
                role=UserRole.delivery_lead,
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()

    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await app_client.get(
        f"/api/clients/order-documents/by-candidate/{ids['candidate_id']}",
        headers=headers,
    )
    # TacPlus przepuszcza DL na endpoint, ale filtr access wycina PO klienta,
    # do którego DL nie jest przypisany → pusto (nie leak).
    assert resp.status_code == 200, resp.text
    assert resp.json()["documents"] == []
