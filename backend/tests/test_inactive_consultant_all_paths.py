"""Konsultant nieaktywny/nieznaleziony — JEDEN mechanizm na wszystkich ścieżkach.

Ticket 09.2026 (reguła ogólna dla wszystkich klientów rozliczanych w MD lub
kwotą budżetową, nie dla jednego klienta):

* osoba z PDF-a bez aktywnej współpracy albo nieznaleziona dostaje JEDEN,
  identyczny komunikat na każdej ścieżce odczytu (poczta, „Nowe zamówienie",
  „Uzupełnij zamówienie") i wybór zostaw / zastąp / usuń — nigdy cichy błąd,
  pominięcie ani ciche wznowienie kontraktu przez automat poczty;
* wykorzystana kwota/MD osoby usuniętej albo zastąpionej NIE wraca do puli —
  tak samo na zamówieniu kosztowym (układ Polkomtela) i MD per osoba (BIK).

Klient jest tu PARAMETREM, a nie gałęzią kodu: te same przypadki idą przez
zamówienie kosztowe i MD. Nazwiska, numery i kwoty są zmyślone (repo publiczne).
"""

from __future__ import annotations

import io
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.scheduling import business_today
from app.services.order_consultant_match import (
    ContractCandidate,
    MATCH_INACTIVE,
    MATCH_NONE,
    inactive_consultant_reason,
    resolve_contract,
    unknown_consultant_reason,
)
from app.services.order_mail_gate import VERDICT_REVIEW, GateInput, evaluate
from app.services.order_mail_planner import (
    ACTION_DECIDE_PERSON,
    ACTION_NEW_DRAFT,
    ACTION_REACTIVATE,
    ExistingOrder,
    plan_document,
)
from app.services.order_mail_resolver import (
    RosterContract,
    RosterPerson,
    resolve_rows,
)
from app.services.order_pdf_parser import ConsultantOrderRow, OrderExtraction

_TODAY = business_today()
_ENDED_ON = date(2031, 2, 12)


# ── Komunikat: jedno źródło dla okna i poczty ──────────────────────────────


def test_window_and_mail_use_the_same_sentence():
    contracts = [
        ContractCandidate(
            contract_id=9,
            candidate_id=5,
            contractor_name="Marian Odchodzący",
            status="ended",
            start_date=date(2030, 1, 1),
            end_date=_ENDED_ON,
        )
    ]
    window = resolve_contract("Marian Odchodzący", contracts)
    assert window.status == MATCH_INACTIVE
    assert window.reason == inactive_consultant_reason(
        "Marian Odchodzący", ended_on=_ENDED_ON
    )
    assert "nie ma już aktywnej współpracy" in window.reason
    for choice in ("zapis historyczny", "wznów", "zastąp", "usuń"):
        assert choice in window.reason

    missing = resolve_contract("Nikt Nieznany", contracts)
    assert missing.status == MATCH_NONE
    assert missing.reason == unknown_consultant_reason("Nikt Nieznany")
    assert "Nie znaleziono „Nikt Nieznany” w systemie" in missing.reason


# ── Poczta: MD i kosztowe czekają na decyzję, okresowe bez zmian ────────────


def _row(name: str) -> ConsultantOrderRow:
    return ConsultantOrderRow(
        consultant_name=name,
        rate_client=Decimal("1280.00"),
        rate_unit="day",
        md_total=Decimal("20"),
        start_date="2031-04-01",
        end_date="2031-06-30",
        uncertain=False,
    )


def _extraction(rows: list[ConsultantOrderRow]) -> OrderExtraction:
    ex = OrderExtraction(
        title="SAP 4500000777",
        start_date="2031-04-01",
        end_date="2031-06-30",
        consultant_rows=rows,
        source="claude",
        uncertain=False,
    )
    ex.confidence["title"] = 1.0
    return ex


_ROSTER = [
    RosterPerson(
        5,
        "Marian",
        "Odchodzący",
        (RosterContract(9, "ended", date(2030, 1, 1), _ENDED_ON),),
    ),
    RosterPerson(6, "Ewa", "Obecna", (RosterContract(10, "active", None, None),)),
]
_COMPLETED = {
    9: [ExistingOrder(301, "completed", "SAP 4500000100", date(2030, 1, 1), _ENDED_ON)]
}


