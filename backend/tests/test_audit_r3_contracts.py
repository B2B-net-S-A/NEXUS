"""Audyt 25.09.2026, runda 3 — umowy i Generator umów B2B.

* R3-1 — cofnięcie zakończenia bez migawki: data końca umowy zlecenie
  zakończonej przez nocny cron NIE jest śladem zakończenia (zostaje, a minioną
  łapie bloker ``end_date_passed``).
* R3-8 — podpisane rozwiązanie/wypowiedzenie w Generatorze zamyka umowę w
  rejestrze tą samą drogą co okno „Zakończ współpracę" (migawka, tryb,
  „Zakończona" dopiero gdy data nadeszła).
* R3-9 — ręczna zmiana statusu w rejestrze czyści migawkę zakończenia.
* R3-10 — umowa z Excela zawieszona przez synchronizację dostaje link do
  kontraktu, więc powrót z zawieszenia nie kończy się 409.
* niskie — rok numeracji z kalendarza firmy, nie z UTC.

Testy czystych reguł biegną bez bazy; reszta idzie prawdziwymi trasami na
własnych wierszach (baza wspólna, nieczyszczona).
"""

from __future__ import annotations

import ast
import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.scheduling import business_today

# ── czyste reguły (bez bazy) ─────────────────────────────────────────────────


class _NoAmendmentDb:
    async def scalar(self, _query):
        return None


def _contract_stub(**fields):
    base = dict(
        id=1,
        contract_type="uzlecenie",
        end_date=None,
        terminated_at=None,
    )
    base.update(fields)
    return SimpleNamespace(**base)


async def test_cron_ended_mandate_keeps_its_end_date_without_snapshot():
    """R3-1: umowa zlecenie zakończona przez cron (``terminated_at`` puste)
    — plan liczy ``terminated_on = end_date``, więc sama równość dat była
    tautologią i umowa wracała bezterminowa."""
    from app.services.contract_termination_reversal import (
        _history_contract_end_date,
    )

    ended_on = business_today() - timedelta(days=5)
    contract = _contract_stub(end_date=ended_on, terminated_at=None)
    assert (
        await _history_contract_end_date(_NoAmendmentDb(), contract, ended_on)
        == ended_on
    )


async def test_manual_termination_trace_still_makes_mandate_indefinite():
    """Reguła z rundy 2 zostaje: data końca równa dacie RĘCZNEGO zakończenia
    (``/terminate`` wpisuje ją umowie bezterminowej) jest śladem zakończenia."""
    from app.services.contract_termination_reversal import (
        _history_contract_end_date,
    )

    ended_on = business_today() - timedelta(days=5)
    contract = _contract_stub(end_date=ended_on, terminated_at=ended_on)
    assert (
        await _history_contract_end_date(_NoAmendmentDb(), contract, ended_on) is None
    )


def _row(**fields):
    base = dict(
        contract_status="active",
        termination_mode=None,
        termination_party=None,
        termination_signed_on=None,
        termination_restore=None,
        closure_reason=None,
        closure_reason_other=None,
        closure_date=None,
        project_end_date=None,
    )
    base.update(fields)
    return SimpleNamespace(**base)


def test_signed_dissolution_marks_the_row_without_closing_it():
    from app.services.contract_termination_sync import (
        clear_pending_dissolution,
        mark_pending_dissolution,
        pending_dissolution,
    )

    row = _row()
    signed = business_today()
    assert mark_pending_dissolution(
        row, mode="mutual_agreement", party=None, signed_on=signed
    )
    assert row.contract_status == "active"
    assert pending_dissolution(row) == ("mutual_agreement", None, signed)
    assert clear_pending_dissolution(row)
    assert pending_dissolution(row) is None
    assert row.termination_mode is None


