# Cel kart wg tempa rekrutacji i miejsce dla świeżych
<!-- indeks: `NEW_COLUMN_TEMPO_TARGET_ENABLED`, `tempo_of`, `Tempo`, 5/10/20, `_tempo_tick`, `new_column_tempo_day`, `FRESH_SWAPS_PER_DAY`, `plan_fresh_seats`, `autofill_withdrawn_fresh_seat`, `waiting_system_cards`, „Dodaj 10 kolejnych”, `GET /api/review-batch/jobs/{id}/tempo`, plakietka „cel N” -->

Decyzja Artura z 08.11.2026, raport i makiety:
https://claude.ai/artifact/HgCGsxN7Nk7ENGpb6iNg2B (etap 2). Kod siedzi za flagą
`NEW_COLUMN_TEMPO_TARGET_ENABLED` (domyślnie `false`, włącza Artur przez „Coolify set
env”). Stan `false` to silnik sprzed zmiany: 20 kart we wszystkich rekrutacjach, pełny
przebieg co 15 minut, nikt nie schodzi.

Dlaczego: 74 rekrutacje starsze niż 14 dni nie miały w 21 dni ani jednej decyzji, a 22
zrobiły 67% wszystkich. Z 2 993 kart nieruszonych 7 dni do klienta poszły 3 (0,1%).
Osoba do 14 dni w bazie to 6 wysyłek na 110 kart (5,5%), starsze 49 na 3 293 (1,5%).
Powyżej 70% wynik nie różnicuje (2,0% i 2,0%), dlatego zamiana nie porównuje wyników.

## Świadoma zmiana wcześniejszych decyzji

- **28.10.2026 i `nowi-w-bazie-najpierw.md` („Kart nie zdejmujemy”):** przy włączonej
  fladze karta od systemu schodzi z Tablicy, ale tylko nietknięta od 7 dni i tylko po to,
  żeby zrobić miejsce osobie nowej w bazie. Odrzucone wtedy wygaszanie po 5 dniach
  roboczych dalej nie istnieje: bez czekającej świeżej osoby nikt nie schodzi.
- **07.11.2026 („20 na rekrutację”, porcja dnia):** cel z tempa zastępuje stałe 20 także
  w `REVIEW_BATCH_ENABLED`.

## Cel

Stałe w `services/new_column_autofill.py`, reguła w `tempo_of`:

| Tempo (decyzje w 21 dni) | Cel kart od systemu | W dzień po ruchu karty |
|---|---|---|
| 0 | 5 | nie, przycisk |
| 1–9 | 10 | nie, przycisk |
| 10 i więcej | 20 | tak |
| rekrutacja do 14 dni | 20 | tak |
| P0 (`job_p0.is_active`) | 20 | tak |

- **Decyzja** to człowiek wyprowadzający osobę z „Nowych” (`moved_by` niepuste, poprzedni
  etap `new`/`posting`, jak `review_batch._NEW_STAGES`). Jedna osoba to jedna decyzja, także
  przy powrocie do „Nowych”. Liczą się wszystkie karty kolumny, nie tylko od systemu.
- **Wiek rekrutacji:** `opened_at`, a gdy pusta, `created_at`.
- **Liczą się czekające karty od systemu** (`waiting_system_cards`). Zgłoszenia, osoby od
  zespołu i karty, które ktoś wziął („Dzwonię”, aktywna blokada, `PendingCard.taken`),
  stoją poza celem. To lustro `waitsInSystemQueue` z frontu.
- **Cel to górna granica dokładania.** Kolumna ponad celem zostaje, nikt nie schodzi
  z tego powodu. Osoby nowe w bazie nie wchodzą ponad cel (`FRESH_OVER_TARGET` działa tylko
  przy wyłączonej fladze), bo od tego jest zamiana.

## Rytm

`tick` idzie do `_tempo_tick`, a przy włączonej porcji do `_batch_tick`.

