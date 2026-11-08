"""Uwierzytelnienie XAdES na prawdziwym środowisku TEST MF. Domyślnie pominięte.

Uruchomienie (z ``backend/``)::

    KSEF_TEST_MF=1 python -m pytest tests/test_hr_ksef_xades_mf.py -v -s

Bez danych spółki: losowy NIP i certyfikat samopodpisany, co MF dopuszcza
wyłącznie na TEST (``srodowiska.md``). Ostatni test przechodzi drogę produkcyjną:
wniosek o certyfikat KSeF typu Authentication i logowanie tym certyfikatem.
"""

from __future__ import annotations

import asyncio
import base64
import os
import random
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID, ObjectIdentifier

from app.services.hr.ksef import client as ksef_client
from app.services.hr.ksef import xades
from app.services.hr.ksef.client import KsefClient
from app.services.hr.ksef.environment import API_URLS

pytestmark = pytest.mark.skipif(
    os.environ.get("KSEF_TEST_MF") != "1", reason="ustaw KSEF_TEST_MF=1"
)

BASE = API_URLS["test"]
ORGANIZATION_IDENTIFIER = ObjectIdentifier("2.5.4.97")
NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)


def _random_nip() -> str:
    while True:
        digits = [random.randint(1, 9) for _ in range(9)]
        check = sum(w * d for w, d in zip(NIP_WEIGHTS, digits)) % 11
        if check != 10:
            return "".join(map(str, digits)) + str(check)


def _pem_key(key) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")


def _pem_cert(cert: x509.Certificate) -> str:
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


def _self_signed_seal(nip: str, key) -> xades.SigningIdentity:
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, f"Test {nip}"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Podmiot testowy"),
            x509.NameAttribute(ORGANIZATION_IDENTIFIER, f"VATPL-{nip}"),
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PL"),
        ]
    )
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    return xades.load_identity(_pem_cert(cert), _pem_key(key))


def _random_pesel() -> str:
    """PESEL z 2000 roku (miesiąc + 20) z poprawną cyfrą kontrolną."""

    head = (
        f"00{random.randint(21, 32)}{random.randint(10, 28)}"
        f"{random.randint(0, 9999):04d}"
    )
    weights = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
    check = (10 - sum(int(c) * w for c, w in zip(head, weights)) % 10) % 10
    return f"{head}{check}"


def _self_signed_person(pesel: str, key) -> xades.SigningIdentity:
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.GIVEN_NAME, "Testowa"),
            x509.NameAttribute(NameOID.SURNAME, "Osoba"),
            x509.NameAttribute(NameOID.SERIAL_NUMBER, f"PNOPL-{pesel}"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Testowa Osoba"),
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PL"),
        ]
    )
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    return xades.load_identity(_pem_cert(cert), _pem_key(key))


async def _assert_reads_invoices(nip: str, identity: xades.SigningIdentity) -> str:
    """Bez tokenu KSeF: sam certyfikat ma dać dostęp do zapytania o faktury."""

    ksef_client.forget_sessions()
    async with KsefClient(BASE, context_nip=nip, token="", identity=identity) as client:
        page = await client.query_metadata(
            subject_type="Subject1",
            date_from=(datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),
        )
        assert page.invoices == []
        return await client.access_token()


@pytest.mark.parametrize("kind", ["ec-p256", "rsa-2048"])
async def test_samopodpisana_pieczec_loguje_i_czyta_faktury(kind: str) -> None:
    nip = _random_nip()
    key = (
        ec.generate_private_key(ec.SECP256R1())
        if kind == "ec-p256"
        else rsa.generate_private_key(65537, 2048)
    )
    assert await _assert_reads_invoices(nip, _self_signed_seal(nip, key))


async def _grant_invoice_read(access: str, pesel: str) -> None:
    """Właściciel nadaje osobie sam odczyt faktur, jak w Aplikacji Podatnika."""

    async with httpx.AsyncClient(
        base_url=BASE,
        headers={"Authorization": f"Bearer {access}"},
        timeout=httpx.Timeout(30.0),
    ) as http:
        response = await http.post(
            "/permissions/persons/grants",
            json={
                "subjectIdentifier": {"type": "Pesel", "value": pesel},
                "permissions": ["InvoiceRead"],
                "description": "Odczyt faktur NEXUS",
                "subjectDetails": {
                    "subjectDetailsType": "PersonByIdentifier",
                    "personById": {"firstName": "Testowa", "lastName": "Osoba"},
                },
            },
        )
        assert response.status_code == 202, response.text
        reference = response.json()["referenceNumber"]
        for _ in range(30):
            status = (
                (await http.get(f"/permissions/operations/{reference}"))
                .raise_for_status()
                .json()
            )
            if status["status"]["code"] != 100:
                break
            await asyncio.sleep(1)
        assert status["status"]["code"] == 200, status


