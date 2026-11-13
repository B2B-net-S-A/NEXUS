"""Fałszywy KSeF 2.0 z sesją interaktywną wysyłki faktur (E4) — bez sieci.

Rozszerza ``tests/_ksef_fake.FakeKsef`` (uwierzytelnienie tokenem, klucze
publiczne MF) o ``/sessions/online``: serwer naprawdę odszyfrowuje klucz AES
swoim kluczem ``SymmetricKeyEncryption`` i plik faktury, sprawdza skróty
i rozmiary, a wynik przetwarzania bierze z kolejki ``invoice_codes``.
Numery KSeF fikcyjne, z poprawną sumą kontrolną.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import date
from typing import Any, Optional

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import padding as sym_padding
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from lxml import etree

from app.services.client_invoicing import ksef_send
from app.services.hr.ksef import numbers
from app.services.hr.ksef.client import format_instant
from tests._ksef_fake import TOKEN, Clock, FakeKsef, _error

FORM = {"systemCode": "FA (3)", "schemaVersion": "1-0E", "value": "FA"}
UPO = (
    b'<?xml version="1.0" encoding="UTF-8"?><Potwierdzenie>UPO testowe</Potwierdzenie>'
)


def _sha(content: bytes) -> str:
    return base64.b64encode(hashlib.sha256(content).digest()).decode("ascii")


class FakeKsefIssue(FakeKsef):
    def __init__(self, clock: Clock, **kwargs: Any) -> None:
        super().__init__(clock, **kwargs)
        #: Kody kolejnych odpowiedzi o status faktury (ostatni się powtarza).
        self.invoice_codes: list[int] = [100, 200]
        self.reject_details: list[str] = ["Element P_2 jest wymagany."]
        self.sessions: dict[str, dict[str, Any]] = {}
        self.received: list[bytes] = []
        self.closed: list[str] = []
        self.accepted: dict[str, str] = {}
        #: Wysyłka pliku: faktura zapisana, a potem ta odpowiedź (albo wyjątek
        #: sieci) — KSeF dostał plik, NEXUS nie dostał odpowiedzi.
        self.after_store: list[Any] = []
        #: Numer faktury → numer KSeF dla zapytania o metadane po numerze (po 440).
        self.known_numbers: dict[str, str] = {}
        self._technical = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v2")
        if request.method == "POST" and path == "/invoices/query/metadata":
            body = json.loads(request.content) if request.content else {}
            if "invoiceNumber" in body:
                self.calls.append(request)
                if not self._authorized(request):
                    return httpx.Response(401, json={"status": 401})
                number = body["invoiceNumber"]
                found = self.known_numbers.get(number)
                invoices = (
                    [{"ksefNumber": found, "invoiceNumber": number}] if found else []
                )
                return httpx.Response(
                    200, json={"invoices": invoices, "hasMore": False}
                )
        if not path.startswith("/sessions"):
            return super().handler(request)
        self.calls.append(request)
        for (method, prefix), queue in self.script.items():
            if request.method == method and path.startswith(prefix) and queue:
                return queue.pop(0)
        if not self._authorized(request):
            return httpx.Response(401, json={"title": "Unauthorized", "status": 401})
        body = json.loads(request.content) if request.content else {}
        parts = path.strip("/").split("/")
        if request.method == "POST" and parts == ["sessions", "online"]:
            return self._open(body)
        if request.method == "POST" and parts[:2] == ["sessions", "online"]:
            session = self.sessions.get(parts[2])
            if session is None:
                return _error(21405)
            if parts[3:] == ["invoices"]:
                return self._receive(session, body)
            if parts[3:] == ["close"]:
                self.closed.append(parts[2])
                return httpx.Response(204)
        if request.method == "GET" and parts[0] == "sessions":
            session = self.sessions.get(parts[1])
            if session is None:
                return _error(21405)
            if parts[2:] == ["invoices"]:
                return httpx.Response(
                    200,
                    json={
                        "invoices": [
                            {"referenceNumber": ref} for ref in session["invoices"]
                        ]
                    },
                )
            if len(parts) == 4 and parts[2] == "invoices":
                return self._status(session, parts[3])
            if len(parts) == 6 and parts[3] == "ksef" and parts[5] == "upo":
                if parts[4] not in self.accepted.values():
                    return _error(21164)
                return httpx.Response(
                    200, content=UPO, headers={"Content-Type": "application/xml"}
                )
        return httpx.Response(404, json={"detail": "nieznana ścieżka"})

    def _open(self, body: dict[str, Any]) -> httpx.Response:
        if body.get("formCode") != FORM:
            return _error(21405)
        encryption = body.get("encryption") or {}
        key = self.other_key.decrypt(
            base64.b64decode(encryption["encryptedSymmetricKey"]),
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        reference = self._next("20261120-SO-0000000000")
        self.sessions[reference] = {
            "key": key,
            "iv": base64.b64decode(encryption["initializationVector"]),
            "invoices": {},
        }
        return httpx.Response(
            201,
            json={
                "referenceNumber": reference,
                "validUntil": format_instant(self.clock()),
            },
        )

    def _receive(self, session: dict[str, Any], body: dict[str, Any]) -> httpx.Response:
        encrypted = base64.b64decode(body["encryptedInvoiceContent"])
        if (
            _sha(encrypted) != body["encryptedInvoiceHash"]
            or len(encrypted) != body["encryptedInvoiceSize"]
        ):
            return _error(21405)
        decryptor = Cipher(
            algorithms.AES(session["key"]), modes.CBC(session["iv"])
        ).decryptor()
        padded = decryptor.update(encrypted) + decryptor.finalize()
        unpadder = sym_padding.PKCS7(128).unpadder()
        xml = unpadder.update(padded) + unpadder.finalize()
        if _sha(xml) != body["invoiceHash"] or len(xml) != body["invoiceSize"]:
            return _error(21405)
        self.received.append(xml)
        reference = self._next("20261120-EE-0000000000")
        session["invoices"][reference] = xml
        if self.after_store:
            outcome = self.after_store.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return httpx.Response(202, json={"referenceNumber": reference})

    def _status(self, session: dict[str, Any], reference: str) -> httpx.Response:
        xml: Optional[bytes] = session["invoices"].get(reference)
        if xml is None:
            return _error(21405)
        code = (
            self.invoice_codes.pop(0)
            if len(self.invoice_codes) > 1
            else self.invoice_codes[0]
        )
        number = etree.fromstring(xml).findtext("{*}Fa/{*}P_2")
        payload: dict[str, Any] = {
            "ordinalNumber": 1,
            "referenceNumber": reference,
            "invoiceNumber": number,
            "invoiceHash": _sha(xml),
            "status": {"code": code, "description": "opis"},
        }
        if code == 200:
            if reference not in self.accepted:
                self._technical += 1
                self.accepted[reference] = numbers.make(
                    self.context_nip,
                    date(2026, 11, 20),
                    f"E4{self._technical:010X}",
                )
            payload["ksefNumber"] = self.accepted[reference]
            self.known_numbers.setdefault(number, self.accepted[reference])
            payload["acquisitionDate"] = format_instant(self.clock())
        elif code >= 400:
            payload["status"]["details"] = list(self.reject_details)
        return httpx.Response(200, json=payload)


def factory(fake: FakeKsefIssue) -> ksef_send.ClientFactory:
    async def _no_sleep(_seconds: float) -> None:
        return None

    def build(config: ksef_send.IssueConfig) -> ksef_send.KsefIssueClient:
        return ksef_send.KsefIssueClient(
            config.api_url or "https://api-test.ksef.mf.gov.pl/v2",
            context_nip=config.context_nip,
            token=config.token,
            transport=fake.transport,
            sleep=_no_sleep,
            now=fake.clock,
        )

    return build


__all__ = ["TOKEN", "UPO", "FakeKsefIssue", "factory"]
