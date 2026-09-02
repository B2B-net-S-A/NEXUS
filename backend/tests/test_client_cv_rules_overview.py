"""Reguły CV per klient — „każdy Delivery Lead robi sobie reguły".

Do 09.2026 ``GET /api/settings/cv-rules`` zwracało wyłącznie 14 zasianych
szablonów Championa, a ekran w Ustawieniach był podglądem bez żadnej akcji.
Backend od początku wpuszczał Delivery Leada do zapisu (``TacPlus``), więc
„DL nie może robić reguł" było usterką POWIERZCHNI, nie uprawnień — ale jedną
regułę dawało się założyć tylko przez okno „Edytuj firmę", a zapis i
zatwierdzenie były dwoma osobnymi kliknięciami.

Ten plik dowodzi trzech rzeczy, które ekran zarządzania zakłada, a które
łatwo cofnąć „przy okazji":

1. Delivery Lead zakłada i zatwierdza regułę JEDNYM zapisem (``confirm=true``)
   i to dla DOWOLNEGO klienta — także spoza swojego portfela. To lustro
   ``PATCH /api/clients/{id}`` (też ``TacPlus``, też bez scope'u): reguła CV
   jest konfiguracją klienta jak jego karta. Filtr „moi klienci" jest wygodą
   interfejsu, nie granicą.
2. Przegląd zbiorczy pokazuje KAŻDĄ regułę, nie tylko zasiane — reguła
   założona ręcznie ma ``seed_key = NULL`` i musi być na liście, inaczej jest
   niewidoczna dla wszystkich poza autorem. Szablony bez wiersza idą osobno.
3. Domyślny zapis nadal jest propozycją, a edycja bez ``confirm`` ZDEJMUJE
   zatwierdzenie — zmiana wzoru nie wchodzi na produkcję bez decyzji.
   Role spoza ``DeliveryLeadPlus`` (TAC, HoR, finance, recruiter, sourcer)
   czytają przegląd, ale nie zapisują. TAC celowo poza zapisem (decyzja
   produktowa 02.09.2026): kartę klienta edytuje, reguł CV nie prowadzi.
4. ``generator_instructions`` przechodzi zapis → odczyt → przegląd i wchodzi
   do ``client_policy`` — to jedyne pole reguły, które trafia do promptu,
   więc jego zgubienie po drodze byłoby niewidoczne aż do wygenerowanego CV.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

OVERVIEW_URL = "/api/settings/cv-rules"


def _rule_url(client_id: int) -> str:
    return f"/api/clients/{client_id}/cv-rule"


async def _headers_for(
    app_client: AsyncClient,
    role_value: str,
    *,
    assigned_client_id: int | None = None,
) -> dict[str, str]:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole

    email = f"cvrules-{role_value}-{uuid.uuid4().hex[:8]}@example.com"
    password = f"P4ss_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        role = UserRole(role_value)
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"CV rules {role_value}",
            role=role,
            roles=[role.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.flush()
        if assigned_client_id is not None and role is UserRole.delivery_lead:
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=user.id,
                    client_id=assigned_client_id,
                )
            )
        await db.commit()

    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _make_client(name: str) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client, ClientStatus

    async with AsyncSessionLocal() as db:
        row = Client(name=name, status=ClientStatus.active, hidden=False)
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def _cleanup(client_ids: list[int]) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.client_cv_rule import ClientCvRule
    from app.models.team_structure import DeliveryLeadClientAssignment

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ClientCvRule).where(ClientCvRule.client_id.in_(client_ids))
        )
        await db.execute(
            delete(DeliveryLeadClientAssignment).where(
                DeliveryLeadClientAssignment.client_id.in_(client_ids)
            )
        )
        await db.execute(delete(Client).where(Client.id.in_(client_ids)))
        await db.commit()


async def _rule_is_active_in_db(client_id: int) -> bool:
    from app.core.database import AsyncSessionLocal
    from app.models.client_cv_rule import ClientCvRule

    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(ClientCvRule).where(ClientCvRule.client_id == client_id)
            )
        ).scalar_one()
        return row.confirmed_at is not None


@pytest.mark.asyncio
async def test_delivery_lead_creates_and_confirms_rule_for_any_client_in_one_save(
    app_client: AsyncClient,
):
    """DL: jeden zapis = reguła obowiązuje; klient spoza portfela też przechodzi;
    przegląd zbiorczy widzi regułę bez ``seed_key``."""
    tag = uuid.uuid4().hex[:6]
    mine = await _make_client(f"CV rules portfolio {tag}")
    other = await _make_client(f"CV rules outside {tag}")
    try:
        headers = await _headers_for(
            app_client, "delivery_lead", assigned_client_id=mine
        )

        # Klient SPOZA portfela DL — bramka jest lustrem PATCH /api/clients/{id}.
        r = await app_client.put(
            _rule_url(other),
            json={
                "filename_pattern": "B2B_{STANOWISKO}_{IMIE_NAZWISKO}",
                "spaces_to_underscores": True,
                "cv_language": "pl",
                "notes": "Maks. 3 rekomendacje na stanowisko.",
                "generator_instructions": "  Bez sekcji zainteresowań.  ",
                "confirm": True,
            },
            headers=headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["is_active"] is True, "confirm=true musi zatwierdzać w tym samym zapisie"
        assert body["confirmed_at"] is not None
        assert body["confirmed_by_name"] == "CV rules delivery_lead"
        assert body["generator_instructions"] == "Bez sekcji zainteresowań."
        assert body["client_policy"] == (
            "nazwa pliku, język PL, instrukcje dla generatora"
        )
        assert body["filename_preview"] == "B2B_Analityk_Biznesowy_Jan_Kowalski.docx"
        assert await _rule_is_active_in_db(other) is True

        # Generator czyta wyłącznie zatwierdzone reguły — to jest ta sama
        # ścieżka, więc reguła z jednego zapisu musi być dla niego widoczna.
        from app.core.database import AsyncSessionLocal
        from app.services.cv_generator_b2b.client_rules import resolve_client_rule

        async with AsyncSessionLocal() as db:
            found = await resolve_client_rule(db, other)
            assert found is not None and found.cv_language == "pl"
            assert found.generator_instructions == "Bez sekcji zainteresowań."

        # Przegląd zbiorczy: reguła założona ręcznie (bez seed_key) JEST na
        # liście, z nazwą klienta i autorem zatwierdzenia.
        r = await app_client.get(OVERVIEW_URL, headers=headers)
        assert r.status_code == 200, r.text
        overview = r.json()
        assert set(overview) == {"rules", "unassigned_templates"}
        by_client = {row["client_id"]: row for row in overview["rules"]}
        assert other in by_client, "ręcznie założona reguła musi być w przeglądzie"
        row = by_client[other]
        assert row["seed_key"] is None
        assert row["template_label"] is None
        assert row["client_name"] == f"CV rules outside {tag}"
        assert row["is_active"] is True
        assert row["confirmed_by_name"] == "CV rules delivery_lead"
        assert row["notes"] == "Maks. 3 rekomendacje na stanowisko."
        assert row["generator_instructions"] == "Bez sekcji zainteresowań."

        # Szablony bez wiersza idą osobno, a suma obu list pokrywa DOKŁADNIE
        # 14 kluczy seeda — bez duplikatów i bez dziur.
        from app.api.client_cv_rules import CHAMPION_SEED_KEYS

        seeded_keys = {r["seed_key"] for r in overview["rules"] if r["seed_key"]}
        unassigned_keys = {t["seed_key"] for t in overview["unassigned_templates"]}
        assert seeded_keys.isdisjoint(unassigned_keys)
        assert seeded_keys | unassigned_keys == {k for k, _ in CHAMPION_SEED_KEYS}
        for template in overview["unassigned_templates"]:
            assert set(template) == {"seed_key", "label", "template_url"}
    finally:
        await _cleanup([mine, other])


@pytest.mark.asyncio
async def test_default_save_is_a_proposal_and_editing_drops_confirmation(
    app_client: AsyncClient,
):
    """Bez ``confirm`` zapis zostaje propozycją; edycja obowiązującej reguły
    bez ``confirm`` zdejmuje zatwierdzenie — zmiana wzoru nie wchodzi na
    produkcję bez decyzji."""
    client_id = await _make_client(f"CV rules proposal {uuid.uuid4().hex[:6]}")
    try:
        headers = await _headers_for(app_client, "delivery_lead")

        r = await app_client.put(
            _rule_url(client_id),
            json={"filename_pattern": "B2B_{IMIE_NAZWISKO}"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["is_active"] is False
        assert r.json()["client_policy"] == ""  # wiersz jest, ale nie obowiązuje

        r = await app_client.post(f"{_rule_url(client_id)}/confirm", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["is_active"] is True

        r = await app_client.put(
            _rule_url(client_id),
            json={"filename_pattern": "B2B_{STANOWISKO}_{IMIE_NAZWISKO}"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["is_active"] is False, (
            "edycja bez confirm musi zdejmować zatwierdzenie"
        )
        assert await _rule_is_active_in_db(client_id) is False

        r = await app_client.delete(_rule_url(client_id), headers=headers)
        assert r.status_code == 204, r.text
        r = await app_client.get(_rule_url(client_id), headers=headers)
        assert r.status_code == 200
        assert r.json()["client_policy"] is None, "po DELETE nie ma wiersza"
    finally:
        await _cleanup([client_id])


@pytest.mark.parametrize(
    "role_value", ["tac", "head_of_recruitment", "finance", "recruiter", "sourcer"]
)
@pytest.mark.asyncio
async def test_roles_outside_delivery_lead_plus_read_the_overview_but_cannot_write(
    app_client: AsyncClient, role_value: str
):
    """Odczyt = każda rola operacyjna (``OperationalUser``); zapis, zatwierdzenie
    i usunięcie = ``DeliveryLeadPlus``. TAC CELOWO poza zapisem (decyzja
    02.09.2026) mimo że kartę klienta edytuje; HoR jak przy karcie klienta."""
    client_id = await _make_client(f"CV rules ro {role_value} {uuid.uuid4().hex[:6]}")
    try:
        headers = await _headers_for(app_client, role_value)

        r = await app_client.get(OVERVIEW_URL, headers=headers)
        assert r.status_code == 200, f"{role_value} GET overview → {r.status_code}"

        r = await app_client.put(
            _rule_url(client_id),
            json={"filename_pattern": "B2B_{IMIE_NAZWISKO}", "confirm": True},
            headers=headers,
        )
        assert r.status_code == 403, f"{role_value} PUT → {r.status_code}: {r.text}"
        r = await app_client.post(f"{_rule_url(client_id)}/confirm", headers=headers)
        assert r.status_code == 403, f"{role_value} confirm → {r.status_code}"
        r = await app_client.delete(_rule_url(client_id), headers=headers)
        assert r.status_code == 403, f"{role_value} DELETE → {r.status_code}"
    finally:
        await _cleanup([client_id])
