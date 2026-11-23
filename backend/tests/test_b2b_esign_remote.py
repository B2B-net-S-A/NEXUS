"""Podpis u dostawcy przez API CSC (E1, kierunek K1 Artura z 22.11.2026).

Dostawca nie jest wybrany, więc NEXUS rozmawia z samą specyfikacją CSC v1.
Tu dostawcę udaje lokalny serwer (``_FakeCsc``) z certyfikatem z testowego CA
zrobionego w teście: przyjmuje kod z PKCE, wydaje token, opisuje certyfikat,
wiąże zatwierdzenie ze skrótami (SCAL 2) i podpisuje je kluczem testowym.
Prawdziwy dostawca nie dostaje żadnego żądania.

„Kwalifikowany” rozstrzyga jak w ``test_b2b_esign.py`` podmieniony walidator
(``_FakeValidator``), a całość podpisu sprawdza osobno pyHanko z testowym CA.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient

from app.services.b2b_esign import remote
from app.services.b2b_esign.verdict import Fingerprint, builds_on
from tests.test_b2b_esign import (  # noqa: F401 — fikstura esign_env
    _FakeValidator,
    _partner,
    _report,
    _seed_in_progress,
    _token,
    esign_env,
)
from tests.test_b2b_esign_package import (
    _client_template,
    _send,
    _use_admin_as_company_signer,
)

SIGN_RSA_SHA256 = "1.2.840.113549.1.1.11"


def _pdf(text: str) -> bytes:
    """Najprostszy prawdziwy PDF z poprawnym spisem obiektów (pyHanko go czyta)."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R >>",
    ]
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects.append(
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
    )
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


CONTRACT_PDF = _pdf("Umowa B2B testowa")
NDA_PDF = _pdf("NDA testowe")


class _TestCa:
    """Testowe CA i certyfikaty osób — tylko w pamięci tego biegu."""

    def __init__(self) -> None:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        self._x509, self._hashes, self._rsa, self._oid = x509, hashes, rsa, NameOID
        now = datetime.now(timezone.utc)
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Testowe CA")])
        self.cert = (
            x509.CertificateBuilder()
            .subject_name(self.name)
            .issuer_name(self.name)
            .public_key(self.key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
            .add_extension(self._usage(cert_sign=True), True)
            .sign(self.key, hashes.SHA256())
        )

    def _usage(self, *, cert_sign: bool) -> Any:
        return self._x509.KeyUsage(
            digital_signature=True,
            content_commitment=not cert_sign,
            key_encipherment=False,
            data_encipherment=False,
            key_agreement=False,
            key_cert_sign=cert_sign,
            crl_sign=cert_sign,
            encipher_only=False,
            decipher_only=False,
        )

    def person(self, common_name: str) -> tuple[Any, Any]:
        now = datetime.now(timezone.utc)
        key = self._rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cert = (
            self._x509.CertificateBuilder()
            .subject_name(
                self._x509.Name(
                    [self._x509.NameAttribute(self._oid.COMMON_NAME, common_name)]
                )
            )
            .issuer_name(self.name)
            .public_key(key.public_key())
            .serial_number(self._x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=30))
            .add_extension(self._usage(cert_sign=False), True)
            .sign(self.key, self._hashes.SHA256())
        )
        return cert, key


