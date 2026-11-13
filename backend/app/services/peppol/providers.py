"""Dostawca Peppol z API — adapter, żeby zmiana dostawcy nie ruszała reszty.

NEXUS nie ma własnego punktu dostępu (członkostwo OpenPeppol i certyfikacja to
koszt kilku tysięcy euro rocznie). Gotowy i zwalidowany UBL oddajemy
dostawcy, a on doręcza go do punktu dostępu odbiorcy i zgłasza wynik.

Interfejs (``PeppolProvider``):

* ``send(SendRequest) → SendResult`` — przyjęcie do wysyłki (identyfikator
  u dostawcy i stan, często od razu ``pending``),
* ``status(document_id) → SendResult`` — późniejszy wynik doręczenia.

Implementacje: ``SimulatedProvider`` (``PEPPOL_PROVIDER=simulate`` — pliki
w katalogu, staging i testy; nic nie wychodzi do sieci) i
``RecommandProvider`` (``PEPPOL_PROVIDER=recommand`` — REST
``POST /api/v1/{companyId}/send`` z ``documentType: "xml"`` i
``GET /api/v1/documents/{id}``, uwierzytelnienie Basic kluczem i sekretem).
Nowy dostawca = nowa klasa i wpis w ``open_provider``.

Do logów idzie kategoria błędu i status HTTP — bez kluczy, treści faktur
i odpowiedzi dostawcy.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

PROVIDERS = ("off", "simulate", "recommand")
REQUEST_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
#: Stany doręczenia w NEXUS-ie: przyjęta (czeka), doręczona, odrzucona.
PENDING, DELIVERED, FAILED = "pending", "delivered", "failed"


class ProviderError(RuntimeError):
    """Dostawca nie przyjął żądania (sieć, uwierzytelnienie, walidacja, 5xx)."""

    def __init__(self, message: str, *, category: str = "error", retry: bool = False) -> None:
        self.category = category
        self.retry = retry
        super().__init__(message)


@dataclass(frozen=True)
class SendRequest:
    xml: bytes
    doctype_id: str
    recipient: str
    #: Klucz idempotencji po naszej stronie (faktura + skrót pliku).
    reference: str


@dataclass(frozen=True)
class SendResult:
    document_id: str
    state: str  # pending | delivered | failed
    detail: Optional[str] = None
    raw_state: Optional[str] = None
    references: dict[str, Any] = field(default_factory=dict)


class PeppolProvider(Protocol):
    name: str

    async def send(self, request: SendRequest) -> SendResult: ...

    async def status(self, document_id: str) -> SendResult: ...


# ── Symulacja (staging, testy) ───────────────────────────────────────────────


class SimulatedProvider:
    """Zapisuje plik i od razu „doręcza”; adres ``0208:1234567894`` zwraca odrzucenie (jak w piaskownicy Recommand)."""

    name = "simulate"
    FAIL_RECIPIENT = "0208:1234567894"

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    async def send(self, request: SendRequest) -> SendResult:
        document_id = f"sim_{uuid.uuid4().hex[:16]}"
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / f"{document_id}.xml").write_bytes(request.xml)
        if request.recipient == self.FAIL_RECIPIENT:
            result = SendResult(document_id, FAILED, "recipient_not_found: odbiorca nie jest zarejestrowany w sieci Peppol")
        else:
            result = SendResult(document_id, DELIVERED, None, "delivered")
        (self.directory / f"{document_id}.json").write_text(
            json.dumps({"recipient": request.recipient, "state": result.state, "detail": result.detail})
        )
        return result

    async def status(self, document_id: str) -> SendResult:
        meta = self.directory / f"{Path(document_id).name}.json"
        if not meta.is_file():
            raise ProviderError("Dostawca nie zna tego dokumentu.", category="not_found")
        data = json.loads(meta.read_text())
        return SendResult(document_id, data["state"], data.get("detail"), data["state"])


# ── Recommand ────────────────────────────────────────────────────────────────


def _recommand_state(payload: dict[str, Any]) -> tuple[str, Optional[str], dict[str, Any]]:
    """``deliveryStatus`` + szczegóły nieudanej dostawy Peppol."""

    raw = payload.get("deliveryStatus")
    detail = None
    references: dict[str, Any] = {}
    for delivery in payload.get("deliveries") or []:
        if not isinstance(delivery, dict) or delivery.get("channel") != "peppol":
            continue
        references = dict(delivery.get("references") or {})
        failure = delivery.get("failure")
        if isinstance(failure, dict):
            parts = [str(failure.get(key)) for key in ("category", "message", "code") if failure.get(key)]
            detail = ": ".join(parts)[:500] or None
    if raw == "delivered":
        return DELIVERED, None, references
    if raw == "failed":
        return FAILED, detail or "Dostawca zgłosił nieudane doręczenie.", references
    return PENDING, None, references


def _errors_text(payload: Any) -> str:
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if isinstance(errors, dict):
        parts = []
        for key, values in errors.items():
            values = values if isinstance(values, list) else [values]
            parts.append(f"{key}: {'; '.join(str(v) for v in values)}")
        return " | ".join(parts)[:500]
    if isinstance(errors, list):
        return " | ".join(str(error) for error in errors)[:500]
    message = payload.get("message") if isinstance(payload, dict) else None
    return str(message or "Dostawca odrzucił dokument.")[:500]


class RecommandProvider:
    name = "recommand"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        api_secret: str,
        company_id: str,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.company_id = company_id
        self._auth = httpx.BasicAuth(api_key, api_secret)
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            auth=self._auth,
            timeout=REQUEST_TIMEOUT,
            transport=self._transport,
            headers={"User-Agent": "NEXUS-einvoices"},
        )

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            data = {}
        return data if isinstance(data, dict) else {}

    def _raise_for(self, response: httpx.Response, action: str) -> None:
        if response.status_code < 400:
            return
        logger.warning("[peppol] %s: HTTP %s", action, response.status_code)
        if response.status_code in (401, 403):
            raise ProviderError("Dostawca Peppol odrzucił klucz API.", category="auth")
        if response.status_code == 429 or response.status_code >= 500:
            raise ProviderError(
                "Dostawca Peppol chwilowo nie odpowiada — spróbuj za kilka minut.",
                category="unavailable",
                retry=True,
            )
        raise ProviderError(_errors_text(self._json(response)), category="rejected")

    async def send(self, request: SendRequest) -> SendResult:
        body = {
            "recipient": request.recipient,
            "documentType": "xml",
            "doctypeId": request.doctype_id,
            "document": request.xml.decode("utf-8"),
        }
        try:
            async with self._client() as client:
                response = await client.post(f"/api/v1/{self.company_id}/send", json=body)
        except httpx.HTTPError as exc:
            logger.warning("[peppol] send: %s", type(exc).__name__)
            raise ProviderError(
                "Brak połączenia z dostawcą Peppol.", category="network", retry=True
            ) from exc
        self._raise_for(response, "send")
        payload = self._json(response)
        if payload.get("success") is False:
            raise ProviderError(_errors_text(payload), category="rejected")
        document_id = str(payload.get("id") or "")
        if not document_id:
            raise ProviderError("Dostawca nie zwrócił identyfikatora dokumentu.", category="invalid_response")
        state, detail, references = _recommand_state(payload)
        return SendResult(document_id, state, detail, payload.get("deliveryStatus"), references)

    async def status(self, document_id: str) -> SendResult:
        try:
            async with self._client() as client:
                response = await client.get(f"/api/v1/documents/{document_id}")
        except httpx.HTTPError as exc:
            logger.warning("[peppol] status: %s", type(exc).__name__)
            raise ProviderError(
                "Brak połączenia z dostawcą Peppol.", category="network", retry=True
            ) from exc
        self._raise_for(response, "status")
        payload = self._json(response)
        document = payload.get("document") if isinstance(payload.get("document"), dict) else payload
        state, detail, references = _recommand_state(document)
        return SendResult(document_id, state, detail, document.get("deliveryStatus"), references)


# ── Wybór dostawcy ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    disabled_reason: Optional[str]

    @property
    def enabled(self) -> bool:
        return self.disabled_reason is None


def load_config() -> ProviderConfig:
    name = (settings.PEPPOL_PROVIDER or "off").strip().lower()
    if name not in PROVIDERS or name == "off":
        return ProviderConfig("off", "Wysyłka e-faktur jest wyłączona (brak dostawcy Peppol).")
    if name == "recommand" and not (
        settings.PEPPOL_API_KEY and settings.PEPPOL_API_SECRET and settings.PEPPOL_COMPANY_ID
    ):
        return ProviderConfig(name, "Brak klucza, sekretu albo firmy u dostawcy Peppol.")
    return ProviderConfig(name, None)


def open_provider(
    *, transport: Optional[httpx.AsyncBaseTransport] = None
) -> Optional[PeppolProvider]:
    config = load_config()
    if not config.enabled:
        return None
    if config.name == "simulate":
        directory = Path(settings.PEPPOL_SIMULATE_DIR or "/tmp/nexus-peppol-simulate")  # noqa: S108 — katalog symulacji
        return SimulatedProvider(directory)
    return RecommandProvider(
        base_url=settings.PEPPOL_API_URL,
        api_key=settings.PEPPOL_API_KEY,
        api_secret=settings.PEPPOL_API_SECRET,
        company_id=settings.PEPPOL_COMPANY_ID,
        transport=transport,
    )
