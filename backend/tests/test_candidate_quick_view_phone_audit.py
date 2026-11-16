"""Karta kontaktu na telefonie (`/podglad/kandydat/{id}`) zostawia ślad.

Decyzja Artura z 14.11.2026: na telefonie wolno znaleźć numer kandydata, ale
każde otwarcie karty zapisuje się w historii kandydata. Karta czyta
`GET /api/candidates/{id}/quick-view?via=phone`; ta sama trasa bez `via`
(szybki podgląd na laptopie) niczego nie zapisuje.

Uses the in-process `app_client` / `app_auth_headers` fixtures from conftest
(real postgres in CI).
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select


async def _seed_candidate() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Tel",
            lastname=f"Test-{uuid.uuid4().hex[:6]}",
            email=f"tel-{uuid.uuid4().hex[:8]}@example.com",
            phone="+48 600 100 200",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _audit_rows(candidate_id: int) -> list:
    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.services import candidate_audit

    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(Activity).where(
                        Activity.entity_type == "candidate",
                        Activity.entity_id == candidate_id,
                        Activity.action == candidate_audit.CONTACT_VIEWED_ON_PHONE,
                    )
                )
            )
            .scalars()
            .all()
        )


async def test_phone_card_records_who_opened_it(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id = await _seed_candidate()

    r = await app_client.get(
        f"/api/candidates/{candidate_id}/quick-view",
        params={"via": "phone"},
        headers=app_auth_headers,
    )

    assert r.status_code == 200, r.text
    assert r.json()["candidate"]["phone"] == "+48 600 100 200"
    (row,) = await _audit_rows(candidate_id)
    assert row.user_id is not None
    # Dziennik bez danych osobowych: same identyfikatory i kanał.
    assert row.details == {"via": "phone"}


async def test_laptop_quick_view_records_nothing(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id = await _seed_candidate()

    r = await app_client.get(
        f"/api/candidates/{candidate_id}/quick-view", headers=app_auth_headers
    )

    assert r.status_code == 200, r.text
    assert await _audit_rows(candidate_id) == []


async def test_unknown_channel_is_rejected(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id = await _seed_candidate()

    r = await app_client.get(
        f"/api/candidates/{candidate_id}/quick-view",
        params={"via": "tablet"},
        headers=app_auth_headers,
    )

    assert r.status_code == 422
    assert await _audit_rows(candidate_id) == []


async def test_card_survives_failed_audit_write(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Awaria dziennika nie odbiera karty (przegląd bezpieczeństwa 14.11.2026).

    `rollback()` wygasza obiekty sesji, więc zapis przed złożeniem odpowiedzi
    kończył się 500 przy pierwszym odczycie atrybutu kandydata.
    """
    from app.services import candidate_audit

    def boom(*_args, **_kwargs):
        raise RuntimeError("dziennik niedostępny")

    monkeypatch.setattr(candidate_audit, "record_candidate_audit", boom)
    candidate_id = await _seed_candidate()

    r = await app_client.get(
        f"/api/candidates/{candidate_id}/quick-view",
        params={"via": "phone"},
        headers=app_auth_headers,
    )

    assert r.status_code == 200, r.text
    assert r.json()["candidate"]["phone"] == "+48 600 100 200"
    assert await _audit_rows(candidate_id) == []
