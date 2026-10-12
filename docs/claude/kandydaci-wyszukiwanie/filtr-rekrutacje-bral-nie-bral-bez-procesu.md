# Blok „Rekrutacje” w filtrze „Historia z nami”: brał / nie brał udziału, bez procesu w toku (12.10.2026)
<!-- indeks: odpowiednik „Nieprzypisany” z Traffita, zakres klienta, lista rekrutacji z szukaniem po stronie serwera, cztery pola stanu i tryb wyliczany -->

Decyzja Artura 12.10.2026 (makiety: https://claude.ai/artifact/G1EfD1VqGL7oaBET2LDg9a).
Zespół przechodzi z Traffita i szuka ręcznie; w Traffit jest „Rekrutacje:
Przypisany / Nieprzypisany · Klient · Status rekrutacji · Rekrutacja”. Do tej
daty lista miała tylko „Przypisani / Nieprzypisani” po wskazaniu rekrutacji,
a lista rekrutacji w filtrze pokazywała 500 najnowszych z 4 455, sam tytuł.

Pomiar produkcji 12.10.2026: 65 598 kandydatów, 27 338 nigdy w rekrutacji,
2 011 z procesem w toku. Nowe warunki 1–70 ms na istniejących indeksach
(`EXPLAIN ANALYZE`, tylko odczyt) — bez migracji.

## Co widzi rekruter

Jedno pytanie: **Dowolnie · Brał udział · Nie brał udziału · Bez procesu w toku**.
Przy dwóch środkowych lista rekrutacji, domyślnie „Wszystkie rekrutacje”:

- „Nie brał udziału” bez wskazania rekrutacji = w ŻADNEJ (to „Nieprzypisany”
  z Traffita); „Brał udział” bez wskazania = w co najmniej jednej.
- Ze wskazaniem — dotychczasowe znaczenie: jest w którejkolwiek z wybranych /
  nie ma go w żadnej z wybranych.
- „Bez procesu w toku” = reguła kolumny „W procesie”: najnowszy wiersz pary
  (osoba, rekrutacja) na rekrutacji niezamkniętej stoi na etapie innym niż
  końcowy. Zbiór końcowy kolumna trzyma we froncie (`candidate-row-format.ts`,
  `TERMINAL_STAGES`), filtr wyprowadza go z `STAGE_CATEGORY`; zgodność przypina
  test-lustro i test parytetu z `include_active_recruitments`
  (`test_candidates_recruitment_filter.py`). Osoba „Pracuje u nas” zostaje w tym
  filtrze — zatrudnienie u klienta to osobny filtr „Dostępność”.
- „Jest w rekrutacji” znaczy: ma dowolny wiersz etapu, także końcowy i z archiwum
  Traffita. **Worek zgłoszeń liczy się jak rekrutacja** (decyzja Artura: bez
  wyjątku; rekrutacja nie ma znacznika „worek”). Propozycje automatu, shortlisty
  i pule przypisaniem nie są.

## Parametry listy (`GET /api/candidates`, eksport bierze je sam)

- `recruitment_presence`: `never` | `ever` | `not_in_process`.
- `recruitment_client_id` (powtarzany): „wszystkie rekrutacje klienta” — warunek
  po `jobs.client_id`, nie lista numerów (największy klient ma 2 112 rekrutacji
  i dochodzą nowe). Razem z `recruitment_id` tworzy JEDEN zakres (LUB), kierunek
  niesie `recruitment_match`. Filtr etapu razem z zakresem „przypisany” dotyczy
  rekrutacji z całego zakresu (`job_in_scope` w predykacie i w `move_predicates`).
- Predykaty są w `app/services/candidate_recruitment_filter.py` — builder listy
  nie może ich mieć u siebie (strażnik źródła w `test_candidate_search_predicates.py`).
- **Nie przeciążaj `recruitment_match=not_assigned` pustą listą rekrutacji.**
  Para „jedna rekrutacja + `not_assigned`” oznacza okno „Szukaj ręcznie”
  (`candidate_match_order.job_scope`, front `matchSortAvailable`) i włącza
  kolejność „Dopasowanie”. Zakres klienta ten kontekst wyłącza — inaczej
  `order_base_filters` odwróciłby „poza klientem” na „u klienta”.
- Zapisane wyszukiwania niosą oba parametry same (`list_only`, przypadki we
  wspólnym pliku `saved-search-unified-cases.json`). **Znane ograniczenie:**
  alert zapisu z tym filtrem nie reaguje na sam ruch karty (skaner patrzy na
  zmianę wiersza kandydata, notatkę i dokument), więc osoba zdjęta z rekrutacji
  nie wywoła dzwonka. Zapis z samym „Nie brał udziału” i dzwonkiem alarmuje przy
  prawie każdym nowym kandydacie (80% dodanych w 90 dni nie trafia do rekrutacji).

## Stan we froncie — cztery pola, tryb wyliczany

`recruitmentIds`, `recruitmentClientIds` (zakres), `recruitmentMatch` (kierunek),
`recruitmentPresence` (pytanie bez zakresu). Tryb liczy `recruitmentMode`
z `lib/recruitment-filter.ts`; **pola zapisuj tylko jego łatkami** — żyją w dwóch
pojemnikach stanu listy, więc łatka częściowa zostawia resztę po poprzednim trybie.

- Odznaczenie wszystkiego W LIŚCIE wraca do „Wszystkie rekrutacje” bieżącej
  opcji; ✕ na ostatnim chipie zakresu nad tabelą zdejmuje filtr („Dowolnie”) —
  nie może zamienić „poza rekrutacją X” w „w żadnej rekrutacji”.
- „Nie brał udziału” w żadnej czyści i wyłącza „Etap w rekrutacji” oraz „Wysłany
  do klienta” (zawsze dałyby zero), ze zdaniem wyjaśnienia.
- Adres: `recr_cl`, `recr_p` dopisane PO `recr_mode` — stare adresy i zapisy
  zostają bajt w bajt. `recr_mode` idzie przy każdym niepustym zakresie, także
  gdy to sam klient. Pole, którego `encodeFilters` nie zapisze, jest niewidoczne
  dla licznika „Szukaj” (test wszystkich par stanów w `candidate-list-staging.test.ts`).
- Okno „Szukaj ręcznie”: pigułki zostają, listy rekrutacji nie ma (zdanie
  blokady). `candidatesListFiltersForQuery` wymusza „nie w tej rekrutacji”,
  czyści zakres klienta (przywrócony z pamięci filtrowałby niewidocznie)
  i zostawia `recruitmentPresence`.

## Lista rekrutacji — `GET /api/jobs-lookup/search`

Nowa trasa obok starej `/api/jobs-lookup` (ta zostaje bez zmian: przypinają ją
testy bramek i otwarte karty). Ta sama bramka sekcji, lista wspólna dla całej
firmy (bez zawężenia Delivery Leada — jak pozostałe listy wyboru rekrutacji).

- **Szukanie** (`q`, `status=open|closed|all`, `limit` ≤ 50): to, co pokazuje
  rejestr `/jobs` (bez klientów ukrytych i usuniętych); tekst pasuje do nazwy
  roboczej i od klienta, numeru referencyjnego, nazwy klienta albo numeru
  rekrutacji („2143”, „#2143”). **Technologii z wymagań świadomie nie czyta**
  (nie używaj `jobs_search_clause`): lista pokazuje tytuł i klienta, więc
  trafienie „po Javie” byłoby wierszem bez wyjaśnienia. `clients` (do 5, przy
  tekście ≥ 2 znaki) to pozycje „Wszystkie rekrutacje klienta …”.
- **Etykiety** (`ids`, `client_ids`): bez filtra widoczności i statusu — zapisany
  wcześniej identyfikator dalej filtruje listę, więc chip nie może spaść do „#123”.
- Front: `lib/recruitment-lookup.ts` (osobne klucze zapytań dla szukania
  i etykiet; `paramsSerializer: { indexes: null }`, bo `ids[]=` serwer pomija po
  cichu) i `RecruitmentScopePicker.tsx`. Przełącznik statusu stoi w `<Command>`,
  więc jest owinięty `onKeyDown` ze `stopPropagation` — bez tego Enter na
  przełączniku zaznaczał podświetlony wiersz listy (test to pilnuje).
- Lista jest osobnym okienkiem, nie częścią okienka „Historia z nami”
  (odstępstwo od makiety — inaczej okienko nie mieści się na laptopie
  1280 × 720). Od 1024 px szerokości otwiera się OBOK okienka filtra: pod
  przyciskiem zostawało przy 1280 × 720 miejsce na dwa i pół wiersza (150 px),
  obok jest 360 px. Węziej zostaje pod przyciskiem. Okienko „Historia z nami”
  ma 460 px, żeby cztery opcje stały w jednym rzędzie.
