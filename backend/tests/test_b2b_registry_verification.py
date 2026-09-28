"""Sprawdzenie firmy w CEIDG/KRS przed wygenerowaniem umowy B2B (ticket 6).

Rejestry są podmienione `httpx.MockTransport`, a kształty odpowiedzi
odwzorowują to, co CEIDG v3 i KRS OpenAPI zwróciły na żywo 28.09.2026:
kilka wpisów CEIDG pod jednym NIP-em w dowolnej kolejności, HTTP 204 dla
brakującej firmy, dział 6 KRS z likwidacją i upadłością oraz spółka
wykreślona widoczna wyłącznie w odpisie pełnym.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from app.services.b2b_contract_generator import (
    registry_lookup,
    registry_verification,
)
from app.services.b2b_contract_generator.registry_lookup import (
    _parse_ceidg,
    pick_current_ceidg_firm,
)
from app.services.b2b_contract_generator.registry_verification import (
    UNVERIFIED,
    VERIFIED,
    WARN_CEIDG_DELETED,
    WARN_CEIDG_SUSPENDED,
    WARN_KRS_BANKRUPTCY,
    WARN_KRS_DELETED,
    WARN_KRS_LIQUIDATION,
    ceidg_warnings,
    krs_deletion_date,
    krs_warnings,
    verify_company,
)

NIP_JDG = "5260000001"
NIP_SPOLKA = "5260000002"
KRS = "0000123456"


def _firm(status: str, start: str, name: str, street: str) -> dict:
    return {
        "id": "1C0A30F0-17FD-4F94-B147-A8C2B336CF65",
        "nazwa": name,
        "status": status,
        "dataRozpoczecia": start,
        "adresDzialalnosci": {
            "ulica": street,
            "budynek": "5",
            "kod": "00-001",
            "miasto": "Warszawa",
        },
        "wlasciciel": {
            "imie": "Jan",
            "nazwisko": "Kowalski",
            "nip": NIP_JDG,
            "regon": "123456789",
        },
    }


def _odpis(name: str, dzial6: dict | None = None) -> dict:
    return {
        "odpis": {
            "rodzaj": "Aktualny",
            "naglowekA": {"numerKRS": KRS, "stanPozycji": 1},
            "dane": {
                "dzial1": {
                    "danePodmiotu": {
                        "nazwa": name,
                        "identyfikatory": {
                            "nip": NIP_SPOLKA,
                            "regon": "14567890000000",
                        },
                    },
                    "siedzibaIAdres": {
                        "adres": {
                            "ulica": "UL. PROSTA",
                            "nrDomu": "1",
                            "kodPocztowy": "00-002",
                            "miejscowosc": "WARSZAWA",
                        }
                    },
                },
                "dzial6": dzial6 or {},
            },
        }
    }


@pytest.fixture
def registries(monkeypatch: pytest.MonkeyPatch):
    """Podmienia sieć obu modułów na jeden handler; zwraca listę zapytań."""
    calls: list[httpx.Request] = []
    state: dict[str, Callable[[httpx.Request], httpx.Response]] = {}

    def install(handler: Callable[[httpx.Request], httpx.Response]) -> list:
        state["handler"] = handler
        return calls

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs.pop("transport", None)

        def route(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return state["handler"](request)

        return real_client(*args, transport=httpx.MockTransport(route), **kwargs)

    # Oba moduły trzymają ten sam obiekt `httpx`, więc jedna podmiana wystarcza.
    monkeypatch.setattr(registry_lookup.httpx, "AsyncClient", client_factory)
    monkeypatch.setattr(registry_lookup.settings, "CEIDG_API_TOKEN", "token")
    return install


def _white_list(krs: str | None) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "result": {
                "subject": {
                    "name": "X",
                    "nip": NIP_SPOLKA,
                    "krs": krs,
                    "workingAddress": "PROSTA 1, 00-002 WARSZAWA",
                }
            }
        },
    )


# ── Wybór wpisu CEIDG ────────────────────────────────────────────────────────


def test_active_firm_wins_over_older_deleted_one_regardless_of_order():
    old = _firm("WYKRESLONY", "2012-10-23", "Stara Firma - Jan Kowalski", "ul. Stara")
    new = _firm("AKTYWNY", "2021-09-01", "Nowa Firma - Jan Kowalski", "ul. Nowa")
    assert pick_current_ceidg_firm([old, new]) is new
    assert pick_current_ceidg_firm([new, old]) is new


def test_pending_start_beats_deleted_and_newest_deleted_wins_among_deleted():
    deleted = _firm("WYKRESLONY", "2014-06-03", "A", "ul. A")
    pending = _firm("OCZEKUJE_NA_ROZPOCZECIE_DZIALANOSCI", "2026-10-01", "B", "ul. B")
    assert pick_current_ceidg_firm([deleted, pending]) is pending
    older = _firm("WYKRESLONY", "2017-08-02", "C", "ul. C")
    newest = _firm("WYKRESLONY", "2024-03-01", "D", "ul. D")
    assert pick_current_ceidg_firm([older, newest, deleted]) is newest


def test_autofill_lookup_takes_the_current_firm_not_the_first_listed():
    """Do 28.09 `_parse_ceidg` brał `firmy[0]` — bywało nim stare przedsiębiorstwo."""
    data = {
        "firmy": [
            _firm("WYKRESLONY", "2007-07-02", "Stara Firma", "ul. Stara"),
            _firm("AKTYWNY", "2016-12-01", "Nowa Firma", "ul. Nowa"),
        ]
    }
    parsed = _parse_ceidg(data)
    assert parsed["name"] == "Nowa Firma"
    assert parsed["address"].startswith("UL. NOWA 5")


def test_village_address_without_street_keeps_the_locality():
    firm = _firm("AKTYWNY", "2020-01-01", "F", None)
    firm["adresDzialalnosci"] = {"budynek": "12", "kod": "05-252", "miasto": "Dąbrówka"}
    assert _parse_ceidg({"firmy": [firm]})["address"] == "DĄBRÓWKA 12, 05-252 DĄBRÓWKA"


# ── Reguły ostrzeżeń ─────────────────────────────────────────────────────────


def test_ceidg_statuses_give_warnings_only_for_suspended_and_deleted():
    assert ceidg_warnings(_firm("AKTYWNY", "2020-01-01", "F", "ul. A")) == []
    assert (
        ceidg_warnings(
            _firm("OCZEKUJE_NA_ROZPOCZECIE_DZIALANOSCI", "2026-10-01", "F", "x")
        )
        == []
    )
    suspended = ceidg_warnings(
        _firm("ZAWIESZONY", "2020-01-01", "F", "x"), {"dataZawieszenia": "2026-05-01"}
    )
    assert [w["code"] for w in suspended] == [WARN_CEIDG_SUSPENDED]
    assert "01.05.2026" in suspended[0]["message"]
    deleted = ceidg_warnings(_firm("WYKRESLONY", "2020-01-01", "F", "x"))
    assert [w["code"] for w in deleted] == [WARN_CEIDG_DELETED]
    assert "(od" not in deleted[0]["message"]


def test_krs_liquidation_from_section_6_or_name_suffix():
    by_section = krs_warnings(
        _odpis(
            "CON-RAIL SP. Z O.O.", {"likwidacja": [{"otwarcieLikwidacji": "UCHWAŁA"}]}
        )["odpis"]
    )
    assert [w["code"] for w in by_section] == [WARN_KRS_LIQUIDATION]
    by_name = krs_warnings(_odpis("ABC SPÓŁKA AKCYJNA W LIKWIDACJI")["odpis"])
    assert [w["code"] for w in by_name] == [WARN_KRS_LIQUIDATION]


def test_krs_bankruptcy_names_the_declaration_date_and_whether_it_ended():
    ongoing = krs_warnings(
        _odpis(
            "GETIN NOBLE BANK SPÓŁKA AKCYJNA W UPADŁOŚCI",
            {
                "postepowanieUpadlosciowe": [
                    {
                        "informacjaOOgloszeniuUpadlosci": {"data": "20.07.2023"},
                        "opisZakonczeniaProcesuUpadlosci": {},
                    }
                ]
            },
        )["odpis"]
    )
    assert [w["code"] for w in ongoing] == [WARN_KRS_BANKRUPTCY]
    assert "ogłoszona 20.07.2023" in ongoing[0]["message"]
    assert "zakończone" not in ongoing[0]["message"]

    ended = krs_warnings(
        _odpis(
            "XYZ SP. Z O.O.",
            {
                "postepowanieUpadlosciowe": [
                    {
                        "informacjaOOgloszeniuUpadlosci": {"data": "01.02.2020"},
                        "opisZakonczeniaProcesuUpadlosci": {"data": "01.02.2022"},
                    }
                ]
            },
        )["odpis"]
    )
    assert "postępowanie zakończone" in ended[0]["message"]


def test_other_section_6_entries_are_not_warnings():
    """Połączenie spółek albo pusta struktura działu 6 to zwykła spółka."""
    odpis = _odpis(
        "PKP SPÓŁKA AKCYJNA",
        {
            "polaczeniePodzialPrzeksztalcenie": [
                {"okreslenieOkolicznosci": "PRZEJĘCIE"}
            ],
            "likwidacja": [{}],
            "postepowanieUpadlosciowe": [{"opisZakonczeniaProcesuUpadlosci": {}}],
        },
    )["odpis"]
    assert krs_warnings(odpis) == []


def test_krs_deletion_read_from_the_last_entry_of_the_full_extract():
    full = {
        "naglowekP": {
            "stanPozycji": 2,
            "wpis": [
                {"opis": "REJESTRACJA", "dataWpisu": "01.01.2010"},
                {
                    "opis": "WYKREŚLENIE Z KRAJOWEGO REJESTRU SĄDOWEGO",
                    "dataWpisu": "24.09.2026",
                },
            ],
        }
    }
    assert krs_deletion_date(full) == (True, "24.09.2026")
    full["naglowekP"]["wpis"].append(
        {"opis": "ZMIANA DANYCH W REJESTRZE", "dataWpisu": "x"}
    )
    assert krs_deletion_date(full) == (False, None)


# ── Pełna ścieżka ────────────────────────────────────────────────────────────


async def test_sole_trader_verified_with_fresh_data_from_ceidg(registries):
    def handler(request: httpx.Request) -> httpx.Response:
        if "dane.biznes.gov.pl" in request.url.host:
            assert request.headers["Authorization"] == "Bearer token"
            return httpx.Response(
                200,
                json={
                    "firmy": [
                        _firm("WYKRESLONY", "2010-01-01", "Stara", "ul. Stara"),
                        _firm(
                            "AKTYWNY", "2023-09-25", "Nowa - Jan Kowalski", "ul. Nowa"
                        ),
                    ]
                },
            )
        return _white_list(None)

    calls = registries(handler)
    result = await verify_company(nip="526-000-00-01")
    assert result["status"] == VERIFIED
    assert result["registry"] == "ceidg"
    # JDG znaleziona → Biała Lista (dzienny limit zapytań) nie jest pytana.
    assert all("wl-api" not in c.url.host for c in calls)
    assert result["warnings"] == []
    assert result["company"]["name"] == "Nowa - Jan Kowalski"
    assert result["company"]["address"] == "UL. NOWA 5, 00-001 WARSZAWA"
    assert result["company"]["regon"] == "123456789"
    assert result["company"]["entity_type"] == "sole_trader"


async def test_suspended_sole_trader_is_verified_with_a_warning_and_date(registries):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/firmy"):
            return httpx.Response(
                200, json={"firmy": [_firm("ZAWIESZONY", "2019-01-01", "F", "ul. A")]}
            )
        if "/firma/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "firma": [{"status": "ZAWIESZONY", "dataZawieszenia": "2026-03-01"}]
                },
            )
        return _white_list(None)

    registries(handler)
    result = await verify_company(nip=NIP_JDG)
    assert result["status"] == VERIFIED
    assert [w["code"] for w in result["warnings"]] == [WARN_CEIDG_SUSPENDED]
    assert "01.03.2026" in result["warnings"][0]["message"]


async def test_company_goes_to_krs_with_number_from_the_white_list(registries):
    def handler(request: httpx.Request) -> httpx.Response:
        if "dane.biznes.gov.pl" in request.url.host:
            return httpx.Response(204)
        if "wl-api.mf.gov.pl" in request.url.host:
            return _white_list("123456")
        if "OdpisAktualny" in request.url.path:
            assert request.url.path.endswith(f"/{KRS}")
            return httpx.Response(
                200,
                json=_odpis(
                    "ABC SP. Z O.O. W LIKWIDACJI",
                    {"likwidacja": [{"otwarcieLikwidacji": "UCHWAŁA"}]},
                ),
            )
        raise AssertionError(request.url)

    registries(handler)
    result = await verify_company(nip=NIP_SPOLKA)
    assert result["status"] == VERIFIED
    assert result["registry"] == "krs"
    assert result["company"]["name"] == "ABC SP. Z O.O. W LIKWIDACJI"
    assert result["company"]["address"] == "UL. PROSTA 1, 00-002 WARSZAWA"
    assert result["company"]["entity_type"] == "company"
    assert [w["code"] for w in result["warnings"]] == [WARN_KRS_LIQUIDATION]


async def test_deleted_company_found_only_in_the_full_extract(registries):
    def handler(request: httpx.Request) -> httpx.Response:
        if "OdpisAktualny" in request.url.path:
            return httpx.Response(204)
        if "OdpisPelny" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "odpis": {
                        "naglowekP": {
                            "wpis": [
                                {
                                    "opis": "WYKREŚLENIE Z KRAJOWEGO REJESTRU SĄDOWEGO",
                                    "dataWpisu": "24.09.2026",
                                }
                            ]
                        }
                    }
                },
            )
        raise AssertionError(request.url)

    registries(handler)
    result = await verify_company(krs="123456")
    assert result["status"] == VERIFIED
    assert [w["code"] for w in result["warnings"]] == [WARN_KRS_DELETED]
    assert "24.09.2026" in result["warnings"][0]["message"]


async def test_unknown_krs_number_is_unverified_not_an_error(registries):
    registries(lambda request: httpx.Response(204))
    result = await verify_company(krs="999")
    assert result["status"] == UNVERIFIED
    assert "0000000999" in result["message"]


async def test_registry_down_is_unverified_with_a_reason(registries):
    def handler(request: httpx.Request) -> httpx.Response:
        if "dane.biznes.gov.pl" in request.url.host:
            raise httpx.ReadTimeout("timeout", request=request)
        return _white_list(None)

    registries(handler)
    result = await verify_company(nip=NIP_JDG)
    assert result["status"] == UNVERIFIED
    assert result["registry"] == "ceidg"
    assert "CEIDG" in result["message"]
    assert result["warnings"] == []


async def test_krs_server_error_is_unverified(registries):
    registries(lambda request: httpx.Response(503))
    result = await verify_company(krs=KRS)
    assert result["status"] == UNVERIFIED
    assert "KRS" in result["message"]


async def test_no_ceidg_token_for_a_sole_trader_says_so(registries, monkeypatch):
    registries(lambda request: _white_list(None))
    monkeypatch.setattr(registry_lookup.settings, "CEIDG_API_TOKEN", "")
    result = await verify_company(nip=NIP_JDG)
    assert result["status"] == UNVERIFIED
    assert "klucza API" in result["message"]


async def test_missing_nip_is_unverified_without_any_request(registries):
    calls = registries(lambda request: httpx.Response(500))
    result = await verify_company(nip="123")
    assert result["status"] == UNVERIFIED
    assert "NIP" in result["message"]
    assert calls == []


async def test_unexpected_crash_never_escapes(monkeypatch):
    async def boom(nip: str, krs: str) -> dict:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(registry_verification, "_verify", boom)
    result = await verify_company(nip=NIP_JDG)
    assert result["status"] == UNVERIFIED


async def test_slow_registries_hit_the_total_ceiling(monkeypatch):
    """Użytkownik czeka po kliknięciu „Pobierz DOCX” — sprawdzenie ma sufit."""
    import asyncio

    async def slow(nip: str, krs: str) -> dict:
        await asyncio.sleep(5)
        raise AssertionError("nie powinno dojść do końca")

    monkeypatch.setattr(registry_verification, "_verify", slow)
    monkeypatch.setattr(registry_verification, "_TOTAL_TIMEOUT_SECONDS", 0.05)
    result = await verify_company(nip=NIP_JDG)
    assert result["status"] == UNVERIFIED
    assert "czasie" in result["message"]
