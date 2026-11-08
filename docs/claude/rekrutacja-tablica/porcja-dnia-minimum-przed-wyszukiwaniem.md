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
- **Decyzja** = wyjście karty od systemu z „Nowych” przez tę osobę
  (`decided_today`, sekcja „Etap 0”): odrzucenie z powodem od razu, screening po
  domknięciu, z ekranu porcji albo z Tablicy. Pomijania nie ma.
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
- **Minimum domyślnie 10**, dalej rośnie osobno dla każdego (sekcja „Narastanie
  minimum”).
- **Blokada tylko w dni robocze od 7:00** (`blocking_now`, `BLOCK_START_HOUR`).
  W weekend i przed 7:00 wyszukiwanie działa, a ekran mówi „do następnego dnia
  roboczego, 7:00”.
- **Wyłącznik i pilot bez wdrożenia** (`BatchSettings.block_enabled`,
  `pilot_user_ids`, „Ranking kandydatów → Wagi”): HoR wyłącza samą blokadę
  (porcja dalej się rozdziela) albo zawęża ją do zaznaczonych osób. Pusta lista
  = wszyscy rekruterzy. Env `REVIEW_BATCH_ENABLED` zostaje wyłącznikiem głównym.

## Narastanie minimum (decyzja Artura 08.11.2026)

Porcja rusza 09.11.2026 dla wszystkich rekruterów, bez pilota, z minimum 10.
Artur: „jak ktoś zrobi 10 to dajesz 10 więcej kolejnego dnia aż będzie 50 i
zostaniemy przy 50 do odwołania”.

- **Poziom jest osobny dla każdego** (`services/review_batch_levels.py`,
  `app_settings['review_batch_levels']`): kto w dniu roboczym podjął tyle decyzji,
  ile wynosi jego minimum (`next_level`), następnego dnia roboczego ma o 10 więcej,
  aż do 50. Kto nie zrobił albo był nieobecny, zostaje na swoim poziomie, a poziom
  nie spada. Liczy się `counted_at` decyzji z etapu 0, więc samo S bez domknięcia
  nie podnosi poziomu.
- **Przelicza pierwszy tick nowego dnia** (`roll_levels` w `_batch_tick`, ta sama
  transakcja co plan dnia, więc restart nie podnosi drugi raz). Pierwsze przeliczenie
  zakłada stan i nikogo nie podnosi: dni sprzed włączenia porcji się nie liczą.
- **Blokada zostaje po stronie dostępnych kart:** `required = min(poziom, decyzje +
  czekające + dzisiejsze otwarte S)`. Kto przy poziomie 50 ma w porcji 30 osób,
  przegląda 30 i wyszukiwanie wraca. Poziom ustawiony przez HoR w „Minimum” jest
  podłogą (`level_of`).
- **Gdzie widać:** „Zobacz zespół dziś” (kolumna „Poziom”), `/porcja` po minimum.
  Na 09.11 z pomiaru na kopii 08.11 minimum 10 padło w 10 z 244 osobodni, stąd
  warunek stopu z etapu 0 (spadek wysłanych CV) i wyłącznik blokady w ustawieniach.

Testy: `backend/tests/test_review_batch_levels.py`.

## Etap 0 przed pilotem (audyt 08.11.2026)

Raport: https://claude.ai/artifact/VXHZFJQZQbNRXAVGzNfdCu, plansza „Porcja dnia”.
Włączenie to decyzja Artura z 08.11 (sekcja „Narastanie minimum”).

- **Decyzja to wyjście z „Nowych”** (`_decisions`, poprzedni etap pary w
  `_NEW_STAGES`). Ruch screening → CV nie jest decyzją: na kopii 155 z 772 par
  liczonych wcześniej to były takie ruchy. Karta, która wróciła do „Nowych”, też
  nie jest decyzją.
- **„Do screeningu” liczy się po domknięciu** (`counted_at_for`): ruch dalej albo
  zapisany screening (`Activity screening_answered`; tabela `screening_notes`
  stoi pusta) w ciągu `SCREENING_CLOSE_DAYS` = 2 dni roboczych. Liczy się w dniu
  domknięcia, odrzucenie z powodem od razu. Bez tego przesunięcie całej porcji na
  screening odblokowywało wyszukiwanie po kilku minutach. Dzisiejsze niedomknięte S
  z własnej porcji (właściciel i `in_batch`, `Decision.own_batch`) zostają w
  `required`, inaczej porcja wyzerowana klawiszem S dawała `met`, i tej karty nie da
  się dziś usunąć z rekrutacji (409 `REVIEW_CARD_NEEDS_DECISION`). S na starszej albo
  cudzej karcie nie cofa zrobionego minimum.
