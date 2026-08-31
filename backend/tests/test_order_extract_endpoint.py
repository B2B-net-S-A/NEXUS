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
import pytest

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


async def _seed_candidate(
    name: str,
    lastname: str,
    *,
    contract_client_id: int | None = None,
    contract_status: str = "active",
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name=name,
            lastname=lastname,
            email=f"pdf-target-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(candidate)
        await db.flush()
        if contract_client_id is not None:
            db.add(
                Contract(
                    candidate_id=candidate.id,
                    client_id=contract_client_id,
                    status=ContractStatus(contract_status),
                    start_date=_TODAY - timedelta(days=30),
                    end_date=_TODAY + timedelta(days=30),
                )
            )
        await db.commit()
        await db.refresh(candidate)
        return candidate.id


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


@pytest.mark.parametrize(
    "client_name",
    ["Polkomtel Sp. z o.o.", "Cyfrowy Polsat S.A.", "BIK S.A."],
)
async def test_targeted_extract_resolves_canonical_candidate_for_each_client(
    app_client: AsyncClient,
    app_auth_headers: dict,
    monkeypatch,
    client_name: str,
):
    from app.api import client_orders as co
    from app.services.order_pdf_parser import ConsultantOrderRow, OrderExtraction

    client_id = await _seed_client(client_name)
    # Historyczny kontrakt u bieżącego klienta nadal kwalifikuje osobę do
    # pickera i ekstrakcji, mimo że nie jest już aktywny.
    candidate_id = await _seed_candidate(
        "Natalia",
        "Prus-Rudzińska",
        contract_client_id=client_id,
        contract_status="ended",
    )
    received: dict[str, str | None] = {}
    monkeypatch.setattr(co, "extract_text", lambda path, filename: "treść PDF")

    async def _fake_parse(
        text: str,
        *,
        consultant_name: str | None = None,
        consultant_given_names: str | None = None,
    ) -> OrderExtraction:
        received["text"] = text
        received["consultant_name"] = consultant_name
        received["consultant_given_names"] = consultant_given_names
        return OrderExtraction(
            title="PO-MULTI",
            start_date="2026-09-01",
            rate_client=Decimal("1640"),
            rate_unit="day",
            md_total=Decimal("37"),
            consultant_rows=[
                ConsultantOrderRow(
                    consultant_name="Prus-Rudzińska Natalia",
                    rate_client=Decimal("1640"),
                    rate_unit="day",
                    md_total=Decimal("37"),
                    uncertain=False,
                )
            ],
            consultant_rate_matched=True,
            consultant_md_matched=True,
            uncertain=False,
            source="claude",
        )

    monkeypatch.setattr(co, "parse_order_document", _fake_parse)
    response = await app_client.post(
        f"/api/clients/{client_id}/orders/extract",
        data={"candidate_id": str(candidate_id)},
        files={"file": ("multi.pdf", b"%PDF-1.4 dummy", "application/pdf")},
        headers=app_auth_headers,
    )

    assert response.status_code == 200, response.text
    assert received == {
        "text": "treść PDF",
        "consultant_name": "Natalia Prus-Rudzińska",
        "consultant_given_names": "Natalia",
    }
    data = response.json()
    assert Decimal(str(data["rate_client"])) == Decimal("1640")
    assert Decimal(str(data["md_total"])) == Decimal("37")
    # Wewnętrzna lista innych osób i ich stawek nie wychodzi z API.
    assert "consultant_rows" not in data


@pytest.mark.parametrize("contract_status", ["active", "ending"])
async def test_targeted_extract_accepts_live_candidate_from_another_client(
    app_client: AsyncClient,
    app_auth_headers: dict,
    monkeypatch,
    contract_status: str,
):
    from app.api import client_orders as co
    from app.services.order_pdf_parser import OrderExtraction

    requested_client_id = await _seed_client("Polkomtel Sp. z o.o.")
    other_client_id = await _seed_client("Inny klient")
    candidate_id = await _seed_candidate(
        "Anna",
        "Kowalska",
        contract_client_id=other_client_id,
        contract_status=contract_status,
    )
    received: dict[str, str | None] = {}
    monkeypatch.setattr(co, "extract_text", lambda path, filename: "treść PDF")

    async def _fake_parse(
        text: str,
        *,
        consultant_name: str | None = None,
        consultant_given_names: str | None = None,
    ) -> OrderExtraction:
        received["consultant_name"] = consultant_name
        received["consultant_given_names"] = consultant_given_names
        return OrderExtraction(
            title="PO-LIVE",
            start_date="2026-09-01",
            uncertain=False,
            source="claude",
        )

    monkeypatch.setattr(co, "parse_order_document", _fake_parse)
    response = await app_client.post(
        f"/api/clients/{requested_client_id}/orders/extract",
        data={"candidate_id": str(candidate_id)},
        files={"file": ("multi.pdf", b"%PDF-1.4 dummy", "application/pdf")},
        headers=app_auth_headers,
    )

    assert response.status_code == 200, response.text
    assert received == {
        "consultant_name": "Anna Kowalska",
        "consultant_given_names": "Anna",
    }


@pytest.mark.parametrize(
    ("contract_status", "case_label"),
    [(None, "bez kontraktu"), ("void", "anulowany kontrakt")],
)
async def test_targeted_extract_rejects_candidate_without_eligible_contract(
    app_client: AsyncClient,
    app_auth_headers: dict,
    monkeypatch,
    contract_status: str | None,
    case_label: str,
):
    from app.api import client_orders as co

    client_id = await _seed_client("BIK S.A.")
    candidate_id = await _seed_candidate(
        "Osoba",
        "BezKontraktu",
        contract_client_id=client_id if contract_status else None,
        contract_status=contract_status or "active",
    )
    called = {"extract": False, "quota": False, "parse": False}

    def _must_not_extract(*args, **kwargs):
        called["extract"] = True
        raise AssertionError(f"file extraction must not run: {case_label}")

    async def _must_not_count_quota(*args, **kwargs):
        called["quota"] = True
        raise AssertionError(f"quota must not run: {case_label}")

    async def _must_not_parse(*args, **kwargs):
        called["parse"] = True
        raise AssertionError(f"parser must not run: {case_label}")

    monkeypatch.setattr(co, "extract_text", _must_not_extract)
    monkeypatch.setattr(co, "check_and_increment", _must_not_count_quota)
    monkeypatch.setattr(co, "parse_order_document", _must_not_parse)
    response = await app_client.post(
        f"/api/clients/{client_id}/orders/extract",
        data={"candidate_id": str(candidate_id)},
        files={"file": ("multi.pdf", b"%PDF-1.4 dummy", "application/pdf")},
        headers=app_auth_headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Candidate not found"
    assert called == {"extract": False, "quota": False, "parse": False}


async def test_targeted_extract_rejects_unknown_candidate_before_parsing(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.api import client_orders as co

    client_id = await _seed_client("BIK S.A.")
    parsed = False

    async def _must_not_parse(*args, **kwargs):
        nonlocal parsed
        parsed = True
        raise AssertionError("parser must not run for an unknown candidate")

    monkeypatch.setattr(co, "parse_order_document", _must_not_parse)
    response = await app_client.post(
        f"/api/clients/{client_id}/orders/extract",
        data={"candidate_id": "2147483647"},
        files={"file": ("multi.pdf", b"%PDF-1.4 dummy", "application/pdf")},
        headers=app_auth_headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Candidate not found"
    assert parsed is False


async def test_nordea_endpoint_forces_call_off_agreement_number(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.api import client_orders as co
    from app.services.order_pdf_parser import OrderExtraction

    client_id = await _seed_client("Nordea Bank ABP")
    # Polityka numeru zamówienia jest bramkowana LISTĄ ID w Coolify, nie
    # podciągiem nazwy: `Client.name` nadpisuje import z Traffita, a klient
    # bywa rodziną rekordów. Nazwa klienta zostaje w seedzie wyłącznie po to,
    # żeby test czytał się jak scenariusz z produkcji.
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(client_id))
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


async def test_bank_pocztowy_endpoint_converts_md_rate_and_forces_number(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Polityka BP na endpointcie: numer z „Numer pisma", stawka netto z wzoru
    ÷ 8 (w górę), oryginał MD obok, zero szumu w komunikatach."""
    from app.api import client_orders as co
    from app.services.order_pdf_parser import OrderExtraction

    client_id = await _seed_client("Bank Pocztowy S.A.")
    # Bramka po LIŚCIE ID w Coolify, nie po nazwie (nazwę nadpisuje Traffit).
    monkeypatch.setenv(
        "BANK_POCZTOWY_ORDER_EXTRACTION_CLIENT_IDS", f"999999,{client_id}"
    )
    monkeypatch.setattr(
        co,
        "extract_text",
        lambda path, filename: (
            "Bank Pocztowy S.A.\n"
            "Numer pisma: BP/DIT/2026/0451\n"
            "Zamówienie nr 445/2026\n"
            "Wynagrodzenie: 1600*1,23*20\n"
        ),
    )

    async def _noisy_ai(text: str) -> OrderExtraction:
        # Model wybrał brutto, jednostkę „day" i liczbę MD z wzoru — polityka
        # ma to wszystko wyprostować bez komunikatów niepewności.
        return OrderExtraction(
            title="445/2026",
            start_date="2026-09-01",
            end_date="2026-12-31",
            rate_client=Decimal("1968"),
            rate_unit="day",
            md_total=Decimal("20"),
            confidence={"title": 0.7, "rate_client": 0.6},
            uncertain=True,
            uncertain_reasons=[
                "Jednostka stawki (dzień) wywnioskowana z kontekstu",
                "Cena 1600 jest kwotą netto przed VAT (mnożnik 1,23)",
            ],
            source="claude",
        )

    monkeypatch.setattr(co, "parse_order_document", _noisy_ai)
    resp = await app_client.post(
        f"/api/clients/{client_id}/orders/extract",
        files={"file": ("bp.pdf", b"%PDF-1.4 dummy", "application/pdf")},
        headers=app_auth_headers,
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["title"] == "BP/DIT/2026/0451"
    assert Decimal(str(data["rate_client"])) == Decimal("200.00")
    assert Decimal(str(data["rate_client_md"])) == Decimal("1600")
    assert data["rate_unit"] == "hour"
    assert data["md_total"] is None
    assert data["uncertain"] is False
    assert data["uncertain_reasons"] == []
    assert data["title_needs_review"] is False


async def test_bank_pocztowy_missing_number_sets_review_flag_for_non_finance(
    app_client: AsyncClient, monkeypatch
):
    """Brak numeru: flaga `title_needs_review` MUSI przeżyć redakcję finansową
    (HoR nie widzi kwot, ale komunikat o numerze go dotyczy), a oryginalna
    stawka MD (`rate_client_md`) MUSI być zredagowana jak każda kwota."""
    from app.api import client_orders as co
    from app.services.order_pdf_parser import OrderExtraction

    client_id = await _seed_client("Bank Pocztowy S.A.")
    monkeypatch.setenv("BANK_POCZTOWY_ORDER_EXTRACTION_CLIENT_IDS", str(client_id))
    hor_headers = await _hor_headers(app_client)

    monkeypatch.setattr(
        co,
        "extract_text",
        # Ani „Numer pisma", ani „Zamówienie nr"; stawka bez wzoru VAT.
        lambda path, filename: "Umowa ramowa 9/2024. Stawka: 1600 zł/MD netto.",
    )

    async def _fake_parse(text: str) -> OrderExtraction:
        return OrderExtraction(
            title="9/2024",
            start_date="2026-09-01",
            end_date="2026-12-31",
            rate_client=Decimal("1600"),
            rate_unit="day",
            confidence={"title": 0.8, "rate_client": 0.9},
            uncertain=False,
            source="claude",
        )

    monkeypatch.setattr(co, "parse_order_document", _fake_parse)
    resp = await app_client.post(
        f"/api/clients/{client_id}/orders/extract",
        files={"file": ("bp.pdf", b"%PDF-1.4 dummy", "application/pdf")},
        headers=hor_headers,
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Polityka odrzuciła numer spoza hierarchii pól i podniosła flagę.
    assert data["title"] is None
    assert data["title_needs_review"] is True
    # Kwoty (w tym oryginał MD) zredagowane dla roli bez VIEW_FINANCE.
    assert data["rate_client"] is None
    assert data["rate_client_md"] is None
    assert "rate_client_md" not in data["fields_confidence"]
    # Redakcja powodów nie gasi banera.
    assert data["uncertain"] is True


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


async def test_bnp_endpoint_reads_a_document_without_a_consultant_name(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """REGRESJA ZGŁOSZENIA: dla BNP odczyt nie dawał ani stawki, ani MD.

    PDF-y BNP nie zawierają imienia ani nazwiska — niosą wyłącznie numer ID
    konsultanta. Generyczny matcher jest fail-closed po nazwisku, więc przy
    podanym ``candidate_id`` czyścił stawkę i liczbę MD przy KAŻDYM odczycie.
    Dokument tego klienta jest z definicji jednoosobowy, więc parser nie
    dostaje nazwiska, a bramka bezpieczeństwa matchera jest pomijana.
    """
    from app.api import client_orders as co

    client_id = await _seed_client("BNP Paribas Bank Polska S.A.")
    candidate_id = await _seed_candidate(
        "Damian", "Krawczyk", contract_client_id=client_id
    )
    monkeypatch.setenv("BNP_ORDER_EXTRACTION_CLIENT_IDS", f"999999,{client_id}")
    monkeypatch.setattr(
        co,
        "extract_text",
        lambda path, filename: (
            "Zamówienie nr 3728_2026\n"
            "Konsultant ID: 4711\n"
            "Okres realizacji: 08-2026 do 12-2026\n"
            "Cena netto: 1 040,00 PLN\n"
            "Szt.: 105\n"
        ),
    )

    resp = await app_client.post(
        f"/api/clients/{client_id}/orders/extract",
        data={"candidate_id": str(candidate_id)},
        files={"file": ("bnp.pdf", b"%PDF-1.4 dummy", "application/pdf")},
        headers=app_auth_headers,
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Reguła klientowa MUSI się nazwać — inaczej niewłączona bramka wygląda
    # dokładnie tak samo jak włączona (patrz `client_policy`).
    assert data["client_policy"] == "BNP"
    # Bez poprawki oba pola wracały jako `null`.
    assert Decimal(str(data["rate_client"])) == Decimal("1040.00")
    assert data["rate_unit"] == "day"
    assert Decimal(str(data["md_total"])) == Decimal("105")
    assert data["start_date"] == "2026-08-01"
    # Ostatni dzień miesiąca, nie pierwszy i nie „31" na sztywno.
    assert data["end_date"] == "2026-12-31"
    assert data["consultant_ref"] == "4711"


async def test_bnp_consultant_ref_survives_finance_redaction(
    app_client: AsyncClient, monkeypatch
):
    """Numer ID nie jest kwotą — rola bez VIEW_FINANCE też musi go zobaczyć.

    To jedyny ślad tożsamości w dokumencie BNP; ukrycie go zostawiłoby
    operatora bez możliwości potwierdzenia, czyjego zamówienia dotyczy plik.
    """
    from app.api import client_orders as co

    client_id = await _seed_client("BNP Paribas Bank Polska S.A.")
    monkeypatch.setenv("BNP_ORDER_EXTRACTION_CLIENT_IDS", str(client_id))
    hor_headers = await _hor_headers(app_client)
    monkeypatch.setattr(
        co,
        "extract_text",
        lambda path, filename: (
            "Konsultant ID: 4711\n08-2026 do 12-2026\nCena netto: 1 040,00\nSzt.: 105\n"
        ),
    )

    resp = await app_client.post(
        f"/api/clients/{client_id}/orders/extract",
        files={"file": ("bnp.pdf", b"%PDF-1.4 dummy", "application/pdf")},
        headers=hor_headers,
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["consultant_ref"] == "4711"
    assert data["rate_client"] is None
    # Liczba MD jest operacyjna, nie finansowa — zostaje.
    assert Decimal(str(data["md_total"])) == Decimal("105")


async def test_bnp_policy_does_not_leak_to_other_clients(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Bramka po ID: klient spoza listy zachowuje dotychczasowe zachowanie."""
    from app.api import client_orders as co

    client_id = await _seed_client("Inny Bank S.A.")
    monkeypatch.setenv("BNP_ORDER_EXTRACTION_CLIENT_IDS", "999999")
    monkeypatch.setattr(
        co,
        "extract_text",
        lambda path, filename: "Konsultant ID: 4711\nCena netto: 1 040,00\nSzt.: 105\n",
    )

    resp = await app_client.post(
        f"/api/clients/{client_id}/orders/extract",
        files={"file": ("other.pdf", b"%PDF-1.4 dummy", "application/pdf")},
        headers=app_auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["consultant_ref"] is None


async def test_extraction_reports_which_client_policy_applied(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Nazwa reguły klientowej wraca w odpowiedzi odczytu.

    Bez tego niewłączona bramka klienta jest NIEWIDOCZNA: odczyt „działa" (model
    coś wypełnia), a jedynym objawem jest numer zamówienia wzięty z niewłaściwego
    pola dokumentu — dokładnie objaw zgłoszony dla Nordei.
    """
    from app.api import client_orders as co

    client_id = await _seed_client("Nordea Bank Abp SA")
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", f"999999,{client_id}")
    monkeypatch.setattr(
        co,
        "extract_text",
        lambda path, filename: (
            "Frame Agreement number: FA-4400011111\n"
            "Call Off Agreement number: COA-4500030222\n"
        ),
    )

    resp = await app_client.post(
        f"/api/clients/{client_id}/orders/extract",
        files={"file": ("nordea.pdf", b"%PDF-1.4 dummy", "application/pdf")},
        headers=app_auth_headers,
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["client_policy"] == "Nordea"
    # Numer UMOWY RAMOWEJ nie może wygrać z numerem zamówienia.
    assert data["title"] == "COA-4500030222"


async def test_extraction_says_when_a_client_has_no_rules_yet(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Brak reguł to INFORMACJA, nie błąd — odczyt ogólny nadal działa."""
    from app.api import client_orders as co

    client_id = await _seed_client("Klient Bez Regul S.A.")
    monkeypatch.setattr(
        co, "extract_text", lambda path, filename: "Zamówienie nr 445/2026\n"
    )

    resp = await app_client.post(
        f"/api/clients/{client_id}/orders/extract",
        files={"file": ("inny.pdf", b"%PDF-1.4 dummy", "application/pdf")},
        headers=app_auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["client_policy"] is None
