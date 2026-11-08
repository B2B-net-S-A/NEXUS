"""Jednorazowa naprawa `repair-ezdrowie-merge`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `ezdrowie_client_merge_2026_09` (2026-09-26), `ezdrowie_client_merge_2026_09_processes` (2026-09-26).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_ezdrowie_merge`.
"""
# Dokończenie scalenia E-Zdrowie 37721 → eZdrowie 115 (25.09.2026) —
# jednorazowo: rekrutacje i kontrakty (z zamówieniami i umowami B2B), które
# nocny import przypinał do ukrytego duplikatu. Import już podąża za
# `merged_into_client_id`. Logika w `scripts/repairs/ezdrowie_client_merge_repair.py`,
# przypięta do id; marker + advisory lock; porażka nie zapisuje niczego.
