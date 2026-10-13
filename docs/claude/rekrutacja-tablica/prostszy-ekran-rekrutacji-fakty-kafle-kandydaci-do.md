# Prostszy ekran rekrutacji — fakty, kafle „Kandydaci do dodania”, kolumna „Zamknięci” (02.10.2026)

Decyzje Artura 02.10.2026 („znowu za dużo się dzieje”), makieta wariant B:
https://claude.ai/artifact/ASHNaTXA9omvTH393cQjCv. Zastępuje ścieżkę
rekrutacji i pasek filtrów z 24.09 oraz blok propozycji w „Nowych” z 22.09.

- **Nagłówek = tytuł + status, linia z nazwą i numerem od klienta, trzy fakty:
  Klient · Budżet · Tryb pracy** (`lib/job-header-facts.ts`, brak wartości =
  „nie podano”). Po prawej tylko „Tablica | Profil Championa”, „Historia
  i czat” i „⋯”. Nie ma liczników, ścieżki „Zlecenie → … → Umowa”,
  „Najbliższego kroku” ani podtytułu.
- **Nic nie znika — schodzi do menu „⋯”** (`JobDetailCompactHeader`): „Oznacz:
  mamy championa”, „Dodaj po nazwisku”, „Dodaj z pliku CV”, „Przeszukaj całą
  bazę (AI)”, „Moi ludzie do tej rekrutacji” (otwiera panel „Moi ludzie”),
  „Zlecenie — skrót”, „Zespół” (z „Rekruter: X +N”), „Baza pytań”, „Ukryj /
  Pokaż puste kolumny” + dotychczasowe pozycje. Nowa akcja zdjęta z widoku =
  pozycja w tym menu i wpis w `recruitment-feature-inventory.json`. Kotwica
  pomocy `job.champion.found` stoi na przycisku menu (pozycji zamkniętego menu
  nie ma w DOM).
- **Pasek „Kandydaci do dodania” nad Tablicą = cztery kafle**
  (`CandidateSourcesStrip`, wstawiany przez `KanbanBoardV2.renderAbove`):
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
  zostają). **„Zamknięci” to wąska kolumna obok Tablicy** (`board-closed-column`,
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
