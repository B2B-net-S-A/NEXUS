# Audyt modułu Cortex — 2026-07-13

## Status dokumentu

- **Zakres:** backend, model danych, proces ekstrakcji, API, frontend/UX, RBAC,
  testy, observability i bieżący health produkcji.
- **Tryb audytu:** read-only. Audyt nie zmieniał kodu Cortexa ani danych.
- **Wniosek:** Cortex ma dobry fundament techniczny, ale obecnie jest bardziej
  diagnostycznym MVP niż operacyjną warstwą „central intelligence”.

## Executive summary

Cortex w obecnym kształcie realizuje pierwszy etap planu:

1. przechowuje znormalizowane fakty `candidate × skill × source`,
2. wyciąga technologie z pola `traffit_technologie`,
3. pokazuje mapę `skill × derived seniority`,
4. pokazuje podstawowe wskaźniki jakości danych.

Nie realizuje jeszcze trzech najważniejszych wartości biznesowych opisanych w
[discovery](./00-discovery.md):

- klient × stack × konsultanci,
- podaż kompetencji kontra popyt/luki klientów,
- operacyjny drill-down do konkretnych kandydatów.

Subiektywna ocena dojrzałości:

| Obszar | Ocena | Uzasadnienie |
|---|---:|---|
| Fundament techniczny | 7/10 | Dobry model provenance, FK, RBAC i exact-token matching |
| Wiarygodność danych | 3/10 | Konflikty taksonomii, brak reconcile i automatycznego syncu |
| Użyteczność operacyjna | 3/10 | Dashboard diagnostyczny bez przejścia do działania |

Nie znaleziono krytycznej luki bezpieczeństwa ani awarii klasy P0. Istnieją
jednak blokery jakości danych, które należy potraktować jako **P0 przed
biznesowym użyciem wyników**.

## Bieżący stan produkcji

Publiczny healthcheck został odczytany 2026-07-13:

- wdrożona wersja odpowiada lokalnemu `main`: `0411fdc`,
- `database = healthy`,
- `traffit = degraded`,
- `anthropic = configured`.