def test_marker_is_not_set_on_rows_that_do_not_bind_anymore():
    from app.services.contract_termination_sync import mark_pending_dissolution

    for status in ("in_progress", "cancelled", "closed"):
        row = _row(contract_status=status)
        assert not mark_pending_dissolution(
            row, mode="notice", party="company", signed_on=business_today()
        )
        assert row.termination_mode is None
    changed_by_contract = _row(
        contract_status="suspended", termination_restore={"contract_id": 5}
    )
    assert not mark_pending_dissolution(
        changed_by_contract, mode="notice", party="company", signed_on=None
    )


def test_mode_left_by_an_earlier_contract_termination_is_not_a_marker():
    """Wiersz z migawką opisuje zakończenie, które już go przestawiło —
    jego tryb nie jest czekającym rozwiązaniem."""
    from app.services.contract_termination_sync import pending_dissolution

    row = _row(
        contract_status="active",
        termination_mode="notice",
        termination_restore={"contract_id": 7},
    )
    assert pending_dissolution(row) is None


def test_snapshot_without_marker_forgets_the_document_mode():
    from app.services.contract_termination_sync import _snapshot

    row = _row(
        termination_mode="mutual_agreement",
        termination_signed_on=business_today(),
    )
    snap = _snapshot(row, SimpleNamespace(id=11), without_marker=True)
    assert snap["contract_id"] == 11
    assert snap["contract_status"] == "active"
    assert snap["termination_mode"] is None
    assert snap["termination_signed_on"] is None


def test_generator_number_year_comes_from_the_business_calendar():
    """Numer „<seq>/<rok>” 1 stycznia między 00:00 a 01:00 (Warszawa) dostawał
    rok z zegara UTC — poprzedni."""
    source = Path(__file__).resolve().parents[1] / "app/api/b2b_contract_generator.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    utc_years = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == "year"
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "now"
    ]
    assert utc_years == []


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


