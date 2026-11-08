"""Uwierzytelnienie certyfikatem w KSeF: podpis XAdES, kolejność metod, konfiguracja.

Bez sieci. Fałszywy serwer sprawdza podpis niezależnie od kodu, który go składa
(``tests/_ksef_fake.verify_xades``). Przebieg na TEST MF: ``test_hr_ksef_xades_mf.py``.
"""

from __future__ import annotations

import base64
import logging
from datetime import timedelta

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID
from lxml import etree

from app.core.config import settings
from app.services.hr.ksef import client as ksef_client
from app.services.hr.ksef import environment, xades
from app.services.hr.ksef.client import KsefApiError, KsefClient
from tests._ksef_fake import BASE, COMPANY_NIP, TOKEN, Clock, FakeKsef, verify_xades

DS = "{http://www.w3.org/2000/09/xmldsig#}"
XADES = "{http://uri.etsi.org/01903/v1.3.2#}"
CHALLENGE = "20261017-CR-0000000000-0000000000-00"


@pytest.fixture(autouse=True)
def _fresh():
    ksef_client.forget_sessions()
    xades.load_identity.cache_clear()
    yield
    ksef_client.forget_sessions()
    xades.load_identity.cache_clear()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def fake(clock) -> FakeKsef:
    return FakeKsef(clock)


def _pem_cert(key, clock: Clock, *, days: int = 60) -> str:
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "Fikcyjna Spółka"),
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PL"),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(4242)
        .not_valid_before(clock() - timedelta(days=1))
        .not_valid_after(clock() + timedelta(days=days))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


def _pem_key(key, password: bytes | None = None) -> str:
    algorithm = (
        serialization.BestAvailableEncryption(password)
        if password
        else serialization.NoEncryption()
    )
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, algorithm
    ).decode("ascii")


def _identity(clock: Clock, key=None, *, days: int = 60) -> xades.SigningIdentity:
    key = key or ec.generate_private_key(ec.SECP256R1())
    return xades.load_identity(_pem_cert(key, clock, days=days), _pem_key(key))


class _Sleeps(list):
    async def __call__(self, seconds: float) -> None:
        self.append(seconds)


def _client(fake, clock, *, token: str = TOKEN, identity=None) -> KsefClient:
    return KsefClient(
        BASE,
        context_nip=COMPANY_NIP,
        token=token,
        identity=identity,
        transport=fake.transport,
        sleep=_Sleeps(),
        now=clock,
    )


# ── Podpis ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", ["ec", "rsa"])
def test_podpis_przechodzi_niezalezna_kontrole(clock, kind):
    key = (
        ec.generate_private_key(ec.SECP256R1())
        if kind == "ec"
        else rsa.generate_private_key(public_exponent=65537, key_size=2048)
    )
    document = xades.signed_auth_request(
        CHALLENGE, COMPANY_NIP, _identity(clock, key), clock()
    )
    assert verify_xades(document) == (CHALLENGE, COMPANY_NIP)


def test_zmiana_nipu_po_podpisie_psuje_skrot(clock):
    document = xades.signed_auth_request(
        CHALLENGE, COMPANY_NIP, _identity(clock), clock()
    )
    with pytest.raises(AssertionError):
        verify_xades(document.replace(COMPANY_NIP.encode(), b"1234563218"))


def test_ecdsa_ma_postac_r_s_a_nie_der(clock):
    root = etree.fromstring(
        xades.signed_auth_request(CHALLENGE, COMPANY_NIP, _identity(clock), clock())
    )
    value = base64.b64decode(root.find(f"{DS}Signature/{DS}SignatureValue").text)
    assert len(value) == 64


