"""Konsultant nieaktywny/nieznaleziony + historia osób na zamówieniu (ticket 09.2026).

Kryteria akceptacji:

* osoba z PDF-a, której współpraca się zakończyła, dostaje wprost komunikat
  i wybór (zostaw jako historię / wznów / zastąp / usuń) — nie cichy błąd;
* zapis historyczny nie wznawia kontraktu i nie trafia do aktywnej obsady;
* wykorzystana kwota/MD osoby usuniętej z zamówienia NIE wraca do puli;
* dodana ręcznie osoba (zastępstwo) ma widoczne: kto ją dodał, kiedy i za kogo;
* PDF zamówienia jest podpinany także do profilu osoby dodanej później.

Nazwiska, numery i kwoty są zmyślone (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.scheduling import business_today


POLKOMTEL_TEXT = """1
ZLECENIE WYKONAWCZE nr SAP 4500987654 / 2026 rok
zawarte w dniu 30.03.2026
III. Warunki finansowe i harmonogram płatności
1. Wartość Zlecenia albo stawki z planowaną pracochłonnością (szczegółowe wyliczenia):
na kwotę 40 000 PLN
na co składa się:
Cena netto 1MD po upuście [PLN] Cena total [PLN] Konsultant
840,00 zł Nowak-Testowa Ewa
40 000,00 zł
1 280,00 zł Odeszły Marian
2. Wskazanie sposobu rozliczenia:
[x] na zasadzie przepracowanego czasu
"""


async def _seed() -> dict:
    """Klient z trzema osobami: aktywna, zakończona, zastępca (aktywny)."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus, RateUnit

    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Zlecenia-{suffix}")
        db.add(client)
        await db.flush()
        ids: dict = {"client_id": client.id}
        people = (
            ("active", "Ewa", "Nowak-Testowa", ContractStatus.active, None),
            (
                "ended",
                "Marian",
                "Odeszły",
                ContractStatus.ended,
                business_today() - timedelta(days=30),
            ),
            ("substitute", "Tadeusz", f"Zastępca{suffix}", ContractStatus.active, None),
        )
        for key, name, lastname, status, end in people:
            candidate = Candidate(
                name=name, lastname=lastname, email=f"hist-{key}-{suffix}@example.com"
            )
            db.add(candidate)
            await db.flush()
            contract = Contract(
                candidate_id=candidate.id,
                client_id=client.id,
                status=status,
                start_date=business_today() - timedelta(days=200),
                end_date=end,
                rate_candidate=Decimal("700.000"),
                rate_unit=RateUnit.daily,
            )
            db.add(contract)
            await db.flush()
            ids[f"{key}_contract"] = contract.id
            ids[f"{key}_candidate"] = candidate.id
            ids[f"{key}_end"] = end
        await db.commit()
        return ids


def _line(contract_id: int, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "rate_cost": 700,
        "rate_revenue": 1280,
        "start_date": (business_today() - timedelta(days=100)).isoformat(),
    }
    payload.update(overrides)
    return payload


async def _create_cost_group(
    app_client: AsyncClient, headers: dict, client_id: int, lines: list[dict]
) -> dict:
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": f"SAP 45{uuid.uuid4().int % 10**8:08d}",
            "start_date": (business_today() - timedelta(days=100)).isoformat(),
            "order_type": "cost",
            "is_cost_based": True,
            "budget_amount": 40000,
            "lines": lines,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _group(app_client: AsyncClient, headers: dict, client_id: int, gid: int):
    listing = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=headers
    )
    assert listing.status_code == 200, listing.text
    return next(g for g in listing.json()["groups"] if g["id"] == gid)


def _by_contract(group: dict, contract_id: int) -> dict:
    return next(line for line in group["lines"] if line["contract_id"] == contract_id)


# ── Odczyt PDF w oknie „Nowe zamówienie" ────────────────────────────────────


