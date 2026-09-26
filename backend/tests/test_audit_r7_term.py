"""Runda 7 audytu (26.09.2026) — zakończenie współpracy i Generator B2B (TERM).

R7-V4-1  rozwiązanie umowy podpisane przy ZAPLANOWANYM końcu projektu
         („Kończący się”, projekt kończy się przed ostatnim dniem umowy) nie
         nadpisuje daty, powodu i wniosków zakończenia kontraktu; umowa
         w rejestrze kończy się ostatnim dniem z dokumentu,
R7-V4-2  aneks stawki sprzed startu działa od startu także wtedy, gdy
         harmonogram ma już krok od startu,
R7-V4-6  „Cofnij zakończenie” projektu nie wskrzesza umowy rozwiązanej
         podpisanym dokumentem,
R7-V4-7  „Oznacz jako podpisaną” blokuje kontrakty przed wierszem rejestru,
R7-X1-1  `termination_restore` zapisuje SQL NULL, a znacznik czekającego
         rozwiązania znika także na wierszach z JSON-owym `null`.

Baza wspólna i nieczyszczona — asercje wyłącznie na własnych wierszach.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select, text

from app.api.contracts import _amendment_step_from
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.contract import Contract, ContractStatus, ContractTerminationReason
from app.services.b2b_documents.effects import project_already_ended
from app.services.contract_termination_sync import (
    DOCUMENT_DISSOLUTION_KEY,
    _kept_snapshot,
)

START = date(2026, 10, 1)


def _contract(**fields) -> SimpleNamespace:
    base = {
        "status": ContractStatus.ending,
        "terminated_at": date(2026, 9, 30),
        "end_date": date(2026, 9, 30),
    }
    base.update(fields)
    return SimpleNamespace(**base)


# ── R7-V4-1: czyste reguły ───────────────────────────────────────────────────


def test_planned_project_end_before_the_agreement_counts_as_ended_before():
    assert project_already_ended(_contract(), date(2026, 10, 31)) is True


def test_agreement_ending_with_or_before_the_project_changes_the_contract():
    assert project_already_ended(_contract(), date(2026, 9, 30)) is False
    assert project_already_ended(_contract(), date(2026, 9, 15)) is False


def test_contract_without_a_termination_is_not_ended_before():
    """„Kończący się” sam z siebie (umowa zlecenie z datą końca) — dokument
    kończy kontrakt jak dotąd."""
    assert (
        project_already_ended(_contract(terminated_at=None), date(2026, 10, 31))
        is False
    )


def test_ended_contract_is_ended_before_regardless_of_the_date():
    ended = _contract(status=ContractStatus.ended)
    assert project_already_ended(ended) is True
    assert project_already_ended(ended, date(2026, 9, 1)) is True
    assert project_already_ended(None, date(2026, 9, 1)) is False


# ── R7-V4-2: krok aneksu sprzed startu ───────────────────────────────────────


def _step(on: date, rate: str) -> SimpleNamespace:
    return SimpleNamespace(effective_from=on, rate=Decimal(rate))


def test_amendment_before_start_lands_on_the_step_from_the_start():
    schedule = [_step(START, "150")]
    assert _amendment_step_from(schedule, START, START - timedelta(days=10)) == START
    schedule.append(_step(START, "165"))
    assert Contract._resolve_scheduled_rate(
        schedule, START + timedelta(days=5), None
    ) == Decimal("165")


def test_amendment_step_keeps_its_date_without_blocking_steps():
    effective = START - timedelta(days=10)
    assert _amendment_step_from([], START, effective) == effective
    assert (
        _amendment_step_from(
            [_step(START - timedelta(days=30), "140")], START, effective
        )
        == effective
    )
    # Po starcie umowy aneks ma swoją datę, a późniejsze kroki zostają nadrzędne.
    later = START + timedelta(days=10)
    assert _amendment_step_from([_step(START, "150")], START, later) == later
    assert _amendment_step_from([_step(START, "150")], None, effective) == effective


# ── R7-V4-6 / R7-X1-1: czyste reguły ─────────────────────────────────────────


def test_kept_snapshot_marks_the_document_dissolution():
    row = SimpleNamespace(
        contract_status="closed",
        closure_reason="project_completed",
        closure_reason_other=None,
        closure_date=date(2026, 10, 31),
        termination_mode="notice",
        termination_party="consultant",
        termination_signed_on=date(2026, 9, 20),
        project_end_date=date(2026, 9, 30),
    )
    snap = _kept_snapshot(row, SimpleNamespace(id=7))
    assert snap["contract_id"] == 7
    assert snap["contract_status"] == "closed"
    assert snap[DOCUMENT_DISSOLUTION_KEY] is True


def test_termination_restore_writes_sql_null():
    column_type = B2BGeneratedContract.__table__.c.termination_restore.type
    assert column_type.none_as_null is True
    assert column_type._variant_mapping["postgresql"].none_as_null is True


def test_clear_pending_markers_sees_json_null_rows():
    from app.services import contract_termination_sync

    source = inspect.getsource(contract_termination_sync._clear_pending_markers)
    assert "jsonb_typeof" in source


# ── R7-V4-7: kolejność blokad ────────────────────────────────────────────────


def test_confirm_fully_signed_locks_contracts_before_the_register_row():
    from app.api import b2b_contract_generator

    source = inspect.getsource(
        b2b_contract_generator.confirm_generated_contract_fully_signed
    )
    lock = source.find("lock_contract_then_orders(")
    row = source.find(".with_for_update()")
    assert 0 <= lock < row


# ── testy na bazie (CI) ──────────────────────────────────────────────────────


async def _ending_with_agreement(app_client) -> tuple[int, int, date]:
    """Umowa aktywna, projekt kończy się za 5 dni (zakończenie z okna)."""
    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from tests.test_b2b_documents_api import _signed_parent

    rid, contract_id = await _signed_parent(app_client)
    project_end = business_today() + timedelta(days=5)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        contract.status = ContractStatus.ending
        contract.end_date = project_end
        contract.terminated_at = project_end
        contract.termination_reason = ContractTerminationReason.client_budget_cut
        contract.termination_lessons = "Klient obciął budżet"
        await db.commit()
    return rid, contract_id, project_end


async def _assert_termination_kept(contract_id: int, project_end: date) -> None:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract.terminated_at == project_end
        assert contract.end_date == project_end
        assert (
            contract.termination_reason == ContractTerminationReason.client_budget_cut
        )
        assert contract.termination_lessons == "Klient obciął budżet"


async def _end_project_and_sync(contract_id: int) -> None:
    from app.core.database import AsyncSessionLocal
    from app.services.contract_termination_sync import (
        sync_generator_after_contract_ended,
    )

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        contract.status = ContractStatus.ended
        await db.flush()
        await sync_generator_after_contract_ended(db, contract, actor_id=None)
        await db.commit()


async def _undo(contract_id: int) -> None:
    from app.core.database import AsyncSessionLocal
    from app.services.contract_termination_sync import undo_contract_termination

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        await undo_contract_termination(db, contract, actor_id=None)
        await db.commit()


async def test_partner_notice_after_planned_project_end_keeps_the_contract(
    app_client, app_auth_headers
):
    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from tests.test_b2b_documents_api import BASE

    rid, contract_id, project_end = await _ending_with_agreement(app_client)
    last_day = business_today() + timedelta(days=36)
    resp = await app_client.post(
        f"{BASE}/documents/partner-notice",
        headers=app_auth_headers,
        json={
            "parent_generated_contract_id": rid,
            "delivered_on": business_today().isoformat(),
            "termination_date": last_day.isoformat(),
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["contract_already_ended"] is True
    await _assert_termination_kept(contract_id, project_end)
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, rid)
        assert row.contract_status == "active"
        assert row.termination_mode == "notice"

    await _end_project_and_sync(contract_id)
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, rid)
        assert row.contract_status == "closed"
        assert row.closure_date == last_day
        assert row.termination_restore[DOCUMENT_DISSOLUTION_KEY] is True

    # „Cofnij zakończenie” projektu nie wskrzesza rozwiązanej umowy.
    await _undo(contract_id)
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, rid)
        assert row.contract_status == "closed"
        assert row.termination_mode == "notice"
        assert row.termination_restore is None


async def test_agreement_after_planned_project_end_describes_and_keeps_the_contract(
    app_client, app_auth_headers
):
    from app.core.scheduling import business_today
    from tests.test_b2b_documents_api import _create, BASE
    from tests.test_b2b_documents_api import _fake_render  # noqa: F401

    rid, contract_id, project_end = await _ending_with_agreement(app_client)
    last_day = business_today() + timedelta(days=36)
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "termination_agreement",
        rid,
        termination_date=last_day.isoformat(),
        last_service_date=last_day.isoformat(),
    )
    effects = await app_client.get(
        f"{BASE}/documents/{doc_id}/effects", headers=app_auth_headers
    )
    assert effects.status_code == 200, effects.text
    changes = " ".join(effects.json()["changes"])
    assert "zaplanowany koniec projektu" in changes
    assert "kontrakt, zamówienia klienta" not in changes

    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    await _assert_termination_kept(contract_id, project_end)

    await _end_project_and_sync(contract_id)
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, rid)
        assert row.contract_status == "closed"
        assert row.closure_date == last_day
        assert row.termination_mode == "mutual_agreement"


async def test_undo_keeps_agreement_dissolved_after_suspension(
    app_client, app_auth_headers
):
    """Projekt się skończył (umowa „bez projektu”), potem podpisano
    porozumienie — „Cofnij zakończenie” nie wraca do stanu sprzed zawieszenia."""
    from app.core.database import AsyncSessionLocal
    from tests.test_b2b_documents_api import _create, BASE
    from tests.test_b2b_documents_api import _fake_render  # noqa: F401
    from tests.test_b2b_documents_round6 import _project_ended_earlier

    rid, contract_id = await _project_ended_earlier(app_client)
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "termination_agreement",
        rid,
        termination_date="2026-08-31",
        last_service_date="2026-08-31",
    )
    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text

    await _undo(contract_id)
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, rid)
        assert row.contract_status == "closed"
        assert row.termination_mode == "mutual_agreement"
        assert row.closure_date == date(2026, 8, 31)


async def test_undo_clears_pending_marker_on_row_with_json_null_restore(
    app_client,
):
    from app.core.database import AsyncSessionLocal
    from app.services.contract_termination_sync import mark_pending_dissolution
    from tests.test_b2b_documents_api import _signed_parent

    rid, contract_id = await _signed_parent(app_client)
    async with AsyncSessionLocal() as db:
        # Stan sprzed rundy 7: przypisanie None zapisywało JSON `null`.
        await db.execute(
            text(
                "UPDATE b2b_generated_contracts "
                "SET termination_restore = 'null'::jsonb WHERE id = :id"
            ),
            {"id": rid},
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, rid)
        assert mark_pending_dissolution(
            row, mode="mutual_agreement", party=None, signed_on=date(2026, 9, 20)
        )
        await db.commit()

    await _undo(contract_id)
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, rid)
        assert row.termination_mode is None


async def test_none_assignment_stores_sql_null(app_client):
    from app.core.database import AsyncSessionLocal
    from tests.test_b2b_documents_api import _signed_parent

    rid, _ = await _signed_parent(app_client)
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, rid)
        row.termination_restore = {"contract_id": 1}
        await db.commit()
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, rid)
        row.termination_restore = None
        await db.commit()
    async with AsyncSessionLocal() as db:
        is_null = await db.scalar(
            select(B2BGeneratedContract.termination_restore.is_(None)).where(
                B2BGeneratedContract.id == rid
            )
        )
        assert is_null is True


async def test_rate_amendment_before_start_beats_an_existing_start_step(
    app_client, app_auth_headers
):
    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.contract_candidate_rate import ContractCandidateRate
    from app.models.contract_client_rate import ContractClientRate
    from tests.test_audit_r6_contracts import _contract_with_schedules, _seed

    start = business_today() + timedelta(days=20)
    ids = await _seed(status=ContractStatus.draft, start_date=start)
    async with AsyncSessionLocal() as db:
        db.add(
            ContractCandidateRate(
                contract_id=ids["contract_id"],
                rate=Decimal("150"),
                effective_from=start,
                note=f"progresja {uuid.uuid4().hex[:4]}",
            )
        )
        db.add(
            ContractClientRate(
                contract_id=ids["contract_id"],
                rate=Decimal("200"),
                effective_from=start,
                note="od startu zamówienia",
            )
        )
        await db.commit()
    resp = await app_client.post(
        f"/api/contracts/{ids['contract_id']}/amendments",
        json={
            "amendment_type": "rate_change",
            "effective_date": (start - timedelta(days=10)).isoformat(),
            "new_rate_candidate": 165,
            "new_rate_client": 230,
            "reason": "aneks przed startem",
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    contract = await _contract_with_schedules(ids["contract_id"])
    on = start + timedelta(days=5)
    assert Decimal(contract.effective_candidate_rate(on)) == Decimal("165")
    assert Decimal(contract.effective_client_rate(on)) == Decimal("230")
