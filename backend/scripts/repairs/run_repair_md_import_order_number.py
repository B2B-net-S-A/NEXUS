"""Jednorazowa naprawa `repair-md-import-order-number`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `md_import_order_number_repair_2026_09_23` (2026-09-23).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_md_import_order_number`.
"""
# Import MD za sierpień 2026 (ticket 23.09.2026) — jednorazowo: wiersz
# z numerem zamówienia nadpisał wartość innego wiersza tej samej osoby na
# zamówieniu-poprzedniku, a lipcowa nadwyżka przeszła na zamówienie, które
# w lipcu nie istniało. Przypięte do ID i stanu z 23.09 (inna wartość =
# pominięcie z kodem). Logika w `scripts/repairs/md_import_order_number_repair.py`;
# marker w `app_settings` + advisory lock. Log: wyłącznie liczby, ID i kody.
