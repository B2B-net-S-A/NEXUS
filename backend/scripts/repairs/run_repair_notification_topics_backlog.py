"""Jednorazowa naprawa `repair-notification-topics-backlog`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `notification_topics_backlog_read_2026_10` (2026-10-16).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_notification_topics_backlog`.
"""
# Pasek bez dzwonka (16.10.2026, decyzja D5) — jednorazowo: nieprzeczytane
# powiadomienia KAŻDEGO typu starsze niż 7 dni oznaczone jako przeczytane.
# Okienko „Rekrutacje” pokazuje tylko tydzień, „CV” liczy się ze stanu; stary
# zapas wisiałby w liczniku na zawsze. Nic nie jest kasowane. Logika
# w `scripts/repairs/notification_backlog_repair.py` (`run_topics_backlog_repair`);
# marker w `app_settings` + advisory lock. Log: same liczby per typ.
