"""Jednorazowa naprawa `repair-proposals-added-by-integration`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `proposal_added_from_integration_2026_10` (2026-10-06).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_proposals_added_by_integration`.
"""
# Propozycje z bazy (07.10.2026) — jednorazowo: `added` stawia już wyłącznie
# dodanie przez człowieka, więc propozycje oznaczone jako dodane przez kartę
# z integracji (każdy proces pary z `entry_source='auto_match'`) wracają do
# `proposed`. Warunek SQL, nie lista ID; logika w
# `scripts/repairs/proposal_added_repair.py`, marker w `app_settings` + advisory
# lock. Log: same liczby.
