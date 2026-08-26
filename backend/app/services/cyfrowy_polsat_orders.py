"""Zamówienia specjalne klienta Cyfrowy Polsat S.A.

Ticket świadomie dotyczy jednego klienta i nie otwiera konfiguracji na kolejne
podmioty. Identyfikator pochodzi z kanonicznego rekordu produkcyjnego; bramka
idzie po ``client_id``, nie po nazwie podatnej na zmianę przez synchronizację.
"""

from __future__ import annotations


CYFROWY_POLSAT_CLIENT_ID = 38339


def is_cyfrowy_polsat_order_types_client(client_id: int | None) -> bool:
    """Czy klient ma jawny wybór: standardowe / kosztowe / wspólna pula MD."""

    return client_id == CYFROWY_POLSAT_CLIENT_ID
