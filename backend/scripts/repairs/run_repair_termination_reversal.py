"""Jednorazowa naprawa `repair-termination-reversal`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0368_termination_reversal_ticket_2026_09_23` (2026-09-24).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_termination_reversal`.
"""
# „Cofnij zakończenie" ze zgłoszenia 23.09.2026 — jednorazowo: kontrakt
# zakończony przez pomyłkę i przywrócony samą zmianą statusu (zamówienie
# zostało w „Zakończonych"). Ta sama operacja co przycisk; logika
# w `scripts/repairs/contract_termination_reversal_repair.py`, przypięta do
# trójki ID. Marker w `app_settings` + advisory lock; porażka nie zapisuje
# niczego — następny start ponawia. Log: wyłącznie liczby i ID.
