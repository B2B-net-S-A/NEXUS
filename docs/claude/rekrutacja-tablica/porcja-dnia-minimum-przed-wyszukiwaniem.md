# Porcja dnia od Nexusa: 20 osób na rekrutację, minimum 50 decyzji przed ręcznym wyszukiwaniem
<!-- indeks: `services/review_batch.py`, `/api/review-batch`, `REVIEW_BATCH_ENABLED`, 423 `REVIEW_MINIMUM_PENDING`, `entry_meta.review_owner_id`, `/porcja`, „Dla: …” na karcie, „Dodaj 20 kolejnych” -->

Decyzje Artura z 07.11.2026, raport i makiety M1–M11:
https://claude.ai/artifact/36VRtoCfN6WXhTsRjfKmNi. Od poprawek silnika z 03.11
system dodał karty do „Nowych” w 120 rekrutacjach, a w 101 z nich nikt nie
ruszył żadnej. Każda z 26 osób wysłanych do klienta, które system miał w puli,
a zespół dodał ręcznie, trafiła na pełną kolumnę zajętą przez takie karty.
Rekruterzy szukali ręcznie, a system nie dostawał ocen. Porcja dnia wymusza
decyzję o propozycjach, zanim ruszy ręczne wyszukiwanie.

## Reguły

- **Raz dziennie, w dni robocze od 7:00.** Silnik „Nowych”
  (`new_column_autofill.tick` → `_batch_tick`) robi jeden przebieg po
  rekrutacjach w pracy. Postęp siedzi w `app_settings['review_batch_day']`,
  więc restart w ciągu dnia nie dokłada drugiej porcji. Dopełniania co
  15 minut i po ruchu karty w tym trybie nie ma.
- **20 osób od 65% na rekrutację z rekruterem** (`review_batch.BATCH_SIZE`,
  `MIN_SCORE`, `fill_job(batch=True)`). Liczą się tylko czekające karty od
  systemu, a osoby dodane przez zespół nie. Uzupełnia się w miejsce osób,
  o których zdecydowano, więc w rekrutacji nie czeka więcej niż 20. Mniej
  w puli = mniejsza porcja. Rekrutacja bez rekrutera porcji nie dostaje.
  Pierwsza porcja to karty od systemu, które już leżą w „Nowych”.
- **Podział po równo** między rekruterów rekrutacji (`job_team`, bez propozycji
  automatu, tylko konta z rolą rekrutera): od najlepszej osoby do osoby z
  najmniejszą liczbą kart, remis rozstrzyga losowa, stała w ciągu dnia
  kolejność zespołu (`plan_owners`). Właściciel siedzi w
  `entry_meta.review_owner_id`. Osoba zdjęta z zespołu traci karty przy
  następnym przebiegu i od razu przestaje być nimi blokowana (`_own_cards`).
  Na karcie Tablicy: „Dla: …” (`cardOwner`, rola `review`).
- **Decyzja** = ruch karty od systemu z „Nowych” przez tę osobę dziś
  (`decided_today`): screening albo odrzucenie z powodem, z ekranu porcji albo
  z Tablicy. Pomijania nie ma.
- **Minimum** (domyślnie 50, `app_settings['review_batch']`, ustawia HoR i admin
  w „Ranking kandydatów → Wagi”). Kto ma w porcji mniej, przegląda całą porcję:
  `required = min(minimum, decyzje dziś + czekające)`.
- **Blokada 423 `REVIEW_MINIMUM_PENDING`** tylko dla konta z rolą rekrutera,
  przy włączonej porcji i niezrobionym minimum (`assert_search_allowed`). Trasy:
  `GET /api/candidates` z filtrami albo opisem w `q`, `POST /api/search/candidates`,
  `POST /api/search/semantic`, `POST /api/candidate-search/runs` z `radar`
  (Talent Radar) i `POST /api/talent-radar/search`. Przechodzi: samo nazwisko,
  mail albo telefon w `q` (`interpret_text`, ⌘K, wybór osoby, telefon od
  kandydata), lista bez filtrów, „Propozycje z bazy” (`candidate-search/runs`
  z `job_id`), „Podobne rekrutacje”, dodanie osoby spoza bazy i cała Tablica.
  Admin, HoR i DL bez blokady. Front: `ReviewBatchBlockedNotice`.
- **Kolejność przeglądu narzuca serwer** (`review_queue`): rekrutacje na zmianę
  (P0, potem priorytet), w każdej od najlepszej osoby. Inaczej 50 łatwych
  odrzuceń z jednej rekrutacji odblokowałoby wyszukiwanie.
- **Ekran `/porcja`** (`ReviewBatchScreen`, `ReviewBatchCard`): jedna osoba,
  wynik, „musi mieć” ✓/?, stawka wobec budżetu, „Aktywnie szuka”, uwagi.
  S = „Do screeningu”, O = „Odrzuć”, 1–8 = powód, R = „z profilu”/„po rozmowie”,
  Enter = odrzuć. Ruch przez `usePipelineMoveCore`, odrzucenie bez maila do
  kandydata, z powodem dla systemu (`autofill_*`) i powodem z szablonu.
  „Brak umiejętności” i „Inne” wymagają opisu (trafia do `notes` i
  `autofill_feedback.note`).
- **„Dodaj 20 kolejnych”** (`POST /api/review-batch/jobs/{id}/more`): tylko
  rekruter rekrutacji, gdy jego część porcji w niej jest przejrzana. Nowe osoby
  trafiają do klikającego.
- **Licznik w pasku** tylko przed minimum (przy 1280 px pasek jest ciasny).

## Wyjątek od „Kanban bez bramek”

To bramka wyszukiwania, nie ruchu karty: przepływ w pipeline zostaje bez
blokad. Decyzja Artura z 07.11.2026 świadomie dokłada ją obok wyjątków
z `kanban-bez-bramek.md`. Nie zdejmuj jej bez nowej decyzji.

## Wyłącznik i wdrożenie

`REVIEW_BATCH_ENABLED` (domyślnie `false`, workflow „Coolify set env”). Wymaga
też `NEW_COLUMN_AUTOFILL_ENABLED`. Wyłączenie przywraca silnik sprzed 07.11
(dopełnianie do 20 co 15 minut) i zdejmuje blokadę od razu. Właściciele
w `entry_meta` zostają i nic nie psują.

Testy: `backend/tests/test_review_batch.py`, `test_review_batch_unit.py`,
`frontend/src/components/v2/review-batch/__tests__/ReviewBatchCard.test.tsx`,
`frontend/src/lib/api/__tests__/reviewBatch.test.ts`.
