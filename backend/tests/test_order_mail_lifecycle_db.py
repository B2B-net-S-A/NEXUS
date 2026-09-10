"""Hosted-Postgres acceptance tests for atomic writes and one-off protection."""

from datetime import date, timedelta
from decimal import Decimal
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, func, text
from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.client_directory import ClientPortfolioScope, PortfolioCategory
from app.models.candidate import Candidate
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.order_mail import OrderMailDocument
from app.models.activity import Activity
from app.services.order_mail_apply import apply_document
from app.services.order_mail_cleanup import client_inventory, fingerprint


def document(client_id, name, number, *, start="2033-09-01", end="2033-11-30"):
    return OrderMailDocument(
        internet_message_id=f"<{uuid.uuid4()}@example.test>",
        client_id=client_id,
        outcome="needs_review",
        gate_verdict="auto",
        extraction={
            "title": number,
            "start_date": start,
            "end_date": end,
            "source": "claude",
            "uncertain": False,
            "confidence": {"title": 1.0},
            "consultant_rows": [
                {
                    "consultant_name": name,
                    "rate_client": "140.00",
                    "rate_unit": "hour",
                    "uncertain": False,
                }
            ],
        },
        proposal={"rows": [{"action": "new_draft"}]},
    )


@pytest.mark.asyncio
async def test_first_mail_creates_once_then_updates_draft_and_notifies_once(
    monkeypatch,
):
    from app.services import order_mail_apply as writer

    notify = AsyncMock()
    monkeypatch.setattr(writer, "_notify_new_draft", notify)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Mail lifecycle {uuid.uuid4().hex}")
        db.add(client)
        await db.flush()
        name = "Jan Testowy" + uuid.uuid4().hex[:8]
        first = document(client.id, name, "Zlecenie nr 22")
        db.add(first)
        await db.flush()
        result = await apply_document(db, first, actor_user_id=None)
        assert result.ok, result.as_dict()
        order = await db.get(ClientOrder, result.rows[0].order_id)
        assert order.status == ClientOrderStatus.draft
        assert order.rate_client == Decimal("140") and order.rate_candidate is None
        second = document(client.id, name, "Zlecenie nr 23")
        db.add(second)
        await db.flush()
        updated = await apply_document(db, second, actor_user_id=None)
        assert updated.ok, updated.as_dict()
        assert updated.rows[0].order_id == order.id
        assert order.title == "Zlecenie nr 23"
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Contract)
                .where(Contract.client_id == client.id)
            )
            == 1
        )
        notify.assert_awaited_once()
        await db.rollback()


async def _returning_consultant(db, *, start, end, **contract_fields):
    """Klient + osoba z zakończonym zamówieniem okresowym na tej samej umowie."""
    client = Client(name=f"Returning mail {uuid.uuid4().hex}")
    candidate = Candidate(name="Jan", lastname="Powrotny" + uuid.uuid4().hex[:8])
    db.add_all([client, candidate])
    await db.flush()
    contract = Contract(
        client_id=client.id,
        candidate_id=candidate.id,
        status=ContractStatus.ended,
        start_date=start,
        end_date=end,
        rate_candidate=Decimal("100"),
        rate_unit=RateUnit.hourly,
        **contract_fields,
    )
    db.add(contract)
    await db.flush()
    completed = ClientOrder(
        client_id=client.id,
        contract_id=contract.id,
        title="Old order",
        status=ClientOrderStatus.completed,
        start_date=start,
        end_date=end,
        rate_client=Decimal("140"),
        rate_candidate=Decimal("100"),
        rate_unit=RateUnit.hourly,
        order_type="periodic",
    )
    db.add(completed)
    await db.flush()
    return client, candidate, contract, completed


