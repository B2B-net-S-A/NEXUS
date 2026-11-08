"""Jednorazowa naprawa `repair-candidate-name-markers`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0436_candidate_name_markers` (2026-10-13).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_candidate_name_markers`.
"""
# Imię i nazwisko bez dopisków z Traffita (0436, 13.10.2026) — jednorazowo:
# „[ACTIVE]”, „(zaakceptowany)”, „(czarna lista)” znikają z imion; najpierw
# pole (czarna lista → status, „active” → dostępność), potem tekst, dopiski
# do `cv_extracted_data.traffit_name_marker`. Safety-net migracji 0436 (prod
# alembic bywa osierocony) i jedyne miejsce, które zapisuje kolejkę indeksu
# zmienionych osób — także po korekcie wykonanej przez migrację. Logika
# w `app/services/candidate_name_marker_repair.py`; paragon w `app_settings`
# + advisory lock; porażka nie zapisuje niczego. Log: wyłącznie liczby.
