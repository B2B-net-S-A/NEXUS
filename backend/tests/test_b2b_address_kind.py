"""Rodzaj adresu JDG z CEIDG: stałe miejsce działalności vs tylko adres do doręczeń.

Kształt odpowiedzi biznes.gov.pl sprawdzony na żywo 23.10.2026 (NIP z umowy
generatora): JDG bez stałego miejsca ma w ``addressData`` tylko
``correspondenceAddress``. HTTP zaślepiony ``httpx.MockTransport``.
"""

from __future__ import annotations

import httpx
import pytest

from app.services.b2b_contract_generator import registry_lookup
from app.services.b2b_contract_generator.registry_lookup import (
    ADDRESS_PLACE_OF_BUSINESS,
    ADDRESS_SERVICE,
    _merge,
    address_kind_from_biznes_details,
    lookup_by_biznes,
)

_ADDR = {"street": "ul. Testowa", "buildingNumber": "1", "city": "Warszawa"}


@pytest.mark.parametrize(
    "address_data,expected",
    [
        (
            {"placeOfBusinessAddress": _ADDR, "correspondenceAddress": _ADDR},
            ADDRESS_PLACE_OF_BUSINESS,
        ),
        (
            {
                "additionalPlaceOfBusinessAddress": _ADDR,
                "placeOfBusinessAddress": _ADDR,
                "correspondenceAddress": _ADDR,
            },
            ADDRESS_PLACE_OF_BUSINESS,
        ),
        ({"correspondenceAddress": _ADDR}, ADDRESS_SERVICE),
        ({}, None),
        (None, None),
    ],
)
def test_address_kind_from_details(address_data, expected):
    assert address_kind_from_biznes_details({"addressData": address_data}) == expected


def test_merge_keeps_kind_only_for_sole_trader():
    jdg = {"name": "Jan Test IT", "source": "CEIDG", "address_kind": ADDRESS_SERVICE}
    assert _merge(jdg, None)["address_kind"] == ADDRESS_SERVICE
    company = {"name": "Test S.A.", "source": "KRS", "address_kind": ADDRESS_SERVICE}
    assert _merge(company, {"krs": "0000000001"})["address_kind"] is None


def _patch_http(monkeypatch, handler):
    real = httpx.AsyncClient

    def client(*args, **kwargs):
        return real(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(registry_lookup.httpx, "AsyncClient", client)


def _search(source: str) -> dict:
    return {
        "companyList": [
            {"id": "ABC", "name": "Jan Test IT", "nip": "1234567890", "source": source}
        ]
    }


@pytest.mark.asyncio
async def test_lookup_reads_service_address_from_company_card(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path.rsplit("/", 1)[-1])
        if request.url.path.endswith("/SearchAdvance"):
            return httpx.Response(200, json=_search("CEIDG"))
        assert request.url.params["id"] == "ABC"
        return httpx.Response(
            200, json={"addressData": {"correspondenceAddress": _ADDR}}
        )

    _patch_http(monkeypatch, handler)
    found = await lookup_by_biznes("1234567890")
    assert found["address_kind"] == ADDRESS_SERVICE
    assert seen == ["SearchAdvance", "GetCompanyDetails"]


@pytest.mark.asyncio
async def test_company_card_failure_keeps_name(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/SearchAdvance"):
            return httpx.Response(200, json=_search("CEIDG"))
        return httpx.Response(500)

    _patch_http(monkeypatch, handler)
    found = await lookup_by_biznes("1234567890")
    assert found["name"] == "Jan Test IT"
    assert found["address_kind"] is None


@pytest.mark.asyncio
async def test_krs_company_skips_company_card(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/SearchAdvance")
        return httpx.Response(200, json=_search("KRS"))

    _patch_http(monkeypatch, handler)
    found = await lookup_by_biznes("1234567890")
    assert found["address_kind"] is None