def test_dokument_zgodny_ze_schematem_i_opisuje_certyfikat(clock):
    identity = _identity(clock)
    root = etree.fromstring(
        xades.signed_auth_request(CHALLENGE, COMPANY_NIP, identity, clock())
    )
    names = [etree.QName(child).localname for child in root]
    assert names == [
        "Challenge",
        "ContextIdentifier",
        "SubjectIdentifierType",
        "Signature",
    ]
    assert root[2].text == "certificateSubject"
    assert root.findtext(f".//{XADES}SigningTime") == "2026-10-17T11:59:00Z"
    assert root.findtext(f".//{DS}X509SerialNumber") == "4242"
    assert root.findtext(f".//{XADES}CertDigest/{DS}DigestValue") == (
        base64.b64encode(identity.certificate.fingerprint(hashes.SHA256())).decode()
    )


# ── Wczytanie certyfikatu ────────────────────────────────────────────────────


def test_przyjmuje_pem_z_lamaniami_w_env_i_base64(clock):
    key = ec.generate_private_key(ec.SECP256R1())
    cert, private = _pem_cert(key, clock), _pem_key(key)
    fingerprint = xades.load_identity(cert, private).fingerprint

    escaped = xades.load_identity(
        cert.replace("\n", "\\n"), private.replace("\n", "\\n")
    )
    encoded = xades.load_identity(
        base64.b64encode(cert.encode()).decode(),
        base64.b64encode(private.encode()).decode(),
    )
    assert escaped.fingerprint == encoded.fingerprint == fingerprint


def test_klucz_z_haslem(clock):
    key = ec.generate_private_key(ec.SECP256R1())
    protected = _pem_key(key, b"haslo-testowe")
    cert = _pem_cert(key, clock)

    assert xades.load_identity(cert, protected, "haslo-testowe")
    with pytest.raises(xades.CertificateError):
        xades.load_identity(cert, protected, "zle-haslo")
    with pytest.raises(xades.CertificateError):
        xades.load_identity(cert, protected)


def test_klucz_niepasujacy_do_certyfikatu(clock):
    cert = _pem_cert(ec.generate_private_key(ec.SECP256R1()), clock)
    other = _pem_key(ec.generate_private_key(ec.SECP256R1()))
    with pytest.raises(xades.CertificateError, match="nie pasuje"):
        xades.load_identity(cert, other)


def test_za_slaby_klucz(clock):
    key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    with pytest.raises(xades.CertificateError, match="2048"):
        xades.load_identity(_pem_cert(key, clock), _pem_key(key))


@pytest.mark.parametrize("value", ["", "to nie jest certyfikat", "AAAA"])
def test_smieci_zamiast_certyfikatu(clock, value):
    key = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(xades.CertificateError):
        xades.load_identity(value, _pem_key(key))


def test_blad_wczytania_nie_zdradza_klucza(clock):
    key = ec.generate_private_key(ec.SECP256R1())
    private = _pem_key(key)
    with pytest.raises(xades.CertificateError) as caught:
        xades.load_identity("to nie jest certyfikat", private)
    assert "PRIVATE" not in str(caught.value)


def test_repr_tozsamosci_nie_zawiera_klucza(clock):
    assert "private_key" not in repr(_identity(clock))


# ── Kolejność metod ──────────────────────────────────────────────────────────


async def test_certyfikat_idzie_pierwszy_a_token_nie_jest_uzywany(fake, clock):
    async with _client(fake, clock, identity=_identity(clock)) as client:
        assert await client.access_token()

    assert fake.count("POST", "/auth/xades-signature") == 1
    assert fake.count("POST", "/auth/ksef-token") == 0
    assert fake.decrypted == []


async def test_sam_certyfikat_bez_tokenu_wystarcza(fake, clock):
    async with _client(fake, clock, token="", identity=_identity(clock)) as client:
        assert await client.access_token()
    assert fake.count("POST", "/auth/ksef-token") == 0


async def test_odmowa_certyfikatu_przechodzi_na_token_i_krzyczy_w_logu(
    fake, clock, caplog
):
    fake.auth_codes = [460, 200]
    with caplog.at_level(logging.ERROR, logger=ksef_client.__name__):
        async with _client(fake, clock, identity=_identity(clock)) as client:
            assert await client.access_token()

    assert fake.count("POST", "/auth/xades-signature") == 1
    assert fake.count("POST", "/auth/ksef-token") == 1
    assert "przejście na token" in caplog.text
    assert TOKEN not in caplog.text