async def _assert_completed_untouched(db, completed, *, start, end):
    await db.refresh(completed)
    assert completed.status == ClientOrderStatus.completed
    assert completed.title == "Old order"
    assert (completed.start_date, completed.end_date) == (start, end)
    assert completed.rate_client == Decimal("140")
    assert completed.rate_candidate == Decimal("100")
    assert completed.file_path is None and completed.notes is None
    touched = await db.scalar(
        select(func.count())
        .select_from(Activity)
        .where(
            Activity.entity_type == "client_order",
            Activity.entity_id == completed.id,
        )
    )
    assert touched == 0, "writer zostawił ślad na zakończonym zamówieniu"


@pytest.mark.asyncio
async def test_return_after_gap_creates_new_order_and_leaves_completed_untouched():
    """Decyzja 10.09.2026: powrót po przerwie = NOWE zamówienie.

    Do tej rewizji writer przepisywał zakończone zamówienie (tytuł, okres,
    stawki, PDF) i przestawiał je na draft — a na nim rozliczono już faktury.
    Link do poprzednika niesie wyłącznie Activity nowego zamówienia.
    """
    old_start, old_end = date(2033, 1, 1), date(2033, 7, 31)
    async with AsyncSessionLocal() as db:
        client, candidate, contract, completed = await _returning_consultant(
            db, start=old_start, end=old_end
        )
        doc = document(client.id, f"{candidate.name} {candidate.lastname}", "New order")
        db.add(doc)
        await db.flush()
        result = await apply_document(db, doc, actor_user_id=None)
        assert result.ok, result.as_dict()
        assert result.rows[0].action == "reactivate"
        assert result.rows[0].order_id != completed.id

        await _assert_completed_untouched(db, completed, start=old_start, end=old_end)
        renewal = await db.get(ClientOrder, result.rows[0].order_id)
        assert renewal.contract_id == contract.id
        assert renewal.title == "New order"
        assert (renewal.start_date, renewal.end_date) == (
            date(2033, 9, 1),
            date(2033, 11, 30),
        )
        assert renewal.rate_client == Decimal("140")
        assert renewal.rate_candidate == Decimal("100")  # z umowy, nie z PDF-a
        assert renewal.status == ClientOrderStatus.active
        assert renewal.notes == f"Zamówienie z maila (dokument #{doc.id})"
        assert renewal.predecessor_order_id is None
        activity = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "client_order",
                Activity.entity_id == renewal.id,
                Activity.action == "order_mail_renewal",
            )
        )
        assert activity is not None
        assert activity.details["renewal_of_order_id"] == completed.id
        assert activity.details["gap_days"] == 32
        assert activity.details["previous_end_date"] == "2033-07-31"
        assert activity.details["document_id"] == doc.id

        # Ponowienie bez zapisanego wyniku (crash) nie dubluje zamówienia.
        doc.proposal = {k: v for k, v in doc.proposal.items() if k != "apply_result"}
        await db.flush()
        again = await apply_document(db, doc, actor_user_id=None)
        assert again.ok, again.as_dict()
        assert again.rows[0].order_id == renewal.id
        assert (
            await db.scalar(
                select(func.count())
                .select_from(ClientOrder)
                .where(ClientOrder.contract_id == contract.id)
            )
            == 2
        )
        await _assert_completed_untouched(db, completed, start=old_start, end=old_end)
        await db.rollback()


