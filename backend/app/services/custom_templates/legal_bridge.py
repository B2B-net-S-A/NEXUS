"""Cienka warstwa do fundamentu asystenta prawnego (część A planu).

Kontrakt z ``docs/asystent-prawny-plan.md``: pakiet ``app.services.legal``
z ``citations.extract(text)`` i ``citations.verify(text, passages)`` oraz
``corpus.get_provision(db, act_key, ref)``. Część A powstaje równolegle —
do scalenia jej gałęzi pakietu nie ma, więc każda funkcja tutaj działa
w dwóch trybach: z fundamentem albo bez (stan ``unverified``, „do
sprawdzenia”). Po scaleniu wystarczy, że kontrakt się zgadza; ten plik
jest jedynym miejscem, które trzeba wtedy przejrzeć.
"""

from __future__ import annotations

import importlib
import logging
from types import ModuleType

logger = logging.getLogger(__name__)


def _citations() -> ModuleType | None:
    try:
        return importlib.import_module("app.services.legal.citations")
    except ImportError:
        return None


def available() -> bool:
    return _citations() is not None


def citation_state(cite: str) -> str:
    """Czy cytat da się rozpoznać weryfikatorem fundamentu.

    Bez fundamentu — ``unverified``. Z fundamentem: ``extract`` musi rozpoznać
    przepis (``ok``), inaczej ``missing``. Pełne porównanie z tekstem
    przepisu (``verify`` z ``SourcePassage`` z korpusu) wymaga bazy i biegnie
    w ścieżce fundamentu, nie przy każdym zapisie szkicu."""
    module = _citations()
    if module is None:
        return "unverified"
    try:
        found = module.extract(cite)
    except Exception:  # noqa: BLE001 — fundament to dodatek do sprawdzeń
        logger.warning("legal_bridge: extract failed for %r", cite, exc_info=True)
        return "unverified"
    return "ok" if found else "missing"
