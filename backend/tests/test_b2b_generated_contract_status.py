"""Status handlowy wygenerowanej umowy B2B + wyszukiwarka listy.

Dwie rzeczy, których nie da się sprawdzić samą walidacją DTO i dlatego jadą
przez prawdziwą bazę:

1. Zamknięcie umowy **nie usuwa** wiersza i jest niezależne od statusu podpisu
   (podpisaną umowę też się wypowiada — inaczej cała funkcja byłaby martwa dla
   najczęstszego przypadku).
2. ``?q=`` filtruje po stronie serwera, więc znajduje umowy spoza pierwszej
   strony listy — filtrowanie w przeglądarce dawałoby fałszywe „brak wyników".
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.b2b_contract_generator import B2BGeneratedContractUpdate

PATH = "/api/b2b-generator/generated"


async def _admin_user_id(app_client) -> int:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.user import User

    email = app_client.headers.get("X-Test-Admin-Email")
    async with AsyncSessionLocal() as db:
        uid = await db.scalar(select(User.id).where(User.email == email))
    assert uid is not None, "app_client nie zaseedował admina"
    return uid


async def _seed(
    created_by: int,
    *,
    partner_name: str = "Jan Kowalski",
    client_name: str = "Nordea Bank",
    signature_status: str = "unsigned",
) -> tuple[int, str]:
    """Wstaw wiersz i zwróć ``(id, contract_number)``.

    ``seq`` z UUID → brak kolizji z UNIQUE(year, seq) przy powtórnym
    uruchomieniu testu na tej samej bazie."""
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract

    seq = 100000 + (uuid.uuid4().int % 800000)
    async with AsyncSessionLocal() as db:
        row = B2BGeneratedContract(
            year=2026,
            seq=seq,
            contract_number=f"{seq}/2026",
            partner_name=partner_name,
            client_name=client_name,
            language="pl",
            created_by=created_by,
            signature_status=signature_status,
            render_payload={"language": "pl", "client_name": client_name},
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id, row.contract_number


# ── DTO: lustro CHECK-a spójności ────────────────────────────────────────────


def test_update_dto_rejects_closed_without_reason_or_date():
    with pytest.raises(ValidationError, match="powód zamknięcia"):
        B2BGeneratedContractUpdate(contract_status="closed", closure_date="2026-08-01")
    with pytest.raises(ValidationError, match="Data zakończenia"):
        B2BGeneratedContractUpdate(
            contract_status="closed", closure_reason="termination"
        )


def test_update_dto_requires_free_text_only_for_other():
    with pytest.raises(ValidationError, match="własny powód"):
        B2BGeneratedContractUpdate(
            contract_status="closed",
            closure_reason="other",
            closure_date="2026-08-01",
        )
    with pytest.raises(ValidationError, match="tylko dla powodu"):
        B2BGeneratedContractUpdate(
            contract_status="closed",
            closure_reason="termination",
            closure_reason_other="cokolwiek",
            closure_date="2026-08-01",
        )


def test_update_dto_rejects_closure_fields_without_status():
    """Same pola zamknięcia bez statusu zostawiłyby wiersz w sprzeczności."""
    with pytest.raises(ValidationError, match="wyłącznie razem"):
        B2BGeneratedContractUpdate(closure_date="2026-08-01")


# ── API: zamknięcie i powrót do aktywnej ─────────────────────────────────────


async def test_new_contract_defaults_to_active(app_client, app_auth_headers):
    admin_id = await _admin_user_id(app_client)
    rid, _number = await _seed(admin_id)

    resp = await app_client.get(PATH, headers=app_auth_headers, params={"limit": 200})
    assert resp.status_code == 200, resp.text
    item = next(x for x in resp.json() if x["id"] == rid)
    assert item["contract_status"] == "active"
    assert item["closure_reason"] is None
    assert item["closure_date"] is None
    assert item["can_change_status"] is True


async def test_closing_keeps_the_row_and_records_reason_and_date(
    app_client, app_auth_headers
):
    """Sedno zgłoszenia: „umowa pozostaje w systemie i nie jest usuwana"."""
    admin_id = await _admin_user_id(app_client)
    rid, _number = await _seed(admin_id)

    resp = await app_client.patch(
        f"{PATH}/{rid}",
        headers=app_auth_headers,
        json={
            "contract_status": "closed",
            "closure_reason": "termination",
            "closure_date": "2026-08-31",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["contract_status"] == "closed"
    assert body["closure_reason"] == "termination"
    assert body["closure_date"] == "2026-08-31"

    listing = await app_client.get(
        PATH, headers=app_auth_headers, params={"limit": 200}
    )
    assert listing.status_code == 200
    assert any(x["id"] == rid for x in listing.json()), "zamknięcie usunęło wiersz"


async def test_closing_other_stores_free_text(app_client, app_auth_headers):
    admin_id = await _admin_user_id(app_client)
    rid, _number = await _seed(admin_id)

    resp = await app_client.patch(
        f"{PATH}/{rid}",
        headers=app_auth_headers,
        json={
            "contract_status": "closed",
            "closure_reason": "other",
            "closure_reason_other": "  Zmiana modelu współpracy  ",
            "closure_date": "2026-09-01",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["closure_reason_other"] == "Zmiana modelu współpracy"


async def test_reopening_clears_every_closure_field(app_client, app_auth_headers):
    admin_id = await _admin_user_id(app_client)
    rid, _number = await _seed(admin_id)

    await app_client.patch(
        f"{PATH}/{rid}",
        headers=app_auth_headers,
        json={
            "contract_status": "closed",
            "closure_reason": "mutual_agreement",
            "closure_date": "2026-08-31",
        },
    )
    resp = await app_client.patch(
        f"{PATH}/{rid}",
        headers=app_auth_headers,
        json={"contract_status": "active"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["contract_status"] == "active"
    assert body["closure_reason"] is None
    assert body["closure_reason_other"] is None
    assert body["closure_date"] is None


async def test_signed_contract_can_still_be_closed(app_client, app_auth_headers):
    """Wypowiedzenie i porozumienie dotyczą umów PODPISANYCH.

    Blokada edycji po podpisaniu chroni treść dokumentu, nie jego bieg —
    gdyby obejmowała status, funkcja byłaby bezużyteczna tam, gdzie jest
    najbardziej potrzebna."""
    admin_id = await _admin_user_id(app_client)
    rid, _number = await _seed(admin_id, signature_status="signed_both")

    resp = await app_client.patch(
        f"{PATH}/{rid}",
        headers=app_auth_headers,
        json={
            "contract_status": "closed",
            "closure_reason": "termination",
            "closure_date": "2026-08-31",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["contract_status"] == "closed"

    # Treść dokumentu pozostaje zamrożona.
    blocked = await app_client.patch(
        f"{PATH}/{rid}",
        headers=app_auth_headers,
        json={"client_name": "Inny Klient"},
    )
    assert blocked.status_code == 409


async def test_status_filter_narrows_the_listing(app_client, app_auth_headers):
    admin_id = await _admin_user_id(app_client)
    active_id, _ = await _seed(admin_id)
    closed_id, _ = await _seed(admin_id)
    await app_client.patch(
        f"{PATH}/{closed_id}",
        headers=app_auth_headers,
        json={
            "contract_status": "closed",
            "closure_reason": "termination",
            "closure_date": "2026-08-31",
        },
    )

    resp = await app_client.get(
        PATH,
        headers=app_auth_headers,
        params={"limit": 200, "contract_status": "closed"},
    )
    assert resp.status_code == 200, resp.text
    ids = {x["id"] for x in resp.json()}
    assert closed_id in ids
    assert active_id not in ids


# ── API: wyszukiwarka ────────────────────────────────────────────────────────


async def test_search_by_contract_number(app_client, app_auth_headers):
    admin_id = await _admin_user_id(app_client)
    rid, number = await _seed(admin_id)

    resp = await app_client.get(PATH, headers=app_auth_headers, params={"q": number})
    assert resp.status_code == 200, resp.text
    assert [x["id"] for x in resp.json()] == [rid]


async def test_search_by_partner_full_name_is_case_insensitive(
    app_client, app_auth_headers
):
    admin_id = await _admin_user_id(app_client)
    surname = f"Nowakowski{uuid.uuid4().hex[:8]}"
    rid, _number = await _seed(admin_id, partner_name=f"Anna {surname}")

    resp = await app_client.get(
        PATH, headers=app_auth_headers, params={"q": surname.lower()}
    )
    assert resp.status_code == 200, resp.text
    assert [x["id"] for x in resp.json()] == [rid]


async def test_search_finds_row_by_linked_candidate_name(app_client, app_auth_headers):
    """Umowa jest na firmę Partnera, a szuka się po nazwisku kandydata.

    Bez OUTER JOIN-a na `candidates` ta umowa byłaby nie do znalezienia po
    człowieku, którego dotyczy — a to jest wprost treść zgłoszenia."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from app.models.candidate import Candidate
    from app.models.user import User

    tag = uuid.uuid4().hex[:8]
    email = app_client.headers.get("X-Test-Admin-Email")
    async with AsyncSessionLocal() as db:
        uid = await db.scalar(select(User.id).where(User.email == email))
        candidate = Candidate(name="Zofia", lastname=f"Wisniewska{tag}")
        db.add(candidate)
        await db.commit()
        await db.refresh(candidate)

        seq = 100000 + (uuid.uuid4().int % 800000)
        row = B2BGeneratedContract(
            year=2026,
            seq=seq,
            contract_number=f"{seq}/2026",
            partner_name="ZW Software Sp. z o.o.",  # celowo bez nazwiska
            client_name="Klient",
            language="pl",
            created_by=uid,
            candidate_id=candidate.id,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        rid = row.id

    for phrase in (f"Wisniewska{tag}", f"Zofia Wisniewska{tag}"):
        resp = await app_client.get(
            PATH, headers=app_auth_headers, params={"q": phrase}
        )
        assert resp.status_code == 200, resp.text
        assert [x["id"] for x in resp.json()] == [rid], phrase


async def test_search_wildcards_are_escaped_not_executed(app_client, app_auth_headers):
    """`%` wpisany w szukajkę ma szukać znaku `%`, nie zwracać całej listy."""
    admin_id = await _admin_user_id(app_client)
    await _seed(admin_id, partner_name=f"Bez procenta {uuid.uuid4().hex[:8]}")

    resp = await app_client.get(PATH, headers=app_auth_headers, params={"q": "%"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


async def test_search_misses_return_empty_not_everything(app_client, app_auth_headers):
    admin_id = await _admin_user_id(app_client)
    await _seed(admin_id)

    resp = await app_client.get(
        PATH,
        headers=app_auth_headers,
        params={"q": f"nieistniejaca-fraza-{uuid.uuid4().hex}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == []
