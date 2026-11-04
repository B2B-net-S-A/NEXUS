"""Źródło faktur dla pobierania: API KSeF albo pliki trybu ``simulate``.

Oba mają te same dwie metody co ``KsefClient``: ``query_metadata`` (jedna
strona metadanych) i ``download_invoice`` (XML po numerze KSeF). Tryb
``simulate`` czyta katalog ``KSEF_SIMULATE_DIR``: ``metadata.json``
(``{"invoices": [...]}`` w kształcie ``InvoiceMetadata`` z API) i pliki
``<numer KSeF>.xml`` — fikcyjne faktury do lokalnego przeklikania.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

import httpx

from app.services.hr.ksef import numbers
from app.services.hr.ksef.client import (
    PAGE_SIZE_MAX,
    SUBJECT_BUYER,
    SUBJECT_SELLER,
    KsefApiError,
    KsefClient,
    MetadataPage,
    format_instant,
    parse_instant,
)
from app.services.hr.ksef.environment import KsefConfig

_DATE_FIELDS = {
    "PermanentStorage": "permanentStorageDate",
    "Invoicing": "invoicingDate",
    "Issue": "issueDate",
}


class InvoiceSource(Protocol):
    requests: int

    async def __aenter__(self) -> "InvoiceSource": ...

    async def __aexit__(self, *_exc: object) -> None: ...

    async def query_metadata(
        self,
        *,
        subject_type: str,
        date_from: str,
        date_to: Optional[str] = None,
        date_type: str = "PermanentStorage",
        seller_nip: Optional[str] = None,
        page_offset: int = 0,
        page_size: int = PAGE_SIZE_MAX,
    ) -> MetadataPage: ...

    async def download_invoice(self, ksef_number: str) -> bytes: ...


class SimulatedSource:
    """Fikcyjne faktury z plików — bez sieci, z tymi samymi regułami okna dat."""

    def __init__(
        self,
        directory: Path,
        *,
        context_nip: str,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._directory = directory
        self._context_nip = context_nip
        self._now = now
        self.requests = 0

    async def __aenter__(self) -> "SimulatedSource":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    def _records(self) -> list[dict[str, Any]]:
        path = self._directory / "metadata.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise KsefApiError("unavailable") from None
        invoices = payload.get("invoices") if isinstance(payload, dict) else None
        return [item for item in invoices or [] if isinstance(item, dict)]

    def _party_matches(self, item: dict[str, Any], subject_type: str) -> bool:
        if not self._context_nip:
            return True
        if subject_type == SUBJECT_SELLER:
            return (item.get("seller") or {}).get("nip") == self._context_nip
        if subject_type == SUBJECT_BUYER:
            identifier = (item.get("buyer") or {}).get("identifier") or {}
            return identifier.get("value") == self._context_nip
        return False

    @staticmethod
    def _moment(item: dict[str, Any], date_type: str) -> Optional[datetime]:
        raw = item.get(_DATE_FIELDS[date_type])
        if date_type == "Issue" and isinstance(raw, str):
            try:
                day = date.fromisoformat(raw)
            except ValueError:
                return None
            return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        return parse_instant(raw)

    async def query_metadata(
        self,
        *,
        subject_type: str,
        date_from: str,
        date_to: Optional[str] = None,
        date_type: str = "PermanentStorage",
        seller_nip: Optional[str] = None,
        page_offset: int = 0,
        page_size: int = PAGE_SIZE_MAX,
    ) -> MetadataPage:
        self.requests += 1
        start = parse_instant(date_from)
        if start is None:
            raise KsefApiError("rejected", status=400)
        now = self._now()
        end = min(parse_instant(date_to) or now, now)
        selected = []
        for item in self._records():
            moment = self._moment(item, date_type)
            if moment is None or not (start <= moment <= end):
                continue
            if not self._party_matches(item, subject_type):
                continue
            if seller_nip and (item.get("seller") or {}).get("nip") != seller_nip:
                continue
            selected.append((moment, item))
        selected.sort(key=lambda pair: pair[0])
        size = max(10, min(page_size, PAGE_SIZE_MAX))
        page = selected[page_offset * size : (page_offset + 1) * size]
        return MetadataPage(
            invoices=[item for _, item in page],
            has_more=(page_offset + 1) * size < len(selected),
            is_truncated=False,
            hwm=format_instant(end) if date_type == "PermanentStorage" else None,
        )

    async def download_invoice(self, ksef_number: str) -> bytes:
        self.requests += 1
        if not numbers.is_valid(ksef_number):
            raise KsefApiError("not_found")
        path = self._directory / f"{ksef_number}.xml"
        try:
            return path.read_bytes()
        except OSError:
            raise KsefApiError("not_found") from None


def open_source(
    config: KsefConfig,
    *,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> InvoiceSource:
    """Źródło dla trybu z konfiguracji (wywołujący sprawdza ``config.enabled``)."""

    if config.mode == "simulate":
        return SimulatedSource(
            config.simulate_dir, context_nip=config.context_nip, now=now
        )
    if config.api_url is None:
        raise ValueError(f"tryb {config.mode} nie ma źródła faktur")
    return KsefClient(
        config.api_url,
        context_nip=config.context_nip,
        token=config.token,
        transport=transport,
        now=now,
    )