async def _enroll(access: str, key: ec.EllipticCurvePrivateKey) -> x509.Certificate:
    async with httpx.AsyncClient(
        base_url=BASE,
        headers={"Authorization": f"Bearer {access}"},
        timeout=httpx.Timeout(30.0),
    ) as http:
        data = (
            (await http.get("/certificates/enrollments/data")).raise_for_status().json()
        )
        attributes = [
            x509.NameAttribute(NameOID.COMMON_NAME, data["commonName"]),
            x509.NameAttribute(NameOID.COUNTRY_NAME, data["countryName"]),
        ]
        for field, oid in (
            ("givenName", NameOID.GIVEN_NAME),
            ("surname", NameOID.SURNAME),
            ("serialNumber", NameOID.SERIAL_NUMBER),
            ("uniqueIdentifier", NameOID.X500_UNIQUE_IDENTIFIER),
        ):
            if data.get(field):
                attributes.append(x509.NameAttribute(oid, data[field]))
        if data.get("organizationName"):
            attributes.append(
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, data["organizationName"])
            )
        if data.get("organizationIdentifier"):
            attributes.append(
                x509.NameAttribute(
                    ORGANIZATION_IDENTIFIER, data["organizationIdentifier"]
                )
            )
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(x509.Name(attributes))
            .sign(key, hashes.SHA256())
        )
        response = await http.post(
            "/certificates/enrollments",
            json={
                "certificateName": "NEXUS test XAdES",
                "certificateType": "Authentication",
                "csr": base64.b64encode(
                    csr.public_bytes(serialization.Encoding.DER)
                ).decode("ascii"),
            },
        )
        assert response.status_code == 202, response.text
        reference = response.json()["referenceNumber"]
        for _ in range(30):
            status = (
                (await http.get(f"/certificates/enrollments/{reference}"))
                .raise_for_status()
                .json()
            )
            if status["status"]["code"] != 100:
                break
            await asyncio.sleep(2)
        assert status["status"]["code"] == 200, status
        retrieved = await http.post(
            "/certificates/retrieve",
            json={"certificateSerialNumbers": [status["certificateSerialNumber"]]},
        )
        retrieved.raise_for_status()
        der = base64.b64decode(retrieved.json()["certificates"][0]["certificate"])
        return x509.load_der_x509_certificate(der)


async def test_certyfikat_ksef_typu_authentication_loguje_i_czyta_faktury() -> None:
    nip = _random_nip()
    seal = _self_signed_seal(nip, ec.generate_private_key(ec.SECP256R1()))
    access = await _assert_reads_invoices(nip, seal)

    key = ec.generate_private_key(ec.SECP256R1())
    issued = await _enroll(access, key)
    # Certyfikat bywa ważny dopiero chwilę po wystawieniu.
    wait = (issued.not_valid_before_utc - datetime.now(timezone.utc)).total_seconds()
    if wait > 0:
        await asyncio.sleep(min(wait + 2, 120))
    identity = xades.load_identity(_pem_cert(issued), _pem_key(key))

    assert await _assert_reads_invoices(nip, identity)


async def test_certyfikat_osoby_z_samym_odczytem_faktur_czyta_faktury_spolki() -> None:
    """Zalecana droga na produkcji: osoba, która ma w KSeF tylko InvoiceRead."""

    nip, pesel = _random_nip(), _random_pesel()
    owner = await _assert_reads_invoices(
        nip, _self_signed_seal(nip, ec.generate_private_key(ec.SECP256R1()))
    )
    await _grant_invoice_read(owner, pesel)

    person = _self_signed_person(pesel, ec.generate_private_key(ec.SECP256R1()))
    access = await _assert_reads_invoices(nip, person)

    key = ec.generate_private_key(ec.SECP256R1())
    issued = await _enroll(access, key)
    wait = (issued.not_valid_before_utc - datetime.now(timezone.utc)).total_seconds()
    if wait > 0:
        await asyncio.sleep(min(wait + 2, 120))

    assert await _assert_reads_invoices(
        nip, xades.load_identity(_pem_cert(issued), _pem_key(key))
    )