def _plan(order_type: str, client_id: int):
    rows = [_row("Marian Odchodzący"), _row("Nikt Nieznany"), _row("Ewa Obecna")]
    ex = _extraction(rows)
    resolved = resolve_rows(rows, _ROSTER)
    return (
        ex,
        resolved,
        plan_document(
            client_id=client_id,
            extraction=ex,
            resolved=resolved,
            existing_orders_by_contract=_COMPLETED,
            is_group_client=True,
            today=date(2031, 3, 3),
            order_type=order_type,
        ),
    )


@pytest.mark.parametrize(
    "order_type,client_id",
    [("cost", 15), ("md", 18), ("md", 4242), ("cost", 4343)],
    ids=["kosztowe-polkomtel", "md-bik", "md-dowolny-klient", "kosztowe-dowolny"],
)
def test_mail_stops_inactive_and_unknown_people_on_md_and_cost(order_type, client_id):
    ex, resolved, proposal = _plan(order_type, client_id)
    ended, unknown, active = proposal.rows

    assert ended.action == ACTION_DECIDE_PERSON
    assert ended.reasons == [
        inactive_consultant_reason("Marian Odchodzący", ended_on=_ENDED_ON)
    ]
    assert unknown.action == ACTION_DECIDE_PERSON
    assert unknown.reasons == [unknown_consultant_reason("Nikt Nieznany")]
    assert active.action not in (ACTION_DECIDE_PERSON,)
    assert proposal.auto_eligible_actions is False

    verdict = evaluate(
        GateInput(
            identification_method="registry_id",
            policies_applied=("Reguły klienta",),
            extraction=ex,
            document_truncated=False,
            ocr_capped=False,
            resolved=tuple(resolved),
            proposal=proposal,
            deterministic_rows=tuple(ex.consultant_rows),
            current_rates={},
            autoapply_enabled=True,
        )
    )
    assert verdict.verdict == VERDICT_REVIEW
    assert any("nie ma już aktywnej współpracy" in r for r in verdict.reasons)
    assert any("Nie znaleziono „Nikt Nieznany”" in r for r in verdict.reasons)


def test_periodic_orders_keep_the_return_after_break_decision():
    """Decyzja z 10.09.2026 zostaje: zamówienie okresowe to powrót / nowy szkic."""

    _, _, proposal = _plan("periodic", 12)
    ended, unknown, _ = proposal.rows
    assert ended.action == ACTION_REACTIVATE
    assert unknown.action == ACTION_NEW_DRAFT


# ── Baza: klient z trzema osobami ───────────────────────────────────────────


async def _seed() -> dict:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus, RateUnit

    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Nieaktywni-{suffix}")
        db.add(client)
        await db.flush()
        ids: dict = {"client_id": client.id, "suffix": suffix}
        people = (
            ("leaving", "Anna", f"Odchodząca{suffix}", ContractStatus.active, None),
            (
                "ended",
                "Marian",
                f"Odszedł{suffix}",
                ContractStatus.ended,
                _TODAY - timedelta(days=20),
            ),
            ("substitute", "Tadeusz", f"Zastępca{suffix}", ContractStatus.active, None),
        )
        for key, name, lastname, status, end in people:
            candidate = Candidate(
                name=name, lastname=lastname, email=f"nieakt-{key}-{suffix}@example.com"
            )
            db.add(candidate)
            await db.flush()
            contract = Contract(
                candidate_id=candidate.id,
                client_id=client.id,
                status=status,
                start_date=_TODAY - timedelta(days=300),
                end_date=end,
                rate_candidate=Decimal("700.000"),
                rate_unit=RateUnit.daily,
            )
            db.add(contract)
            await db.flush()
            ids[f"{key}_contract"] = contract.id
            ids[f"{key}_name"] = f"{name} {lastname}"
            ids[f"{key}_end"] = end
        await db.commit()
        return ids


def _line(contract_id: int, order_type: str, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "rate_cost": 700,
        "rate_revenue": 1000,
        "start_date": (_TODAY - timedelta(days=100)).isoformat(),
    }
    if order_type == "md":
        payload.update({"input_mode": "md", "input_value": 50})
    payload.update(overrides)
    return payload


