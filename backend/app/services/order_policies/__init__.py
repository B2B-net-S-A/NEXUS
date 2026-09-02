"""Rejestr polityk odczytu PDF zamówienia per klient.

Jedno miejsce, w którym mówi się „u tego klienta odczyt podlega tej regule".
Ciała polityk (regexy, przeliczenia, czyszczenie pól) zostają tam, gdzie były —
w ``order_pdf_parser`` — ten pakiet trzyma wyłącznie *deklarację*: nazwa,
zmienna bramki, wpływ na wywołanie parsera, kolejność i wykluczenia.

Dlaczego osobny pakiet, a nie kolejne ``if`` w endpoincie: do 09.2026 dołożenie
klienta oznaczało edycję w czterech miejscach (stała env, funkcja bramki, ciało
polityki, blok kolejności w endpoincie) i żadne z nich nie wiedziało o pozostałych.
Przy siedmiu klientach to było znośne; ticket mailowy podnosi liczbę do
kilkunastu i dokłada drugiego konsumenta tej samej listy (ścieżkę mailową), więc
lista musi być danymi, nie kodem rozsianym po routerze.
"""

from app.services.order_policies.registry import (
    OrderClientPolicy,
    ParsePlan,
    PolicyContext,
    active_policies,
    apply_policies,
    client_ids_from_env,
    is_client_in_policy,
    parse_plan,
    policy_by_key,
)

__all__ = [
    "OrderClientPolicy",
    "ParsePlan",
    "PolicyContext",
    "active_policies",
    "apply_policies",
    "client_ids_from_env",
    "is_client_in_policy",
    "parse_plan",
    "policy_by_key",
]
