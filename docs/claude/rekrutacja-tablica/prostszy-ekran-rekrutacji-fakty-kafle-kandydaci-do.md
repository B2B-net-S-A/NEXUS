# Prostszy ekran rekrutacji — fakty, kafle „Kandydaci do dodania”, kolumna „Zamknięci” (02.10.2026)

Decyzje Artura 02.10.2026 („znowu za dużo się dzieje”), makieta wariant B:
https://claude.ai/artifact/ASHNaTXA9omvTH393cQjCv. Zastępuje ścieżkę
rekrutacji i pasek filtrów z 24.09 oraz blok propozycji w „Nowych” z 22.09.

- **Nagłówek = tytuł + status, linia z nazwą i numerem od klienta, trzy fakty:
  Klient · Budżet · Tryb pracy** (`lib/job-header-facts.ts`, brak wartości =
  „nie podano”). Po prawej tylko „Tablica | Profil Championa”, „Historia
  i czat” i „⋯”. Nie ma liczników, ścieżki „Zlecenie → … → Umowa”,
  „Najbliższego kroku” ani podtytułu. **Od 14.10.2026 układ opisuje sekcja
  „Nagłówek w trzech cienkich liniach” na końcu pliku** (priorytet, „Rekruter”,
  źródła kandydatów w nagłówku, „Zwiń”).
- **Nic nie znika — schodzi do menu „⋯”** (`JobDetailCompactHeader`): „Oznacz:
  mamy championa”, „Dodaj po nazwisku”, „Dodaj z pliku CV”, „Przeszukaj całą
  bazę (AI)”, „Moi ludzie do tej rekrutacji” (otwiera panel „Moi ludzie”),
  „Zlecenie — skrót”, „Zespół” (z „Rekruter: X +N”), „Baza pytań”, „Ukryj /
  Pokaż puste kolumny” + dotychczasowe pozycje. **Od 25.10.2026 menu ma
  dziewięć pozycji bez dubli nagłówka** — `menu-rekrutacji-dziewiec-pozycji.md`;
  akcja z drugim widocznym wejściem nie wraca do menu. Kotwica
  pomocy `job.champion.found` stoi na przycisku menu (pozycji zamkniętego menu
  nie ma w DOM).
- **„Kandydaci do dodania” = cztery źródła** (`CandidateSourcesStrip`; do
  14.10.2026 pasek z kaflami nad Tablicą przez `KanbanBoardV2.renderAbove`,
  od 14.10 trzecia linia nagłówka — sekcja na końcu pliku):
  Podobne rekrutacje · Nowi z ogłoszeń (7 dni) · Propozycje z bazy · Szukaj
  w bazie. „Nowi” to zwykła kolumna — liczy tylko karty. Liczby: `GET
  /api/jobs/{id}/proposal-counts` (`postings_recent` + `base` = `total`
  skrzynki, `screened_out`, `not_searchable_must`), `GET …/similar`
  (`reassignable_people` + `other_people`), licznik wyszukiwania (`page_size=1`).
  Po otwarciu okna kafle czytają `jobProposalsKeys.visibleSplit` — te same
  liczby co zakładki (lista łączy skrzynkę z żywym przeglądem). Brak liczby to
  „—”, nigdy zero. Poniżej 1024 px szerokości PASKA kafel jest jedną linią
  (`@container`), żeby Tablica na laptopie zaczynała się wysoko.