class _FakeCsc:
    """Dostawca CSC v1 w pamięci testu (aiohttp na 127.0.0.1)."""

    CODE = "kod-autoryzacji-testowy"
    TOKEN = "token-dostepu-testowy"

    def __init__(self, ca: _TestCa) -> None:
        self.ca = ca
        self.calls: list[tuple[str, Any]] = []
        self.challenge: str | None = None
        self.cert: Any = None
        self.key: Any = None
        self._sad: dict[str, list[str]] = {}
        self.server: Any = None

    def use_person(self, common_name: str) -> None:
        self.cert, self.key = self.ca.person(common_name)

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    async def start(self) -> str:
        from aiohttp import web
        from aiohttp.test_utils import TestServer

        app = web.Application()
        app.router.add_post("/csc/v1/info", self._info)
        app.router.add_post("/oauth2/token", self._token)
        app.router.add_post("/csc/v1/credentials/list", self._list)
        app.router.add_post("/csc/v1/credentials/info", self._credential)
        app.router.add_post("/csc/v1/credentials/authorize", self._authorize)
        app.router.add_post("/csc/v1/signatures/signHash", self._sign)
        self.server = TestServer(app, host="127.0.0.1")
        await self.server.start_server()
        return str(self.server.make_url("")).rstrip("/")

    def _authorized(self, request: Any) -> bool:
        return request.headers.get("Authorization") == f"Bearer {self.TOKEN}"

    async def _info(self, request: Any) -> Any:
        from aiohttp import web

        self.calls.append(("info", await request.json()))
        base = str(self.server.make_url("")).rstrip("/")
        return web.json_response({"name": "Testowy dostawca", "oauth2": base})

    async def _token(self, request: Any) -> Any:
        from aiohttp import web

        form = dict(await request.post())
        self.calls.append(("token", form))
        verifier = form.get("code_verifier", "")
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        if (
            form.get("code") != self.CODE
            or form.get("grant_type") != "authorization_code"
            or expected != self.challenge
        ):
            return web.json_response({"error": "invalid_grant"}, status=400)
        return web.json_response({"access_token": self.TOKEN, "token_type": "Bearer"})

    async def _list(self, request: Any) -> Any:
        from aiohttp import web

        self.calls.append(("credentials/list", await request.json()))
        if not self._authorized(request):
            return web.json_response({"error": "invalid_token"}, status=401)
        return web.json_response({"credentialIDs": ["cred-1"]})

    async def _credential(self, request: Any) -> Any:
        from aiohttp import web
        from cryptography.hazmat.primitives import serialization

        self.calls.append(("credentials/info", await request.json()))
        if not self._authorized(request):
            return web.json_response({"error": "invalid_token"}, status=401)

        def der(cert: Any) -> str:
            return base64.b64encode(
                cert.public_bytes(serialization.Encoding.DER)
            ).decode()

        return web.json_response(
            {
                "key": {"status": "enabled", "algo": [SIGN_RSA_SHA256], "len": 2048},
                "cert": {
                    "status": "valid",
                    "certificates": [der(self.cert), der(self.ca.cert)],
                },
                "authMode": "explicit",
                "SCAL": "2",
                "multisign": 10,
            }
        )

    async def _authorize(self, request: Any) -> Any:
        from aiohttp import web

        body = await request.json()
        self.calls.append(("credentials/authorize", body))
        if not self._authorized(request):
            return web.json_response({"error": "invalid_token"}, status=401)
        sad = f"sad-{len(self._sad) + 1}"
        self._sad[sad] = list(body.get("hash") or [])
        return web.json_response({"SAD": sad, "expiresIn": 300})

    async def _sign(self, request: Any) -> Any:
        from aiohttp import web
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding, utils

        body = await request.json()
        self.calls.append(("signatures/signHash", body))
        pinned = self._sad.get(body.get("SAD"))
        if not self._authorized(request) or pinned is None or body["hash"] != pinned:
            return web.json_response({"error": "invalid_request"}, status=400)
        signatures = [
            base64.b64encode(
                self.key.sign(
                    base64.b64decode(value),
                    padding.PKCS1v15(),
                    utils.Prehashed(hashes.SHA256()),
                )
            ).decode()
            for value in body["hash"]
        ]
        return web.json_response({"signatures": signatures})


@pytest.fixture(scope="module")
def test_ca() -> _TestCa:
    return _TestCa()


@pytest.fixture
async def csc_env(monkeypatch, esign_env, test_ca):  # noqa: F811
    from app.api import b2b_esign
    from app.core.config import settings

    fake = _FakeCsc(test_ca)
    base = await fake.start()

    async def _contract_pdf(docx: bytes) -> bytes:
        return CONTRACT_PDF

    monkeypatch.setattr(b2b_esign, "pdf_from_docx", _contract_pdf)
    monkeypatch.setattr(settings, "B2B_ESIGN_CSC_BASE_URL", base)
    monkeypatch.setattr(settings, "B2B_ESIGN_CSC_CLIENT_ID", "nexus-test")
    monkeypatch.setattr(settings, "B2B_ESIGN_CSC_CLIENT_SECRET", "sekret-testowy")
    monkeypatch.setattr(settings, "B2B_ESIGN_CSC_PROVIDER_LABEL", "Testowy dostawca")
    try:
        yield {**esign_env, "csc": fake}
    finally:
        await fake.server.close()


def _query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}


