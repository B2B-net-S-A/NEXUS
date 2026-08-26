"""Zamówienia specjalne klienta Lotte Wedel.

Ticket świadomie dotyczy jednego klienta i nie otwiera konfiguracji na kolejne
podmioty. Identyfikator 155 pochodzi z kanonicznego, aktywnego rekordu
produkcyjnego potwierdzonego odczytowym ``client-lookup`` 26.08.2026. Bramka
idzie po ``client_id``, nie po nazwie — w bazie istnieje historyczny duplikat
Lotte Wedel, którego ta funkcja nie może przypadkiem objąć.
"""

from __future__ import annotations


LOTTE_WEDEL_CLIENT_ID = 155


def is_lotte_wedel_order_types_client(client_id: int | None) -> bool:
    """Czy klient ma jawny wybór: standardowe / kosztowe / wspólna pula MD."""

    return client_id == LOTTE_WEDEL_CLIENT_ID
