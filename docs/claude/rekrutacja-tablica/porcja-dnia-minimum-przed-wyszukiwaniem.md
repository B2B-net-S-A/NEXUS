# Porcja dnia od Nexusa: 20 osób na rekrutację, minimum 10 decyzji przed ręcznym wyszukiwaniem
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
- **Minimum** (domyślnie 10 od 08.11.2026, wcześniej 50; `app_settings['review_batch']`,
  ustawia HoR i admin w „Ranking kandydatów → Wagi”). Kto ma w porcji mniej, przegląda całą porcję:
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

## Bezpieczne włączenie (decyzja Artura 08.11.2026)

Audyt na kopii produkcji z 06.11 przed planowanym włączeniem w pon. 09.11:
rekruterzy podejmowali 4,7–7,8 decyzji dziennie o kartach od systemu (najwięcej
29, nikt nie doszedł do 50), więc minimum 50 blokowało 12 z 16 osób na cały
dzień. Pierwsza porcja miałaby 1 440 kart, z czego ok. 850 starszych niż 7 dni
i 147 poniżej 65%. Artur wstrzymał obie flagi do tych zmian:

- **W porcji tylko karty od 65% i nie starsze niż 7 dni** (`in_batch`,
  `MAX_AGE_DAYS`). Starsze i słabsze karty zostają na Tablicy, ale nie mają
  właściciela, nie blokują, nie liczą się do 20 i można je zdjąć z rekrutacji.
- **Jednorazowe wycofanie przed włączeniem flagi:**
  `python -m scripts.autofill_withdraw_batch_reset` (podgląd), potem `--apply`.
  Tylko nietknięte karty od systemu (ta sama droga i reguły co
  `autofill_withdraw`), powód `autofill_withdrawn_batch_reset`.
- **Minimum domyślnie 10.** Kolejne progi (20, 30) HoR ustawia po pomiarze:
  krok w górę, gdy co najmniej 80% rekruterów robi minimum przed 11:00,
  a wysłane CV z ręcznych dodań nie spadają o więcej niż 15%.
- **Blokada tylko w dni robocze od 7:00** (`blocking_now`, `BLOCK_START_HOUR`).
  W weekend i przed 7:00 wyszukiwanie działa, a ekran mówi „do następnego dnia
  roboczego, 7:00”.
- **Wyłącznik i pilot bez wdrożenia** (`BatchSettings.block_enabled`,
  `pilot_user_ids`, „Ranking kandydatów → Wagi”): HoR wyłącza samą blokadę
  (porcja dalej się rozdziela) albo zawęża ją do zaznaczonych osób. Pusta lista
  = wszyscy rekruterzy. Env `REVIEW_BATCH_ENABLED` zostaje wyłącznikiem głównym.

## Szczelność blokady (przegląd kodu 07.11.2026)

- **Wyszukanie osoby w trakcie pisania przechodzi** (`is_person_lookup`): 1–3 słowa
  jak imię i nazwisko (także pojedyncze słowo spoza słownika umiejętności i miast,
  np. „Kowal”), początek maila („jan.kow”, „jan@”), cyfry telefonu. ⌘K, okno
  „+ Dodaj” (`POST /api/search/candidates`, `is_broad_body_query`) i wybieraki
  osób działają przy blokadzie. Słowo ze słownika („java”) i opis — 423.
- **Karty z porcji nie da się usunąć z rekrutacji zamiast decyzji**
  (`assert_removal_allowed`, 409 `REVIEW_CARD_NEEDS_DECISION` w
  `DELETE /api/candidates/{id}/recruitments/{job_id}`). Usunięcie zmniejszało
  wymagane minimum bez żadnej decyzji.
- **Karta liczy się tylko jako najnowsze podejście pary**: osoba dodana potem
  ręcznie (nowy proces) nie jest już porcją dawnego właściciela.
- **Karty z rekrutacji zamkniętej albo wstrzymanej nie blokują** (`_own_cards`).
- **Pełne przeszukanie bazy pod rekrutację** (`candidate-search/runs` z `job_id`,
  zakładka „Propozycje z bazy”) zostaje otwarte: to praca z propozycjami systemu.

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

## Pula spoza rekrutacji i pierwszy przegląd w dzień (R2, R6)

- **Pula dopełniania = 150 osób SPOZA rekrutacji** (`auto_full_review.refresh_autofill_pool`,
  `_in_job_ids`: wiersze `candidate_stages` i `candidate_stage_removals` tej
  rekrutacji). Do 07.11 pula liczyła też osoby już w rekrutacji: w AML (789163)
  118 ze 150, a 80 ze 185 rekrutacji miało mniej niż 20 wolnych osób od 70%.
- **Pustosząca pula idzie na początek nocnej kolejki** (`_pool_running_low`,
  `POOL_LOW_FREE` = 40 wolnych osób), tak jak zdarzenie albo zmieniony odcisk.
  Rekrutacja bez puli nie liczy się jako pustosząca — o niej decyduje wiek.
- **Pierwszy pełny przegląd tego samego dnia** (`_daytime_first_review`): dni
  robocze 7–19, rekrutacje w pracy bez żadnego przeglądu automatycznego
  (`first_review_job_ids`), pojedynczo (ustępuje każdemu aktywnemu przeglądowi),
  najwyżej `AUTO_FULL_REVIEW_DAYTIME_MAX` (3 od 08.11.2026, wcześniej 10) dziennie
  poza nocnym oknem. **Automat ustępuje ręcznemu przeglądowi po każdej paczce**
  (`candidate_search_worker._execute_claimed`, `store.yield_run`): bez tego
  rekruter czekał na koniec trwającego automatu (p50 286 s, p90 534 s).
  Ustąpienie nie zużywa próby z `MAX_CLAIMS`.
  Wyłącznik `AUTO_FULL_REVIEW_DAYTIME_FIRST_ENABLED`, domyślnie wyłączony (przegląd
  idzie w procesie web, który w dzień ma już wolne trasy) — włącza się razem z porcją. Szybkie dopasowanie przy
  zapisie (`new_cv`, 11–19 osób) zostaje.
- **Porcja dla nowej rekrutacji jeszcze tego dnia** (`_jobs_without_batch`):
  po dziennym przebiegu silnik co tick dokłada porcję rekrutacjom z ostatnich
  2 dni, które mają pulę i rekrutera, a nie mają żadnej karty od systemu.

Testy: `backend/tests/test_auto_full_review.py` (sekcja z 07.11.2026),
`test_review_batch.py::test_new_job_gets_its_batch_the_same_day`.
