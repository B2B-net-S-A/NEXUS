# Porcja dnia: „Nie odebrał” przesuwa termin screeningu (najwyżej 3 próby)
<!-- indeks: `Decision.attempt_at`, `deadline_attempt`, `MAX_DEADLINE_ATTEMPTS`, `_contact_attempts`, notatka `contact_attempt`, `OpenScreening.attempts` / `last_attempt_at`, „Nie odebrał” w „Do domknięcia” -->

Zgłoszenie rekrutera i decyzja Artura z 23.11.2026. Rekruter po „Pasuje” dzwoni
od razu, kandydat nie odbiera, a po 2 dniach roboczych karta była „po terminie”
i zamykała ręczne wyszukiwanie, choć „Nie odebrał” było zapisane. Na kopii
z 23.11: 364 próby „Nie odebrał” od 09.11, 114 kart po terminie u 9 osób, z tego
4 z zapisaną próbą. Makiety: https://claude.ai/artifact/AJn23wcUzdu2UTRXUeeVtP.

- **Termin domknięcia liczy się od ostatniej próby kontaktu** po decyzji
  (`Decision.due_from` = najpóźniejsze z: ruch, powrót do zespołu, próba).
  Próba = notatka rodzaju `contact_attempt` („Nie odebrał” z Tablicy, profilu,
  formularza i porcji) przy tej rekrutacji albo bez rekrutacji, nowsza niż ruch.
- **Przesuwają tylko pierwsze 3 próby** (`MAX_DEADLINE_ATTEMPTS`,
  `deadline_attempt`). Po trzeciej bez odpowiedzi karta wraca na „po terminie”
  2 dni robocze od niej: wynik screeningu albo odrzucenie z powodem („Nie szuka
  pracy”). Artur wybrał sufit, bo bez niego „Nie odebrał” co 2 dni trzymałoby
  kartę otwartą bez końca. Front zna tę liczbę osobno (`ReviewBatchScreen`).
- **„Nie odebrał” stoi w porcji** w „Do domknięcia” obok „Otwórz screening”
  (`useNoAnswerNote`, ta sama notatka co na Tablicy). Lista pokazuje „nie
  odebrał ×N” i datę ostatniej próby; pasek i komunikat blokady mówią, że
  próba przesuwa termin.
- **Umówiony telefon („Umów telefon”) terminu nie przesuwa.** Artur: z porcji
  dzwoni się od razu, nie planuje telefonu za kilka dni.

Testy: `test_review_batch_stage0_unit.py` (`test_no_answer_attempt_moves_the_deadline`,
`test_only_first_three_attempts_move_the_deadline`), `ReviewBatchScreen.test.tsx`.