async def _create_group(
    app_client: AsyncClient, headers: dict, client_id: int, order_type: str, lines
) -> dict:
    body = {
        "order_number": f"ZAM-{uuid.uuid4().hex[:8]}",
        "start_date": (_TODAY - timedelta(days=100)).isoformat(),
        "order_type": order_type,
        "lines": lines,
    }
    if order_type == "cost":
        body.update({"is_cost_based": True, "budget_amount": 100000})
    else:
        body.update({"md_budget_mode": "per_person", "status": "active"})
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups", json=body, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _group(app_client: AsyncClient, headers: dict, client_id: int, gid: int):
    listing = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=headers
    )
    assert listing.status_code == 200, listing.text
    return next(g for g in listing.json()["groups"] if g["id"] == gid)


async def _consume(order_type: str, group_id: int, line_id: int) -> None:
    """Zużycie osoby: faktura (kosztowe) albo zaraportowane MD (MD per osoba)."""

    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.models.client_order_group import ClientOrderGroup
    from app.models.md_consumption import (
        ClientOrderInvoiceConsumption,
        ClientOrderMdConsumption,
    )
    from app.services.client_order_lines import recompute_remaining
    from app.services.cost_orders import settle_group

    async with AsyncSessionLocal() as db:
        if order_type == "cost":
            db.add(
                ClientOrderInvoiceConsumption(
                    order_id=line_id,
                    period_month="2031-01",
                    invoice_amount=Decimal("12000"),
                    source="manual",
                )
            )
            await db.flush()
            await settle_group(db, await db.get(ClientOrderGroup, group_id))
        else:
            db.add(
                ClientOrderMdConsumption(
                    order_id=line_id,
                    period_month="2031-01",
                    md_reported=Decimal("12"),
                    source="manual",
                )
            )
            await db.flush()
            await recompute_remaining(db, await db.get(ClientOrder, line_id))
        await db.commit()


@pytest.mark.parametrize("order_type", ["cost", "md"], ids=["kosztowe", "md-per-osoba"])
async def test_used_budget_stays_on_the_order_after_removal_and_replacement(
    app_client: AsyncClient, app_auth_headers: dict, order_type: str
):
    ids = await _seed()
    group = await _create_group(
        app_client,
        app_auth_headers,
        ids["client_id"],
        order_type,
        [_line(ids["leaving_contract"], order_type)],
    )
    leaving = group["lines"][0]["id"]
    await _consume(order_type, group["id"], leaving)
    before = await _group(app_client, app_auth_headers, ids["client_id"], group["id"])

    # Zastępstwo za tę osobę NIE przejmuje jej zużycia.
    base = f"/api/clients/{ids['client_id']}/order-groups/{group['id']}/lines"
    added = await app_client.post(
        base,
        json=_line(ids["substitute_contract"], order_type, replaces_order_id=leaving),
        headers=app_auth_headers,
    )
    assert added.status_code == 201, added.text

    # Usunięcie kasuje linię trwale (09.2026), więc osoba z zużyciem jest
    # odrzucana (409) — jej zużycie nie może zniknąć razem z nią.
    removed = await app_client.delete(f"{base}/{leaving}", headers=app_auth_headers)
    assert removed.status_code == 409, removed.text

    after = await _group(app_client, app_auth_headers, ids["client_id"], group["id"])
    line = next(item for item in after["lines"] if item["id"] == leaving)
    assert line["removed_from_order"] is False
    if order_type == "cost":
        assert line["invoiced_total"] == pytest.approx(12000.0)
        assert after["budget_used"] == pytest.approx(before["budget_used"])
        assert after["budget_remaining"] == pytest.approx(before["budget_remaining"]), (
            "wykorzystana kwota wróciła do puli"
        )
    else:
        assert line["md_used"] == pytest.approx(12.0)
        assert line["md_remaining"] == pytest.approx(38.0)
        substitute = next(
            item
            for item in after["lines"]
            if item["contract_id"] == ids["substitute_contract"]
        )
        # Zastępca ma własny budżet — MD zużyte przez poprzednika nie przeszły na niego.
        assert substitute["md_total"] == pytest.approx(50.0)
        assert substitute["md_remaining"] == pytest.approx(50.0)
        assert substitute["replaces_name"] == ids["leaving_name"]


# ── „Uzupełnij zamówienie": osoby z dokumentu jednym zapisem ────────────────


