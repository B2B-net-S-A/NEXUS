# Scalenie profili: etap karty, gdy oba są w tej samej rekrutacji

Decyzja Artura z 05.11.2026. `candidate_stages` to historia dopisywana, nie tabela
kart: dwóch kart tej samej osoby na Tablicy nie ma, a etap wyznacza najnowszy wiersz
pary `(moved_at, id)`. Po przepięciu historie obu profili się przeplatają, więc
scalenie cofało kartę, gdy duplikat dostał świeży wiersz na wcześniejszym etapie.
Tablica, historia i `/api/pipeline/move` czytały ten sam wynik, więc nikt nie widział
rozjazdu. 05.11 trzy karty cofnęły się tak na produkcji, a wiersze z importu lub
automatu potrafiły też cofnąć odrzucenie przez człowieka na „Nowi”.

## Reguła (`card_after_merge` w `services/candidate_merge.py`)

Porównujemy najnowszy wiersz każdego profilu w danej rekrutacji:

1. „Zatrudniony” wygrywa zawsze.
2. Dwa żywe etapy: zostaje dalszy w procesie.
3. Etap końcowy (odrzucony, wycofany) a żywy: końcowy przegrywa tylko z nowszym
   wierszem dalej niż „Nowi”, bo wiersz wejścia bywa automatyczny.
4. Dwa etapy końcowe i ten sam etap: nowszy wiersz.

Gdy etap, który zostaje, nie leży w najnowszym wierszu, scalenie dopisuje jego kopię
mikrosekundę po najnowszym. Nie „teraz”, bo terminy od etapu i liczniki dnia uznałyby
scalenie za nowy ruch. Kopia niesie autora, powód odrzucenia i notatkę źródła.

## Co się z tym wiąże

- **Podgląd:** `merge-preview` zwraca `cards`, a okno pokazuje etap każdej wspólnej
  rekrutacji. Odcisk obejmuje najnowsze wiersze, więc ruch karty po podglądzie daje 409.
- **Proces idzie za kartą:** przy konflikcie `recruitment_processes` zostaje wiersz
  profilu, którego etap zostaje, razem z opiekunem i kredytem. Poza takimi rekrutacjami
  nadal rozstrzyga nowszy wiersz.
- **Ślad:** `activities.details.cards_restored` przy `candidates_merged`.
- **Powiadomień nie ma:** to nie jest ruch karty, nie przechodzi przez `run_move_effects`.