Globalny status `healthy` nie oznacza, że dane Cortex są aktualne. Implementacja
wyznacza overall health wyłącznie ze stanu bazy, a Traffit jest dla Cortexa
jedynym obecnie zaimplementowanym źródłem faktów. Zobacz
[main.py](../../backend/app/main.py#L1017).

Nie udało się niezależnie potwierdzić kompletnego produkcyjnego backfillu.
Status backfillu jest przechowywany wyłącznie w pamięci procesu i znika po
restarcie/deployu. Lokalny preview został sprawdzony na desktopie i urządzeniu
mobilnym; autoryzowany ekran produkcyjny nie był dostępny w użytej sesji.

## Jak Cortex działa obecnie

```text
candidates.cv_extracted_data["traffit_technologie"]
    ↓ ręczny backfill admina
split po przecinku / średniku / newline
    ↓ exact-token normalization
skills + skill_aliases
    ↓
cortex_skill_facts | cortex_unmatched_terms
    ↓
/api/cortex/tech-map | /api/cortex/coverage
```

Najważniejsze elementy:

- model faktów: [models/cortex.py](../../backend/app/models/cortex.py#L44),
- normalizacja: [fact_store.py](../../backend/app/services/cortex/fact_store.py#L63),
- backfill Traffita:
  [extractor_traffit.py](../../backend/app/services/cortex/extractor_traffit.py#L58),
- mapa technologiczna:
  [tech_map.py](../../backend/app/services/cortex/tech_map.py#L56),
- jakość danych:
  [coverage.py](../../backend/app/services/cortex/coverage.py#L25),
- API: [api/cortex.py](../../backend/app/api/cortex.py#L88),
- frontend: [CortexView.tsx](../../frontend/src/components/cortex/CortexView.tsx#L40).

## Mocne strony

1. **Provenance faktów.** Każdy fakt ma `source`, `confidence`, `evidence`,
   `observed_at` i `extracted_at`.
2. **Spójny model relacyjny.** Fakty wskazują kanoniczny skill i kandydata przez
   FK z `ON DELETE CASCADE`; istnieje unique `(candidate_id, skill_id, source)`.
3. **Bezpieczna normalizacja tokenów.** Exact-token matching nie znajdzie aliasu
   `go` w zwykłej prozie. Nazwy takie jak `.NET`, `CI/CD` i `TCP/IP` zachowują
   interpunkcję.
4. **Jawne braki.** `observed_at = NULL` trafia do kubełka „unknown”, zamiast
   udawać świeżą wiedzę.
5. **Agregowanie unikalnych rekordów.** Komórki mapy używają
   `COUNT(DISTINCT candidate_id)`.
6. **RBAC.** Widoki są ograniczone do admin/HoR/DL/TAC, a uruchamianie backfillu
   jest admin-only.
7. **Dobry discovery.** Dokument źródłowy uczciwie identyfikuje słabe pokrycie,
   brak dostępności i ryzyko agregowania pustych lub niezweryfikowanych danych.

## Findings i priorytety

### P0 przed biznesowym użyciem — taksonomia nie jest faktycznie kanoniczna

Pierwsza migracja seeduje nazwy lowercase, np. `python`, `java`, `react`:
[0012_skill_taxonomy.py](../../backend/alembic/versions/0012_skill_taxonomy.py#L41).
Późniejszy seed używa nazw Title Case, np. `Python`, `Java`, `React`:
[seed_skill_aliases.py](../../backend/scripts/seed_skill_aliases.py#L39).

Skrypt późniejszego seeda:

- wyszukuje canonical przez case-sensitive `==`,
- korzysta z case-sensitive unique,
- pomija konflikt aliasu przez `ON CONFLICT DO NOTHING`.

Statyczne porównanie obu źródeł seeda wykazało:

- **37 overlapów case-insensitive**, m.in. `python/Python`, `java/Java`,
  `javascript/JavaScript`, `react/React`, `aws/AWS`,
- **9 konfliktów alias → canonical**:
  - `apache kafka`: `kafka` kontra `Apache Kafka`,
  - `express.js`, `expressjs`: `express` kontra `Express.js`,
  - `node.js`, `nodejs`: `node` kontra `Node.js`,
  - `rest api`, `restful`: `rest` kontra `REST API`,
  - `vue.js`, `vuejs`: `vue` kontra `Vue.js`.

`load_taxonomy()` lowercasuje nazwy do zwykłego `dict` bez deterministycznego
rozwiązywania kolizji. Ostatni zwrócony wiersz wygrywa:
[fact_store.py](../../backend/app/services/cortex/fact_store.py#L63).

Możliwe skutki:

- niedeterministyczny `skill_id`,
- osobne wiersze `python` i `Python` na heatmapie,
- dwa fakty tej samej kompetencji po zmianie mapowania,
- niespójność także w istniejącym scoringu, który korzysta z tej samej
  taksonomii.

Dokument wdrożeniowy potwierdza, że późniejszy seed był uruchamiany. Dokładny
stan produkcyjny należy potwierdzić read-only SQL-em przed migracją naprawczą.

**Rekomendacja:**

- dodać osobne `normalized_key` i `display_name`,
- scalić rekordy po `lower/casefold`, przepinając aliasy i fakty,
- domenowo rozstrzygnąć dziewięć konfliktów,
- dodać unique index na `lower(canonical_name)` i `lower(alias)`,
- loader powinien failować głośno na kolizji zamiast nadpisywać mapę.

### P0 przed biznesowym użyciem — backfill nie wykonuje reconcile

Backfill tylko upsertuje fakty znalezione w bieżącym polu. Nie usuwa faktów,
których nie ma już w źródle:
[extractor_traffit.py](../../backend/app/services/cortex/extractor_traffit.py#L89),
[fact_store.py](../../backend/app/services/cortex/fact_store.py#L137).

Przykład:

```text
przed: Python, Docker
po:    Go
wynik Cortex po rerunie: Python, Docker, Go
```

Backfill nie jest też częścią daily Traffit sync, więc nowe i zmodyfikowane dane
nie trafiają automatycznie do fact store. Jest to ręcznie odświeżany snapshot.

**Rekomendacja:**

- atomowy reconcile per `(candidate_id, source)`: upsert bieżących i delete
  nieobecnych,
- savepoint per kandydat,
- `source_content_hash` do pomijania niezmienionych rekordów,
- incremental Cortex phase zaraz po fazie candidates w daily Traffit sync,
- tygodniowy full reconcile jako safety net.

### P0 przed biznesowym użyciem — unmatched occurrences są fałszywie zawyżane

Każdy rerun zwiększa `occurrences`, także dla niezmienionego źródła:
[fact_store.py](../../backend/app/services/cortex/fact_store.py#L174). Test
integracyjny wprost oczekuje `first_occurrences + 1` po rerunie:
[test_cortex_traffit_extract.py](../../backend/tests/test_cortex_traffit_extract.py#L92).

W rezultacie licznik mierzy częściowo liczbę uruchomień backfillu, a nie liczbę
aktualnych kandydatów z terminem. Ranking kolejki kuracji z czasem traci sens.

**Rekomendacja:** rozdzielić:

- bieżącą liczbę unikalnych kandydatów,
- historyczną liczbę obserwacji,
- pierwszy/ostatni moment obserwacji,
- źródłowy fingerprint lub relację term ↔ candidate/source.

### P1 — sterowanie jobem jest nietrwałe i podatne na race

Status joba jest globalnym słownikiem procesu:
[api/cortex.py](../../backend/app/api/cortex.py#L48).

Problemy:

- znika po restarcie lub deployu,
- nie jest współdzielony między workerami/replikami,
- guard sprawdza `running` przed `create_task`, ale task ustawia flagę później,
- brak job ID, cursoru, heartbeat i właściciela uruchomienia,
- task nie jest rejestrowany w zarządzanym lifecycle aplikacji,
- błąd SQL per kandydat nie używa rollback/savepoint; zatruta transakcja może
  zakończyć cały run mimo lokalnego `except`.

**Rekomendacja:** tabela `cortex_extraction_runs` + advisory lock w Postgresie,
cursor, heartbeat, status, statystyki, `triggered_by`, resume i orphan reaper.

### P1 — deploy może być zielony przy niedziałającym Cortex

Pierwszy deploy PR1 nie utworzył tabel Cortex; endpointy zwracały
`UndefinedTableError` mimo zielonego wdrożenia. Naprawa skopiowała DDL do
entrypointu:
[entrypoint.sh](../../backend/entrypoint.sh#L919).

`/api/health/deep` nadal sprawdza kontrakty, kandydatów, klientów i joby, ale nie
sprawdza `cortex_skill_facts` ani `cortex_unmatched_terms`:
[main.py](../../backend/app/main.py#L1128).

**Rekomendacja:**

- dodać oba modele Cortex do deep health,
- dodać wiek ostatniego kompletnego runu i jego status,
- synthetic smoke: `GET /api/cortex/coverage` z kontem technicznym lub osobny
  bezpieczny probe agregatu,
- alert na stale/partial run oraz wzrost error rate.

### P1 — heatmapa i KPI mogą wprowadzać w błąd

#### Skala koloru

Intensywność heatmapy jest liczona osobno w każdym wierszu. Wartość `60` może
mieć taki sam najciemniejszy kolor jak `900`:
[TechMapHeatmap.tsx](../../frontend/src/components/cortex/TechMapHeatmap.tsx#L54).

#### Suma wiersza

`Σ` sumuje tylko komórki, które przeszły backendowy `min_count`. Po ustawieniu
progu suma nie jest pełnym totalem skilla.

#### Filtr „Tylko u klientów”

Backend stosuje szeroki predykat: aktywny kontrakt **lub** aktywny konflikt
`current_employment` **lub** latest stage `hired`. UI przedstawia wynik jak
jednoznaczny stan „u klienta”:
[tech_map.py](../../backend/app/services/cortex/tech_map.py#L47).

Po filtrowaniu:

- `covered` jest filtrowane,
- `candidates_total` nadal obejmuje całą bazę,
- `sources` pozostaje globalne.

#### KPI źródeł

Frontend sumuje liczbę unikalnych kandydatów per source. Po dodaniu kolejnych
źródeł jeden kandydat może być policzony kilka razy:
[TechMapPanel.tsx](../../frontend/src/components/cortex/TechMapPanel.tsx#L44).

**Rekomendacja:**

- jedna globalna lub logarytmiczna skala koloru z legendą,
- pełne totals zwracane osobno przez API,
- jeden cohort CTE dla cells, denominatora i sources,
- rozdzielić „aktywny kontrakt” i „prawdopodobnie u klienta”,
- pokazywać overlap źródeł zamiast ich prostej sumy.

### P1 — Cortex nie prowadzi od obserwacji do działania

Heatmapa:

- pokazuje tylko top 40 technologii,
- nie ma wyszukiwarki ani paginacji,
- komórki nie są klikalne,
- nie prowadzi do listy kandydatów,
- nie pokazuje evidence, confidence ani freshness na poziomie osoby.

Zobacz
[TechMapHeatmap.tsx](../../frontend/src/components/cortex/TechMapHeatmap.tsx#L17).

Fact store nie zasila jeszcze:

- scoringu,
- structured candidate search,
- endpointów matchingu,
- payloadu Qdrant,
- profilu kandydata.

Dlatego obecna etykieta „kto co umie” jest zbyt mocna. Przy jednym źródle
Traffit ekran odpowiada raczej: **„dla kogo mamy historyczny sygnał o
technologii”**.

Największy wzrost wartości da:

1. kliknięcie komórki → lista kandydatów,
2. klient × stack × aktywny kontrakt,
3. lista potencjalnych następców dla kończących się kontraktów,
4. podaż skilli kontra popyt/hit-rate per klient i rola.

### P1 — pętla kuracji taksonomii nie jest domknięta

Tabela ma status `new/mapped/ignored`, ale API udostępnia tylko odczyt.
`/api/skills` także jest read-only. Admin nie może z UI:

- przypisać terminu do istniejącego skilla,
- utworzyć canonical/alias,
- oznaczyć terminu jako ignored,
- zobaczyć wpływu zmiany,
- audytować autora i daty decyzji.

Dedykowany frontendowy klient `unmatchedTerms()` jest zdefiniowany, lecz panel
korzysta z top 50 dołączonego do coverage:
[api.ts](../../frontend/src/lib/api.ts#L1256).

### P1 — błędy frontendowe wyglądają jak nieskończone ładowanie

Panele sprawdzają `isLoading || !data`, ale nie obsługują `isError`. Po 403,
500 lub timeoutie użytkownik widzi spinner bez końca:

- [TechMapPanel.tsx](../../frontend/src/components/cortex/TechMapPanel.tsx#L23),
- [CoveragePanel.tsx](../../frontend/src/components/cortex/CoveragePanel.tsx#L18).

Po zakończeniu backfillu frontend nie invaliduje coverage i wszystkich wariantów
tech-map. Użytkownik może nadal widzieć stare liczby.

### P1 — niespójność multi-role RBAC

Sidebar i `RequireRole` korzystają z primary + secondary `roles[]`. Middleware
dekoduje z JWT wyłącznie primary `role`:
[middleware.ts](../../frontend/src/middleware.ts#L90).

Przykład: użytkownik primary `recruiter`, secondary `tac` może:

- zobaczyć link Cortex,
- przejść backendowy guard,
- otrzymać `/403` w middleware.

**Rekomendacja:** umieścić pełne `roles` w JWT i sprawdzać unię ról w
middleware, zachowując backend jako ostateczny enforcement point.

### P2 — privacy i kontrola dostępu

- `/coverage` zwraca surowe unmatched terms także HoR/DL/TAC, mimo że dedykowany
  endpoint kolejki jest admin-only.
- `min_count` dopuszcza wartość `1`, co osłabia ochronę agregatów przed
  reidentyfikacją rzadkich kompetencji.
- Przy drill-downie do nazwisk potrzebne będą osobne uprawnienia i audyt
  eksportów.

**Rekomendacja:** minimum k-anonymity 3–5 dla agregatów, admin-only unmatched w
payloadzie oraz osobny guard dla widoków nazwiskowych/eksportów.

### P2 — integralność, wydajność i observability

W modelu brakuje DB CHECK/enum dla:

- `source`,
- `level`,
- `years`,
- `confidence`,
- statusu unmatched.

Brakuje też `extractor_version`, `source_ref`, `content_hash` i `run_id`, więc
wyniku nie da się w pełni odtworzyć ani wycofać.

Wydajność:

- backfill pobiera wszystkie rekordy przez `.all()`,
- wykonuje osobny upsert dla każdego skilla,
- coverage wykonuje wiele sekwencyjnych countów bez cache,
- kolejka unmatched nie ma indeksu pod `status + occurrences DESC`.

Przy obecnej skali jest to jeszcze obsługiwalne, ale przed CV/LLM i milionami
faktów należy przejść na streaming, bulk upsert i preagregowane summary.

### P2 — design system, mobile i accessibility

- Heatmapa używa hardcoded `rgba(37, 99, 235, …)` zamiast tokenów:
  [TechMapHeatmap.tsx](../../frontend/src/components/cortex/TechMapHeatmap.tsx#L70).
- Freshness używa `bg-emerald/amber/orange` zamiast semantycznych tokenów:
  [CoverageView.tsx](../../frontend/src/components/cortex/CoverageView.tsx#L14).
- Zakładki nie mają pełnej semantyki `tablist/tab/aria-selected`.
- Tabela nie ma caption i `scope` dla nagłówków wierszy.
- Loadingi i progress bary nie mają kompletnej semantyki status/progressbar.
- Cortex dostaje padding z AppShell i własny padding, co zawęża mobile.
- Heatmapa przewija się poziomo, ale nie ma czytelnego affordance przewijania.

## Rekomendowana roadmapa

### Etap 0 — Cortex Trust Foundation

Cel: liczby mają być deterministyczne, aktualne i audytowalne.

1. Read-only SQL audit produkcyjnej taksonomii, faktów i runów.
2. Migracja scalająca taksonomię oraz case-insensitive constraints.
3. Reconcile faktów per candidate/source.
4. Idempotentne liczenie unmatched.
5. `cortex_extraction_runs` + advisory lock + resume.
6. Integracja z daily Traffit sync.
7. Cortex w deep health i alert na stale/partial run.
8. Poprawa heatmapy, denominatorów, filtered sources i error states.
9. Pełny, kontrolowany backfill oraz zapis `data_as_of`.

**Kryteria wyjścia:**

- zero case-insensitive duplikatów canonical/alias,
- dwukrotny rerun na niezmienionych danych nie zmienia faktów ani current counts,
- usunięty token znika z fact store,
- status runu przeżywa restart,
- `/api/health/deep` wykrywa brak tabel Cortex,
- każdy raport pokazuje cohort i `data_as_of`.

### Etap 1 — Cortex Action Layer

Cel: użytkownik przechodzi od insightu do działania.

1. Wyszukiwarka skilla i pełna lista technologii.
2. Klikalna komórka → lista kandydatów.
3. Filtry: client, aktywny kontrakt, inferred employment, category, source,
   freshness, confidence, availability.
4. Widok klient × stack × konsultanci.
5. Potencjalni następcy dla kontraktów kończących się.
6. Operacyjny backlog jakości danych z ownerem i CTA.
7. Pełny workflow kuracji taxonomy: map/ignore/create/audit.
8. Filtry zapisane w URL i udostępnialne linki.

### Etap 2 — Cortex Intelligence Layer

Cel: fakty Cortex poprawiają matching, sprzedaż i delivery.

1. CV/LLM extractor najpierw dla aktywnych konsultantów.
2. Ręcznie oznaczony gold set i pomiar precision/recall ekstrakcji.
3. Wersjonowany prompt/model, evidence quote i limity kosztowe.
4. Resolved facts z precedencją `screening > cv_llm > traffit`, confidence i
   freshness decay.
5. Integracja ze scoringiem, matchingiem, search i Qdrant payload.
6. Normalizacja job title → rola/seniority/technologia.
7. Widok podaży kontra popyt/hit-rate per klient i rola.
8. Wymuszone procesy zbierania `close_reason`, `termination_reason`,
   availability, expected rate i verified tech.

Pełnego backfillu LLM całej bazy nie należy uruchamiać przed zakończeniem Etapu
0 i walidacją ekstraktora na ograniczonej populacji.

## Proponowane KPI Cortexa

### Jakość danych

- `% kandydatów z ≥1 resolved fact`,
- `% faktów z known observed_at`,
- `% faktów screening-verified`,
- unmatched rate i median time-to-curate,
- wiek ostatniego udanego runu,
- liczba stale/failed/partial runs,
- liczba duplikatów canonical/alias = 0.

### Użyteczność

- miesięczni aktywni użytkownicy per rola,
- liczba drill-downów z mapy do kandydatów,
- drill-down → shortlist/contact conversion,
- mediana czasu odpowiedzi na „kto zna X / kto jest u klienta Y”,
- liczba użyć client×stack przed spotkaniem sprzedażowym,
- liczba znalezionych potencjalnych następców.

### Wpływ biznesowy

- Precision@5 / Recall@20 / MRR po włączeniu Cortex facts,
- skrócenie czasu do pierwszej shortlisty,
- hit-rate per klient/rola,
- cross-sell opportunities wygenerowane z client×stack,
- wypełnienie close/termination reasons oraz dostępności.

## Testy i weryfikacja

Wykonano:

- frontend `type-check`: zielony,
- Vitest: **237/237** testów zielonych,
- scoped lint plików Cortex: bez błędów i ostrzeżeń,
- Ruff dla API/modeli/serwisów/testów Cortex: zielony,
- testy czystej normalizacji: **29/29** w izolowanym wykonaniu,
- runtime preview desktop/mobile: render poprawny,
- live public healthcheck produkcji: odczytany.

Ograniczenia weryfikacji:

- brak dedykowanych testów frontendowych/E2E Cortex,
- lokalne testy API/DB nie zostały uruchomione bez Postgresa i kompletnego
  środowiska Python 3.12 projektu,
- bieżący zdalny status CI nie został niezależnie potwierdzony,
- preview nie obejmuje tabs, query error states, admin backfill ani RBAC,
- autoryzowany ekran produkcyjny nie został otwarty,
- dokładny stan produkcyjnej taksonomii i kompletność backfillu wymagają
  read-only SQL lub autoryzowanego endpointu statusowego.

## Najlepszy następny krok

Przygotować jeden spójny PR **Cortex Trust Foundation**, obejmujący:

1. migrację i deduplikację taksonomii,
2. reconcile faktów,
3. trwałe extraction runs,
4. daily sync + health,
5. poprawność heatmapy/KPI,
6. testy regresyjne powyższych kontraktów.

Dopiero po jego wdrożeniu należy wykonać kontrolowany pełny backfill, potwierdzić
wyniki SQL-em i przejść do warstwy drill-down/client×stack.
