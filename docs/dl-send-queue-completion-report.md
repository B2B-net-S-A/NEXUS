# „Do wysłania do klienta” — kolejka Delivery Leada widoczna wszędzie — raport

Gałąź `claude/deliver-lead-visibility-36efa8`, 13.10.2026. Reguły: `docs/claude/rekrutacja-tablica/do-wyslania-do-klienta-kolejka-delivery-leada.md`.
Makiety (stan sprzed zmiany i propozycja): https://claude.ai/artifact/BxX2afNFMkzxJK2pvWHJte.

## Skąd ta zmiana

Pytanie Artura z 13.10.2026: skąd Delivery Lead wie, że ma kogoś wysłać do klienta. Przegląd kodu i pomiar
na produkcji (tylko odczyt, same liczby) z tego dnia:

| Co | Liczba |
|---|---|
| Pary w „QC CV” poza Nordeą (ruch zrobiony w NEXUSIE) | 15, u 4 Delivery Leadów |
| — gotowe do wysłania (QC zdane albo przepuszczone) | 7 |
| — jeszcze u rekrutera (QC do poprawy) | 8 |
| Karty z importu Traffita w tej kolumnie | 3 |
| Starsze niż 30 dni | 0 |
| Dzwonki „CV do przeglądu” w 30 dni | 34, przeczytane 2 |
| Stare przypomnienie „Kandydat czeka na decyzję DL” w 30 dni | 4 695 wpisów do 8 osób |
| Zapytanie kolejki dla całej firmy (`EXPLAIN ANALYZE`) | 4,6 ms |

Ponad połowa kolejki Delivery Leada to były osoby, przy których ruch ma rekruter, a jedyne przypomnienie
dotyczyło osób już wysłanych.

## Co się zmieniło

### Jedna reguła na serwerze

- `services/dl_send_queue.py` — wiersze kolejki bez okna czasu (do tej pory 30 dni), `ready` = QC zdane albo
  przepuszczone, `ready_since` = wejście do „QC CV” albo zaliczenie QC (co później), pilność w dniach
  roboczych (1 = bursztyn, 2 = czerwień, 3 = sygnał), `imported` dla etapu z importu Traffita.
- `cv_qc.pair_statuses` zwraca `ok_at`; `board_tasks.reviews_as_dl` to publiczna reguła „czyj przegląd”
  z lustrem w SQL.
- `GET /api/board-tasks/dl-send` — lekka trasa dla górnego paska i menu.

### Pulpit

- Pas „Do wysłania do klienta” nad „Czeka na Ciebie”, tylko u Delivery Leada: gotowi w tabeli (rekrutacja
  z terminem, kto przekazał, stawka kandydata wobec budżetu, QC i screening, czas w kolorze pilności);
  „Jeszcze u rekrutera” i „Z Traffita” zwinięte do jednej linii; pusta kolejka = jedno zdanie.
- Sekcja „Czeka na Twój przegląd (DL)” wyszła z panelu.
- „Przejrzyj po kolei (N)”: przegląd osoba po osobie z licznikiem, „Pomiń” i „Zakończ kolejkę”. Pominięte
  osoby nie są ogłaszane jako załatwione.

### Górny pasek i menu

- Pigułka „Do wysłania · N” z okienkiem i ten sam licznik przy „Rekrutacjach”. Liczy stan kolejki, nie
  zdarzenia; przy zerze i bez roli Delivery Leada jej nie ma.

### Tablica

- Karta gotowa do wysyłki: u Delivery Leada tej rekrutacji „Twój ruch” i „Czeka na Ciebie · N dni”; każdy,
  kto może wysyłać, ma przycisk „Przejrzyj i wyślij” zamiast strzałki.
- „Przejrzyj po kolei (N)” w drugiej linii nagłówka „QC CV”. Nad tablicą nic nie doszło.

### Lista rekrutacji

- Bez nowej kolumny: komórka „QC” w „Etapach” świeci, gdy ktoś czeka na wysyłkę patrzącego; filtr „Do
  wysłania do klienta” w „Więcej filtrów” (`dl_send=mine|stale`, w adresie `tosend=`).

### Przypomnienia

- Poranny dzwonek wymienia dwie najdłużej czekające osoby i liczy tylko gotowe; poranny mail ma sekcję „Do
  wysłania do klienta” z „czeka N dni”.
- „Twoje CV w drodze”: wiersz „W przeglądzie” mówi, czyj jest ruch, a od 2 dni roboczych rekruter ma
  „Przypomnij” (`POST /api/board-tasks/dl-send/{stage_id}/nudge`, raz dziennie, ślad w `Activity`).
- Head of Recruitment: sygnał „CV czeka na wysyłkę do klienta 3+ dni robocze” w „Gdzie stoi”.
- Trigger `check_dl_stage_stale_6h` usunięty (typ powiadomienia zostaje dla historii).

Bez migracji i bez zmian w `entrypoint.sh`.

## Różnice względem makiet

- Nad Tablicą nie ma paska „N osób czeka na Twoją wysyłkę” — łamałby decyzję z 02.10.2026 („bez pasków
  i liczników nad tablicą”) i test 1280 × 720. Zastępuje go przycisk w nagłówku kolumny.
- Lista rekrutacji nie dostała kolumny „do wysłania” (tabela ledwo mieści się przy 1280 px) ani czwartego
  przełącznika w pasku filtrów.
- „Czeka” liczy się od gotowości CV, nie od wejścia do kolumny.

## Weryfikacja

- Backend lokalnie (bez bazy): `ruff check app/`, `ruff format --check app/`, import aplikacji, 669 testów
  strażników i modułów zmiany; testy z bazą — pełny bieg CI na gałęzi.
- Frontend lokalnie: `npm run type-check` (czysto), 1002 testy pulpitu, powłoki i strażników źródeł, osobno
  Tablica (169) i lista rekrutacji (730).
- Ekrany w 1280 × 720 (Playwright na `next dev`): `/preview/dl-send` (kolejka, pusta, po kolei, górny
  pasek), `/preview/custom-dashboard?as=dl`, `/preview/pipeline-v4?as=dl`, `/preview/jobs-list-v3` — bez
  poziomego przewijania; przegląd po kolei przeklikany („1 z 4” → „Pomiń” → „2 z 4” → „Zakończ kolejkę”).

## Świadomie poza zakresem

- Dzwonek i mail przy przekazaniu karty wychodzą dalej przy wejściu do „QC CV”, przed wynikiem QC. Osobny
  dzwonek „gotowe” wymaga decyzji.
- `needs_action_count` nadal liczy każdą kartę w „QC CV” jako ruch rekrutera (steruje tylko sortowaniem
  „Wymaga uwagi”).
- „Twoje CV w drodze” zachowuje okno 30 dni — karta stojąca dłużej nie ma tam „Przypomnij”.

## Znalezione po drodze

- Nagłówek kolumny „QC CV” przy 1280 px traci nazwę kolumny, gdy widać „Porównaj (N)” (istniało przed tą
  zmianą).
- `board_flow._dl_job_ids` traktuje nieaktywnego Delivery Leada inaczej niż kolejka przeglądu.
- Lista rekrutacji czyta filtry z adresu tylko przy wejściu — link z filtrem kliknięty na otwartej liście
  zmienia sam adres (okienko w pasku obchodzi to zwykłym przejściem).