@pytest.mark.parametrize("order_type", ["cost", "md"])
async def test_batch_adds_historical_and_substitute_together(
    app_client: AsyncClient, app_auth_headers: dict, order_type: str
):
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract

    ids = await _seed()
    group = await _create_group(
        app_client,
        app_auth_headers,
        ids["client_id"],
        order_type,
        [_line(ids["leaving_contract"], order_type)],
    )
    url = f"/api/clients/{ids['client_id']}/order-groups/{group['id']}/lines/batch"
    historical = _line(
        ids["ended_contract"],
        order_type,
        historical=True,
        end_date=ids["ended_end"].isoformat(),
        document_name=ids["ended_name"],
    )
    substitute = _line(
        ids["substitute_contract"], order_type, replaces_name=ids["ended_name"]
    )
    resp = await app_client.post(
        url, json={"lines": [historical, substitute]}, headers=app_auth_headers
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    by_contract = {line["contract_id"]: line for line in body["lines"]}
    kept = by_contract[ids["ended_contract"]]
    assert kept["status"] == "completed" and kept["is_active"] is False
    assert kept["origin"] == "document"
    assert by_contract[ids["substitute_contract"]]["replaces_name"] == ids["ended_name"]
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, ids["ended_contract"])
        assert contract.status.value == "ended", "zapis historyczny wznowił kontrakt"


async def test_batch_is_all_or_nothing(app_client: AsyncClient, app_auth_headers: dict):
    ids = await _seed()
    group = await _create_group(
        app_client,
        app_auth_headers,
        ids["client_id"],
        "cost",
        [_line(ids["leaving_contract"], "cost")],
    )
    url = f"/api/clients/{ids['client_id']}/order-groups/{group['id']}/lines/batch"
    fine = _line(
        ids["ended_contract"],
        "cost",
        historical=True,
        end_date=ids["ended_end"].isoformat(),
    )
    # Zapis historyczny osoby, która PRACUJE — odmowa całego zapisu.
    wrong = _line(
        ids["substitute_contract"],
        "cost",
        historical=True,
        end_date=(_TODAY - timedelta(days=1)).isoformat(),
    )
    resp = await app_client.post(
        url, json={"lines": [fine, wrong]}, headers=app_auth_headers
    )
    assert resp.status_code == 422, resp.text
    after = await _group(app_client, app_auth_headers, ids["client_id"], group["id"])
    assert [line["contract_id"] for line in after["lines"]] == [
        ids["leaving_contract"]
    ], "pierwsza osoba z odrzuconego zapisu została na zamówieniu"


# ── Kolejka maila → okno zamówienia → dokument schodzi z kolejki ───────────


async def _mail_doc(client_id: int, number: str, tmp_path, monkeypatch) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.order_mail import OUTCOME_NEEDS_REVIEW, OrderMailDocument
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(storage_service, "ORDER_MAIL_DIR", tmp_path / "order_mail")
    tag = uuid.uuid4().hex
    rel, _ = storage_service.save_order_mail_attachment(
        tag[:64].ljust(64, "0"), "zlecenie.pdf", io.BytesIO(b"%PDF-1.4 " + tag.encode())
    )
    async with AsyncSessionLocal() as db:
        doc = OrderMailDocument(
            internet_message_id=f"<nieakt-{tag}@example>",
            received_at=datetime.now(timezone.utc),
            sender_email="zlecenia@klient.example",
            subject="Zlecenie",
            attachment_name="zlecenie.pdf",
            attachment_sha256=tag[:64].ljust(64, "0"),
            storage_path=rel,
            outcome=OUTCOME_NEEDS_REVIEW,
            client_id=client_id,
            identification_method="registry_id",
            extraction={"title": number, "consultant_rows": []},
            gate_verdict="review",
            gate_reasons=["test"],
            proposal={
                "client_id": client_id,
                "order_number": number,
                "is_group_client": True,
                "blocking": [],
                "rows": [
                    {
                        "row_index": 0,
                        "row_name": "Marian Odchodzący",
                        "action": ACTION_DECIDE_PERSON,
                        "order_type": "cost",
                        "reasons": [
                            inactive_consultant_reason(
                                "Marian Odchodzący", ended_on=_ENDED_ON
                            )
                        ],
                    }
                ],
            },
        )
        db.add(doc)
        await db.commit()
        return doc.id


