# Porcja dnia: „Kluczowe w tej rekrutacji” z dowodem i polski
<!-- indeks: `review_batch_facts`, `key_facts`, `key_facts_for`, `evidence_state`, `polish_status`, `polish_name`, `job_needs_polish`, `NO_POLISH_NEEDED_RE`, `refused_polish` w `system_exclusions`, `ReviewBatchKeyFacts`, klik w pozycję → `searchRequest` -->

Decyzje Artura z 12.11.2026, raport i makiety:
https://claude.ai/artifact/PqmctW9taWS8mXwmGfrFSM (R2, R4, makieta M1).

## Karta

- **Zamiast listy „✓ / ?” stoją krytyczne rekrutacji** (`stored_critical`, profil
  Championa) z dowodem i wiersz „Polski” (`key_facts` w `GET /api/review-batch/me/queue`,
  `review_batch_facts.key_facts_for`, trzy zapytania na kolejkę). Rekrutacja bez
  krytycznych zostaje przy dzisiejszych chipach. Pod spodem „Wymagania z listy:
  X z Y”, pełna lista w zakładce „Wymagania”.
- **Dowód krytycznej:** ✓ doświadczenie = oś technologii z odczytu CV
  (`candidate_skill_usage.months` > 0, cała rodzina aliasów jak w filtrze „Lata”),
  ~ wzmianka = w CV albo na liście umiejętności bez dat, ✗ brak.
- **Klik w pozycję zostaje i działa też w karcie:** CV po prawej szuka tej frazy
  (`searchRequest` panelu podglądu, to samo co klik w „Wymaganiach”).

## Dowód nie wycina nikogo (pomiar 12.11.2026)

Na 1 720 kartach od systemu od 15.10 w rekrutacjach z krytycznymi (najsłabszy
dowód spośród krytycznych): doświadczenie 67% „Pasuje” i 10,7% do klienta,
wzmianka 56% i 10,8%, brak śladu 54% i 4,2%. Artur wybrał „pokazuj dowód”:
bramka porcji się nie zmienia, karta z brakiem krytycznej stoi na końcu jak
dotąd (`criticalGapMap`, `order_cards`). Nie wycinaj wzmianek ani „braku śladu”
bez nowej decyzji: samo „tylko doświadczenie” straciłoby 51 z 72 wysłanych.

## Polski

- **Stan:** profil (ojczysty albo poziom) wygrywa ze wszystkim; potem odrzucenie
  „Brak polskiego” („nie zna”); potem CV po polsku; potem polskie imię i nazwisko
  (`polish_name`: polska litera albo końcówka nazwiska); inaczej „brak danych —
  sprawdź”.
- **Imię i nazwisko tylko podnosi status.** Nigdy nie daje „nie zna”, bo wtedy
  decydowałoby pochodzenie, a nie język. Pomiar 12.11: z 36 odrzuceń za język
  albo pochodzenie 2 osoby miały polskie imię i nazwisko; wśród pozostałych 287
  odrzuconych 64 osobom samo imię i nazwisko dodaje polski, którego nie ma w profilu.
- **Osoba odrzucona za „Brak polskiego” nie wraca do porcji** innych rekrutacji
  (`system_exclusions` → `refused_polish`), chyba że rekrutacja wprost mówi, że
  polski nie jest potrzebny (`job_needs_polish`, `NO_POLISH_NEEDED_RE` na
  `champion_profile.basics.language`; ten sam wzorzec w SQL). Pole języka rekrutacji
  zwykle pomija polski przy polskich bankach, więc pusty albo „Angielski” znaczy
  „polski potrzebny”.

Testy: `backend/tests/test_review_batch_facts.py`,
`test_autofill_feedback.py::test_engine_skips_people_refused_for_no_polish_unless_the_job_says_so`,
`frontend/src/components/v2/review-batch/__tests__/ReviewBatchKeyFacts.test.tsx`.
