# Porcja dnia: kolejka oceniania rekrutacja po rekrutacji, nie na zmianę
<!-- indeks: `review_batch.review_queue`, `review_batch.queue_runs`, `/api/review-batch/me/queue` → `runs`, `QueueRunLine`, `review-queue-run`, „Ta rekrutacja: jeszcze N osób · Potem: …” -->

Decyzja Artura z 17.11.2026 (wariant A z makiet:
https://claude.ai/artifact/7ofXGmhaEa7hC7w8xT8DUL), po zgłoszeniu rekrutera:
„mam 3 kandydatów na request A, potem 2 na B, później jeden na A i potem kilku
na B — trochę to utrudnia sprawne ocenianie”. Kolejka przeplatała rekrutacje
po jednej karcie, więc co kartę zmieniały się profil „Kogo szukamy”, wymagania
i CV po prawej. W dniach 10–13.11 (kopia stagingu) 751 decyzji z porcji dało
125 przeskoków między rekrutacjami, a przy kolejce rekrutacjami wystarczyłoby 65.

## Reguły

- **Kolejka na ekranie `/porcja` idzie rekrutacja po rekrutacji**
  (`review_batch.review_queue`). Poziomy zostają: najpierw cały P0, potem
  P1 Pilne, „Bez priorytetu”, „Przyjmujemy kandydatów”. W obrębie poziomu
  najpierw rekrutacja z najbliższym terminem P0, potem ta z większą liczbą
  osób w kolejce, potem id. W rekrutacji kolejność kolumny „Nowi” na Tablicy.
  Nie wracaj do przeplatania bez nowej decyzji.
- **Plan porcji się nie zmienia.** Podział kart między osoby i rekrutacje
  (`review_batch_plan.plan_portions`, „na zmianę po jednej karcie”) dotyczy
  tego, kto dostaje które karty, a nie kolejności na ekranie.
- **Nad kartą jedna linia** (`QueueRunLine`): „Ta rekrutacja: jeszcze 2 osoby ·
  Potem: <tytuł> (4) i 1 kolejna”. Liczby są z całej kolejki osoby
  (`runs` w `/me/queue`, `queue_runs`), nie z 20 kart na stronie. Ostatnia albo
  jedyna rekrutacja w kolejce: bez linii. Po decyzji kolejka przychodzi od nowa,
  więc bieżąca rekrutacja jest zawsze pierwsza i numer „1 z N” z makiety nie
  miałby sensu.
- **Lista rekrutacji do przełączania nad kartą (wariant B z makiet) nie
  została wybrana 17.11.2026.** Nie dokładaj jej bez nowej decyzji. Wybór
  rekrutacji na cały dzień zdecydowany 24.11.2026: wybrana idzie w kolejce
  pierwsza, reguła w `porcja-wybor-rekrutacji-na-dzis.md`.

Testy: `test_review_batch_unit.py`
(`test_queue_goes_job_by_job_nearest_p0_deadline_first`,
`test_queue_takes_whole_levels_p0_first`), `ReviewBatchScreen.test.tsx`
(„kolejka rekrutacja po rekrutacji”).
