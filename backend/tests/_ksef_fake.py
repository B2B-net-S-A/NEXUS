"""Fałszywy serwer KSeF 2.0 dla testów (bez sieci, ``httpx.MockTransport``).

Odpowiedzi w kształcie ze specyfikacji OpenAPI MF (``api-test.ksef.mf.gov.pl/docs/v2``):
challenge, klucze publiczne (własna para RSA — serwer naprawdę odszyfrowuje
token), uwierzytelnienie tokenem z odpytywaniem statusu, ``redeem``/``refresh``,
metadane faktur z oknem ``PermanentStorage`` i znacznikiem HWM, XML faktury
z nagłówkiem ``x-ms-meta-hash``. Faktury z ``tests/data/ksef`` (fikcyjne NIP-y
i numery KSeF z poprawną sumą kontrolną).
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from app.services.hr.ksef.client import format_instant, parse_instant

BASE = "https://api-test.ksef.mf.gov.pl/v2"
DATA_DIR = Path(__file__).parent / "data" / "ksef"
TOKEN = "fikcyjny-token-ksef-do-testow"
COMPANY_NIP = "9876543210"
OLA_NIP = "1234563218"
ANNA_NIP = "7777777777"
SUPPLIER_NIP = "5555555555"
OLA_INVOICE = "1234563218-20261003-5F2A9C0D71B3-C3"
ANNA_INVOICE = "7777777777-20261004-0B91E4C2A7D8-A7"
ANNA_CORRECTION = "7777777777-20261006-1C02F5D3B8E9-BA"
SUPPLIER_INVOICE = "5555555555-20261005-77C1A0E9B2F4-F7"


@dataclass
class Clock:
    moment: datetime = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, **delta: float) -> None:
        self.moment = self.moment + timedelta(**delta)


def _certificate(key: rsa.RSAPrivateKey, now: datetime) -> bytes:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Klucz testowy KSeF")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now - timedelta(days=30))
        .not_valid_after(now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.DER)


def _key_id(key: rsa.RSAPrivateKey) -> str:
    spki = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return base64.b64encode(hashlib.sha256(spki).digest()).decode("ascii")


def _error(code: int, status: int = 400) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "title": "Bad Request",
            "status": status,
            "detail": "Żądanie jest nieprawidłowe.",
            "errors": [{"code": code, "description": "opis", "details": []}],
            "instance": "/v2",
            "timestamp": "2026-10-17T12:00:00+00:00",
            "traceId": "00000000000000000000000000000000",
        },
    )


class FakeKsef:
    def __init__(
        self,
        clock: Clock,
        *,
        token: str = TOKEN,
        context_nip: str = COMPANY_NIP,
        data_dir: Path = DATA_DIR,
    ) -> None:
        self.clock = clock
        self.token = token
        self.context_nip = context_nip
        self.private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        )
        self.public_key_id = _key_id(self.private_key)
        self.other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        payload = json.loads((data_dir / "metadata.json").read_text(encoding="utf-8"))
        self.metadata: list[dict[str, Any]] = payload["invoices"]
        self.xml: dict[str, bytes] = {
            path.stem: path.read_bytes() for path in data_dir.glob("*.xml")
        }
        self.calls: list[httpx.Request] = []
        self.bodies: list[dict[str, Any]] = []
        #: Odpowiedzi podstawione na kolejne wywołania (metoda, ścieżka bez /v2).
        self.script: dict[tuple[str, str], list[httpx.Response]] = {}
        self.auth_codes: list[int] = [100, 200]
        self.hwm: Optional[datetime] = None
        self.not_ready: set[str] = set()
        self.challenges: dict[str, int] = {}
        self.access: dict[str, datetime] = {}
        self.refresh: dict[str, datetime] = {}
        self.redeemed: set[str] = set()
        self.decrypted: list[str] = []
        self.rejected_key_ids: set[str] = set()
        self.access_ttl = timedelta(minutes=15)
        self._serial = 0

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def paths(self) -> list[str]:
        return [f"{r.method} {r.url.path.removeprefix('/v2')}" for r in self.calls]

    def count(self, method: str, path: str) -> int:
        return self.paths().count(f"{method} {path}")

    def _next(self, prefix: str) -> str:
        self._serial += 1
        return f"{prefix}-{self._serial}"

    def _bearer(self, request: httpx.Request) -> str:
        header = request.headers.get("Authorization") or ""
        return header.removeprefix("Bearer ").strip()

    def _authorized(self, request: httpx.Request) -> bool:
        until = self.access.get(self._bearer(request))
        return until is not None and until > self.clock()

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path.removeprefix("/v2")
        body: dict[str, Any] = {}
        if request.content:
            try:
                body = json.loads(request.content)
            except ValueError:
                body = {}
        self.bodies.append(body)
        for (method, prefix), queue in self.script.items():
            if request.method == method and path.startswith(prefix) and queue:
                return queue.pop(0)
        now = self.clock()

        if request.method == "POST" and path == "/auth/challenge":
            challenge = self._next("20261017-CR-0000000000-00000000")
            stamp = int(now.timestamp() * 1000)
            self.challenges[challenge] = stamp
            return httpx.Response(
                200,
                json={
                    "challenge": challenge,
                    "timestamp": format_instant(now),
                    "timestampMs": stamp,
                    "clientIp": "127.0.0.1",
                },
            )
        if request.method == "GET" and path == "/security/public-key-certificates":
            return httpx.Response(200, json=self._certificates(now))
        if request.method == "POST" and path == "/auth/ksef-token":
            return self._ksef_token(body)
        if request.method == "GET" and path.startswith("/auth/"):
            code = (
                self.auth_codes.pop(0)
                if len(self.auth_codes) > 1
                else self.auth_codes[0]
            )
            return httpx.Response(
                200,
                json={
                    "startDate": format_instant(now),
                    "authenticationMethod": "Token",
                    "authenticationMethodInfo": {
                        "category": "Token",
                        "code": "token",
                        "displayName": "Token KSeF",
                    },
                    "status": {"code": code, "description": "opis"},
                },
            )
        if request.method == "POST" and path == "/auth/token/redeem":
            operation = self._bearer(request)
            if operation in self.redeemed:
                return _error(21301)
            self.redeemed.add(operation)
            return httpx.Response(200, json=self._tokens(now, with_refresh=True))
        if request.method == "POST" and path == "/auth/token/refresh":
            until = self.refresh.get(self._bearer(request))
            if until is None or until <= now:
                return _error(21301)
            return httpx.Response(200, json=self._tokens(now, with_refresh=False))
        if not self._authorized(request):
            return httpx.Response(
                401, json={"title": "Unauthorized", "status": 401, "detail": "Brak"}
            )
        if request.method == "POST" and path == "/invoices/query/metadata":
            return self._metadata(request, body, now)
        if request.method == "GET" and path.startswith("/invoices/ksef/"):
            number = path.rsplit("/", 1)[-1]
            if number in self.not_ready:
                return _error(21165)
            content = self.xml.get(number)
            if content is None:
                return _error(21164)
            digest = base64.b64encode(hashlib.sha256(content).digest()).decode("ascii")
            return httpx.Response(
                200,
                content=content,
                headers={"Content-Type": "application/xml", "x-ms-meta-hash": digest},
            )
        return httpx.Response(404, json={"detail": "nieznana ścieżka"})

    def _certificates(self, now: datetime) -> list[dict[str, Any]]:
        def entry(key: rsa.RSAPrivateKey, usage: str) -> dict[str, Any]:
            der = _certificate(key, now)
            return {
                "certificate": base64.b64encode(der).decode("ascii"),
                "certificateId": base64.b64encode(
                    hashlib.sha256(der).digest()
                ).decode(),
                "publicKeyId": _key_id(key),
                "validFrom": format_instant(now - timedelta(days=30)),
                "validTo": format_instant(now + timedelta(days=365)),
                "usage": [usage],
            }

        return [
            entry(self.other_key, "SymmetricKeyEncryption"),
            entry(self.private_key, "KsefTokenEncryption"),
        ]

    def _ksef_token(self, body: dict[str, Any]) -> httpx.Response:
        if body.get("publicKeyId") in self.rejected_key_ids:
            return _error(21470)
        stamp = self.challenges.pop(str(body.get("challenge")), None)
        if stamp is None:
            return _error(21111)
        context = body.get("contextIdentifier") or {}
        plaintext = self.private_key.decrypt(
            base64.b64decode(body["encryptedToken"]),
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        ).decode("utf-8")
        self.decrypted.append(plaintext)
        if plaintext != f"{self.token}|{stamp}" or context != {
            "type": "Nip",
            "value": self.context_nip,
        }:
            self.auth_codes = [450]
        operation = self._next("op")
        return httpx.Response(
            202,
            json={
                "referenceNumber": self._next("20261017-AU-0000000000-0000000000"),
                "authenticationToken": {
                    "token": operation,
                    "validUntil": format_instant(self.clock() + timedelta(minutes=10)),
                },
            },
        )

    def _tokens(self, now: datetime, *, with_refresh: bool) -> dict[str, Any]:
        access = self._next("acc")
        self.access[access] = now + self.access_ttl
        result: dict[str, Any] = {
            "accessToken": {
                "token": access,
                "validUntil": format_instant(now + self.access_ttl),
            }
        }
        if with_refresh:
            refresh = self._next("ref")
            self.refresh[refresh] = now + timedelta(days=7)
            result["refreshToken"] = {
                "token": refresh,
                "validUntil": format_instant(now + timedelta(days=7)),
            }
        return result

    def _metadata(
        self, request: httpx.Request, body: dict[str, Any], now: datetime
    ) -> httpx.Response:
        date_range = body.get("dateRange") or {}
        start = parse_instant(date_range.get("from"))
        if start is None:
            return _error(21405)
        hwm = min(self.hwm or now, now)
        end = parse_instant(date_range.get("to")) or now
        if date_range.get("restrictToPermanentStorageHwmDate"):
            end = min(end, hwm)
        subject = body.get("subjectType")
        selected = []
        for item in self.metadata:
            moment = parse_instant(item.get("permanentStorageDate"))
            if moment is None or not (start <= moment <= end):
                continue
            if subject == "Subject2":
                if item["buyer"]["identifier"]["value"] != self.context_nip:
                    continue
            elif subject == "Subject1":
                if item["seller"]["nip"] != self.context_nip:
                    continue
            if body.get("sellerNip") and item["seller"]["nip"] != body["sellerNip"]:
                continue
            selected.append(item)
        selected.sort(key=lambda item: item["permanentStorageDate"])
        offset = int(request.url.params.get("pageOffset", 0))
        size = int(request.url.params.get("pageSize", 10))
        page = selected[offset * size : (offset + 1) * size]
        return httpx.Response(
            200,
            json={
                "hasMore": (offset + 1) * size < len(selected),
                "isTruncated": False,
                "permanentStorageHwmDate": format_instant(end),
                "invoices": page,
            },
        )


def rate_limited(seconds: int) -> httpx.Response:
    return httpx.Response(
        429,
        headers={"Retry-After": str(seconds)},
        json={
            "status": {
                "code": 429,
                "description": "Too Many Requests",
                "details": [f"Spróbuj ponownie po {seconds} sekundach."],
            }
        },
    )
