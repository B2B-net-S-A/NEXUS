"""Listy dzwonienia widoczne dla całej Sprzedaży (decyzja Artura 12.11.2026).

Tabela ma zakres „Moje / Wszyscy” z kolumną „Kto dzwoni”, a karta firmy pokazuje, na czyjej
liście jest firma. Każdy z „Sprzedaż: podgląd” widzi listy, zapis wyniku dalej tylko
przypisany albo admin, a sprzeciw i numer telefonu nie wychodzą poza kolejkę.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.test_sales_calling_queue import URL, _campaign, _company, _record, _save
from tests.test_sales_companies_api import _headers, _user


async def _table(app_client: Any, user: Any, **params: Any) -> dict[str, Any]:
    resp = await app_client.get(f"{URL}/records", params=params, headers=_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_all_scope_shows_every_callers_records_with_who_calls(app_client) -> None:
    marcel = await _user("sales_view", "sales_edit")
    bianca = await _user("sales_view", "sales_edit")
    seller = await _user("sales_view")
    campaign_id = await _campaign()
    marcels = await _record(marcel.id, campaign_id, await _company())
    biancas = await _record(
        bianca.id, campaign_id, await _company(), state="offer_sent"
    )
    await _record(bianca.id, campaign_id, await _company(), state="do_not_contact")

    mine = await _table(app_client, seller, campaign_id=campaign_id)
    assert mine["items"] == [] and mine["counts"] == {}

    everyone = await _table(app_client, seller, campaign_id=campaign_id, scope="all")
    by_record = {item["record_id"]: item for item in everyone["items"]}
    assert set(by_record) == {marcels, biancas}
    assert by_record[marcels]["assignee"] == {"id": marcel.id, "name": marcel.name}
    assert by_record[biancas]["assignee"]["id"] == bianca.id
    # Sprzeciw nie wychodzi także w zakresie „Wszyscy”.
    assert everyone["counts"] == {"new": 1, "offer_sent": 1}
    assert {caller["id"] for caller in everyone["callers"]} == {marcel.id, bianca.id}


@pytest.mark.asyncio
async def test_all_scope_filters_by_caller_and_mine_ignores_caller(app_client) -> None:
    marcel = await _user("sales_view", "sales_edit")
    bianca = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign()
    marcels = await _record(marcel.id, campaign_id, await _company())
    biancas = await _record(bianca.id, campaign_id, await _company())

    only_bianca = await _table(
        app_client, marcel, campaign_id=campaign_id, scope="all", caller_id=bianca.id
    )
    assert [item["record_id"] for item in only_bianca["items"]] == [biancas]

    # „Moje” zawsze znaczy zalogowaną osobę, nawet z cudzym caller_id w adresie.
    mine = await _table(
        app_client, marcel, campaign_id=campaign_id, caller_id=bianca.id
    )
    assert [item["record_id"] for item in mine["items"]] == [marcels]


@pytest.mark.asyncio
async def test_someone_elses_record_is_saved_only_with_sales_edit(app_client) -> None:
    """Decyzja Artura 13.11.2026 zastępuje „cudzy rekord tylko do czytania” z 12.11:
    wynik w cudzej kolejce zapisuje każdy z „Sprzedaż: edycja”, podgląd dalej nie."""

    marcel = await _user("sales_view", "sales_edit")
    seller = await _user("sales_view", "sales_edit")
    viewer = await _user("sales_view")
    campaign_id = await _campaign()
    record_id = await _record(marcel.id, campaign_id, await _company())

    card = await app_client.get(f"{URL}/records/{record_id}", headers=_headers(viewer))
    assert card.status_code == 200, card.text
    assert card.json()["can_save"] is False
    assert (
        await _save(app_client, viewer, record_id, outcome="no_answer")
    ).status_code == 403
    card = await app_client.get(f"{URL}/records/{record_id}", headers=_headers(seller))
    assert card.json()["can_save"] is True
    resp = await _save(app_client, seller, record_id, outcome="no_answer")
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_unknown_scope_is_refused(app_client) -> None:
    seller = await _user("sales_view")
    resp = await app_client.get(
        f"{URL}/records", params={"scope": "team"}, headers=_headers(seller)
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_company_card_lists_who_calls_without_phone_numbers(app_client) -> None:
    marcel = await _user("sales_view", "sales_edit")
    seller = await _user("sales_view")
    campaign_id = await _campaign()
    company_id = await _company()
    record_id = await _record(
        marcel.id,
        campaign_id,
        company_id,
        state="not_interested",
        person_name="Ewa Testowa",
        phone="511 222 333",
    )
    await _record(marcel.id, campaign_id, await _company())

    resp = await app_client.get(
        f"{URL}/companies/{company_id}/records", headers=_headers(seller)
    )
    assert resp.status_code == 200, resp.text
    [row] = resp.json()
    assert row["record_id"] == record_id
    assert row["assignee"] == {"id": marcel.id, "name": marcel.name}
    assert row["state"] == "not_interested"
    assert row["person_name"] == "Ewa Testowa"
    assert "phone" not in row and "511 222 333" not in resp.text


@pytest.mark.asyncio
async def test_company_records_need_sales_view(app_client) -> None:
    outsider = await _user()
    company_id = await _company()
    resp = await app_client.get(
        f"{URL}/companies/{company_id}/records", headers=_headers(outsider)
    )
    assert resp.status_code == 403
