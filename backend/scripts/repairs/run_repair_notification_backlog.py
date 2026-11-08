"""Jednorazowa naprawa `repair-notification-backlog`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `notification_backlog_read_2026_10` (2026-10-04).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_notification_backlog`.
"""
# Powiadomienia (04.10.2026) — jednorazowo: nieprzeczytane wpisy „etap stoi
# 6 h”, „etap stoi 7 dni”, „coach KPI” i PowerCalling starsze niż 14 dni
# oznaczone jako przeczytane (decyzja Artura; nic nie jest kasowane). Logika
# w `scripts/repairs/notification_backlog_repair.py`; marker w `app_settings`
# + advisory lock. Log: same liczby.
