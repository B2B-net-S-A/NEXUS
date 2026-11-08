"""Jednorazowa naprawa `repair-ended-tab-contracts`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0274_ended_tab_contract_repair` (2026-09-03).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_ended_tab_contracts`.
"""
# Reguła zakładki „Zakończeni" (09.2026) — jednorazowa korekta wskazanego
# kontraktu + audyt klasy (safety-net dla migracji 0274, gdy alembic na prodzie
# stoi na starszej rewizji). Jedno źródło SQL-a w
# `app/services/contract_ended_tab_repair.py`; blok jest idempotentny.