async def _start(app_client: AsyncClient, token: str, **body: Any):
    return await app_client.post(
        f"/api/public/b2b-sign/{token}/remote/start",
        json={"include_document_ids": [], "method": "one_time", **body},
    )


async def _callback(
    app_client: AsyncClient, fake: _FakeCsc, redirect_url: str, **extra
):
    """Przeglądarka po zatwierdzeniu u dostawcy wraca z kodem i ``state``."""
    params = _query(redirect_url)
    fake.challenge = params["code_challenge"]
    query = {"code": _FakeCsc.CODE, "state": params["state"], **extra}
    return await app_client.get("/api/public/b2b-sign/remote/callback", params=query)


async def _request(request_id: int):
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_signing_request import B2BSigningRequest

    async with AsyncSessionLocal() as db:
        return await db.get(B2BSigningRequest, request_id)


async def _assert_intact(data: bytes, ca: _TestCa, signatures: int) -> list[str]:
    """pyHanko: każdy podpis cały, ważny i z zaufanego (testowego) CA."""
    from asn1crypto import x509 as asn1_x509
    from cryptography.hazmat.primitives import serialization
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import async_validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext

    root = asn1_x509.Certificate.load(ca.cert.public_bytes(serialization.Encoding.DER))
    reader = PdfFileReader(BytesIO(data), strict=False)
    assert len(reader.embedded_signatures) == signatures
    names = []
    for embedded in reader.embedded_signatures:
        status = await async_validate_pdf_signature(
            embedded, ValidationContext(trust_roots=[root])
        )
        assert status.intact and status.valid and status.trusted, (
            status.pretty_print_details()
        )
        names.append(status.signing_cert.subject.human_friendly)
    return names


async def _send_with_nda(app_client, headers, env) -> dict[str, Any]:
    admin_id = env["admin_id"]
    await _use_admin_as_company_signer(admin_id)
    scenario = await _seed_in_progress(created_by=admin_id)
    await _client_template(scenario["client_id"], "NDA klienta", NDA_PDF)
    sent = await _send(app_client, headers, scenario["generated_id"], admin_id)
    assert sent.status_code == 200, sent.text
    [document] = sent.json()["request"]["documents"]
    return {
        **scenario,
        "request_id": sent.json()["request"]["id"],
        "token": _token(sent.json()["sign_url"]),
        "document_id": document["id"],
        "partner": await _partner(scenario["generated_id"]),
    }


# ── bez konfiguracji ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_without_configuration_the_provider_path_is_off(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    esign_env,  # noqa: F811
):
    """Dostawca niewybrany: wszystko puste, nic nie podsuwa podpisu u dostawcy."""
    assert remote.availability() == remote.Availability(False, None)
    admin_id = esign_env["admin_id"]
    await _use_admin_as_company_signer(admin_id)
    scenario = await _seed_in_progress(created_by=admin_id)
    sent = await _send(app_client, app_auth_headers, scenario["generated_id"], admin_id)
    token = _token(sent.json()["sign_url"])

    view = await app_client.get(f"/api/public/b2b-sign/{token}")
    assert view.json()["remote_signing"] == {"available": False, "provider_label": None}
    start = await _start(app_client, token)
    assert start.status_code == 404, start.text
    callback = await app_client.get(
        "/api/public/b2b-sign/remote/callback", params={"code": "x", "state": "y"}
    )
    assert callback.status_code == 404

    available = await app_client.get(
        "/api/b2b-generator/esign/company-remote/available", headers=app_auth_headers
    )
    assert available.status_code == 200, available.text
    assert available.json() == {"available": False, "provider_label": None}
    company = await app_client.post(
        "/api/b2b-generator/esign/company-remote/start",
        json={"request_ids": [sent.json()["request"]["id"]]},
        headers=app_auth_headers,
    )
    assert company.status_code == 404, company.text


