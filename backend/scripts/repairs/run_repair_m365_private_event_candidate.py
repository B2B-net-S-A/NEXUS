"""Jednorazowa naprawa `repair-m365-private-event-candidate`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `m365_private_event_candidate_unlink_2026_09_26` (2026-09-27).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_m365_private_event_candidate`.
"""
# Prywatne spotkania z Outlooka oczyszczone przed rundą 7 (R8-V3-3) —
# jednorazowo: zdjęcie `candidate_id`, który pochodził z uczestników. Profil
# kandydata pokazywał „Spotkanie prywatne”, czyli z kim było. Logika
# w `scripts/repairs/m365_private_event_link_repair.py`; marker w `app_settings`
# + advisory lock; porażka nie zapisuje niczego. Log: wyłącznie liczby.
