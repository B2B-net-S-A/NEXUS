"""Jednorazowa naprawa `repair-pfron-split`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0306_pfron_renewal_split_repair` (2026-09-11).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_pfron_split`.
"""
# PFRON 507–509 (0306, 09.2026) — jednorazowe rozdzielenie zamówień, które
# czyszczenie kolejki maila z 9/10.09 przepisało W MIEJSCU nowym okresem:
# nowy okres → nowy wiersz, oryginał wraca do stanu z Activity
# `order_mail_reactivate`. Safety-net dla migracji 0306 (alembic na prodzie
# bywa osierocony). Jedno źródło SQL-a w `app/services/pfron_renewal_split_repair.py`;
# marker + advisory lock → drugi start kończy się natychmiast, a zamówienie,
# którego tożsamość się nie zgadza, zostaje nietknięte z powodem w paragonie.
# Blok czeka na blokady najwyżej `lock_timeout` (15 s) i bierze blokadę wiersza
# klienta jak writer maila starego kontenera; po przekroczeniu pada w całości,
# bez zapisu i bez markera — następny start spróbuje ponownie.
# Log idzie do Grafany (Loki): wypisujemy WYŁĄCZNIE liczby i powody pominięcia,
# nigdy tytuły, stawki ani ścieżki — paragon zostaje w `app_settings`.
