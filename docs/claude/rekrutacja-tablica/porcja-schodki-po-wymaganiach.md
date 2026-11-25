# Porcja dnia: schodki po wymaganiach — najpierw więcej spełnionych „musi mieć”
<!-- indeks: `services/requirement_steps.py`, `Steps`, `steps_for`, `steps_for_jobs`, `labels_by_candidate`, `steps_if_enabled`, `OrderFacts.steps`, `_step_key`, `_with_known_points`, `entry_autofill.steps`, `requirements` w `/me/queue`, `ReviewBatchRequirementsBlock`, „Musi mieć 7 z 10” -->

Decyzja Artura z 23.11.2026, wariant B z makiet:
https://claude.ai/artifact/5SJB7AYPZWbFkVKf77jhnN. Zgłoszenie: „ręczne
wyszukiwanie jest lepsze niż porcja”, prośba: najpierw osoby spełniające
krytyczne, musi mieć i mile widziane, potem reszta.

## Reguły

- **Klucz kolejności** (`review_batch_order.order_cards`, lustro `orderNewColumn`):
  grupy bez zmian (nowi w bazie od progu, bez uwag z miejscem co 5., z ostrzeżeniem,
  z brakiem krytycznej), a w każdej grupie najpierw mniej braków „musi mieć”, potem
  mniej braków „mile widzianych”, dopiero potem wynik z premiami (znamy, aktywnie
  szuka, budżet, polski, lider). Premie działają już tylko w obrębie schodka.
- **Jedna kolejność wszędzie:** porcja (`with_order_facts`), dobór z puli
  (`new_column_autofill._with_known_points`, okno 150 osób, więc do porcji wchodzą
  najpierw osoby z największą liczbą spełnionych „musi mieć”) i kolumna „Nowi”
  na Tablicy (`entry_autofill.steps` z `requirement_steps.steps_for_jobs`, dwa
  zapytania na wszystkie Tablice).
- **„Spełnia” = ślad w CV albo na liście umiejętności** (`review_batch_facts.evidence_for`:
  doświadczenie albo wzmianka), ta sama miara co „Kluczowe w tej rekrutacji”.
  Wiersz Championa spełnia jedno jego słowo (`label_row_words`, „Postman lub Swagger”).
  „Musi mieć” liczy się bez krytycznych.
- **Na koniec idzie tylko brak krytycznej w CV.** Do 23.11 porcja odkładała każdą
  kartę z `entry_meta.missing_must`, czyli z dowolnym „?” silnika przy „musi mieć”
  (w rekrutacji Spark wszystkie karty). Ze schodkami taka karta stoi według liczby
  spełnionych. Bez schodków (porcja wyłączona, rekrutacja bez wymagań) — jak dotąd.
- **Karta porcji:** „Musi mieć 7 z 10 · brak: …” z chipami ✓ / ~ / ✗ (klik przewija CV),
  „Mile widziane 2 z 7: …” i linia „Kolejność: 7 z 10 musi mieć · 69% + …”
  (`ReviewBatchRequirementsBlock`, `orderLine`). Zastępuje chipy ✓ / ? z migawki
  silnika i zdanie „Z listy wymagań: X z Y”. Procent zostaje wynikiem.
- **Tylko przy włączonej porcji** (`REVIEW_BATCH_ENABLED`, `steps_if_enabled`).
- **Osoba tylko ze słowami swojej rekrutacji.** `steps_for_jobs` podaje
  `evidence_for` mapę `labels_by_candidate`; bez niej każda osoba ze wszystkich
  Tablic idzie przez słowa wszystkich rekrutacji. 25.11.2026 strażnik pętli
  zdarzeń złapał 34 zastoje `my-next-steps` (do 35 s, `loop_stall` w `_text_hit`).
  Kopia z 25.11, rekruter z 25 Tablicami: 850 osób × 204 słowa = 173 400 par
  i 33 s CPU w pętli, przy 12 123 potrzebnych parach; po zmianie 0,7 s, wynik
  ten sam. Nowe wywołanie `evidence_for` dla wielu rekrutacji też zawęża pary.
  Wzmianka w CV (`_text_hit`): najpierw `str.find`, regex tylko od pierwszego
  wystąpienia słowa, wzorce skompilowane raz (`_mention_pattern`).

## Pomiar (kopia produkcji z 23.11.2026, karty od 09.11)

- Komplet krytycznych i „musi mieć”: 4,4% decyzji do klienta, 75–99%: 4,0%,
  50–74%: 2,9%, mniej niż połowa: 1,4%. „Pasuje” tego nie odróżnia (51–56%).
- Pełne „spełnia wszystko” z mile widzianymi: 2,5% do klienta przy średniej 2,8%,
  6% kart; w 85 ze 172 rekrutacji z pulą nikt nie ma kompletu krytycznych i „musi
  mieć”. Dlatego nie „najpierw komplet”, tylko schodki (wariant A odrzucony).
- Symulacja na 48 rekrutacjach (2 297 decyzji): górna połowa kart 35 → 44 osoby
  u klienta, „Pasuje” 56,2% → 53,4%. Do sprawdzenia po 2 tygodniach tym samym zapytaniem.
- Różnica z ręcznym szukaniem leży gdzie indziej: w tych samych rekrutacjach
  ręcznie dodani idą do klienta w 21,1% decyzji, porcja w 3,4%, a 38 z 53
  wysłanych ręcznie silnik stawiał poza pierwszą 60. Osobne badanie silnika.

Testy: `backend/tests/test_requirement_steps.py`,
`frontend/src/lib/__tests__/new-column-queue.test.ts` („schodki po wymaganiach”),
`frontend/src/components/v2/review-batch/__tests__/ReviewBatchRequirements.test.tsx`.