@pytest.mark.asyncio
async def test_return_on_terminated_contract_stays_draft_and_never_revives_it():
    """Mail nie cofa wypowiedzenia umowy (A3, 10.09.2026).

    Nowe zamówienie obejmuje DZIŚ, więc bez tej reguły zostałoby aktywowane
    (umowa ``ended`` przepuszczała aktywację), a ``sync_contract_to_live_order``
    przywróciłoby wypowiedzianą umowę do aktywnych — i do MRR.
    """
    from app.core.scheduling import business_today
    from app.models.contract import ContractTerminationReason
    from app.services.order_mail_signature import complete_signed_mail_drafts

    today = business_today()
    old_start, old_end = today - timedelta(days=400), today - timedelta(days=40)
    async with AsyncSessionLocal() as db:
        client, candidate, contract, completed = await _returning_consultant(
            db,
            start=old_start,
            end=old_end,
            terminated_at=old_end,
            termination_reason=ContractTerminationReason.project_ended,
        )
        doc = document(
            client.id,
            f"{candidate.name} {candidate.lastname}",
            "Return after termination",
            start=(today - timedelta(days=5)).isoformat(),
            end=(today + timedelta(days=60)).isoformat(),
        )
        db.add(doc)
        await db.flush()
        result = await apply_document(db, doc, actor_user_id=None)
        assert result.ok, result.as_dict()
        assert result.rows[0].activated is False
        assert result.rows[0].contract_revived is False
        renewal = await db.get(ClientOrder, result.rows[0].order_id)
        assert renewal.id != completed.id
        assert renewal.status == ClientOrderStatus.draft
        await db.refresh(contract)
        assert contract.status == ContractStatus.ended
        assert contract.terminated_at == old_end
        await _assert_completed_untouched(db, completed, start=old_start, end=old_end)

        # Zdarzenie podpisu (webhook Autenti, potwierdzenie w generatorze B2B)
        # woła tę samą regułę — szkic z maila zostaje szkicem.
        assert doc.applied_order_id == renewal.id
        assert await complete_signed_mail_drafts(db, contract.id) == 0
        await db.refresh(renewal)
        assert renewal.status == ClientOrderStatus.draft
        await db.rollback()


@pytest.mark.asyncio
async def test_single_global_namesake_needs_a_human_and_diacritics_fold(monkeypatch):
    """Osoba bez umowy u klienta, a w bazie jedna osoba o tym nazwisku (A4).

    Prefiltr zwija polskie znaki po obu stronach: „Lukasz Gradzki" z PDF-a
    znajduje „Łukasz Grądzki" z bazy — wcześniej writer zakładał po cichu
    drugą kartę tej osoby. Automat (bez aktora) nie dopina cudzej karty po
    samym nazwisku: dokument wraca do weryfikacji. Człowiek dopina istniejącą
    osobę i nie powstaje nowy kandydat.
    """
    from app.core.security import hash_password
    from app.models.user import User, UserRole
    from app.services import order_mail_apply as writer

    monkeypatch.setattr(writer, "_notify_new_draft", AsyncMock())
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Namesake mail {suffix}")
        person = Candidate(name="Łukasz", lastname=f"Grądzki{suffix}")
        reviewer = User(
            email=f"namesake-{suffix}@example.test",
            password_hash=hash_password(f"P4ss_{suffix}!"),
            name="Namesake reviewer",
            role=UserRole.admin,
            roles=[UserRole.admin.value],
            is_active=True,
            profile_completed=True,
        )
        db.add_all([client, person, reviewer])
        await db.flush()
        doc = document(client.id, f"Lukasz Gradzki{suffix}", "Namesake order")
        db.add(doc)
        await db.flush()

        async def people_with_suffix():
            return await db.scalar(
                select(func.count())
                .select_from(Candidate)
                .where(Candidate.lastname.ilike(f"%{suffix}"))
            )

        automatic = await apply_document(db, doc, actor_user_id=None)
        assert not automatic.ok
        assert f"#{person.id}" in automatic.error
        assert "zastosuj ręcznie" in automatic.error
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Contract)
                .where(Contract.client_id == client.id)
            )
            == 0
        )
        assert await people_with_suffix() == 1

        manual = await apply_document(db, doc, actor_user_id=reviewer.id)
        assert manual.ok, manual.as_dict()
        order = await db.get(ClientOrder, manual.rows[0].order_id)
        contract = await db.get(Contract, order.contract_id)
        assert contract.client_id == client.id
        assert contract.candidate_id == person.id
        assert await people_with_suffix() == 1
        await db.rollback()


