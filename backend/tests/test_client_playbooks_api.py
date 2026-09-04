"""Karta klienta (`client_playbooks`, migracja 0272) — kontrakty API.

Każdy test dowodzi jednego kontraktu, który łatwo cofnąć „przy okazji":

1. GET bez wiersza to pusta karta (`exists=false`), nigdy 404 — 404 jest
   wyłącznie dla nieistniejącego KLIENTA.
2. Zapis zmieniający treść bumpuje ``version`` i zostawia wpis ``saved``
   z DIFFEM pól; identyczna treść nie bumpuje i nie zostawia wpisu.
3. Odczyt karty i przeglądu jest org-wide dla ról operacyjnych (karta
   zastępuje wzory Word czytane w Pomocy przez każdego); zapis i historia
   wymagają sekcji Delivery, a każdy DL może zarządzać każdym klientem.
4. ``off_limits`` z umowy ramowej jedzie tylko do ról z odczytem sekcji
   Delivery.
5. Seed w repo (14 kart) i lustro DDL/seeda w ``entrypoint.sh`` są spójne
   z migracją — prod alembic jest osierocony, więc lustro jest wdrożeniem.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

URL = "/api/clients/{cid}/playbook"
OVERVIEW_URL = "/api/settings/client-playbooks"
BACKEND_ROOT = Path(__file__).resolve().parents[1]


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

    email = f"playbook-{role_value}-{uuid.uuid4().hex[:8]}@example.com"
    password = f"P4ss_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        role = UserRole(role_value)
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Playbook {role_value}",
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


async def _make_client(
    name: str,
    *,
    display_name: str | None = None,
    hidden: bool = False,
    merged_into_client_id: int | None = None,
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client, ClientStatus

    async with AsyncSessionLocal() as db:
        row = Client(
            name=name,
            display_name=display_name,
            status=ClientStatus.active,
            hidden=hidden,
            merged_into_client_id=merged_into_client_id,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def _cleanup(client_ids: list[int]) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.client_contract_terms import ClientContractTerms
    from app.models.client_playbook import ClientPlaybook
    from app.models.client_playbook_event import ClientPlaybookEvent
    from app.models.team_structure import DeliveryLeadClientAssignment

    async with AsyncSessionLocal() as db:
        for model in (
            ClientPlaybookEvent,
            ClientPlaybook,
            ClientContractTerms,
            DeliveryLeadClientAssignment,
        ):
            await db.execute(delete(model).where(model.client_id.in_(client_ids)))
        await db.execute(delete(Client).where(Client.id.in_(client_ids)))
        await db.commit()


def _full_payload(**overrides) -> dict:
    payload = {
        "sla_business_days": 5,
        "sla_min_candidates": 3,
        "cv_limit_per_process": 3,
        "hold_hours": 48,
        "multi_project_cooldown_days": 30,
        "rate_policy": "Stawka ustalana per projekt",
        "about_for_candidate": "Bank z 5 mln klientów.",
        "priority_rules": "Bankowość w pierwszej kolejności.",
        "process_rules_md": "## Proces\n1. CV w 5 dni",
        "onboarding_md": "## Onboarding\n- KRK",
        "documents": [{"name": "KRK", "url": "https://sp.example/krk"}],
    }
    payload.update(overrides)
    return payload


def _unique(label: str) -> str:
    return f"{label} {uuid.uuid4().hex[:6]}"


# ── Odczyt ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_without_row_returns_empty_card_not_404(app_client: AsyncClient):
    cid = await _make_client(_unique("Playbook empty"), display_name="Pusty Bank")
    try:
        headers = await _headers_for(app_client, "recruiter")
        r = await app_client.get(URL.format(cid=cid), headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["exists"] is False
        assert body["version"] == 0
        assert body["documents"] == []
        assert body["off_limits"] is None
        assert body["client_name"] == "Pusty Bank"
    finally:
        await _cleanup([cid])


@pytest.mark.asyncio
async def test_get_unknown_client_is_404(app_client: AsyncClient):
    headers = await _headers_for(app_client, "recruiter")
    r = await app_client.get(URL.format(cid=999_999_999), headers=headers)
    assert r.status_code == 404
    assert r.json()["detail"] == "Klient nie został znaleziony."


# ── Zapis i wersjonowanie ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_creates_row_with_version_one_and_saved_event(
    app_client: AsyncClient,
):
    cid = await _make_client(_unique("Playbook v1"))
    try:
        headers = await _headers_for(
            app_client, "delivery_lead", assigned_client_id=cid
        )
        r = await app_client.put(
            URL.format(cid=cid), json=_full_payload(), headers=headers
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["exists"] is True
        assert body["version"] == 1
        assert body["sla_business_days"] == 5
        assert body["documents"] == [{"name": "KRK", "url": "https://sp.example/krk"}]
        assert body["updated_by_name"] == "Playbook delivery_lead"

        h = await app_client.get(URL.format(cid=cid) + "/history", headers=headers)
        assert h.status_code == 200, h.text
        events = h.json()
        assert len(events) == 1
        assert events[0]["action"] == "saved"
        assert events[0]["playbook_version"] == 1
        assert events[0]["changes"]["sla_business_days"] == {"from": None, "to": 5}
        assert events[0]["changes"]["documents"]["from"] == []
    finally:
        await _cleanup([cid])


@pytest.mark.asyncio
async def test_put_identical_payload_does_not_bump_version_or_add_event(
    app_client: AsyncClient,
):
    cid = await _make_client(_unique("Playbook idem"))
    try:
        headers = await _headers_for(
            app_client, "delivery_lead", assigned_client_id=cid
        )
        first = await app_client.put(
            URL.format(cid=cid), json=_full_payload(), headers=headers
        )
        assert first.status_code == 200, first.text
        second = await app_client.put(
            URL.format(cid=cid), json=_full_payload(), headers=headers
        )
        assert second.status_code == 200, second.text
        assert second.json()["version"] == 1
        h = await app_client.get(URL.format(cid=cid) + "/history", headers=headers)
        assert len(h.json()) == 1
    finally:
        await _cleanup([cid])


@pytest.mark.asyncio
async def test_put_change_bumps_version_and_records_only_changed_fields(
    app_client: AsyncClient,
):
    cid = await _make_client(_unique("Playbook diff"))
    try:
        headers = await _headers_for(
            app_client, "delivery_lead", assigned_client_id=cid
        )
        await app_client.put(URL.format(cid=cid), json=_full_payload(), headers=headers)
        changed = _full_payload(
            cv_limit_per_process=2,
            documents=[
                {"name": "KRK", "url": "https://sp.example/krk"},
                {"name": "NDA", "url": "https://sp.example/nda"},
            ],
        )
        r = await app_client.put(URL.format(cid=cid), json=changed, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["version"] == 2

        h = await app_client.get(URL.format(cid=cid) + "/history", headers=headers)
        latest = h.json()[0]
        assert latest["playbook_version"] == 2
        assert set(latest["changes"]) == {"cv_limit_per_process", "documents"}
        assert latest["changes"]["cv_limit_per_process"] == {"from": 3, "to": 2}
    finally:
        await _cleanup([cid])


@pytest.mark.asyncio
async def test_put_blank_strings_become_null(app_client: AsyncClient):
    cid = await _make_client(_unique("Playbook blank"))
    try:
        headers = await _headers_for(
            app_client, "delivery_lead", assigned_client_id=cid
        )
        r = await app_client.put(
            URL.format(cid=cid),
            json=_full_payload(rate_policy="   ", onboarding_md=""),
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["rate_policy"] is None
        assert r.json()["onboarding_md"] is None
    finally:
        await _cleanup([cid])


@pytest.mark.asyncio
async def test_put_rejects_out_of_range_numbers_and_bad_document_urls(
    app_client: AsyncClient,
):
    cid = await _make_client(_unique("Playbook 422"))
    try:
        headers = await _headers_for(
            app_client, "delivery_lead", assigned_client_id=cid
        )
        for bad in (
            _full_payload(sla_business_days=400),
            _full_payload(hold_hours=0),
            _full_payload(documents=[{"name": "XSS", "url": "javascript:alert(1)"}]),
            _full_payload(
                documents=[
                    {"name": f"D{i}", "url": f"https://sp.example/d{i}"}
                    for i in range(51)
                ]
            ),
        ):
            r = await app_client.put(URL.format(cid=cid), json=bad, headers=headers)
            assert r.status_code == 422, (bad, r.text)
        # Nic nie powstało po odrzuconych zapisach.
        g = await app_client.get(URL.format(cid=cid), headers=headers)
        assert g.json()["exists"] is False
    finally:
        await _cleanup([cid])


# ── Uprawnienia ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_needs_delivery_section_write_read_is_operational(
    app_client: AsyncClient,
):
    """Zapis = sekcja Delivery (write); odczyt karty i przeglądu = każda rola operacyjna."""
    cid = await _make_client(_unique("Playbook roles"))
    try:
        for role in ("tac", "recruiter", "head_of_recruitment"):
            headers = await _headers_for(app_client, role)
            r = await app_client.put(
                URL.format(cid=cid), json=_full_payload(), headers=headers
            )
            assert r.status_code == 403, (role, r.text)

        admin = await _headers_for(app_client, "admin")
        r = await app_client.put(
            URL.format(cid=cid), json=_full_payload(), headers=admin
        )
        assert r.status_code == 200, r.text

        tac = await _headers_for(app_client, "tac")
        h = await app_client.get(URL.format(cid=cid) + "/history", headers=tac)
        assert h.status_code == 403, h.text

        recruiter = await _headers_for(app_client, "recruiter")
        g = await app_client.get(URL.format(cid=cid), headers=recruiter)
        assert g.status_code == 200, g.text
        assert g.json()["exists"] is True
        o = await app_client.get(OVERVIEW_URL, headers=recruiter)
        assert o.status_code == 200, o.text
        assert cid in {item["client_id"] for item in o.json()["items"]}
    finally:
        await _cleanup([cid])


@pytest.mark.asyncio
async def test_delivery_lead_writes_for_all_clients(
    app_client: AsyncClient,
):
    cid = await _make_client(_unique("Playbook portfolio"))
    try:
        stranger = await _headers_for(app_client, "delivery_lead")
        r = await app_client.put(
            URL.format(cid=cid), json=_full_payload(), headers=stranger
        )
        assert r.status_code == 200, r.text
        stranger_history = await app_client.get(
            URL.format(cid=cid) + "/history", headers=stranger
        )
        assert stranger_history.status_code == 200, stranger_history.text

        owner = await _headers_for(app_client, "delivery_lead", assigned_client_id=cid)
        r = await app_client.put(
            URL.format(cid=cid), json=_full_payload(), headers=owner
        )
        assert r.status_code == 200, r.text
        h = await app_client.get(URL.format(cid=cid) + "/history", headers=owner)
        assert h.status_code == 200, h.text

        admin = await _headers_for(app_client, "admin")
        r = await app_client.put(
            URL.format(cid=cid),
            json=_full_payload(rate_policy="Admin nadpisał"),
            headers=admin,
        )
        assert r.status_code == 200, r.text
        assert r.json()["version"] == 2
    finally:
        await _cleanup([cid])


@pytest.mark.asyncio
async def test_off_limits_only_for_delivery_readers(app_client: AsyncClient):
    from app.core.database import AsyncSessionLocal
    from app.models.client_contract_terms import ClientContractTerms

    cid = await _make_client(_unique("Playbook offlimit"))
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                ClientContractTerms(
                    client_id=cid, off_limits_months=12, off_limits_scope="cały bank"
                )
            )
            await db.commit()

        owner = await _headers_for(app_client, "delivery_lead", assigned_client_id=cid)
        r = await app_client.put(
            URL.format(cid=cid), json=_full_payload(), headers=owner
        )
        assert r.status_code == 200, r.text
        assert r.json()["off_limits"] == {
            "months": 12,
            "scope": "cały bank",
            "notes": None,
        }
        g = await app_client.get(URL.format(cid=cid), headers=owner)
        assert g.json()["off_limits"]["months"] == 12

        recruiter = await _headers_for(app_client, "recruiter")
        g = await app_client.get(URL.format(cid=cid), headers=recruiter)
        assert g.status_code == 200, g.text
        assert g.json()["off_limits"] is None
        o = await app_client.get(OVERVIEW_URL, headers=recruiter)
        mine = [i for i in o.json()["items"] if i["client_id"] == cid]
        assert mine and mine[0]["off_limits"] is None

        # Zapis karty nie dotyka warunków umowy.
        async with AsyncSessionLocal() as db:
            terms = (
                await db.execute(
                    select(ClientContractTerms).where(
                        ClientContractTerms.client_id == cid
                    )
                )
            ).scalar_one()
            assert terms.off_limits_months == 12
    finally:
        await _cleanup([cid])


@pytest.mark.asyncio
async def test_version_continues_after_row_is_recreated(app_client: AsyncClient):
    from app.core.database import AsyncSessionLocal
    from app.models.client_playbook import ClientPlaybook

    cid = await _make_client(_unique("Playbook recreate"))
    try:
        owner = await _headers_for(app_client, "delivery_lead", assigned_client_id=cid)
        r = await app_client.put(
            URL.format(cid=cid), json=_full_payload(), headers=owner
        )
        assert r.json()["version"] == 1
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(ClientPlaybook).where(ClientPlaybook.client_id == cid)
            )
            await db.commit()
        r = await app_client.put(
            URL.format(cid=cid), json=_full_payload(), headers=owner
        )
        assert r.status_code == 200, r.text
        assert r.json()["version"] == 2
    finally:
        await _cleanup([cid])


# ── Backfill z seeda ────────────────────────────────────────────────────────

SEED_URL = "/api/clients/{cid}/playbook/seed"
# Wpis z documents + kompletem liczb — dobre pokrycie mapowania seed → payload.
SEED_KEY = "profil-championa-wzor-pansa-docx"


@pytest.mark.asyncio
async def test_seed_backfill_creates_card_with_seed_key_and_event(
    app_client: AsyncClient,
):
    """Backfill zakłada kartę z GOTOWEJ treści seeda: pola z pliku, `seed_key`
    ustawiony (proweniencja), wpis historii `seeded` (odróżnia od ręcznego)."""
    cid = await _make_client(_unique("Playbook seed"))
    try:
        headers = await _headers_for(
            app_client, "delivery_lead", assigned_client_id=cid
        )
        r = await app_client.post(
            SEED_URL.format(cid=cid), json={"seed_key": SEED_KEY}, headers=headers
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["exists"] is True
        assert body["version"] == 1
        assert body["seed_key"] == SEED_KEY
        assert body["sla_business_days"] == 5
        assert body["cv_limit_per_process"] == 3
        assert len(body["documents"]) == 2

        h = await app_client.get(URL.format(cid=cid) + "/history", headers=headers)
        assert h.status_code == 200, h.text
        assert h.json()[0]["action"] == "seeded"
        assert h.json()[0]["playbook_version"] == 1
    finally:
        await _cleanup([cid])


@pytest.mark.asyncio
async def test_seed_backfill_does_not_overwrite_existing_card(app_client: AsyncClient):
    """Karta istnieje → 409; decyzja człowieka wygrywa z seedem (jak automatyczny
    ``ON CONFLICT DO NOTHING``)."""
    cid = await _make_client(_unique("Playbook seed dup"))
    try:
        headers = await _headers_for(
            app_client, "delivery_lead", assigned_client_id=cid
        )
        first = await app_client.post(
            SEED_URL.format(cid=cid), json={"seed_key": SEED_KEY}, headers=headers
        )
        assert first.status_code == 200, first.text
        again = await app_client.post(
            SEED_URL.format(cid=cid), json={"seed_key": SEED_KEY}, headers=headers
        )
        assert again.status_code == 409, again.text
    finally:
        await _cleanup([cid])


@pytest.mark.asyncio
async def test_seed_backfill_unknown_seed_key_is_400_and_creates_nothing(
    app_client: AsyncClient,
):
    cid = await _make_client(_unique("Playbook seed 400"))
    try:
        headers = await _headers_for(
            app_client, "delivery_lead", assigned_client_id=cid
        )
        r = await app_client.post(
            SEED_URL.format(cid=cid),
            json={"seed_key": "nie-ma-takiego-szablonu"},
            headers=headers,
        )
        assert r.status_code == 400, r.text
        g = await app_client.get(URL.format(cid=cid), headers=headers)
        assert g.json()["exists"] is False
    finally:
        await _cleanup([cid])


@pytest.mark.asyncio
async def test_seed_backfill_unknown_client_is_404(app_client: AsyncClient):
    headers = await _headers_for(app_client, "admin")
    r = await app_client.post(
        SEED_URL.format(cid=999_999_999),
        json={"seed_key": SEED_KEY},
        headers=headers,
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_seed_backfill_needs_delivery_write_same_as_put(app_client: AsyncClient):
    """Ta sama bramka co PUT: role bez Delivery → 403; każdy DL i admin → 200."""
    cid = await _make_client(_unique("Playbook seed authz"))
    admin_cid = await _make_client(_unique("Playbook seed admin authz"))
    try:
        for role in ("tac", "recruiter", "head_of_recruitment"):
            headers = await _headers_for(app_client, role)
            r = await app_client.post(
                SEED_URL.format(cid=cid), json={"seed_key": SEED_KEY}, headers=headers
            )
            assert r.status_code == 403, (role, r.text)

        stranger = await _headers_for(app_client, "delivery_lead")
        r = await app_client.post(
            SEED_URL.format(cid=cid), json={"seed_key": SEED_KEY}, headers=stranger
        )
        assert r.status_code == 200, r.text

        admin = await _headers_for(app_client, "admin")
        r = await app_client.post(
            SEED_URL.format(cid=admin_cid), json={"seed_key": SEED_KEY}, headers=admin
        )
        assert r.status_code == 200, r.text
    finally:
        await _cleanup([cid, admin_cid])


def test_every_seed_entry_builds_a_valid_payload():
    """Każdy z 14 wpisów seed.json buduje poprawny payload karty (granice liczb,
    allowlista URL dokumentów) — backfill nie może paść 422 na treści, którą sami
    wgraliśmy."""
    from app.api.client_playbooks import _payload_from_seed
    from app.services.client_playbook_seed import load_playbook_seed

    entries = load_playbook_seed()
    assert len(entries) == 14
    for entry in entries:
        # Rzuci ValidationError, gdy wpis łamie granice/URL — to jest asercja.
        payload = _payload_from_seed(entry)
        assert payload.sla_business_days == entry.get("sla_business_days")
        assert len(payload.documents) == len(entry.get("documents") or [])


# ── Przegląd ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_overview_skips_hidden_and_merged_clients_and_orders_by_display_name(
    app_client: AsyncClient,
):
    tag = uuid.uuid4().hex[:6]
    a = await _make_client(f"Playbook ovw A {tag}", display_name=f"Zzz Karta {tag}")
    b = await _make_client(f"Aaa Karta {tag}")
    c = await _make_client(f"Playbook ovw C {tag}")
    d = await _make_client(f"Playbook ovw D {tag}", hidden=True)
    e = await _make_client(f"Playbook ovw E {tag}", merged_into_client_id=a)
    ids = [a, b, c, d, e]
    try:
        admin = await _headers_for(app_client, "admin")
        for cid in (a, b, d, e):
            r = await app_client.put(
                URL.format(cid=cid), json=_full_payload(), headers=admin
            )
            assert r.status_code == 200, r.text

        o = await app_client.get(OVERVIEW_URL, headers=admin)
        assert o.status_code == 200, o.text
        listed = [item["client_id"] for item in o.json()["items"]]
        assert a in listed and b in listed
        assert c not in listed and d not in listed and e not in listed
        assert listed.index(b) < listed.index(a)
        names = {item["client_id"]: item["client_name"] for item in o.json()["items"]}
        assert names[a] == f"Zzz Karta {tag}"
    finally:
        await _cleanup(ids)


# ── Rejestracja tras i lustra wdrożeniowe (bez bazy) ────────────────────────


def _all_paths() -> set[str]:
    # Nie pętla po `app.routes`: od FastAPI 0.139 `include_router()` nie spłaszcza
    # tras (widać 4 trasy health zamiast ~800) — helper składa prefiksy sam.
    from app.main import app
    from tests._route_introspection import iter_api_routes

    return {path for path, _route in iter_api_routes(app)}


def test_routes_are_registered_under_api_prefix():
    paths = _all_paths()
    for expected in (
        "/api/clients/{client_id}/playbook",
        "/api/clients/{client_id}/playbook/seed",
        "/api/clients/{client_id}/playbook/history",
        "/api/settings/client-playbooks",
    ):
        assert expected in paths, expected


def test_seed_file_matches_migration_and_entrypoint_mirror():
    """Seed w repo + lustro w entrypoint — prod alembic jest osierocony, lustro jest wdrożeniem."""
    from app.api.client_cv_rules import CHAMPION_SEED_KEYS

    seed_path = BACKEND_ROOT / "app" / "data" / "client_playbooks" / "seed.json"
    entries = json.loads(seed_path.read_text(encoding="utf-8"))
    assert len(entries) == 14
    assert {e["seed_key"] for e in entries} == {slug for slug, _ in CHAMPION_SEED_KEYS}
    for entry in entries:
        assert entry["name_pattern"].startswith("%") and entry["name_pattern"].endswith(
            "%"
        )
        sla = entry.get("sla_business_days")
        assert sla is None or 0 <= sla <= 365
        for key in (
            "sla_min_candidates",
            "cv_limit_per_process",
            "hold_hours",
            "multi_project_cooldown_days",
        ):
            value = entry.get(key)
            assert value is None or value > 0, (entry["seed_key"], key)
        assert isinstance(entry["documents"], list)
        for doc in entry["documents"]:
            assert doc["name"] and doc["url"].startswith("https://"), doc
        assert (entry.get("rate_policy") or "") == "" or len(
            entry["rate_policy"]
        ) <= 500

    entrypoint = (BACKEND_ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    for needle in (
        "CREATE TABLE IF NOT EXISTS client_playbooks",
        "CREATE TABLE IF NOT EXISTS client_playbook_events",
        "ADD CONSTRAINT ck_client_playbooks_numbers",
        "await _seed_client_playbooks(conn)",
        "0272_champion_client_templates_unpublished",
    ):
        assert needle in entrypoint, needle

    migration = (
        BACKEND_ROOT / "alembic" / "versions" / "0272_client_playbooks.py"
    ).read_text(encoding="utf-8")
    assert "ON CONFLICT (client_id) DO NOTHING" in migration
    assert re.search(r'down_revision = "0271_default_template_interview"', migration)
    assert re.search(r'revision = "0272_client_playbooks"', migration)
    for slug, _ in CHAMPION_SEED_KEYS:
        assert slug in migration, slug
        assert slug in entrypoint, slug


@pytest.mark.asyncio
async def test_concurrent_first_create_is_409_not_500(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Dwa PIERWSZE zapisy karty naraz: oba widzą brak wiersza, drugi INSERT pada
    na ``ux_client_playbooks_client``. Bez mapowania wyjątek leci jako 500 bez
    CORS („Network Error"); tu ma być 409 z komunikatem, a ponowny zapis ma
    przejść, bo sesja została odwinięta."""
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import AsyncSession

    cid = await _make_client(_unique("Playbook race"))
    try:
        headers = await _headers_for(app_client, "admin")
        real_flush = AsyncSession.flush
        armed = {"on": False}

        async def flush_like_a_lost_race(self, *args, **kwargs):
            if armed["on"]:
                armed["on"] = False
                raise IntegrityError(
                    "INSERT INTO client_playbooks",
                    {},
                    Exception(
                        "duplicate key value violates unique constraint "
                        '"ux_client_playbooks_client"'
                    ),
                )
            return await real_flush(self, *args, **kwargs)

        monkeypatch.setattr(AsyncSession, "flush", flush_like_a_lost_race)
        armed["on"] = True
        r = await app_client.put(
            URL.format(cid=cid), json=_full_payload(), headers=headers
        )
        assert r.status_code == 409, r.text
        assert "ktoś inny" in r.json()["detail"]
        assert armed["on"] is False, "atrapa flush nie została użyta w handlerze"

        r2 = await app_client.put(
            URL.format(cid=cid), json=_full_payload(), headers=headers
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["version"] == 1
    finally:
        await _cleanup([cid])


def test_seed_never_names_another_client_in_card_text():
    """Wzór PFRON niósł zdanie „sprzęt zapewnia bank Nordea" skopiowane z wzoru
    Nordei — na karcie innego klienta to fałsz pokazywany rekruterom od pierwszego
    startu. Nazwa banku może paść wyłącznie na jego własnej karcie."""
    seed_path = BACKEND_ROOT / "app" / "data" / "client_playbooks" / "seed.json"
    entries = json.loads(seed_path.read_text(encoding="utf-8"))
    text_fields = (
        "about_for_candidate",
        "priority_rules",
        "process_rules_md",
        "onboarding_md",
        "rate_policy",
    )
    for entry in entries:
        if "nordea" in entry["seed_key"]:
            continue
        text = " ".join(str(entry.get(field) or "") for field in text_fields)
        assert "Nordea" not in text, entry["seed_key"]