# ── kontraktor ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_contract_and_nda_are_signed_with_one_authorization(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    csc_env,
):
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.b2b_signing_document import B2BSigningDocument
    from app.models.start_document import PlacementStartDocument
    from app.services import storage_service

    fake: _FakeCsc = csc_env["csc"]
    case = await _send_with_nda(app_client, app_auth_headers, csc_env)
    fake.use_person(case["partner"])
    _FakeValidator.report = _report((f"CN={case['partner']}", "TOTAL_PASSED", "QESig"))

    view = await app_client.get(f"/api/public/b2b-sign/{case['token']}")
    assert view.json()["remote_signing"] == {
        "available": True,
        "provider_label": "Testowy dostawca",
    }

    start = await _start(
        app_client, case["token"], include_document_ids=[case["document_id"]]
    )
    assert start.status_code == 200, start.text
    redirect_url, session_id = start.json()["redirect_url"], start.json()["session_id"]
    params = _query(redirect_url)
    assert redirect_url.startswith(
        f"{fake.server.make_url('')}".rstrip("/") + "/oauth2/authorize?"
    )
    assert params["response_type"] == "code"
    assert params["client_id"] == "nexus-test"
    assert params["scope"] == "service"
    assert params["code_challenge_method"] == "S256"
    assert params["redirect_uri"].endswith("/api/public/b2b-sign/remote/callback")
    # Przed powrotem od dostawcy wniosek stoi.
    waiting = await app_client.get(
        f"/api/public/b2b-sign/{case['token']}/remote/{session_id}"
    )
    assert waiting.json() == {
        "state": "waiting_for_user",
        "message": None,
        "view": None,
    }

    back = await _callback(app_client, fake, redirect_url)
    assert back.status_code == 302, back.text
    assert back.headers["location"].endswith(
        f"/sign/b2b/{case['token']}?remote={session_id}"
    )

    # Jedno zatwierdzenie i jeden podpis na oba pliki.
    assert fake.names().count("credentials/authorize") == 1
    assert fake.names().count("signatures/signHash") == 1
    [(_, authorize)] = [c for c in fake.calls if c[0] == "credentials/authorize"]
    assert authorize["numSignatures"] == 2 and len(authorize["hash"]) == 2
    assert authorize["credentialID"] == "cred-1"
    # Sekret klienta idzie tylko do wymiany kodu, nigdy do usługi podpisu.
    assert all(
        "sekret-testowy" not in repr(body)
        for name, body in fake.calls
        if name != "token"
    )

    status = await app_client.get(
        f"/api/public/b2b-sign/{case['token']}/remote/{session_id}"
    )
    assert status.status_code == 200, status.text
    assert status.json()["state"] == "done", status.json()
    assert status.json()["view"]["status"] == "signed_by_you"
    assert status.json()["view"]["documents"][0]["signed"] is True
    assert status.json()["view"]["remote_signing"]["available"] is False

    request = await _request(case["request_id"])
    assert request.status == "contractor_signed"
    contract = storage_service.read_b2b_signing_pdf(request.contractor_pdf_path)
    assert builds_on(contract, Fingerprint.of(CONTRACT_PDF))
    assert await _assert_intact(contract, fake.ca, 1) == [
        f"Common Name: {case['partner']}"
    ]
    async with AsyncSessionLocal() as db:
        item = await db.get(B2BSigningDocument, case["document_id"])
        assert item.signed_via == "qualified"
        nda = storage_service.read_b2b_signing_pdf(item.signed_pdf_path)
        pair = await db.scalar(
            select(PlacementStartDocument).where(
                PlacementStartDocument.document_id == item.start_document_id,
                PlacementStartDocument.candidate_id == case["candidate_id"],
            )
        )
    assert builds_on(nda, Fingerprint.of(NDA_PDF))
    await _assert_intact(nda, fake.ca, 1)
    # Ta sama droga co wgranie: dokument od razu w „Dokumentach do startu”.
    assert pair is not None and pair.status == "delivered"
    assert storage_service.read_start_document_file(pair.file_path) == nda

    # Sesja nie trzyma tokenu linku ani PKCE po końcu.
    async with AsyncSessionLocal() as db:
        from app.models.b2b_esign_remote_session import B2BEsignRemoteSession

        session = await db.scalar(
            select(B2BEsignRemoteSession).where(
                B2BEsignRemoteSession.public_id == session_id
            )
        )
        assert session.sealed_token is None and session.code_verifier is None
        assert session.evidence["files"] == 2
        assert session.evidence["provider"] == "Testowy dostawca"

    # Sesja należy do swojego linku.
    other = await _send_with_nda(app_client, app_auth_headers, csc_env)
    foreign = await app_client.get(
        f"/api/public/b2b-sign/{other['token']}/remote/{session_id}"
    )
    assert foreign.status_code == 404


