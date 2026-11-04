"""Klient API EBI24: podpis z wektora podręcznika, tylko odczyt, limity, błędy.

Bez sieci — ``httpx.MockTransport``. Dane fikcyjne; klucz, sekret i oczekiwane
wyniki pochodzą z sekcji „Sprawdzenie własnej implementacji” podręcznika 1.9.1.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.services.ebi24.client import (
    Ebi24ApiError,
    Ebi24Client,
    build_credentials,
    build_signature,
)
from app.services.ebi24.environment import Ebi24Config

VECTOR_KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="  # gitleaks:allow
VECTOR_SECRET = "ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8="  # gitleaks:allow
VECTOR_USER = "00000000-0000-4000-8000-000000000001"
VECTOR_ACCOUNT = "00000000-0000-4000-8000-000000000002"
VECTOR_TIMESTAMP = "1787738400000"
VECTOR_BODY = b'{"data":{"_schemaName":"INCOME_INVOICE"}}'
VECTOR_SIGNATURE = "YgDsTo/xWhQU6thXVod2WeCJd1iCJN/GppxLJBxrLF0="  # gitleaks:allow
VECTOR_CREDENTIALS = (
    "JBuoGXqCbbJTc7cfsIEnq7oFKS6vizJ8u0BQ1e/88H55BtDNF9bJ44VJ/QE6YI5C"  # gitleaks:allow
    "gDY/ekI8bujK13BUoQ9H6vLQqoGulQhEJGq8F4iMOsKfO3UEkm+L024xGOkDpM1K"  # gitleaks:allow
)

CONFIG = Ebi24Config(
    mode="uat",
    user_uuid=VECTOR_USER,
    account_uuid=VECTOR_ACCOUNT,
    communication_key=VECTOR_KEY,
    secret_phrase=VECTOR_SECRET,
)
INVOICE_XML = (
    Path(__file__).parent
    / "data"
    / "ksef"
    / "sales"
    / "9876543210-20261103-A1180C0FFEE1-5C.xml"
).read_bytes()


def _envelope(data: object, **extra: object) -> httpx.Response:
    return httpx.Response(200, json={"response": {"status": 0, "data": data, **extra}})


class _Clock:
    def __init__(self, moment_ms: int = 1787738400000) -> None:
        self.moment_ms = moment_ms
        self.slept: list[float] = []

    def now(self) -> datetime:
        return datetime.fromtimestamp(self.moment_ms / 1000, tz=timezone.utc)

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.moment_ms += int(seconds * 1000)


def _client(handler, clock: _Clock | None = None) -> Ebi24Client:
    clock = clock or _Clock()
    return Ebi24Client(
        CONFIG,
        transport=httpx.MockTransport(handler),
        now=clock.now,
        sleep=clock.sleep,
    )


def test_podpis_zgodny_z_wektorem_z_podrecznika() -> None:
    key = base64.b64decode(VECTOR_KEY)

    signature = build_signature(
        VECTOR_BODY, "bucket/index", VECTOR_TIMESTAMP, VECTOR_ACCOUNT, key
    )

    assert signature == VECTOR_SIGNATURE


def test_credentials_zgodne_z_wektorem_z_podrecznika() -> None:
    key = base64.b64decode(VECTOR_KEY)

    credentials = build_credentials(
        "SESSION_1", VECTOR_SECRET, "GENERATOR_1", VECTOR_TIMESTAMP, key
    )

    assert credentials == VECTOR_CREDENTIALS


def test_sekrety_poza_repr_konfiguracji() -> None:
    text = repr(CONFIG)

    assert VECTOR_KEY not in text
    assert VECTOR_SECRET not in text


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"mode": "off"}, "mode_off"),
        ({"user_uuid": ""}, "missing_user_uuid"),
        ({"account_uuid": ""}, "missing_account_uuid"),
        ({"communication_key": ""}, "missing_communication_key"),
        ({"secret_phrase": ""}, "missing_secret_phrase"),
        ({"communication_key": "nie-base64!"}, "invalid_communication_key"),
        # Poprawny base64, ale 16 bajtów zamiast 32 wymaganych przez AES-256.
        (
            {"communication_key": base64.b64encode(b"x" * 16).decode()},
            "invalid_communication_key",
        ),
    ],
)
def test_niepelna_konfiguracja_wylacza_integracje(overrides, reason) -> None:
    fields = {
        "mode": "uat",
        "user_uuid": VECTOR_USER,
        "account_uuid": VECTOR_ACCOUNT,
        "communication_key": VECTOR_KEY,
        "secret_phrase": VECTOR_SECRET,
        **overrides,
    }

    config = Ebi24Config(**fields)

    assert config.disabled_reason == reason
    assert config.enabled is False


def test_adresy_srodowisk_z_podrecznika() -> None:
    assert CONFIG.api_url == "https://test-api.ebi24.pl/system/api/v1/"
    prod = Ebi24Config("prod", VECTOR_USER, VECTOR_ACCOUNT, VECTOR_KEY, VECTOR_SECRET)
    assert prod.api_url == "https://api.ebi24.pl/system/api/v1/"


async def test_lista_dokumentow_wysyla_post_i_podpisuje_wyslane_bajty() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _envelope([{"_id": "A"}], startRow=0, endRow=1, actualTotalRows=7)

    async with _client(handler) as client:
        page = await client.list_documents(
            {"_schemaName": "INCOME_INVOICE"}, start_row=0, end_row=1
        )

    assert page.documents == ({"_id": "A"},)
    assert page.total == 7
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == "https://test-api.ebi24.pl/system/api/v1/bucket/index"
    assert request.headers["content-type"] == "application/json"
    assert request.headers["x-ebi24-user-uuid"] == VECTOR_USER
    assert request.headers["x-ebi24-account-uuid"] == VECTOR_ACCOUNT
    timestamp = str(1787738400000)
    assert request.headers["x-ebi24-signature"] == build_signature(
        request.content,
        "bucket/index",
        timestamp,
        VECTOR_ACCOUNT,
        base64.b64decode(VECTOR_KEY),
    )
    assert json.loads(request.content)["data"] == {"_schemaName": "INCOME_INVOICE"}


async def test_strona_listy_nie_przekracza_limitu_500_wierszy() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _envelope([], startRow=0, endRow=0, actualTotalRows=0)

    async with _client(handler) as client:
        await client.list_documents({}, start_row=100, end_row=5000)

    assert bodies[0]["startRow"] == 100
    assert bodies[0]["endRow"] == 600


async def test_akcja_spoza_listy_odczytu_nie_wychodzi_do_serwera() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _envelope([])

    async with _client(handler) as client:
        with pytest.raises(ValueError):
            await client._send("bucket/create", {"data": {}})  # noqa: SLF001

    assert calls == 0


async def test_znaczniki_rosna_a_zadania_ida_co_sekunde() -> None:
    timestamps: list[str] = []
    clock = _Clock()
    key = base64.b64decode(VECTOR_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        for candidate in range(clock.moment_ms - 5, clock.moment_ms + 5):
            if request.headers["x-ebi24-signature"] == build_signature(
                request.content, "bucket/index", str(candidate), VECTOR_ACCOUNT, key
            ):
                timestamps.append(str(candidate))
        return _envelope([], startRow=0, endRow=0, actualTotalRows=0)

    async with _client(handler, clock) as client:
        await client.list_documents({}, start_row=0, end_row=1)
        await client.list_documents({}, start_row=0, end_row=1)

    assert len(timestamps) == 2
    assert int(timestamps[1]) > int(timestamps[0])
    assert clock.slept == [1.0]


async def test_429_czeka_retry_after_i_ponawia_z_nowym_znacznikiem() -> None:
    signatures: list[str] = []
    clock = _Clock()

    def handler(request: httpx.Request) -> httpx.Response:
        signatures.append(request.headers["x-ebi24-signature"])
        if len(signatures) == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return _envelope([], startRow=0, endRow=0, actualTotalRows=0)

    async with _client(handler, clock) as client:
        await client.list_documents({}, start_row=0, end_row=1)

    assert 7.0 in clock.slept
    assert len(signatures) == 2
    assert signatures[0] != signatures[1]


async def test_dluga_blokada_429_przerywa_z_czasem_powrotu() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "3600"})

    async with _client(handler) as client:
        with pytest.raises(Ebi24ApiError) as caught:
            await client.list_documents({}, start_row=0, end_row=1)

    assert caught.value.category == "rate_limited"
    assert caught.value.retry_after == 3600.0


async def test_blad_sieci_ponawia_z_rosnacym_odstepem() -> None:
    attempts = 0
    clock = _Clock()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ConnectError("brak", request=request)
        return _envelope([], startRow=0, endRow=0, actualTotalRows=0)

    async with _client(handler, clock) as client:
        await client.list_documents({}, start_row=0, end_row=1)

    assert attempts == 3
    assert clock.slept == [1.0, 2.0]


async def test_trwala_awaria_sieci_to_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("brak", request=request)

    async with _client(handler) as client:
        with pytest.raises(Ebi24ApiError) as caught:
            await client.list_documents({}, start_row=0, end_row=1)

    assert caught.value.category == "unavailable"


@pytest.mark.parametrize(
    ("response", "category"),
    [
        (
            httpx.Response(401, headers={"content-type": "text/html"}, text="<html>"),
            "auth_failed",
        ),
        (
            httpx.Response(403, headers={"content-type": "text/html"}, text="<html>"),
            "not_authorized",
        ),
        (
            httpx.Response(200, headers={"content-type": "text/html"}, text="<html>"),
            "not_authorized",
        ),
        (
            httpx.Response(200, json={"response": {"status": -1, "data": "NIP 123"}}),
            "rejected",
        ),
        (httpx.Response(200, json={"response": {"status": -4}}), "rejected"),
        (httpx.Response(200, json={"inne": True}), "invalid_response"),
        (httpx.Response(418), "invalid_response"),
    ],
)
async def test_odpowiedzi_bledne_daja_kategorie_bez_tresci(response, category) -> None:
    async with _client(lambda _request: response) as client:
        with pytest.raises(Ebi24ApiError) as caught:
            await client.list_documents({}, start_row=0, end_row=1)

    assert caught.value.category == category
    assert "NIP 123" not in str(caught.value)


async def test_xml_ksef_zwraca_bajty_faktury() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/bucket/getKsefData")
        assert json.loads(request.content) == {"data": {"_id": "A"}}
        return httpx.Response(
            200, headers={"content-type": "application/xml"}, content=INVOICE_XML
        )

    async with _client(handler) as client:
        assert await client.get_ksef_xml("A") == INVOICE_XML


async def test_xml_ksef_z_archiwum_idzie_na_osobny_adres() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(
            200, headers={"content-type": "application/xml"}, content=INVOICE_XML
        )

    async with _client(handler) as client:
        await client.get_ksef_xml("A", archive=True)

    assert paths == ["/system/api/v1/archive/getKsefData"]


@pytest.mark.parametrize(
    ("response", "category"),
    [
        (
            httpx.Response(404, json={"response": {"status": -1, "data": "Brak"}}),
            "not_found",
        ),
        (
            httpx.Response(400, json={"response": {"status": -1, "data": "Zły _id"}}),
            "rejected",
        ),
        # Brak uprawnienia do odczytu ma tu kod 200 i kopertę JSON.
        (
            httpx.Response(200, json={"response": {"status": -1, "data": "Brak"}}),
            "rejected",
        ),
        (
            httpx.Response(
                200,
                headers={"content-type": "application/xml"},
                content=b"x" * (5 * 1024 * 1024 + 1),
            ),
            "too_large",
        ),
    ],
)
async def test_bledy_xml_ksef(response, category) -> None:
    async with _client(lambda _request: response) as client:
        with pytest.raises(Ebi24ApiError) as caught:
            await client.get_ksef_xml("A")

    assert caught.value.category == category


async def test_logi_bez_sekretow_i_tresci(caplog) -> None:
    caplog.set_level(logging.DEBUG, logger="app.services.ebi24.client")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": {"status": -1, "data": "NIP 123"}})

    async with _client(handler) as client:
        with pytest.raises(Ebi24ApiError):
            await client.list_documents({"customer": "Firma"}, start_row=0, end_row=1)

    text = caplog.text
    for forbidden in (VECTOR_KEY, VECTOR_SECRET, VECTOR_ACCOUNT, "NIP 123", "Firma"):
        assert forbidden not in text
