"""Generator Umów B2B — poprawki po audycie 23.09.2026.

Każdy test odtwarza zachowanie zmierzone na produkcji albo w kodzie:
umowa „Aktywna” bez podpisu, numer usuniętej umowy wydany drugi raz,
poprawka literówki przez „usuń i wygeneruj”, rejestr ucięty do 100 wierszy,
rejestr, który nie wie o końcu kontraktu, stawka nadpisana cudzemu szkicowi.

In-process `app_client`; baza wspólna i nieczyszczona — asercje tylko na
własnych wierszach (numery z UUID).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.database import AsyncSessionLocal
from app.schemas.b2b_contract_generator import (
    B2BRateStageInput,
    B2BRenderRequest,
)
from tests.test_b2b_generated_contract_status import (
    PATH,
    _admin_user_id,
    _item_by_number,
    _link,
    _render_docx,
    _seed,
    _seed_linked_contract,
)
from tests.test_b2b_generator_rate_visibility import _seed_documents, _seed_user


def _number() -> str:
    seq = 300000 + (uuid.uuid4().int % 500000)
    return f"{seq}/2026"


# ── „Aktywna” wyłącznie po podpisie ──────────────────────────────────────────


async def test_unsigned_contract_cannot_be_made_active_by_hand(
    app_client, app_auth_headers
):
    """Do 23.09 PATCH przepuszczał `in_progress → active`: wiersz „Aktywny
    i Niepodpisany” bez kontraktu, zamówienia i ruchu kandydata."""
    number = await _render_docx(app_client, app_auth_headers)
    item = await _item_by_number(app_client, app_auth_headers, number)

    resp = await app_client.patch(
        f"{PATH}/{item['id']}",
        headers=app_auth_headers,
        json={"contract_status": "active"},
    )
    assert resp.status_code == 422, resp.text
    assert "podpisaną" in resp.json()["detail"]
    after = await _item_by_number(app_client, app_auth_headers, number)
    assert after["contract_status"] == "in_progress"


async def test_closed_unsigned_contract_returns_to_in_progress_not_active(
    app_client, app_auth_headers
):
    admin_id = await _admin_user_id(app_client)
    rid, number = await _seed(admin_id)
    closed = await app_client.patch(
        f"{PATH}/{rid}",
        headers=app_auth_headers,
        json={
            "contract_status": "closed",
            "closure_reason": "project_completed",
            "closure_date": "2026-08-31",
        },
    )
    assert closed.status_code == 200, closed.text

    to_active = await app_client.patch(
        f"{PATH}/{rid}", headers=app_auth_headers, json={"contract_status": "active"}
    )
    assert to_active.status_code == 422, to_active.text

    back = await app_client.patch(
        f"{PATH}/{rid}",
        headers=app_auth_headers,
        json={"contract_status": "in_progress"},
    )
    assert back.status_code == 200, back.text
    assert back.json()["contract_status"] == "in_progress"
    assert back.json()["closure_reason"] is None


# ── Numer usuniętej umowy nie wraca do puli ──────────────────────────────────


async def test_deleted_number_is_neither_suggested_nor_accepted_again(
    app_client, app_auth_headers
):
    """1518 i 1522/2026 zostały usunięte i wydane innym Partnerom — usunięty
    DOCX mógł już wyjść mailem."""
    number = await _render_docx(app_client, app_auth_headers)
    item = await _item_by_number(app_client, app_auth_headers, number)
    deleted = await app_client.delete(f"{PATH}/{item['id']}", headers=app_auth_headers)
    assert deleted.status_code == 204, deleted.text

    reuse = await app_client.post(
        "/api/b2b-generator/render?format=docx",
        headers=app_auth_headers,
        json={
            "language": "pl",
            "contract_number": number,
            "partner_name": "Inna Osoba",
            "client_name": "Nordea Bank",
            "signing_date": "2026-08-01",
        },
    )
    assert reuse.status_code == 409, reuse.text
    assert "był już wydany" in reuse.json()["detail"]

    from app.api.b2b_contract_generator import _next_seq

    async with AsyncSessionLocal() as db:
        suggested = await _next_seq(db)
    assert suggested != int(number.split("/")[0])


async def test_a_deleted_typo_number_does_not_inflate_the_numbering(
    app_client, app_auth_headers
):
    """Usunięta literówka („15190” zamiast „1519”) nie może na zawsze
    przestawić sugestii — pomijamy usunięte numery, nie liczymy z nich max."""
    from app.api.b2b_contract_generator import _next_seq

    async with AsyncSessionLocal() as db:
        before = await _next_seq(db)
    typo = before + 50_000
    await _render_docx(app_client, app_auth_headers, contract_number=f"{typo}/2026")
    item = await _item_by_number(app_client, app_auth_headers, f"{typo}/2026")
    deleted = await app_client.delete(f"{PATH}/{item['id']}", headers=app_auth_headers)
    assert deleted.status_code == 204, deleted.text

    async with AsyncSessionLocal() as db:
        after = await _next_seq(db)
    assert after < typo


async def test_numbering_continues_across_years(app_client):
    """Rejestr działu: „zmieniamy jedynie rok”. Z filtrem po roku 1 stycznia
    2027 sugestią byłoby „1/2027”."""
    from app.api.b2b_contract_generator import _next_seq

    admin_id = await _admin_user_id(app_client)
    _rid, number = await _seed(admin_id)
    async with AsyncSessionLocal() as db:
        suggested = await _next_seq(db)
    assert suggested > int(number.split("/")[0])


async def test_render_returns_the_register_row_id(app_client, app_auth_headers):
    number = _number()
    resp = await app_client.post(
        "/api/b2b-generator/render?format=docx",
        headers=app_auth_headers,
        json={
            "language": "pl",
            "contract_number": number,
            "partner_name": "Zofia Wiśniewska",
            "client_name": "Nordea Bank",
            "signing_date": "2026-08-01",
        },
    )
    assert resp.status_code == 200, resp.text
    item = await _item_by_number(app_client, app_auth_headers, number)
    assert resp.headers["X-Generated-Contract-Id"] == str(item["id"])
    assert "X-Generated-Contract-Id" in resp.headers["Access-Control-Expose-Headers"]


# ── Poprawka pod tym samym numerem ───────────────────────────────────────────


async def test_rerender_fixes_the_same_row_under_the_same_number(
    app_client, app_auth_headers
):
    """Do 23.09 poprawka = „usuń i wygeneruj” (15 usunięć na ~104 generacje),
    a wersja EN tej samej umowy dostawała drugi numer."""
    number = await _render_docx(app_client, app_auth_headers)
    item = await _item_by_number(app_client, app_auth_headers, number)

    resp = await app_client.post(
        f"{PATH}/{item['id']}/rerender",
        headers=app_auth_headers,
        json={
            "language": "en",
            "contract_number": "1/2026",  # ignorowany — numer należy do wiersza
            "partner_name": "Zofia Wiśniewska-Nowak",
            "client_name": "Nordea Bank",
            "signing_date": "2026-08-02",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["X-Contract-Number"] == number

    after = await _item_by_number(app_client, app_auth_headers, number)
    assert after["id"] == item["id"]
    assert after["partner_name"] == "Zofia Wiśniewska-Nowak"
    assert after["language"] == "en"
    assert after["signing_date"] == "2026-08-02"

    redownload = await app_client.get(
        f"{PATH}/{item['id']}/docx", headers=app_auth_headers
    )
    assert redownload.status_code == 200, redownload.text


async def test_rerender_refuses_signed_contracts(app_client, app_auth_headers):
    admin_id = await _admin_user_id(app_client)
    rid, _ = await _seed(admin_id, signature_status="signed_both")
    resp = await app_client.post(
        f"{PATH}/{rid}/rerender",
        headers=app_auth_headers,
        json={"language": "pl", "partner_name": "X", "client_name": "Nordea Bank"},
    )
    assert resp.status_code == 409, resp.text


async def test_rerender_cannot_switch_candidate(app_client, app_auth_headers):
    number = await _render_docx(app_client, app_auth_headers)
    item = await _item_by_number(app_client, app_auth_headers, number)
    resp = await app_client.post(
        f"{PATH}/{item['id']}/rerender",
        headers=app_auth_headers,
        json={
            "language": "pl",
            "partner_name": "X",
            "client_name": "Nordea Bank",
            "candidate_id": 1,
            "job_id": 1,
        },
    )
    assert resp.status_code == 422, resp.text


async def test_rerender_is_for_the_author_only(app_client, app_auth_headers):
    number = await _render_docx(app_client, app_auth_headers)
    item = await _item_by_number(app_client, app_auth_headers, number)
    other_h, _ = await _seed_user(app_client, "tac")
    resp = await app_client.post(
        f"{PATH}/{item['id']}/rerender",
        headers=other_h,
        json={"language": "pl", "partner_name": "X", "client_name": "Nordea Bank"},
    )
    assert resp.status_code == 403, resp.text


# ── Rejestr: stronicowanie i stan kontraktu ──────────────────────────────────


async def test_register_pages_past_the_first_window(app_client, app_auth_headers):
    """Lista kończyła się cicho na `limit` najnowszych wierszach."""
    admin_id = await _admin_user_id(app_client)
    marker = f"Stronicowanie {uuid.uuid4().hex[:8]}"
    ids = {(await _seed(admin_id, partner_name=f"{marker} {i}"))[0] for i in range(3)}
    first = await app_client.get(
        PATH, headers=app_auth_headers, params={"q": marker, "limit": 2}
    )
    second = await app_client.get(
        PATH,
        headers=app_auth_headers,
        params={"q": marker, "limit": 2, "offset": 2},
    )
    assert first.status_code == 200 and second.status_code == 200
    assert len(first.json()) == 2
    assert len(second.json()) == 1
    assert {x["id"] for x in first.json() + second.json()} == ids


async def test_register_row_carries_the_linked_contract_state(
    app_client, app_auth_headers
):
    """1447, 1472 i 1487/2026 były „Aktywne” przy zakończonych kontraktach."""
    from app.models.contract import Contract, ContractStatus

    admin_id = await _admin_user_id(app_client)
    rid, number = await _seed(admin_id, signature_status="signed_both")
    contract_id, _client_id = await _seed_linked_contract()
    await _link(rid, contract_id=contract_id)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        contract.status = ContractStatus.ended
        contract.end_date = date(2026, 8, 31)
        await db.commit()

    item = await _item_by_number(app_client, app_auth_headers, number)
    assert item["linked_contract_status"] == "ended"
    assert item["linked_contract_end_date"] == "2026-08-31"


# ── Walidacja wejścia ────────────────────────────────────────────────────────


def test_rate_is_rounded_to_grosze_once_for_amount_and_words():
    req = B2BRenderRequest(rate_candidate=135.999)
    assert req.rate_candidate == 136.0
    assert B2BRenderRequest(rate_candidate=135.555).rate_candidate == 135.56
    assert B2BRateStageInput(rate=99.994).rate == 99.99


def test_names_longer_than_the_register_columns_are_422_not_500():
    with pytest.raises(ValidationError):
        B2BRenderRequest(client_name="x" * 256)
    with pytest.raises(ValidationError):
        B2BRenderRequest(partner_legal_name="x" * 256)


# ── POST /generate nie nadpisuje stawki cudzego szkicu ───────────────────────


async def test_generate_cannot_overwrite_rate_of_someone_elses_draft(app_client):
    """Rekruter spoza zespołu rekrutacji zmieniał stawkę szkicu Delivery
    z 150 na 1 — przy czym sam tej stawki nie mógł nawet zobaczyć."""
    from app.models.b2b_contract_role import B2BContractRole
    from app.models.contract import Contract

    author_h, author_id = await _seed_user(app_client, "sourcer")
    _runner_h, runner_id = await _seed_user(app_client, "recruiter")
    outsider_h, _ = await _seed_user(app_client, "recruiter")
    docs = await _seed_documents(author_id=author_id, job_recruiter_id=runner_id)
    # Szkic bez rekrutacji — ścieżka `contract_id` nie waliduje wtedy pary
    # kandydat–rekrutacja, więc test mierzy wyłącznie bramkę stawki.
    async with AsyncSessionLocal() as db:
        draft = await db.get(Contract, docs["contract_id"])
        draft.job_id = None
        await db.commit()
    from sqlalchemy import select

    from app.models.contract_template import ContractTemplate

    async with AsyncSessionLocal() as db:
        has_template = await db.scalar(
            select(ContractTemplate.id).where(
                ContractTemplate.contract_type == "b2b",
                ContractTemplate.language == "pl",
            )
        )
        if has_template is None:
            db.add(
                ContractTemplate(
                    name="B2B PL (test)",
                    contract_type="b2b",
                    language="pl",
                    content_jinja="<p>{{ b2b.contract_number }}</p>",
                )
            )
            await db.commit()
        role_id = await db.scalar(select(B2BContractRole.id).limit(1))
        if role_id is None:
            role = B2BContractRole(
                category_key="dev",
                category_label_pl="Dev",
                category_label_en="Dev",
                slug=f"rola-{uuid.uuid4().hex[:6]}",
                name_pl="Rola",
                name_en="Role",
                area_label_pl="Obszar",
                area_label_en="Area",
                scope_pl=["Zakres"],
                scope_en=["Scope"],
            )
            db.add(role)
            await db.commit()
            role_id = role.id

    resp = await app_client.post(
        "/api/b2b-generator/generate",
        headers=outsider_h,
        json={
            "role_id": role_id,
            "contract_id": docs["contract_id"],
            "rate_candidate": 1,
            "start_date": "2026-10-01",
        },
    )
    assert resp.status_code == 403, resp.text
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, docs["contract_id"])
        assert contract.rate_candidate == Decimal("150")


class _Rows:
    def __init__(self, numbers: list[str]) -> None:
        self._numbers = numbers

    def all(self) -> list[tuple[str]]:
        return [(n,) for n in self._numbers]


class _FakeDb:
    def __init__(self, live: list[str]) -> None:
        self._live = live

    async def execute(self, _statement):
        return _Rows(self._live)


@pytest.mark.parametrize(
    ("live", "deleted", "expected"),
    [
        # Usunięto najnowszy wpis (1522) — nie wraca do puli.
        (["1520/2026", "1521/2026"], ["1522/2026"], 1523),
        # Seria usuniętych na szczycie jest przeskakiwana w całości.
        (["1521/2026"], ["1522/2026", "1523/2026"], 1524),
        # Usunięta literówka daleko ponad numeracją nic nie zawyża.
        (["1521/2026"], ["15190/2026"], 1522),
        # Rok się zmienia, numer płynie dalej.
        (["1522/2026"], [], 1523),
    ],
)
async def test_next_seq_skips_deleted_numbers_without_inflating(
    monkeypatch, live, deleted, expected
):
    from app.api import b2b_contract_generator as module

    async def _deleted(_db):
        return deleted

    monkeypatch.setattr(module, "_deleted_contract_numbers", _deleted)
    assert await module._next_seq(_FakeDb(live)) == expected


async def test_saved_form_can_be_reopened_for_correction(app_client, app_auth_headers):
    """„Popraw” z wiersza rejestru — działa też po odświeżeniu strony."""
    number = await _render_docx(app_client, app_auth_headers, project_city="Płock")
    item = await _item_by_number(app_client, app_auth_headers, number)
    resp = await app_client.get(f"{PATH}/{item['id']}/form", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == item["id"]
    assert body["form"]["contract_number"] == number
    assert body["form"]["project_city"] == "Płock"
    assert "_clause_override" not in body["form"]

    other_h, _ = await _seed_user(app_client, "tac")
    foreign = await app_client.get(f"{PATH}/{item['id']}/form", headers=other_h)
    assert foreign.status_code == 403, foreign.text