@pytest.mark.asyncio
async def test_error_in_second_person_rolls_back_first_person(monkeypatch):
    from app.services import order_mail_apply as writer

    monkeypatch.setattr(writer, "_notify_new_draft", AsyncMock())
    original = writer._new_person_contract
    calls = 0

    async def fail_second(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("synthetic conflict in second row")
        return await original(*args)

    monkeypatch.setattr(writer, "_new_person_contract", fail_second)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Atomic mail {uuid.uuid4().hex}")
        db.add(client)
        await db.flush()
        cid = client.id
        doc = document(cid, "Jan Atomowy" + uuid.uuid4().hex[:8], "Atomic")
        doc.extraction = {
            **doc.extraction,
            "consultant_rows": [
                *doc.extraction["consultant_rows"],
                {
                    "consultant_name": "Anna Atomowa" + uuid.uuid4().hex[:8],
                    "rate_client": "140",
                    "rate_unit": "hour",
                },
            ],
        }
        db.add(doc)
        await db.flush()
        result = await apply_document(db, doc, actor_user_id=None)
        assert not result.ok and "synthetic conflict" in result.error
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Contract)
                .where(Contract.client_id == cid)
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(ClientOrder)
                .where(ClientOrder.client_id == cid)
            )
            == 0
        )
        assert doc.applied_order_id is None
        await db.rollback()


@pytest.mark.asyncio
async def test_cleanup_uses_effective_inactive_tab_and_preserves_all_relations():
    async with AsyncSessionLocal() as db:
        no_history = Client(name=f"Inactive membership {uuid.uuid4().hex}")
        history = Client(
            name=f"Inactive history {uuid.uuid4().hex}",
            notes="Previous sales discussion",
        )
        active = Client(name=f"Active protected {uuid.uuid4().hex}")
        db.add_all([no_history, history, active])
        await db.flush()
        for client in (no_history, history, active):
            db.add(
                ClientPortfolioScope(
                    client_id=client.id,
                    category=PortfolioCategory.active,
                    category_override=PortfolioCategory.inactive
                    if client != active
                    else None,
                )
            )
        await db.flush()
        soft_table = "test_mail_cleanup_soft_" + uuid.uuid4().hex
        await db.execute(text(f'CREATE TABLE "{soft_table}" (client_id integer)'))
        await db.execute(
            text(f'INSERT INTO "{soft_table}" (client_id) VALUES (:id)'),
            {"id": no_history.id},
        )
        before = set(db.dirty), set(db.deleted)
        plan = await client_inventory(db)
        assert no_history.id in [r["id"] for r in plan["blocked"]]
        assert history.id in [r["id"] for r in plan["preserved"]]
        assert active.id not in [r["id"] for values in plan.values() for r in values]
        assert any(
            r["table"] == "client_portfolio_scopes"
            for c in plan["blocked"]
            if c["id"] == no_history.id
            for r in c["dependencies"]
        )
        assert any(
            r["table"] == soft_table
            for c in plan["blocked"]
            if c["id"] == no_history.id
            for r in c["dependencies"]
        )
        assert (set(db.dirty), set(db.deleted)) == before
        assert fingerprint(plan) == fingerprint(await client_inventory(db))
        await db.rollback()


@pytest.mark.asyncio
async def test_signature_completes_mail_draft_with_agreement_cost(monkeypatch):
    from app.services import order_mail_apply as writer
    from app.services import order_mail_signature as signature

    monkeypatch.setattr(writer, "_notify_new_draft", AsyncMock())
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Signature mail {uuid.uuid4().hex}")
        db.add(client)
        await db.flush()
        doc = document(
            client.id, "Jan Podpisany" + uuid.uuid4().hex[:8], "Signed order"
        )
        db.add(doc)
        await db.flush()
        result = await apply_document(db, doc, actor_user_id=None)
        assert result.ok, result.as_dict()
        order = await db.get(ClientOrder, result.rows[0].order_id)
        contract = await db.get(Contract, order.contract_id)
        assert order.status == ClientOrderStatus.draft
        doc.applied_order_id = order.id
        doc.proposal = {"apply_result": result.as_dict()}
        contract.rate_candidate = Decimal("100")
        contract.rate_candidate_currency = "PLN"
        await db.flush()
        monkeypatch.setattr(
            signature, "can_activate_mail_order", AsyncMock(return_value=True)
        )
        assert await signature.complete_signed_mail_drafts(db, contract.id) == 1
        assert order.rate_candidate == Decimal("100")
        assert order.status == ClientOrderStatus.active
        assert await signature.complete_signed_mail_drafts(db, contract.id) == 0
        await db.rollback()


