"""Rodzaj adresu JDG z CEIDG: stałe miejsce działalności vs tylko adres do doręczeń.

Kształt odpowiedzi biznes.gov.pl sprawdzony na żywo 23.10.2026 (NIP z umowy
generatora): JDG bez stałego miejsca ma w ``addressData`` tylko
``correspondenceAddress``. HTTP zaślepiony ``httpx.MockTransport``.
"""

from __future__ import annotations

import httpx
import pytest

from app.services.b2b_contract_generator import registry_lookup
from app.services.b2b_contract_generator.address_format import format_registry_address
from app.services.b2b_contract_generator.registry_lookup import (
    ADDRESS_PLACE_OF_BUSINESS,
    ADDRESS_SERVICE,
    _merge,
    address_kind_from_biznes_details,
    lookup_by_biznes,
)

_ADDR = {"street": "ul. Testowa", "buildingNumber": "1", "city": "Warszawa"}


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Biała Lista: wielkie litery, bez „ul.” (zgłoszenie działu umów 03.11.2026).
        ("TESTOWA 12/3, 00-001 WARSZAWA", "ul. Testowa 12/3, 00-001 Warszawa"),
        (
            "TESTOWA 118E/31, 31-416 RAWA MAZOWIECKA",
            "ul. Testowa 118E/31, 31-416 Rawa Mazowiecka",
        ),
        (
            "WAŁ TESTOWY 22/G, 03-994 BIELSKO-BIAŁA",
            "ul. Wał Testowy 22/G, 03-994 Bielsko-Biała",
        ),
        ("ŚW. JANA 7, 02-945 ŁÓDŹ", "ul. św. Jana 7, 02-945 Łódź"),
        (
            "DR. JANA TESTOWEGO 15, 30-393 KRAKÓW",
            "ul. dr. Jana Testowego 15, 30-393 Kraków",
        ),
        (
            "3 MAJA 5, 00-001 NOWE MIASTO NAD PILICĄ",
            "ul. 3 Maja 5, 00-001 Nowe Miasto nad Pilicą",
        ),
        (
            "ŻWIRKI I WIGURY 1, 00-001 WARSZAWA",
            "ul. Żwirki i Wigury 1, 00-001 Warszawa",
        ),
        ("MIESZKA I 12, 00-001 POZNAŃ", "ul. Mieszka I 12, 00-001 Poznań"),
        (
            "JANA III TESTOWEGO 4, 00-001 GDAŃSK",
            "ul. Jana III Testowego 4, 00-001 Gdańsk",
        ),
        ("POD LIPAMI 4, 00-001 WARSZAWA", "ul. Pod Lipami 4, 00-001 Warszawa"),
        ("TESTOWA 36 E, 00-001 WARSZAWA", "ul. Testowa 36 E, 00-001 Warszawa"),
        (
            "TESTOWA 10 LOK. 5, 00-001 WARSZAWA",
            "ul. Testowa 10 lok. 5, 00-001 Warszawa",
        ),
        # Rodzaj ulicy już jest — „ul.” nie wchodzi drugi raz.
        ("UL. TESTOWA 3, 43-360 BYSTRA", "ul. Testowa 3, 43-360 Bystra"),
        ("UL.TESTOWA 3, 43-360 BYSTRA", "ul. Testowa 3, 43-360 Bystra"),
        ("AL. TESTOWA 44/18, 54-106 WROCŁAW", "al. Testowa 44/18, 54-106 Wrocław"),
        (
            "ALEJA JANA PAWŁA II 20/1026, 00-133 WARSZAWA",
            "Aleja Jana Pawła II 20/1026, 00-133 Warszawa",
        ),
        ("OSIEDLE TESTOWE 4/42, 31-877 KRAKÓW", "Osiedle Testowe 4/42, 31-877 Kraków"),
        ("PLAC TESTOWY 1, 00-001 WARSZAWA", "Plac Testowy 1, 00-001 Warszawa"),
        ("RYNEK 5, 00-001 KRAKÓW", "Rynek 5, 00-001 Kraków"),
        # Miejscowość bez ulic: numer stoi przy nazwie miejscowości.
        ("NOWA WIEŚ 80B, 83-304 NOWA WIEŚ", "Nowa Wieś 80B, 83-304 Nowa Wieś"),
        ("NOWA-STACJA 46, 16-061 NOWA-STACJA", "Nowa-Stacja 46, 16-061 Nowa-Stacja"),
        ("Testowo 36 E, 26-650 Testowo", "Testowo 36 E, 26-650 Testowo"),
        # Zapis zwykły zostaje, dochodzi tylko brakujące „ul.”.
        ("Testowa 19, 84-242 Luzino", "ul. Testowa 19, 84-242 Luzino"),
        ("ul. Testowa 19, 84-242 Luzino", "ul. Testowa 19, 84-242 Luzino"),
        # Sam numer: nie ma czego nazwać ulicą.
        ("12, 00-001 WARSZAWA", "12, 00-001 Warszawa"),
    ],
)
def test_registry_address_reads_like_a_normal_address(raw, expected):
    assert format_registry_address(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_registry_address_empty_stays_empty(raw):
    assert format_registry_address(raw) is None


def test_registry_address_uses_street_field_when_the_registry_gave_it():
    """CEIDG API mówi wprost, czy jest ulica. Wieś z pocztą w innej miejscowości
    wygląda w tekście jak ulica, więc to pole ma pierwszeństwo przed zgadywaniem."""
    village = "WIERZBOWO 233, 22-417 STARE TESTOWO"
    assert format_registry_address(village) == "ul. Wierzbowo 233, 22-417 Stare Testowo"
    assert (
        format_registry_address(village, has_street=False)
        == "Wierzbowo 233, 22-417 Stare Testowo"
    )
    assert (
        format_registry_address("NOWA WIEŚ 1, 00-001 NOWA WIEŚ", has_street=True)
        == "ul. Nowa Wieś 1, 00-001 Nowa Wieś"
    )


def test_merge_carries_street_signal_only_from_the_ceidg_source():
    ceidg = {"name": "F", "source": "CEIDG", "has_street": False}
    assert _merge(ceidg, {"address": "A 1, 00-001 B"})["has_street"] is False
    assert _merge({"name": "F", "source": "CEIDG"}, None)["has_street"] is None


@pytest.mark.asyncio
async def test_company_lookup_endpoint_returns_formatted_address(monkeypatch):
    from app.api import b2b_contract_generator as api

    async def lookup(**_):
        return {
            "name": "Jan Test IT",
            "address": "TESTOWA 1, 00-001 WARSZAWA",
            "has_street": None,
            "source": "CEIDG",
        }

    monkeypatch.setattr(api, "lookup_company", lookup)
    monkeypatch.setattr(api, "_require_contract_generation", lambda _user: None)
    found = await api.company_lookup(current_user=object(), nip="1234567890", krs=None)
    assert found["address"] == "ul. Testowa 1, 00-001 Warszawa"


@pytest.mark.asyncio
async def test_sales_registry_lookup_keeps_raw_address(monkeypatch):
    """Kartoteka Sprzedaży wyciąga miasto z surowego adresu — poprawka dotyczy
    generatora umów, `lookup_company` zwraca rejestr bez zmian."""

    async def base(**_):
        return {"address": "TESTOWA 1, 00-001 WARSZAWA", "entity_type": "sole_trader"}

    monkeypatch.setattr(registry_lookup, "_lookup_company_base", base)
    found = await registry_lookup.lookup_company(nip="1234567890")
    assert found["address"] == "TESTOWA 1, 00-001 WARSZAWA"


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
