"""Próbny PDF podpisany pyHanko certyfikatem testowym (bez sieci, bez TSA).

Podpis ma zadany czas podpisu (atrybut ``signingTime``), więc test sprawdza
odczyt daty i godziny tak, jak przy prawdziwym podpisie kwalifikowanym.
Certyfikaty są samopodpisane: test sprawdza odczyt i spójność, nie zaufanie.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from unittest import mock

from asn1crypto import keys as asn1_keys
from asn1crypto import x509 as asn1_x509
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from pyhanko.pdf_utils import generic
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.writer import PdfFileWriter
from pyhanko.sign import signers
from pyhanko.sign.signers import pdf_signer
from pyhanko_certvalidator.registry import SimpleCertificateStore


def blank_pdf() -> bytes:
    writer = PdfFileWriter()
    writer.insert_page(
        generic.DictionaryObject(
            {
                generic.NameObject("/Type"): generic.NameObject("/Page"),
                generic.NameObject("/MediaBox"): generic.ArrayObject(
                    [generic.NumberObject(v) for v in (0, 0, 595, 842)]
                ),
            }
        )
    )
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def signer_for(common_name: str) -> signers.SimpleSigner:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PL"),
        ]
    )
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(start + timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    asn1_cert = asn1_x509.Certificate.load(
        cert.public_bytes(serialization.Encoding.DER)
    )
    asn1_key = asn1_keys.PrivateKeyInfo.load(
        key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return signers.SimpleSigner(
        signing_cert=asn1_cert,
        signing_key=asn1_key,
        cert_registry=SimpleCertificateStore.from_certs([asn1_cert]),
    )


def signer_from_ca_outside_the_eu_list(common_name: str) -> signers.SimpleSigner:
    """Certyfikat wydany przez CA spoza listy zaufanych UE, bez QcStatements.

    Kształt podpisu osobistego z e-dowodu (wystawca MSWiA): pyHanko nie zbuduje
    ścieżki do zaufanego wystawcy (``NO_CERTIFICATE_CHAIN_FOUND``). Samopodpisany
    certyfikat z ``signer_for`` daje inny powód (``CHAIN_CONSTRAINTS_FAILURE``),
    więc tu jest osobne CA."""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "Testowe CA spoza listy UE"),
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PL"),
        ]
    )
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(start + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name(
                [
                    x509.NameAttribute(NameOID.COMMON_NAME, common_name),
                    x509.NameAttribute(NameOID.COUNTRY_NAME, "PL"),
                ]
            )
        )
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(start + timedelta(days=3650))
        .sign(ca_key, hashes.SHA256())
    )

    def asn1(cert: x509.Certificate) -> asn1_x509.Certificate:
        return asn1_x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER))

    return signers.SimpleSigner(
        signing_cert=asn1(leaf),
        signing_key=asn1_keys.PrivateKeyInfo.load(
            key.private_bytes(
                serialization.Encoding.DER,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        ),
        cert_registry=SimpleCertificateStore.from_certs([asn1(ca)]),
    )


async def sign(
    data: bytes,
    common_name: str,
    at: datetime,
    *,
    field: str,
    signer: signers.SimpleSigner | None = None,
) -> bytes:
    """Dopisz podpis (aktualizacja przyrostowa) z czasem ``at``."""

    class _Fixed(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001, ANN206
            return at

    writer = IncrementalPdfFileWriter(BytesIO(data), strict=False)
    out = BytesIO()
    with mock.patch.object(pdf_signer, "datetime", _Fixed):
        await pdf_signer.PdfSigner(
            pdf_signer.PdfSignatureMetadata(field_name=field),
            signer=signer or signer_for(common_name),
        ).async_sign_pdf(writer, output=out)
    return out.getvalue()


async def signed_by(*parties: tuple[str, datetime]) -> bytes:
    """PDF podpisany kolejno przez podane osoby."""
    data = blank_pdf()
    for index, (name, at) in enumerate(parties, start=1):
        data = await sign(data, name, at, field=f"Podpis{index}")
    return data