@pytest.mark.asyncio
async def test_cleanup_audit_and_apply_honour_the_autoapply_kill_switch(
    monkeypatch, tmp_path
):
    """Jednorazowe sprzątanie kolejki zapisuje bez aktora — też słucha flagi."""
    from types import SimpleNamespace

    from app.services import order_mail_cleanup as cleanup
    from app.services import order_mail_ingest as ingest

    async def certain(db, doc):
        doc.gate_verdict = "auto"
        doc.gate_reasons = []

    apply = AsyncMock()
    monkeypatch.setattr(cleanup, "refresh_review_plan", certain)
    monkeypatch.setattr(cleanup, "apply_document", apply)
    monkeypatch.setattr(
        cleanup, "extract_order_text", lambda *a: SimpleNamespace(text="Zamówienie")
    )
    monkeypatch.setattr(
        cleanup.storage_service,
        "get_order_mail_attachment_path",
        lambda path: tmp_path / "doc.pdf",
    )
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Cleanup kill switch {uuid.uuid4().hex}")
        db.add(client)
        await db.flush()
        doc = document(client.id, "Jan Sprzątany", "Cleanup order")
        doc.storage_path = "cleanup.pdf"
        db.add(doc)
        await db.flush()
        # Wycofany savepoint wygasza obiekt — id zapamiętane przed audytem.
        doc_id = doc.id

        async def plan_for_doc():
            plans = await cleanup.queue_inventory(db)
            return next(p for p in plans if p["before"]["id"] == doc_id)

        monkeypatch.setattr(ingest.settings, "ORDER_MAIL_AUTOAPPLY_ENABLED", True)
        assert (await plan_for_doc())["action"] == "apply"
        monkeypatch.setattr(ingest.settings, "ORDER_MAIL_AUTOAPPLY_ENABLED", False)
        held = await plan_for_doc()
        assert held["action"] == "refresh"
        assert held["after"]["verdict"] == "review"
        assert held["after"]["reasons"] == [ingest.AUTOAPPLY_DISABLED_REASON]

        # Flaga wyłączona pod planem „apply" (zmiana w trakcie wywołania)
        # przerywa całe sprzątanie, zamiast zapisać zamówienie.
        plan = {
            "clients": {"delete_candidates": [], "blocked": [], "preserved": []},
            "queue": [{"before": {"id": doc_id}, "action": "apply"}],
            "review_reasons_by_client": {},
            "fingerprint": "expected",
        }
        monkeypatch.setattr(cleanup, "build_cleanup_plan", AsyncMock(return_value=plan))
        with pytest.raises(ValueError, match="Automatyczny zapis jest wyłączony"):
            await cleanup.apply_cleanup_plan(db, "expected")
        apply.assert_not_awaited()
        await db.rollback()


@pytest.mark.asyncio
async def test_cleanup_fingerprint_guard_and_durable_receipt(monkeypatch):
    from app.services import order_mail_cleanup as cleanup
    from app.models.app_setting import AppSetting

    plan = {
        "clients": {"delete_candidates": [], "blocked": [], "preserved": []},
        "queue": [],
        "review_reasons_by_client": {},
        "fingerprint": "expected",
    }
    monkeypatch.setattr(cleanup, "build_cleanup_plan", AsyncMock(return_value=plan))
    async with AsyncSessionLocal() as db:
        with pytest.raises(ValueError, match="Dane zmieniły"):
            await cleanup.apply_cleanup_plan(db, "stale")
        assert await db.get(AppSetting, cleanup.RECEIPT_KEY) is None
        result = await cleanup.apply_cleanup_plan(db, "expected")
        assert result["deleted_clients"] == []
        assert (await db.get(AppSetting, cleanup.RECEIPT_KEY)).value == result
        assert await cleanup.apply_cleanup_plan(db, "expected") == result
        await db.rollback()
