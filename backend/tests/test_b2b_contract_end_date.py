"""Umowa B2B bezterminowa, dopóki ktoś jej ręcznie nie zakończy (09.2026).

Trzy warstwy, każda z testem:

* reguła (``app.services.b2b_contract_end_date``) — czysta funkcja;
* API — tworzenie, edycja, aneks przedłużający i okno „Nowy kontraktor /
  zamówienie" nie dają umowie B2B daty końca bez zakończenia; umowy zlecenie
  bez zmian; „Zakończ współpracę" nadal ustawia datę (także przyszłą);
* jednorazowa korekta (``app.services.b2b_end_date_repair``) — WYKONYWANA na
  bazie testowej: literówka w kolumnie wyszłaby dopiero na produkcji,
  a entrypoint połknąłby ją (``|| echo skipped``).

Osoby i ID w testach są zmyślone (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import (
    Contract,
    ContractStatus,
    ContractTerminationReason,
    ContractType,
    ContractWorkMode,
)
from app.models.contract_amendment import ContractAmendment, ContractAmendmentType
from app.services.b2b_contract_end_date import (
    B2B_END_DATE_REASON,
    end_date_allowed,
)
from app.services.b2b_end_date_repair import (
    DETAILS_KEY,
    NOTE_REASON,
    REPAIR_MARKER,
    TICKET_TERMINATIONS,
    TicketTermination,
    run_b2b_end_date_repair,
    target_status,
)

BACKEND = Path(__file__).resolve().parents[1]
TODAY = business_today()


# ── Reguła ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("contract_type", "status", "terminated", "allowed"),
    [
        (ContractType.b2b, ContractStatus.active, False, False),
        (ContractType.b2b, ContractStatus.ending, False, False),
        (ContractType.b2b, ContractStatus.draft, False, False),
        (ContractType.b2b, ContractStatus.active, True, True),
        (ContractType.b2b, ContractStatus.ending, True, True),
        (ContractType.b2b, ContractStatus.ended, False, True),
        (ContractType.b2b, ContractStatus.void, False, True),
        (ContractType.uzlecenie, ContractStatus.active, False, True),
        (ContractType.uop, ContractStatus.ending, False, True),
    ],
)
def test_end_date_rule_matrix(contract_type, status, terminated, allowed):
    assert (
        end_date_allowed(
            contract_type=contract_type,
            status=status,
            end_date=TODAY + timedelta(days=30),
            manually_terminated=terminated,
        )
        is allowed
    )
    # Brak daty jest zawsze poprawny — umowa bezterminowa.
    assert end_date_allowed(
        contract_type=contract_type,
        status=status,
        end_date=None,
        manually_terminated=terminated,
    )


def test_target_status_mirrors_terminate_and_the_nightly_cron():
    assert target_status(TODAY, TODAY) == ContractStatus.ended
    assert target_status(TODAY - timedelta(days=5), TODAY) == ContractStatus.ended
    assert target_status(TODAY + timedelta(days=30), TODAY) == ContractStatus.ending
    assert target_status(TODAY + timedelta(days=31), TODAY) == ContractStatus.active


# ── Lista ze zgłoszenia ──────────────────────────────────────────────────────

# Kształt zgłoszenia 11.09.2026 (bez nazwisk): data zakończenia → wpis.
_TICKET_ROWS = sorted(
    [
        (date(2026, 10, 2), "Klient — No budget"),
        (date(2026, 9, 19), "Klient — Wydajność"),
        (date(2026, 8, 24), "Klient — Wydajność"),
        (date(2026, 9, 30), "Klient — No budget"),
        (date(2026, 10, 31), "Kandydat — Wyższa stawka"),
        (date(2026, 9, 30), "Kandydat — Wyższa stawka"),
        (date(2026, 12, 31), "Internalizacja"),
        (date(2026, 7, 31), "Klient — Wydajność"),
        (date(2026, 8, 31), "Klient — Wydajność"),
        (date(2026, 9, 11), "Klient — No budget"),
        (date(2026, 6, 30), "Kandydat"),
        (date(2026, 9, 30), "Kandydat — Przyczyny osobiste"),
        (date(2026, 8, 18), "Klient — Wydajność"),
        (date(2026, 9, 3), "Klient — Wydajność"),
        (date(2026, 10, 31), "Kandydat — No budget"),
        (date(2026, 8, 31), "Kandydat — Wyższa stawka"),
    ]
)


def test_ticket_lists_all_sixteen_people_with_ticket_dates_and_notes():
    """Blok jest jednorazowy: wdrożenie z niepełną listą zużyłoby marker."""
    assert len(TICKET_TERMINATIONS) == 16
    assert len({spec.contract_id for spec in TICKET_TERMINATIONS}) == 16
    assert len({spec.candidate_id for spec in TICKET_TERMINATIONS}) == 16
    assert (
        sorted((spec.end_date, spec.note) for spec in TICKET_TERMINATIONS)
        == _TICKET_ROWS
    )


def test_every_ticket_note_maps_to_a_termination_reason():
    for _, note in _TICKET_ROWS:
        assert note in NOTE_REASON
    # Kto zakończył decyduje o słowniku: inicjatywa konsultanta liczy się
    # w analityce jako rezygnacja, klienta — nie.
    assert NOTE_REASON["Kandydat"] == ContractTerminationReason.consultant_resigned
    assert NOTE_REASON["Klient — No budget"] == (
        ContractTerminationReason.client_budget_cut
    )
    assert NOTE_REASON["Internalizacja"] == ContractTerminationReason.poached_by_client


def test_receipt_key_is_a_public_receipt_and_details_key_is_not():
    from scripts.show_migration_receipts import is_receipt_key

    assert is_receipt_key(REPAIR_MARKER)
    # Treść „kto — powód" nie może trafić do publicznego logu Actions.
    assert not is_receipt_key(DETAILS_KEY)


def test_entrypoint_runs_the_repair_and_logs_only_numbers():
    source = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    block = source.split("run_b2b_end_date_repair", 1)[1].split("\nPY\n", 1)[0]
    assert "summarize_for_log(summary)" in block
    assert "await db.commit()" in block
    assert "await db.rollback()" in block


# ── Seed ─────────────────────────────────────────────────────────────────────


async def _seed_contract(
    *,
    contract_type: ContractType = ContractType.b2b,
    status: ContractStatus = ContractStatus.active,
    end_date: date | None = None,
    terminated_at: date | None = None,
    termination_reason: ContractTerminationReason | None = None,
) -> dict[str, int]:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Indefinite B2B {suffix}")
        candidate = Candidate(
            name="Testowa",
            lastname=f"Osoba{suffix}",
            email=f"b2b-{suffix}@example.test",
        )
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=contract_type,
            work_mode=ContractWorkMode.remote,
            status=status,
            start_date=TODAY - timedelta(days=200),
            end_date=end_date,
            terminated_at=terminated_at,
            termination_reason=termination_reason,
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("150.000"),
        )
        db.add(contract)
        await db.commit()
        return {
            "contract_id": contract.id,
            "candidate_id": candidate.id,
            "client_id": client.id,
        }


async def _contract(contract_id: int) -> Contract:
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract is not None
        return contract


# ── API ──────────────────────────────────────────────────────────────────────


async def test_patch_rejects_an_end_date_on_a_live_b2b_contract(
    app_client, app_auth_headers
):
    ids = await _seed_contract()
    resp = await app_client.patch(
        f"/api/contracts/{ids['contract_id']}",
        json={"end_date": (TODAY + timedelta(days=60)).isoformat()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["reason"] == B2B_END_DATE_REASON
    assert (await _contract(ids["contract_id"])).end_date is None


async def test_patch_of_another_field_does_not_trip_over_a_legacy_date(
    app_client, app_auth_headers
):
    """Formularz odsyła nieruszaną datę — zapis innego pola przechodzi."""
    legacy_end = TODAY + timedelta(days=60)
    ids = await _seed_contract(end_date=legacy_end)
    resp = await app_client.patch(
        f"/api/contracts/{ids['contract_id']}",
        json={"end_date": legacy_end.isoformat(), "project_name": "Nowy projekt"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    # Wyczyszczenie daty — zawsze dozwolone.
    resp = await app_client.patch(
        f"/api/contracts/{ids['contract_id']}",
        json={"end_date": None},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["end_date"] is None


async def test_umowa_zlecenie_keeps_its_end_date(app_client, app_auth_headers):
    ids = await _seed_contract(contract_type=ContractType.uzlecenie)
    target = TODAY + timedelta(days=60)
    resp = await app_client.patch(
        f"/api/contracts/{ids['contract_id']}",
        json={"end_date": target.isoformat()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["end_date"] == target.isoformat()


async def test_terminate_sets_a_future_date_and_it_can_be_corrected(
    app_client, app_auth_headers
):
    ids = await _seed_contract()
    first = TODAY + timedelta(days=40)
    resp = await app_client.post(
        f"/api/contracts/{ids['contract_id']}/terminate",
        json={
            "termination_reason": "client_budget_cut",
            "termination_lessons": "Klient — No budget",
            "terminated_at": first.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["end_date"] == first.isoformat()
    # Umowa wypowiedziana pracuje do daty zakończenia — od 0358 jako
    # „Kończący się” (data zakończenia projektu jest włączna).
    assert resp.json()["status"] == "ending"
    # Po ręcznym zakończeniu datę wolno poprawić w edycji.
    corrected = TODAY + timedelta(days=20)
    resp = await app_client.patch(
        f"/api/contracts/{ids['contract_id']}",
        json={"end_date": corrected.isoformat()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["end_date"] == corrected.isoformat()


async def test_create_gives_a_new_b2b_contract_no_end_date_unless_it_ended(
    app_client, app_auth_headers
):
    ids = await _seed_contract()
    base = {
        "candidate_id": ids["candidate_id"],
        "client_id": ids["client_id"],
        "start_date": (TODAY - timedelta(days=400)).isoformat(),
        "rate_candidate": 100,
        "rate_client": 150,
        "contract_type": "b2b",
    }
    # Kontrakt z seeda blokuje duplikat u tego klienta — nowy u innego.
    async with AsyncSessionLocal() as db:
        other = Client(name=f"Indefinite B2B other {uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        base["client_id"] = other.id
    resp = await app_client.post(
        "/api/contracts",
        json={**base, "end_date": (TODAY + timedelta(days=90)).isoformat()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["reason"] == B2B_END_DATE_REASON
    # Wpis historii: umowa już zakończona niesie swoją datę.
    ended_on = TODAY - timedelta(days=30)
    resp = await app_client.post(
        "/api/contracts",
        json={**base, "end_date": ended_on.isoformat(), "status": "ended"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "ended"
    assert resp.json()["end_date"] == ended_on.isoformat()


async def test_extension_amendment_is_refused_for_an_unterminated_b2b_contract(
    app_client, app_auth_headers
):
    ids = await _seed_contract()
    resp = await app_client.post(
        f"/api/contracts/{ids['contract_id']}/amendments",
        json={
            "amendment_type": "extension",
            "effective_date": TODAY.isoformat(),
            "new_end_date": (TODAY + timedelta(days=180)).isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert (await _contract(ids["contract_id"])).end_date is None


async def test_register_reopen_of_an_ended_b2b_contract_makes_it_indefinite(
    app_client, app_auth_headers
):
    """Ze starą datą nocny cron zakończyłby ją ponownie następnej nocy."""
    ids = await _seed_contract(
        status=ContractStatus.ended, end_date=TODAY - timedelta(days=10)
    )
    resp = await app_client.patch(
        f"/api/contracts/{ids['contract_id']}",
        json={"status": "active"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"
    assert resp.json()["end_date"] is None


async def test_new_contractor_order_window_refuses_a_contract_end_date(
    app_client, app_auth_headers
):
    ids = await _seed_contract()
    async with AsyncSessionLocal() as db:
        other = Client(name=f"Indefinite B2B flow {uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        client_id = other.id
    payload = {
        "candidate_id": ids["candidate_id"],
        "title": "Zamówienie testowe 1/2026",
        "contract_start_date": TODAY.isoformat(),
        "order_start_date": TODAY.isoformat(),
        "order_end_date": (TODAY + timedelta(days=90)).isoformat(),
        "rate_client": 18000,
        "rate_candidate": 14000,
        "rate_unit": "monthly",
    }
    resp = await app_client.post(
        f"/api/clients/{client_id}/contract-with-order",
        json={**payload, "contract_end_date": (TODAY + timedelta(days=90)).isoformat()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["reason"] == B2B_END_DATE_REASON

    resp = await app_client.post(
        f"/api/clients/{client_id}/contract-with-order",
        json=payload,
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    # Synchronizacja z zamówieniem niesie okres ZAMÓWIENIA, nigdy okresu umowy.
    contract = await _contract(resp.json()["contract_id"])
    assert contract.end_date is None


# ── Jednorazowa korekta ──────────────────────────────────────────────────────


async def _drop_markers() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(AppSetting).where(AppSetting.key.in_([REPAIR_MARKER, DETAILS_KEY]))
        )
        await db.commit()


async def test_repair_terminates_ticket_rows_then_clears_unterminated_b2b_dates():
    await _drop_markers()
    order_copied = TODAY + timedelta(days=45)
    # Klasa, którą czyści korekta.
    live = await _seed_contract(end_date=order_copied)
    ending = await _seed_contract(
        status=ContractStatus.ending, end_date=TODAY + timedelta(days=10)
    )
    # Bez zmian: zakończona, zlecenie, wypowiedziana, aneks early_termination,
    # szkic.
    ended = await _seed_contract(
        status=ContractStatus.ended, end_date=TODAY - timedelta(days=20)
    )
    zlecenie = await _seed_contract(
        contract_type=ContractType.uzlecenie, end_date=order_copied
    )
    terminated = await _seed_contract(
        end_date=order_copied,
        terminated_at=order_copied,
        termination_reason=ContractTerminationReason.project_ended,
    )
    amended = await _seed_contract(end_date=order_copied)
    draft = await _seed_contract(status=ContractStatus.draft, end_date=order_copied)
    async with AsyncSessionLocal() as db:
        db.add(
            ContractAmendment(
                contract_id=amended["contract_id"],
                amendment_type=ContractAmendmentType.early_termination,
                effective_date=order_copied,
            )
        )
        await db.commit()

    # Zakończenia ze zgłoszenia: przyszłe (z zamówieniem do skrócenia),
    # dzisiejsze, z przeszłości na kontrakcie zakończonym cronem po dacie
    # zamówienia oraz wpis, którego trójka ID się nie zgadza.
    future_person = await _seed_contract(end_date=TODAY + timedelta(days=100))
    today_person = await _seed_contract()
    past_person = await _seed_contract(
        status=ContractStatus.ended, end_date=TODAY - timedelta(days=2)
    )
    mismatch = await _seed_contract(end_date=order_copied)
    async with AsyncSessionLocal() as db:
        order = ClientOrder(
            client_id=future_person["client_id"],
            contract_id=future_person["contract_id"],
            title=f"Zamówienie {uuid.uuid4().hex[:6]}",
            status=ClientOrderStatus.active,
            start_date=TODAY - timedelta(days=30),
            end_date=TODAY + timedelta(days=120),
        )
        db.add(order)
        await db.commit()
        order_id = order.id

    future_end = TODAY + timedelta(days=21)
    past_end = TODAY - timedelta(days=12)
    specs = (
        TicketTermination(
            future_person["contract_id"],
            future_person["candidate_id"],
            future_person["client_id"],
            future_end,
            "Klient — Wydajność",
        ),
        TicketTermination(
            today_person["contract_id"],
            today_person["candidate_id"],
            today_person["client_id"],
            TODAY,
            "Klient — No budget",
        ),
        TicketTermination(
            past_person["contract_id"],
            past_person["candidate_id"],
            past_person["client_id"],
            past_end,
            "Kandydat",
        ),
        TicketTermination(
            mismatch["contract_id"],
            mismatch["candidate_id"] + 999_999,
            mismatch["client_id"],
            TODAY,
            "Internalizacja",
        ),
    )
    scope = {
        ids["contract_id"]
        for ids in (
            live,
            ending,
            ended,
            zlecenie,
            terminated,
            amended,
            draft,
            future_person,
            today_person,
            past_person,
            mismatch,
        )
    }
    try:
        async with AsyncSessionLocal() as db:
            summary = await run_b2b_end_date_repair(
                db, today=TODAY, terminations=specs, only_contract_ids=scope
            )
            await db.commit()
        assert summary is not None
        async with AsyncSessionLocal() as db:
            assert (
                await run_b2b_end_date_repair(
                    db, today=TODAY, terminations=specs, only_contract_ids=scope
                )
                is None
            ), "drugi start nie może niczego powtórzyć"

        # ── Zakończenia ze zgłoszenia ──
        assert summary["terminations_applied"] == 3
        assert summary["terminations_skipped"] == [
            {"contract_id": mismatch["contract_id"], "reason": "identity_mismatch"}
        ]
        future = await _contract(future_person["contract_id"])
        assert future.end_date == future_end
        assert future.terminated_at == future_end
        assert future.termination_reason == ContractTerminationReason.performance_issue
        assert future.termination_lessons == "Klient — Wydajność"
        # 21 dni → „Kończący się": pracuje do daty, nie znika z MRR przed czasem.
        assert future.status == ContractStatus.ending
        async with AsyncSessionLocal() as db:
            order = await db.get(ClientOrder, order_id)
            assert order.end_date == future_end
        today_contract = await _contract(today_person["contract_id"])
        assert today_contract.status == ContractStatus.ended
        assert today_contract.end_date == TODAY
        assert today_contract.termination_lessons == "Klient — No budget"
        past = await _contract(past_person["contract_id"])
        assert past.status == ContractStatus.ended
        assert past.end_date == past_end
        assert past.termination_reason == ContractTerminationReason.consultant_resigned
        assert (await _contract(mismatch["contract_id"])).terminated_at is None

        # ── Czyszczenie dat B2B ──
        cleared_ids = {item["contract_id"] for item in summary["cleared"]}
        assert live["contract_id"] in cleared_ids
        assert ending["contract_id"] in cleared_ids
        live_contract = await _contract(live["contract_id"])
        assert live_contract.end_date is None
        assert live_contract.status == ContractStatus.active
        ending_contract = await _contract(ending["contract_id"])
        assert ending_contract.end_date is None
        assert ending_contract.status == ContractStatus.active
        # Wpis ze zgłoszenia z niezgodną trójką ID to zwykła żywa umowa B2B.
        assert mismatch["contract_id"] in cleared_ids
        for untouched, expected_end in (
            (ended, TODAY - timedelta(days=20)),
            (zlecenie, order_copied),
            (terminated, order_copied),
            (amended, order_copied),
            (draft, order_copied),
        ):
            assert untouched["contract_id"] not in cleared_ids
            assert (await _contract(untouched["contract_id"])).end_date == expected_end
        assert future_person["contract_id"] not in cleared_ids

        async with AsyncSessionLocal() as db:
            receipt = (await db.get(AppSetting, REPAIR_MARKER)).value
            details = (await db.get(AppSetting, DETAILS_KEY)).value
            audit = (
                await db.scalars(
                    select(Activity).where(
                        Activity.entity_type == "contract",
                        Activity.entity_id == live["contract_id"],
                        Activity.action == "end_date_cleared",
                    )
                )
            ).all()
        # Paragon publiczny: liczby, ID, daty, kody — bez treści wpisów.
        assert "Klient" not in str(receipt)
        assert {item["note"] for item in details["terminated"]} == {
            "Klient — Wydajność",
            "Klient — No budget",
            "Kandydat",
        }
        # Stan zamówień sprzed korekty — do odwrócenia daty wstecznej.
        future_details = next(
            item
            for item in details["terminated"]
            if item["contract_id"] == future_person["contract_id"]
        )
        assert future_details["orders_before"] == [
            {
                "order_id": order_id,
                "status": "active",
                "start_date": (TODAY - timedelta(days=30)).isoformat(),
                "end_date": (TODAY + timedelta(days=120)).isoformat(),
                "order_group_id": None,
            }
        ]
        assert audit and audit[0].details["previous_end_date"] == (
            order_copied.isoformat()
        )
    finally:
        await _drop_markers()
