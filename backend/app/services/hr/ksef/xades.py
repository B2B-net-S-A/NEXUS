"""Podpis XAdES dokumentu ``AuthTokenRequest`` — uwierzytelnienie certyfikatem.

Druga metoda obok tokenu KSeF (``POST /auth/xades-signature``). Dokument
z ``authv2.xsd`` podpisujemy podpisem otaczanym XAdES-BES: referencja do
całego dokumentu (``URI=""``, enveloped + exc-c14n), referencja do
``SignedProperties``, certyfikat w ``KeyInfo``. Kształt jak w oficjalnym
kliencie MF (``ksef-client-csharp``, ``SignatureService``).

Klucz: EC (zalecany przez MF, krzywa co najmniej 256 bitów) albo RSA (co
najmniej 2048 bitów). ``SignatureValue`` ECDSA to ``R || S`` (RFC 4050), nie DER.

Certyfikat i klucz przychodzą ze zmiennych środowiskowych jako PEM albo Base64
z PEM. Klucz nie wychodzi z procesu i nie trafia do logów.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Union

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from lxml import etree

AUTH_NS = "http://ksef.mf.gov.pl/auth/token/2.0"
DS_NS = "http://www.w3.org/2000/09/xmldsig#"
XADES_NS = "http://uri.etsi.org/01903/v1.3.2#"

EXC_C14N = "http://www.w3.org/2001/10/xml-exc-c14n#"
ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"
SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"
RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
ECDSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha256"
SIGNED_PROPERTIES_TYPE = "http://uri.etsi.org/01903#SignedProperties"

#: NIP, PESEL albo ``organizationIdentifier`` z certyfikatu; odcisk wymaga
#: osobno nadanych uprawnień, więc go nie używamy.
SUBJECT_IDENTIFIER_TYPE = "certificateSubject"
MIN_RSA_BITS = 2048
MIN_EC_BITS = 256
#: Zegar serwera MF bywa za naszym; oficjalny klient cofa czas podpisu o minutę.
SIGNING_TIME_BUFFER = timedelta(minutes=1)
_SIGNATURE_ID = "Signature"
_SIGNED_PROPERTIES_ID = "SignedProperties"

PrivateKey = Union[ec.EllipticCurvePrivateKey, rsa.RSAPrivateKey]


class CertificateError(ValueError):
    """Certyfikat albo klucz nie nadaje się do podpisu. Treść bez danych sekretu."""


@dataclass(frozen=True)
class SigningIdentity:
    certificate: x509.Certificate
    private_key: PrivateKey = field(repr=False)

    @property
    def valid_from(self) -> datetime:
        return self.certificate.not_valid_before_utc

    @property
    def valid_until(self) -> datetime:
        return self.certificate.not_valid_after_utc

    def valid_at(self, moment: datetime) -> bool:
        return self.valid_from <= moment <= self.valid_until

    @property
    def fingerprint(self) -> str:
        return self.certificate.fingerprint(hashes.SHA256()).hex()


def _pem(raw: str) -> bytes:
    """PEM wprost, PEM ze znakami ``\\n`` z env-a albo Base64 z PEM."""

    text = raw.strip().replace("\\n", "\n")
    if text.startswith("-----BEGIN"):
        return text.encode("ascii", "ignore")
    try:
        return base64.b64decode("".join(text.split()), validate=True)
    except (binascii.Error, ValueError):
        raise CertificateError("wartość nie jest PEM ani Base64") from None


@lru_cache(maxsize=4)
def load_identity(
    certificate: str, private_key: str, password: str = ""
) -> SigningIdentity:
    """Wczytuje parę i sprawdza ją; wynik w pamięci, bo klucz z hasłem jest wolny."""

    try:
        cert = x509.load_pem_x509_certificate(_pem(certificate))
    except ValueError:
        raise CertificateError("nieczytelny certyfikat") from None
    try:
        key = serialization.load_pem_private_key(
            _pem(private_key), password=password.encode("utf-8") if password else None
        )
    except (ValueError, TypeError, UnsupportedAlgorithm):
        raise CertificateError("nieczytelny klucz albo złe hasło") from None
    if isinstance(key, rsa.RSAPrivateKey):
        if key.key_size < MIN_RSA_BITS:
            raise CertificateError("klucz RSA krótszy niż 2048 bitów")
    elif isinstance(key, ec.EllipticCurvePrivateKey):
        if key.curve.key_size < MIN_EC_BITS:
            raise CertificateError("krzywa EC krótsza niż 256 bitów")
    else:
        raise CertificateError("KSeF przyjmuje tylko klucze RSA i EC")
    if cert.public_key().public_numbers() != key.public_key().public_numbers():
        raise CertificateError("klucz nie pasuje do certyfikatu")
    return SigningIdentity(certificate=cert, private_key=key)


def _canonical(element: etree._Element) -> bytes:
    return etree.tostring(element, method="c14n", exclusive=True, with_comments=False)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _digest(data: bytes) -> str:
    return _b64(hashlib.sha256(data).digest())


def _ds(parent: etree._Element, name: str, **attributes: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{DS_NS}}}{name}", attributes)


def _xades(parent: etree._Element, name: str, **attributes: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{XADES_NS}}}{name}", attributes)


def _reference(
    signed_info: etree._Element,
    uri: str,
    digest: str,
    transforms: tuple[str, ...],
    **attributes: str,
) -> None:
    reference = _ds(signed_info, "Reference", URI=uri, **attributes)
    chain = _ds(reference, "Transforms")
    for algorithm in transforms:
        _ds(chain, "Transform", Algorithm=algorithm)
    _ds(reference, "DigestMethod", Algorithm=SHA256)
    _ds(reference, "DigestValue").text = digest


def _qualifying_properties(
    signature: etree._Element, identity: SigningIdentity, signing_time: datetime
) -> etree._Element:
    """``ds:Object`` z XAdES; zwraca ``SignedProperties`` do policzenia skrótu."""

    obj = _ds(signature, "Object")
    qualifying = etree.SubElement(
        obj,
        f"{{{XADES_NS}}}QualifyingProperties",
        {"Target": f"#{_SIGNATURE_ID}"},
        nsmap={"xades": XADES_NS},
    )
    signed = _xades(qualifying, "SignedProperties", Id=_SIGNED_PROPERTIES_ID)
    properties = _xades(signed, "SignedSignatureProperties")
    _xades(properties, "SigningTime").text = (
        signing_time - SIGNING_TIME_BUFFER
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    cert = _xades(_xades(properties, "SigningCertificate"), "Cert")
    cert_digest = _xades(cert, "CertDigest")
    _ds(cert_digest, "DigestMethod", Algorithm=SHA256)
    _ds(cert_digest, "DigestValue").text = _b64(
        identity.certificate.fingerprint(hashes.SHA256())
    )
    issuer_serial = _xades(cert, "IssuerSerial")
    _ds(
        issuer_serial, "X509IssuerName"
    ).text = identity.certificate.issuer.rfc4514_string()
    _ds(issuer_serial, "X509SerialNumber").text = str(
        identity.certificate.serial_number
    )
    return signed


def _signature_value(key: PrivateKey, signed_info: bytes) -> str:
    if isinstance(key, rsa.RSAPrivateKey):
        return _b64(key.sign(signed_info, padding.PKCS1v15(), hashes.SHA256()))
    r, s = decode_dss_signature(key.sign(signed_info, ec.ECDSA(hashes.SHA256())))
    size = (key.curve.key_size + 7) // 8
    return _b64(r.to_bytes(size, "big") + s.to_bytes(size, "big"))


def signed_auth_request(
    challenge: str,
    context_nip: str,
    identity: SigningIdentity,
    signing_time: datetime,
) -> bytes:
    """Podpisany ``AuthTokenRequest`` (UTF-8) dla ``POST /auth/xades-signature``."""

    root = etree.Element(f"{{{AUTH_NS}}}AuthTokenRequest", nsmap={None: AUTH_NS})
    etree.SubElement(root, f"{{{AUTH_NS}}}Challenge").text = challenge
    context = etree.SubElement(root, f"{{{AUTH_NS}}}ContextIdentifier")
    etree.SubElement(context, f"{{{AUTH_NS}}}Nip").text = context_nip
    etree.SubElement(
        root, f"{{{AUTH_NS}}}SubjectIdentifierType"
    ).text = SUBJECT_IDENTIFIER_TYPE
    # Skrót dokumentu przed dołożeniem podpisu to to samo, co po transformacie enveloped.
    document_digest = _digest(_canonical(root))

    signature = etree.SubElement(
        root, f"{{{DS_NS}}}Signature", {"Id": _SIGNATURE_ID}, nsmap={"ds": DS_NS}
    )
    signed_info = _ds(signature, "SignedInfo")
    _ds(signed_info, "CanonicalizationMethod", Algorithm=EXC_C14N)
    _ds(
        signed_info,
        "SignatureMethod",
        Algorithm=RSA_SHA256
        if isinstance(identity.private_key, rsa.RSAPrivateKey)
        else ECDSA_SHA256,
    )
    signature_value = _ds(signature, "SignatureValue")
    x509_data = _ds(_ds(signature, "KeyInfo"), "X509Data")
    _ds(x509_data, "X509Certificate").text = _b64(
        identity.certificate.public_bytes(serialization.Encoding.DER)
    )
    signed_properties = _qualifying_properties(signature, identity, signing_time)

    _reference(signed_info, "", document_digest, (ENVELOPED, EXC_C14N))
    _reference(
        signed_info,
        f"#{_SIGNED_PROPERTIES_ID}",
        _digest(_canonical(signed_properties)),
        (EXC_C14N,),
        Type=SIGNED_PROPERTIES_TYPE,
    )
    signature_value.text = _signature_value(
        identity.private_key, _canonical(signed_info)
    )
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")