async def test_polkomtel_pdf_reads_rows_and_names_the_ended_consultant(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.services import order_group_extraction as og
    from app.services.order_document_text import OrderDocumentText
    from app.services.order_pdf_parser import ConsultantOrderRow, OrderExtraction

    ids = await _seed()
    monkeypatch.setenv("POLKOMTEL_ORDER_EXTRACTION_CLIENT_IDS", str(ids["client_id"]))
    monkeypatch.setattr(
        og,
        "extract_order_text",
        lambda path, filename: OrderDocumentText(
            text=POLKOMTEL_TEXT,
            page_count=2,
            ocr_used=False,
            ocr_capped=False,
            reextracted_with=None,
            letter_spacing_ratio=0.0,
        ),
    )

    async def _model(text: str, *, all_rows: bool = False, **_kw) -> OrderExtraction:
        # Model bez wiedzy o typie zamówienia: zgłasza brak MD i zeruje stawkę.
        return OrderExtraction(
            title="PZ/0000001111",
            start_date="2026-03-30",
            end_date="2026-12-31",
            consultant_rows=[
                ConsultantOrderRow(
                    consultant_name="Nowak-Testowa Ewa",
                    uncertain=True,
                    uncertain_reason="Brak informacji o liczbie MD",
                ),
                ConsultantOrderRow(consultant_name="Odeszły Marian", uncertain=True),
            ],
            uncertain=True,
            uncertain_reasons=["Brak informacji o liczbie MD"],
            source="claude",
        )

    monkeypatch.setattr(og, "parse_order_document", _model)
    resp = await app_client.post(
        f"/api/clients/{ids['client_id']}/order-groups/extract",
        files={"file": ("zlecenie.pdf", b"%PDF-1.4 dummy", "application/pdf")},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["order_number"] == "SAP 4500987654"
    assert data["start_date"] == "2026-03-30"
    assert data["end_date"] is None and data["open_ended"] is True
    assert data["total_value"] == 40000
    assert data["md_scope"] is None
    assert data["client_policy"] == "Polkomtel"
    # Sedno ticketu: brak MD nie jest błędem zamówienia kosztowego.
    assert data["uncertain"] is False and data["uncertain_reasons"] == []

    active, ended = data["lines"]
    assert (active["rate_revenue"], active["rate_revenue_unit"]) == (840, "day")
    assert active["match_status"] == "confirm"  # odwrotna kolejność imienia
    assert active["contract"]["contract_id"] == ids["active_contract"]
    assert active["warnings"] == []

    assert (ended["rate_revenue"], ended["rate_revenue_unit"]) == (1280, "day")
    assert ended["match_status"] == "inactive"
    assert ended["contract"]["contract_id"] == ids["ended_contract"]
    assert "nie ma już aktywnej współpracy" in ended["match_reason"]


# ── Zapis historyczny i zastępstwo przy zakładaniu ──────────────────────────


async def test_historical_line_does_not_revive_the_contract(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract

    ids = await _seed()
    ended_on = ids["ended_end"]
    group = await _create_cost_group(
        app_client,
        app_auth_headers,
        ids["client_id"],
        [
            _line(
                ids["active_contract"],
                rate_revenue=840,
                document_name="Nowak-Testowa Ewa",
            ),
            _line(
                ids["ended_contract"],
                historical=True,
                end_date=ended_on.isoformat(),
                document_name="Odeszły Marian",
            ),
            _line(ids["substitute_contract"], replaces_name="Odeszły Marian"),
        ],
    )
    body = await _group(app_client, app_auth_headers, ids["client_id"], group["id"])
    assert body["active_consultants"] == 2

    historical = _by_contract(body, ids["ended_contract"])
    assert historical["status"] == "completed" and historical["is_active"] is False
    assert historical["end_date"] == ended_on.isoformat()
    assert historical["cooperation_ended_on"] == ended_on.isoformat()
    assert historical["origin"] == "document"

    from_pdf = _by_contract(body, ids["active_contract"])
    assert from_pdf["origin"] == "document" and from_pdf["replaces_name"] is None

    substitute = _by_contract(body, ids["substitute_contract"])
    assert substitute["origin"] == "manual"
    assert substitute["replaces_name"] == "Odeszły Marian"
    assert substitute["added_by_name"]
    assert substitute["added_at"]

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, ids["ended_contract"])
        assert contract.status.value == "ended", "zapis historyczny wznowił kontrakt"


async def test_historical_line_for_a_working_consultant_is_refused(
    app_client: AsyncClient, app_auth_headers: dict
):
    ids = await _seed()
    resp = await app_client.post(
        f"/api/clients/{ids['client_id']}/order-groups",
        json={
            "order_number": "SAP 4500000001",
            "start_date": (business_today() - timedelta(days=100)).isoformat(),
            "order_type": "cost",
            "is_cost_based": True,
            "budget_amount": 40000,
            "lines": [
                _line(
                    ids["active_contract"],
                    historical=True,
                    end_date=(business_today() - timedelta(days=1)).isoformat(),
                )
            ],
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert "nadal aktywny" in resp.text


def test_historical_line_needs_a_contract_and_an_end_date():
    from pydantic import ValidationError

    from app.schemas.client_order_group import OrderLineCreate

    base = {"rate_cost": 1, "rate_revenue": 1, "start_date": "2031-01-01"}
    with pytest.raises(ValidationError, match="istniejącego kontraktu"):
        OrderLineCreate(candidate_id=1, historical=True, end_date="2031-02-01", **base)
    with pytest.raises(ValidationError, match="daty końca udziału"):
        OrderLineCreate(contract_id=1, historical=True, **base)


# ── Usunięcie z zamówienia nie zabiera zużycia (409) ───────────────────────


async def test_removing_a_consultant_with_invoices_is_refused_and_pool_unchanged(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order_group import ClientOrderGroup
    from app.models.md_consumption import ClientOrderInvoiceConsumption
    from app.services.cost_orders import settle_group

    ids = await _seed()
    group = await _create_cost_group(
        app_client,
        app_auth_headers,
        ids["client_id"],
        [_line(ids["active_contract"]), _line(ids["substitute_contract"])],
    )
    leaving = _by_contract(group, ids["active_contract"])["id"]
    async with AsyncSessionLocal() as db:
        db.add(
            ClientOrderInvoiceConsumption(
                order_id=leaving,
                period_month="2026-05",
                invoice_amount=Decimal("25720"),
                source="manual",
            )
        )
        await db.flush()
        await settle_group(db, await db.get(ClientOrderGroup, group["id"]))
        await db.commit()

    before = await _group(app_client, app_auth_headers, ids["client_id"], group["id"])
    assert before["budget_remaining"] == pytest.approx(14280.0)

    resp = await app_client.delete(
        f"/api/clients/{ids['client_id']}/order-groups/{group['id']}/lines/{leaving}",
        headers=app_auth_headers,
    )
    # Od 09.2026 usunięcie kasuje linię trwale, więc linia z fakturami jest
    # odrzucana — kaskada zabrałaby faktury i zwróciła kwotę do puli.
    assert resp.status_code == 409, resp.text

    after = await _group(app_client, app_auth_headers, ids["client_id"], group["id"])
    assert after["budget_remaining"] == pytest.approx(14280.0), (
        "zużycie wróciło do puli"
    )
    assert after["budget_used"] == pytest.approx(25720.0)
    kept = next(line for line in after["lines"] if line["id"] == leaving)
    assert kept["removed_from_order"] is False
    assert kept["status"] == "active"
    assert kept["invoiced_total"] == pytest.approx(25720.0)


# ── „Zostaw jako historię" i zastępstwo za osobę z zamówienia ──────────────


async def test_keep_history_records_who_decided_and_refuses_working_people(
    app_client: AsyncClient, app_auth_headers: dict
):
    ids = await _seed()
    group = await _create_cost_group(
        app_client,
        app_auth_headers,
        ids["client_id"],
        [
            _line(ids["active_contract"]),
            _line(
                ids["ended_contract"],
                historical=True,
                end_date=ids["ended_end"].isoformat(),
            ),
        ],
    )
    base = f"/api/clients/{ids['client_id']}/order-groups/{group['id']}/lines"
    working = _by_contract(group, ids["active_contract"])["id"]
    ended = _by_contract(group, ids["ended_contract"])["id"]

    refused = await app_client.post(
        f"{base}/{working}/keep-history", headers=app_auth_headers
    )
    assert refused.status_code == 409, refused.text

    for _ in range(2):  # drugie kliknięcie nie dubluje wpisu
        kept = await app_client.post(
            f"{base}/{ended}/keep-history", headers=app_auth_headers
        )
        assert kept.status_code == 204, kept.text

    body = await _group(app_client, app_auth_headers, ids["client_id"], group["id"])
    line = _by_contract(body, ids["ended_contract"])
    assert line["history_kept_at"] and line["history_kept_by_name"]
    events = await app_client.get(
        f"/api/clients/{ids['client_id']}/order-groups/{group['id']}/events",
        headers=app_auth_headers,
    )
    kept_events = [
        ev
        for ev in events.json()["events"]
        if ev["event_type"] == "zakonczenie_konsultanta"
        and "zostawiony na zamówieniu" in ev["description"]
    ]
    assert len(kept_events) == 1


async def test_substitute_added_later_names_the_replaced_person_and_gets_the_pdf(
    app_client: AsyncClient, app_auth_headers: dict
):
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.contract_document import ContractDocument

    ids = await _seed()
    group = await _create_cost_group(
        app_client,
        app_auth_headers,
        ids["client_id"],
        [
            _line(
                ids["ended_contract"],
                historical=True,
                end_date=ids["ended_end"].isoformat(),
            )
        ],
    )
    base = f"/api/clients/{ids['client_id']}/order-groups/{group['id']}"
    upload = await app_client.put(
        f"{base}/file",
        files={"file": ("zlecenie.pdf", b"%PDF-1.4 zlecenie", "application/pdf")},
        headers=app_auth_headers,
    )
    assert upload.status_code in (200, 204), upload.text
    replaced = group["lines"][0]["id"]

    wrong = await app_client.post(
        f"{base}/lines",
        json=_line(ids["substitute_contract"], replaces_order_id=replaced + 10_000),
        headers=app_auth_headers,
    )
    assert wrong.status_code == 422, wrong.text

    added = await app_client.post(
        f"{base}/lines",
        json=_line(ids["substitute_contract"], replaces_order_id=replaced),
        headers=app_auth_headers,
    )
    assert added.status_code == 201, added.text

    body = await _group(app_client, app_auth_headers, ids["client_id"], group["id"])
    substitute = _by_contract(body, ids["substitute_contract"])
    assert substitute["origin"] == "manual"
    assert substitute["replaces_name"] == "Marian Odeszły"
    assert substitute["added_by_name"]

    async with AsyncSessionLocal() as db:
        docs = (
            (
                await db.execute(
                    select(ContractDocument).where(
                        ContractDocument.contract_id == ids["substitute_contract"],
                        ContractDocument.source_order_group_id == group["id"],
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(docs) == 1, "PDF zamówienia nie trafił do profilu zastępcy"


# ── Przegląd adwersarialny: cykl życia ──────────────────────────────────────


async def test_md_order_stays_open_while_an_offboarding_decision_is_pending(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Zamknięcie po wyczerpaniu MD odebrałoby DL-owi „przywróć" i „przenieś"."""
    from sqlalchemy import delete, select

    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.client_order_group import ClientOrderGroup
    from app.models.client_order_offboarding import ClientOrderOffboardingCase
    from app.services.order_md_exhaustion import sync_md_group_exhaustion

    ids = await _seed()
    monkeypatch.setenv("POLKOMTEL_ORDER_EXTRACTION_CLIENT_IDS", str(ids["client_id"]))
    resp = await app_client.post(
        f"/api/clients/{ids['client_id']}/order-groups",
        json={
            "order_number": f"SAP 46{uuid.uuid4().int % 10**8:08d}",
            "start_date": (business_today() - timedelta(days=100)).isoformat(),
            "order_type": "md",
            "md_budget_mode": "per_person",
            "lines": [
                _line(ids["active_contract"], input_mode="md", input_value=10),
                _line(
                    ids["ended_contract"],
                    input_mode="md",
                    input_value=20,
                    historical=True,
                    end_date=ids["ended_end"].isoformat(),
                ),
            ],
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    group = resp.json()
    working = _by_contract(group, ids["active_contract"])["id"]
    departed = _by_contract(group, ids["ended_contract"])["id"]

    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, working)
        line.md_remaining = Decimal("0")
        line.status = ClientOrderStatus.completed
        db.add(
            ClientOrderOffboardingCase(
                contract_id=ids["ended_contract"],
                order_id=departed,
                order_group_id=group["id"],
                client_id=ids["client_id"],
                effective_date=ids["ended_end"],
                uses_shared_md_pool=False,
                remaining_md_snapshot=Decimal("20"),
            )
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        assert await sync_md_group_exhaustion(db, group["id"]) is False
        await db.commit()
        # Decyzja zapadła (sprawy już nie ma) → zamówienie może się zakończyć,
        # bo osoba z zakończoną współpracą nie trzyma go otwartego.
        await db.execute(
            delete(ClientOrderOffboardingCase).where(
                ClientOrderOffboardingCase.order_id == departed
            )
        )
        assert await sync_md_group_exhaustion(db, group["id"]) is True
        await db.commit()
        status = await db.scalar(
            select(ClientOrderGroup.status).where(ClientOrderGroup.id == group["id"])
        )
        assert status == "completed"


async def test_historical_line_needs_an_ended_status_not_just_terminated_at(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`terminated_at` przeżywa wznowienie kontraktu — nie dowodzi końca pracy."""
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract

    ids = await _seed()
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, ids["active_contract"])
        contract.terminated_at = business_today() - timedelta(days=60)
        await db.commit()
    resp = await app_client.post(
        f"/api/clients/{ids['client_id']}/order-groups",
        json={
            "order_number": "SAP 4500000002",
            "start_date": (business_today() - timedelta(days=100)).isoformat(),
            "order_type": "cost",
            "is_cost_based": True,
            "budget_amount": 40000,
            "lines": [
                _line(
                    ids["active_contract"],
                    historical=True,
                    end_date=(business_today() - timedelta(days=60)).isoformat(),
                )
            ],
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text


async def test_historical_line_leaves_the_ended_contract_untouched(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract, RateUnit

    ids = await _seed()
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, ids["ended_contract"])
        contract.rate_unit = RateUnit.hourly
        contract.rate_candidate = Decimal("90.000")
        await db.commit()
    await _create_cost_group(
        app_client,
        app_auth_headers,
        ids["client_id"],
        [
            _line(
                ids["ended_contract"],
                historical=True,
                end_date=ids["ended_end"].isoformat(),
            )
        ],
    )
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, ids["ended_contract"])
        assert contract.status.value == "ended"
        assert contract.rate_unit == RateUnit.hourly
        assert contract.rate_candidate == Decimal("90.000")
        assert contract.client_order_start_date is None


async def test_keep_history_refuses_a_person_whose_contract_is_still_active(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus

    ids = await _seed()
    group = await _create_cost_group(
        app_client, app_auth_headers, ids["client_id"], [_line(ids["active_contract"])]
    )
    line_id = group["lines"][0]["id"]
    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, line_id)
        line.status = ClientOrderStatus.completed
        await db.commit()
    resp = await app_client.post(
        f"/api/clients/{ids['client_id']}/order-groups/{group['id']}/lines/{line_id}/keep-history",
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text


# ── Faza B: „Zastąpiony → następca" w kolumnie, sumy pozycji umowy ───────────


async def _create_md_group(
    app_client: AsyncClient, headers: dict, client_id: int, lines: list[dict]
) -> dict:
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": f"CeZ-{uuid.uuid4().hex[:6]}",
            "start_date": (business_today() - timedelta(days=100)).isoformat(),
            "order_type": "md",
            "md_budget_mode": "per_person",
            "lines": lines,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_replacement_sets_the_predecessor_column_and_positions_skip_the_replaced(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Zastępstwo wiąże linie kolumną: poprzednik wnosi zużycie, nie budżet."""
    ids = await _seed()
    group = await _create_md_group(
        app_client,
        app_auth_headers,
        ids["client_id"],
        [_line(ids["active_contract"], input_mode="md", input_value=50)],
    )
    base = f"/api/clients/{ids['client_id']}/order-groups/{group['id']}"
    replaced = group["lines"][0]
    consumption = await app_client.put(
        f"{base}/lines/{replaced['id']}/consumptions/2026-06",
        json={"md_reported": 20, "status": "accepted"},
        headers=app_auth_headers,
    )
    assert consumption.status_code == 200, consumption.text

    added = await app_client.post(
        f"{base}/lines",
        json=_line(
            ids["substitute_contract"],
            input_mode="md",
            input_value=40,
            replaces_order_id=replaced["id"],
        ),
        headers=app_auth_headers,
    )
    assert added.status_code == 201, added.text
    substitute = added.json()
    assert substitute["predecessor_order_id"] == replaced["id"]
    assert substitute["predecessor_consultant_name"] == "Ewa Nowak-Testowa"

    body = await _group(app_client, app_auth_headers, ids["client_id"], group["id"])
    previous = _by_contract(body, ids["active_contract"])
    successor = _by_contract(body, ids["substitute_contract"])
    assert previous["replaced_by_order_id"] == successor["id"]
    assert previous["replaced_by_consultant_name"] == successor["consultant_name"]
    assert successor["replaced_by_order_id"] is None
    assert successor["replaces_name"] == "Ewa Nowak-Testowa"
    # Poprzednik NIE jest zamykany przez zastępstwo — to nie zamiana.
    assert previous["status"] == "active"
    # Pozycje umowy: tylko następca (40 MD); zużycie: obie osoby (20 MD).
    assert body["md_positions_total"] == 40
    assert body["md_used_total"] == 20
    assert body["contract_value_pln"] == pytest.approx(40 * 1280)
    assert body["used_value_pln"] == pytest.approx(20 * 1280)
