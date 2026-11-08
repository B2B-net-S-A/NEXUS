"""Jednorazowa naprawa `cleanup-prod-test-records`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `prod_test_records_cleanup_2026_10_20` (2026-10-20).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_cleanup_prod_test_records`.
"""
# Rekordy testowe z ręcznego audytu UI 26–27.09.2026 (decyzja Artura
# 20.10.2026) — jednorazowo: szkice zamówień i kontrakty klienta testowego
# → void, spotkania z Outlooka podpięte do osoby testowej po adresie
# pracownika wracają bez niej, cztery osoby testowe usuwane ścieżką przycisku
# „Usuń”. Logika w `scripts/repairs/prod_test_records_cleanup.py`, przypięta do
# id i odcisków; paragon w `app_settings` + advisory lock; porażka nie
# zapisuje niczego. Log: wyłącznie liczby.
