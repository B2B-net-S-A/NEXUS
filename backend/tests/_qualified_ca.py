"""Testowe kwalifikowane CA z responderem OCSP i listą CRL na 127.0.0.1.

Dane do długiej weryfikacji (E6) pobiera ten sam backend pyHanko co walidacja,
z adresów zapisanych w certyfikatach. Tu certyfikaty wskazują lokalny serwer
aiohttp, więc test przechodzi prawdziwą ścieżkę pobrania bez internetu. CA jest
na „liście zaufanych” (``TSPRegistry`` z usługą CA/QC), a certyfikaty osób
mają QcStatements, więc walidator daje ``QESig`` jak przy prawdziwym podpisie
kwalifikowanym. Wszystkie dane fikcyjne.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from aiohttp import web
from asn1crypto import keys as asn1_keys
from asn1crypto import x509 as asn1_x509
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509 import ocsp
from cryptography.x509.oid import NameOID, ObjectIdentifier
from pyhanko.sign import signers
from pyhanko.sign.ades import qualified_asn1
from pyhanko_certvalidator.registry import SimpleCertificateStore

_QC_STATEMENTS_OID = ObjectIdentifier("1.3.6.1.5.5.7.1.3")


def _asn1(cert: x509.Certificate) -> asn1_x509.Certificate:
    return asn1_x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER))


def _qc_statements() -> x509.UnrecognizedExtension:
    """Kwalifikowany (QcCompliance), klucz na QSCD, typ: podpis."""
    value = qualified_asn1.QcStatements(
        [
            {"statement_id": "qc_compliance"},
            {"statement_id": "qc_sscd"},
            {
                "statement_id": "qc_type",
                "statement_info": qualified_asn1.QcCertificateType(["qct_esign"]),
            },
        ]
    ).dump()
    return x509.UnrecognizedExtension(_QC_STATEMENTS_OID, value)


@dataclass
class QualifiedTestCA:
    base: str
    key: ec.EllipticCurvePrivateKey
    cert: x509.Certificate
    issued: dict[int, x509.Certificate] = field(default_factory=dict)
    ocsp_hits: int = 0
    crl_hits: int = 0
    down: bool = False

    @property
    def asn1_cert(self) -> asn1_x509.Certificate:
        return _asn1(self.cert)

    def registry(self):
        """Lista zaufanych z jedną usługą: to CA wydaje certyfikaty
        kwalifikowane do podpisu."""
        from pyhanko.sign.validation.qualified.tsp import (
            CA_QC_URI,
            BaseServiceInformation,
            CAServiceInformation,
            QcCertType,
            TSPRegistry,
        )

        registry = TSPRegistry()
        registry.register_ca(
            CAServiceInformation(
                base_info=BaseServiceInformation(
                    service_type=CA_QC_URI,
                    service_name="Testowe kwalifikowane CA",
                    valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
                    valid_until=None,
                    provider_certs=(self.asn1_cert,),
                    additional_info_certificate_type=frozenset({QcCertType.QC_ESIGN}),
                    other_additional_info=frozenset(),
                ),
                qualifications=frozenset(),
                expired_certs_revocation_info=None,
            )
        )
        return registry

    def _issue(
        self, common_name: str, *, via: str, tsa: bool = False
    ) -> tuple[x509.Certificate, asn1_keys.PrivateKeyInfo]:
        """Certyfikat od tego CA; ``via`` = ``ocsp`` albo ``crl`` (który adres
        unieważnień ma certyfikat); ``tsa`` = znacznik czasu zamiast osoby."""
        now = datetime.now(timezone.utc)
        # Testowy znacznik czasu pyHanko podpisuje tylko kluczem RSA.
        key = (
            rsa.generate_private_key(public_exponent=65537, key_size=2048)
            if tsa
            else ec.generate_private_key(ec.SECP256R1())
        )
        builder = (
            x509.CertificateBuilder()
            .subject_name(
                x509.Name(
                    [
                        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
                        x509.NameAttribute(NameOID.COUNTRY_NAME, "PL"),
                    ]
                )
            )
            .issuer_name(self.cert.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=365))
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=not tsa,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
        )
        if tsa:
            builder = builder.add_extension(
                x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.TIME_STAMPING]),
                critical=True,
            )
        else:
            builder = builder.add_extension(_qc_statements(), critical=False)
        if via == "ocsp":
            builder = builder.add_extension(
                x509.AuthorityInformationAccess(
                    [
                        x509.AccessDescription(
                            x509.AuthorityInformationAccessOID.OCSP,
                            x509.UniformResourceIdentifier(f"{self.base}/ocsp"),
                        )
                    ]
                ),
                critical=False,
            )
        else:
            builder = builder.add_extension(
                x509.CRLDistributionPoints(
                    [
                        x509.DistributionPoint(
                            full_name=[
                                x509.UniformResourceIdentifier(f"{self.base}/ca.crl")
                            ],
                            relative_name=None,
                            reasons=None,
                            crl_issuer=None,
                        )
                    ]
                ),
                critical=False,
            )
        leaf = builder.sign(self.key, hashes.SHA256())
        self.issued[leaf.serial_number] = leaf
        return leaf, asn1_keys.PrivateKeyInfo.load(
            key.private_bytes(
                serialization.Encoding.DER,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )

    def signer(self, common_name: str, *, via: str) -> signers.SimpleSigner:
        """Osoba z certyfikatem kwalifikowanym do podpisu (QcStatements)."""
        cert, key = self._issue(common_name, via=via)
        return signers.SimpleSigner(
            signing_cert=_asn1(cert),
            signing_key=key,
            cert_registry=SimpleCertificateStore.from_certs([self.asn1_cert]),
        )

    def timestamper(self):
        """Znacznik czasu podpisu (PAdES-T, jak u KIR); TSA ma adres OCSP."""
        from pyhanko.sign.timestamps.dummy_client import DummyTimeStamper

        cert, key = self._issue("Testowy znacznik czasu", via="ocsp", tsa=True)
        return DummyTimeStamper(
            tsa_cert=_asn1(cert),
            tsa_key=key,
            certs_to_embed=SimpleCertificateStore.from_certs([self.asn1_cert]),
        )

    def ocsp_response(self, body: bytes) -> bytes:
        request = ocsp.load_der_ocsp_request(body)
        now = datetime.now(timezone.utc)
        builder = (
            ocsp.OCSPResponseBuilder()
            .add_response(
                cert=self.issued[request.serial_number],
                issuer=self.cert,
                algorithm=request.hash_algorithm,
                cert_status=ocsp.OCSPCertStatus.GOOD,
                this_update=now - timedelta(minutes=1),
                next_update=now + timedelta(days=1),
                revocation_time=None,
                revocation_reason=None,
            )
            .responder_id(ocsp.OCSPResponderEncoding.HASH, self.cert)
        )
        try:
            nonce = request.extensions.get_extension_for_class(x509.OCSPNonce)
            builder = builder.add_extension(nonce.value, critical=False)
        except x509.ExtensionNotFound:
            pass
        return builder.sign(self.key, hashes.SHA256()).public_bytes(
            serialization.Encoding.DER
        )

    def crl(self) -> bytes:
        now = datetime.now(timezone.utc)
        return (
            x509.CertificateRevocationListBuilder()
            .issuer_name(self.cert.subject)
            .last_update(now - timedelta(hours=1))
            .next_update(now + timedelta(days=1))
            .add_extension(x509.CRLNumber(1), critical=False)
            .sign(self.key, hashes.SHA256())
            .public_bytes(serialization.Encoding.DER)
        )


def new_ca(base: str) -> QualifiedTestCA:
    now = datetime.now(timezone.utc)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "Testowe kwalifikowane CA"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Przykładowy dostawca"),
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PL"),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=30))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    return QualifiedTestCA(base=base, key=key, cert=cert)


async def start_ca() -> tuple[QualifiedTestCA, web.AppRunner]:
    """CA i jego serwer OCSP/CRL na 127.0.0.1; wołający sprząta
    ``runner.cleanup()``. Port znamy dopiero po starcie, a adres idzie do
    certyfikatów, więc trasy sięgają po CA z ``holder``."""
    holder: dict[str, QualifiedTestCA] = {}

    async def _ocsp(request: web.Request) -> web.Response:
        ca = holder["ca"]
        ca.ocsp_hits += 1
        if ca.down:
            raise web.HTTPServiceUnavailable()
        return web.Response(
            body=ca.ocsp_response(await request.read()),
            content_type="application/ocsp-response",
        )

    async def _crl(_request: web.Request) -> web.Response:
        ca = holder["ca"]
        ca.crl_hits += 1
        if ca.down:
            raise web.HTTPServiceUnavailable()
        return web.Response(body=ca.crl(), content_type="application/pkix-crl")

    app = web.Application()
    app.router.add_post("/ocsp", _ocsp)
    app.router.add_get("/ca.crl", _crl)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = runner.addresses[0][:2]
    holder["ca"] = new_ca(f"http://{host}:{port}")
    return holder["ca"], runner