async def test_certyfikat_po_terminie_nie_pyta_mf_i_idzie_tokenem(fake, clock):
    identity = _identity(clock, days=1)
    clock.advance(days=2)
    async with _client(fake, clock, identity=identity) as client:
        assert await client.access_token()

    assert fake.count("POST", "/auth/xades-signature") == 0
    assert fake.count("POST", "/auth/ksef-token") == 1


async def test_odmowa_certyfikatu_bez_tokenu_konczy_sie_bledem(fake, clock):
    fake.auth_codes = [460]
    async with _client(fake, clock, token="", identity=_identity(clock)) as client:
        with pytest.raises(KsefApiError) as caught:
            await client.access_token()
    assert caught.value.category == "auth_failed"
    assert caught.value.code == 460
    assert "błąd certyfikatu" in caught.value.message


async def test_awaria_mf_nie_przechodzi_na_token(fake, clock):
    fake.script[("POST", "/auth/xades-signature")] = [
        httpx.Response(503),
        httpx.Response(503),
        httpx.Response(503),
    ]
    async with _client(fake, clock, identity=_identity(clock)) as client:
        with pytest.raises(KsefApiError) as caught:
            await client.access_token()
    assert caught.value.category == "unavailable"
    assert fake.count("POST", "/auth/ksef-token") == 0


async def test_limit_mf_nie_przechodzi_na_token(fake, clock):
    fake.script[("POST", "/auth/xades-signature")] = [
        httpx.Response(429, headers={"Retry-After": "600"}),
    ]
    async with _client(fake, clock, identity=_identity(clock)) as client:
        with pytest.raises(KsefApiError) as caught:
            await client.access_token()
    assert caught.value.category == "rate_limited"
    assert fake.count("POST", "/auth/ksef-token") == 0


async def test_bez_certyfikatu_po_staremu_token(fake, clock):
    async with _client(fake, clock) as client:
        assert await client.access_token()
    assert fake.count("POST", "/auth/xades-signature") == 0
    assert fake.count("POST", "/auth/ksef-token") == 1


# ── Konfiguracja ─────────────────────────────────────────────────────────────


def _configure(monkeypatch, *, token="", certificate="", key="", password="") -> None:
    monkeypatch.setattr(settings, "KSEF_MODE", "test")
    monkeypatch.setattr(settings, "KSEF_CONTEXT_NIP", "1234563218")
    monkeypatch.setattr(settings, "KSEF_TOKEN", token)
    monkeypatch.setattr(settings, "KSEF_CERTIFICATE", certificate)
    monkeypatch.setattr(settings, "KSEF_CERTIFICATE_KEY", key)
    monkeypatch.setattr(settings, "KSEF_CERTIFICATE_KEY_PASSWORD", password)


def test_sam_certyfikat_wlacza_integracje_a_klucz_nie_trafia_do_repr(
    monkeypatch, clock
):
    key = ec.generate_private_key(ec.SECP256R1())
    private = _pem_key(key)
    _configure(monkeypatch, certificate=_pem_cert(key, clock), key=private)

    config = environment.load_config()

    assert config.enabled and config.identity is not None
    assert not config.certificate_invalid
    assert "PRIVATE" not in repr(config)


def test_zepsuty_certyfikat_przy_tokenie_nie_wylacza_integracji(monkeypatch):
    _configure(monkeypatch, token=TOKEN, certificate="zle", key="zle")

    config = environment.load_config()

    assert config.enabled
    assert config.identity is None
    assert config.certificate_invalid


def test_zepsuty_certyfikat_bez_tokenu_ma_wlasny_powod(monkeypatch):
    _configure(monkeypatch, certificate="zle", key="zle")
    assert environment.load_config().disabled_reason == "invalid_certificate"


def test_brak_obu_to_dotychczasowy_powod(monkeypatch):
    _configure(monkeypatch)
    assert environment.load_config().disabled_reason == "missing_token"
