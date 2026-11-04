"""Audyt 25.09.2026, runda 4 — kontrakty, Generator B2B, zamówienia MD.

R4-13 korekta daty umowy rozwiązanej dokumentem, R4-17 znacznik rozwiązania
po wyczyszczeniu daty, R4-21 „Cofnij zakończenie” po „Powrocie po przerwie”,
R4-22 i R4-23 zaplanowane „Wejdź za konsultanta”, R4-24 „inny numer
zamówienia” w oknie zużycia MD. Testy z bazą seedują WŁASNE wiersze (baza
wspólna, nieczyszczona) i asertują wyłącznie na nich.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core.scheduling import business_today
from app.services import finance_order_matching
from app.services.finance_order_matching import build_order_number_index
from app.services.md_consumption_view import (
    ConsumptionIn,
    ImportRefIn,
    binds_as_order_number,
    build_consumption_view,
    is_foreign_number,
)

D = Decimal

# ── R4-24: „inny numer zamówienia” tylko dla numeru zamówienia ──────────────

SAP_CLIENT = 9401
SAP_NUMBERS = build_order_number_index(
    [(SAP_CLIENT, "4500030197"), (SAP_CLIENT, "4500030845")]
)
SAP = {"client_id": SAP_CLIENT, "order_numbers": SAP_NUMBERS}

BNP_CLIENT = 9402
BNP_NUMBERS = build_order_number_index([(BNP_CLIENT, "87_2026")])
BNP = {"client_id": BNP_CLIENT, "order_numbers": BNP_NUMBERS}


def test_other_numbers_from_notes_are_not_order_numbers():
    """„delegacja 445” i „08/2026” w „Uwagach” — import ich nie wiąże, więc
    okno zużycia nie może ich nazwać „innym numerem zamówienia”."""
    assert not is_foreign_number("445", "4500030197", **SAP)
    assert not is_foreign_number("2026", "4500030197", **SAP)
    assert not is_foreign_number("2026", "87_2026", **BNP)
    assert not binds_as_order_number("445", **SAP)


def test_real_other_order_number_still_warns():
    # Znany numer innego zamówienia tego klienta.
    assert is_foreign_number("4500030845", "4500030197", **SAP)
    # Nieznany, ale długi numer u klienta z numerami SAP (literówka albo
    # zamówienie spoza NEXUSA) — reguła wiązania go uznaje.
    assert is_foreign_number("4500099999", "4500030197", **SAP)
    # Ten sam numer (także bez zer wiodących) — nigdy obcy.
    assert not is_foreign_number("4500030197", "4500030197", **SAP)


def test_long_number_does_not_bind_for_client_with_other_number_shapes():
    assert not is_foreign_number("4500099999", "87_2026", **BNP)


def test_polkomtel_keeps_the_broader_sap_rule(monkeypatch):
    monkeypatch.setattr(finance_order_matching, "POLKOMTEL_CLIENT_ID", 9403)
    index = build_order_number_index([(9403, "SAP 4500012345")])
    assert is_foreign_number(
        "445", "SAP 4500012345", client_id=9403, order_numbers=index
    )


def test_consumption_view_does_not_flag_note_numbers():
    view = build_consumption_view(
        [ConsumptionIn("2026-08", D("21"), "import")],
        remaining=D("10"),
        import_refs={
            "2026-08": [
                ImportRefIn(7, 3, "445", D("20")),
                ImportRefIn(7, 4, "4500030845", D("1")),
            ]
        },
        corrections=[],
        order_number="4500030197",
        **SAP,
    )
    refs = view.months["2026-08"].import_rows
    assert [(r.order_number_hint, r.foreign) for r in refs] == [
        ("445", False),
        ("4500030845", True),
    ]
    assert [ref.order_number_hint for _month, ref in view.foreign] == ["4500030845"]


# ── ścieżki z bazą ───────────────────────────────────────────────────────────

CONTRACTS = "/api/contracts"
GENERATOR = "/api/b2b-generator"


@pytest.fixture
def fake_render(monkeypatch):
    from app.api import b2b_documents

    monkeypatch.setattr(
        b2b_documents, "render_docx", lambda key, ctx: b"PK-" + key.encode()
    )
    monkeypatch.setattr(b2b_documents, "render_html", lambda key, ctx: f"<p>{key}</p>")


async def _contract(contract_id: int):
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract

    async with AsyncSessionLocal() as db:
        return await db.get(Contract, contract_id)


# ── R4-13: korekta daty umowy rozwiązanej dokumentem z Generatora ────────────


async def test_later_end_date_keeps_a_dissolution_signed_in_the_generator(
    app_client, app_auth_headers, fake_render
):
    """Porozumienie o rozwiązaniu (dokument pochodny) nie zapisuje trybu na
    kontrakcie — żyje wyłącznie na wierszu rejestru. Nowa, późniejsza data
    końca to korekta daty: umowa w rejestrze zostaje „Zakończona” z trybem,
    a kontrakt do tej daty jest „Kończący się”."""
    from tests.test_audit_r3_contracts import (
        _create_termination,
        _generated,
        _signed_parent,
    )

    rid, contract_id = await _signed_parent(app_client)
    when = business_today() - timedelta(days=2)
    doc_id = await _create_termination(
        app_client, app_auth_headers, rid, termination=when
    )
    signed = await app_client.post(
        f"{GENERATOR}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    contract = await _contract(contract_id)
    assert contract.status.value == "ended"
    assert contract.agreement_termination_mode is None
    assert (await _generated(rid)).contract_status == "closed"

    later = business_today() + timedelta(days=20)
    resp = await app_client.patch(
        f"{CONTRACTS}/{contract_id}",
        json={"end_date": later.isoformat()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ending"
    row = await _generated(rid)
    assert row.contract_status == "closed"
    assert row.termination_mode == "mutual_agreement"
    assert (row.termination_restore or {}).get("contract_id") == contract_id


async def test_later_end_date_keeps_a_registered_partner_notice(
    app_client, app_auth_headers, fake_render
):
    from tests.test_audit_r3_contracts import _generated, _signed_parent

    rid, contract_id = await _signed_parent(app_client)
    delivered = business_today() - timedelta(days=40)
    notice = await app_client.post(
        f"{GENERATOR}/documents/partner-notice",
        headers=app_auth_headers,
        json={
            "parent_generated_contract_id": rid,
            "delivered_on": delivered.isoformat(),
            "termination_date": (business_today() - timedelta(days=3)).isoformat(),
        },
    )
    assert notice.status_code == 200, notice.text
    assert (await _generated(rid)).contract_status == "closed"

    later = business_today() + timedelta(days=15)
    resp = await app_client.patch(
        f"{CONTRACTS}/{contract_id}",
        json={"end_date": later.isoformat()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ending"
    row = await _generated(rid)
    assert row.contract_status == "closed"
    assert (row.termination_mode, row.termination_party) == ("notice", "consultant")


# ── R4-17: wyczyszczona data zdejmuje czekające rozwiązanie ─────────────────


async def test_clearing_end_date_drops_the_pending_dissolution_marker(
    app_client, app_auth_headers, fake_render
):
    """„Kończący się” → „Aktywny” przez wyczyszczenie daty odwołuje
    zakończenie: znacznik porozumienia na wierszu rejestru znika, więc
    późniejsze zwykłe zakończenie projektu zawiesza umowę („Bez projektu”),
    a nie zamyka jej jako rozwiązanej starym trybem."""
    from tests.test_audit_r3_contracts import (
        _create_termination,
        _generated,
        _signed_parent,
    )

    rid, contract_id = await _signed_parent(app_client)
    when = business_today() + timedelta(days=20)
    doc_id = await _create_termination(
        app_client, app_auth_headers, rid, termination=when
    )
    signed = await app_client.post(
        f"{GENERATOR}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    assert (await _contract(contract_id)).status.value == "ending"
    assert (await _generated(rid)).termination_mode == "mutual_agreement"

    cleared = await app_client.patch(
        f"{CONTRACTS}/{contract_id}", json={"end_date": None}, headers=app_auth_headers
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["status"] == "active"
    row = await _generated(rid)
    assert row.contract_status == "active"
    assert row.termination_mode is None

    project_end = business_today() - timedelta(days=1)
    ended = await app_client.post(
        f"{CONTRACTS}/{contract_id}/terminate",
        json={
            "termination_reason": "client_budget_cut",
            "terminated_at": project_end.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert ended.status_code == 200, ended.text
    row = await _generated(rid)
    assert row.contract_status == "suspended"
    assert row.termination_mode is None


# ── R4-21: „Cofnij zakończenie” po „Powrocie po przerwie” ────────────────────


async def test_reversal_is_blocked_after_return_after_break(
    app_client, app_auth_headers, monkeypatch
):
    from tests.test_contract_termination_reversal import (
        _enable_multi,
        _seed_active_md_consultant,
        _terminate,
    )

    seed = await _seed_active_md_consultant()
    _enable_multi(monkeypatch, seed["client_id"])
    await _terminate(app_client, app_auth_headers, seed["contract_id"])
    returned = await app_client.post(
        f"{CONTRACTS}/{seed['contract_id']}/return-after-break",
        json={"start_date": (business_today() + timedelta(days=10)).isoformat()},
        headers=app_auth_headers,
    )
    assert returned.status_code == 201, returned.text
    new_id = returned.json()["contract_id"]

    preview = await app_client.get(
        f"{CONTRACTS}/{seed['contract_id']}/termination-reversal",
        headers=app_auth_headers,
    )
    assert preview.status_code == 200, preview.text
    blockers = {b["code"]: b for b in preview.json()["blockers"]}
    assert blockers["returned_after_break"]["contract_id"] == new_id
    assert f"#{new_id}" in blockers["returned_after_break"]["message"]

    refused = await app_client.post(
        f"{CONTRACTS}/{seed['contract_id']}/termination-reversal",
        headers=app_auth_headers,
    )
    assert refused.status_code == 409, refused.text
    assert (await _contract(seed["contract_id"])).status.value == "ended"


# ── R4-22 / R4-23: zaplanowane „Wejdź za konsultanta” ────────────────────────


async def _scheduled(app_client, headers, monkeypatch) -> tuple[dict, dict]:
    from tests.test_order_line_takeover import (
        _enable_multi,
        _schedule_takeover,
        _seed,
    )

    seed = await _seed(source_state="leaving")
    _enable_multi(monkeypatch, seed["client_id"])
    planned = await _schedule_takeover(app_client, headers, seed)
    return seed, planned


async def _line(line_id: int):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder

    async with AsyncSessionLocal() as db:
        return await db.get(ClientOrder, line_id)


async def _cancel_events(group_id: int, order_id: int) -> list:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.client_order_group import ClientOrderGroupEvent

    async with AsyncSessionLocal() as db:
        events = (
            await db.scalars(
                select(ClientOrderGroupEvent)
                .where(
                    ClientOrderGroupEvent.group_id == group_id,
                    ClientOrderGroupEvent.order_id == order_id,
                )
                .order_by(ClientOrderGroupEvent.id)
            )
        ).all()
    return [e for e in events if (e.payload or {}).get("scheduled_cancelled")]


async def test_extension_amendment_cancels_a_scheduled_takeover(
    app_client, app_auth_headers, monkeypatch
):
    seed, planned = await _scheduled(app_client, app_auth_headers, monkeypatch)
    resp = await app_client.post(
        f"{CONTRACTS}/{seed['konrad_contract_id']}/amendments",
        json={
            "amendment_type": "extension",
            "effective_date": business_today().isoformat(),
            "new_end_date": (seed["departure"] + timedelta(days=90)).isoformat(),
            "reason": "Przedłużenie projektu",
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert (await _line(planned["id"])).status.value == "cancelled"
    (event,) = await _cancel_events(seed["group_id"], planned["id"])
    assert event.payload["cancel_reason"] == "source_extended"
    assert "przedłużono" in event.description


async def test_bulk_extend_cancels_a_scheduled_takeover(
    app_client, app_auth_headers, monkeypatch
):
    seed, planned = await _scheduled(app_client, app_auth_headers, monkeypatch)
    resp = await app_client.post(
        f"{CONTRACTS}/bulk-extend?ids={seed['konrad_contract_id']}&months=2",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert (await _line(planned["id"])).status.value == "cancelled"
    (event,) = await _cancel_events(seed["group_id"], planned["id"])
    assert event.payload["cancel_reason"] == "source_extended"


async def test_undone_termination_cancels_a_scheduled_takeover(
    app_client, app_auth_headers, monkeypatch
):
    """Odwołanie zakończenia (tu: wyczyszczenie daty „Kończącej się” umowy —
    ta sama `undo_contract_termination`, którą woła „Cofnij zakończenie”)
    anuluje zaplanowane zastępstwo z wpisem w historii zamówienia."""
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract, ContractStatus

    seed, planned = await _scheduled(app_client, app_auth_headers, monkeypatch)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, seed["konrad_contract_id"])
        contract.status = ContractStatus.ending
        await db.commit()
    resp = await app_client.patch(
        f"{CONTRACTS}/{seed['konrad_contract_id']}",
        json={"end_date": None},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"
    assert (await _line(planned["id"])).status.value == "cancelled"
    (event,) = await _cancel_events(seed["group_id"], planned["id"])
    assert event.payload["cancel_reason"] == "source_termination_undone"
    assert "cofnięto" in event.description


async def test_scanner_does_not_treat_a_scheduled_takeover_as_a_successor(
    app_client, app_auth_headers, monkeypatch
):
    """Szkic zastępstwa nie domyka linii odchodzącego po dacie linii — inaczej
    nocne wejście przeniosłoby pulę osoby, która nadal pracuje."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.tasks.dl_portal_expiry_scanner import _promote_statuses

    seed, planned = await _scheduled(app_client, app_auth_headers, monkeypatch)
    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, seed["line_id"])
        line.end_date = business_today() - timedelta(days=1)
        await db.commit()
    async with AsyncSessionLocal() as db:
        await _promote_statuses(db)
        await db.commit()
    assert (await _line(seed["line_id"])).status.value == "active"
    assert (await _line(planned["id"])).status.value == "draft"


