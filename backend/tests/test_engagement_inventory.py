"""Tests for GET /api/admin/engagement-inventory (M5 plan PR-00).

Read-only raport anomalii lifecycle współpracy/kontraktu:
- auth: X-Snapshot-Token albo JWT admina; zwykły user → 403, brak auth → 401;
- shape: query_version/totals/summary/checks z count+sample+severity;
- fixtures wybranych klas anomalii są wykrywane w sample;
- endpoint NICZEGO nie mutuje (contract count przed == po);
- sample nie zawiera PII ani sekretów (identyfikatory numeryczne + numer
  dokumentu + data progu; nigdy nazwisko/email/telefon/token).

Rozłączność z M4: ten raport NIE dubluje pipeline-inventory (hired_no_contract
itd.) — patrzy na wewnętrzny stan kontraktu.

Uses in-process `app_client` / `app_auth_headers` fixtures (real postgres in CI).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import settings
from app.main import app

URL = "/api/admin/engagement-inventory"

_TODAY = date.today()
_PAST = _TODAY - timedelta(days=30)
_FUTURE = _TODAY + timedelta(days=30)


# ── Seed helpers (bezpośrednio przez ORM, osobna sesja jak w M4) ─────────────


async def _any_user_id() -> int:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        return (await db.execute(text("SELECT id FROM users LIMIT 1"))).scalar_one()


async def _seed_candidate() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Eng",
            lastname=f"Inv-{uuid.uuid4().hex[:6]}",
            email=f"eng-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_client() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"EngClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        return cli.id


async def _seed_job(client_id: int) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        j = Job(
            title=f"Eng-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus("published"),
            client_id=client_id,
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id


async def _seed_contract(**overrides) -> int:
    """Seed a Contract; sensible non-anomalous defaults unless overridden."""
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract, ContractStatus

    client_id = overrides.pop("client_id", None) or await _seed_client()
    candidate_id = overrides.pop("candidate_id", None) or await _seed_candidate()
    fields: dict = {
        "candidate_id": candidate_id,
        "client_id": client_id,
        "status": ContractStatus.active,
        "start_date": _PAST,
        "end_date": _FUTURE,
        "rate_candidate": Decimal("100.000"),
        "rate_client": Decimal("150.000"),
        # far-future scalar so a bare "active" contract does NOT trip
        # active_without_order_coverage by default
        "client_order_end_date": _FUTURE,
    }
    fields.update(overrides)
    async with AsyncSessionLocal() as db:
        c = Contract(**fields)
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_document(contract_id: int) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.contract_document import ContractDocument

    async with AsyncSessionLocal() as db:
        db.add(
            ContractDocument(
                contract_id=contract_id,
                filename="umowa.pdf",
                file_path=f"/tmp/{uuid.uuid4().hex}.pdf",
            )
        )
        await db.commit()


async def _seed_signature(
    contract_id: int,
    status_value: str,
    *,
    signed_document_url: str | None = None,
    stale_hours: int | None = None,
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.document_signature import DocumentSignature, SignatureStatus

    uid = await _any_user_id()
    async with AsyncSessionLocal() as db:
        s = DocumentSignature(
            contract_id=contract_id,
            status=SignatureStatus(status_value),
            provider="szafir_sdk",
            signer_email=f"signer-{uuid.uuid4().hex[:8]}@example.com",
            signer_first_name="Jan",
            signer_last_name="Testowy",
            sender_user_id=uid,
            signed_document_url=signed_document_url,
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)
        sig_id = s.id
    if stale_hours:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("UPDATE document_signatures SET created_at = :ts WHERE id = :sid"),
                {
                    "ts": datetime.now(timezone.utc) - timedelta(hours=stale_hours),
                    "sid": sig_id,
                },
            )
            await db.commit()
    return sig_id


async def _seed_signature_link(signature_id: int) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.signature_link import SignatureLink

    uid = await _any_user_id()
    async with AsyncSessionLocal() as db:
        db.add(
            SignatureLink(
                token=f"tok-{uuid.uuid4().hex}",
                signature_id=signature_id,
                party="company",
                purpose="sign",
                created_by=uid,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                revoked=False,
            )
        )
        await db.commit()


async def _seed_client_order(
    contract_id: int, client_id: int, end_date: date, status_value: str = "active"
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus

    async with AsyncSessionLocal() as db:
        db.add(
            ClientOrder(
                contract_id=contract_id,
                client_id=client_id,
                title=f"Order-{uuid.uuid4().hex[:6]}",
                status=ClientOrderStatus(status_value),
                start_date=_PAST,
                end_date=end_date,
            )
        )
        await db.commit()


async def _seed_equipment(contract_id: int) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.contract_equipment import (
        ContractEquipment,
        EquipmentItemType,
        EquipmentOwner,
        EquipmentReturnStatus,
    )

    async with AsyncSessionLocal() as db:
        e = ContractEquipment(
            contract_id=contract_id,
            item_type=EquipmentItemType.laptop,
            owner=EquipmentOwner.ours,
            handed_over_date=_PAST,
            return_status=EquipmentReturnStatus.pending,
        )
        db.add(e)
        await db.commit()
        await db.refresh(e)
        return e.id


async def _seed_candidate_rate(contract_id: int, effective_from: date) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.contract_candidate_rate import ContractCandidateRate

    async with AsyncSessionLocal() as db:
        db.add(
            ContractCandidateRate(
                contract_id=contract_id,
                rate=Decimal("100.000"),
                effective_from=effective_from,
            )
        )
        await db.commit()


async def _seed_b2b_generated(contract_number: str, year: int, seq: int) -> None:
    """Wstaw wiersz sentinelowy — IDEMPOTENTNIE.

    `b2b_generated_contracts` ma UNIQUE(year, seq), a wołający przekazuje tu
    stałą parę (rok 9999 to sentinel „dane testowe"). Bez usunięcia
    poprzednika drugi przebieg suite'u na tej samej bazie kończył się
    `UniqueViolationError` — czyli suite dawał się uruchomić dokładnie raz.
    W CI maskował to świeży kontener postgresa per job, więc widać to było
    tylko lokalnie.

    Kasowanie jest wąskie: dokładnie ta jedna para (year, seq), nigdy zakres.
    `contract_number` celowo NIE jest tu kluczem — nie ma na nim UNIQUE
    (patrz docstring modelu: legacy `seq` był licznikiem niezależnym od
    numeru), a duplikat numeru jest właśnie tym, co ten test bada.
    """
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(B2BGeneratedContract).where(
                B2BGeneratedContract.year == year,
                B2BGeneratedContract.seq == seq,
            )
        )
        db.add(
            B2BGeneratedContract(
                year=year,
                seq=seq,
                contract_number=contract_number,
            )
        )
        await db.commit()


async def _seed_invoice(contract_id: int, invoice_number: str) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.invoice import Invoice, InvoiceDirection, InvoiceStatus

    async with AsyncSessionLocal() as db:
        db.add(
            Invoice(
                contract_id=contract_id,
                direction=InvoiceDirection.to_client,
                invoice_number=invoice_number,
                issue_date=_TODAY,
                amount=1000,
                currency="PLN",
                status=InvoiceStatus.issued,
            )
        )
        await db.commit()


async def _contracts_count() -> int:
    """Policz WSZYSTKIE kontrakty.

    Pomiar globalny jest wiarygodny, dopóki suite backendu chodzi w JEDNYM
    procesie — a tak jest dziś (`ci.yml` woła pytest bez `-n`). Łapie wtedy
    zarówno dodanie, jak i skasowanie wiersza przez endpoint.

    Gdyby ktoś wprowadzał `pytest-xdist`: ta asercja jest jedną z tych, które
    się o to rozbijają. Przy WSPÓLNEJ bazie równoległy worker wstawiający
    własny kontrakt jest nieodróżnialny od endpointu mutującego dane i test
    zaczyna oskarżać endpoint o cudzy zapis (tak wywrócił się w CI 2026-08-07).
    Zawężenie do znacznika `MAX(id)` ratuje przebieg, ale kosztuje wykrywanie
    INSERT-u. Właściwym rozwiązaniem jest osobna baza per worker — wtedy ten
    licznik zostaje bez zmian. Patrz gałąź `xdist-per-worker-db-wip` i
    docs/ci-deploy-latency-completion-report.md.
    """
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        return (await db.execute(text("SELECT COUNT(*) FROM contracts"))).scalar_one()


def _check(report: dict, key: str) -> dict:
    matches = [c for c in report["checks"] if c["key"] == key]
    assert matches, f"check {key!r} missing from report"
    return matches[0]


def _contract_ids(check: dict) -> set[int]:
    return {row["contract_id"] for row in check["sample"] if "contract_id" in row}


def _signature_ids(check: dict) -> set[int]:
    return {row["signature_id"] for row in check["sample"] if "signature_id" in row}


_ALLOWED_SAMPLE_FIELDS = {
    "contract_id",
    "candidate_id",
    "client_id",
    "job_id",
    "order_id",
    "equipment_id",
    "signature_id",
    "invoice_id",
    "occurrences",
    "contract_number",
    "invoice_number",
    "effective_from",
}


# ── Auth ─────────────────────────────────────────────────────────────────────


async def test_inventory_requires_auth(app_client: AsyncClient):
    r = await app_client.get(URL)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_inventory_rejects_bad_token(monkeypatch):
    monkeypatch.setattr(settings, "SNAPSHOT_TOKEN", "engagement-good-token")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        r = await ac.get(URL, headers={"X-Snapshot-Token": "wrong"})
    assert r.status_code == 401


async def test_inventory_rejects_non_admin(app_client: AsyncClient):
    """Zwykły user (viewer) z ważnym JWT dostaje 403 — raport jest admin-only."""
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    email = f"eng-viewer-{uuid.uuid4().hex[:8]}@example.com"
    password = f"V13wer_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="Eng Viewer",
                role=UserRole.user,
                is_active=True,
            )
        )
        await db.commit()

    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    r = await app_client.get(URL, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


# ── Shape + anomaly fixtures + read-only guarantee ───────────────────────────


async def test_inventory_detects_anomalies_and_does_not_mutate(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.models.contract import ContractStatus, ContractTerminationReason

    client_id = await _seed_client()
    job_id = await _seed_job(client_id)

    # active bez dokumentu (ma job/rates/scalar → tylko ta klasa + brak order)
    c_nodoc = await _seed_contract(client_id=client_id, job_id=job_id)

    # active ze start w przyszłości (ma dokument)
    c_future = await _seed_contract(
        client_id=client_id, job_id=job_id, start_date=_FUTURE
    )
    await _seed_document(c_future)

    # ended z terminated_at w przyszłości (ma reason)
    c_futterm = await _seed_contract(
        status=ContractStatus.ended,
        terminated_at=_FUTURE,
        termination_reason=ContractTerminationReason.project_ended,
    )

    # active bez job
    c_nojob = await _seed_contract(client_id=client_id, job_id=None)
    await _seed_document(c_nojob)

    # active bez rate_candidate
    c_norate = await _seed_contract(
        client_id=client_id, job_id=job_id, rate_candidate=None
    )
    await _seed_document(c_norate)

    # active bez pokrycia zamówieniem (scalar NULL, brak client_orders)
    c_noorder = await _seed_contract(
        client_id=client_id, job_id=job_id, client_order_end_date=None
    )
    await _seed_document(c_noorder)

    # legacy_order_date_drift: scalar ≠ max(order.end_date), z aktywnym orderem
    c_drift = await _seed_contract(
        client_id=client_id, job_id=job_id, client_order_end_date=_FUTURE
    )
    await _seed_document(c_drift)
    await _seed_client_order(c_drift, client_id, end_date=_FUTURE + timedelta(days=10))

    # rate_schedule_same_date_dup: dwa wiersze candidate rate na tę samą datę
    c_ratedup = await _seed_contract(client_id=client_id, job_id=job_id)
    await _seed_document(c_ratedup)
    await _seed_candidate_rate(c_ratedup, date(2026, 1, 1))
    await _seed_candidate_rate(c_ratedup, date(2026, 1, 1))

    # ended bez reason
    c_noreason = await _seed_contract(status=ContractStatus.ended, terminated_at=_PAST)

    # draft + completed signature bez artefaktu → signed_without_activation
    #   + completed_signature_without_artifact
    c_draft = await _seed_contract(status=ContractStatus.draft)
    sig_completed = await _seed_signature(c_draft, "completed")

    # completed signature na terminalu + aktywny link → orphan_active_signature_link
    await _seed_signature_link(sig_completed)

    # stuck signature (sent, >24h)
    c_stuck = await _seed_contract(client_id=client_id, job_id=job_id)
    await _seed_document(c_stuck)
    sig_stuck = await _seed_signature(c_stuck, "sent", stale_hours=48)

    # ended + wydany sprzęt nierozliczony
    c_asset = await _seed_contract(status=ContractStatus.ended, terminated_at=_PAST)
    await _seed_equipment(c_asset)

    # duplicate b2b contract number
    dup_num = f"TEST-{uuid.uuid4().hex[:6]}/9999"
    await _seed_b2b_generated(dup_num, 9999, 1)
    await _seed_b2b_generated(dup_num, 9999, 2)

    # duplicate invoice number
    dup_inv = f"DUP-{uuid.uuid4().hex[:8]}"
    c_inv = await _seed_contract(client_id=client_id, job_id=job_id)
    await _seed_invoice(c_inv, dup_inv)
    await _seed_invoice(c_inv, dup_inv)

    rows_before = await _contracts_count()
    r = await app_client.get(URL, headers=app_auth_headers)
    assert r.status_code == 200, r.text
    report = r.json()
    assert await _contracts_count() == rows_before, "endpoint zmutował dane!"

    # Shape
    assert report["query_version"].startswith("m5-pr00")
    assert report["module"] == "m5-engagement"
    assert report["auth_mode"] == "jwt"
    assert report["sample_limit"] == 20
    assert set(report["summary"]) == {
        "checks_total",
        "checks_failed",
        "anomalies_p0",
        "anomalies_p1",
        "anomalies_p2",
    }
    assert report["summary"]["checks_failed"] == 0, [
        c for c in report["checks"] if c.get("error")
    ]
    assert report["totals"]["contracts_total"] >= 10
    for check in report["checks"]:
        assert check["severity"] in {"P0", "P1", "P2"}
        assert isinstance(check["count"], int)
        assert len(check["sample"]) <= report["sample_limit"]
        assert check["elapsed_ms"] >= 0
        for row in check["sample"]:
            for field in row:
                assert field in _ALLOWED_SAMPLE_FIELDS, (
                    f"nieoczekiwane pole {field!r} w sample {check['key']}"
                )

    # Anomaly detection (obecność w odpowiednim checku; nakładki są naturalne)
    assert c_nodoc in _contract_ids(_check(report, "active_without_document"))
    assert c_future in _contract_ids(_check(report, "active_before_start_date"))
    assert c_futterm in _contract_ids(_check(report, "future_termination_marked_ended"))
    assert c_nojob in _contract_ids(_check(report, "active_without_job"))
    assert c_norate in _contract_ids(_check(report, "active_without_rates"))
    assert c_noorder in _contract_ids(_check(report, "active_without_order_coverage"))
    assert c_drift in _contract_ids(_check(report, "legacy_order_date_drift"))
    assert c_ratedup in _contract_ids(_check(report, "rate_schedule_same_date_dup"))
    assert c_noreason in _contract_ids(_check(report, "ended_without_reason"))
    assert sig_completed in _signature_ids(_check(report, "signed_without_activation"))
    assert sig_completed in _signature_ids(
        _check(report, "completed_signature_without_artifact")
    )
    assert sig_completed in _signature_ids(
        _check(report, "orphan_active_signature_link")
    )
    assert sig_stuck in _signature_ids(_check(report, "stuck_signature"))
    assert c_asset in _contract_ids(_check(report, "ended_with_assigned_equipment"))

    dupnum_check = _check(report, "duplicate_contract_number")
    assert dup_num in {row.get("contract_number") for row in dupnum_check["sample"]}
    dupinv_check = _check(report, "duplicate_invoice_number")
    assert dup_inv in {row.get("invoice_number") for row in dupinv_check["sample"]}

    # A well-formed contract with document/rates/job/coverage must NOT surface
    # in the P0 document/start checks.
    assert c_future not in _contract_ids(_check(report, "active_without_document"))
    assert c_nodoc not in _contract_ids(_check(report, "active_before_start_date"))


async def test_inventory_is_repeatable(app_client: AsyncClient, app_auth_headers):
    """Dwa wywołania: ta sama wersja zapytań i te same countery (bez mutacji)."""
    r1 = await app_client.get(URL, headers=app_auth_headers)
    r2 = await app_client.get(URL, headers=app_auth_headers)
    assert r1.status_code == 200 and r2.status_code == 200
    a, b = r1.json(), r2.json()
    assert a["query_version"] == b["query_version"]
    counts_a = {c["key"]: c["count"] for c in a["checks"]}
    counts_b = {c["key"]: c["count"] for c in b["checks"]}
    assert counts_a == counts_b
