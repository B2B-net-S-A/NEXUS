"""Rekrutacja bez Delivery Leada dostaje DL-a opiekuna klienta (24.09.2026).

Decyzja Artura: każda rekrutacja ma swojego DL-a — gdy nikt nie jest wpisany
w rekrutacji, jest nim główny DL klienta (`delivery_lead_client_assignments`
z ``is_head``). Na produkcji 24.09 DL był wpisany w 4 z 327 otwartych
rekrutacji, bo import z Traffita tego pola nie ustawia, a zakładanie w NEXUSIE
(`auto_assign_owners.resolve_default_owners`) robi to tylko dla nowych.

Reguła jest UZUPEŁNIAJĄCA: DL wpisany przez człowieka nigdy nie jest
nadpisywany. DL wpisany przez automat (``delivery_lead_auto_filled``, 0376)
idzie za zmianą głównego DL-a klienta — do audytu 24.09.2026 zostawał przy
poprzednim, więc nowy DL nie widział przeglądu DL, a po odejściu starego
przegląd i alerty trafiały donikąd. Zamknięte rekrutacje zostają nietknięte — statystyki DL i liga DL i tak
liczą je przez głównego DL-a klienta (`insights_dl_scope`,
`competitions._resolve_dl_id`), więc ich uzupełnienie nic by nie dało.
Wołają ją: start aplikacji, faza rekrutacji importu z Traffita i zmiana
przypisania DL-a do klienta.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_HEADS = """
    SELECT DISTINCT ON (a.client_id) a.client_id, a.delivery_lead_user_id AS dl_id
      FROM delivery_lead_client_assignments a
      JOIN users u ON u.id = a.delivery_lead_user_id AND u.is_active
     WHERE a.is_head
     ORDER BY a.client_id, a.id
"""

# Puste pole albo DL wpisany przez automat, który nie jest już głównym DL-em.
_TARGET = """
       AND (j.delivery_lead_id IS NULL
            OR (j.delivery_lead_auto_filled AND j.delivery_lead_id <> h.dl_id))
       AND j.status IN ('draft', 'published')
"""

_FILL_ALL = text(
    f"""
    UPDATE jobs j SET delivery_lead_id = h.dl_id, delivery_lead_auto_filled = true
      FROM ({_HEADS}) h
     WHERE j.client_id = h.client_id
       {_TARGET}
    RETURNING j.id
    """
)

_FILL_CLIENTS = text(
    f"""
    UPDATE jobs j SET delivery_lead_id = h.dl_id, delivery_lead_auto_filled = true
      FROM ({_HEADS}) h
     WHERE j.client_id = h.client_id
       AND j.client_id = ANY(:client_ids)
       {_TARGET}
    RETURNING j.id
    """
)


async def fill_missing_job_delivery_leads(
    db: AsyncSession, client_ids: Optional[Iterable[int]] = None
) -> int:
    """Wpisuje głównego DL-a klienta w otwarte rekrutacje bez DL-a (albo z DL-em
    wpisanym automatycznie, który przestał być głównym DL-em klienta).

    Nie commituje — wołający zapisuje razem ze swoją zmianą. Zwraca liczbę
    uzupełnionych rekrutacji.
    """

    if client_ids is None:
        result = await db.execute(_FILL_ALL)
    else:
        ids = sorted({int(c) for c in client_ids if c is not None})
        if not ids:
            return 0
        result = await db.execute(_FILL_CLIENTS, {"client_ids": ids})
    filled = len(result.all())
    if filled:
        logger.info("job_delivery_lead_fill: filled=%d", filled)
    return filled


__all__ = ["fill_missing_job_delivery_leads"]