- **Jedno okno dla wszystkich źródeł** (`AddCandidatesPanel`, `?win=add&wintab=
  similar|postings|base|search|manual`; stary `?win=similar` działa): w każdej
  zakładce lista + podgląd osoby OBOK (`PersonPreview`, ten sam co w podobnych
  rekrutacjach), zaznaczenie i „Dodaj N do Nowych”. Zakładki to haki zwracające
  sloty (`SourceTabSlots`: toolbar, body, footer, sidePane) — zostają
  zamontowane, więc zaznaczenia przeżywają przełączanie; zapytania startują po
  pierwszym wejściu (`visited`).
  - „Podobne rekrutacje” (`useSimilarJobsTab`): w rekrutacji najpierw wysłani
    do klienta, pod nimi „Pozostali z tej rekrutacji” (`GET …/similar/people?
    include_rest=true`: doszli co najmniej do Screeningu, klient ich nie
    widział; ≤ 50 + `rest_total`). Pozostali nie są zaznaczani sami i idą przez
    `proposals/bulk` (`historical`) — `/similar/reassign` przyjmuje wyłącznie
    wysłanych (422).
  - „Nowi z ogłoszeń” / „Propozycje z bazy”: jedna scalona lista
    `useJobProposals` dzielona przez `splitByPostings` (`posting_recent` liczy
    serwer: źródła `new_cv`/`job_board`, `first_seen_at` z 7 dni) — nikt nie
    wypada i nikt się nie dubluje. „Pomiń” z powodem jak na ekranie propozycji.
  - „Szukaj w bazie” (`useSearchBaseTab` + `useJobSearchSeed`): lista na tym
    samym API i tych samych filtrach co „Szukaj ręcznie” (wiersze `search.
    requirements` Championa, `sort=match`), uruchamiana od razu; od 13.10.2026 linie „Wymagane (krytyczne)”, „Musi
    mieć (Delivery Lead)”, „Mile widziane”, „Lokalizacja kandydata” i „Rekruter
    sprawdza w rozmowie” (`talk_checks` z `proposal-counts`) zastąpiły blok
    „Po tym nie szukamy” — `dwie-listy-wymagan.md`. Bez wierszy w Championie
    zakładka NIE pokazuje całej bazy — odsyła do Championa i „Szukaj ręcznie”.
    Zastąpiła „Znajdź w bazie (AI)”; ręczny pełny przegląd AI startuje z menu
    „⋯” (`fullReviewRequest` — raz na kliknięcie, nigdy przy otwarciu okna).
  - „Szukaj ręcznie” (14.10.2026) to piąta zakładka tego okna, nie osobne
    okno: `ManualSearchPanel` w oknie szerokim, bez podglądu osoby obok, liczba
    na zakładce „—”. „Zmień słowa i filtry” i „Szukaj ręcznie” w „Szukaj
    w bazie” przełączają zakładkę (okno zostaje, zaznaczenia też); po pierwszym
    wejściu wyszukiwarka zostaje zamontowana (ukryta poza zakładką). Stare
    `?win=manual-search` i `?tab=manual-search` otwierają `win=add&wintab=manual`.
    Kafla nie ma (`CandidateWindowTab` = kafle + `manual`).
- **Tablica bez paska filtrów** (nazwisko, „Mój ruch”, „Filtry”, „N w procesie”,
  SLA w pasku — usunięte bez zamiennika; plakietki „Twój ruch” i SLA kolumn
  zostają). Wyjątek od 14.10.2026: jeden przycisk „Kto dodał” w nagłówku (linia
  źródeł kandydatów) (`nastepna-osoba-po-odrzuceniu.md`, sekcja „Kolejka w kolumnie…”);
  kolejny filtr = nowa decyzja. **„Zamknięci” to wąska kolumna obok Tablicy** (`board-closed-column`,
  poza przewijanym obszarem): cztery strefy upuszczenia z tymi samymi
  `droppableId` co dawne chipy (`closedChips`), klik rozwija kolumny zamkniętych.
- **Tytuł roboczy nie bierze zdań z must-have** (`job_working_title._is_prose`
  ↔ `lib/job-names.ts`, wspólny fixture): pozycja > 3 słów, > 40 znaków albo
  z `, ; : – —` jest pomijana PRZED wyborem dwóch pierwszych. Istniejące tytuły
  automatyczne przelicza jednorazowo faza `working-title-prose-fix`
  w `entrypoint.sh` (marker `job_working_title_prose_fix_2026_10`; ręczne
  tytuły i `updated_at` nietknięte).
