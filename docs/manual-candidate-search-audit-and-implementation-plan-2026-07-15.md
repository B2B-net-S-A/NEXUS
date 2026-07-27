# Manualne wyszukiwanie kandydatów — audyt i plan implementacji

> Data audytu: 2026-07-15
>
> Status dokumentu: propozycja do realizacji; implementacja nie została
> rozpoczęta
>
> Tryb audytu: read-only, bez zmian danych produkcyjnych
>
> Baseline produkcyjny: `4ba716904ec553800f9ae7d08a20c529a402063f` (`origin/main`)

## 1. Executive summary

NEXUS ma już większość elementów potrzebnych do dobrego sourcingu:

- bazę ponad 54 tys. kandydatów,
- rozbudowane filtry na globalnej liście,
- wyszukiwanie pełnotekstowe i semantyczne,
- zapisane wyszukiwania i alerty,
- rekomendowane strategie z Profilu Championa,
- scoring z częściowym breakdownem,
- porównanie kandydatów,
- masowe dodawanie do rekrutacji.

Problemem nie jest brak pojedynczej funkcji. Problemem jest to, że te elementy
działają jako kilka niespójnych produktów, korzystają z różnych kontraktów i
inaczej interpretują te same dane.

W obecnym stanie manualne wyszukiwanie nie powinno być traktowane jako w pełni
wiarygodna odpowiedź na pytanie „kto najlepiej pasuje do requestu klienta”,
ponieważ:

1. część poprawnych kandydatów może zostać wyeliminowana przez błędne jednostki
   stawki i niepoprawne mapowanie lokalizacji,
2. filtrowanie skills nie korzysta konsekwentnie ze wszystkich źródeł danych,
3. kilka silników może zwracać różne listy dla tego samego requestu,
4. wyniki nie pokazują realnego score ani dowodów dopasowania,
5. rekruter przechodzi prawie bezpośrednio z wyników do pipeline'u, bez
   request-specific shortlisty i sensownego porównania.

### Główna rekomendacja

Nie budować kolejnej wyszukiwarki ani nie zaczynać od tuningu AI. Należy:

1. naprawić błędy poprawności P0,
2. wprowadzić jeden wersjonowany kontrakt wyszukiwania,
3. wykorzystać globalną listę kandydatów jako wspólny **Recruiter Search
   Workspace**,
4. połączyć retrieval, eligibility i scoring w jeden pipeline,
5. dodać wyjaśnialne wyniki, shortlistę stanowiska i request-aware compare,
6. dopiero potem optymalizować modele i ranking.

## 2. Podstawa audytu

Audyt objął:

- rzeczywisty flow rekrutera w produkcyjnym UI,
- zakładkę `Wyszukaj manualnie` w rekrutacji,
- globalną listę `/candidates`,
- `AI Matching`, rekomendacje oraz Profil Championa,
- frontendowe mapowanie requestu na filtry,
- backendowe filtry strukturalne, FTS, hybrid search i scoring,
- saved searches, bulk add, porównanie i testy,
- healthcheck produkcji.

Produkcja zwracała zdrowy overall status oraz wersję zgodną z `origin/main`.
Check Traffit miał stan `degraded`, dlatego aktualność danych importowanych z
Traffita należy traktować jako osobny warunek gotowości operacyjnej.

Lokalny checkout był brudny oraz `ahead 2 / behind 18`. Wnioski nie były oparte
na lokalnym WIP, lecz na produkcji i snapshotcie `origin/main` dla SHA powyżej.

## 3. Jak działa wyszukiwanie obecnie

### 3.1. Flow z poziomu rekrutacji

1. Rekruter otwiera rekrutację i zakładkę `Wyszukaj manualnie`.
2. Frontend buduje `CandidateSearchRequest` z:
   - pełnego tytułu joba,
   - kategorii kompetencyjnej,
   - wszystkich `must_skills`,
   - co najmniej jednego `nice_skill`,
   - widełek,
   - całego pola lokalizacji.
3. Domyślnie uruchamiany jest tryb boolean/FTS; rekruter może przełączyć go na
   wyszukiwanie semantyczne.
4. Wszystkie filtry strukturalne są łączone jako warunki obowiązkowe.
5. Rekruter zaznacza wyniki i dodaje je zbiorczo bezpośrednio do rekrutacji.

