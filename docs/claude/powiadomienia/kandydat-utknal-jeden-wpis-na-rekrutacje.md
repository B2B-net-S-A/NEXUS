# „Kandydat utknął”: jeden wpis na rekrutację na tydzień (08.11.2026)

Audyt 2, U4. Dzwonek na parę to było 44% dzwonków DL (1932 z 4436 w dwa
tygodnie), a karta ruszała po 3,1% z nich. Większość dotyczyła rekrutacji, przy
których rekruter już nie pracował. Decyzja Artura 08.11.2026 (przyjęta
propozycja raportu). Kod: `check_stage_stuck_7d`.

- **Prowadzący** dostaje raz w tygodniu jeden wpis na rekrutację: „43084 Senior
  PM: 23 osoby stoją ponad 7 dni (najdłużej 21 dni)”, link
  `/jobs/{id}?added_by=stuck` (filtr „Stoją > 7 dni” Tablicy, ta sama reguła co
  chip „Utknęli”: `days_in_stage > 7`, kolumny w toku bez „Zatrudniony”
  i zamkniętych; „Ogłoszenia” leżą w „Nowi” i się liczą).
- **Rekrutacja bez pracującego rekrutera** (zespół z `recruiters_for_jobs`:
  brak osób, odpięci „Poprzedni”, konto wyłączone, sama propozycja automatu):
  jeden wpis do DL-a (aktywnego) i do każdego HoR, „przypisz rekrutera”, encja
  `job_unstaffed`. Tylko gdy ktoś przy niej był (odpięty, konto wyłączone) albo
  to P1: bez prowadzącego poza P1 to stan normalny (08.11.2026: 47 wpisów
  tygodniowo zamiast 130).
- **Pojedynczy dzwonek** zostaje tylko dla „CV wysłane” (follow-up, ruch po
  stronie osoby) i tylko do pracującego rekrutera. DL nie dostaje par.
- **Co budzi** zostaje jak było: karta w oknie 7–30 dni, etap ustawiony
  w NEXUSIE (nie import Traffita), rekrutacja opublikowana. **Co liczy wpis** to
  to, co pokaże filtr: wszystkie karty w toku ponad 7 dni, bez górnej granicy
  i z importem, inaczej liczba we wpisie rozjeżdża się z ekranem.
- Bez nowego typu w enumie: `stage_stuck_7d` z encją `job` albo `job_unstaffed`
  (`STAGE_STUCK_*_ENTITY` w `notification_topics.py`). Dedup tygodniowy po
  (odbiorca, rodzaj encji, id encji), bo id etapu i id rekrutacji to dwie
  numeracje.
- **Okienko „Rekrutacje”** (`GET /api/notifications/jobs`): `stage_stuck_7d`
  nigdy nie jest podglądem wątku, jeśli w wątku jest inna sprawa, i nie wypycha
  wątku na górę. Wątek z samym wpisem zbiorczym ma `digest`
  (`stuck`/`unstaffed`), link z wpisu i własną sekcję pod nowościami
  (`splitJobThreads`), a nie w miejscu ważniejszych dzwonków.
- Kategoria dalej „Przypomnienia”: wyciszenie osoby działa bez zmian.