- **Laptop 1280 × 720:** kolumna „Nowi” zaczyna się na ~56% wysokości okna
  (`/preview/job-detail?empty=1`). Harness ma zasiane wszystkie cztery źródła:
  `?sources=similar|postings|base|search` otwiera okno od razu.

## Wiersz listy: dopasowanie bez klikania, „+ Dodaj” z „Cofnij”, powód (14.10.2026)

Decyzja Artura D1 + P1 (14.10.2026) — rekruter klikał kafel, „Policz
dopasowanie dla N”, otwierał osobę, zaznaczał i dopiero dodawał.

- **Dopasowanie liczy się samo.** Przycisku „Policz dopasowanie dla N” nie ma:
  wiersz `PickList` zgłasza się, gdy wejdzie na ekran (`IntersectionObserver`;
  bez niego — jsdom — pierwszych 20), a okno woła `useVisibleMatchScores`
  (paczki po 20, ponowienia 429). To tani odczyt wektorowy, nie LLM. Bez
  wyniku i bez błędu wiersz mówi „liczę…”, błąd — „nie policzono — ponów”,
  brak pomiaru — „Ocena niepełna”, nigdy 0. Lista dla hooka tylko rośnie
  (nowa tożsamość listy zeruje wyniki). Pełny przegląd AI nadal tylko z „⋯”.
- **„+ Dodaj” w wierszu** propozycji („Nowi z ogłoszeń”, „Propozycje z bazy”)
  i „Szukaj w bazie” — nie w „Podobnych rekrutacjach” (to przepięcie). Ta sama
  droga co stopka: `proposals.addToJob` / `proposals/bulk` ze źródłem
  `manual_search`. Zaznaczenie i „Dodaj N do Nowych” zostają. Odmowy (zamknięta
  karta, weto HM) mają dotychczasowe komunikaty; weto blokuje też „+ Dodaj”.
- **Dodana osoba zostaje na liście** w swoim miejscu: „Dodano do „Nowych” ·
  rezerwacja 12 h · Cofnij” (okno trzyma kopię wiersza, bo źródła już jej nie
  zwracają — `withKeptRows`). „Cofnij” = `DELETE /api/candidates/{id}/
  recruitments/{job_id}`. Do 15 min od wejścia osoby (najstarszy wiersz etapu)
  serwer oddaje jej propozycję (`added` → `proposed`,
  `job_proposals.reopen_after_quick_undo`), więc wiersz wraca do zwykłego
  stanu; później propozycja zostaje `added`, a pominięta (`dismissed`) — pominięta.
- **Powód w wierszu:** do trzech chipów i „+N” za resztę (tokeny
  `success-muted` / `destructive-muted` / `warning-muted`): „✓ spełnia”,
  „✕ brakuje”, „? zapytaj w rozmowie”, najpierw po jednym z rodzaju
  (`reason-chips.ts`). Chipy stoją pod CAŁYM wierszem (także pod „+ Dodaj”
  i strzałką), najwyżej dwie linie, etykieta do 18 znaków, cała w podpowiedzi
  — obok przycisków w oknie 540 px mieściły 1–3 litery. Propozycje — z `detail.requirements` (bez zapytania),
  „Szukaj w bazie” — z `matching_must` / `gap_must` odpowiedzi `/scores`,
  „zapytaj” — must-have zdaniem (`not_searchable_must`). Jednolinijkowy powód
  (`row.reason`) zostaje.
- Harness: `/preview/job-detail?sources=base|search|manual` — wyniki z zasiewu
  (`/scores` odpowiada lokalnie), po jednej osobie w stanie „Dodano · Cofnij”
  (`initialAddedIds`).

## Nagłówek w trzech cienkich liniach — priorytet, rekruter, „Zwiń” (14.10.2026)

