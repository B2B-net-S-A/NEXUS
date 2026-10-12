# Blok „Rekrutacje” w filtrze kandydatów i pełna lista rekrutacji — raport z wdrożenia

12.10.2026. Reguły: `docs/claude/kandydaci-wyszukiwanie/filtr-rekrutacje-bral-nie-bral-bez-procesu.md`.
Makiety: https://claude.ai/artifact/G1EfD1VqGL7oaBET2LDg9a.

## Po co

Zespół przechodzi z Traffita i szuka kandydatów ręcznie. W Traffit jest filtr
„Rekrutacje” (Przypisany / Nieprzypisany · Klient · Status rekrutacji ·
Rekrutacja); w NEXUSIE „Nieprzypisani” pojawiało się dopiero po wskazaniu
rekrutacji, więc nie dało się zapytać o osoby, które nie były w żadnej, ani
o osoby, z którymi nikt teraz nie prowadzi procesu.

## Pomiar (produkcja, 12.10.2026, tylko odczyt)

| Co | Liczba |
|---|---|
| Kandydaci | 65 598 |
| Nigdy w żadnej rekrutacji | 27 338 |
| …wyłącznie w „worku zgłoszeń” (jedna rekrutacja, 14 658 osób) | 9 212 |
| Z procesem w toku (reguła kolumny „W procesie”) | 2 011 |
| Rekrutacje ogółem / w liście wyboru filtra | 4 455 / 500 najnowszych |
| Otwarte rekrutacje poza listą wyboru | 16 z 238 |
| Powtórzone tytuły w liście wyboru | 27 |
| Największy klient | 2 112 rekrutacji |

Nowe zapytania (`EXPLAIN ANALYZE` skompilowanego SQL-a, tylko odczyt): filtr
listy 43–66 ms licznik i 0,3–70 ms strona na istniejących indeksach; lista
rekrutacji do 23 ms. Bez migracji i bez nowego indeksu.

## Decyzje właściciela (12.10.2026)

- Obie odpowiedzi: „nie brał udziału w żadnej” i „bez procesu w toku”.
- Worek zgłoszeń liczy się jak rekrutacja (bez wyjątku).
- Pełna wersja: jeden blok „Rekrutacje” i przebudowana lista rekrutacji
  z klientem, numerem, statusem i pozycją „Wszystkie rekrutacje klienta”.

## Co weszło

- `backend/app/services/candidate_recruitment_filter.py` — predykaty listy:
  zakres (rekrutacje LUB wszystkie rekrutacje klientów), obecność
  (`never` / `ever`), proces w toku (`not_in_process`).
- `backend/app/api/candidates.py` — parametry `recruitment_presence`
  i `recruitment_client_id` (lista i eksport), filtr etapu zawężony do całego
  zakresu.
- `backend/app/services/candidate_match_order.py` — okno „Szukaj ręcznie” nie
  włącza się przy zakresie klienta.
- `backend/app/services/job_lookup.py`, `backend/app/api/phase5.py` — nowa
  trasa `GET /api/jobs-lookup/search` (szukanie i etykiety); stara
  `/api/jobs-lookup` bez zmian. Wzorzec bramek `authz_golden/phase5.json`:
  ten sam werdykt co stara trasa.
- `frontend/src/lib/recruitment-filter.ts` — tryb bloku wyliczany z czterech
  pól i łatki każdej zmiany; `frontend/src/lib/url-filters.ts` — pola, adres
  (`recr_cl`, `recr_p`), parametry listy.
- `frontend/src/lib/recruitment-lookup.ts`,
  `frontend/src/components/v2/filters/RecruitmentScopePicker.tsx` — lista
  rekrutacji z szukaniem po stronie serwera (zastąpiła `RecruitmentMultiSelect`).
