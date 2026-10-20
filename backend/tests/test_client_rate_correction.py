"""Zmiana stawki do klienta po wysyłce CV (20.10.2026, wariant A).

Reguła: ``app/services/client_rate_correction.py``. Delivery Lead zmienia
stawkę z powodem, historia pokazuje kwotę wysyłki i zmiany po niej, a po
zamówieniu na tę parę zapis stoi (409) — stawkę zmienia się w zamówieniu.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.client_rate_correction import (
    AuditRow,
    RateValue,
    SentRow,
    build_history,
    note_content,
    rate_label,
)

T0 = datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)
R150 = RateValue(150.0, "hourly", "PLN")
R145 = RateValue(145.0, "hourly", "PLN")
R140 = RateValue(140.0, "hourly", "PLN")


# ── Składanie historii (bez bazy) ───────────────────────────────────────────


def test_rate_label_is_short_and_polish() -> None:
    assert rate_label(R150) == "150 zł/h"
    assert rate_label(RateValue(152.5, "daily", "PLN")) == "152.5 zł/dzień"
    assert rate_label(RateValue(30000.0, "monthly", "EUR")) == "30000 EUR/mies."
    assert rate_label(None) == "brak stawki"


def test_without_changes_the_sent_rate_is_the_current_one() -> None:
    out = build_history(
        sent=SentRow(at=T0, by_name="Ewa"), audits=[], current=R150, note_texts={}
    )
    assert out["sent"]["label"] == "150 zł/h"
    assert out["sent"]["by_name"] == "Ewa"
    assert out["changes"] == []


def test_sent_rate_comes_from_the_first_change_after_sending() -> None:
    audits = [
        AuditRow(T0 + timedelta(days=3), "Ewa", R145, R140, "other", None),
        AuditRow(T0 + timedelta(days=1), "Ewa", R150, R145, "client_negotiated", 7),
    ]
    text = note_content(R150, R145, "client_negotiated", "zszedł po drugiej rozmowie")
    out = build_history(
        sent=SentRow(at=T0, by_name="Ewa"),
        audits=audits,
        current=R140,
        note_texts={7: text},
    )
    assert out["sent"]["label"] == "150 zł/h"
    assert [c["new_label"] for c in out["changes"]] == ["140 zł/h", "145 zł/h"]
    newest, oldest = out["changes"]
    assert newest["reason_label"] == "Inny powód"
    assert oldest["reason_label"] == "Klient wynegocjował inną stawkę"
    # Historia pokazuje słowa DL-a, bez zdania o kwotach z notatki.
    assert oldest["note"] == "zszedł po drugiej rozmowie"


def test_changes_before_sending_are_not_history_after_sending() -> None:
    before = AuditRow(T0 - timedelta(hours=1), "Ewa", None, R150, None, None)
    out = build_history(
        sent=SentRow(at=T0, by_name="Ewa"), audits=[before], current=R150, note_texts={}
    )
    assert out["changes"] == []
    assert out["sent"]["label"] == "150 zł/h"


def test_old_change_without_reason_still_shows() -> None:
    legacy = AuditRow(T0 + timedelta(days=1), "Ewa", R150, R145, None, None)
    out = build_history(
        sent=SentRow(at=T0, by_name="Ewa"), audits=[legacy], current=R145, note_texts={}
    )
    assert out["changes"][0]["reason"] is None
    assert out["changes"][0]["reason_label"] is None
    assert out["changes"][0]["old_label"] == "150 zł/h"


def test_note_without_own_words_shows_nothing_extra() -> None:
    row = AuditRow(T0 + timedelta(days=1), "Ewa", R150, R145, "send_mistake", 9)
    out = build_history(
        sent=SentRow(at=T0, by_name="Ewa"),
        audits=[row],
        current=R145,
        note_texts={9: note_content(R150, R145, "send_mistake", "  ")},
    )
    assert out["changes"][0]["note"] is None


# ── Ścieżka HTTP ────────────────────────────────────────────────────────────


async def _login(app_client: AsyncClient, role: UserRole) -> dict[str, str]:
    from app.core.security import hash_password

    unique = uuid.uuid4().hex[:8]
    email = f"crc-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Crc"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Crc {role.value}",
                role=role,
                roles=[role.value],
                is_active=True,
            )
        )
        await db.commit()
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed(*, with_order: bool = False) -> tuple[int, int]:
    """Para z CV wysłanym za 190 zł/h i późniejszym wierszem rozmowy bez stawki."""

    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
    from app.models.job import Job, JobStatus

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"CrcClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.flush()
        job = Job(
            title=f"Crc-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
        )
        cand = Candidate(
            name="Crc",
            lastname=f"Osoba-{uuid.uuid4().hex[:6]}",
            email=f"crc-{uuid.uuid4().hex[:8]}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([job, cand])
        await db.flush()
        db.add_all(
            [
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job.id,
                    stage=PipelineStage.cv_sent,
                    moved_at=now - timedelta(days=2),
                    client_rate_value=Decimal("190"),
                    client_rate_unit="hourly",
                    client_rate_currency="PLN",
                ),
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job.id,
                    stage=PipelineStage.client_interview,
                    moved_at=now - timedelta(days=1),
                ),
            ]
        )
        if with_order:
            contract = Contract(
                candidate_id=cand.id,
                client_id=cli.id,
                job_id=job.id,
                contract_type=ContractType.b2b,
                status=ContractStatus.active,
                start_date=date(2033, 11, 1),
                rate_candidate=Decimal("140"),
                rate_client=Decimal("190"),
                rate_unit=RateUnit.hourly,
            )
            db.add(contract)
            await db.flush()
            db.add(
                ClientOrder(
                    client_id=cli.id,
                    contract_id=contract.id,
                    job_id=job.id,
                    title="Zamówienie Crc",
                    status=ClientOrderStatus.active,
                    start_date=date(2033, 11, 1),
                    rate_client=Decimal("190"),
                    rate_unit=RateUnit.hourly,
                )
            )
        await db.commit()
        return job.id, cand.id


async def test_delivery_lead_changes_the_rate_with_a_reason_after_sending(
    app_client: AsyncClient,
) -> None:
    headers = await _login(app_client, UserRole.delivery_lead)
    job_id, cand_id = await _seed()
    base = f"/api/candidates/{cand_id}/recruitments/{job_id}/client-rate"

    saved = await app_client.patch(
        base,
        json={
            "rate_value": 180,
            "rate_unit": "hourly",
            "reason": "client_negotiated",
            "note": "Klient zszedł po drugiej rozmowie",
        },
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["client_rate"]["value"] == 180.0

    history = await app_client.get(f"{base}/history", headers=headers)
    assert history.status_code == 200, history.text
    body = history.json()
    assert body["current_label"] == "180 zł/h"
    # Wiersz rozmowy nie miał stawki — „było” to kwota wysyłki, nie pustka.
    assert body["sent"]["label"] == "190 zł/h"
    [change] = body["changes"]
    assert change["old_label"] == "190 zł/h"
    assert change["reason"] == "client_negotiated"
    assert change["note"] == "Klient zszedł po drugiej rozmowie"
    assert body["order_lock"] is None
    assert body["can_write"] is True

    notes = await app_client.get(
        "/api/notes", params={"candidate_id": cand_id}, headers=headers
    )
    assert notes.status_code == 200, notes.text
    assert "190 zł/h → 180 zł/h" in notes.text


async def test_note_without_a_reason_is_refused(app_client: AsyncClient) -> None:
    headers = await _login(app_client, UserRole.delivery_lead)
    job_id, cand_id = await _seed()
    resp = await app_client.patch(
        f"/api/candidates/{cand_id}/recruitments/{job_id}/client-rate",
        json={"rate_value": 180, "rate_unit": "hourly", "note": "bez powodu"},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


async def test_order_locks_the_rate_in_the_recruitment(app_client: AsyncClient) -> None:
    headers = await _login(app_client, UserRole.delivery_lead)
    job_id, cand_id = await _seed(with_order=True)
    base = f"/api/candidates/{cand_id}/recruitments/{job_id}/client-rate"

    history = await app_client.get(f"{base}/history", headers=headers)
    assert history.status_code == 200, history.text
    body = history.json()
    assert body["order_lock"]["title"] == "Zamówienie Crc"
    assert body["order_lock"]["rate_client"] == 190.0
    assert body["can_write"] is False

    resp = await app_client.patch(
        base,
        json={"rate_value": 180, "rate_unit": "hourly", "reason": "client_negotiated"},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    assert "zmień w zamówieniu" in resp.json()["detail"]


async def test_recruiter_does_not_read_the_rate_history(
    app_client: AsyncClient,
) -> None:
    headers = await _login(app_client, UserRole.recruiter)
    job_id, cand_id = await _seed()
    resp = await app_client.get(
        f"/api/candidates/{cand_id}/recruitments/{job_id}/client-rate/history",
        headers=headers,
    )
    assert resp.status_code == 403, resp.text
