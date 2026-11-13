"""Wysyłka faktury sprzedaży do KSeF 2.0 — sesja interaktywna (E4).

Tryb ``KSEF_SALES_ISSUE_MODE`` (``off`` domyślnie, ``test``, ``prod``), kontekst
``KSEF_CONTEXT_NIP`` i osobny token ``KSEF_SALES_ISSUE_TOKEN`` z uprawnieniem
``InvoiceWrite`` (token odczytu ``KSEF_TOKEN`` go nie ma). Uwierzytelnienie,
odświeżanie tokenu, 429 i 5xx — wspólne z odczytem (``hr/ksef/client.py``).

Przebieg (dokumentacja MF „Sesja interaktywna”):

1. klucz AES-256 i wektor IV losowane na sesję; klucz szyfrowany RSA-OAEP
   (SHA-256) kluczem publicznym MF ``SymmetricKeyEncryption``,
2. ``POST /sessions/online`` z kodem formularza ``FA (3)`` / ``1-0E`` →
   ``referenceNumber`` sesji,
3. ``POST /sessions/online/{ref}/invoices`` — faktura zaszyfrowana AES-CBC
   (PKCS#7) z SHA-256 i rozmiarem pliku przed i po szyfrowaniu →
   ``referenceNumber`` faktury,
4. ``GET /sessions/{ref}/invoices/{invoiceRef}`` aż do wyniku: 200 = przyjęta
   (``ksefNumber``), 4xx/5xx = odrzucona z opisem, 100/150 = w toku,
5. ``POST /sessions/online/{ref}/close``, potem UPO faktury
   ``GET /sessions/{ref}/invoices/ksef/{ksefNumber}/upo``.

Logi: kategoria i kod — bez numerów KSeF, NIP-ów i kwot.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

from cryptography.hazmat.primitives import hashes, padding as sym_padding
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.core.config import settings
from app.services.client_invoicing.fa3_build import SCHEMA_VERSION, SYSTEM_CODE
from app.services.hr.ksef import crypto, numbers
from app.services.hr.ksef.client import (
    KsefApiError,
    KsefClient,
    _error_for,
    _json_object,
    parse_instant,
)
from app.services.hr.ksef.environment import API_URLS
from app.services.order_client_identity import nip_checksum_valid

logger = logging.getLogger(__name__)

MODES = ("off", "test", "prod")
MODE_LABELS = {
    "off": "wyłączona",
    "test": "środowisko testowe MF",
    "prod": "produkcyjne MF",
}
DISABLED_REASONS = {
    "mode_off": "Wysyłka faktur do KSeF jest wyłączona (KSEF_SALES_ISSUE_MODE=off).",
    "missing_context_nip": "Brak NIP-u spółki (KSEF_CONTEXT_NIP).",
    "invalid_context_nip": "NIP spółki w KSEF_CONTEXT_NIP ma złą sumę kontrolną.",
    "missing_token": "Brak tokenu KSeF z uprawnieniem do wystawiania faktur "
    "(KSEF_SALES_ISSUE_TOKEN).",
}
#: Odpytywanie statusu faktury w ramach jednej wysyłki (sekundy, łącznie ok. 14 s).
STATUS_POLL_DELAYS = (1.0, 1.0, 2.0, 2.0, 3.0, 5.0)
STATUS_ACCEPTED = 200
STATUS_PENDING = frozenset({100, 150})
UPO_MAX_BYTES = 2 * 1024 * 1024
#: Opisy kodów statusu faktury w sesji (dokumentacja MF, KSeF 2.0).
INVOICE_STATUS_LABELS = {
    100: "faktura przyjęta do dalszego przetwarzania",
    150: "trwa przetwarzanie",
    200: "sukces",
    405: "przetwarzanie anulowane z powodu błędu sesji",
    410: "nieprawidłowy zakres uprawnień",
    415: "brak możliwości wysłania faktury z załącznikiem",
    430: "błąd weryfikacji pliku faktury",
    435: "błąd odszyfrowania pliku",
    440: "duplikat faktury",
    450: "błąd weryfikacji semantyki dokumentu faktury",
    500: "nieznany błąd",
    550: "operacja anulowana przez system",
}


@dataclass(frozen=True)
class IssueConfig:
    mode: str
    context_nip: str
    token: str = field(repr=False)

    @property
    def disabled_reason(self) -> Optional[str]:
        if self.mode == "off":
            return "mode_off"
        if not self.context_nip:
            return "missing_context_nip"
        if not nip_checksum_valid(self.context_nip):
            return "invalid_context_nip"
        if not self.token:
            return "missing_token"
        return None

    @property
    def enabled(self) -> bool:
        return self.disabled_reason is None

    @property
    def api_url(self) -> Optional[str]:
        return API_URLS.get(self.mode)


def load_config() -> IssueConfig:
    mode = (
        str(getattr(settings, "KSEF_SALES_ISSUE_MODE", "off") or "off").strip().lower()
    )
    nip = "".join(
        ch
        for ch in str(getattr(settings, "KSEF_CONTEXT_NIP", "") or "")
        if ch.isdigit()
    )
    return IssueConfig(
        mode=mode if mode in MODES else "off",
        context_nip=nip,
        token=str(getattr(settings, "KSEF_SALES_ISSUE_TOKEN", "") or "").strip(),
    )


def status_payload(config: IssueConfig) -> dict[str, Any]:
    reason = config.disabled_reason
    return {
        "mode": config.mode,
        "mode_label": MODE_LABELS[config.mode],
        "enabled": reason is None,
        "disabled_reason": DISABLED_REASONS.get(reason) if reason else None,
    }


# ── Szyfrowanie ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SessionKey:
    key: bytes = field(repr=False)
    iv: bytes

    @classmethod
    def random(cls) -> "SessionKey":
        return cls(key=os.urandom(32), iv=os.urandom(16))

    def encrypt(self, content: bytes) -> bytes:
        padder = sym_padding.PKCS7(128).padder()
        padded = padder.update(content) + padder.finalize()
        encryptor = Cipher(algorithms.AES(self.key), modes.CBC(self.iv)).encryptor()
        return encryptor.update(padded) + encryptor.finalize()

    def wrapped(self, public_key: rsa.RSAPublicKey) -> str:
        ciphertext = public_key.encrypt(
            self.key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        return base64.b64encode(ciphertext).decode("ascii")


def _b64_sha256(content: bytes) -> str:
    return base64.b64encode(hashlib.sha256(content).digest()).decode("ascii")


# ── Klient ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InvoiceStatus:
    code: Optional[int]
    description: str
    details: tuple[str, ...] = ()
    ksef_number: Optional[str] = None
    acquired_at: Optional[datetime] = None

    @property
    def accepted(self) -> bool:
        return self.code == STATUS_ACCEPTED and self.ksef_number is not None

    @property
    def pending(self) -> bool:
        return self.code in STATUS_PENDING

    @property
    def text(self) -> str:
        label = INVOICE_STATUS_LABELS.get(self.code or 0) or self.description
        parts = [f"{label} (kod {self.code})" if self.code else label]
        parts.extend(self.details)
        return "; ".join(part for part in parts if part)[:500]


def _invoice_status(payload: dict[str, Any]) -> InvoiceStatus:
    status = payload.get("status") if isinstance(payload.get("status"), dict) else {}
    code = status.get("code") if isinstance(status.get("code"), int) else None
    details = tuple(
        " ".join(str(item).split())[:200]
        for item in status.get("details") or []
        if isinstance(item, str) and item.strip()
    )[:5]
    number = payload.get("ksefNumber")
    return InvoiceStatus(
        code=code,
        description=" ".join(str(status.get("description") or "").split())[:200],
        details=details,
        ksef_number=number if numbers.is_valid(number) else None,
        acquired_at=parse_instant(payload.get("acquisitionDate")),
    )


class KsefIssueClient(KsefClient):
    """Sesja interaktywna wysyłki faktur w kontekście NIP-u spółki."""

    async def open_session(self, key: SessionKey) -> str:
        try:
            public = crypto.pick_key(
                await self._public_keys(refresh=False),
                self._now(),
                crypto.SYMMETRIC_KEY_USAGE,
            )
        except crypto.PublicKeyError:
            raise KsefApiError("public_key") from None
        body = {
            "formCode": {
                "systemCode": SYSTEM_CODE,
                "schemaVersion": SCHEMA_VERSION,
                "value": "FA",
            },
            "encryption": {
                "encryptedSymmetricKey": key.wrapped(public.public_key),
                "initializationVector": base64.b64encode(key.iv).decode("ascii"),
            },
        }
        response = await self._authorized("POST", "/sessions/online", json_body=body)
        if response.status_code not in (200, 201):
            raise _error_for(response)
        reference = _json_object(response).get("referenceNumber")
        if not isinstance(reference, str) or not reference:
            raise KsefApiError("invalid_response", status=response.status_code)
        return reference

    async def send_invoice(self, session: str, key: SessionKey, xml: bytes) -> str:
        encrypted = key.encrypt(xml)
        body = {
            "invoiceHash": _b64_sha256(xml),
            "invoiceSize": len(xml),
            "encryptedInvoiceHash": _b64_sha256(encrypted),
            "encryptedInvoiceSize": len(encrypted),
            "encryptedInvoiceContent": base64.b64encode(encrypted).decode("ascii"),
            "offlineMode": False,
        }
        response = await self._authorized(
            "POST", f"/sessions/online/{session}/invoices", json_body=body
        )
        if response.status_code not in (200, 201, 202):
            raise _error_for(response)
        reference = _json_object(response).get("referenceNumber")
        if not isinstance(reference, str) or not reference:
            raise KsefApiError("invalid_response", status=response.status_code)
        return reference

    async def invoice_status(self, session: str, invoice: str) -> InvoiceStatus:
        response = await self._authorized(
            "GET", f"/sessions/{session}/invoices/{invoice}"
        )
        if response.status_code != 200:
            raise _error_for(response)
        return _invoice_status(_json_object(response))

    async def session_invoice_refs(self, session: str) -> list[str]:
        """Faktury sesji — gdy odpowiedź na wysyłkę przepadła, numer referencyjny
        faktury bierzemy stąd."""

        response = await self._authorized("GET", f"/sessions/{session}/invoices")
        if response.status_code != 200:
            raise _error_for(response)
        items = _json_object(response).get("invoices") or []
        return [
            item["referenceNumber"]
            for item in items
            if isinstance(item, dict) and isinstance(item.get("referenceNumber"), str)
        ]

    async def close_session(self, session: str) -> None:
        response = await self._authorized("POST", f"/sessions/online/{session}/close")
        if response.status_code not in (200, 202, 204):
            raise _error_for(response)

    async def download_upo(self, session: str, ksef_number: str) -> bytes:
        if not numbers.is_valid(ksef_number):
            raise KsefApiError("invalid_response")
        response = await self._authorized(
            "GET",
            f"/sessions/{session}/invoices/ksef/{ksef_number}/upo",
            accept="application/xml",
        )
        if response.status_code != 200:
            raise _error_for(response)
        if len(response.content) > UPO_MAX_BYTES:
            raise KsefApiError("too_large", status=200)
        return response.content


# ── Wysyłka ─────────────────────────────────────────────────────────────────


@dataclass
class TransmitResult:
    """Wynik wysyłki. ``stage`` mówi, dokąd doszła: ``open`` (sesja nie
    powstała), ``send`` (plik nie został przyjęty), ``status`` (plik przyjęty,
    wynik znany albo jeszcze nie)."""

    stage: str
    session_ref: Optional[str] = None
    invoice_ref: Optional[str] = None
    status: Optional[InvoiceStatus] = None
    upo: Optional[bytes] = None
    error: Optional[KsefApiError] = None


ClientFactory = Callable[[IssueConfig], KsefIssueClient]


def default_client(config: IssueConfig) -> KsefIssueClient:
    assert config.api_url is not None
    return KsefIssueClient(
        config.api_url, context_nip=config.context_nip, token=config.token
    )


async def _poll(
    client: KsefIssueClient,
    session: str,
    invoice: str,
    sleep: Callable[[float], Awaitable[Any]],
) -> InvoiceStatus:
    status = await client.invoice_status(session, invoice)
    for delay in STATUS_POLL_DELAYS:
        if not status.pending:
            break
        await sleep(delay)
        status = await client.invoice_status(session, invoice)
    return status


async def transmit(
    config: IssueConfig,
    xml: bytes,
    *,
    client_factory: ClientFactory = default_client,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> TransmitResult:
    """Otwiera sesję, wysyła fakturę, czeka chwilę na wynik, zamyka sesję."""

    result = TransmitResult(stage="open")
    key = SessionKey.random()
    async with client_factory(config) as client:
        try:
            result.session_ref = await client.open_session(key)
            result.stage = "send"
            result.invoice_ref = await client.send_invoice(result.session_ref, key, xml)
            result.stage = "status"
            result.status = await _poll(
                client, result.session_ref, result.invoice_ref, sleep
            )
        except KsefApiError as exc:
            logger.warning(
                "ksef-issue: wysyłka przerwana na etapie %s (%s)",
                result.stage,
                exc.label,
            )
            result.error = exc
        if result.session_ref:
            try:
                await client.close_session(result.session_ref)
            except KsefApiError:
                logger.info(
                    "ksef-issue: zamknięcie sesji nieudane — KSeF zamknie ją sam"
                )
        if result.status is not None and result.status.accepted:
            result.upo = await _upo(
                client, result.session_ref, result.status.ksef_number
            )
    return result


async def _upo(
    client: KsefIssueClient, session: Optional[str], ksef_number: Optional[str]
) -> Optional[bytes]:
    if not session or not ksef_number:
        return None
    try:
        return await client.download_upo(session, ksef_number)
    except KsefApiError:
        # UPO bywa gotowe dopiero po zamknięciu sesji — „Sprawdź status” dociągnie je później.
        logger.info("ksef-issue: UPO jeszcze niedostępne")
        return None


async def check(
    config: IssueConfig,
    *,
    session_ref: str,
    invoice_ref: Optional[str],
    ksef_number: Optional[str],
    client_factory: ClientFactory = default_client,
) -> TransmitResult:
    """„Sprawdź status”: wynik faktury w sesji i UPO (bez ponownej wysyłki)."""

    result = TransmitResult(
        stage="status", session_ref=session_ref, invoice_ref=invoice_ref
    )
    async with client_factory(config) as client:
        try:
            if result.invoice_ref is None:
                refs = await client.session_invoice_refs(session_ref)
                result.invoice_ref = refs[0] if len(refs) == 1 else None
                if result.invoice_ref is None:
                    result.stage = "send"
                    return result
            if ksef_number is None:
                result.status = await client.invoice_status(
                    session_ref, result.invoice_ref
                )
                ksef_number = (
                    result.status.ksef_number if result.status.accepted else None
                )
            else:
                result.status = InvoiceStatus(
                    code=STATUS_ACCEPTED, description="", ksef_number=ksef_number
                )
        except KsefApiError as exc:
            result.error = exc
            return result
        result.upo = await _upo(client, session_ref, ksef_number)
    return result


__all__ = [
    "DISABLED_REASONS",
    "INVOICE_STATUS_LABELS",
    "IssueConfig",
    "InvoiceStatus",
    "KsefIssueClient",
    "SessionKey",
    "TransmitResult",
    "check",
    "load_config",
    "status_payload",
    "transmit",
]
