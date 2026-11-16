# „Dodali do rekrutacji” na pulpicie i w Insights → Raporty (16.11.2026)
<!-- indeks: jedna liczba w backendzie (services/added_to_jobs.py) dla pulpitu i raportu; para kandydat × rekrutacja, pierwszy wpis etapu; automat „Nowi” osobno; dziś i 7 dni w kalendarzu firmy; bez punktów ligi -->

Decyzja Artura z 16.11.2026 po „Kto ilu dodał” na Tablicy
(`rekrutacja-tablica/kto-ilu-dodal-w-zespole-rekrutacji.md`): ta sama liczba
na pulpicie HoR/DL i w Insights → Raporty → „Aktywność zespołu”.

## Reguła liczenia (jedno miejsce: `backend/app/services/added_to_jobs.py`)

- **Dodanie** = para (kandydat, rekrutacja), liczona raz, w dniu pierwszego
  wpisu etapu pary (najwcześniejszy `candidate_stages.moved_at`, przy remisie
  najmniejsze `id` — jak `earliest` w kanbanie).
- **Osoba** = `moved_by` tego wpisu. Bez niego, gdy para nie jest z silnika
  „Nowi”: `recruitment_processes.opened_by_user_id` najnowszego procesu pary.
  To jedyna różnica wobec Tablicy, która takie pary pokazuje jako „Bez danych”.
- **Automat „Nowi”** (`entry_source = 'system'`, najnowszy proces pary) i wpisy
  bez osoby nie liczą się nikomu — idą osobnymi liczbami pod tabelą, żeby
  nic nie znikało bez śladu.
- **Okna** to dni kalendarza firmy (`local_day_start_utc`): „dziś” od północy
  w Warszawie, „7 dni” = dziś i sześć dni wstecz. W raporcie Insights okno
  z paska okresu, półotwarte `[start, end)`.
- **Bez punktów w lidze** (Artur: nie). Nie dopisuj dodań do `total_actions`,
  celów ani wyścigów.

## Gdzie to widać

- **Pulpit** (kafelek „Aktywność rekrutacyjna”, widok „Cały zespół”,
  `TeamDayTable`): kolumny „Dodali dziś” i „Dodali 7 dni” z
  `GET /api/insights/team/added-to-jobs` (bramka `VIEW_TEAM_KPI`: HoR, DL, TCM,
  Finanse, admin; rekruter 403). Dwie kolumny, nie „x / y” w jednej komórce —
  z tego samego powodu, dla którego 29.10.2026 zniknęło „dzień / miesiąc”.
  Okna są stałe, niezależne od paska okresu. Filtr roli i klienta z paska
  działa też na tę liczbę. Osoba, która tylko dodawała, dostaje wiersz z
  zerami w kolumnach okresu.
- **Insights → Raporty → „Aktywność zespołu”** (`InsightsTeamActivity`):
  kolumna „Dodani do rekrutacji” obok „Kandydatów”. „Kandydaci” to nowo
  utworzone profile (`user_activities.candidate_added`), a nie dodania do
  rekrutacji — obie kolumny zostają, różnicę mówi tytuł nagłówka i notka
  pod tabelą. Raport jest imienny dla każdego zalogowanego (D7), jak reszta
  kolumn tego rankingu.

## Czego nie robić

- Nie licz dodań drugi raz na froncie z innych danych ani osobnym SQL-em:
  nowa powierzchnia woła `count_added_to_jobs` / `added_today_and_last_days`.
- Nie mieszaj z filtrem „Kto dodał” na Tablicy (osoba karty) ani z „Kandydatami”.
