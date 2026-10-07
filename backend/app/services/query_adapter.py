"""Adapter wektora zapytania oferta→kandydat (badanie 06.10.2026).

Macierz W (1024×1024) wyuczona na naszych parach „rekrutacja → osoba, którą
zespół zweryfikował” (`scripts/train_query_adapter.py`): cel = średnia osób
z prawdy minus średnia trudnych negatywów, ridge. Zapytanie po Voyage dostaje
``q' = normalize(q + a · q·W)``; wektory kandydatów zostają bez zmian, więc nic
nie trzeba przeliczać. Zmierzone na rekrutacjach z 2026 (sam wektor): top 100
+3,2 pkt proc., MRR +3,5 pkt proc. (`docs/audits/2026-10-06/…`).

Wołany WYŁĄCZNIE tam, gdzie wektor zapytania opisuje rekrutację i szuka
kandydatów (`request_vector` w ocenie kanonicznej, pełnym przeglądzie,
dopasowaniu w pipeline i kolejności „Szukaj ręcznie”). Nie dotyczy podobnych
rekrutacji, kierunku kandydat→oferta ani wyszukiwania tekstem.

Pamięci wektorów zapytań trzymają surowe wektory Voyage — adapter działa po
nich. Wersja macierzy wchodzi do `scoring_algorithm_version()`.
"""

from __future__ import annotations

import hashlib
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

ARTIFACT = Path(__file__).resolve().parent.parent / "data" / "query_adapter.npz"


class _Adapter:
    def __init__(self, matrix, alpha: float, model: str, sha: str):
        self.matrix = matrix
        self.alpha = alpha
        self.model = model
        self.sha = sha


@lru_cache(maxsize=1)
def _load() -> Optional[_Adapter]:
    if not ARTIFACT.exists():
        return None
    try:
        import numpy as np

        raw = ARTIFACT.read_bytes()
        with np.load(ARTIFACT, allow_pickle=False) as data:
            matrix = np.asarray(data["W"], dtype=np.float32)
            alpha = float(data["alpha"])
            model = str(data["model"])
        if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
            raise ValueError(f"zły kształt macierzy {matrix.shape}")
        return _Adapter(matrix, alpha, model, hashlib.sha256(raw).hexdigest())
    except Exception:  # noqa: BLE001 — zły plik = brak adaptera, nie awaria
        logger.exception("[query_adapter] nie da się wczytać %s", ARTIFACT.name)
        return None


def active() -> Optional[_Adapter]:
    """Adapter do użycia albo ``None`` (flaga OFF, brak pliku, inny model)."""
    if not getattr(settings, "QUERY_ADAPTER_ENABLED", False):
        return None
    adapter = _load()
    if adapter is None:
        return None
    if adapter.model != settings.VOYAGE_MODEL:
        # Macierz uczona na wektorach innego modelu nic nie znaczy. Ostrzeżenie
        # raz na proces — `active()` woła się na gorących ścieżkach oceny.
        _warn_model_mismatch(adapter.model, settings.VOYAGE_MODEL)
        return None
    return adapter


@lru_cache(maxsize=4)
def _warn_model_mismatch(matrix_model: str, active_model: str) -> None:
    logger.warning(
        "[query_adapter] model macierzy %s ≠ %s — adapter wyłączony",
        matrix_model,
        active_model,
    )


def version_tag() -> str:
    """Do klucza wyników oceny: skrót macierzy albo ``off``."""
    adapter = active()
    return f"{adapter.sha[:12]}:{adapter.alpha:g}" if adapter else "off"


def adapt_job_query(vector):
    """Wektor zapytania rekrutacji po adapterze. Bez adaptera — ten sam obiekt."""
    if vector is None:
        return None
    adapter = active()
    if adapter is None or len(vector) != adapter.matrix.shape[0]:
        return vector
    import numpy as np

    q = np.asarray(vector, dtype=np.float32)
    out = q + adapter.alpha * (q @ adapter.matrix)
    norm = float(np.linalg.norm(out))
    if not np.isfinite(norm) or norm == 0.0:
        return vector
    return (out / norm).astype(float).tolist()