Prośba Artura: brakowało widocznego priorytetu i rekrutera, a przy 1280×720
(menu 240 px) nagłówek 151 px + pasek kandydatów 81 px spychały Tablicę na
323 px. Decyzje K-D1–K-D5, makiety https://claude.ai/artifact/DZWUbWtiQLrnzm81RwLvDP.
Harness `/preview/job-detail`: kolumna „Nowi” na 218 px (0,30 okna), po „Zwiń”
na 145 px; próg w `e2e/responsive-preview.spec.ts` — 0,4.

- **Jedna karta, trzy linie** (`JobDetailCompactHeader`): (1) priorytet, tytuł,
  status | zakładki, obecność, ikona „Historia i czat” (licznik na ikonie,
  nazwa w dymku — K-D4), „⋯”, „Zwiń”; (2) fakty i „Rekruter”; (3) tylko na
  Tablicy i z wczytaną Tablicą: „Kandydaci do dodania” + „Kto dodał” po prawej
  (K-D1). Nowy element w nagłówku nie dostaje własnej linii — najpierw sprawdź
  pomiar na harnessie przy 1280×720.
- **Fakty z ikoną zamiast etykiety** (K-D2): `Building2` / `Wallet` / `MapPin`,
  etykieta jako `sr-only` w `dt` i w dymku faktu. Od `lg` linia się nie zawija:
  pierwsza kurczy się nazwa klienta (najwyżej 15rem), potem tryb pracy, budżet
  nigdy (`FACT_SHRINK`). Niżej linie zawijają się bez poziomego przewijania.
- **Nazwa od klienta i numery** (K-D3): w dymku tytułu (`title` h1: tytuł,
  nowa linia, „U klienta: … · nr u klienta … · nasz nr …”) i jako `sr-only`
  `header-client-line` dla czytnika ekranu (nazwa od klienta i nasz numer).
  **Numer u klienta od 15.10.2026 widać w linii 1** — znacznik
  `ClientReferenceChip` między priorytetem a tytułem, także po „Zwiń”, klik
  kopiuje (decyzja Artura, prośba DL Nordei; reguła numeru w
  `rekrutacja-tworzenie/trzy-nazwy-rekrutacji.md`). Nie dostaje własnej linii.
- **Priorytet** (`JobPriorityMenu`): ta sama krótka plakietka co na liście
  („P1”, „Bez priorytetu”, „Przyjmujemy”) — w nagłówku stoi też „Bez
  priorytetu”. Prawo zmiany = `useJobTeamPermissions` (ta sama reguła co
  zakładka „Zespół”: `can_set_priority` z serwera, inaczej capability); menu
  z trzema poziomami i zdaniem z `PRIORITY_LEVEL_HINT`, zapis od razu przez
  `useJobPriorityChange` (wspólny z polem w panelu „Zespół”). Bez prawa — sama
  plakietka z dymkiem, kto zmienia.
- **„Rekruter”** (`JobRecruiterFact`): reguła `recruitersOf`, zalogowana osoba
  pierwsza jako „Ty”, jeden awatar + „+N” (awatary nie na zakładkę — tło jest
  półprzezroczyste), bursztynowe „Bez rekrutera”, przerywana „propozycja: …”.
  Okienko = `JobOwnershipPanel` (wszystkie akcje zespołu wg roli) + Delivery
  Lead (`delivery_lead_user`) + link do „Profil Championa › Zespół”. Panel
  zgłasza własne okna (`onLayerOpenChange`: potwierdzenie, „Zmień rekrutera”):
  okienko jest wtedy `invisible`, a klik i fokus w `[role=dialog]` go nie
  zamykają — inaczej potwierdzenie znikało razem z panelem.
