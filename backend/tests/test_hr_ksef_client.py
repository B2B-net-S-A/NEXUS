"""Klient KSeF 2.0 (R1): numer KSeF, szyfrowanie tokenu, uwierzytelnienie, metadane, XML.

Bez sieci — fałszywy serwer z ``tests/_ksef_fake.py`` (odpowiedzi w kształcie
ze specyfikacji OpenAPI MF). Dane fikcyjne.
"""

from __future__ import annotations

import base64
import logging
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.services.hr.ksef import client as ksef_client
from app.services.hr.ksef import crypto, numbers
from app.services.hr.ksef.client import KsefApiError, KsefClient
from tests._ksef_fake import (
    ANNA_INVOICE,
    BASE,
    COMPANY_NIP,
    OLA_INVOICE,
    OLA_NIP,
    TOKEN,
    Clock,
    FakeKsef,
    rate_limited,
)


@pytest.fixture(autouse=True)
def _fresh_sessions():
    ksef_client.forget_sessions()
    yield
    ksef_client.forget_sessions()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def fake(clock) -> FakeKsef:
    return FakeKsef(clock)


class _Sleeps(list):
    async def __call__(self, seconds: float) -> None:
        self.append(seconds)


def _client(
    fake: FakeKsef, clock: Clock, sleeps=None, *, token: str = TOKEN
) -> KsefClient:
    return KsefClient(
        BASE,
        context_nip=COMPANY_NIP,
        token=token,
        transport=fake.transport,
        sleep=sleeps if sleeps is not None else _Sleeps(),
        now=clock,
    )


# ── Numer KSeF ───────────────────────────────────────────────────────────────


def test_suma_kontrolna_crc8_jak_w_dokumentacji_mf():
    # Wektor z przykładowej odpowiedzi /invoices/query/metadata w specyfikacji MF.
    assert numbers.is_valid("5555555555-20250828-010080615740-E4")
    assert numbers.checksum("5555555555-20250828-010080615740") == "E4"
    assert numbers.is_valid(OLA_INVOICE)
    assert numbers.make(OLA_NIP, date(2026, 10, 3), "5f2a9c0d71b3") == OLA_INVOICE


@pytest.mark.parametrize(
    "number",
    [
        OLA_INVOICE[:-2] + "00",  # zła suma kontrolna
        OLA_INVOICE.lower(),  # małe litery w części szesnastkowej
        "1234563218-20261332-5F2A9C0D71B3-C3",  # nie ma takiego dnia
        "1234563218-20261003-5F2A9C-0D71B3-C3",  # format 36 znaków z KSeF 1.0
        "",
        None,
        "../../etc/passwd",
    ],
)
def test_niepoprawny_numer_ksef(number):
    assert not numbers.is_valid(number)


# ── Klucz publiczny i szyfrowanie ────────────────────────────────────────────


