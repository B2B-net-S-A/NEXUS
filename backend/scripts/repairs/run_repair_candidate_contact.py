"""Jednorazowa naprawa `repair-candidate-contact`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0320_contract_candidate_contact` (2026-09-17).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_candidate_contact`.
"""
# Kontakt do konsultanta na umowie (09.2026, ticket „E-mail i telefon kandydata
# w widoku kontraktu") — jednorazowo: e-mail i telefon wpisane w „Danych
# Partnera" generatora B2B trafiają z `render_payload` na powiązany kontrakt.
# Wyłącznie poziom pierwszy kolejności źródeł: profilu kandydata NIE
# materializujemy, bo fallback do niego liczy się przy odczycie i ma zostać
# żywy. Dopasowanie tylko po `b2b_generated_contracts.contract_id` — szukanie
# po kandydacie/rekrutacji byłoby zgadywaniem. Fill-only: ręczna poprawka
# w kontrakcie wygrywa. Logika w
# `app/services/contract_candidate_contact_backfill.py`; marker w `app_settings`
# + advisory lock; wartości (PII) pod osobnym kluczem szczegółów.
# Log: wyłącznie liczby i kody powodów.
