"""Jednorazowa naprawa `repair-m365-email-duplicates`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0342_m365_email_dedupe` (2026-09-22).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_m365_email_duplicates`.
"""
# Zdublowane maile M365 (INT-14, audyt 22.09.2026) — jednorazowo: ta sama
# skrzynka + ten sam internetMessageId = jeden wiersz (zostaje ten z kluczem
# wysyłki, inaczej najstarszy; przejmuje aktualne ID Graph, kandydata,
# brakujące załączniki i powiązania maili odrzucenia). Logika
# w `scripts/repairs/m365_email_dedupe_repair.py`; marker w `app_settings`
# + advisory lock. Porażka nie zapisuje niczego — następny start ponawia.
# Log: wyłącznie liczby.