def test_token_szyfrowany_rsa_oaep_sha256(fake, clock):
    key = crypto.pick_token_key(fake._certificates(clock()), clock())
    assert key.public_key_id == fake.public_key_id
    encrypted = crypto.encrypt_token(TOKEN, 1760702400123, key.public_key)
    plaintext = fake.private_key.decrypt(
        base64.b64decode(encrypted),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    assert plaintext == f"{TOKEN}|1760702400123".encode()


def test_wybor_klucza_pomija_niewazne_i_inne_przeznaczenie(fake, clock):
    now = clock()
    certificates = fake._certificates(now)
    expired = dict(
        certificates[1], validTo="2026-01-01T00:00:00+00:00", publicKeyId="stary"
    )
    assert crypto.pick_token_key(
        [certificates[0], expired, certificates[1]], now
    ).public_key_id == (fake.public_key_id)
    with pytest.raises(crypto.PublicKeyError):
        crypto.pick_token_key([certificates[0], expired], now)


def test_klucz_jako_sam_subject_public_key_info(fake, clock):
    # Przykład w specyfikacji ma w polu „certificate” sam klucz (SPKI), nie certyfikat.
    from cryptography.hazmat.primitives import serialization

    spki = fake.private_key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    entry = {
        "certificate": base64.b64encode(spki).decode(),
        "publicKeyId": "spki",
        "usage": ["KsefTokenEncryption"],
    }
    assert isinstance(
        crypto.pick_token_key([entry], clock()).public_key, rsa.RSAPublicKey
    )


# ── Uwierzytelnienie ─────────────────────────────────────────────────────────


async def test_uwierzytelnienie_tokenem_pelny_przebieg(fake, clock, caplog):
    caplog.set_level(logging.DEBUG)
    sleeps = _Sleeps()
    async with _client(fake, clock, sleeps) as ksef:
        access = await ksef.access_token()
    assert access.startswith("acc-")
    assert fake.paths() == [
        "POST /auth/challenge",
        "GET /security/public-key-certificates",
        "POST /auth/ksef-token",
        "GET /auth/20261017-AU-0000000000-0000000000-3",
        "GET /auth/20261017-AU-0000000000-0000000000-3",
        "POST /auth/token/redeem",
    ]
    body = fake.bodies[2]
    assert body["contextIdentifier"] == {"type": "Nip", "value": COMPANY_NIP}
    assert body["publicKeyId"] == fake.public_key_id
    assert TOKEN not in str(body)
    # Serwer odszyfrował dokładnie „token|timestampMs” z challenge'a.
    assert fake.decrypted == [f"{TOKEN}|{int(clock().timestamp() * 1000)}"]
    assert sleeps == [0.5]  # status 100, potem 200
    assert fake.calls[0].headers["X-Error-Format"] == "problem-details"
    assert TOKEN not in caplog.text


async def test_token_dostepu_z_pamieci_i_odswiezenie(fake, clock):
    async with _client(fake, clock) as ksef:
        first = await ksef.access_token()
    async with _client(fake, clock) as ksef:
        assert await ksef.access_token() == first
    assert fake.count("POST", "/auth/challenge") == 1

    clock.advance(minutes=20)  # access wygasł, refresh ważny 7 dni
    async with _client(fake, clock) as ksef:
        refreshed = await ksef.access_token()
    assert refreshed != first
    assert fake.count("POST", "/auth/token/refresh") == 1
    assert fake.count("POST", "/auth/challenge") == 1


async def test_wygasly_refresh_to_nowe_uwierzytelnienie(fake, clock):
    async with _client(fake, clock) as ksef:
        await ksef.access_token()
    clock.advance(days=8)
    async with _client(fake, clock) as ksef:
        await ksef.access_token()
    assert fake.count("POST", "/auth/challenge") == 2
    assert fake.count("POST", "/auth/token/refresh") == 0


async def test_odrzucony_refresh_to_nowe_uwierzytelnienie(fake, clock):
    async with _client(fake, clock) as ksef:
        await ksef.access_token()
    clock.advance(minutes=20)
    fake.refresh.clear()  # MF unieważnił sesję
    fake.auth_codes = [200]
    async with _client(fake, clock) as ksef:
        await ksef.access_token()
    assert fake.count("POST", "/auth/token/refresh") == 1
    assert fake.count("POST", "/auth/challenge") == 2


async def test_zly_token_status_450(fake, clock):
    async with _client(fake, clock, token="zly-token") as ksef:
        with pytest.raises(KsefApiError) as caught:
            await ksef.access_token()
    assert caught.value.category == "auth_failed"
    assert caught.value.code == 450
    assert "nieprawidłowy" in caught.value.message
    assert fake.count("POST", "/auth/token/redeem") == 0


async def test_nieznany_klucz_mf_pobiera_liste_ponownie(fake, clock):
    async with _client(fake, clock) as ksef:
        await ksef.access_token()
    ksef_client._SESSIONS.clear()
    # Klucz z pamięci procesu został wycofany: pierwsza próba 21470, druga z nowym.
    fake.script[("POST", "/auth/ksef-token")] = [
        httpx.Response(400, json={"errors": [{"code": 21470}]})
    ]
    fake.auth_codes = [200]
    async with _client(fake, clock) as ksef:
        await ksef.access_token()
    assert fake.count("GET", "/security/public-key-certificates") == 2
    assert fake.count("POST", "/auth/ksef-token") == 3


async def test_uwierzytelnienie_ciagle_w_toku_to_unavailable(fake, clock):
    fake.auth_codes = [100]
    sleeps = _Sleeps()
    async with _client(fake, clock, sleeps) as ksef:
        with pytest.raises(KsefApiError) as caught:
            await ksef.access_token()
    assert caught.value.category == "unavailable"
    assert len(sleeps) == len(ksef_client.AUTH_POLL_DELAYS)


async def test_wygasly_access_w_trakcie_to_jedno_ponowienie(fake, clock):
    async with _client(fake, clock) as ksef:
        await ksef.access_token()
        fake.access.clear()  # serwer unieważnił token przed jego datą
        fake.auth_codes = [200]
        page = await ksef.query_metadata(
            subject_type="Subject2", date_from="2026-10-01T00:00:00.000+00:00"
        )
    assert len(page.invoices) == 4
    assert fake.count("POST", "/invoices/query/metadata") == 2


# ── Metadane ─────────────────────────────────────────────────────────────────


async def test_metadane_jako_nabywca_okno_permanent_storage(fake, clock):
    async with _client(fake, clock) as ksef:
        page = await ksef.query_metadata(
            subject_type="Subject2",
            date_from="2026-10-01T00:00:00.000+00:00",
            page_size=10,
        )
    request = fake.calls[-1]
    body = fake.bodies[-1]
    assert body == {
        "subjectType": "Subject2",
        "dateRange": {
            "dateType": "PermanentStorage",
            "from": "2026-10-01T00:00:00.000+00:00",
            "restrictToPermanentStorageHwmDate": True,
        },
    }
    assert request.url.params["sortOrder"] == "Asc"
    assert request.url.params["pageSize"] == "10"
    assert request.headers["Authorization"].startswith("Bearer acc-")
    assert [item["ksefNumber"] for item in page.invoices][:2] == [
        OLA_INVOICE,
        ANNA_INVOICE,
    ]
    assert page.has_more is False
    assert page.hwm == "2026-10-17T12:00:00.000+00:00"


async def test_metadane_jako_sprzedawca_subject1_dla_kolejnego_etapu(fake, clock):
    async with _client(fake, clock) as ksef:
        page = await ksef.query_metadata(
            subject_type="Subject1",
            date_from="2026-10-01T00:00:00.000+00:00",
            date_to="2026-10-31T00:00:00.000+00:00",
            date_type="Issue",
            seller_nip=COMPANY_NIP,
        )
    body = fake.bodies[-1]
    assert body["subjectType"] == "Subject1"
    assert body["sellerNip"] == COMPANY_NIP
    assert body["dateRange"] == {
        "dateType": "Issue",
        "from": "2026-10-01T00:00:00.000+00:00",
        "to": "2026-10-31T00:00:00.000+00:00",
    }
    assert page.invoices == []


async def test_nieobslugiwany_subject_type_bez_zapytania(fake, clock):
    async with _client(fake, clock) as ksef:
        with pytest.raises(ValueError):
            await ksef.query_metadata(subject_type="Subject3", date_from="2026-10-01")
    assert fake.calls == []


async def test_odpowiedz_bez_listy_faktur_to_invalid_response(fake, clock):
    async with _client(fake, clock) as ksef:
        await ksef.access_token()
        fake.script[("POST", "/invoices/query/metadata")] = [
            httpx.Response(200, json={"invoices": "nie lista"})
        ]
        with pytest.raises(KsefApiError) as caught:
            await ksef.query_metadata(subject_type="Subject2", date_from="2026-10-01")
    assert caught.value.category == "invalid_response"


# ── Limity i awarie ──────────────────────────────────────────────────────────


async def test_krotka_blokada_429_czeka_retry_after(fake, clock):
    sleeps = _Sleeps()
    async with _client(fake, clock, sleeps) as ksef:
        await ksef.access_token()
        fake.script[("POST", "/invoices/query/metadata")] = [rate_limited(7)]
        page = await ksef.query_metadata(
            subject_type="Subject2", date_from="2026-10-01T00:00:00Z"
        )
    assert 7.0 in sleeps
    assert len(page.invoices) == 4


async def test_dluga_blokada_429_przerywa_z_retry_after(fake, clock):
    async with _client(fake, clock) as ksef:
        await ksef.access_token()
        fake.script[("POST", "/invoices/query/metadata")] = [rate_limited(900)]
        with pytest.raises(KsefApiError) as caught:
            await ksef.query_metadata(
                subject_type="Subject2", date_from="2026-10-01T00:00:00Z"
            )
    assert caught.value.category == "rate_limited"
    assert caught.value.retry_after == 900


async def test_retry_after_jako_data_http(fake, clock):
    later = (clock() + timedelta(seconds=20)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    sleeps = _Sleeps()
    async with _client(fake, clock, sleeps) as ksef:
        await ksef.access_token()
        fake.script[("POST", "/invoices/query/metadata")] = [
            httpx.Response(429, headers={"Retry-After": later})
        ]
        await ksef.query_metadata(
            subject_type="Subject2", date_from="2026-10-01T00:00:00Z"
        )
    assert 20.0 in sleeps


async def test_trzecie_429_z_rzedu_przerywa(fake, clock):
    async with _client(fake, clock) as ksef:
        await ksef.access_token()
        fake.script[("POST", "/invoices/query/metadata")] = [
            rate_limited(1) for _ in range(3)
        ]
        with pytest.raises(KsefApiError) as caught:
            await ksef.query_metadata(
                subject_type="Subject2", date_from="2026-10-01T00:00:00Z"
            )
    assert caught.value.category == "rate_limited"


async def test_bledy_serwera_ponawiane_potem_unavailable(fake, clock):
    sleeps = _Sleeps()
    async with _client(fake, clock, sleeps) as ksef:
        await ksef.access_token()
        fake.script[("POST", "/invoices/query/metadata")] = [
            httpx.Response(503) for _ in range(3)
        ]
        with pytest.raises(KsefApiError) as caught:
            await ksef.query_metadata(
                subject_type="Subject2", date_from="2026-10-01T00:00:00Z"
            )
    assert caught.value.category == "unavailable"
    assert sleeps[-2:] == list(ksef_client.SERVER_ERROR_DELAYS)


async def test_brak_sieci_to_unavailable_bez_tokenu_w_logu(clock, caplog):
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("brak sieci")

    caplog.set_level(logging.DEBUG)
    async with KsefClient(
        BASE,
        context_nip=COMPANY_NIP,
        token=TOKEN,
        transport=httpx.MockTransport(broken),
        sleep=_Sleeps(),
        now=clock,
    ) as ksef:
        with pytest.raises(KsefApiError) as caught:
            await ksef.access_token()
    assert caught.value.category == "unavailable"
    assert TOKEN not in caplog.text


async def test_brak_uprawnienia_403(fake, clock):
    async with _client(fake, clock) as ksef:
        await ksef.access_token()
        fake.script[("POST", "/invoices/query/metadata")] = [
            httpx.Response(403, json={"reasonCode": "missing-permissions"})
        ]
        with pytest.raises(KsefApiError) as caught:
            await ksef.query_metadata(
                subject_type="Subject2", date_from="2026-10-01T00:00:00Z"
            )
    assert caught.value.category == "forbidden"
    assert "odczytu faktur" in caught.value.message


# ── XML faktury ──────────────────────────────────────────────────────────────


async def test_pobranie_xml_z_kontrola_skrotu(fake, clock):
    async with _client(fake, clock) as ksef:
        content = await ksef.download_invoice(OLA_INVOICE)
    assert content == fake.xml[OLA_INVOICE]
    assert fake.calls[-1].headers["Accept"] == "application/xml"


async def test_skrot_niezgodny_z_naglowkiem_to_invalid_response(fake, clock):
    async with _client(fake, clock) as ksef:
        await ksef.access_token()
        fake.script[("GET", "/invoices/ksef/")] = [
            httpx.Response(
                200, content=b"<Faktura/>", headers={"x-ms-meta-hash": "AAAA"}
            )
        ]
        with pytest.raises(KsefApiError) as caught:
            await ksef.download_invoice(OLA_INVOICE)
    assert caught.value.category == "invalid_response"


async def test_faktura_jeszcze_niegotowa_21165(fake, clock):
    fake.not_ready.add(OLA_INVOICE)
    async with _client(fake, clock) as ksef:
        with pytest.raises(KsefApiError) as caught:
            await ksef.download_invoice(OLA_INVOICE)
    assert caught.value.category == "not_ready"
    assert caught.value.code == 21165


async def test_zly_numer_bez_zapytania(fake, clock):
    async with _client(fake, clock) as ksef:
        with pytest.raises(KsefApiError):
            await ksef.download_invoice("../../security/public-key-certificates")
    assert fake.calls == []


async def test_za_duzy_plik(fake, clock, monkeypatch):
    monkeypatch.setattr(ksef_client, "MAX_XML_BYTES", 100)
    async with _client(fake, clock) as ksef:
        with pytest.raises(KsefApiError) as caught:
            await ksef.download_invoice(OLA_INVOICE)
    assert caught.value.category == "too_large"


def test_parse_instant_z_siedmioma_cyframi_ulamka():
    moment = ksef_client.parse_instant("2025-07-11T12:23:56.0154302+00:00")
    assert moment == datetime(2025, 7, 11, 12, 23, 56, 15430, tzinfo=timezone.utc)
    assert ksef_client.parse_instant("nie data") is None
