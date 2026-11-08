"""Jednorazowa naprawa `repair-job-creator-delivery-lead`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `job_creator_delivery_lead_2026_10` (2026-10-08).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_job_creator_delivery_lead`.
"""
# Delivery Lead rekrutacji (08.10.2026) — jednorazowo: otwarte rekrutacje
# założone przez Delivery Leada, którym automat wpisał głównego DL-a klienta,
# wracają do twórcy (od tej daty `create_job_core` robi to sam). Warunek SQL,
# nie lista ID; logika w `scripts/repairs/job_creator_delivery_lead_repair.py`,
# marker w `app_settings` + advisory lock. Log: same liczby i ID.
