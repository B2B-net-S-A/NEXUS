"""„Zczytaj i uzupełnij całe zamówienie" — plan z jednego PDF-a (ticket 09.2026).

Kryterium akceptacji: PDF BIK z dwiema pozycjami (Krzysztof Suwała, Paweł
Łaski) daje w jednym kroku karty obu osób — stawka kosztowa z kontraktu,
stawka przychodowa i MD z PDF-a, każda wartość z opisem źródła.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.services.order_group_extraction import document_position_labels

_TODAY = date(2026, 9, 3)

BIK_TEXT = """B2B.NET S.A
ZAMÓWIENIE
Numer/data zamówienia
4500030845 / 20260903
Na fakturze proszę powołać się na nr zamówienia : 4500030845
Poz.Przedmiot Ilość zamów. Jedn. Cena jednostk. Wart.netto
10 Rozwój Strumienia Detalicznego 35,000 SZT 1.080,00 37.800,00
Profil UR - Krzysztof Suwała
Obowiązująca stawka za osobę wynosi 1080,- zł/MD
W wymiarze 35 MD (roboczo dni). Rozliczenie w trybie T&M.
20 Rozwój Strumienia Detalicznego 42,000 SZT 1.280,00 53.760,00
Profil UR - Paweł Łaski
Obowiązująca stawka za osobę wynosi 1280,- zł/MD
W wymiarze 42 MD (roboczo dni). Rozliczenie w trybie T&M.
Łącz. wart. netto bez VAT 91.560,00 PLN
"""


def test_position_labels_follow_the_table_rows():
    assert document_position_labels(BIK_TEXT, ["Krzysztof Suwała", "Paweł Łaski"]) == [
        "10",
        "20",
    ]


def test_position_labels_do_not_depend_on_row_order():
    assert document_position_labels(BIK_TEXT, ["Paweł Łaski", "Krzysztof Suwała"]) == [
        "20",
        "10",
    ]


def test_position_label_is_unknown_rather_than_borrowed():
    text = "Zamówienie 445\nJan Kowalski — 20 MD\nAnna Nowak — 10 MD\n"
    # Brak numeru pozycji: nie wolno pożyczyć „445" ani cudzej linii.
    assert document_position_labels(text, ["Jan Kowalski", "Anna Nowak", None]) == [
        None,
        None,
        None,
    ]


# ── Endpoint ────────────────────────────────────────────────────────────────


async def _seed_bik_client(*, prefix_laski: str = "") -> dict[str, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus, RateUnit

    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"BIK-plan-{suffix}")
        db.add(client)
        await db.flush()
        ids: dict[str, int] = {"client_id": client.id}
        people = (
            ("suwala", "Krzysztof", "Suwała", Decimal("148.750")),
            # Zapis bez polskich znaków — ticket: ma dopasować się automatycznie.
            ("laski", f"{prefix_laski}Pawel".strip(), "Laski", Decimal("160.000")),
        )
        for key, name, lastname, rate in people:
            candidate = Candidate(
                name=name,
                lastname=lastname,
                email=f"plan-{key}-{suffix}@example.com",
            )
            db.add(candidate)
            await db.flush()
            contract = Contract(
                candidate_id=candidate.id,
                client_id=client.id,
                status=ContractStatus.active,
                start_date=_TODAY - timedelta(days=90),
                rate_candidate=rate,
                rate_unit=RateUnit.daily,
            )
            db.add(contract)
            await db.flush()
            ids[f"{key}_contract"] = contract.id
            ids[f"{key}_candidate"] = candidate.id
        await db.commit()
        return ids


def _patch_pipeline(monkeypatch) -> None:
    from app.services import order_group_extraction as og
    from app.services.order_document_text import OrderDocumentText
    from app.services.order_pdf_parser import ConsultantOrderRow, OrderExtraction

    monkeypatch.setattr(
        og,
        "extract_order_text",
        lambda path, filename: OrderDocumentText(
            text=BIK_TEXT,
            page_count=1,
            ocr_used=False,
            ocr_capped=False,
            reextracted_with=None,
            letter_spacing_ratio=0.0,
        ),
    )

    async def _fake_parse(
        text: str, *, all_rows: bool = False, **_kw
    ) -> OrderExtraction:
        assert all_rows is True, "okno nowego zamówienia czyta WSZYSTKIE osoby"
        return OrderExtraction(
            title="4500030845",
            start_date="2026-09-03",
            total_value=Decimal("91560"),
            currency="PLN",
            consultant_rows=[
                ConsultantOrderRow(
                    consultant_name="Krzysztof Suwała",
                    rate_client=Decimal("1080"),
                    rate_unit="day",
                    md_total=Decimal("35"),
                    uncertain=False,
                ),
                ConsultantOrderRow(
                    consultant_name="Paweł Łaski",
                    rate_client=Decimal("1280"),
                    rate_unit="day",
                    md_total=Decimal("42"),
                    uncertain=False,
                ),
            ],
            uncertain=False,
            source="claude",
        )

    monkeypatch.setattr(og, "parse_order_document", _fake_parse)


async def _post_pdf(app_client: AsyncClient, client_id: int, headers: dict):
    return await app_client.post(
        f"/api/clients/{client_id}/order-groups/extract",
        files={"file": ("4500030845.pdf", b"%PDF-1.4 dummy", "application/pdf")},
        headers=headers,
    )


async def test_bik_pdf_fills_every_consultant_card_in_one_step(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    ids = await _seed_bik_client()
    _patch_pipeline(monkeypatch)

    resp = await _post_pdf(app_client, ids["client_id"], app_auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["order_number"] == "4500030845"
    assert data["start_date"] == "2026-09-03"
    assert data["total_value"] == 91560
    assert len(data["lines"]) == 2

    suwala, laski = data["lines"]
    assert suwala["document_name"] == "Krzysztof Suwała"
    assert suwala["match_status"] == "auto"
    assert suwala["contract"]["contract_id"] == ids["suwala_contract"]
    # Stawka kosztowa — z kontraktu; przychodowa i MD — z PDF-a, poz. 10.
    assert suwala["contract"]["rate_cost"] == 148.75
    assert suwala["contract"]["rate_cost_unit"] == "daily"
    assert suwala["rate_revenue"] == 1080
    assert suwala["rate_revenue_unit"] == "day"
    assert suwala["md_total"] == 35
    assert suwala["position_label"] == "10"

    # „Pawel Laski" (bez polskich znaków) → automatycznie do „Paweł Łaski".
    assert laski["match_status"] == "auto"
    assert laski["contract"]["contract_id"] == ids["laski_contract"]
    assert laski["contract"]["contractor_name"] == "Pawel Laski"
    assert laski["md_total"] == 42
    assert laski["position_label"] == "20"


async def test_prefixed_contractor_name_needs_confirmation(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    ids = await _seed_bik_client(prefix_laski="Active ")
    _patch_pipeline(monkeypatch)

    resp = await _post_pdf(app_client, ids["client_id"], app_auth_headers)
    assert resp.status_code == 200, resp.text
    laski = resp.json()["lines"][1]
    assert laski["match_status"] == "confirm"
    assert laski["contract"]["contractor_name"] == "Active Pawel Laski"
    assert "Active" in laski["match_reason"]


async def test_duplicate_name_at_the_client_is_never_picked_automatically(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.contract import Contract, ContractStatus

    ids = await _seed_bik_client()
    async with AsyncSessionLocal() as db:
        namesake = Candidate(
            name="Krzysztof",
            lastname="Suwala",
            email=f"plan-namesake-{uuid.uuid4().hex[:6]}@example.com",
        )
        db.add(namesake)
        await db.flush()
        db.add(
            Contract(
                candidate_id=namesake.id,
                client_id=ids["client_id"],
                status=ContractStatus.active,
                start_date=_TODAY - timedelta(days=10),
            )
        )
        await db.commit()
    _patch_pipeline(monkeypatch)

    resp = await _post_pdf(app_client, ids["client_id"], app_auth_headers)
    assert resp.status_code == 200, resp.text
    suwala = resp.json()["lines"][0]
    assert suwala["match_status"] == "ambiguous"
    assert suwala["contract"] is None
    assert len(suwala["options"]) == 2


async def test_rates_are_redacted_for_a_delivery_lead_outside_the_portfolio(
    app_client: AsyncClient, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    ids = await _seed_bik_client()
    _patch_pipeline(monkeypatch)
    email = f"dl-plan-{uuid.uuid4().hex[:8]}@example.com"
    password = f"P4ss_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="DL Plan",
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

    resp = await _post_pdf(app_client, ids["client_id"], headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total_value"] is None
    line = data["lines"][0]
    assert line["rate_revenue"] is None
    assert line["contract"]["rate_cost"] is None
    # Liczba MD jest operacyjna — przeżywa redakcję.
    assert line["md_total"] == 35


async def test_non_pdf_is_rejected_before_any_ai_call(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.services import order_group_extraction as og

    ids = await _seed_bik_client()

    async def _must_not_run(*_a, **_kw):
        raise AssertionError("parser nie może ruszyć dla złego pliku")

    monkeypatch.setattr(og, "parse_order_document", _must_not_run)
    resp = await app_client.post(
        f"/api/clients/{ids['client_id']}/order-groups/extract",
        files={"file": ("zamowienie.txt", b"abc", "text/plain")},
        headers=app_auth_headers,
    )
    assert resp.status_code == 415


# ── Zapis jednym wywołaniem ─────────────────────────────────────────────────


def _line(contract_id: int, *, md: int | None) -> dict:
    line = {
        "contract_id": contract_id,
        "rate_cost": 148.75,
        "rate_revenue": 1080,
        "start_date": _TODAY.isoformat(),
    }
    if md is not None:
        line.update({"input_mode": "md", "input_value": md})
    return line


async def test_md_order_with_all_consultants_is_created_active_in_one_call(
    app_client: AsyncClient, app_auth_headers: dict
):
    ids = await _seed_bik_client()
    resp = await app_client.post(
        f"/api/clients/{ids['client_id']}/order-groups",
        json={
            "order_number": "4500030845",
            "start_date": _TODAY.isoformat(),
            "order_type": "md",
            "md_budget_mode": "per_person",
            "status": "active",
            "lines": [
                _line(ids["suwala_contract"], md=35),
                _line(ids["laski_contract"], md=42),
            ],
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    group = resp.json()
    assert group["status"] in ("active", "scheduled")
    assert sorted(line["md_total"] for line in group["lines"]) == [35, 42]


@pytest.mark.parametrize("lines_md", [[], [35, None]])
async def test_active_md_order_without_complete_budgets_is_rejected(
    app_client: AsyncClient, app_auth_headers: dict, lines_md
):
    ids = await _seed_bik_client()
    contracts = [ids["suwala_contract"], ids["laski_contract"]]
    resp = await app_client.post(
        f"/api/clients/{ids['client_id']}/order-groups",
        json={
            "order_number": "4500030846",
            "start_date": _TODAY.isoformat(),
            "order_type": "md",
            "md_budget_mode": "per_person",
            "status": "active",
            "lines": [
                _line(contract_id, md=md)
                for contract_id, md in zip(contracts, lines_md)
            ],
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text


# ── Weryfikacja wierszy modelu regułą klienta (przegląd adwersarialny) ──────


def _row(name: str, rate: str | None, unit: str | None = "day", md: str | None = "35"):
    from app.services.order_pdf_parser import ConsultantOrderRow

    return ConsultantOrderRow(
        consultant_name=name,
        rate_client=Decimal(rate) if rate is not None else None,
        rate_unit=unit,
        md_total=Decimal(md) if md is not None else None,
        uncertain=False,
    )


def test_table_rule_wins_over_a_model_that_read_the_wrong_column():
    """Credit Agricole: model wziął liczbę MD (54) za stawkę — tabela PDF-a mówi 1100."""
    from app.services.order_group_extraction import _reconcile_with_evidence

    row = _row("Jan Kowalski", "54", "day", "54")
    rate, unit, md, gross, warnings = _reconcile_with_evidence(
        row.rate_client,
        row.rate_unit,
        row.md_total,
        None,
        row,
        [_row("Kowalski Jan", "1100", "day", "54")],
    )
    assert (rate, unit, md) == (Decimal("1100"), "day", Decimal("54"))
    assert any("różniła się od tabeli" in w for w in warnings)


def test_person_missing_from_the_table_rule_is_flagged_not_silent():
    from app.services.order_group_extraction import _reconcile_with_evidence

    row = _row("Anna Nowak", "900")
    rate, _, _, _, warnings = _reconcile_with_evidence(
        row.rate_client,
        row.rate_unit,
        row.md_total,
        None,
        row,
        [_row("Jan Kowalski", "1100")],
    )
    assert rate == Decimal("900")
    assert any("nie potwierdziła tej pozycji" in w for w in warnings)


def test_multi_person_document_without_rows_creates_no_nameless_card():
    from app.services.order_group_extraction import _document_rows
    from app.services.order_pdf_parser import OrderExtraction

    extraction = OrderExtraction(rate_client=Decimal("1000"), rate_unit="day")
    assert (
        _document_rows(extraction, single_consultant_document=False, ignores_md=False)
        == []
    )
    single = _document_rows(
        extraction, single_consultant_document=True, ignores_md=False
    )
    assert len(single) == 1 and single[0].consultant_name == ""


def test_orlen_collapses_on_off_site_rows_and_drops_document_md():
    from app.services.order_group_extraction import _document_rows
    from app.services.order_pdf_parser import OrderExtraction

    extraction = OrderExtraction(
        consultant_rows=[
            _row("Jan Kowalski", "1200", "day", "20"),
            _row("Jan Kowalski", "1200", "day", "5"),
        ]
    )
    rows = _document_rows(extraction, single_consultant_document=False, ignores_md=True)
    assert len(rows) == 1
    assert rows[0].md_total is None


async def test_endpoint_uses_the_client_table_rule_for_the_card_rate(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.services import order_group_extraction as og
    from app.services.order_policies.registry import OrderClientPolicy

    ids = await _seed_bik_client()
    _patch_pipeline(monkeypatch)
    policy = OrderClientPolicy(
        key="test_table",
        display_name="Test tabeli",
        env_var="TEST_TABLE_CLIENT_IDS",
        apply=lambda result, ctx: result,
        order=10,
        extract_rows=lambda text: [
            _row("Krzysztof Suwała", "1180", "day", "35"),
            _row("Paweł Łaski", "1280", "day", "42"),
        ],
    )
    monkeypatch.setattr(og, "active_policies", lambda client_id: [policy])

    resp = await _post_pdf(app_client, ids["client_id"], app_auth_headers)
    assert resp.status_code == 200, resp.text
    suwala, laski = resp.json()["lines"]
    assert suwala["rate_revenue"] == 1180
    assert any("różniła się od tabeli" in w for w in suwala["warnings"])
    assert laski["rate_revenue"] == 1280
    assert not any("tabeli" in w for w in laski["warnings"])
