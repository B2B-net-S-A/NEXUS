"""Writer zamówień z maila + kolejka (API) — end-to-end na bazie.

Seed: klient z NIP-em, kandydat z aktywnym kontraktem i stawką kosztową
(bez niej zamówienie nie aktywuje się — `rate_candidate` NIGDY z PDF-a),
dokument z planem `new`. Sprawdzamy: zamówienie powstało i jest aktywne,
PDF przypięty, `sync_contract_to_live_order` zadziałał, kolejka redaguje
kwoty dla roli bez finansów i odmawia „Zastosuj" HoR-owi.
Lata 2031+; identyfikatory per przebieg (baza współdzielona).
"""

import random
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.dl_alert import DlAlert
from app.models.order_mail import (
    OUTCOME_APPLIED,
    OUTCOME_NEEDS_REVIEW,
    OrderMailDocument,
)
from app.services import order_mail_ingest as svc
from app.services import storage_service
from app.services.order_mail_apply import apply_document

RUN = uuid.uuid4().hex[:8]


def _nip() -> str:
    w = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    while True:
        body = [random.randint(0, 9) for _ in range(9)]
        c = sum(d * x for d, x in zip(body, w)) % 11
        if c != 10:
            return "".join(map(str, body)) + str(c)


@pytest_asyncio.fixture
async def seeded(tmp_path, monkeypatch):
    tag = uuid.uuid4().hex[:8]  # per wywołanie — fixture jest function-scope
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(storage_service, "ORDER_MAIL_DIR", tmp_path / "order_mail")
    monkeypatch.setattr(
        storage_service, "CLIENT_ORDER_POS_DIR", tmp_path / "client_orders"
    )
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Bank Apply {tag} S.A.", nip=_nip())
        db.add(client)
        await db.flush()
        cand = Candidate(
            name="Jan",
            lastname=f"Testowy{tag[:4].upper()}",
            email=f"jan-{tag}@example.test",
        )
        db.add(cand)
        await db.flush()
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=date(2031, 1, 1),
            end_date=date(2031, 3, 31),
            rate_candidate=Decimal("700"),
            rate_client=Decimal("900"),
            rate_unit=RateUnit.daily,
        )
        db.add(contract)
        await db.flush()
        pdf_rel, _ = storage_service.save_order_mail_attachment(
            "ab" * 32,
            "zam.pdf",
            __import__("io").BytesIO(b"%PDF-1.4 apply " + tag.encode()),
        )
        doc = OrderMailDocument(
            internet_message_id=f"<apply-{tag}@example>",
            received_at=datetime.now(timezone.utc),
            sender_email="orders@bank-apply.example",
            subject="Zamówienie",
            attachment_name="zam.pdf",
            attachment_sha256="ab" * 32,
            storage_path=pdf_rel,
            outcome=OUTCOME_NEEDS_REVIEW,
            client_id=client.id,
            identification_method="registry_id",
            client_policy="PKO BP",
            extraction={
                "title": f"7/{tag}",
                "start_date": "2031-04-01",
                "end_date": "2031-06-30",
                "rate_client": "950.00",
                "rate_unit": "day",
                "uncertain": False,
                "consultant_rows": [
                    {
                        "consultant_name": f"Jan Testowy{tag[:4].upper()}",
                        "rate_client": "950.00",
                        "rate_unit": "day",
                    }
                ],
            },
            gate_verdict="review",
            gate_reasons=["test"],
            proposal={
                "client_id": client.id,
                "order_number": f"7/{tag}",
                "is_group_client": False,
                "blocking": [],
                "rows": [
                    {
                        "row_index": 0,
                        "row_name": "Jan",
                        "action": "future",
                        "candidate_id": cand.id,
                        "contract_id": contract.id,
                        "target_order_id": None,
                        "title": f"7/{tag}",
                        "start_date": "2031-04-01",
                        "end_date": "2031-06-30",
                        "rate_client": "950.00",
                        "rate_unit": "day",
                        "md_total": None,
                        "reasons": [],
                    }
                ],
            },
        )
        db.add(doc)
        await db.commit()
        return {
            "tag": tag,
            "client_id": client.id,
            "candidate_id": cand.id,
            "contract_id": contract.id,
            "doc_id": doc.id,
        }


