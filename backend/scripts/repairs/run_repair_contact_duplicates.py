"""Jednorazowa naprawa `repair-contact-duplicates`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `contact_duplicates_merge_2026_09_25` (2026-10-14).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_contact_duplicates`.
"""
# Zdublowane kontakty klienta z Traffita (25.09.2026) — jednorazowo: trzy pary
# tej samej osoby u tego samego klienta. Zostaje kontakt o niższym id, drugi
# rekord Traffita dostaje alias (`traffit_contact_aliases`), żeby nocny import
# go nie odtworzył. Logika w `app/services/contact_duplicate_merge.py`,
# przypięta do id. Marker + advisory lock; porażka nie zapisuje niczego.
