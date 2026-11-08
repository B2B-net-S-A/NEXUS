"""Jednorazowa naprawa `repair-closed-job-proposals`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `job_proposals_closed_jobs_expired_2026_10` (2026-10-07).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_closed_job_proposals`.
"""
# Propozycje (06.10.2026, audyt R6) — jednorazowo: otwarte propozycje
# rekrutacji zamkniętych przed 0422 wygasają (`proposed` → `expired`; nic nie
# jest kasowane). Od 0422 robi to zamknięcie rekrutacji. Logika
# w `scripts/repairs/job_proposal_closed_expiry.py`; marker w `app_settings`
# + advisory lock. Log: same liczby.
