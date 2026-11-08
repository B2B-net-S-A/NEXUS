"""Jednorazowa naprawa `repair-cardif-client-merge`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0435_cardif_client_merge` (2026-10-13), `0436_cardif_contract_fill` (2026-10-13).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_cardif_client_merge`.
"""
# Pełne scalenie „BNP Paribas Cardif” 52 → Cardif Assurances 38335 (13.10.2026) —
# jednorazowo: rekrutacje z procesami, kontakty, karta klienta i alerty DL
# przechodzą na klienta docelowego, podpisana umowa 1520/2026 dostaje właściwy
# kontrakt (#689), a rekord 52 zostaje oznaczony jako scalony. Logika
# w `scripts/repairs/cardif_client_merge_repair.py`, przypięta do id i nazwy;
# marker w `app_settings` + advisory lock; porażka nie zapisuje niczego.
# Log: wyłącznie liczby i kody.