@pytest.mark.asyncio
async def test_the_contract_is_always_in_the_batch(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    csc_env,
):
    fake: _FakeCsc = csc_env["csc"]
    case = await _send_with_nda(app_client, app_auth_headers, csc_env)
    fake.use_person(case["partner"])
    _FakeValidator.report = _report((f"CN={case['partner']}", "TOTAL_PASSED", "QESig"))

    foreign = await _start(app_client, case["token"], include_document_ids=[987654])
    assert foreign.status_code == 404, foreign.text

    start = await _start(app_client, case["token"])
    assert start.status_code == 200, start.text
    back = await _callback(app_client, fake, start.json()["redirect_url"])
    assert back.status_code == 302, back.text
    [(_, authorize)] = [c for c in fake.calls if c[0] == "credentials/authorize"]
    assert authorize["numSignatures"] == 1

    view = (await app_client.get(f"/api/public/b2b-sign/{case['token']}")).json()
    # Umowa podpisana, NDA czeka; kolejna sesja u dostawcy nie ma umowy do podpisu.
    assert view["status"] == "waiting" and view["contract_signed"] is True
    assert view["documents"][0]["signed"] is False
    assert view["remote_signing"]["available"] is False
    again = await _start(
        app_client, case["token"], include_document_ids=[case["document_id"]]
    )
    assert again.status_code == 409, again.text


@pytest.mark.asyncio
async def test_unknown_reused_and_expired_state_are_refused(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    csc_env,
):
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_esign_remote_session import B2BEsignRemoteSession
    from sqlalchemy import select

    fake: _FakeCsc = csc_env["csc"]
    case = await _send_with_nda(app_client, app_auth_headers, csc_env)
    fake.use_person(case["partner"])
    _FakeValidator.report = _report((f"CN={case['partner']}", "TOTAL_PASSED", "QESig"))

    # Obcy ``state``.
    start = await _start(app_client, case["token"])
    stranger = await app_client.get(
        "/api/public/b2b-sign/remote/callback",
        params={"code": _FakeCsc.CODE, "state": "obcy-state"},
    )
    assert stranger.status_code == 400, stranger.text
    missing = await app_client.get(
        "/api/public/b2b-sign/remote/callback", params={"code": _FakeCsc.CODE}
    )
    assert missing.status_code == 400

    # Sesja po czasie: powrót nic nie podpisuje, przeglądarka wraca na stronę.
    async with AsyncSessionLocal() as db:
        session = await db.scalar(
            select(B2BEsignRemoteSession).where(
                B2BEsignRemoteSession.public_id == start.json()["session_id"]
            )
        )
        session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    late = await _callback(app_client, fake, start.json()["redirect_url"])
    assert late.status_code == 302, late.text
    status = await app_client.get(
        f"/api/public/b2b-sign/{case['token']}/remote/{start.json()['session_id']}"
    )
    assert status.json()["state"] == "cancelled"
    assert status.json()["message"] == remote.MSG_TIMEOUT
    assert status.json()["view"]["status"] == "waiting"
    assert "token" not in fake.names()
    request = await _request(case["request_id"])
    assert request.status == "sent" and request.contractor_pdf_path is None

    # Ten sam ``state`` drugi raz — po udanym podpisie.
    fresh = await _start(app_client, case["token"])
    first = await _callback(app_client, fake, fresh.json()["redirect_url"])
    assert first.status_code == 302, first.text
    replay = await _callback(app_client, fake, fresh.json()["redirect_url"])
    assert replay.status_code == 409, replay.text
    assert fake.names().count("token") == 1


@pytest.mark.asyncio
async def test_cancel_at_the_provider_leaves_the_request_sent(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    csc_env,
):
    fake: _FakeCsc = csc_env["csc"]
    case = await _send_with_nda(app_client, app_auth_headers, csc_env)
    start = await _start(
        app_client, case["token"], include_document_ids=[case["document_id"]]
    )
    params = _query(start.json()["redirect_url"])
    back = await app_client.get(
        "/api/public/b2b-sign/remote/callback",
        params={"error": "access_denied", "state": params["state"]},
    )
    assert back.status_code == 302, back.text
    status = await app_client.get(
        f"/api/public/b2b-sign/{case['token']}/remote/{start.json()['session_id']}"
    )
    assert status.json()["state"] == "cancelled"
    assert status.json()["message"] == remote.MSG_CANCELLED
    assert fake.names() == ["info"]
    request = await _request(case["request_id"])
    assert request.status == "sent" and request.contractor_pdf_path is None
    view = (await app_client.get(f"/api/public/b2b-sign/{case['token']}")).json()
    assert view["documents"][0]["signed"] is False
    assert view["remote_signing"]["available"] is True


