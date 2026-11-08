"""Jednorazowa naprawa `repair-contract-duplicate`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0308_contract_duplicate_merge` (2026-09-13).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_contract_duplicate`.
"""
# Duplikat kontraktu ze zgłoszenia (09.2026) — jednorazowo: dane, zamówienia,
# dokumenty i historia duplikatu przechodzą na kontrakt zachowany (bez
# nadpisywania uzupełnionych pól), duplikat jest usuwany trwale, a scalenie
# zapisane w dzienniku kontraktu i w Historii zdarzeń. Pary przypięte po ID
# (bez nazwisk w repo); niezgodna para zostaje nietknięta z kodem powodu.
# Logika w `app/services/contract_duplicate_merge_repair.py`; marker
# w `app_settings` + advisory lock. Porażka nie zapisuje niczego (rollback) —
# następny start spróbuje ponownie. Log: wyłącznie liczby, ID i kody powodów.
