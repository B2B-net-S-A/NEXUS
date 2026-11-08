"""Jednorazowa naprawa `repair-billing-hours-168`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0345_billing_hours_168` (2026-09-22).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_billing_hours_168`.
"""
# Jeden miesiąc roboczy 168 h (0345, decyzja 22.09.2026) — jednorazowo:
# znacznik 176 h/mc przechodzi do `contracts.orders_in_md`, a godziny
# rozliczeniowe 160/176 kontraktów i zamówień → 168 (inna, jawnie wybrana
# liczba zostaje). Żadna stawka nie jest przepisywana. Safety-net dla
# migracji 0345 (alembic na prodzie bywa osierocony). Jedno źródło SQL-a
# w `app/services/billing_hours_unification.py`; marker + advisory lock,
# `lock_timeout` 15 s — po przekroczeniu nic nie zapisuje, następny start
# ponawia. Log: wyłącznie liczby (paragon w `app_settings`).