- **Pusta kolejka przy `met=false`** (cała porcja na S): `/porcja` pokazuje
  `open_today_screenings` z linkami do Tablicy zamiast „Porcja przejrzana”. Wyjścia to
  zapis screeningu, odrzucenie i „Dodaj kolejnych”.
- **Kolejność jak na Tablicy** (`review_batch_order.order_cards`, lustro
  `orderNewColumn`): nowi w bazie od progu, bez uwag z miejscem co 5., z ostrzeżeniem,
  z brakiem krytycznej, po sumie wyniku, „znamy” i premii. Tego samego klucza używa
  `plan_owners`. Brak krytycznej porcja czyta z `entry_meta.missing_must`, bo
  `pipeline_base_fit` trwa kilka sekund.
- **Premia tylko w kolejności, przy włączonej porcji:** `availability=actively_looking`
  +5, znana stawka w PLN ≤ budżet +3 (`bonus_for`, `entry_autofill.queue_bonus`
  na Tablicy). Procent na karcie zostaje wynikiem.
- **Próg wyniku** `BatchSettings.min_score` (domyślnie 65, zakres 50–95) ustawia
  HoR obok minimum.
- **Widok zespołu** `GET /api/review-batch/team` (HoR+, „Zobacz zespół dziś”):
  decyzje dziś, wymagane, w porcji, godzina minimum, S:O, otwarte screeningi, blokady
  (`Activity review_batch.blocked`, raz na osobę na 10 minut, własna sesja, bo sesja
  żądania cofa się po 423).
- **Filtry własnej pracy przechodzą** (`is_broad_list_query` z `user`):
  `added_by_user_id`, `stage_moved_by`, `contacted_by` (tylko z `contacted=yes`,
  bo inaczej nie zawęża) równe zalogowanej osobie i `recruitment_id` z jej zespołów. Zawężenia (`pipeline_stage`, daty ruchu,
  `rejection_by`, które przyjmuje tylko `client/us/candidate`) działają wyłącznie
  razem z takim filtrem. Cudze id, rekrutacja spoza zespołu, `recruitment_match`
  inny niż `assigned`, dodana umiejętność albo opis w `q` = 423.
- **Nieobecni** (`absent_today`, urlop i L4 z `absences_on`, także pół dnia): nie
  dostają kart i nie mają blokady. Ich karty przechodzą przy następnym przebiegu na
  resztę zespołu.
- **Plan dnia** (`_day_plan`): P0, priorytet, nowsze. Dwie rundy: najpierw każda
  rekrutacja do `FIRST_ROUND_CARDS` = 5 osób, potem reszta. Bezpiecznik 100 dodań na
  tick zostaje (decyzja z 23.10), więc przy ok. 100 rekrutacjach pierwsza runda
  trwa kilka minut, nie jeden tick.
- **Pierwszy rekruter** (`no_team` w `app_settings['review_batch_day']`): rekrutacja
  bez zespołu czeka na liście, a tick, który zobaczy rekrutera, zdejmuje nietknięte
  stare karty (`plan_batch_reset`) i dokłada porcję tego samego dnia.
- **Pomiar blokady (P4):** `entry_meta.found_via` przy dodaniu ręcznym
  (`search`, `outside_base`, `proposals`) i `review_batch_streams`
  (`python -m scripts.review_batch_streams_report`, to samo w „Zobacz zespół dziś”):
  baza 62 od systemu i 187 ręcznych na 14 dni, kryterium zatrzymania to wszystkie
  wysłane CV niżej o ponad 10% przez 2 pełne tygodnie.
- **Obowiązkowa nowość** ma `requires_setting: REVIEW_BATCH_ENABLED`. Nowa nowość
  zależna od flagi: to samo pole w `novelties.json`.

Testy: `test_review_batch_stage0.py`, `test_review_batch_stage0_unit.py`.

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

Przy `NEW_COLUMN_TEMPO_TARGET_ENABLED` (08.11.2026) rozmiar porcji to cel z tempa
rekrutacji, a nie stałe 20: `cel-kart-wg-tempa-i-miejsce-dla-swiezych.md`.

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
