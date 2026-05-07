"""Integration test for ``POST /api/autenti/webhook``.

Stands up the in-process FastAPI client (``app_client`` fixture), forces
``AUTENTI_ENABLED=true`` so the router is mounted, monkeypatches the
JWKS fetcher to return a test public key, and signs synthetic JWTs with
the matching private key.

Validates:
- 200 + ``{"status": "ok"}`` on a fresh well-formed event for a known process_id
- 200 + ``{"status": "duplicate"}`` on replay of the same event_id
- 200 + ``{"status": "ignored"}`` on payload referencing an unknown process_id
- 401 on signature tampered after the fact

The signed-PDF download path is patched out (we don't call the real
Autenti API) — covered separately in :mod:`test_autenti_webhook_handler`.
"""

from __future__ import annotations

import base64
import time
from datetime import datetime, timezone
from typing import Any

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from jose import jwt
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.models.document_signature_event import DocumentSignatureEvent
from app.models.user import User
from app.services.autenti.webhook_verify import _reset_cache_for_tests


def _generate_keypair() -> tuple[rsa.RSAPrivateKey, dict[str, Any]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = private_key.public_key().public_numbers()

    def _b64(value: int) -> str:
        byte_length = (value.bit_length() + 7) // 8
        raw = value.to_bytes(byte_length, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    jwk = {
        "kty": "RSA",
        "kid": "wh-test-key",
        "use": "sig",
        "alg": "RS256",
        "n": _b64(public_numbers.n),
        "e": _b64(public_numbers.e),
    }
    return private_key, jwk


def _sign(
    private_key: rsa.RSAPrivateKey, payload: dict[str, Any], kid: str = "wh-test-key"
) -> str:
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return jwt.encode(payload, pem, algorithm="RS256", headers={"kid": kid})


@pytest_asyncio.fixture
async def autenti_signature_row(app_auth_headers):  # noqa: ARG001 — drives admin seeding
    """Insert a Contract + Candidate + Client + DocumentSignature with a known
    ``autenti_process_id``. Returns the signature row.

    Cleans up nothing — relies on test DB being recreated between runs.
    """
    async with AsyncSessionLocal() as db:
        # Re-use any admin user — the fixture already seeded one.
        admin = await db.scalar(select(User).where(User.is_active.is_(True)).limit(1))
        assert admin is not None

        client = Client(name=f"Autenti Test Client {time.time_ns()}")
        db.add(client)
        await db.flush()

        candidate = Candidate(
            name="Anna",
            lastname="Testowa",
            email=f"anna+{time.time_ns()}@example.com",
            phone="+48555111222",
            legal_name="Anna Testowa JDG",
            nip="0000000000",
        )
        db.add(candidate)
        await db.flush()

        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            start_date=datetime(2026, 1, 1, tzinfo=timezone.utc).date(),
            end_date=datetime(2026, 12, 31, tzinfo=timezone.utc).date(),
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
        )
        db.add(contract)
        await db.flush()

        snapshot = ContractDocument(
            contract_id=contract.id,
            filename="snapshot.html",
            file_path="contracts/0/test.html",
            content_type="text/html",
            size_bytes=10,
            doc_type=ContractDocumentType.contract,
            uploaded_by=admin.id,
        )
        db.add(snapshot)
        await db.flush()

        sig = DocumentSignature(
            contract_id=contract.id,
            contract_document_id=snapshot.id,
            autenti_process_id=f"proc-test-{time.time_ns()}",
            autenti_signature_type="SES",
            status=SignatureStatus.sent,
            sender_user_id=admin.id,
            signer_email=candidate.email,
            signer_first_name=candidate.name,
            signer_last_name=candidate.lastname,
        )
        db.add(sig)
        await db.commit()
        await db.refresh(sig)
        yield sig


@pytest.fixture(autouse=True)
def _enable_autenti_and_reset(monkeypatch):
    """Enable router + reset JWKS cache for each test."""
    monkeypatch.setattr(settings, "AUTENTI_ENABLED", True)
    _reset_cache_for_tests()
    yield
    _reset_cache_for_tests()


@pytest.fixture
def keypair():
    return _generate_keypair()


@pytest.fixture
def patch_jwks(monkeypatch, keypair):
    private_key, jwk = keypair

    async def fake_fetch(force: bool = False):
        return {jwk["kid"]: jwk}

    monkeypatch.setattr("app.services.autenti.webhook_verify._fetch_jwks", fake_fetch)
    return private_key, jwk


@pytest.mark.asyncio
async def test_webhook_ok_for_known_process(
    app_client: AsyncClient,
    autenti_signature_row: DocumentSignature,
    patch_jwks,
    monkeypatch,
):
    """First-time event lands → 200 ok, status flips to in_progress."""
    private_key, _ = patch_jwks

    # Patch the signed-PDF download so completion path doesn't call real API.
    async def fake_download(self, *args, **kwargs):
        return b""

    monkeypatch.setattr(
        "app.services.autenti.client.AutentiClient.download_signed_file",
        fake_download,
    )

    payload = {
        "iat": int(time.time()),
        "iss": "autenti.com",
        "jti": f"evt-{time.time_ns()}",
        "eventType": "APPROVAL_PROCESS_CONSENTED",
        "processId": autenti_signature_row.autenti_process_id,
    }
    token = _sign(private_key, payload)

    resp = await app_client.post("/api/autenti/webhook", content=token)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "ok"}

    # DB side-effects
    async with AsyncSessionLocal() as db:
        events = (
            (
                await db.execute(
                    select(DocumentSignatureEvent).where(
                        DocumentSignatureEvent.signature_id == autenti_signature_row.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1
        assert events[0].event_type == "APPROVAL_PROCESS_CONSENTED"
        assert events[0].processed_at is not None


@pytest.mark.asyncio
async def test_webhook_duplicate_replay(
    app_client: AsyncClient,
    autenti_signature_row: DocumentSignature,
    patch_jwks,
):
    private_key, _ = patch_jwks
    payload = {
        "iat": int(time.time()),
        "jti": f"evt-dup-{time.time_ns()}",
        "eventType": "APPROVAL_PROCESS_CONSENTED",
        "processId": autenti_signature_row.autenti_process_id,
    }
    token = _sign(private_key, payload)

    first = await app_client.post("/api/autenti/webhook", content=token)
    assert first.status_code == 200
    second = await app_client.post("/api/autenti/webhook", content=token)
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"


@pytest.mark.asyncio
async def test_webhook_ignores_unknown_process(
    app_client: AsyncClient,
    patch_jwks,
):
    private_key, _ = patch_jwks
    payload = {
        "iat": int(time.time()),
        "jti": f"evt-unknown-{time.time_ns()}",
        "eventType": "APPROVAL_PROCESS_CONSENTED",
        "processId": "proc-does-not-exist",
    }
    token = _sign(private_key, payload)

    resp = await app_client.post("/api/autenti/webhook", content=token)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_webhook_rejects_tampered_signature(
    app_client: AsyncClient,
    patch_jwks,
):
    private_key, _ = patch_jwks
    payload = {
        "iat": int(time.time()),
        "jti": "evt-tampered",
        "processId": "anything",
    }
    token = _sign(private_key, payload)
    head, body, sig = token.split(".")
    tampered = f"{head}.{body}.{'A' * len(sig)}"

    resp = await app_client.post("/api/autenti/webhook", content=tampered)
    assert resp.status_code == 401
