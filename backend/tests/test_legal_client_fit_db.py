"""Zgodność umów B2B z umową ramową klienta (asystent prawny G) — z bazą (CI).

Fikcyjni klienci i fikcyjne klauzule.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.legal_client_fit import LegalClientFitCheck, LegalClientFitFinding
from app.models.user import UserRole
from app.services.legal_client_fit import engine, service, task_provider
from tests.test_permissions_contracts_rules import _user


def _finding(
    topic: str, state: str = "gap", quote: str = "Wykonawca zapewni szkolenie."
) -> engine.Finding:
    return engine.Finding(
        topic=topic,
        state=state,
        summary="Fikcyjne ustalenie.",
        client_quote=quote,
        client_ref="Aneks „Fikcyjny”, § 4 ust. 1",
        client_source_kind="amendment",
        client_source_id=1,
        our_quote=None if state == "gap" else "Partner zachowa poufność.",
        our_ref=None if state == "gap" else "§ 8",
        next_step="Dopisz w aneksie.",
        annex_text="Partner zobowiązuje się do szkolenia." if state != "ok" else None,
    )


async def _client() -> int:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Bank Fikcyjny {uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.commit()
        return client.id


async def _cleanup(client_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(Client.__table__.delete().where(Client.id == client_id))
        await db.commit()


async def _count(client_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return int(
            await db.scalar(
                select(func.count(LegalClientFitFinding.id)).where(
                    LegalClientFitFinding.client_id == client_id
                )
            )
        )


async def test_recheck_overwrites_topics_instead_of_duplicating() -> None:
    client_id = await _client()
    try:
        async with AsyncSessionLocal() as db:
            await service.store_findings(
                db, client_id, [_finding("ict_training"), _finding("audit_rights")]
            )
            await db.commit()
        async with AsyncSessionLocal() as db:
            first = await db.scalar(
                select(LegalClientFitFinding.id).where(
                    LegalClientFitFinding.client_id == client_id,
                    LegalClientFitFinding.topic == "ict_training",
                )
            )
            await service.store_findings(
                db,
                client_id,
                [
                    _finding(
                        "ict_training", quote="Wykonawca zapewni coroczne szkolenie."
                    )
                ],
            )
            await db.commit()
        assert await _count(client_id) == 1  # temat, którego już nie ma, znika
        async with AsyncSessionLocal() as db:
            row = await db.scalar(
                select(LegalClientFitFinding).where(
                    LegalClientFitFinding.client_id == client_id
                )
            )
            assert row.id == first  # to samo ustalenie, nowa treść
            assert row.client_quote == "Wykonawca zapewni coroczne szkolenie."
    finally:
        await _cleanup(client_id)


async def test_upload_trigger_does_not_queue_twice(monkeypatch) -> None:
    started: list[int] = []
    monkeypatch.setattr(service, "start", lambda cid: started.append(cid))
    client_id = await _client()
    try:
        async with AsyncSessionLocal() as db:
            await service.request_check(db, client_id, trigger="upload")
            await service.request_check(db, client_id, trigger="upload")
        async with AsyncSessionLocal() as db:
            rows = (
                await db.scalars(
                    select(LegalClientFitCheck).where(
                        LegalClientFitCheck.client_id == client_id
                    )
                )
            ).all()
        assert len(rows) == 1 and rows[0].status == "queued"
        assert started == [client_id]
    finally:
        await _cleanup(client_id)


async def test_without_model_the_run_is_unavailable_and_shows_no_findings(
    monkeypatch,
) -> None:
    async def _unavailable(*_args, **_kwargs):
        return engine.FitOutcome(status="unavailable", message=engine.MSG_NO_KEY)

    async def _passages(*_args, **_kwargs):
        return [object()]

    monkeypatch.setattr(engine, "compare", _unavailable)
    monkeypatch.setattr(service.sources, "client_passages", _passages)
    monkeypatch.setattr(
        service.sources.ClientDocuments, "readable", property(lambda self: [1])
    )
    monkeypatch.setattr(service, "start", lambda _cid: None)
    client_id = await _client()
    try:
        async with AsyncSessionLocal() as db:
            await service.store_findings(db, client_id, [_finding("ict_training")])
            await db.commit()
            await service.request_check(db, client_id, trigger="manual")
        await service.run_check(client_id)
        async with AsyncSessionLocal() as db:
            client = await db.get(Client, client_id)
            view = await service.load_view(db, client)
        assert view.check.status == "unavailable"
        assert view.findings == []  # nic nie udaje zgodności
        assert "niedostępne" in view.check.status_message
    finally:
        await _cleanup(client_id)


async def test_tasks_for_delivery_lead_only_at_assigned_clients(monkeypatch) -> None:
    mine, other = await _client(), await _client()

    async def _portfolio(user, _db):
        # Jak prawdziwy resolver: portfel tylko dla Delivery Leada, reszta = wszyscy.
        return frozenset({mine}) if user.role == UserRole.delivery_lead else None

    monkeypatch.setattr(task_provider, "resolve_delivery_lead_client_ids", _portfolio)
    try:
        async with AsyncSessionLocal() as db:
            for client_id in (mine, other):
                db.add(
                    LegalClientFitCheck(
                        client_id=client_id,
                        status="done",
                        trigger="upload",
                        checked_at=service._now(),
                    )
                )
                await service.store_findings(
                    db,
                    client_id,
                    [_finding("ict_training"), _finding("copyright", "ok")],
                )
            await db.commit()
        async with AsyncSessionLocal() as db:
            lead = await task_provider.client_fit_tasks(
                db, _user(UserRole.delivery_lead)
            )
            admin = await task_provider.client_fit_tasks(db, _user(UserRole.admin))
        assert [t.client_id for t in lead] == [mine]
        assert {mine, other} <= {t.client_id for t in admin}
        task = lead[0]
        assert task.key.startswith(f"client_fit_gap:{mine}:") and task.severity == "gap"
        assert task.href.endswith(f"zgodnosc={mine}")
        assert "luki: 1" in task.detail
    finally:
        await _cleanup(mine)
        await _cleanup(other)
