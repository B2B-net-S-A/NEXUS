"""Jednorazowa naprawa `repair-alior-reversed-order`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0397_alior_reversed_period_order` (2026-09-28).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_alior_reversed_order`.
"""
# Zamówienie z odwróconym okresem (Alior, zgłoszenie 28.09.2026) — jednorazowo:
# drugie zamówienie tej samej osoby o tym samym numerze, 01.01.2027 → 31.12.2026,
# założone oknem przedłużenia. Ta sama droga co usunięcie z zakładki
# „Zamówienia”; logika w `scripts/repairs/alior_reversed_order_repair.py`,
# przypięta do ID, numeru i dat. Plik PDF kasowany po commicie. Log: ID.
