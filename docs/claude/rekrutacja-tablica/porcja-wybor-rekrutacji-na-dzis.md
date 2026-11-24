# Porcja dnia: rekruter wybiera rekrutację na dziś — najpierw z niej, z innych schodzi tylko nadwyżka
<!-- indeks: `services/review_batch_focus.py`, `app_settings['review_batch_focus']`, `GET/PUT /api/review-batch/me/focus`, `GET /api/review-batch/me/focus/{job_id}`, `plan_portions(focus, pinned)`, `PlanInputs`, `batch_capacity`, `_release_surplus`, `Activity review_batch.focus`, `why.chosen`, `ReviewBatchFocusPicker`, „Wybierz rekrutację na dziś”, „Twój wybór na dziś” -->

Zgłoszenie rekruterów z 16.11.2026: zespół rano umawia się, kto robi który
request, a porcja dzieli P0 po równo między przypisanych. Decyzje Artura
z 24.11.2026, makieta na stagingu (kopia 24.11, konta 152 i 226, 1280 × 720):
https://claude.ai/artifact/Lhbqb5KSMATAjNmGWuKWk6.

## Decyzje

- **Tylko swoje rekrutacje.** Wybiera się jedną rekrutację, w której osoba
  pracuje (prowadzi, przypisanie, współpraca, te same co `_team_jobs`). Inna
  daje 403, porcja wyłączona 409, konto bez porcji (DL, HoR, nieobecny) 403.
  Wariant „wszystkie w puli” odrzucony: dopisywałby osobę do zespołu, a o tym,
  kto pracuje nad requestem, decyduje DL.
- **Do końca dnia.** Stan w `app_settings['review_batch_focus']` z dniem firmy
  (`business_today`). Następnego dnia roboczego plan wraca do zwykłej
  kolejności (najpierw pilne). „Wróć do zwykłej kolejności” kasuje wybór, a osoby
  zostają u rekrutera. Wariant „do ręcznej zmiany” odrzucony: zapomniany wybór
  odcinałby P0 na kilka dni.
- **Kto pierwszy, ten bierze najlepszych.** Zapis pod blokadą wiersza (`_write`,
  `FOR UPDATE`), więc dwa wybory naraz idą po kolei. Plan obsługuje wybierających
  w kolejności wyboru, przed wszystkimi poziomami (`plan_portions(focus=…)`).
  Nikt nie traci kart, które już ma. Podział po równo odrzucony: pierwszej
  osobie znikałyby karty w trakcie pracy.

## Jak działa

- **Liczba osób do decyzji się nie zmienia.** Z wybranej przychodzi tyle osób, ile
  naprawdę przechodzi jej reguły dopełniania (`batch_capacity`, to samo sito co
  `fill_job`). Z innych rekrutacji osoby schodzi tylko nadwyżka ponad porcję
  (`_release_surplus`): najpierw z najniższego priorytetu, w rekrutacji od
  najsłabszej. Karty, które ktoś wziął („Biorę”, „Dzwonię”), zostają i zajmują
  miejsce przed wybraną (`pinned`). Kto miał mniej niż swój poziom, dostaje
  z wybranej do poziomu, nigdy ponad.
- **Pula od progu to szacunek.** 24.11.2026 na kopii produkcji „91 wolnych” w P0
  dało po regułach 12 osób, a „150” w innej rekrutacji zero. Pierwsza wersja
  zdejmowała karty za szacunek i porcja rekruterki spadła z 10 do 6. Na liście
  wyboru nie ma więc liczby z puli, a podgląd pod zaznaczoną rekrutacją
  (`GET /me/focus/{job_id}`, 0,3–1,2 s) liczy ją tym samym sitem. Nie zdejmuj kart
  za osoby, których jeszcze nie ma.
- **Przebieg porcji trzyma wybór** co 5 minut i rano tego samego dnia
  (`load_inputs` czyta wybór, `PlanInputs.portions`). Odłożone karty (R5) dalej
  nie liczą się w planie.
- **Ekran `/porcja`:** „Wybierz rekrutację na dziś” obok plakietki wyszukiwania
  (`data-tour="review-batch.focus"`); lista w poziomach zamiast zakładek, pod
  zaznaczoną podgląd z serwera i kto już ją dziś wybrał (godzina, ile ma osób);
  po wyborze w pasku „Najpierw z wybranej na dziś: …” z „Zmień” i „Wróć do
  zwykłej kolejności”, nad osobą „Twój wybór na dziś”, w zakładce „Rekrutacje”
  „wybrana na dziś”, a kolejka zaczyna od wybranej (`review_queue`).
- Minimum, blokada 423, termin screeningów, „Dodaj 20 kolejnych” i plan rano
  następnego dnia bez zmian. Bez migracji.
- **Ślad do pomiaru:** każdy wybór i powrót to `Activity` `review_batch.focus`
  (`entity_type` `review_batch`, `entity_id` = osoba, `details`: `job_id`,
  `added`, `released`), bo stan w `app_settings` trzyma tylko dzisiejszy dzień.

## Pomiar po tygodniu

Od pierwszego dnia na produkcji przez 5 dni roboczych, tymi samymi zapytaniami:
ilu rekruterów i w ilu dniach wybiera rekrutację, ile z wyborów to P0, jak
często druga osoba na tę samą rekrutację dostała 0, czy rekrutacje P0 bez
wyboru dostają mniej decyzji niż przed zmianą i czy rośnie liczba decyzji
z porcji na osobę dziennie. Spadek decyzji w P0 bez wyboru o ponad 20% to
sygnał do rozmowy z Arturem o przypomnieniu albo limicie.

Testy: `backend/tests/test_review_batch_focus_unit.py`,
`backend/tests/test_review_batch_focus.py` (dwie osoby naraz, spoza swoich
rekrutacji, poranny plan trzyma wybór, trasy),
`frontend/src/components/v2/review-batch/__tests__/ReviewBatchFocusPicker.test.tsx`,
`ReviewBatchScreen.test.tsx` („rekrutacja wybrana na dziś”).
