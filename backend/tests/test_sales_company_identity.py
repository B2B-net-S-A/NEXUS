"""Sprzedaż → tożsamość firmy przy zakładaniu (``/api/sales/companies/identity``).

Podpowiedź istniejącej karty po nazwie i domenie oraz domena z adresu strony albo
maila osoby. To podpowiedź: niczego nie blokuje.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.database import AsyncSessionLocal
from app.models.sales import SalesCompany
from app.services.sales.companies import mail_domain
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_meeting_decisions import _firm, _opportunity

URL = "/api/sales/companies"


def _tag() -> str:
    return uuid.uuid4().hex[:10]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://www.Firma.example/kontakt?x=1", "firma.example"),
        ("jan.kowalski@firma.com.pl", "firma.com.pl"),
        ("firma.pl", "firma.pl"),
        ("www.firma.pl:8080", "firma.pl"),
        ("mailto:jan@firma.pl", "firma.pl"),
        ("jan@gmail.com", None),
        ("firma", None),
        ("javascript:alert(1)", None),
        ("dwa slowa.pl", None),
        ("jan@", None),
        ("", None),
        (None, None),
    ],
)
def test_mail_domain(value, expected) -> None:
    assert mail_domain(value) == expected


async def _identity(app_client, user, **params: str) -> dict:
    resp = await app_client.get(
        f"{URL}/identity", params=params, headers=_headers(user)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_identity_needs_sales_view(app_client) -> None:
    stranger = await _user()
    resp = await app_client.get(
        f"{URL}/identity", params={"name": "Firma"}, headers=_headers(stranger)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_domain_comes_from_the_website_then_from_the_mail(app_client) -> None:
    viewer = await _user("sales_view")
    both = await _identity(
        app_client,
        viewer,
        website="https://www.strona-firmy.example/o-nas",
        email="osoba@poczta-firmy.example",
    )
    assert (both["domain"], both["domain_source"]) == (
        "strona-firmy.example",
        "website",
    )
    mail = await _identity(app_client, viewer, email="Osoba@Poczta-Firmy.example")
    assert (mail["domain"], mail["domain_source"]) == ("poczta-firmy.example", "email")
    free = await _identity(app_client, viewer, email="osoba@gmail.com")
    assert (free["domain"], free["domain_source"]) == (None, None)
    assert (await _identity(app_client, viewer))["matches"] == []


@pytest.mark.asyncio
async def test_existing_cards_are_suggested_by_name_and_domain(app_client) -> None:
    rep = await _user("sales_edit")
    tag = _tag()
    exact = await _firm(f"Zakłady {tag} S.A.")
    similar = await _firm(f"Zakłady {tag} Logistyka")
    by_domain = await _firm(domain=f"https://www.{tag}.example/")
    archived = await _firm(f"Zakłady {tag} Archiwum")
    async with AsyncSessionLocal() as db:
        company = await db.get(SalesCompany, archived)
        company.archived_at = company.created_at
        await db.commit()
    await _opportunity(app_client, rep, similar)

    found = await _identity(
        app_client, rep, name=f"zaklady {tag}", email=f"ktos@{tag}.example"
    )
    assert [(m["id"], m["reason"]) for m in found["matches"]] == [
        (exact, "name"),
        (by_domain, "domain"),
        (similar, "similar"),
    ]
    assert found["matches"][2]["open_opportunities"] == 1
    assert found["domain"] == f"{tag}.example"

    without_self = await _identity(
        app_client, rep, name=f"Zakłady {tag}", exclude_id=str(exact)
    )
    assert [m["id"] for m in without_self["matches"]] == [similar]
    # Jedna litera to za mało, żeby cokolwiek podpowiadać.
    assert (await _identity(app_client, rep, name="Z"))["matches"] == []


@pytest.mark.asyncio
async def test_new_company_takes_the_domain_from_its_website(app_client) -> None:
    rep = await _user("sales_edit")
    created = await app_client.post(
        URL,
        json={"name": f"Firma WWW {_tag()}", "website_url": "www.firma-www.example"},
        headers=_headers(rep),
    )
    assert created.status_code == 201, created.text
    assert created.json()["domain"] == "firma-www.example"

    # Wpisana domena zostaje, strona jej nie nadpisuje.
    kept = await app_client.post(
        URL,
        json={
            "name": f"Firma Domena {_tag()}",
            "domain": "wpisana.example",
            "website_url": "https://inna.example",
        },
        headers=_headers(rep),
    )
    assert kept.json()["domain"] == "wpisana.example"
    patched = await app_client.patch(
        f"{URL}/{kept.json()['id']}",
        json={"website_url": "https://jeszcze-inna.example"},
        headers=_headers(rep),
    )
    assert patched.json()["domain"] == "wpisana.example"

    # Domena skasowana świadomie nie wraca ze strony przy tym samym zapisie.
    cleared = await app_client.patch(
        f"{URL}/{kept.json()['id']}",
        json={"domain": None, "website_url": "https://jeszcze-inna.example"},
        headers=_headers(rep),
    )
    assert cleared.json()["domain"] is None
    # Zapis samej strony na karcie bez domeny ją uzupełnia.
    filled = await app_client.patch(
        f"{URL}/{kept.json()['id']}",
        json={"website_url": "https://nowa-strona.example"},
        headers=_headers(rep),
    )
    assert filled.json()["domain"] == "nowa-strona.example"
