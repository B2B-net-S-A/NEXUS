"""Tryb i konfiguracja KSeF (``KSEF_MODE``, ``KSEF_CONTEXT_NIP``, ``KSEF_TOKEN``).

Tryby:

* ``off`` — nic nie wychodzi (domyślnie),
* ``simulate`` — faktury z plików w ``KSEF_SIMULATE_DIR`` (domyślnie
  ``tests/data/ksef``), bez sieci — lokalne przeklikanie zakładki,
* ``test`` / ``demo`` / ``prod`` — API KSeF 2.0 Ministerstwa Finansów.

Środowisko API wymaga NIP-u spółki (10 cyfr, suma kontrolna) i tokenu;
brak któregoś = integracja wyłączona z powodem w karcie stanu.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.services.order_client_identity import nip_checksum_valid

MODES = ("off", "simulate", "test", "demo", "prod")
API_MODES = ("test", "demo", "prod")
#: Adresy z ``servers`` specyfikacji OpenAPI każdego środowiska (17.10.2026).
API_URLS = {
    "test": "https://api-test.ksef.mf.gov.pl/v2",
    "demo": "https://api-demo.ksef.mf.gov.pl/v2",
    "prod": "https://api.ksef.mf.gov.pl/v2",
}
MODE_LABELS = {
    "off": "wyłączone",
    "simulate": "symulacja (pliki lokalne)",
    "test": "testowe MF",
    "demo": "przedprodukcyjne MF (demo)",
    "prod": "produkcyjne MF",
}
DISABLED_REASONS = {
    "mode_off": "Pobieranie z KSeF jest wyłączone (KSEF_MODE=off).",
    "missing_context_nip": "Brak NIP-u spółki (KSEF_CONTEXT_NIP).",
    "invalid_context_nip": "NIP spółki w KSEF_CONTEXT_NIP ma złą sumę kontrolną.",
    "missing_token": "Brak tokenu KSeF spółki (KSEF_TOKEN).",
}

_DEFAULT_SIMULATE_DIR = Path(__file__).resolve().parents[4] / "tests" / "data" / "ksef"


@dataclass(frozen=True)
class KsefConfig:
    mode: str
    context_nip: str
    #: Sekret — poza ``repr``, żeby nie trafił do logów przy wypisaniu obiektu.
    token: str = field(repr=False)
    simulate_dir: Path

    @property
    def disabled_reason(self) -> Optional[str]:
        if self.mode == "off":
            return "mode_off"
        if self.mode == "simulate":
            return None
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

    @property
    def state_key(self) -> str:
        """Klucz znacznika pobierania: środowisko + NIP spółki (test ≠ prod)."""

        return f"{self.mode}:{self.context_nip or '-'}"


def current_mode() -> str:
    mode = str(getattr(settings, "KSEF_MODE", "off") or "off").strip().lower()
    return mode if mode in MODES else "off"


def load_config() -> KsefConfig:
    nip = "".join(
        ch
        for ch in str(getattr(settings, "KSEF_CONTEXT_NIP", "") or "")
        if ch.isdigit()
    )
    raw_dir = str(getattr(settings, "KSEF_SIMULATE_DIR", "") or "").strip()
    return KsefConfig(
        mode=current_mode(),
        context_nip=nip,
        token=str(getattr(settings, "KSEF_TOKEN", "") or "").strip(),
        simulate_dir=Path(raw_dir) if raw_dir else _DEFAULT_SIMULATE_DIR,
    )