- **„Zwiń”** (K-D5): sama linia 1 + awatary rekruterów; włączony filtr „Kto
  dodał” zostaje widoczny w linii tytułu. Pamięć per osoba w `localStorage`
  (`lib/job-header-preferences.ts`, klucz `nexus:job-header-collapsed:<id>`,
  domyślnie rozwinięty, poza `clearSessionArtifacts`). Dawny klucz
  `nexus:jobHeaderCollapsed:v3` (do #1899, domyślnie zwinięty) nie wraca.
- Przełącznik widoku Tablicy (tylko > 10 kolumn) rysuje się nad kolumnami sam
  (`KanbanBoardV2` bez `renderAbove`). Harness: `?prio=`, `?team=me|none|proposal`,
  `?client=long`, `?collapsed=1`, `?readonly=1`.

## „Pasuje też do” po „+ Dodaj” i „+1 rekrutacja” na karcie (14.10.2026)

Decyzje Artura D1–D4 z 14.10.2026 (makiety https://claude.ai/artifact/RTUD8nEm1dRXrarnwHrE7f, A1–A2).
Rekruter dodawał osobę do A, a ta sama osoba pasowała do innych rekrutacji — podpowiedź istniała tylko
w profilu („Pasujące rekrutacje”, starszy wzór, bez bramki i progu). Raport: `docs/also-fits-completion-report.md`.

- **Reguła = automaty i „Moi ludzie” (D1).** `GET /api/candidates/{id}/also-fits?from_job_id=A`
  (`api/also_fits.py`, `services/also_fits.py`): pula to rekrutacje `published` + `IN_WORK_STATES`
  w zakresie odczytu patrzącego, bez A i bez rekrutacji, w których osoba ma JAKIKOLWIEK wiersz etapu
  (w toku albo zamknięta karta). Qdrant zawęża pulę do 8 najbliższych (tekst kandydata × wektory
  rekrutacji), każda dostaje `my_people_matching.fits_for_job` — kanoniczny fit, kwalifikowalność
  (weto HM, czarna lista), dowody z CV i notatek i dealbreakery z bramką „Wymagane (krytyczne)”.
  Zostaje najwyżej 3 z wynikiem ≥ 70, zmierzonym (`measurement == "measured"`), nieukrytym
  i dopuszczonym. Procent to ta sama liczba, którą B pokazuje w „Szukaj w bazie”. Awaria Qdranta =
  `status: "unavailable"` → „Nie udało się sprawdzić innych rekrutacji · Ponów”, nigdy pusta lista.
  `score_people_for_job` („Moi ludzie”) woła tę samą `fits_for_job` — jedna ocena, dwa ekrany.
- **Gdzie (A1):** blok pod osobą dodaną w oknie „Kandydaci do dodania” — zakładki propozycji
  i „Szukaj w bazie” (`useAlsoFitsJobs` w `AddCandidatesPanel`/`useSearchBaseTab`, prezentacja
  `also-fits-block.tsx`, pole `PickRow.alsoFits`; `PickList` sam nic nie pobiera). Pusty wynik =
  nic. Okno pyta samo tylko o 3 ostatnio dodane osoby (`ALSO_FITS_AUTO_CHECK`) — stopka dodaje do
  100 naraz, a każde zapytanie to kilka pełnych ocen na serwerze; przy reszcie jest „Sprawdź, gdzie
  jeszcze pasuje”. „Szukaj ręcznie” (od 15.10.2026): dodana osoba znika z wyników (lista ukrywa osoby
  w rekrutacji), więc nad listą stoi pasek „Dodani teraz (N)” (`ManualAddedStrip.tsx`): „Dodano do
  „Nowych” · rezerwacja 12 h · Cofnij” (15 min, `quick_undo`, po cofnięciu osoba wraca do wyników)
  i ten sam blok „Pasuje też do”; widać 3 najnowsze osoby, resztę po „Pokaż wszystkich (N)”. Lista
  osadzona oddaje dodanych przez `embed.onAdded([{ candidateId, fullName }])`.
- **„+ Dodaj” do B (D2)** = zwykłe `POST /api/jobs/{B}/proposals/bulk` ze źródłem `also_fits`
  i `origin_job_id`: „Nowi”, `entry_source="added_manual"`, rezerwacja 12 h dla dodającego, „Cofnij”
  przez 15 min (`DELETE …?quick_undo=true`). Odmowy (zamknięta karta, weto) mówią słowami serwera pod
  rekrutacją. Po zapisie `record_also_fits_added`: wpis `Activity(candidate, also_fits_added,
  {job_id, from_job_id})` i dzwonek `also_fits_added` (kategoria „Kandydaci”, sekcja pipeline,
  migracja 0444 + lustro w `entrypoint.sh`) do rekruterów B (`job_team.recruiters_for_jobs` +
  `working`) — bez osoby, która dodała; encja dzwonka to nowy wiersz etapu pary w B (dedup dzienny
  po osobie zjadałby drugi dzwonek przy „Dodaj do wszystkich”). Dzwonek nigdy nie cofa dodania. Nowe źródło dodania żyje
  w trzech miejscach: `BulkAddSource`, `PIPELINE_ADD_SOURCES`, `BulkAddSource` na froncie.
- **„+N rekrutacja” na karcie (A2):** `other_open_jobs` karty Tablicy (`build_kanban_view`, jedno
  zapytanie na Tablicę tylko o osoby z kart w „Nowych”/„Screeningu”, same tytuły rekrutacji, filtr
  etapów w SQL; `with_other_jobs=False` w „Moich następnych krokach”) = inne niezamknięte
  rekrutacje, w których najnowszy wiersz etapu osoby jest w „Nowych”/„Screeningu” (`board_column_for`),
  najwyżej 5. Chip tylko na kartach w tych kolumnach (`kanban-other-jobs-chip.tsx`); okienko
  wymienia rekrutacje i prowadzi do karty („Otwórz kartę”). „Screening razem” dochodzi w PR 2.
- **Liczenie (D4):** weryfikacja w kilku rekrutacjach liczy się per rekrutacja, jak dotąd.

## Plakietka stawki względem budżetu w wierszu (D3, 19.10.2026)

Rekruter prosił, żeby wyszukiwanie AI „uwzględniało stawkę”. Decyzja D3:
**ocena bez zmian** (stawka nadal NIE daje punktów — `scoring_service`,
bramka `critical` → `_unscored`; pomiar 30.09: stawka w ocenie spychała osoby,
które zespół wysyła), **za to w każdym wierszu okna „Kandydaci do dodania”
widać stawkę względem budżetu rekrutacji**.

- **Jedna reguła** `lib/rate-budget-badge.ts` (`rateBudgetBadge`) dla „Szukaj
  w bazie”, „Propozycji z bazy” i „Nowych z ogłoszeń”: „w budżecie · 140 zł/h”
  (≤ górnej granicy „od–do”, `budzet-rekrutacji-od-do.md`), „+12% ponad budżet
  · 160 zł/h” — `warning-muted` do +15% włącznie, wyżej `destructive-muted`
  (tuż nad progiem z jednym miejscem po przecinku: „+15,1%”). Rekrutacja bez
  budżetu albo inna waluta — sama kwota (`muted`); brak stawki — nic.
- **Stawka = „Stawka od”** (`candidate_rate_from.effective_rate`) — ta sama co
  filtr i bramka: w „Szukaj w bazie” `rate_from_hourly` wiersza `GET
  /api/candidates` (nie `expected_rate_hourly` profilu), w propozycjach
  `expected_rate_hourly` z `proposal-facts`, a do ich wczytania
  `detail.rateHourly`. Obie są PLN/h, więc stawki „nie godzinowej” tu nie ma.
- **Miejsce:** pierwsza w rzędzie chipów pod wierszem (`pick-list.tsx`,
  `pick-row-rate`), nie skraca się i nie liczy do trzech chipów wymagań —
  rząd ma dalej najwyżej dwie linie. Zostaje też przy osobie dodanej
  w oknie (chipy wymagań wtedy znikają).
- **Kwota raz:** goła stawka zniknęła z linii faktów (`proposalFactsLine`,
  linia „Szukaj w bazie”), a w propozycjach plakietka „Oczekuje +N% ponad
  budżet” zostaje tylko wtedy, gdy serwer zgłasza `over_budget`, a liczby
  stawki w wierszu nie ma. Podgląd osoby („Stawka od”) i panel propozycji bez zmian.
- Harness `/preview/job-detail?sources=base|search` (budżet 95): w budżecie,
  równo budżet, +7%, +25%, bez stawki.

## „Propozycje z bazy” domyślnie według dopasowania (D4, 19.10.2026)

Zgłoszenie rekrutera „najpierw najbardziej dopasowani”. Do 19.10 okno startowało
z „Najpierw byli u tego klienta” (osoby z historią u klienta na górze bez względu
na wynik), a osoby z podobnych rekrutacji i rekomendacji bez zapisanego wyniku
stały na końcu, choć po przeliczeniu bywały wyżej.

- Domyślny tryb „Dopasowanie” (`ProposalSortMode = "match"`,
  `proposal-facts.sortByShownScore`): malejąco po pokazanym % — zapisany wynik
  propozycji albo policzony na ekranie (`useVisibleMatchScores`); bez wyniku na
  końcu, remisy stabilnie. „Najpierw byli u tego klienta” zostaje drugą opcją
  przełącznika (gdy ktoś na liście ma historię u klienta); dawny tryb „Kolejność
  propozycji” (przepięcia i praktykant na górze, punkty historii) zniknął
  z przełącznika — `compareProposals` dalej układa listę wejściową.
- W trybie „Dopasowanie” okno zgłasza do liczenia od razu do 100 osób bez wyniku
  (`MATCH_SORT_PRESCORE_MAX`, paczki po 20), nie dopiero po przewinięciu.

## Procent w oknie = tylko ocena NEXUSA, nie wynik scrapera (27.10.2026)

Zgłoszenie Delivery Leada (tester na Fullstacka z 77%, rekrutacja 758736):
okno brało największą z kilku liczb osoby, w tym punktację scrapera portalu
(`job_board`, Pracuj.pl / JJIT, na stagingu 52–78) — inny algorytm w tym
samym fioletowym kolorze, więc jedna osoba miała różne procenty w różnych
miejscach. Rekomendacja 4 z analizy (https://claude.ai/artifact/LCJMGvUagzYvtWapzdw5WL),
zrzuty przed/po: https://claude.ai/artifact/4CADHRfmwXo6UVDPxHRJ7z.

- **Serwer** (`job_proposals.list_for_job`, `GET …/proposal-inbox`): `score` =
  największy wynik źródeł spoza `NON_CANONICAL_SCORE_SOURCES` (dziś tylko
  `job_board`); scraper osobno jako `board_score`. Kolejność stron liczy się
  dalej z największego wyniku dowolnego źródła (`rank_score`), żeby zmiana nie
  przestawiła, kto trafia na stronę.
- **Okno:** osoba bez kanonicznego wyniku (sama `job_board`) idzie przez
  `useVisibleMatchScores` (`POST /api/search/candidates/scores`) jak podobne
  rekrutacje; ten procent wiersz niesie też do kolejności „Dopasowanie”
  i do przekreślonego procentu przy „Inna rola”. Wynik scrapera stoi wyłącznie
  w dymku procentu („portal ogłoszeń ocenił na N% (inny algorytm, nie
  porównuj)”), nigdy jako liczba w wierszu. Nowe źródło z własną skalą =
  dopisek do `NON_CANONICAL_SCORE_SOURCES`, nie do `scores` w `proposals-merge`.
