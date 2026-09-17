"""Klienci z rozszerzonym zestawem alertów zamówień (BNP Paribas Bank Polska).

Jedna lista, dwie zmiany w powiadomieniach Delivery Leada — obie opisane
w tickecie „Powiadomienia o kończącym się zamówieniu dla BNP Paribas":

1. **Karta „kończy się okres" dla linii zamówienia wielo-konsultantowego.**
   ``rule_periodic_order_ending`` z założenia pomija linie grup
   (``order_group_id IS NULL``), bo u klientów rozliczanych na MD zamówienie
   kończy zwykle wyczerpanie budżetu, nie kalendarz. U BNP jest odwrotnie:
   zamówienia mają twardą datę końca (np. 31.12) i to ona jest sprawą do
   załatwienia. Dzwonek (``dl_portal_expiry_scanner``) te linie widzi od
   zawsze, ale daje jeden sygnał na próg — maila i powtórkę co 7 dni ma
   wyłącznie karta w panelu „Moi klienci".

2. **Alert o zużyciu PODSTAWY MD** (``md_base_usage_high``). Globalny
   ``md_budget_low`` startuje przy 21 MD POZOSTAŁYCH, liczonych od podstawy
   razem z zakresem opcjonalnym. Przy zamówieniu BNP na 220 MD to ~90%
   zużycia — za późno na nowy dokument PO.

Bramka jest **fail-closed**: pusta zmienna = obie reguły zachowują się
dokładnie jak przed tą rewizją, u wszystkich klientów.

Świadomie CSV z env, a nie zaszyte ``BNP_CLIENT_ID``: „BNP" to RODZINA
rekordów klienta (osobne wiersze oddziału i banku, do tego Cardif — patrz
``order_policies/known_clients.py`` i audyt ``/api/admin/client-mixups``),
więc id właściwej spółki ustala się na produkcji. Nie reużywamy też
``BNP_ORDER_EXTRACTION_CLIENT_IDS`` z rejestru polityk PDF: zdjęcie klienta
z polityki ODCZYTU dokumentów po cichu zabrałoby mu alerty.
"""

from __future__ import annotations

from app.core.config import settings


def extended_order_alert_client_ids() -> frozenset[int]:
    """``client_id`` klientów z rozszerzonymi alertami zamówień."""
    return settings.extended_order_alert_client_ids


def uses_extended_order_alerts(client_id: int | None) -> bool:
    """Czy ten klient ma rozszerzony zestaw alertów zamówień."""
    if client_id is None:
        return False
    return client_id in extended_order_alert_client_ids()


def md_base_usage_percent() -> float:
    """Próg alertu o zużyciu podstawy MD (procent ``md_total``)."""
    return float(settings.DL_ALERT_MD_BASE_USAGE_PERCENT)
