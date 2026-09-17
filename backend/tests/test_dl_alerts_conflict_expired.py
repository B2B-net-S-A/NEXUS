"""Alert DL „konflikt z kandydatem wygasł" (``candidate_conflict_expired``).

Jednorazowa karta dla konfliktu, którego ``expires_at`` minął w ostatnich 7
dniach. Wiersz konfliktu zostaje ``active`` (historia), skaner go nie przełącza.
Baza testowa jest wspólna — każdy test zakłada własnego klienta, DL i kandydata
i czyta alerty wyłącznie po własnych identyfikatorach.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.models.client import Client
from app.models.dl_alert import (
    ALERT_CANDIDATE_CONFLICT_EXPIRED,
    DL_ALERT_SECTION_BY_TYPE,
    DL_ALERT_SECTION_ENDING,
    DL_ALERT_TYPE_LABELS,
    DlAlert,
)
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.tasks.dl_alerts_scanner import rule_candidate_conflict_expired


def _hex() -> str:
    return uuid.uuid4().hex[:8]


async def _seed(
    *,
    expires_delta: timedelta | None,
    active: bool = True,
    with_dl: bool = True,
    lastname: str | None = None,
) -> dict:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Wygasly-Klient-{_hex()}")
        candidate = Candidate(
            name="Jan",
            lastname=lastname or f"Wygasly-{_hex()}",
            email=f"expired-{_hex()}@example.com",
        )
        db.add_all([client, candidate])
        await db.flush()
        dl_id = None
        if with_dl:
            dl = User(
                email=f"expired-dl-{_hex()}@example.com",
                password_hash=hash_password(f"T3st_{_hex()}!PassX"),
                name="DL Konflikty",
                role=UserRole.delivery_lead,
                roles=[UserRole.delivery_lead.value],
                is_active=True,
                profile_completed=True,
            )
            db.add(dl)
            await db.flush()
            db.add(
                DeliveryLeadClientAssignment(
                    client_id=client.id, delivery_lead_user_id=dl.id
                )
            )
            dl_id = dl.id
        conflict = CandidateConflict(
            candidate_id=candidate.id,
            client_id=client.id,
            type=ConflictType.nda,
            active=active,
            expires_at=(
                None
                if expires_delta is None
                else datetime.now(timezone.utc) + expires_delta
            ),
        )
        db.add(conflict)
        await db.commit()
        return {
            "client_id": client.id,
            "client_name": client.name,
            "candidate_id": candidate.id,
            "lastname": candidate.lastname,
            "conflict_id": conflict.id,
            "dl_id": dl_id,
        }


async def _run() -> None:
    async with AsyncSessionLocal() as db:
        await rule_candidate_conflict_expired(db)
        await db.commit()


async def _alerts(client_id: int) -> list[DlAlert]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(DlAlert)
                    .where(
                        DlAlert.client_id == client_id,
                        DlAlert.alert_type == ALERT_CANDIDATE_CONFLICT_EXPIRED,
                    )
                    .order_by(DlAlert.id)
                )
            ).all()
        )


def test_type_is_registered_with_label_and_ending_section():
    assert DL_ALERT_TYPE_LABELS[ALERT_CANDIDATE_CONFLICT_EXPIRED] == (
        "Konflikt z kandydatem wygasł"
    )
    assert (
        DL_ALERT_SECTION_BY_TYPE[ALERT_CANDIDATE_CONFLICT_EXPIRED]
        == DL_ALERT_SECTION_ENDING
    )


async def test_recently_expired_conflict_gives_one_card_without_pii():
    seed = await _seed(expires_delta=timedelta(hours=-3))
    await _run()

    alerts = await _alerts(seed["client_id"])
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.user_id == seed["dl_id"]
    assert alert.title == f"{seed['client_name']} — wygasł konflikt: NDA / cooling-off"
    assert "ponownie proponować" in alert.message
    assert alert.link == f"/candidates/{seed['candidate_id']}"
    assert alert.event_key == (
        f"{ALERT_CANDIDATE_CONFLICT_EXPIRED}:conflict:{seed['conflict_id']}:"
        f"{seed['dl_id']}"
    )
    assert set(alert.payload) == {
        "conflict_id",
        "candidate_id",
        "conflict_type",
        "expires_at",
    }
    for text in (alert.title, alert.message, str(alert.payload)):
        assert seed["lastname"] not in text

    # Skaner nie przełącza konfliktu — stan „wygasły" liczy odczyt.
    async with AsyncSessionLocal() as db:
        conflict = await db.get(CandidateConflict, seed["conflict_id"])
        assert conflict.active is True
        assert conflict.state_at() == "expired"


async def test_second_run_is_idempotent():
    seed = await _seed(expires_delta=timedelta(days=-1))
    await _run()
    await _run()
    assert len(await _alerts(seed["client_id"])) == 1


async def test_expiry_older_than_seven_days_is_ignored():
    seed = await _seed(expires_delta=timedelta(days=-10))
    await _run()
    assert await _alerts(seed["client_id"]) == []


async def test_future_expiry_and_no_expiry_are_ignored():
    future = await _seed(expires_delta=timedelta(days=2))
    forever = await _seed(expires_delta=None)
    await _run()
    assert await _alerts(future["client_id"]) == []
    assert await _alerts(forever["client_id"]) == []


async def test_deactivated_conflict_is_ignored():
    seed = await _seed(expires_delta=timedelta(hours=-2), active=False)
    await _run()
    assert await _alerts(seed["client_id"]) == []


async def test_client_without_delivery_lead_gets_no_card():
    seed = await _seed(expires_delta=timedelta(hours=-2), with_dl=False)
    await _run()
    assert await _alerts(seed["client_id"]) == []