Prefill jest zaimplementowany w
[jobowym prefillu wyszukiwania](../frontend/src/app/jobs/%5Bid%5D/page.tsx#L1517).

### 3.2. Równoległe powierzchnie

Obecnie występują co najmniej cztery różne doświadczenia sourcingowe:

1. globalna lista `/candidates`,
2. `CandidateSearchView` używany w jobie i `/candidates/search`,
3. `AI Matching` / legacy matches,
4. rekomendacje i strategie Profilu Championa.

Dodatkowo marketplace ma własne ścieżki candidate-to-job matching. Każda z tych
powierzchni częściowo powiela logikę zapytania, retrievalu, scoringu lub zapisu
filtrów.

### 3.3. Obserwacja z produkcji

Dla rzeczywistego requestu `Data Engineer MID lub SENIOR (ZOB-2846)`:

- domyślne wyszukiwanie manualne zwróciło `0` wyników,
- po przełączeniu na semantyczne pojawiło się `199` wyników,
- legacy AI Matching pokazywał `89` kandydatów,
- podgląd kryteriów jednocześnie pokazywał `0 must-have` i `0 nice-to-have`,
- w wynikach pojawiały się prawdopodobne duplikaty tej samej osoby pod różnymi
  ID.

Tak duży rozjazd nie jest tylko problemem UX. Rekruter nie może ustalić, która
lista jest źródłem prawdy i dlaczego konkretna osoba znalazła się wyżej od
innej.

## 4. Mocne strony, które należy zachować

1. Globalna lista ma szeroki zestaw filtrów, logiczne grupy AND/OR/NOT, kolumny,
   URL state, eksport, porównanie i bulk actions.
2. Istnieją wydajne ścieżki FTS i highlight/snippets opisane w
   [raporcie candidate search FTS](./candidate-search-fts-completion-report.md).
3. Saved searches mają współdzielenie, przypięcie do joba i alerty nowych
   kandydatów; zobacz
   [saved-search alerts](./saved-search-alerts-completion-report.md).
4. Profil Championa potrafi już wygenerować 2–3 strategie wyszukiwania, policzyć
   wyniki i zapisać zatwierdzoną strategię dla zespołu; zobacz
   [Champion Profile Workflow](./champion-workflow-completion-report.md).
5. Scoring ma istniejące elementy breakdownu, snippets i powodów, które można
   wykorzystać zamiast budować explainability od zera.
6. Bulk API obsługuje bardziej rozbudowane dane niż obecny jobowy UI faktycznie
   wysyła.
7. Cortex ma już model faktów `candidate × canonical skill × source` z
   confidence i evidence. Należy go naprawić oraz wykorzystać jako wspólną
   warstwę faktów, zgodnie z
   [Cortex discovery](./cortex/00-discovery.md), zamiast tworzyć następny magazyn
   skills.

## 5. Findings i rekomendacje

### SEARCH-P0-01 — stawka godzinowa jest porównywana z miesięczną

Formularz joba opisuje `salary_min` i `salary_max` jako `PLN/h`:
[`AppShell.tsx`](../frontend/src/components/AppShell.tsx#L1102).

Jednocześnie [model `Job`](../backend/app/models/job.py#L78) i
[prep kit](../backend/app/api/prep_kit.py#L121) opisują te same pola jako
miesięczne.
Manual search przekazuje je jako `salary_min/max`, a backend porównuje je z
`Candidate.salary_expectation`, czyli oczekiwaniem miesięcznym:

- [`structured_candidate_search.py`](../backend/app/services/structured_candidate_search.py#L171),
- [`candidate.py`](../backend/app/models/candidate.py#L91).

**Skutek:** request `90–150 PLN/h` może szukać kandydatów oczekujących
`90–150 PLN/mies.`, eliminując praktycznie całą właściwą bazę.

**Rekomendacja:** w nowym kontrakcie wynagrodzenie musi zawsze zawierać
`amount_min`, `amount_max`, `currency`, `unit` oraz znaczenie biznesowe kwoty
(np. budżet na kandydata albo sell rate klienta). Obecne porównanie z wartością
miesięczną należy usunąć natychmiast. Twardy filtr godzinowy można włączyć
dopiero po potwierdzeniu znaczenia pola:

- jeśli to maksymalny budżet na kandydata, `expected_rate_hourly <= max` jest
  warunkiem, ale oczekiwanie poniżej `min` nie powinno automatycznie wykluczać,
- jeśli to sell rate klienta, nie wolno porównywać go bezpośrednio z oczekiwaniem
  kandydata,
- brak stawki jest `unknown` i podlega jawnej polityce strict/lenient,
- inna waluta nie jest przeliczana bez wersjonowanego źródła FX i daty kursu.

Przed migracją trzeba wykonać audyt istniejących rekordów `Job.salary_min/max`
i ustalić, które przechowują kwoty miesięczne, godzinowe lub sell rate. Backfill
nie może opierać się wyłącznie na nazwie pola albo etykiecie aktualnego UI.

### SEARCH-P0-02 — lokalizacja i remote policy są mapowane błędnie

Job ma tekstową lokalizację z placeholderem `Warszawa / Remote` oraz osobne pole
`remote_policy`. Manual search ignoruje `remote_policy` i przekazuje całe pole
lokalizacji jako jeden `location_city`. Backend wykonuje substring lookup dla
całego ciągu.

Istnieje też rozjazd enum: [frontend](../frontend/src/components/AppShell.tsx#L1093)
wysyła `on_site` i `flexible`, podczas gdy
[backendowy model](../backend/app/models/job.py#L13) przyjmuje `onsite`,
`hybrid`, `remote`. `flexible` nie ma jednoznacznego odpowiednika.

**Skutek:** kandydat z miastem `Warszawa` może nie przejść filtra
`Warszawa / Remote`; kandydat otwarty na remote może zostać pominięty.

**Rekomendacja:** adapter job → search powinien osobno mapować:

- miasta,
- kraje,
- akceptowany tryb pracy,
- promień lub zasady hybrydy,
- opcję „brak danych” w trybie strict/lenient.

Docelowo job powinien przechowywać te wartości strukturalnie. Parser tekstu
`Warszawa / Remote` jest tylko migracyjnym fallbackiem. Potrzebna jest jawna
macierz zgodności job mode × candidate preference obejmująca onsite, hybrid,
remote, kilka miast, promień dojazdu oraz `unknown`; nie należy zakładać
prostego OR dla każdego użycia znaku `/`.

Containment musi dodać adapter `on_site` ↔ `onsite` oraz decyzję biznesową i
migrację dla `flexible`; nowe zapisy nie mogą utrwalać niekanonicznego enum.

### SEARCH-P0-03 — skills nie mają jednego źródła prawdy

Manualny filtr korzysta z tekstowego `skills + tags` i dopasowania substring:
[`structured_candidate_search.py`](../backend/app/services/structured_candidate_search.py#L47).

Scoring ma osobne fallbacki do `verified_tech`, danych Traffit, CV i innych pól.
W efekcie kandydat może być wysoko oceniony przez scoring, ale wcześniej nie
wejść do zbioru wynikowego. Substring generuje też fałszywe trafienia, np. `go`
w dłuższym słowie.

**Rekomendacja:** naprawić i rozszerzyć istniejący fact store Cortexa
(`cortex_skill_facts`, `skills`, `skill_aliases`) zamiast tworzyć kolejną,
równoległą tabelę. Docelowy magazyn powinien zapewniać:

- kanoniczny `normalized_key`,
- jednoznaczne aliasy,
- źródło i confidence,
- dowód/provenance,
- exact-token matching.

Ten sam resolver musi zasilać search, scoring, snippets i indeks semantyczny.
Przed użyciem Cortexa w ścieżce krytycznej trzeba domknąć reconcile, kolizje
taksonomii i automatyczny incremental sync.

### SEARCH-P0-04 — eligibility nie jest jedną polityką

Search może pokazać blacklistowaną osobę jak zwykły wynik. Bulk add odrzuca
część przypadków dopiero po kliknięciu, ale nie wszystkie ścieżki przypisania
stosują spójną interpretację:

- aktywnego konfliktu,
- daty wygaśnięcia konfliktu,
- wykluczonego klienta,
- duplikatu w jobie,
- aktywnego procesu,
- nieznanej dostępności.

**Rekomendacja:** utworzyć jeden serwis `candidate_job_eligibility`, używany
przez search, recommendations i każdy endpoint przypisania. Polityka musi
rozróżniać:

1. niewidoczny hard block, którego nie można obejść,
2. widoczny wynik z ostrzeżeniem,
3. wynik widoczny w searchu, ale blokowany dopiero przy przypisaniu,
4. blokadę z audytowanym override dla wskazanych ról.

Wynik powinien zawierać `eligible`, `visibility`, `assignment_allowed`,
`severity`, `reason_code`, opis, `override_allowed` i wymagane uzasadnienie.

### SEARCH-P0-05 — dwa niekompatybilne formaty saved search

Globalna lista zapisuje wersjonowany payload `{version, qs, api}`, natomiast
`CandidateSearchView` zapisuje surowy `CandidateSearchRequest`. Oba rekordy są
zwracane jako `entity="candidates"`.

**Skutek:** search zapisany w jednym widoku może otworzyć się jako pusty lub
domyślny w drugim; alert może wykonywać inną semantykę niż ręczne otwarcie.

**Rekomendacja:** jeden `CandidateSearchQueryV3`, migracja starych payloadów,
adaptery tylko na granicach kompatybilności i przechowanie oryginalnego payloadu
na czas rollbacku.

### SEARCH-P1-01 — request jest zamieniany w zbyt ubogie i zbyt twarde zapytanie

Prefill pomija m.in.:

- opis i wymagania,
- seniority,
- języki,
- remote policy,
- datę rozpoczęcia,
- okres wypowiedzenia,
- historię i wykluczenia klienta.

Jednocześnie `nice_skills` stają się twardym warunkiem „co najmniej jeden”, a
pełny tytuł wraz z numerem referencyjnym trafia do query.

**Rekomendacja:** parser requestu powinien wytworzyć trzy jawne grupy:

1. `hard_filters`,
2. `soft_preferences` z wagami,
3. `exclude`.

System powinien automatycznie pokazać edytowalny preview interpretacji.
Dodatkowe potwierdzenie jest wymagane tylko dla kryteriów o niskim confidence,
sprzecznych sygnałów albo zmiany hard constraint. Istniejące
`ChampionRecommendedSearches` należy przenieść do tego samego workspace'u jako
strategie, a nie utrzymywać jako osobną wyspę.

### SEARCH-P1-02 — hybrid search filtruje dopiero po globalnym top 200

Semantyczna ścieżka pobiera globalny pool 200 kandydatów, a następnie nakłada na
niego filtry strukturalne:
[`search.py`](../backend/app/api/search.py#L152).

**Skutek:** dobry kandydat spoza top 200 nie pojawi się po zawężeniu filtrów, a
`total` nie reprezentuje całej bazy spełniającej kryteria.

**Rekomendacja:** filter-first retrieval albo metadane/pre-filtry w Qdrant,
następnie lexical + dense retrieval w tej samej kohorcie, RRF i jeden scoring.

### SEARCH-P1-03 — wynik nie wyjaśnia dopasowania

Backend ustawia `relevance_score=0.0`:
[`search.py`](../backend/app/api/search.py#L223), a wiersz wyniku go nie pokazuje:
[`CandidateSearchView.tsx`](../frontend/src/components/v2/pages/CandidateSearchView.tsx#L512).

Brakuje:

- pokrycia must-have,
- niespełnionych i niepotwierdzonych kryteriów,
- źródłowych fragmentów CV,
- confidence i świeżości danych,
- historii procesów i ostatniego kontaktu,
- powodów blokady lub ostrzeżenia.

**Rekomendacja:** response wyszukiwania powinien zawierać deterministyczny
`request_fit_score`, składniki wyniku, snippets, gaps, unknowns, confidence i
eligibility. Skala 0–100 jest indeksem rankingowym w obrębie jednego joba i
strategii, a nie prawdopodobieństwem zatrudnienia. Nie wolno porównywać score
między różnymi jobami lub strategiami bez osobnej kalibracji. Brak informacji
ma być oznaczony jako `unknown`, nie automatycznie jako „spełnia” lub „nie
spełnia”. UI powinien eksponować dowody i confidence co najmniej równie mocno
jak samą liczbę.

### SEARCH-P1-04 — brak diagnostyki zerowych wyników

Empty state mówi tylko „zmień filtry lub poszerz query”. Rekruter nie wie, czy
zero wyników spowodowała stawka, lokalizacja, must skill, dostępność czy błąd
danych.

**Rekomendacja:** dodać exclusion waterfall i kontrolowane sugestie
poluzowania:

```text
54 061 aktywnych profili
→ 8 420 po kategorii
→ 2 110 po must skills
→ 310 po lokalizacji/remote
→ 0 po stawce godzinowej
```

System powinien pokazać efekt poluzowania bez automatycznej zmiany kryteriów.
Sugestie nigdy nie mogą wyłączać blacklisty, prawnego hard blocka ani konfliktu
klienta. Każda propozycja pokazuje dokładnie zmienione kryterium, prognozowaną
liczbę wyników, oznaczenie wartości przybliżonej i możliwość undo.

### SEARCH-P1-05 — brak shortlisty powiązanej z requestem

Kandydat trafia praktycznie bezpośrednio z wyszukiwania do pipeline'u. Globalne
piny nie są substytutem shortlisty: nie mają job context, statusu decyzji,
właściciela ani powodu.

**Rekomendacja:** wprowadzić shortlistę joba z dwoma niezależnymi wymiarami:

- `evaluation_status`: `do_oceny`, `potencjalny`, `zatwierdzony`, `odrzucony`,
- `outreach_status`: `nie_kontaktowano`, `do_kontaktu`, `kontakt_w_toku`,
  `zainteresowany`, `brak_zainteresowania`.

Każdy wpis powinien mieć właściciela, notatkę, reason code, następny krok i
audit trail. Dopiero zatwierdzeni kandydaci trafiają zbiorczo do pipeline'u.
Przed wyborem modelu danych potrzebny jest krótki ADR: osobny byt pre-pipeline
kontra rozszerzenie istniejącego `Proposal`. Konwersja shortlista → proposal
musi być idempotentna i zachowywać historię.

### SEARCH-P1-06 — compare mierzy kompletność, nie dopasowanie

Globalne porównanie oblicza własny wynik kompletności profilu i nie przyjmuje
`job_id`.

**Rekomendacja:** request-aware compare powinien pokazywać macierz
`kandydat × wymaganie`, dowód, brak/unknown, stawkę, dostępność, historię klienta
i ryzyka. Wynik kompletności profilu może pozostać osobnym wskaźnikiem jakości
danych, ale nie może wyglądać jak match score.

### SEARCH-P1-07 — indeks semantyczny nie ma mierzalnego lifecycle

Nie wszystkie ścieżki create/update/import/enrichment gwarantują reindeksację.
Brakuje fingerprintu treści, wersji modelu i wiarygodnej metryki pokrycia DB ↔
Qdrant. Fallback między modelami o tym samym wymiarze nie gwarantuje zgodnej
przestrzeni wektorowej.

**Rekomendacja:** outbox indeksowania, wersjonowane kolekcje per model,
`content_fingerprint`, `indexed_at`, coverage/freshness oraz lexical fallback w
stanie degraded zamiast mieszania embeddingów z różnych modeli.

### SEARCH-P2-01 — problemy UX i test coverage

Dodatkowe problemy:

- wcześniejsza odpowiedź HTTP może nadpisać nowsze wyniki przy szybkim
  zmienianiu filtrów,
- zaznaczenia mogą pozostać po zmianie kryteriów,
- stan jobowego searcha nie jest w pełni trwały i udostępnialny przez URL,
- bulk add nie wykorzystuje etapu, notatki i tagów wspieranych przez API,
- część pól filtrów ma słabe etykiety dostępności,
- E2E nie chroni jednostek stawki, mapowania lokalizacji, score, shortlisty ani
  rzeczywistego bulk add.

## 6. Docelowy workflow rekrutera

```text
Request klienta
    ↓
Interpretacja briefu: hard / soft / exclude / unknown
    ↓
Strategia: ścisła / zbalansowana / profile sąsiednie
    ↓
Filter-first lexical + semantic retrieval
    ↓
Job-specific request-fit index + confidence + eligibility + dowody + braki
    ↓
Shortlista stanowiska
    ↓
Request-aware compare i kontakt
    ↓
Zatwierdzenie do pipeline'u
```

### 6.1. Recruiter Search Workspace

Główne CTA w jobie powinno nazywać się `Znajdź kandydatów` i otwierać wspólny
workspace oparty na globalnej liście, z kontekstem `job_id`.

Workspace zawiera:

1. panel interpretacji requestu,
2. strategie wyszukiwania,
3. filtry i exclusion waterfall,
4. listę wyników z quick view,
5. panel zaznaczonych kandydatów,
6. shortlistę i porównanie,
7. saved search, share i alerty.

Nie należy osadzać całego obecnego `CandidatesListV2` jako kolejnego monolitu.
Najpierw trzeba wydzielić współdzielone moduły: query state, URL codec, filter
model, results table, selection, quick view i bulk actions. Widok globalny oraz
jobowy składają się następnie z tych samych modułów.

`Dodaj kandydata` może pozostać prostym lookupem znanej osoby. Nie powinien być
alternatywną wyszukiwarką sourcingową.

### 6.2. Kontrakt `CandidateSearchQueryV3`

Docelowy kontrakt powinien być wersjonowany i jawnie rozdzielać intencję:

```json
{
  "version": 3,
  "context": {
    "job_id": 123,
    "strategy": {"key": "balanced", "version": 1}
  },
  "query": {
    "text": "data engineer",
    "all": [],
    "any_groups": [],
    "none": []
  },
  "retrieval": {"mode": "hybrid", "rerank": true},
  "hard_filters": {
    "skills": {
      "all": [{
        "key": "java",
        "min_level": null,
        "min_years": null,
        "recency": null,
        "accepted_sources": []
      }],
      "any": [],
      "none": []
    },
    "locations": [],
    "work_modes": [],
    "rate": {
      "min": null,
      "max": null,
      "currency": "PLN",
      "unit": "hour",
      "meaning": "candidate_budget"
    },
    "availability": {"mode": "lenient"},
    "languages": []
  },
  "soft_preferences": [
    {"type": "skill", "key": "aws", "weight": 0.3, "evidence_required": true}
  ],
  "exclude": {"all": [], "any": [], "none": []},
  "sort": {"field": "request_fit", "direction": "desc"},
  "page": {"size": 50, "cursor": null},
  "facets": ["skills", "locations", "availability"]
}
```

To jest przykład kierunku kontraktu, nie gotowy schemat implementacyjny.
Ostateczny model powinien być typowanym AST obsługującym free text,
`all/any/none`, poziom, lata, recency, provenance, wagi, retrieval mode,
paginację i facety. Strategia musi mieć wersję albo zapisywać rozwinięte
kryteria, aby alert nie zmieniał znaczenia po późniejszej zmianie wag. Kontrakt
powinien powstać jako Pydantic schema z wygenerowanym typem TypeScript lub być
sprawdzany dwustronnymi testami kontraktowymi.

### 6.3. Docelowy pipeline backendowy

```text
Search DSL validation
→ non-overridable visibility blocks
→ canonical skill/location/language filters
→ lexical + dense retrieval w tej samej kohorcie
→ RRF/rerank
→ jeden deterministyczny job-context request-fit index
→ warnings i assignment eligibility
→ stable cursor (query hash, scoring/index version, sort-specific seek tuple)
→ explanations, snippets, unknowns i warnings
```

Hard visibility blocks można prefilterować. Ostrzeżenia i reguły zależne od
pełnego kontekstu są oceniane po retrievalu, a każdy zapis do joba ponownie
waliduje eligibility transakcyjnie. Dla globalnego searcha bez `job_id` istnieje
`retrieval_score`; `request_fit_score` jest dostępny tylko w kontekście joba.
`data_confidence` pozostaje osobnym wymiarem.

## 7. Plan implementacji

### Zasada realizacji

Najpierw poprawność kontraktów, następnie konsolidacja powierzchni, później
normalizacja danych i scoring, na końcu shortlista oraz migracja legacy.
Rozbudowywanie obecnego równoległego `CandidateSearchView` przed zakończeniem
Fazy 1–2 zwiększy koszt migracji.

### Faza 0 — baseline, golden dataset i kontrakty

**Cel:** zmierzyć obecny stan i zabezpieczyć semantykę przed zmianą silnika.

#### Zakres

- rozpocząć od 15–30 reprezentatywnych requestów, a przed użyciem jako gate
  rozszerzyć zbiór warstwowo po kategorii, seniority, źródle danych i poziomie
  braków,
- dla każdego oznaczyć oczekiwanych kandydatów i powody,
- uwzględnić: importowanego kandydata, alias skilla, nieznaną dostępność,
  języki, konflikt klienta, blacklistę, remote, stawkę godzinową i hard
  negatives,
- użyć co najmniej dwóch niezależnych oceniających oraz adjudykacji rozbieżnych
  przypadków,
- dodać `backend/scripts/eval_candidate_search.py`,
- zmierzyć:
  - recall@20 i recall@50,
  - overlap obecnych silników,
  - zero-result rate,
  - p50/p95 latency,
  - pokrycie i świeżość Qdrant,
  - duplicate rate.

#### Pliki/moduły

- `backend/app/schemas/candidate_search.py`,
- `backend/app/api/search.py`,
- nowy `backend/scripts/eval_candidate_search.py`,
- syntetyczny fixture/golden dataset bez danych osobowych w repo dla CI,
- chroniony, pseudonimizowany eval na danych produkcyjnych poza repo, z RBAC,
  retencją i audytem dostępu.

#### Kryteria akceptacji

- baseline jest powtarzalny,
- każdy golden case ma uzasadnienie oczekiwanego wyniku,
- przed uczynieniem evala gate'em ustalono progi recall/precision per segment,
- metryki można porównać przed i po każdym kolejnym PR,
- dataset w Git nie zawiera danych osobowych ani treści CV,
- produkcyjny eval nie eksportuje danych poza autoryzowane środowisko.

### Faza 1 — correctness containment P0

**Cel:** usunąć błędy eliminujące poprawnych kandydatów bez oczekiwania na pełną
przebudowę silnika.

#### Backend

- zinwentaryzować semantykę istniejących `Job.salary_min/max`, usunąć błędne
  porównanie miesięczne ↔ godzinowe i dodać jawny unit/meaning,
- poprawić mapowanie i filtrowanie city/country/work mode, w tym
  `on_site`/`onsite` i decyzję dla `flexible`,
- dodać tymczasowy wspólny skill resolver dla search i scoringu, korzystający z
  obecnych źródeł i exact-token/alias matching; zastąpi go/zasili utwardzony
  Cortex z Fazy 3,
- naprawić powiązanie kodu języka z poziomem,
- wprowadzić `candidate_job_eligibility`,
- stosować eligibility w search, bulk add i quick assign,
- zwracać dokładne per-candidate skip reasons,
- wprowadzić kompatybilny reader obu obecnych formatów saved search; zapis do
  V3 i migracja nastąpią w Fazie 2.

#### Frontend

- poprawić job → search prefill,
- usunąć numer referencyjny z query,
- mapować `nice_skills` jako preferencje, nie hard gate,
- pokazywać lub domyślnie wykluczać blacklistę,
- anulować stale requesty,
- czyścić/uzgadniać zaznaczenia po zmianie wyników,
- pokazywać dokładne przyczyny pominięcia w bulk add.

#### Testy wymagane

- job `90–150 PLN/h` nie dotyka pola miesięcznego; po potwierdzeniu semantyki
  budżetu kandydat oczekujący `80 PLN/h` nie jest odrzucony tylko dlatego, że
  jest poniżej minimum, a `160 PLN/h` przekracza twardy max,
- brak stawki pozostaje `unknown`, a inna waluta nie jest automatycznie
  przeliczana,
- macierz city/work mode poprawnie obsługuje kilka miast, onsite, hybrid,
  remote, promień i `unknown`,
- `Go` nie pasuje do `Django`,
- `EN:A2 + DE:B2` nie spełnia `EN>=B2`,
- aktywny hard conflict blokuje search i każdy endpoint przypisania,
- wygasły konflikt nie blokuje,
- brak dostępności zachowuje się inaczej w strict i lenient,
- starsza odpowiedź API nie nadpisuje nowszej,
- ukryty po zmianie filtrów kandydat nie pozostaje zaznaczony,
- numer referencyjny nie trafia do query, a `nice_skills` nie są hard gate,
- pusty lub niepełny brief nie tworzy przypadkowego pustego hard filtra,
- saved search daje ten sam predicate dla tego samego snapshotu w obu
  widokach.

#### Kryteria akceptacji

- wszystkie powyższe testy są zielone w hosted CI,
- nie ma ścieżki przypisania omijającej eligibility,
- bieżące saved searches pozostają odtwarzalne,
- produkcyjny smoke dla godzinowej stawki i remote jest poprawny.

### Faza 2 — jeden Search DSL i wspólny Recruiter Search Workspace

**Cel:** usunąć dwa niezależne produkty manualnego wyszukiwania.

#### Backend

- wprowadzić `CandidateSearchQueryV3`,
- zachować `/api/search/candidates` jako compatibility facade,
- dodać adapter GET `/api/candidates` ↔ V3,
- wersjonować payloady saved search,
- dodać `saved_searches.dsl_version` i zachować oryginalny payload na czas
  migracji/rollbacku,
- dodać kolumny addytywnie przez migrację od aktualnych heads i idempotentny
  safety-net w `backend/entrypoint.sh`,
- migrować legacy payloady przy odczycie, a następnie backfillem,
- zachować alertowe watermarki `last_scanned_at`/`last_seen_candidate_id` i
  dedup log; zmiana DSL/normalizera wymaga kontrolowanego re-baseline bez alert
  stormu,
- zmiana faktu wpływającego na search musi emitować event/generation watermark,
  nawet jeśli nie zmienia `Candidate.updated_at`,
- zapewnić wspólne URL/query encoding.

#### Frontend

- wydzielić z `CandidatesListV2` współdzielone moduły query state, URL codec,
  filtrów, tabeli wyników, selection i bulk actions,
- dodać `job_id`, `search_id` i strategię do URL state,
- przenieść istniejące filtry, quick view, kolumny i bulk actions,
- osadzić `ChampionRecommendedSearches` w panelu interpretacji requestu,
- zredukować `CandidateSearchView` do wrappera kompatybilności lub go wygasić,
- rozdzielić proste `Dodaj kandydata` od pełnego `Znajdź kandydatów`.

#### Elementy do reuse

- `CandidatesListV2`,
- `SavedSearchesMenu`,
- `candidate-saved-search.ts`,
- `CandidateQuickView`,
- `ChampionRecommendedSearches`,
- istniejące filtry firmy, roli, klienta, procesu, aktywności i stawki,
- `POST /api/jobs/{job_id}/proposals/bulk`.

#### Kryteria akceptacji

- refresh zachowuje job, strategię, filtry, sort i wybrany saved search, ale nie
  przywraca ulotnych checkboxów kandydatów; trwałym wyborem jest shortlista,
- link można udostępnić innemu uprawnionemu rekruterowi,
- osoba bez uprawnienia do joba/searcha otrzymuje kontrolowane 403/404 bez PII i
  liczników wyników,
- ten sam filtr ma identyczną semantykę globalnie i w jobie,
- istnieje jeden format saved search,
- alert i ręczne otwarcie stosują ten sam predicate/DSL dla tego samego
  kandydata i snapshotu; alert może dodatkowo używać delta watermark i dedup,
- uszkodzony lub nieobsługiwany saved-search payload pokazuje błąd i opcję
  naprawy; nigdy nie otwiera po cichu filtrów domyślnych,
- testy obejmują shared link, usunięty job, utratę uprawnień i alert.

### Faza 3 — kanoniczne fakty, eligibility i niezawodny indeks

**Cel:** usunąć `CAST(JSONB AS TEXT)` jako podstawę filtrowania i sprawić, żeby
indeks semantyczny był kompletny oraz mierzalny.

#### Migracje i modele

1. Naprawa i rozszerzenie istniejących `skills`, `skill_aliases` oraz
   `cortex_skill_facts`:
   - jednoznaczny `normalized_key` i oddzielny `display_name`,
   - deterministyczne aliasy bez case-insensitive collisions,
   - `source`, `confidence`, status weryfikacji i evidence/provenance,
   - `normalizer_version` i `source_content_hash`,
   - reconcile faktów nieobecnych już w źródle,
   - FK z `ON DELETE CASCADE`, jednoznaczna unique rule oraz indeksy po
     kandydacie, skillu i źródle,
   - raport failed rows i coverage względem każdego konkretnego źródła.
2. Opcjonalne `candidate_language_facts`, jeśli JSONB nie zapewni poprawnej i
   wydajnej semantyki.
3. Kanoniczny normalizer `city/country/work_modes` i idempotentny backfill
   istniejących rekordów; osobny fact model tylko jeśli obecne pola nie
   wystarczą do zachowania provenance.
4. `candidate_search_index_state`.
5. `candidate_search_index_outbox`.

Każda tabela i kolumna musi mieć idempotentny safety-net w
`backend/entrypoint.sh`, zgodnie z migration trap NEXUS. Migracje uruchamiamy
przez `alembic upgrade heads`. Rewizja musi wychodzić z aktualnych wszystkich
heads albo zostać poprzedzona merge revision.

Alembic i `_COLUMN_STATEMENTS` tworzą wyłącznie addytywny schemat. Ekstrakcja
CV, reconcile 54 tys. kandydatów i budowa embeddingów nie mogą działać w
entrypoincie. Wykonuje je osobny, resumowalny worker/admin job z checkpointem,
statusem, limitem batcha i kill-switchem.

#### Backfill

- etap 1: `skills`, `verified_tech`, Traffit i tags,
- etap 2: bounded extraction z CV,
- checkpointy i idempotentny upsert,
- dual-read podczas backfillu,
- reconcile, nie tylko append,
- metryki pokrycia per źródło.

#### Lifecycle Qdrant

- outbox po create/update/import/CV enrichment, zmianie facts/notes, delete i
  merge; raw-SQL importy również muszą emitować zdarzenia,
- worker z deduplikacją, retry/backoff, `FOR UPDATE SKIP LOCKED`, poison-event
  state, tombstone i metryką najstarszego eventu,
- `content_fingerprint`, model i wersja embeddingu,
- wersjonowana kolekcja per model,
- fail-closed builder przypisany do jednego modelu,
- outbox/dual-write uruchomiony przed backfillem,
- watermark, snapshot/backfill do nowej kolekcji, replay zdarzeń po watermarku i
  końcowy reconcile,
- walidacja coverage i fingerprintów przed atomowym przełączeniem aliasu,
- stara kolekcja otrzymuje dual-write lub ma udokumentowany replay do czasu
  zakończenia okna rollbacku,
- lexical fallback przy awarii dense search.

Voyage i Ollama nie mogą zapisywać ani odpytywać tej samej kolekcji tylko
dlatego, że mają równy wymiar wektora.

#### Kryteria akceptacji

- 100% rozpoznanych skills ma odpowiedni fact,
- backfill można bezpiecznie przerwać i wznowić,
- coverage aktywnych, nieusuniętych i indeksowalnych kandydatów wynosi co
  najmniej 99,5%,
- opóźnienie indeksacji p95 nie przekracza 5 minut,
- edycja skilla i enrichment CV zmieniają fingerprint/embedding,
- awaria Qdrant nie zwraca fałszywego pustego wyniku.

Powyższe wartości coverage/lag są proponowanym startowym SLO, a nie arbitralnym
warunkiem bez pomiaru. Przed gate'em trzeba zdefiniować mianownik
aktywnej/indeksowalnej populacji, wyjątki, okno pomiarowe, steady state oraz
osobne zachowanie w trakcie dużego importu/backfillu.

Hosted CI musi dostać Qdrant jako service lub osobny integration job. Nowe pliki
pytest trzeba jawnie dopisać do enumerowanego gate'u w `.github/workflows/ci.yml`;
samo dodanie testu do repo nie oznacza, że zostanie uruchomiony.

### Faza 4 — jeden retrieval/scoring pipeline i explainability

**Cel:** zwracać jedną, deterministyczną i wyjaśnialną listę kandydatów.

#### Pipeline

```text
non-overridable visibility blocks + hard filters
→ lexical + dense retrieval w przefiltrowanej kohorcie
→ RRF
→ jeden job-context request-fit index
→ warnings i assignment eligibility
→ stable cursor
```

Endpoint zapisu ponownie waliduje eligibility transakcyjnie, ponieważ stan
konfliktu lub procesu może zmienić się między wyszukaniem a przypisaniem.

#### Zmiany backendowe

- połączyć `search.py`, `hybrid_search.py`, `advanced_candidate_search.py`,
  `structured_candidate_search.py` i `scoring_service.py` za wspólnym
  interfejsem,
- przenieść POST search ze starego `fts_doc` na kanoniczny
  `search_fts/search_doc/search_doc_unaccented` używany przez aktualny GET i
  wycofać `fts_doc` dopiero po parity testach,
- must-have jako hard constraint, nice-to-have jako boost,
- dokumentować `request_fit_score` jako względny indeks dla jednego joba i
  strategii, nie jako probability,
- liczyć dokładny lub jasno opisany bounded `total`,
- cursor zawierający `query_hash`, `scoring_version`, `index_version` i
  sort-specific seek tuple albo referencję do krótkotrwałego search snapshotu,
- response zawiera:
  - `retrieval_score` dla każdego searcha,
  - `request_fit_score`,
  - `matched_criteria`,
  - `missing_criteria`,
  - `unknown_criteria`,
  - `evidence_snippets`,
  - `data_freshness`,
  - `eligibility` i warnings,
- dodać exclusion waterfall.

`request_fit_score` występuje wyłącznie przy `job_id`; globalna lista bez
requestu nie może udawać job fit. `data_confidence` pozostaje osobnym polem, nie
częścią relevance.

#### Zmiany frontendowe

- pokazać score i breakdown,
- pokazać spełnione/brakujące/niepotwierdzone kryteria,
- dodać snippets z CV i źródło danych,
- eksponować rolę, firmę, stawkę godzinową, dostępność, notice period,
  procesy i ostatnią aktywność,
- strategie `strict`, `balanced`, `adjacent`,
- pokazać dokładnie, które warunki poluzowała strategia,
- pokazywać banner oraz freshness badge przy degraded Traffit/Qdrant lub
  lexical fallback,
- grupować prawdopodobne duplikaty, bez automatycznego scalania rekordów;
  grupa ma stabilny rekord reprezentatywny, możliwość rozwinięcia źródeł i
  blokadę zaznaczenia dwóch rekordów tej samej osoby.

#### Testy wymagane

- kandydat spoza globalnego top 200 pojawia się po zawężeniu filtrów,
- kolejne strony nie mają duplikatów ani pominięć,
- cursor zachowuje spójność podczas równoczesnego update'u, zmiany score i
  reindeksacji,
- lexical fallback działa przy awarii Qdrant,
- score i explanation są deterministyczne,
- unknown nie jest traktowane jako automatyczne spełnienie,
- golden dataset nie traci recall względem zatwierdzonego baseline,
- p95 latency nie pogarsza baseline o więcej niż uzgodniony budżet.

### Faza 5 — shortlista, request-aware compare i migracja konsumentów

**Cel:** domknąć proces od wyników do zatwierdzonego kandydata.

#### Shortlista

Najpierw ADR musi rozstrzygnąć: osobny byt pre-pipeline, np.
`job_shortlist_entries`, czy rozszerzenie istniejącego `Proposal`. Jeśli
powstaje osobny model, powinien zawierać:

- `job_id`, `candidate_id`,
- oddzielne `evaluation_status` i `outreach_status`,
- `owner_id`,
- `decision_reason_code`, `note`,
- `next_action_at`,
- snapshot score/criteria version,
- `version` do optimistic locking,
- `promoted_to_pipeline_at` i referencję do utworzonego proposal/stage,
- `created_by`, `updated_by`, timestampy,
- audit log zmian.

Wymagane są unique `(job_id, candidate_id)`, deterministyczny retry po
konflikcie, jawne FK/delete policies, indeksy job/status/owner, RBAC oraz
idempotentna konwersja shortlista → proposal. Audit events powinny być
append-only, aby shortlista i pipeline nie stały się konkurencyjnymi źródłami
prawdy.

#### Frontend

- review drawer wybranych kandydatów,
- statusy shortlisty i ownership,
- request-aware compare dla 2–5 osób,
- wybór docelowego etapu, wspólnej notatki i tagów,
- per-candidate wynik bulk add i dokładny powód pominięcia,
- historia zmian kryteriów i decyzji.

Workspace, tabela, quick view, compare i review drawer muszą być obsługiwalne
klawiaturą, mieć poprawny focus management i etykiety screen readera. Score,
status i ryzyko nie mogą być komunikowane wyłącznie kolorem.

#### Migracja konsumentów

Do jednego wykonawcy V3 należy kolejno podłączyć:

- `/api/search/candidates`,
- `GET /api/candidates`,
- `/api/jobs/{id}/ai-matches`,
- `/api/jobs/{id}/recommendations`,
- saved-search alerts.

Marketplace/seeking-contractors powinien współdzielić kanoniczne fakty,
eligibility i lifecycle indeksu, ale ma inną intencję biznesową. Migrację jego
rankingu należy potraktować jako osobny etap po walidacji V3, bez założenia
identycznej skali lub kolejności wyników.

Legacy endpointy pozostają czasowo jako facade. Usuwamy je dopiero po
telemetrycznym potwierdzeniu braku użycia i porównaniu wyników.

#### Kryteria akceptacji

- kandydat może być oceniony bez natychmiastowego wejścia do pipeline'u,
- compare zawsze ma `job_id` i kryteria requestu,
- zatwierdzony bulk add przyjmuje etap, notatkę i tagi,
- UI pokazuje dokładny wynik każdej osoby,
- retry po timeout, częściowa awaria i powtórne wysłanie tego samego bulk
  requestu nie tworzą duplikatów; response rozlicza `added/skipped/failed`,
- współbieżna zmiana shortlisty nie nadpisuje po cichu nowszej decyzji,
- dla tego samego joba wszystkie powierzchnie używają tej samej skali i
  semantyki rankingu,
- zapisany search i alert stosują ten sam predicate/DSL; alert zachowuje własny
  delta watermark i dedup.

## 8. Zależności i możliwa równoległość

```text
Faza 0
  └── Faza 1
        ├── Faza 2 ───────────────┐
        └── Faza 3 ───────┐       │
                           └── Faza 4
                                  └── Faza 5
```

- Faza 1 powinna zostać wdrożona jako containment przed większą przebudową.
- Po Fazie 1 prace nad wspólnym workspace'em i danymi/indeksem mogą być
  częściowo równoległe.
- Przełączenie wspólnego scoringu wymaga gotowego DSL oraz potwierdzonego
  pokrycia danych i indeksu.
- Kod workspace'u może zostać wcześniej zmergowany za domyślnie wyłączoną
  flagą, ale aktywacja produkcyjna czeka na kanoniczny retrieval, coverage i
  explainability z Fazy 4.
- Shortlista może być rozwijana za flagą po ustabilizowaniu `job_id` context i
  wyniku V3.

## 9. Proponowana sekwencja PR-ów

| PR | Zakres | Warunek merge |
|---|---|---|
| 0 | Baseline harness + syntetyczny fixture | powtarzalne metryki i privacy review |
| 1 | Audyt danych stawek i ADR semantyki rate/work mode | decyzja właściciela procesu, bez mutacji danych |
| 2 | Addytywny kontrakt rate + kontrolowany backfill/adapter | parity starych rekordów i smoke |
| 3 | Normalizacja location/work-mode enum + prefill | macierz zgodności i testy mappingu |
| 4 | Interim skill resolver + language correctness | exact-token i source fallback tests |
| 5 | Eligibility core + prefilters/warnings | polityka reason codes i RBAC |
| 6 | Eligibility write gates + idempotent bulk + frontend race/selection | brak ścieżki omijającej hard block |
| 7 | `CandidateSearchQueryV3` schema + addytywne kolumny saved search | contract tests i migracja `heads` |
| 8 | Dual-read/write saved search + alert executor + backfill | zachowane watermarki i brak alert stormu |
| 9 | Wspólne moduły workspace'u za domyślnie wyłączoną flagą | URL/RBAC/a11y component tests |
| 10 | Hardening Cortex taxonomy/facts i schema reconcile | constraints, source coverage i failed-row report |
| 11 | Resumowalny Cortex/location backfill worker | checkpoint, kill-switch i resume test |
| 12 | Index outbox, worker i dual-write | retry, poison event, delete/merge tests |
| 13 | Nowa kolekcja Qdrant: snapshot, replay, reconcile, alias | coverage/freshness i rollback rehearsal |
| 14 | Kanoniczny FTS + filter-first retrieval + cursor | golden recall i latency gate |
| 15 | Job-fit scoring, explanations i degraded UX | deterministyczny eval i Chrome review |
| 16 | ADR shortlisty + addytywny model/API | RBAC, optimistic lock i idempotent promotion |
| 17 | Shortlista/compare UI + pełny E2E | bezpieczny test job i cleanup |
| 18 | Migracja jobowych AI Matching/recommendations | shadow parity + telemetry |
| 19 | Aktywacja workspace'u dla kohort, a potem default-on | potwierdzone coverage, koszt i SLO |
| 20 | Usunięcie legacy po okresie obserwacji | brak ruchu i udokumentowany rollback |

Każdy PR powinien mieć wąski zakres. Nie należy łączyć migracji danych, nowego
rankingu i dużej przebudowy UI w jednym wdrożeniu.

Marketplace/seeking-contractors nie jest częścią PR 18–20. Otrzymuje osobny
plan po walidacji wspólnych faktów i eligibility.

## 10. Strategia testów

### 10.1. Unit i contract tests

- mapper job → `CandidateSearchQueryV3`,
- stawka, currency i unit,
- parser lokalizacji/work mode,
- skill aliases i exact-token match,
- language code + level,
- eligibility i expiry konfliktów,
- strict/lenient unknown policy,
- serializacja URL,
- migracja saved search,
- score breakdown i unknowns.

Mapper requestu musi dodatkowo pokrywać: numer referencyjny, pusty brief,
`nice_skills`, kilka miast, hybrid, stawkę poniżej minimum, brak stawki i inną
walutę.

### 10.2. Integracyjne API

- godzinowa stawka end-to-end,
- city/country/remote,
- kandydat z technologią wyłącznie w źródle Traffit/CV,
- blacklist, excluded client, aktywny i wygasły konflikt,
- filter-first hybrid retrieval,
- stabilna paginacja,
- bulk add z etapem, notatką i tagami,
- idempotentny retry bulk add po timeout i częściowej awarii,
- optimistic-lock conflict shortlisty,
- uprawnienia shared searches i shortlist,
- negatywne 403/404 dla joba, saved search, shortlisty i deep linku,
- Qdrant outage → lexical fallback.

### 10.3. Frontend/component tests

- interpretacja requestu,
- przełączanie strategii,
- explanation, gaps i unknowns,
- exclusion waterfall,
- ochrona przed stale response,
- selection reconciliation,
- quick view bez utraty stanu,
- shortlist transitions,
- selected candidates review,
- odtworzenie workspace'u z URL,
- klawiatura, focus management, screen reader labels i status niezależny od
  koloru.

### 10.4. Blokujący scenariusz E2E

1. Otwórz job ze stawką godzinową, miastem i remote policy.
2. Kliknij `Znajdź kandydatów`.
3. Potwierdź poprawną interpretację requestu.
4. Przełącz strategię i filtry.
5. Sprawdź score, dowody, braki i unknowns.
6. Otwórz quick view bez utraty listy.
7. Dodaj dwie osoby do shortlisty.
8. Porównaj je względem requestu.
9. Zatwierdź bulk add do wybranego etapu z notatką i tagami.
10. Odśwież stronę i potwierdź zachowanie filtrów, sortowania i strategii oraz
    brak automatycznego odtworzenia ulotnych zaznaczeń.

Pełne DB/Qdrant/E2E należy wykonywać w hosted CI. Lokalnie tylko najmniejsze
host-native testy zgodne z polityką repo; bez lokalnego Dockera.

Produkcyjny Chrome smoke wykonuje się na dedykowanym testowym jobie i
kontrolowanych rekordach. Każda mutacja musi mieć autoryzowany cleanup; smoke
nie może dopisywać shortlisty ani proposal do realnego procesu klienta.

## 11. RODO, bezpieczeństwo i anty-bias

Wyszukiwanie wspiera decyzję człowieka i nie może automatycznie odrzucać lub
przypisywać kandydata na podstawie samego modelu.

Wymagania:

- cechy chronione oraz ich świadome proxy nie są używane w filtrach ani
  scoringu,
- wersja DSL, kryteriów, wag, modelu i evidence jest zapisana w audycie decyzji,
- snippets podlegają RBAC i redakcji danych, których rekruter nie powinien
  widzieć w danym kontekście,
- URL, telemetryka i logi nie zawierają PII ani treści CV,
- identyfikatory w telemetryce są pseudonimizowane, a retencja zdefiniowana,
- usunięcie kandydata propaguje się do fact store, Qdrant, shortlisty,
  snapshotów score i danych ewaluacyjnych,
- golden dataset w repo używa syntetycznych lub zanonimizowanych przykładów,
- każdy hard block i override ma reason code, autora, czas i podstawę polityki,
- access tests obejmują zmianę roli, usunięty job, utratę dostępu oraz shared
  search.

Przed produkcyjnym użyciem V3 wymagany jest przegląd scoring features pod kątem
proxy bias oraz potwierdzenie przez właściciela procesu, które reguły są
prawnym hard blockiem, ostrzeżeniem i blokadą przypisania.

## 12. Rollout, observability i rollback

### Feature flags

Rekomendowane flagi:

- `CANDIDATE_SEARCH_V3_ENABLED`,
- `CANDIDATE_SEARCH_V3_SHADOW_MODE`,
- `RECRUITER_SEARCH_WORKSPACE_ENABLED`,
- `JOB_SHORTLIST_ENABLED`.

Flagi muszą wspierać kohorty użytkowników/zespół, nie tylko globalne true/false.
Shadow sampling powinien mieć osobny procent ruchu i limit kosztu/latency.

### Shadow mode

Przed przełączeniem użytkowników:

1. wykonywać V2 i V3 dla kontrolowanej próbki requestów,
2. nie pokazywać V3 użytkownikowi,
3. wykonywać shadow asynchronicznie poza latency requestu użytkownika,
4. stosować timeout, circuit breaker i dzienny limit kosztu DB/Qdrant/rerankera,
5. logować overlap top 20/50, różnice score, latency i błędy,
6. analizować przypadki dużego rozjazdu,
7. dopiero potem przełączyć wybrane role/zespół.

Logi nie mogą zawierać treści CV ani danych kontaktowych.

### Metryki techniczne

- latency p50/p95,
- error i timeout rate,
- zero-result rate,
- lexical fallback rate,
- DB ↔ Qdrant coverage,
- index lag i stale fingerprint count,
- overlap V2/V3,
- eligibility blocks per reason,
- duplicate group rate.

### Metryki produktowe

- czas od otwarcia requestu do pierwszych 5 ocenionych osób,
- czas do pierwszej shortlisty,
- liczba zmian kryteriów,
- konwersja wynik → shortlista → kontakt → pipeline,
- accept/reject rate top 10,
- najczęściej niespełniane kryteria,
- udział wyszukiwań zapisanych i alertowanych.

### Rollback

- legacy endpointy pozostają jako facade do końca migracji,
- oryginalne saved-search payloady są zachowane,
- nowa kolekcja Qdrant jest przełączana aliasem,
- poprzednia kolekcja pozostaje dostępna przez ustalony okres,
- nowe modele shortlisty są addytywne,
- rollback nie usuwa danych produkcyjnych.

## 13. Definition of Done

Program jest ukończony dopiero, gdy:

1. nie występuje rozjazd stawka godzinowa ↔ miesięczna,
2. lokalizacja i remote mają jednoznaczną semantykę,
3. istnieje jeden Search DSL i jeden format saved search,
4. wszystkie ścieżki przypisania używają jednej eligibility policy,
5. job-context manual search, AI Matching i recommendations korzystają z tego
   samego request-fit contractu; globalny search ma osobny retrieval score, a
   marketplace jest walidowany w oddzielnym programie,
6. każdy wynik ma wyjaśnienie, gaps, unknowns i źródła,
7. Qdrant coverage/freshness są mierzone i alertowane,
8. rekruter może przejść request → shortlista → compare → pipeline bez utraty
   kontekstu,
9. golden eval, integracyjne API i blokujący E2E są zielone,
10. każdy PR przeszedł CI, merge, deploy, exact-SHA healthcheck i produkcyjny
    Chrome smoke zgodnie z kontraktem NEXUS.

## 14. Świadomy out of scope

Ten plan nie obejmuje:

- automatycznego scalania wszystkich istniejących duplikatów kandydatów,
- przebudowy parsera CV jako osobnego produktu,
- zmiany polityki biznesowej konfliktów bez decyzji właściciela procesu,
- automatycznego kontaktowania kandydatów,
- tuningu progów marketplace przed ujednoliceniem source path,
- usuwania legacy endpointów przed okresem shadow/telemetry.

W wynikach należy grupować prawdopodobne duplikaty, ale właściwe merge wymaga
oddzielnego, audytowalnego procesu.

## 15. Decyzja rekomendowana

Rozpocząć od PR 1 i PR 2 jako natychmiastowego containment. Następnie wdrożyć
Search DSL i wspólny workspace. Normalizację skills oraz lifecycle indeksu
prowadzić równolegle, ale nie przełączać unified scoringu przed potwierdzeniem
coverage i golden eval.

Największą wartość biznesową przyniesie nie kolejny model AI, lecz wiarygodny,
wyjaśnialny i wspólny workflow rekrutera, w którym te same kryteria znaczą to
samo na każdym ekranie.
