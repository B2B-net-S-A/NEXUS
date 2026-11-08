"""Jednorazowa naprawa `repair-pfron-resync`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0306_pfron_revenue_resync` (2026-09-11).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_pfron_resync`.
"""
# PFRON 507–509 (0306) — krok przychodu kontraktu zaraz po rozdzieleniu: surowy
# SQL wyżej nie wyzwala synchronizacji kontrakt ↔ zamówienia, więc przywrócony
# okres nie ma kroku przychodu, a czerwiec–sierpień czytałby stawkę nowego
# okresu do najbliższego zapisu zamówienia. `scripts/repairs/pfron_revenue_resync.py`
# woła tę samą synchronizację co zwykły zapis zamówienia (tylko przy włączonej
# 0304); własny marker + advisory lock, jednorazowy. Log: tylko liczby.