async def test_mail_document_leads_to_the_order_window_and_leaves_the_queue(
    app_client: AsyncClient, app_auth_headers: dict, tmp_path, monkeypatch
):
    ids = await _seed()
    group = await _create_group(
        app_client,
        app_auth_headers,
        ids["client_id"],
        "cost",
        [_line(ids["leaving_contract"], "cost")],
    )
    doc_id = await _mail_doc(
        ids["client_id"], group["order_number"], tmp_path, monkeypatch
    )

    target = await app_client.get(
        f"/api/order-mail/queue/{doc_id}/order-target", headers=app_auth_headers
    )
    assert target.status_code == 200, target.text
    assert target.json() == {
        "client_id": ids["client_id"],
        "order_group_id": group["id"],
        "order_type": "cost",
        "order_number": group["order_number"],
        "attachment_name": "zlecenie.pdf",
    }

    # Zamówienie innego klienta nie zamyka dokumentu.
    other = await _seed()
    foreign = await _create_group(
        app_client,
        app_auth_headers,
        other["client_id"],
        "cost",
        [_line(other["leaving_contract"], "cost")],
    )
    refused = await app_client.post(
        f"/api/order-mail/queue/{doc_id}/resolved-in-order",
        json={"order_group_id": foreign["id"]},
        headers=app_auth_headers,
    )
    assert refused.status_code == 422, refused.text

    done = await app_client.post(
        f"/api/order-mail/queue/{doc_id}/resolved-in-order",
        json={"order_group_id": group["id"]},
        headers=app_auth_headers,
    )
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["outcome"] == "applied"
    assert body["applied_order_id"] is None
    assert body["proposal"]["resolved_in_order"]["order_group_id"] == group["id"]

    again = await app_client.post(
        f"/api/order-mail/queue/{doc_id}/resolved-in-order",
        json={"order_group_id": group["id"]},
        headers=app_auth_headers,
    )
    assert again.status_code == 409


async def test_mail_document_without_an_open_order_opens_a_new_one(
    app_client: AsyncClient, app_auth_headers: dict, tmp_path, monkeypatch
):
    ids = await _seed()
    doc_id = await _mail_doc(ids["client_id"], "SAP 4599999999", tmp_path, monkeypatch)
    target = await app_client.get(
        f"/api/order-mail/queue/{doc_id}/order-target", headers=app_auth_headers
    )
    assert target.status_code == 200, target.text
    assert target.json()["order_group_id"] is None


# ── Wybór zakończonego kontraktu z listy w oknie ────────────────────────────


def test_ended_option_carries_the_same_inactive_sentence():
    from app.api.client_order_groups import _plan_contract_read
    from app.services.order_group_extraction import PlanContractOption

    option = PlanContractOption(
        contract_id=9,
        candidate_id=5,
        contractor_name="Marian Odchodzący",
        status="ended",
        start_date=date(2030, 1, 1),
        end_date=_ENDED_ON,
        rate_cost=None,
    )
    read = _plan_contract_read(option, with_finance=False)
    assert read.inactive_reason == inactive_consultant_reason(
        "Marian Odchodzący", ended_on=_ENDED_ON
    )
    live = _plan_contract_read(
        PlanContractOption(
            contract_id=10,
            candidate_id=6,
            contractor_name="Ewa Obecna",
            status="active",
            start_date=None,
            end_date=None,
            rate_cost=None,
        ),
        with_finance=False,
    )
    assert live.inactive_reason is None


async def test_batch_refuses_a_person_already_working_on_the_order(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Karta bez dopasowania (np. BNP, literówka) pozwala wskazać osobę ręcznie —
    także taką, która już pracuje na tym zamówieniu. Druga linia = drugi budżet."""

    ids = await _seed()
    group = await _create_group(
        app_client,
        app_auth_headers,
        ids["client_id"],
        "md",
        [_line(ids["leaving_contract"], "md")],
    )
    url = f"/api/clients/{ids['client_id']}/order-groups/{group['id']}/lines/batch"
    again = await app_client.post(
        url,
        json={"lines": [_line(ids["leaving_contract"], "md")]},
        headers=app_auth_headers,
    )
    assert again.status_code == 409, again.text
    assert "jest już na zamówieniu" in again.json()["detail"]

    twice = await app_client.post(
        url,
        json={
            "lines": [
                _line(ids["substitute_contract"], "md"),
                _line(ids["substitute_contract"], "md"),
            ]
        },
        headers=app_auth_headers,
    )
    assert twice.status_code == 409, twice.text
    after = await _group(app_client, app_auth_headers, ids["client_id"], group["id"])
    assert [line["contract_id"] for line in after["lines"]] == [ids["leaving_contract"]]