async def _source_done(seed: dict, *, used_up_case: bool) -> None:
    """Odchodzący zakończył współpracę, a jego pula spadła do zera."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.client_order_offboarding import (
        OFFBOARDING_RESOLUTION_REMOVE,
        OFFBOARDING_STATUS_RESOLVED,
        ClientOrderOffboardingCase,
    )
    from app.models.contract import Contract, ContractStatus
    from app.models.md_consumption import (
        CONSUMPTION_SOURCE_MANUAL,
        ClientOrderMdConsumption,
    )
    from app.services.client_order_lines import recompute_remaining

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, seed["konrad_contract_id"])
        contract.status = ContractStatus.ended
        line = await db.get(ClientOrder, seed["line_id"])
        line.status = ClientOrderStatus.completed
        db.add(
            ClientOrderMdConsumption(
                order_id=line.id,
                period_month=seed["departure"].strftime("%Y-%m"),
                md_reported=Decimal("187"),
                source=CONSUMPTION_SOURCE_MANUAL,
            )
        )
        await db.flush()
        await recompute_remaining(db, line, rebalance=False)
        if used_up_case:
            db.add(
                ClientOrderOffboardingCase(
                    contract_id=contract.id,
                    order_id=line.id,
                    order_group_id=seed["group_id"],
                    client_id=seed["client_id"],
                    effective_date=seed["departure"],
                    status=OFFBOARDING_STATUS_RESOLVED,
                    resolution=OFFBOARDING_RESOLUTION_REMOVE,
                    version=2,
                    uses_shared_md_pool=False,
                    remaining_md_snapshot=Decimal("0"),
                    order_number_snapshot="CeZ",
                    resolution_payload={"automatic": True},
                    resolved_at=datetime.now(timezone.utc),
                )
            )
        await db.commit()


@pytest.mark.parametrize("used_up_case", [False, True])
async def test_takeover_for_an_exhausted_pool_is_cancelled_not_retried(
    app_client, app_auth_headers, monkeypatch, used_up_case
):
    """R4-23: pula odchodzącego wyczerpała się przed dniem wejścia. Zastępstwo
    odpada z wpisem „pula wyczerpana” (nie wisi jako szkic odrzucany co noc),
    a sprawa zamknięta automatycznie nie jest opisywana jako decyzja ręczna."""
    from app.core.database import AsyncSessionLocal
    from app.services.order_line_takeover import activate_due_takeovers

    seed, planned = await _scheduled(app_client, app_auth_headers, monkeypatch)
    await _source_done(seed, used_up_case=used_up_case)
    entry = seed["departure"] + timedelta(days=1)
    async with AsyncSessionLocal() as db:
        activated = await activate_due_takeovers(db, today=entry)
        await db.commit()
    assert activated == 0
    assert (await _line(planned["id"])).status.value == "cancelled"
    (event,) = await _cancel_events(seed["group_id"], planned["id"])
    assert event.payload["cancel_reason"] == "source_pool_used_up"
    assert "wyczerpała" in event.description
    assert "ręcznie" not in event.description