@pytest.mark.asyncio
async def test_a_signature_the_validator_rejects_changes_nothing(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    csc_env,
):
    """Certyfikat od dostawcy bez nazwiska z umowy: ta sama odmowa co przy
    wgraniu pliku, a umowa i NDA zostają niepodpisane (wszystko albo nic)."""
    fake: _FakeCsc = csc_env["csc"]
    case = await _send_with_nda(app_client, app_auth_headers, csc_env)
    fake.use_person("Jan Obcy")
    _FakeValidator.report = _report(("CN=Jan Obcy", "TOTAL_PASSED", "QESig"))
    start = await _start(
        app_client, case["token"], include_document_ids=[case["document_id"]]
    )
    back = await _callback(app_client, fake, start.json()["redirect_url"])
    assert back.status_code == 302, back.text
    status = await app_client.get(
        f"/api/public/b2b-sign/{case['token']}/remote/{start.json()['session_id']}"
    )
    assert status.json()["state"] == "failed"
    assert case["partner"] in status.json()["message"]
    request = await _request(case["request_id"])
    assert request.status == "sent" and request.contractor_pdf_path is None
    assert request.contractor_failed_attempts == 0
    assert status.json()["view"]["documents"][0]["signed"] is False


# ── reprezentant B2Bnetwork ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_company_signs_two_contracts_with_one_authorization(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    csc_env,
):
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from app.models.user import User
    from app.services import storage_service

    fake: _FakeCsc = csc_env["csc"]
    admin_id = csc_env["admin_id"]
    cases = []
    for _ in range(2):
        case = await _send_with_nda(app_client, app_auth_headers, csc_env)
        fake.use_person(case["partner"])
        _FakeValidator.report = _report(
            (f"CN={case['partner']}", "TOTAL_PASSED", "QESig")
        )
        start = await _start(
            app_client, case["token"], include_document_ids=[case["document_id"]]
        )
        await _callback(app_client, fake, start.json()["redirect_url"])
        assert (await _request(case["request_id"])).status == "contractor_signed"
        cases.append(case)
    waiting = await _send_with_nda(app_client, app_auth_headers, csc_env)

    available = await app_client.get(
        "/api/b2b-generator/esign/company-remote/available", headers=app_auth_headers
    )
    assert available.json() == {"available": True, "provider_label": "Testowy dostawca"}
    # Umowa jeszcze u kontraktora nie wejdzie do podpisu firmy.
    early = await app_client.post(
        "/api/b2b-generator/esign/company-remote/start",
        json={"request_ids": [cases[0]["request_id"], waiting["request_id"]]},
        headers=app_auth_headers,
    )
    assert early.status_code == 409, early.text

    async with AsyncSessionLocal() as db:
        admin_name = (await db.get(User, admin_id)).name
    fake.use_person(admin_name)
    fake.calls.clear()
    request_ids = [c["request_id"] for c in cases]
    start = await app_client.post(
        "/api/b2b-generator/esign/company-remote/start",
        json={"request_ids": request_ids},
        headers=app_auth_headers,
    )
    assert start.status_code == 200, start.text
    session_id = start.json()["session_id"]
    params = _query(start.json()["redirect_url"])
    assert params["redirect_uri"].endswith(
        "/api/b2b-generator/esign/company-remote/callback"
    )
    fake.challenge = params["code_challenge"]
    # Powrót bez zalogowania nie przechodzi bramki.
    anonymous = await app_client.get(
        "/api/b2b-generator/esign/company-remote/callback",
        params={"code": _FakeCsc.CODE, "state": params["state"]},
    )
    assert anonymous.status_code in (401, 403)

    contractor_pdfs = {
        rid: storage_service.read_b2b_signing_pdf(
            (await _request(rid)).contractor_pdf_path
        )
        for rid in request_ids
    }
    # Walidator nie czyta pliku: raport z nazwiskiem kontraktora danej umowy.
    reports = {
        rid: _report(
            (f"CN={c['partner']}", "TOTAL_PASSED", "QESig"),
            (f"CN={admin_name}", "TOTAL_PASSED", "QESig"),
        )
        for rid, c in zip(request_ids, cases)
    }
    order = iter(request_ids)

    async def _next_report() -> None:
        _FakeValidator.report = reports[next(order)]

    _FakeValidator.on_validate = _next_report
    back = await app_client.get(
        "/api/b2b-generator/esign/company-remote/callback",
        params={"code": _FakeCsc.CODE, "state": params["state"]},
        headers=app_auth_headers,
    )
    _FakeValidator.on_validate = None
    assert back.status_code == 302, back.text
    assert back.headers["location"].endswith(
        f"/contracts/b2b-generator?tab=generated&remote={session_id}"
    )
    assert fake.names().count("credentials/authorize") == 1
    [(_, authorize)] = [c for c in fake.calls if c[0] == "credentials/authorize"]
    assert authorize["numSignatures"] == 2

    status = await app_client.get(
        f"/api/b2b-generator/esign/company-remote/{session_id}",
        headers=app_auth_headers,
    )
    assert status.status_code == 200, status.text
    assert status.json() == {
        "state": "done",
        "message": None,
        "done_request_ids": request_ids,
    }
    for rid, case in zip(request_ids, cases):
        request = await _request(rid)
        assert request.status == "completed"
        final = storage_service.read_b2b_signing_pdf(request.final_pdf_path)
        assert builds_on(final, Fingerprint.of(contractor_pdfs[rid]))
        assert await _assert_intact(final, fake.ca, 2) == [
            f"Common Name: {case['partner']}",
            f"Common Name: {admin_name}",
        ]
        async with AsyncSessionLocal() as db:
            row = await db.get(B2BGeneratedContract, case["generated_id"])
            # Ta sama automatyka co po wgraniu: „Oznacz jako podpisaną”.
            assert row.signature_status == "signed_both"

    # Sesja jest tego konta.
    from tests.test_b2b_signature_automation import _headers_for_role
    from app.models.user import UserRole

    other = await _headers_for_role(app_client, UserRole.delivery_lead)
    foreign = await app_client.get(
        f"/api/b2b-generator/esign/company-remote/{session_id}", headers=other
    )
    assert foreign.status_code == 404