async def test_cron_ended_mandate_reversal_keeps_date_and_is_blocked(
    app_client, app_auth_headers
):
    """R3-1 na prawdziwej trasie: umowa zlecenie zakończona przez cron
    (status ``ended``, data końca w treści minęła, bez ``terminated_at``) —
    cofnięcie zachowuje datę i odmawia do przedłużenia aneksem."""
    from tests.test_contract_termination_reversal import (
        _ended_on,
        _seed_active_md_consultant,
    )

    ended_on = _ended_on()
    seed = await _seed_active_md_consultant(
        contract_type="uzlecenie", contract_status="ended", contract_end_date=ended_on
    )
    preview = await app_client.get(
        f"{CONTRACTS}/{seed['contract_id']}/termination-reversal",
        headers=app_auth_headers,
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["contract"]["end_date_target"] == ended_on.isoformat()
    assert "end_date_passed" in {b["code"] for b in body["blockers"]}


async def _signed_parent(app_client) -> tuple[int, int]:
    from tests.test_b2b_documents_api import _signed_parent as seed

    return await seed(app_client)


async def _create_termination(
    app_client, headers, parent_id: int, *, termination: date
) -> int:
    resp = await app_client.post(
        f"{GENERATOR}/documents",
        headers=headers,
        json={
            "document_type": "termination_agreement",
            "language": "pl",
            "parent_generated_contract_id": parent_id,
            "values": {
                "document_date": (business_today() - timedelta(days=10)).isoformat(),
                "gender": "k",
                "partner_name": "Anna Testowa",
                "partner_legal_name": "Anna Testowa IT",
                "termination_date": termination.isoformat(),
                "last_service_date": termination.isoformat(),
            },
        },
    )
    assert resp.status_code == 200, resp.text
    return int(resp.headers["X-Document-Id"])


async def _generated(gid: int):
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract

    async with AsyncSessionLocal() as db:
        return await db.get(B2BGeneratedContract, gid)


async def test_future_dissolution_keeps_the_agreement_until_the_cron_closes_it(
    app_client, app_auth_headers, fake_render
):
    """R3-8: porozumienie o rozwiązaniu z datą w przyszłości — umowa obowiązuje
    do tej daty; zamyka ją nocny cron (z migawką i trybem), a powrót po
    przerwie zakłada NOWĄ umowę zamiast przywracać rozwiązaną."""
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from app.models.contract import Contract, ContractStatus
    from app.services.contract_lifecycle import sync_contract_to_live_order
    from app.tasks import contract_alerts
    from sqlalchemy import select

    rid, contract_id = await _signed_parent(app_client)
    when = business_today() + timedelta(days=20)
    doc_id = await _create_termination(
        app_client, app_auth_headers, rid, termination=when
    )
    signed = await app_client.post(
        f"{GENERATOR}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text

    row = await _generated(rid)
    assert row.contract_status == "active"
    assert row.closure_date is None
    assert row.termination_mode == "mutual_agreement"
    assert row.termination_restore is None
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract.status == ContractStatus.ending
        assert contract.terminated_at == when

    # Data nadeszła: nocny cron kończy kontrakt i zamyka umowę w rejestrze.
    passed = business_today() - timedelta(days=1)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        contract.end_date = passed
        contract.terminated_at = passed
        await db.commit()
    async with AsyncSessionLocal() as db:
        await contract_alerts._promote_statuses(db)
        await db.commit()

    row = await _generated(rid)
    assert row.contract_status == "closed"
    assert row.closure_date == passed
    assert row.termination_mode == "mutual_agreement"
    assert (row.termination_restore or {}).get("contract_id") == contract_id
    assert row.termination_restore["termination_mode"] is None

    # Powrót po przerwie: rozwiązana umowa zostaje w „Zakończonych”.
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        await sync_contract_to_live_order(
            db,
            contract,
            order_start=business_today(),
            order_end=None,
            actor_id=None,
            today=business_today(),
        )
        await db.commit()
    previous = await _generated(rid)
    assert previous.contract_status == "closed"
    async with AsyncSessionLocal() as db:
        follow_up = await db.scalar(
            select(B2BGeneratedContract).where(
                B2BGeneratedContract.previous_generated_contract_id == rid
            )
        )
    assert follow_up is not None
    assert follow_up.contract_status == "in_progress"


async def test_past_dissolution_closes_with_snapshot_and_reversal_restores_it(
    app_client, app_auth_headers, fake_render
):
    """R3-8: data rozwiązania minęła — umowa „Zakończona” od razu, z trybem
    i migawką, więc „Cofnij zakończenie” wraca ją na „Aktywną”."""
    rid, contract_id = await _signed_parent(app_client)
    when = business_today() - timedelta(days=2)
    doc_id = await _create_termination(
        app_client, app_auth_headers, rid, termination=when
    )
    signed = await app_client.post(
        f"{GENERATOR}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    row = await _generated(rid)
    assert row.contract_status == "closed"
    assert row.closure_date == when
    assert row.termination_mode == "mutual_agreement"
    assert (row.termination_restore or {}).get("contract_id") == contract_id

    reversal = await app_client.post(
        f"{CONTRACTS}/{contract_id}/termination-reversal", headers=app_auth_headers
    )
    assert reversal.status_code == 200, reversal.text
    row = await _generated(rid)
    assert row.contract_status == "active"
    assert row.termination_mode is None
    assert row.termination_restore is None


async def test_withdrawn_partner_notice_leaves_no_pending_dissolution(
    app_client, app_auth_headers, fake_render
):
    """R3-8: wypowiedzenie Partnera z przyszłą datą czeka na wierszu; cofnięcie
    wypowiedzenia zdejmuje znacznik, żeby cron nie zamknął umowy."""
    rid, _contract_id = await _signed_parent(app_client)
    delivered = business_today()
    notice = await app_client.post(
        f"{GENERATOR}/documents/partner-notice",
        headers=app_auth_headers,
        json={
            "parent_generated_contract_id": rid,
            "delivered_on": delivered.isoformat(),
            "termination_date": (delivered + timedelta(days=30)).isoformat(),
        },
    )
    assert notice.status_code == 200, notice.text
    row = await _generated(rid)
    assert row.contract_status == "active"
    assert row.termination_mode == "notice"
    assert row.termination_party == "consultant"

    resp = await app_client.post(
        f"{GENERATOR}/documents",
        headers=app_auth_headers,
        json={
            "document_type": "notice_withdrawal",
            "language": "pl",
            "parent_generated_contract_id": rid,
            "values": {
                "document_date": delivered.isoformat(),
                "gender": "k",
                "partner_name": "Anna Testowa",
                "partner_legal_name": "Anna Testowa IT",
                "notice_delivery_date": delivered.isoformat(),
            },
        },
    )
    assert resp.status_code == 200, resp.text
    doc_id = int(resp.headers["X-Document-Id"])
    signed = await app_client.post(
        f"{GENERATOR}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    row = await _generated(rid)
    assert row.contract_status == "active"
    assert row.termination_mode is None


async def test_manual_register_status_wins_over_the_termination_snapshot(
    app_client, app_auth_headers
):
    """R3-9: rejestr zamknięty synchronizacją, człowiek przywraca „Aktywną” —
    „Cofnij zakończenie” kontraktu nie może wrócić do migawki („Bez projektu”)."""
    from tests.test_contract_termination_form_sync import _dissolution, _seed

    cid, gid, _ = await _seed(generator_status="suspended")
    project_end = business_today() - timedelta(days=1)
    ended = await app_client.post(
        f"{CONTRACTS}/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "terminated_at": project_end.isoformat(),
            "agreement_termination": _dissolution(project_end, project_end),
        },
        headers=app_auth_headers,
    )
    assert ended.status_code == 200, ended.text
    row = await _generated(gid)
    assert row.contract_status == "closed"
    assert row.termination_restore is not None

    manual = await app_client.patch(
        f"{GENERATOR}/generated/{gid}",
        json={"contract_status": "active"},
        headers=app_auth_headers,
    )
    assert manual.status_code == 200, manual.text
    row = await _generated(gid)
    assert row.contract_status == "active"
    assert row.termination_restore is None
    assert row.termination_mode is None

    reversal = await app_client.post(
        f"{CONTRACTS}/{cid}/termination-reversal", headers=app_auth_headers
    )
    assert reversal.status_code == 200, reversal.text
    assert (await _generated(gid)).contract_status == "active"


async def test_excel_row_suspended_by_sync_can_return_to_a_project(
    app_client, app_auth_headers
):
    """R3-10: wiersz z Excela (bez ``contract_id``) dopasowany po osobie
    i zawieszony synchronizacją dostaje link do kontraktu — powrót na
    „Aktywna” z projektem przechodzi zamiast 409."""
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from tests.test_b2b_generated_contract_status import _seed_job
    from tests.test_contract_termination_form_sync import _seed

    cid, gid, _ = await _seed(link_generator=False)
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, gid)
        row.source = "excel"
        row.source_key = f"r3-{uuid.uuid4().hex}"
        client_id = row.client_id
        await db.commit()

    ended = await app_client.post(
        f"{CONTRACTS}/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "terminated_at": (business_today() - timedelta(days=1)).isoformat(),
        },
        headers=app_auth_headers,
    )
    assert ended.status_code == 200, ended.text
    row = await _generated(gid)
    assert row.contract_status == "suspended"
    assert row.contract_id == cid

    job_id = await _seed_job(client_id, f"Powrót {uuid.uuid4().hex[:6]}")
    back = await app_client.patch(
        f"{GENERATOR}/generated/{gid}",
        json={"contract_status": "active", "job_id": job_id},
        headers=app_auth_headers,
    )
    assert back.status_code == 200, back.text
    assert (await _generated(gid)).contract_status == "active"
