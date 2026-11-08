"""Jednorazowa naprawa `cleanup-settings-test-data`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `settings_test_data_cleanup_2026_10_20` (2026-10-20).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_cleanup_settings_test_data`.
"""
# Ślady testów w Ustawieniach (inwentarz docs/settings-test-data-inventory.md,
# zgoda Artura 20.10.2026) — jednorazowo: klient QA-E2E znika z list Ustawień
# (reguła CV, karta klienta, przypisanie DL, portfele; klient i rekrutacje
# zostają), szablon procesu i wzór umowy ze smoke testów są usuwane, konto
# serwisowe `claude-traffit-ops` wyłączone z odwołaniem kluczy. Logika
# w `scripts/repairs/settings_test_data_cleanup.py`, przypięta do id i odcisków;
# paragon w `app_settings` + advisory lock. Log: wyłącznie liczby.
