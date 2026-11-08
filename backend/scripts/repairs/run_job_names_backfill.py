"""Jednorazowa naprawa `job-names-backfill`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `job_names_backfill_0380` (2026-09-25).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_job_names_backfill`.
"""
# Trzy nazwy rekrutacji (0380, 25.09.2026) — jednorazowo: tytuł dla rekrutera
# (składany z Championa, a bez niego z tytułu i must-have) i numer u klienta
# (tylko jednoznaczny ZOB z tytułu albo numeru) dla istniejących rekrutacji.
# Reguła jest w Pythonie: `app/services/job_working_title.py`. Rusza wyłącznie
# puste pola; marker w `app_settings` + advisory lock → drugi start kończy się
# od razu. Log: same liczby.