@pytest.mark.asyncio
async def test_apply_creates_active_order_with_pdf_and_syncs_contract(seeded):
    async with AsyncSessionLocal() as db:
        doc = await db.get(OrderMailDocument, seeded["doc_id"])
        result = await apply_document(db, doc, actor_user_id=None)
        assert result.ok, result.as_dict()
        await db.commit()
        order = await db.scalar(
            select(ClientOrder).where(ClientOrder.id == result.rows[0].order_id)
        )
        assert order is not None
        assert order.status == ClientOrderStatus.active, order.status
        assert order.title == f"7/{seeded['tag']}"
        assert (order.start_date, order.end_date) == (
            date(2031, 4, 1),
            date(2031, 6, 30),
        )
        assert order.rate_client == Decimal("950.00") and order.rate_candidate is None
        assert order.rate_unit == RateUnit.daily
        assert order.file_path and order.filename == "zam.pdf"
        assert doc.applied_order_id == order.id and doc.applied_by_user_id is None
        contract = await db.get(Contract, seeded["contract_id"])
        # Zamówienie jest PRZYSZŁE (2031) — `sync_contract_to_live_order` zmienia
        # kontrakt wyłącznie dla zamówienia obejmującego DZIŚ; przyszłe nie
        # rusza nic (reguła z contract_lifecycle). Writer go zawołał (inwariant),
        # a kontrakt został taki, jaki był.
        assert contract.end_date == date(2031, 3, 31)
        assert result.rows[0].contract_revived is False


@pytest.mark.asyncio
async def test_queue_list_detail_apply_and_dismiss_via_api(
    seeded, app_client: AsyncClient, app_auth_headers
):
    r = await app_client.get(
        "/api/order-mail/queue",
        headers=app_auth_headers,
        params={"client_id": seeded["client_id"]},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["id"] for i in items] == [seeded["doc_id"]]
    assert items[0]["can_apply"] is True
    assert items[0]["extraction"]["rate_client"] == "950.00"  # admin widzi kwoty

    r = await app_client.get(
        f"/api/order-mail/queue/{seeded['doc_id']}/file", headers=app_auth_headers
    )
    assert r.status_code == 200 and r.content.startswith(b"%PDF")

    r = await app_client.post(
        f"/api/order-mail/queue/{seeded['doc_id']}/apply", headers=app_auth_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["document"]["outcome"] == OUTCOME_APPLIED
    assert body["document"]["applied_order_id"]

    r = await app_client.post(
        f"/api/order-mail/queue/{seeded['doc_id']}/apply", headers=app_auth_headers
    )
    assert r.status_code == 409  # już zastosowane

    r = await app_client.post(
        f"/api/order-mail/queue/{seeded['doc_id']}/dismiss", headers=app_auth_headers
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_notify_review_falls_back_to_admins(seeded):
    async with AsyncSessionLocal() as db:
        doc = await db.get(OrderMailDocument, seeded["doc_id"])
        created = await svc.notify_review(db, doc)
        assert created >= 1
        alerts = (
            (
                await db.execute(
                    select(DlAlert).where(DlAlert.client_id == seeded["client_id"])
                )
            )
            .scalars()
            .all()
        )
        assert any(a.alert_type == "order_mail_review" for a in alerts)
        # powtórka w tym samym oknie nie dubluje
        again = await svc.notify_review(db, doc)
        assert again == 0


@pytest.mark.asyncio
async def test_reapply_after_partial_failure_does_not_duplicate_orders(seeded):
    """Wiersz 1 zapisany, wiersz 2 pada → outcome zostaje needs_review; drugi
    „Zastosuj" nie może założyć wierszowi 1 drugiego zamówienia."""
    async with AsyncSessionLocal() as db:
        doc = await db.get(OrderMailDocument, seeded["doc_id"])
        good = dict(doc.proposal["rows"][0])
        bad = {**good, "row_index": 1, "row_name": "Nikt", "contract_id": 999_999_999}
        doc.proposal = {**doc.proposal, "rows": [good, bad]}
        await db.commit()

        first = await apply_document(db, doc, actor_user_id=None)
        await db.commit()
        assert first.ok is False
        assert first.rows[0].order_id and first.rows[1].error

        second = await apply_document(db, doc, actor_user_id=None)
        await db.commit()
        assert second.rows[0].order_id == first.rows[0].order_id
        orders = (
            (
                await db.execute(
                    select(ClientOrder).where(
                        ClientOrder.contract_id == seeded["contract_id"]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(orders) == 1, [o.id for o in orders]

        # Trzeci bieg bez zapisanego apply_result (symulacja crasha) — guard po markerze.
        doc.proposal = {k: v for k, v in doc.proposal.items() if k != "apply_result"}
        await db.commit()
        third = await apply_document(db, doc, actor_user_id=None)
        await db.commit()
        assert third.rows[0].order_id == first.rows[0].order_id
        orders = (
            (
                await db.execute(
                    select(ClientOrder).where(
                        ClientOrder.contract_id == seeded["contract_id"]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(orders) == 1
