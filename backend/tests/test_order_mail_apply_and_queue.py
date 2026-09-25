"""Writer zamówień z maila + kolejka (API) — end-to-end na bazie.

Seed: klient z NIP-em, kandydat z aktywnym kontraktem i stawką kosztową
(bez niej zamówienie nie aktywuje się — `rate_candidate` NIGDY z PDF-a),
dokument z planem `new`. Sprawdzamy: zamówienie powstało i jest aktywne,
PDF przypięty, `sync_contract_to_live_order` zadziałał, kolejka daje TCM
bezpieczny odczyt i odcina Head of Recruitment na granicy Delivery.
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
from app.core.security import hash_password
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
from app.models.user import User, UserRole
from app.services import order_mail_ingest as svc
from app.services import storage_service
from app.services.order_mail_apply import apply_document

RUN = uuid.uuid4().hex[:8]


async def _headers_for_role(app_client: AsyncClient, role: UserRole) -> dict[str, str]:
    tag = uuid.uuid4().hex[:8]
    email = f"order-mail-{role.value}-{tag}@example.com"
    password = f"P4ss_{tag}!"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Order Mail {role.value}",
                role=role,
                roles=[role.value],
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


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
        doc.identification_reason = "NIP 1234567890 znaleziony w dokumencie"
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
        assert order.rate_client == Decimal(
            "950.00"
        ) and order.rate_candidate == Decimal("700")
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
async def test_tcm_gets_safe_order_mail_read_and_hor_is_section_denied(
    seeded, app_client: AsyncClient
):
    async with AsyncSessionLocal() as db:
        doc = await db.get(OrderMailDocument, seeded["doc_id"])
        doc.identification_reason = "NIP z dokumentu wskazuje klienta Bank Apply"
        doc.gate_reasons = ["Stawka 950 odbiega od obowiązującej 700"]
        doc.error = "Nie udało się zapisać stawki 950"
        doc.extraction = {
            **doc.extraction,
            "uncertain": True,
            "uncertain_reasons": ["Stawka 950 wymaga kontroli"],
            "consultant_rows": [
                {
                    **doc.extraction["consultant_rows"][0],
                    "rate_client_gross": "1168.50",
                    "uncertain_reason": "Stawka 950 wymaga kontroli",
                }
            ],
        }
        await db.commit()

    tcm_headers = await _headers_for_role(app_client, UserRole.talent_community_manager)
    response = await app_client.get(
        f"/api/order-mail/queue/{seeded['doc_id']}", headers=tcm_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["extraction"]["rate_client"] is None
    assert body["extraction"]["consultant_rows"][0]["rate_client"] is None
    assert body["extraction"]["consultant_rows"][0]["rate_client_gross"] is None
    assert body["extraction"]["uncertain_reasons"] == [
        "Sprawdź odczytane dane przed zapisem."
    ]
    assert body["extraction"]["consultant_rows"][0]["uncertain_reason"] == (
        "Sprawdź odczytane dane przed zapisem."
    )
    assert body["gate_reasons"] == ["Sprawdź odczytane dane przed zapisem."]
    assert body["identification_reason"] == "Klient rozpoznany automatycznie."
    assert body["error"] == "Przetwarzanie dokumentu zakończyło się błędem."
    assert body["has_file"] is False
    assert body["can_apply"] is False

    file_response = await app_client.get(
        f"/api/order-mail/queue/{seeded['doc_id']}/file", headers=tcm_headers
    )
    assert file_response.status_code == 403
    apply_response = await app_client.post(
        f"/api/order-mail/queue/{seeded['doc_id']}/apply", headers=tcm_headers
    )
    assert apply_response.status_code == 403
    assert apply_response.json()["detail"]["code"] == "section_access_denied"

    hor_headers = await _headers_for_role(app_client, UserRole.head_of_recruitment)
    denied = await app_client.get(
        f"/api/order-mail/queue/{seeded['doc_id']}", headers=hor_headers
    )
    assert denied.status_code == 403


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
async def test_stale_proposal_is_replanned_and_reapply_does_not_duplicate_orders(
    seeded,
):
    """Stale targets are discarded; retries never duplicate the current source row."""
    async with AsyncSessionLocal() as db:
        doc = await db.get(OrderMailDocument, seeded["doc_id"])
        good = dict(doc.proposal["rows"][0])
        bad = {**good, "row_index": 1, "row_name": "Nikt", "contract_id": 999_999_999}
        doc.proposal = {**doc.proposal, "rows": [good, bad]}
        await db.commit()

        first = await apply_document(db, doc, actor_user_id=None)
        await db.commit()
        assert first.ok is True
        assert len(first.rows) == 1 and first.rows[0].order_id

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


@pytest.mark.asyncio
async def test_refresh_plan_uses_saved_pdf_without_writing_orders(
    seeded, app_client, monkeypatch
):
    from app.services.order_document_text import OrderDocumentText

    monkeypatch.setattr(svc.settings, "ORDER_MAIL_AUTOAPPLY_ENABLED", True)
    monkeypatch.setattr(
        svc,
        "extract_order_text",
        lambda *args: OrderDocumentText(
            text="Stawka brutto za jeden dzień świadczenia usług: 950,00 PLN",
            page_count=1,
            ocr_used=False,
            ocr_capped=False,
            reextracted_with=None,
            letter_spacing_ratio=0.0,
        ),
    )
    headers = await _headers_for_role(app_client, UserRole.admin)
    before = (
        await app_client.get(
            f"/api/order-mail/queue/{seeded['doc_id']}", headers=headers
        )
    ).json()
    response = await app_client.post(
        f"/api/order-mail/queue/{seeded['doc_id']}/refresh-plan", headers=headers
    )
    assert response.status_code == 200, response.text
    after = response.json()
    assert after["client_id"] == before["client_id"]
    assert after["extraction"]["title"] == before["extraction"]["title"]
    assert after["outcome"] == "needs_review"
    assert after["applied_order_id"] is None
    assert after["proposal"]["rows"][0]["rate_client"] == "772.36"
    assert after["proposal"]["rows"][0]["action"] != "skip"
    again = await app_client.post(
        f"/api/order-mail/queue/{seeded['doc_id']}/refresh-plan", headers=headers
    )
    assert again.status_code == 200
    assert again.json()["proposal"]["rows"][0]["rate_client"] == "772.36"
    async with AsyncSessionLocal() as db:
        assert (
            await db.execute(
                select(ClientOrder).where(
                    ClientOrder.contract_id == seeded["contract_id"]
                )
            )
        ).scalars().all() == []


@pytest.mark.asyncio
async def test_refresh_plan_rejects_read_only_roles_and_partially_applied_document(
    seeded, app_client
):
    for role in (UserRole.finance, UserRole.talent_community_manager):
        headers = await _headers_for_role(app_client, role)
        response = await app_client.post(
            f"/api/order-mail/queue/{seeded['doc_id']}/refresh-plan", headers=headers
        )
        assert response.status_code == 403
    async with AsyncSessionLocal() as db:
        doc = await db.get(OrderMailDocument, seeded["doc_id"])
        doc.proposal = {
            **doc.proposal,
            "apply_result": {"rows": [{"row_index": 0, "order_id": 42}]},
        }
        await db.commit()
    headers = await _headers_for_role(app_client, UserRole.admin)
    response = await app_client.post(
        f"/api/order-mail/queue/{seeded['doc_id']}/refresh-plan", headers=headers
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_refresh_rechecks_rights_after_client_change_and_rolls_back(
    seeded, app_client, monkeypatch
):
    from tests.test_order_extract_endpoint import _dl_headers

    headers = await _dl_headers(app_client, seeded["client_id"])
    async with AsyncSessionLocal() as db:
        other = Client(name=f"Other refresh {uuid.uuid4().hex}")
        db.add(other)
        await db.commit()
        other_id = other.id

    async def move_plan(db, doc):
        doc.client_id = other_id
        # Nawet autoflush wykonany przez planer nie może utrwalić zmiany,
        # gdy użytkownik nie ma prawa do klienta docelowego.
        await db.flush()

    # Przycisk i przeliczenie po zmianie reguły idą przez jedną funkcję
    # (``svc.replan_and_apply``), więc podmiana siedzi w module ingest.
    monkeypatch.setattr(svc, "refresh_review_plan", move_plan)
    response = await app_client.post(
        f"/api/order-mail/queue/{seeded['doc_id']}/refresh-plan", headers=headers
    )
    assert response.status_code == 403, response.text
    async with AsyncSessionLocal() as db:
        doc = await db.get(OrderMailDocument, seeded["doc_id"])
        assert doc.client_id == seeded["client_id"]
        assert doc.applied_order_id is None


@pytest.mark.asyncio
async def test_refresh_auto_verdict_applies_without_another_click(
    seeded, app_client, monkeypatch
):
    from app.services import order_mail_apply
    from app.services.order_mail_apply import ApplyResult, AppliedRow

    async def certain(db, doc):
        doc.gate_verdict = "auto"
        doc.gate_reasons = []

    calls = []

    async def write(db, doc, *, actor_user_id, confirmed_by_human):
        calls.append((actor_user_id, confirmed_by_human))
        return ApplyResult(rows=[AppliedRow(row_index=0, action="new")])

    monkeypatch.setattr(svc, "refresh_review_plan", certain)
    monkeypatch.setattr(order_mail_apply, "apply_document", write)
    headers = await _headers_for_role(app_client, UserRole.admin)
    me = await app_client.get("/api/auth/me", headers=headers)
    response = await app_client.post(
        f"/api/order-mail/queue/{seeded['doc_id']}/refresh-plan", headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "auto_applied"
    # Aktor do atrybucji, ale bez zatwierdzenia planu (imiennik, dopasowanie
    # niedokładne) — to dalej zapis automatu.
    assert calls == [(me.json()["id"], False)]


@pytest.mark.asyncio
async def test_refresh_auto_verdict_waits_in_queue_when_autoapply_is_off(
    seeded, app_client, monkeypatch
):
    """Wyłącznik automatu obejmuje też „Przelicz plan" (zapis bez aktora).

    Ręczne „Zastosuj" flagi nie czyta — człowiek nadal zapisuje zamówienie.
    """
    from unittest.mock import AsyncMock

    from app.services import order_mail_apply

    async def certain(db, doc):
        doc.gate_verdict = "auto"
        doc.gate_reasons = []

    write = AsyncMock()
    monkeypatch.setattr(svc, "refresh_review_plan", certain)
    monkeypatch.setattr(order_mail_apply, "apply_document", write)
    monkeypatch.setattr(svc.settings, "ORDER_MAIL_AUTOAPPLY_ENABLED", False)
    headers = await _headers_for_role(app_client, UserRole.admin)
    response = await app_client.post(
        f"/api/order-mail/queue/{seeded['doc_id']}/refresh-plan", headers=headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == OUTCOME_NEEDS_REVIEW
    assert body["gate_verdict"] == "review"
    assert body["gate_reasons"] == [svc.AUTOAPPLY_DISABLED_REASON]
    assert body["applied_order_id"] is None
    write.assert_not_awaited()

    # Prawdziwy writer, flaga nadal wyłączona.
    monkeypatch.setattr(order_mail_apply, "apply_document", apply_document)
    manual = await app_client.post(
        f"/api/order-mail/queue/{seeded['doc_id']}/apply", headers=headers
    )
    assert manual.status_code == 200, manual.text
    assert manual.json()["ok"] is True
    assert manual.json()["document"]["outcome"] == OUTCOME_APPLIED


# ── Audyt 22.09, druga runda ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_manual_apply_keeps_the_document_currency(seeded):
    """FIN-MAIL-02: waluta z dokumentu idzie na zamówienie, nie waluta kontraktu."""
    async with AsyncSessionLocal() as db:
        doc = await db.get(OrderMailDocument, seeded["doc_id"])
        doc.extraction = {**doc.extraction, "currency": "EUR"}
        doc.proposal = {
            **doc.proposal,
            "rows": [{**doc.proposal["rows"][0], "currency": "EUR"}],
        }
        await db.flush()
        result = await apply_document(db, doc, actor_user_id=None)
        assert result.ok, result.as_dict()
        order = await db.get(ClientOrder, result.rows[0].order_id)
        assert order.rate_client_currency == "EUR"
        await db.rollback()


@pytest.mark.asyncio
async def test_refresh_applies_client_rules_to_a_document_recognized_late(
    seeded, monkeypatch
):
    """FIN-MAIL-05: dokument rozpoznany dopiero przy recheku przechodzi reguły.

    Odczyt powstał, zanim znano klienta, więc reguły klienta nie zadziałały.
    Przeliczenie stosuje je deterministycznie (bez modelu), zapisuje nazwę
    reguły, a bramka dostaje wyłącznie reguły faktycznie zastosowane.
    """
    from types import SimpleNamespace

    from app.services.order_document_text import OrderDocumentText

    def ruled(result, ctx):
        result.title = "RULED/1"
        result.confidence["title"] = 1.0
        return result

    policy = SimpleNamespace(
        key="stub_late",
        display_name="Stub Late",
        order=1,
        requires_target=False,
        suppressed_by=frozenset(),
        apply=ruled,
        rate_rules=None,
        rule_version="v1",
        table_authoritative=False,
        reapply_on_refresh=False,
        extract_rows=None,
        open_ended_period=False,
        document_period_authoritative=False,
    )
    monkeypatch.setattr(svc, "active_policies", lambda client_id: [policy])
    monkeypatch.setattr(
        svc,
        "extract_order_text",
        lambda *_a: OrderDocumentText("tekst", 1, False, False, None, 0.0),
    )
    seen: dict = {}

    async def plan_and_gate(db, row, extraction, doc, policies, client_id, method):
        seen["title"] = extraction.title
        seen["applied"] = svc._applied_policy_names(row)

    monkeypatch.setattr(svc, "_plan_and_gate", plan_and_gate)
    async with AsyncSessionLocal() as db:
        doc = await db.get(OrderMailDocument, seeded["doc_id"])
        doc.client_policy = None
        doc.document_meta = {"policies_pending": True}
        await svc.refresh_review_plan(db, doc)
        assert seen == {"title": "RULED/1", "applied": ("Stub Late",)}
        assert doc.client_policy == "Stub Late"
        assert "policies_pending" not in (doc.document_meta or {})
        await db.rollback()


@pytest.mark.asyncio
async def test_locked_queue_read_sees_the_state_after_the_lock(seeded):
    """FIN-MAIL-08: blokada czyta stan z bazy, nie z mapy tożsamości sesji."""
    from app.api.order_mail_queue import _load_visible

    admin = User(email="lock@example.com", name="Lock", role=UserRole.admin)
    admin.roles = [UserRole.admin.value]
    async with AsyncSessionLocal() as db:
        stale = await _load_visible(db, seeded["doc_id"], admin)
        assert stale.outcome == OUTCOME_NEEDS_REVIEW
        async with AsyncSessionLocal() as other:
            fresh = await other.get(OrderMailDocument, seeded["doc_id"])
            fresh.outcome = "dismissed"
            await other.commit()
        locked = await _load_visible(db, seeded["doc_id"], admin, for_update=True)
        assert locked.outcome == "dismissed"
        await db.rollback()


# ── Audyt 24.09, blok B ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_pdf_on_disk_is_404_and_hides_the_file_actions(
    seeded, app_client: AsyncClient
):
    """N1: skasowany plik dawał 500 (helper magazynu rzuca FileNotFoundError)
    w pobraniu i w „Przelicz plan", a kolejka dalej pokazywała przycisk PDF."""
    headers = await _headers_for_role(app_client, UserRole.admin)
    async with AsyncSessionLocal() as db:
        doc = await db.get(OrderMailDocument, seeded["doc_id"])
        storage_service.get_order_mail_attachment_path(doc.storage_path).unlink()

    detail = await app_client.get(
        f"/api/order-mail/queue/{seeded['doc_id']}", headers=headers
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["has_file"] is False

    download = await app_client.get(
        f"/api/order-mail/queue/{seeded['doc_id']}/file", headers=headers
    )
    assert download.status_code == 404
    assert "nie istnieje na dysku" in download.json()["detail"]

    refresh = await app_client.post(
        f"/api/order-mail/queue/{seeded['doc_id']}/refresh-plan", headers=headers
    )
    assert refresh.status_code == 404
    assert "nie istnieje na dysku" in refresh.json()["detail"]


@pytest.mark.asyncio
async def test_admin_can_dismiss_an_unrecognized_document(
    seeded, app_client: AsyncClient
):
    """N2: „Nierozpoznane" nie dało się odrzucić — dokument wisiał na zawsze."""
    from app.models.order_mail import OUTCOME_DISMISSED, OUTCOME_UNRECOGNIZED

    async with AsyncSessionLocal() as db:
        doc = await db.get(OrderMailDocument, seeded["doc_id"])
        doc.outcome = OUTCOME_UNRECOGNIZED
        doc.client_id = None
        await db.commit()

    finance = await _headers_for_role(app_client, UserRole.finance)
    refused = await app_client.post(
        f"/api/order-mail/queue/{seeded['doc_id']}/dismiss", headers=finance
    )
    assert refused.status_code == 403

    admin = await _headers_for_role(app_client, UserRole.admin)
    detail = await app_client.get(
        f"/api/order-mail/queue/{seeded['doc_id']}", headers=admin
    )
    assert detail.json()["can_dismiss"] is True
    assert detail.json()["can_apply"] is False
    dismissed = await app_client.post(
        f"/api/order-mail/queue/{seeded['doc_id']}/dismiss", headers=admin
    )
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()["outcome"] == OUTCOME_DISMISSED
    assert dismissed.json()["can_dismiss"] is False


@pytest.mark.asyncio
async def test_failed_entry_can_be_dismissed_and_says_whether_it_is_retried(
    seeded, app_client: AsyncClient
):
    """Runda 2 audytu 25.09: wpis „Nieudane” nie dawał się zdjąć z listy, a
    kolejka obiecywała ponowienia także wpisom, których system nie weźmie."""
    from app.models.order_mail import OUTCOME_DISMISSED, OUTCOME_FAILED

    admin = await _headers_for_role(app_client, UserRole.admin)
    async with AsyncSessionLocal() as db:
        doc = await db.get(OrderMailDocument, seeded["doc_id"])
        doc.outcome = OUTCOME_FAILED
        doc.received_at = datetime.now(timezone.utc)
        doc.document_meta = None
        await db.commit()

    fresh = await app_client.get(
        f"/api/order-mail/queue/{seeded['doc_id']}", headers=admin
    )
    assert fresh.status_code == 200, fresh.text
    assert fresh.json()["failed_retry_pending"] is True
    assert fresh.json()["can_dismiss"] is True

    # Brak pliku (np. Graph nie zwrócił treści) — ponowień nie będzie.
    async with AsyncSessionLocal() as db:
        doc = await db.get(OrderMailDocument, seeded["doc_id"])
        doc.storage_path = None
        doc.client_id = None
        await db.commit()
    no_file = await app_client.get(
        f"/api/order-mail/queue/{seeded['doc_id']}", headers=admin
    )
    assert no_file.json()["failed_retry_pending"] is False

    finance = await _headers_for_role(app_client, UserRole.finance)
    refused = await app_client.post(
        f"/api/order-mail/queue/{seeded['doc_id']}/dismiss", headers=finance
    )
    assert refused.status_code == 403

    dismissed = await app_client.post(
        f"/api/order-mail/queue/{seeded['doc_id']}/dismiss", headers=admin
    )
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()["outcome"] == OUTCOME_DISMISSED
    assert dismissed.json()["failed_retry_pending"] is False


# ── Audyt 24.09.2026: stawka bez jednostki ───────────────────────────────────


@pytest.mark.asyncio
async def test_manual_apply_refuses_rate_without_unit_instead_of_contract_unit(
    seeded,
):
    """Wiersz z własną stawką (inną niż dokument) bez jednostki: planer zostawia
    jednostkę pustą, a writer brał jednostkę kontraktu — 1200 zł za MD mogło się
    zapisać jako 1200 zł/h. Ręczne „Zastosuj" odmawia z prośbą o jednostkę."""
    async with AsyncSessionLocal() as db:
        doc = await db.get(OrderMailDocument, seeded["doc_id"])
        # `apply_document` liczy plan od nowa z odczytu, więc brak jednostki
        # musi być w ODCZYCIE: osoba z inną stawką niż dokument, bez jednostki.
        row = doc.extraction["consultant_rows"][0]
        doc.extraction = {
            **doc.extraction,
            "consultant_rows": [{**row, "rate_client": "1200.00", "rate_unit": None}],
        }
        await db.flush()
        result = await apply_document(db, doc, actor_user_id=None)
        # Odmowa pada w writerze (wiersz z błędem) albo już przy przeliczeniu
        # planu (błąd dokumentu) — w obu przypadkach nic się nie zapisuje.
        assert not result.ok
        if result.rows:
            assert "nie ma jednostki" in (result.rows[0].error or "")
            assert result.rows[0].order_id is None
        else:
            assert result.error
        orders = (
            await db.scalars(
                select(ClientOrder).where(
                    ClientOrder.contract_id == seeded["contract_id"]
                )
            )
        ).all()
        assert orders == []
        await db.rollback()
