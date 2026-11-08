"""Jednorazowa naprawa `repair-cez-standalone-md-duplicates`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0325_cez_standalone_md_duplicates` (2026-09-17).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_cez_standalone_md_duplicates`.
"""
# Centrum e-Zdrowia (09.2026) — jednorazowo: dwie osoby miały obok linii
# zamówienia grupowego CeZ/242/2025 stare, samodzielne zamówienie na tym samym
# kontrakcie (karta bez zużycia MD nad właściwą kartą). Anulowanie jak
# `DELETE /orders/{id}` (rekord zostaje, status „anulowane"), tylko gdy kontrakt
# jest żywy i ma żywą linię w aktywnej grupie; inaczej pominięcie z kodem.
# Logika w `scripts/repairs/cez_standalone_md_duplicate_repair.py`; marker
# w `app_settings` + advisory lock. Log: wyłącznie liczby, ID i kody powodów.
