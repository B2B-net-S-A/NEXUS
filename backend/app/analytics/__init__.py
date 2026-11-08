"""Analytics v1 — wspólny fundament statystyk (plan 2026-07-16).

R0 (PR 1) wnosi tu wyłącznie warstwę uprawnień (``capabilities``) — twardy,
backendowy kontrakt na to KTO może widzieć JAKĄ klasę danych analitycznych.
Router ``/api/analytics/v1`` usunięty 08.11.2026 (D1 z audytu); zostały
capabilities, periods i metrics, z których korzystają pulpity i Insights.
"""
