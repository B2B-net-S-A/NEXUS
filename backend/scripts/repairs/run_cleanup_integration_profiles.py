"""Jednorazowa naprawa `cleanup-integration-profiles`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `hr_integration_profile_cleanup_2026_10_20` (2026-10-20).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_cleanup_integration_profiles`.
"""
# Kartoteki kont integracji OAuth (decyzja Artura 20.10.2026) — jednorazowo:
# konto, w którego imieniu działają scrapery (`oauth_clients.acting_user_id`),
# dostało 19.10 kartotekę z „Kartoteka idzie za kontem” i stało w kolejce
# timesheetów. Usuwana jest tylko kartoteka założona z konta i bez danych
# kadrowych. Logika w `scripts/repairs/integration_profile_cleanup.py`;
# paragon w `app_settings` + advisory lock. Log: wyłącznie liczby.