- `CandidateFilterBar.tsx` (blok „Rekrutacje”, wyłączanie etapu i daty
  wysłania), `ActiveFilterChips.tsx` (chip trybu i klientów),
  `job-search-filters.ts` (okno „Szukaj ręcznie”), harness
  `/preview/candidates-list` z fikcyjną listą rekrutacji.
- Przewodnik Jarvisa `candidates.list` (dopisek o nowych opcjach) i stempel.

## Odstępstwa od makiety

- Lista rekrutacji jest osobnym okienkiem i od 1024 px otwiera się obok okienka
  filtra: pod przyciskiem przy 1280 × 720 mieściło się 150 px listy, obok 360 px.
- Okienko „Historia z nami” ma 460 px (było 420), żeby cztery opcje stały
  w jednym rzędzie. Przy 1280 × 720: „Dowolnie” mieści się bez przewijania
  (374 px), „Nie brał udziału” przewija okienko o 55 px.

## Odstępstwo od planu

Etykiety wybranych pozycji (`ids`, `client_ids`) zwracają nazwę klienta także
wtedy, gdy klient jest ukryty albo usunięty — plan zakładał pustą nazwę. Po
scaleniu klientów chip „Rekrutacje klienta: #12” byłby nieczytelny, a tę samą
nazwę pokazuje już kolumna „W procesie” i ekran rekrutacji.

## Przegląd kodu przed scaleniem

Cztery niezależne przeglądy (Python, TypeScript, całość względem planu,
bezpieczeństwo). Przeglądy Pythona i bezpieczeństwa nie znalazły nic
blokującego. Dwie rzeczy blokujące, obie poprawione przed otwarciem PR-a:

- Stopka listy rekrutacji stała wewnątrz `<Command>`, więc Enter na „Gotowe”
  albo „Wyczyść” zaznaczał podświetlony wiersz zamiast wykonać przycisk (cmdk
  przechwytuje Enter) — do filtra wpadała rekrutacja, której nikt nie wybrał.
  Stopka stoi teraz poza `<Command>`; test odtwarzający błąd był czerwony przed
  poprawką.
- Test „bez procesu w toku” zasiewał etap „Wycofany” bez powodu, a baza taki
  wiersz odrzuca (`ck_candidate_stages_withdrawn_requires_reason`). Pierwszy
  pełny bieg CI na gałęzi (run 38242944674) miał przez to czerwony shard 9 —
  jedyny czerwony test na 12 shardów. Etap końcowy w teście to teraz
  „Odrzucony”, a zasiew stoi w `try`, żeby nieudany nie zostawiał danych.

## Weryfikacja

- Testy bez bazy lokalnie (Python 3.12): kształt SQL predykatów, lustro zbioru
  etapów końcowych z frontem, klauzula szukania, macierz bramek, stemple, indeks.
- Testy z bazą w pełnym biegu CI na gałęzi po poprawkach (run 38245537176):
  obecność, „bez procesu w toku” w ośmiu układach z parytetem względem kolumny
  „W procesie”, zakres klienta, tryb razem z zakresem (okno rekrutacji),
  eksport, nowa trasa, cofnięcie sekcji.
- Front: `tsc`, ESLint, Vitest (logika trybów, adres, każda para stanów czeka
  na „Szukaj”, lista wyboru z klawiaturą, chipy, ekran listy i okno „Szukaj
  ręcznie”).
- Harness `/preview/candidates-list` i `?embed=1` przeklikany przy 1280 × 720
  i 1280 × 650.

## Znane ograniczenia

- Alert zapisanego wyszukiwania nie reaguje na sam ruch karty (skaner patrzy na
  zmianę wiersza kandydata, notatkę i dokument), więc osoba zdjęta z rekrutacji
  nie wywoła dzwonka.
- Reguła „w toku” ma nadal trzy zapisy (lista, podgląd, profil); filtr jest
  przypięty testem do listy.
- Stara trasa `/api/jobs-lookup` została bez konsumenta we froncie — do
  usunięcia osobno.