- **Poranny przebieg raz dziennie** w dni robocze od 7:00, po wszystkich rekrutacjach w pracy
  (P0, priorytet, nowsze). Postęp w `app_settings['new_column_tempo_day']`: restart nie zaczyna
  dnia od nowa i wraca od miejsca, w którym bezpiecznik `NEW_COLUMN_AUTOFILL_MAX_PER_TICK` przerwał.
- **W dzień** tylko rekrutacje gorące, nowe i P0, w których człowiek ruszył kartę.
  Pełnego przebiegu co 15 minut nie ma.
- **Rekrutacja założona w ciągu dnia** dostaje karty po pierwszym przeglądzie
  (`_jobs_without_batch(need_team=False)`), po dziennym przebiegu.

## Miejsce dla świeżych

Tylko w porannym przebiegu (`fill_job(swap=True)`), także przy włączonej porcji (runda „reszta”).

- Najpierw zwykłe dopełnienie do celu. Zamiana dotyczy osób nowych w bazie, które zostały.
- **Świeża osoba:** te same warunki co `new_in_base_picks` (do 14 dni w bazie, od
  `proposal_threshold`, bez uwag) i bramka `_allowed`. W porcji także od jej progu.
- **Karta, która ustępuje** (`autofill_withdraw.plan_fresh_seats`): od systemu, otwarta co
  najmniej `FRESH_SEAT_AGE_DAYS` = 7 dni temu i nietknięta wg `_untouched_pairs` (bez „Dzwonię”,
  blokady, decyzji, ruchu, oceny, screeningu, notatki). Warunek sprawdzany drugi raz pod
  blokadą kandydata. Od najniższego wyniku.
- **Limit:** `FRESH_SWAPS_PER_DAY` = 5 na rekrutację i dzień, liczony z archiwum, więc
  przerwany przebieg nie zamienia drugi raz. Zamiany liczą się do bezpiecznika dodań.
- **Zdejmuje `autofill_withdraw.apply`** z powodem `autofill_withdrawn_fresh_seat`, bez wpisu
  w `autofill_feedback`, bo to nie decyzja człowieka.
- **Osoba może wrócić.** To jedyny powód w archiwum, który `ranked_picks` i pula nocnego
  przeglądu (`auto_full_review._in_job_ids`) pomijają. Inny wpis tej pary w archiwum dalej
  wyklucza osobę. Propozycji nie zamykamy.
- **„Praca w tle”:** `autofill_withdrawn` z `why: "fresh_seat"` i `count` („Rano 5 zamian…”).

## „Dodaj 10 kolejnych” i plakietka

- **`POST /api/review-batch/jobs/{id}/more`** przy włączonej fladze: każda osoba z prawem
  edycji rekrutacji (`ensure_job_editor`), rekrutacja w pracy (inaczej 409), także bez porcji
  i ponad cel. W porcji rekruter z zespołu najpierw przegląda swoje karty (409, jak dotąd),
  a nowe trafiają do niego; osoba spoza zespołu dostaje podział po równo. `MORE_CARDS` = 10.
  Przy wyłączonej fladze trasa działa jak w `porcja-dnia-minimum-przed-wyszukiwaniem.md`.
- **`GET /api/review-batch/jobs/{id}/tempo`** daje cel i `can_add_more`. Przy wyłączonej fladze
  `{enabled: false}`, a nagłówek kolumny nie dostaje drugiego rzędu (`NewColumnTempo`).
- Plakietka „cel N” i przycisk stoją w nagłówku kolumny „Nowi”. W dymku: skąd ten cel.

## Czego to nie obejmuje

Karty ponad celem w cichych rekrutacjach nie są zdejmowane jednorazowo: schodzą decyzjami
ludzi i zamianami. Jeśli po włączeniu będzie to za mało, sprzątanie to osobna decyzja
(wzór: `scripts/autofill_withdraw_batch_reset.py`).

Testy: `backend/tests/test_new_column_tempo.py`,
`frontend/src/components/v2/recruitment/__tests__/NewColumnTempo.test.tsx`.