@pytest.mark.asyncio
async def test_expired_sessions_lose_the_sealed_link_in_the_sweeper(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    csc_env,
):
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.b2b_esign_remote_session import B2BEsignRemoteSession
    from app.tasks import b2b_esign_sweeper

    case = await _send_with_nda(app_client, app_auth_headers, csc_env)
    start = await _start(app_client, case["token"])
    session_id = start.json()["session_id"]
    async with AsyncSessionLocal() as db:
        session = await db.scalar(
            select(B2BEsignRemoteSession).where(
                B2BEsignRemoteSession.public_id == session_id
            )
        )
        # Token linku nie leży w bazie jawnie.
        assert session.sealed_token and case["token"] not in session.sealed_token
    await b2b_esign_sweeper.sweep(datetime.now(timezone.utc) + timedelta(minutes=16))
    async with AsyncSessionLocal() as db:
        session = await db.scalar(
            select(B2BEsignRemoteSession).where(
                B2BEsignRemoteSession.public_id == session_id
            )
        )
        assert session.status == "cancelled"
        assert session.sealed_token is None and session.code_verifier is None


# ── czyste reguły ────────────────────────────────────────────────────────────


def test_sealed_token_opens_only_with_its_state():
    sealed = remote.seal("token-linku", "state-a")
    assert remote.unseal(sealed, "state-a") == "token-linku"
    with pytest.raises(Exception):
        remote.unseal(sealed, "state-b")


def test_messages_for_the_contractor_have_no_em_dash():
    from app.services.b2b_esign import csc

    for module in (remote, csc):
        for name in dir(module):
            if name.startswith("MSG_"):
                assert "—" not in getattr(module, name), name


def test_entrypoint_mirrors_the_remote_sessions_table():
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    entrypoint = (root / "entrypoint.sh").read_text(encoding="utf-8")
    assert "remote_schema as _b2b_esign_remote_schema" in entrypoint
    assert entrypoint.index("*_B2B_ESIGN_REMOTE_DDL,") > entrypoint.index(
        "*_B2B_SIGNING_DOCUMENTS_DDL,"
    )
    migration = (
        root / "alembic/versions/0759_b2b_esign_remote_sessions.py"
    ).read_text()
    assert re.search(r'down_revision = "0758_b2b_mass_send"', migration)
