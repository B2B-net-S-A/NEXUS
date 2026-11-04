"""Źródło urządzeń z Intune dla ewidencji sprzętu (etap 4, D9) — wyłącznie odczyt.

Tryby (``EQUIPMENT_INTUNE_MODE``):

* ``off`` — nic nie czytamy (domyślnie, do zgody administratora M365),
* ``simulate`` — stała, fikcyjna lista urządzeń; pozwala przeklikać zakładkę
  „Intune” lokalnie, bez Microsoftu,
* ``live`` — Graph ``GET /deviceManagement/managedDevices`` tokenem rejestracji
  „NEXUS Kadry” (``app/services/hr/m365/auth.py``, ten sam mechanizm co urlopy),
  uprawnienie aplikacyjne ``DeviceManagementManagedDevices.Read.All``.

``$select`` bierze tylko pola ewidencji. Kluczy BitLocker (osobny zasób
``informationProtection/bitlocker``), haseł, IMEI ani numerów telefonów nie
pobieramy wcale, a ``device_from_graph`` przepuszcza wyłącznie znane pola —
nawet gdyby Graph zwrócił więcej.

Klient to ``AppGraphClient`` (ponowienia 429/503 z ``Retry-After``, nowy token
po 401, twardy limit czasu żądania). Tu dochodzą: ponowienie pozostałych 5xx,
limit stron i kontrola, że ``@odata.nextLink`` prowadzi do Graph — token
aplikacji nie może pojechać pod adres podany w odpowiedzi.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional, Protocol
from zoneinfo import ZoneInfo

import httpx

from app.core.config import settings
from app.core.scheduling import DEFAULT_TZ
from app.services.hr.m365.ops import categorize

logger = logging.getLogger(__name__)

MODES = ("off", "simulate", "live")
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
DEVICES_PATH = "/deviceManagement/managedDevices"

#: Jedyne pola, o które prosimy Graph (i jedyne, które zapisujemy).
SELECT_FIELDS: tuple[str, ...] = (
    "id",
    "deviceName",
    "serialNumber",
    "manufacturer",
    "model",
    "operatingSystem",
    "userPrincipalName",
    "complianceState",
    "lastSyncDateTime",
)

#: Ponawiane 5xx. 429 i 503 ponawia już ``GraphClient`` z ``Retry-After``,
#: a 599 to jego twardy limit czasu (2 min) — powtórka tylko by go mnożyła.
RETRYABLE_STATUSES = frozenset({500, 502, 504})
SERVER_ERROR_DELAYS = (5.0, 15.0)
#: Firma ma kilkaset urządzeń; limit chroni przed pętlą na zepsutym ``nextLink``.
MAX_PAGES = 50

#: Długości kolumn ``equipment_intune_devices`` — dłuższa wartość jest przycinana.
_LIMITS = {
    "device_name": 255,
    "serial_number": 128,
    "manufacturer": 120,
    "model": 160,
    "operating_system": 60,
    "user_principal_name": 255,
    "compliance_state": 32,
}


def current_mode() -> str:
    """Tryb z ``EQUIPMENT_INTUNE_MODE``; nieznana wartość = ``off``.

    ``getattr``, bo pole dochodzi do ``config.py`` osobno — moduł działa
    (i jest wyłączony), zanim się tam pojawi.
    """

    mode = str(getattr(settings, "EQUIPMENT_INTUNE_MODE", "off") or "off")
    mode = mode.strip().lower()
    return mode if mode in MODES else "off"


@dataclass(frozen=True)
class IntuneDevice:
    intune_device_id: str
    device_name: Optional[str]
    serial_number: Optional[str]
    manufacturer: Optional[str]
    model: Optional[str]
    operating_system: Optional[str]
    user_principal_name: Optional[str]
    compliance_state: Optional[str]
    last_sync_at: Optional[datetime]


class IntuneSourceError(Exception):
    """Odmowa albo awaria odczytu; ``label`` (kategoria i status) trafia do
    ``last_error`` — bez treści odpowiedzi Graph, która cytuje adresy i nazwy."""

    def __init__(self, status: Optional[int], *, category: Optional[str] = None):
        self.status = status
        self.category = category or categorize(status)
        super().__init__(self.label)

    @property
    def label(self) -> str:
        return f"{self.category} ({self.status})" if self.status else self.category


def _text(value: Any, field: str) -> Optional[str]:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text[: _LIMITS[field]] or None


def _instant(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    # Graph oznacza „nigdy” datą 0001-01-01.
    return None if moment.year < 2000 else moment


def device_from_graph(raw: Any) -> Optional[IntuneDevice]:
    """Wiersz Graph → ``IntuneDevice`` (tylko pola z ``SELECT_FIELDS``)."""

    if not isinstance(raw, dict):
        return None
    device_id = str(raw.get("id") or "").strip()
    if not device_id or len(device_id) > 64:
        # Identyfikator Intune to GUID; przycięty dawałby kolizje przy upsercie.
        return None
    return IntuneDevice(
        intune_device_id=device_id,
        device_name=_text(raw.get("deviceName"), "device_name"),
        serial_number=_text(raw.get("serialNumber"), "serial_number"),
        manufacturer=_text(raw.get("manufacturer"), "manufacturer"),
        model=_text(raw.get("model"), "model"),
        operating_system=_text(raw.get("operatingSystem"), "operating_system"),
        user_principal_name=_text(raw.get("userPrincipalName"), "user_principal_name"),
        compliance_state=_text(raw.get("complianceState"), "compliance_state"),
        last_sync_at=_instant(raw.get("lastSyncDateTime")),
    )


class DeviceSource(Protocol):
    async def list_devices(self) -> list[IntuneDevice]: ...


# ── Symulacja ─────────────────────────────────────────────────────────────────

#: Fikcyjne urządzenia (repo jest publiczne): S/N „SIMSN…”, UPN @example.com.
_SIMULATED: tuple[dict[str, Any], ...] = (
    {
        "id": "sim-device-0001",
        "deviceName": "LAPTOP-SIM-01",
        "serialNumber": "SIMSN0001",
        "manufacturer": "Lenovo",
        "model": "ThinkPad T14",
        "operatingSystem": "Windows",
        "userPrincipalName": "anna.przykladowa@example.com",
        "complianceState": "compliant",
    },
    {
        "id": "sim-device-0002",
        "deviceName": "LAPTOP-SIM-02",
        "serialNumber": "SIMSN0002",
        "manufacturer": "Dell",
        "model": "Latitude 5440",
        "operatingSystem": "Windows",
        "userPrincipalName": "jan.testowy@example.com",
        "complianceState": "noncompliant",
    },
    {
        "id": "sim-device-0003",
        "deviceName": "MAC-SIM-03",
        "serialNumber": "SIMSN0003",
        "manufacturer": "Apple",
        "model": "MacBook Air",
        "operatingSystem": "macOS",
        "userPrincipalName": "ewa.przykladowa@example.com",
        "complianceState": "compliant",
    },
    {
        "id": "sim-device-0004",
        "deviceName": "LAPTOP-SIM-SALA",
        "serialNumber": "SIMSN0004",
        "manufacturer": "HP",
        "model": "ProBook 450",
        "operatingSystem": "Windows",
        "userPrincipalName": None,
        "complianceState": "compliant",
    },
    {
        "id": "sim-device-0005",
        "deviceName": "LAPTOP-SIM-05",
        "serialNumber": None,
        "manufacturer": "Lenovo",
        "model": "ThinkPad E14",
        "operatingSystem": "Windows",
        "userPrincipalName": "piotr.przykladowy@example.com",
        "complianceState": "inGracePeriod",
    },
)


class SimulatedIntuneSource:
    """Ta sama lista przy każdym przebiegu; data synchronizacji z dnia przebiegu."""

    def __init__(self, now: Optional[datetime] = None) -> None:
        self._now = now

    async def list_devices(self) -> list[IntuneDevice]:
        now = self._now or datetime.now(timezone.utc)
        local_day = now.astimezone(ZoneInfo(DEFAULT_TZ)).date()
        synced = datetime.combine(local_day, time(5), tzinfo=ZoneInfo(DEFAULT_TZ))
        devices = []
        for index, raw in enumerate(_SIMULATED):
            moment = synced - timedelta(hours=index)
            device = device_from_graph(
                {**raw, "lastSyncDateTime": moment.astimezone(timezone.utc).isoformat()}
            )
            if device is not None:
                devices.append(device)
        return devices


# ── Graph ─────────────────────────────────────────────────────────────────────


class GraphIntuneSource:
    """``managedDevices`` przez ``AppGraphClient`` z tokenem rejestracji HR.

    ``client_factory`` i ``sleep`` podmieniają testy (fałszywy transport HTTP,
    bez czekania); produkcja bierze domyślne.
    """

    def __init__(
        self,
        *,
        client_factory: Optional[Callable[[], Any]] = None,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        max_pages: int = MAX_PAGES,
    ) -> None:
        self._client_factory = client_factory
        self._sleep = sleep
        self._max_pages = max_pages

    def _client(self) -> Any:
        if self._client_factory is not None:
            return self._client_factory()
        from app.services.hr.m365.auth import acquire_hr_token
        from app.services.m365.app_graph_client import AppGraphClient

        return AppGraphClient(token_provider=acquire_hr_token)

    async def list_devices(self) -> list[IntuneDevice]:
        from app.services.m365.app_graph_client import AppOnlyTokenUnavailable

        client = self._client()
        try:
            await client.__aenter__()
        except AppOnlyTokenUnavailable:
            raise IntuneSourceError(None, category="auth") from None
        try:
            return await self._collect(client)
        finally:
            await client.close()

    async def _collect(self, client: Any) -> list[IntuneDevice]:
        url: Optional[str] = DEVICES_PATH
        params: Optional[dict[str, str]] = {"$select": ",".join(SELECT_FIELDS)}
        devices: list[IntuneDevice] = []
        pages = 0
        while url:
            pages += 1
            if pages > self._max_pages:
                raise IntuneSourceError(None, category="too_many_pages")
            page = await self._get(client, url, params)
            if not isinstance(page, dict):
                raise IntuneSourceError(None, category="bad_response")
            for raw in page.get("value") or []:
                device = device_from_graph(raw)
                if device is not None:
                    devices.append(device)
            next_link = page.get("@odata.nextLink")
            if next_link and not str(next_link).startswith(f"{GRAPH_BASE}/"):
                raise IntuneSourceError(None, category="bad_next_link")
            # ``nextLink`` niesie już ``$select`` i ``$skiptoken``.
            url, params = (str(next_link) if next_link else None), None
        return devices

    async def _get(
        self, client: Any, url: str, params: Optional[dict[str, str]]
    ) -> Any:
        from app.services.m365.app_graph_client import AppOnlyTokenUnavailable
        from app.services.m365.graph_client import GraphRequestError

        attempt = 0
        while True:
            try:
                return await client.get(url, params=params)
            except GraphRequestError as exc:
                retryable = exc.status in RETRYABLE_STATUSES
                if retryable and attempt < len(SERVER_ERROR_DELAYS):
                    delay = SERVER_ERROR_DELAYS[attempt]
                    attempt += 1
                    logger.warning(
                        "equipment_intune: Graph %s, ponowienie %d za %.0f s",
                        exc.status,
                        attempt,
                        delay,
                    )
                    await self._sleep(delay)
                    continue
                raise IntuneSourceError(exc.status) from None
            except AppOnlyTokenUnavailable:
                raise IntuneSourceError(None, category="auth") from None
            except httpx.TimeoutException:
                raise IntuneSourceError(None, category="timeout") from None
            except httpx.HTTPError:
                raise IntuneSourceError(None, category="network") from None


def source_for(mode: str, *, now: Optional[datetime] = None) -> DeviceSource:
    if mode == "simulate":
        return SimulatedIntuneSource(now)
    if mode == "live":
        return GraphIntuneSource()
    raise ValueError(f"Tryb {mode!r} nie czyta urządzeń.")
