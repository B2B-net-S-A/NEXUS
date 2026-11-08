"""Jednorazowa naprawa `repair-candidate-name-markers-0481`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0481_candidate_name_markers_v2` (2026-10-20).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_candidate_name_markers_0481`.
"""
# Imię i nazwisko bez dopisków — druga runda (0481, 20.10.2026): klamry,
# nawias bez pary, „acive”, emoji, plus trzy ręczne poprawki rozjechanych pól
# zatwierdzone przez Artura. Safety-net migracji 0481 i jedyne miejsce, które
# zapisuje kolejkę indeksu zmienionych osób. Ten sam rdzeń co 0436; paragon
# w `app_settings` + advisory lock; porażka nie zapisuje niczego. Log: liczby.
