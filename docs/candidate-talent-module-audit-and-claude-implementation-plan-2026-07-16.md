# Moduł 2 — Kandydaci, sourcing i baza talentów

## Audyt, rekomendacja docelowa i szczegółowy plan implementacyjny dla Claude Code

**Data audytu:** 2026-07-16  
**Repozytorium:** NEXUS  
**Zakres źródłowy:** <code>origin/main</code> na commicie <code>e25225bdd35886fd9f6ccd1c90b2e902968dba09</code>  
**Wersja produkcyjna podczas finalnej weryfikacji:** <code>e25225bdd35886fd9f6ccd1c90b2e902968dba09</code>  
**Charakter dokumentu:** raport decyzyjny i plan wykonawczy; dokument nie zmienia działania systemu ani danych produkcyjnych

---

## 1. Streszczenie zarządcze

NEXUS ma rozbudowaną bazę kandydatów i wiele działających ścieżek sourcingu: ręczne tworzenie, import CSV, upload CV, publiczne zgłoszenia, LinkedIn/Proxycurl, TalentRadar, Traffit, pule talentów i marketplace. Problemem nie jest brak funkcji. Problemem jest brak jednego kontraktu tożsamości, prywatności, dokumentu, dostępności i wejścia do systemu.

Najważniejsze decyzje:

1. **Pierwszym krokiem musi być containment bezpieczeństwa.**  
   Rola <code>user</code>, opisana w modelu jako read-only viewer/klient, może obecnie czytać pełną bazę kandydatów, PII, stawki, dane JDG, notatki, CV i dokumenty. Może też bezpośrednim wywołaniem API uruchomić zbiorczą pseudonimizację do 500 kandydatów, zmieniać firmowe pule, dopisywać źródła i tworzyć notatki.

2. **Obecnej akcji <code>anonymize_pii</code> nie wolno traktować jako realizacji RODO/DSAR.**  
   Usuwa ona tylko kilka pól kontaktowych, zostawiając CV, dokumenty, treści, dane JDG, historię, nagrania, transkrypcje, wektory i rekordy integracyjne. Jednocześnie ustawia sourcingowy status <code>blacklisted</code>. Hard delete ma odwrotny problem: usuwa część historii operacyjnej i kontraktowej przez cascade, a może zostawić pliki, obiekty storage, Qdrant i JSON-y integracyjne.

3. **Anonimowy intake nie może mutować kanonicznego profilu kandydata.**  
   Publiczne zgłoszenie po samym znanym adresie email może dziś nadpisać istniejące imię, CV, podsumowanie i właściciela profilu. Docelowo każde zgłoszenie ma najpierw tworzyć niezmienny <code>CandidateSubmission</code>, a połączenie z istniejącym kandydatem ma wymagać zweryfikowanej tożsamości albo jawnej decyzji uprawnionego użytkownika.

4. **Tożsamość musi być osobnym, atomowym kontraktem.**  
   Surowy, case-sensitive email, nieunikalny telefon, niejednolity LinkedIn i pojedyncze <code>external_source/external_id</code> nie wystarczają przy wielu źródłach danych. Potrzebne są znormalizowane <code>CandidateIdentity</code>, wiele zewnętrznych identyfikatorów, kolejka przypadków niejednoznacznych oraz bezpieczny, audytowalny merge.

5. **<code>CandidateDocument</code> powinien stać się jedyną prawdą o plikach.**  
   Obecnie współistnieją lokalny dysk, pola legacy na <code>Candidate</code>, BYTEA i object storage w <code>CandidateDocument</code>. Różne endpointy używają innych priorytetów. Docelowy pipeline ma być wersjonowany, streamingowy, skanowany, idempotentny i transakcyjnie sprzątany.

6. **Prywatność, dostępność i marketability to trzy różne osie.**  
   <code>blacklisted</code>, <code>availability_status</code>, status kontraktu, konflikty, preferencje i engagement flags nie mogą być wymiennie używane jako odpowiedź na pytanie „czy wolno wyszukać, skontaktować, pokazać klientowi albo dodać do Job”. Potrzebny jest jeden <code>CandidateMarketabilityService</code> zwracający decyzję i przyczyny.

7. **Twardych konfliktów NDA/blacklist nie wolno wyłączać filtrem użytkownika.**  
   Aktualny checkbox „Respektuj NDA / blacklist klientów” przekazuje <code>industry_blocklist=false</code>, a backend wtedy nie ładuje konfliktów. Twarde wykluczenia muszą być zawsze wymuszane server-side; przełącznik może dotyczyć wyłącznie miękkich ostrzeżeń.

8. **Search V3, outbox i nowe prymitywy Traffit są dobrym fundamentem, ale nie są jeszcze końcem migracji.**  
   <code>CandidateSearchQueryV3</code> jest na razie schematem i adapterem, nie jednym wykonawcą wszystkich wyszukiwań. Commity <code>bbee39e</code> i <code>e25225b</code> dodały tabele integracji Traffit, content hash dokumentów, append-only pola notatek oraz czysty silnik 3-way merge z prawidłowym rozróżnieniem <code>MISSING</code> i <code>null</code>. Wszystkie kierunki integracji pozostają domyślnie wyłączone. Te elementy należy wykorzystać, nie duplikować.

Rekomendowany sposób realizacji to **dokładnie 7 zależnych PR-ów**. Pierwszy zamyka P0 bez feature flagi osłabiającej bezpieczeństwo. Kolejne dodają prywatność, bezpieczny intake, tożsamość, dokumenty, jedną politykę marketability/search oraz kończą frontend, wydajność, obserwowalność i CI.

---

## 2. Zakres modułu

### 2.1. W zakresie

Moduł 2 obejmuje:

- publiczne, ręczne i integracyjne wejście kandydata do systemu;
- rozpoznanie osoby, deduplikację, scalanie i zewnętrzne identyfikatory;
- kanoniczny profil kandydata i pochodzenie pól;
- CV, dokumenty, ekstrakcję, enrichment i wersjonowanie;
- techniczne mechanizmy podstawy przetwarzania, obowiązku informacyjnego, ograniczenia kontaktu, retencji, legal hold i DSAR;
- źródła pozyskania i lineage;
- status kandydata, dostępność i świeżość deklaracji;
- pule talentów, listę „Talenty” i marketplace „Targ / Dostępni”;
- wyszukiwanie i selekcję kandydata do momentu bezpiecznego przekazania do Job;
- bezpieczne projekcje danych, eksporty i pobieranie CV;
- uprawnienia, audyt, jakość danych, obserwowalność i testy tego przepływu.

### 2.2. Świadomie poza zakresem

- pełna przebudowa algorytmów scoringu i rankingu kandydat ↔ Job — to osobny moduł; tutaj definiowany jest tylko kontrakt eligibility i wejście do matchingu;
- przebudowa pipeline’u po skutecznym dodaniu kandydata do Job;
- generator branded CV poza integralnością dokumentu źródłowego;
- cały lifecycle kontraktu konsultanta;
- konfiguracja prawna bez decyzji DPO/legal;
- migracja Traffit jako osobny program — ten moduł poprawia tylko kontrakty dotyczące kandydata, importu i lineage;
- implementacja zewnętrznego scrapera GoWork; przyszły adapter ma używać tego samego intake contract;
- ogólnosystemowy redesign nawigacji i logowania.

### 2.3. Granica z następnym modułem

Moduł 2 kończy się na komendzie:

<code>AddCandidateToJob(candidate_id, job_id, actor, source_context, idempotency_key)</code>

Komenda ma zweryfikować dostęp, prywatność, twarde konflikty, aktualny status i podstawowe eligibility, utworzyć pierwszy etap oraz snapshot CV. Dalsze prowadzenie procesu, przesuwanie etapów, oceny i zatrudnienie należą do modułu pipeline’u.

---

## 3. Źródła dowodowe i ograniczenia audytu

### 3.1. Stan kodu

- Analiza została rozpoczęta na <code>adcfa43</code>, a przed finalizacją dwukrotnie ponowiono <code>git fetch origin</code>, ponieważ <code>main</code> aktywnie się przesuwał.
- Najnowszy <code>origin/main</code> i produkcja wskazywały ten sam pełny SHA: <code>e25225bdd35886fd9f6ccd1c90b2e902968dba09</code>.
- Różnica <code>adcfa43..e25225b</code> dotyczyła głównie addytywnych, domyślnie wyłączonych prymitywów dwukierunkowej integracji Traffit, czystego silnika 3-way merge oraz dołączenia pięciu suite’ów Traffit do jawnej listy CI. Audytowane endpointy kandydatów, frontend, RBAC, marketplace i search nie zmieniły się.
- Lokalny checkout jest rescue branchem z niezwiązanymi, nieśledzonymi dokumentami. Do analizy użyto czystego obrazu <code>origin/main</code>; lokalny WIP nie był uznany za prawdę produkcyjną.
- Nie resetowano, nie stashowano i nie modyfikowano cudzych zmian.

### 3.2. Stan produkcji

Finalny <code>GET https://api.nexus.dynaminds.pl/api/health</code> z wymaganym User-Agent zwrócił:

- HTTP 200;
- <code>status=healthy</code>;
- <code>version=e25225b...</code>;
- <code>checks.database=healthy</code>;
- <code>checks.traffit=degraded</code>;
- <code>checks.cloudtalk=unhealthy</code>;
- <code>checks.anthropic=configured</code>.

Na początku audytu healthcheck chwilowo zwracał 502/503. Kolejne próby były zdrowe, a finalna potwierdziła deploy <code>e25225b</code>. Raport nie interpretuje chwilowego błędu jako trwałej awarii, ale uwzględnia potrzebę monitorowania zależności integracyjnych.

### 3.3. Ograniczenie snapshotu administracyjnego

Nie pobrano <code>/api/admin/snapshot</code>, ponieważ lokalnie nie było wymaganego pliku/tokena <code>NEXUS_SNAPSHOT_TOKEN</code>. Dlatego:

- liczby duplikatów, osieroconych plików, niepełnych privacy records i stale availability nie są w tym raporcie przedstawiane jako zmierzone;
- istniejące komentarze migracji i skrypty traktowane są jako dowód historycznego problemu, nie aktualny licznik produkcyjny;
- przed migracjami Claude ma uruchomić preflight z sekcji 13 w kontrolowanym środowisku administracyjnym.

### 3.4. Produkcyjne flow sprawdzone read-only

W przeglądarce, bez mutacji danych, sprawdzono:

- listę kandydatów;
- Targ / Dostępni — zakładkę „Szukają projektu”;
- Targ / Dostępni — zakładkę „Targ ręczny”.

Zaobserwowano:

- lista pokazywała <code>54 096</code> kandydatów;
- w pierwszej stronie widoczny był co najmniej jeden rekord placeholder <code>? ?</code>;
- duża część widocznych kandydatów miała „Dostępność nieznana”;
- widok „Szukają projektu” zwrócił 18 konsultantów w horyzoncie 30 dni; każdy widoczny rekord nie miał oferty przekraczającej próg, a tylko dwa pokazywały po jednym słabym dopasowaniu;
- ręczny targ zawierał 5 kandydatów, każdy z widocznym statusem „Nieznany”; część nie miała kategorii ani ownera;
- UI obiecuje alert przy score ≥ 70, podczas gdy backendowy default <code>MARKETPLACE_SCORE_THRESHOLD</code> wynosi 80.

Nie odczytywano ani nie zapisano treści CV, danych kontaktowych ani innych prywatnych danych kandydatów.

### 3.5. Ważne rozróżnienie dowodów

Raport rozdziela:

- **potwierdzone zachowanie produkcji** — zagregowane obserwacje UI i healthcheck;
- **potwierdzony kontrakt kodu** — ścieżki wykonania w aktualnym <code>origin/main</code>;
- **hipotezy wymagające konfiguracji, logów lub SQL** — realny stan feature flag, providerów, retencji i liczebność niespójności;
- **decyzje prawne** — muszą zostać zatwierdzone przez DPO/legal; raport opisuje kontrolki techniczne, nie wydaje oceny prawnej.

---

## 4. Obecny i docelowy przepływ

### 4.1. Obecny przepływ

~~~mermaid
flowchart LR
    A["Manual / CSV / CV / LinkedIn / Public apply / TalentRadar / Traffit"] --> B["Wiele bezpośrednich writerów Candidate"]
    B --> C["Ścieżkowy dedup lub brak dedup"]
    C --> D["Candidate jako profil i magazyn wielu źródeł prawdy"]
    D --> E["Local file / legacy fields / BYTEA / object storage"]
    D --> F["AI parsing / Voyage / Qdrant"]
    D --> G["List / search / pools / marketplace"]
    G --> H["Wiele writerów CandidateStage"]
    H --> I["Job pipeline"]
    D --> J["blacklisted używane obok availability i privacy"]
~~~

Główne skutki:

- retry może utworzyć duplikat, dodatkowy stage lub source event;
- różne źródła nadpisują pojedyncze pola pochodzenia;
- publiczny intake może zmienić istniejący profil;
- wynik parsera może nadpisać nowszą lub ręcznie poprawioną wartość;
- dostępność i prawo do kontaktu nie mają świeżości ani jednej decyzji;
- search, marketplace i add-to-job stosują różne podzbiory reguł;
- usunięcie lub „anonimizacja” nie obejmują wszystkich magazynów danych.

### 4.2. Docelowy przepływ

~~~mermaid
flowchart LR
    A["Adapter źródła"] --> B["CandidateSubmission / IntakeEvent"]
    B --> C["Walidacja pliku i privacy context"]
    C --> D["Identity Resolver"]
    D -->|"deterministic"| E["Kanoniczny Candidate"]
    D -->|"ambiguous"| F["Identity Review Queue"]
    F --> E
    C --> G["CandidateDocument revision"]
    G --> H["ExtractionRun + field provenance"]
    H --> E
    E --> I["Privacy State"]
    E --> J["Availability Claims"]
    E --> K["CandidateMarketabilityService"]
    I --> K
    J --> K
    K --> L["Search V3 / Pools / Marketplace"]
    L --> M["AddCandidateToJob command"]
    M --> N["Job pipeline"]
    E --> O["Durable outbox"]
    O --> P["Qdrant / cleanup / integrations"]
~~~

Kluczowe rozróżnienia:

- <code>CandidateSubmission</code> odpowiada: **co i z jakiego źródła wpłynęło?**
- <code>CandidateIdentity</code> odpowiada: **z jaką osobą wiążemy ten sygnał?**
- <code>Candidate</code> odpowiada: **jaki jest kanoniczny profil operacyjny?**
- <code>CandidateDocument</code> odpowiada: **jaki konkretny plik i wersję otrzymaliśmy?**
- <code>CandidatePrivacyState</code> odpowiada: **w jakim zakresie wolno przetwarzać i kontaktować?**
- <code>CandidateAvailabilityClaim</code> odpowiada: **kto, kiedy i na jak długo zadeklarował dostępność?**
- <code>CandidateMarketabilityDecision</code> odpowiada: **czy kandydat może wejść do danego kanału i dlaczego?**

---

## 5. Co warto zachować

Plan nie powinien przepisywać wszystkiego. Należy zachować i rozwinąć:

- model <code>CandidateDocument</code> z deferred BYTEA i object storage;
- dodane na <code>bbee39e</code> pola <code>content_sha256</code>, <code>source_manifest_fingerprint</code> i <code>source_deleted_at</code>;
- dodane prymitywy Traffit: entity links, inbox/outbox, conflicts, runs/phases, leases i runtime control — przy zachowaniu fail-closed gate’ów OFF;
- <code>backend/app/services/traffit/merge.py</code> z 3-way merge i sentinelem <code>MISSING ≠ null</code>; rozwijać ten silnik, nie pisać konkurencyjnego;
- append-only kierunek notatek przez <code>external_source</code>, <code>external_id</code> i <code>supersedes_note_id</code>;
- <code>CandidateSearchQueryV3</code> i lossless adapter jako docelowy język zapytań;
- <code>candidate_job_eligibility.py</code> jako zalążek jednej polityki eligibility;
- index outbox z revision i <code>SKIP LOCKED</code>, ale dopiero po spięciu ze wszystkimi writerami i jedną transakcją;
- istniejące source events jako marketingowe touches, po dodaniu aktora, idempotencji i prawidłowej atrybucji;
- marketplace singleton, TTL oraz alert log z unikalnością pary kandydat–Job;
- istniejące komponenty design systemu i mechanizm authenticated blob URL;
- stabilny healthcheck i deployment exact-SHA;
- normalizację telefonu z dedup service jako wspólny prymityw, po przeniesieniu do identity contract;
- kill-switche integracji i persisted watermark — po poprawieniu semantyki sukcesu.

---

## 6. Rejestr najważniejszych ustaleń

| ID | Priorytet | Ustalenie | Skutek |
|---|---:|---|---|
| M2-SEC-01 | P0 | <code>CurrentUser</code> daje viewerowi pełny list/detail/search/export/CV/documents | Masowa ekspozycja PII, stawek, danych JDG i plików |
| M2-SEC-02 | P0 | Viewer może wywołać bulk <code>anonymize_pii</code> do 500 rekordów | Nieautoryzowana i nieodwracalna mutacja danych |
| M2-SEC-03 | P0 | Użytkownik może wyłączyć ładowanie hard NDA/blacklist conflicts | Ryzyko ujawnienia niedozwolonego Job lub klienta |
| M2-SEC-04 | P0 | Viewery mogą mutować firmowe pule, źródła i notatki | Zatrucie danych, provenance i działań innych użytkowników |
| M2-PRIV-01 | P0 | Pseudo-anonymize zostawia większość PII i artefaktów | Fałszywe poczucie wykonania żądania prywatności |
| M2-PRIV-02 | P0 | Hard delete kasuje historię przez cascade, a nie sprząta wszystkich stores | Utrata audytu/kontraktów oraz osierocone PII |
| M2-PRIV-03 | P0 | Legacy embedding i parser mogą wysyłać surowe CV/PII do providerów | Brak technicznego fail-closed i pełnego egress manifestu |
| M2-INTAKE-01 | P0 | Public apply mutuje istniejący profil po samym emailu | Profile poisoning, podmiana CV i ownera |
| M2-ID-01 | P1 | Dedup jest ścieżkowy, check-then-insert i nieatomowy | Duplikaty przy retry, concurrency i wariantach danych |
| M2-ID-02 | P1 | Skrypt merge przy konflikcie może skasować poprawne child rows | Cicha utrata historii przy scalaniu |
| M2-ID-03 | P1 | Jeden scalar external ID nie opisuje wielu źródeł | Nadpisanie lineage między Traffit/TalentRadar/LinkedIn |
| M2-IMP-01 | P1 | Traffit przesuwa watermark także przy błędach fazy | Rekord może wypaść z delty po oknie lookback |
| M2-DATA-01 | P1 | Schematy pozwalają na nieprawidłowe null/ujemne/shape, a licznik notatek dryfuje | 500, niespójne JSON i błędne statystyki profilu |
| M2-DOC-01 | P1 | Lokalne CV, legacy Candidate, BYTEA i documents mają różne prawdy | Niespójne pobieranie, orphan files i brakujący CV w UI |
| M2-DOC-02 | P1 | Upload czyta całość, ufa MIME lub rozszerzeniu i nie ma pełnego scan flow | Spoofing, presja pamięci, zły plik i niedeterministyczny rollback |
| M2-EXP-01 | P1 | CSV/XLSX nie neutralizuje formuł z danych kandydata | Formula injection po otwarciu eksportu |
| M2-ELIG-01 | P1 | Status, availability, engagement, kontrakt, konflikty i privacy są rozproszone | Różne surface pokazują inny zbiór kandydatów |
| M2-MKT-01 | P1 | Marketplace ma próg 70 w UI i 80 w backendzie oraz różne buildery | Użytkownik nie rozumie braku wyników i rozbieżnych matchy |
| M2-SRC-01 | P1 | Source event nie ma aktora/idempotencji, a hire attribution jest zbyt szerokie | Zawyżony ROI kanałów i backdated touches |
| M2-SEARCH-01 | P1 | V3 nie jest jeszcze jednym wykonawcą; hybrid capuje do 200 | Niespójne filtry, total i dalsze strony |
| M2-INDEX-01 | P1 | Nie wszystkie istotne pola invalidują cache i enqueue reindex | Stale search i stale score po edycji profilu |
| M2-PERF-01 | P1 | Listy i eksporty pobierają zbyt szeroki ORM graph/raw CV | Wysoki koszt DB/pamięci i niestabilne p95 |
| M2-FE-01 | P1 | Notatka z Add/Edit jest tracona, a LinkedIn ma złą nazwę pola | Cicha utrata danych i niedziałający link |
| M2-FE-02 | P1 | Wiele błędów API wygląda jak pusty wynik; draft może się resetować | Fałszywa prawda biznesowa i utrata wpisywanych zmian |
| M2-FE-03 | P1 | Compare łamie Rules of Hooks i wymyśla pseudo-score | Niestabilny ekran i nieudokumentowane metryki |
| M2-POOL-01 | P1 | Firmowe pule są edytowalne przez każdego; lista kończy się na 500 | Naruszenie read-only i niepełny widok dużych pul |
| M2-TOKEN-01 | P1 | Engagement token jest plaintext i nie jest atomowo konsumowany | Wyścig one-time tokena i nadmierna ekspozycja sekretu |
| M2-TEST-01 | P1 | Backend CI uruchamia już suite’y Traffit, ale nadal pomija wiele innych istniejących testów kandydatów | Krytyczna regresja poza Traffit może przejść mimo istniejącego testu |
| M2-RBAC-02 | P2 | Część guardów używa tylko primary <code>user.role</code> | Błędne decyzje dla secondary roles |
| M2-UX-01 | P2 | Import/profile/pools/marketplace mają braki a11y, URL state i retry | Trudna obsługa i słaba diagnostyka |
| M2-OBS-01 | P2 | Brak jednego admin quality snapshot modułu | Drift wykrywany dopiero przez użytkownika |

---

## 7. Szczegółowe ustalenia i rekomendacje

## 7.1. Bezpieczeństwo i polityka dostępu

### M2-SEC-01 — pełna baza kandydatów i PII dostępne dla roli viewer/client

**Dowód w kodzie**

- <code>backend/app/models/user.py:13-37</code> opisuje rolę <code>user</code> jako read-only viewer, także Quality Control / klient.
- <code>backend/app/api/deps.py:87-152</code>: <code>CurrentUser</code> oznacza tylko aktywnego, zalogowanego użytkownika.
- Sam <code>CurrentUser</code> chroni m.in.:
  - listę i detail kandydatów w <code>backend/app/api/candidates.py:1016-1021,2601-2623</code>;
  - eksport do 50 000 wierszy w <code>candidates.py:1832-2073</code>;
  - listę i content dokumentów oraz presigned URL w <code>candidates.py:3181-3355</code>;
  - pojedynczy i zbiorczy download CV w <code>candidates.py:3923-4069</code>;
  - advanced/global search w <code>backend/app/api/search.py</code>;
  - członków talent pool i marketplace.
- <code>CandidateResponse</code> w <code>backend/app/schemas/candidate.py:300-417</code> zawiera email, telefon, stawki, salary, preferencje, engagement notes, dokładną lokalizację, legal_name, NIP, REGON, business address, dane źródeł i pola ekstrakcji.
- <code>frontend/src/middleware.ts:27-30,49-54</code> nie wymaga konkretnych ról dla <code>/candidates</code> i <code>/talents</code>.

**Ryzyko**

- konto self-registered z rolą <code>user</code> może pobrać masowy eksport albo CV;
- klient/viewer może enumerować ID i otrzymać więcej danych niż pokazuje UI;
- brak audytu odczytu PII, eksportu i downloadu utrudnia rozliczalność;
- ukrycie przycisku w frontendzie nie zamknie bezpośredniego wywołania API.

**Rekomendacja**

Wprowadzić centralny <code>CandidateAccessPolicy</code> z capability, nie z jednym „can view”:

- <code>candidate.search_summary</code>;
- <code>candidate.view_profile</code>;
- <code>candidate.view_contact</code>;
- <code>candidate.view_documents</code>;
- <code>candidate.view_rates</code>;
- <code>candidate.view_legal</code>;
- <code>candidate.export</code>;
- <code>candidate.mutate</code>;
- <code>candidate.merge</code>;
- <code>candidate.privacy_execute</code>.

Rozdzielić DTO na co najmniej:

- <code>CandidateSearchSummary</code> — brak kontaktów, danych prawnych i binary metadata;
- <code>CandidateOperationalProfile</code> — pola dla wewnętrznego recruitera/sourcera;
- <code>CandidateFinanceView</code>;
- <code>CandidateLegalView</code>;
- <code>CandidateClientShareView</code> — tylko jawnie udostępniona, zredagowana projekcja.

**Kryteria akceptacji**

- <code>user</code> nie dostaje globalnej listy PII, emaila, telefonu, LinkedIn, CV URL/binary, stawek, NIP ani eksportu;
- bezpośredni request po znanym ID nie ujawnia istnienia nieautoryzowanego rekordu;
- recruiter/sourcer otrzymuje zatwierdzony zakres operacyjny; finanse/legal są osobnymi capability;
- primary i secondary roles przechodzą tę samą macierz;
- eksport i download zapisują immutable audit: actor, purpose/reason, scope/count, request ID, bez surowego PII w logu;
- frontend renderuje akcje z capability, ale backend pozostaje autorytatywny;
- testy obejmują list, detail, search, documents, export, ZIP i talent pools dla każdej roli.

### M2-SEC-02 — destrukcyjny bulk endpoint dostępny dla viewerów

**Dowód w kodzie**

- <code>backend/app/api/candidates_bulk.py:144-201</code> używa <code>CurrentUser</code>.
- Akcja obsługuje <code>add_tags</code> i <code>anonymize_pii</code> dla maksymalnie 500 kandydatów.
- Pseudonimizacja zeruje wybrane pola i ustawia <code>status=blacklisted</code> bez reauth, typed reason, per-row authorization i trwałego audytu.

**Rekomendacja natychmiastowa**

- zablokować <code>anonymize_pii</code> dla wszystkich poza dedykowaną capability admin/DPO;
- do czasu prawdziwego privacy executora endpoint ma odpowiadać 409/501 z jasnym komunikatem, a nie wykonywać częściową operację;
- <code>add_tags</code> ograniczyć do ról operacyjnych i autoryzowanego zakresu;
- wprowadzić preview/dry-run, reauth, reason, idempotency key i audit event.

**Kryteria akceptacji**

- <code>user</code>, klient i nieuprawniona rola otrzymują 403; baza pozostaje byte-identical;
- sam wybór akcji w body nie może zmienić wymaganego permission;
- retry tej samej operacji nie wykonuje jej drugi raz;
- częściowy błąd nie zostawia nieudokumentowanej połowy batcha;
- UI nie pokazuje akcji, dopóki prawdziwy executor nie jest gotowy.

### M2-SEC-03 — filtr użytkownika wyłącza twarde konflikty NDA/blacklist

**Dowód w kodzie**

- <code>frontend/src/components/sourcing/RecommendationFiltersBar.tsx:167-175</code> pokazuje checkbox „Respektuj NDA / blacklist klientów”.
- <code>backend/app/api/recommendations.py:1109-1137</code> przyjmuje <code>industry_blocklist</code> od każdego zalogowanego użytkownika.
- <code>backend/app/services/recommendation_filters.py:204-220</code> przy <code>false</code> nie ładuje konfliktów w ogóle.
- Hard conflicts obejmują m.in. <code>blacklist</code>, <code>competitor</code> i <code>nda</code>.

**Rekomendacja**

Rozdzielić:

- <code>hard_exclusions</code> — zawsze fail-closed, bez parametru pozwalającego ominąć;
- <code>soft_warnings</code> — opcjonalny widok ostrzeżeń, np. obecne zatrudnienie;
- telemetryczne <code>excluded_reason_codes</code> — bez ujawniania niedozwolonego Job w wynikach, countach lub below-threshold.

**Kryteria akceptacji**

- <code>industry_blocklist=false</code> nie zmienia zbioru hard-blocked ID;
- hard-blocked Job nie występuje w results, counts, weak matches, telemetry ani cache;
- test bezpośredniego API potwierdza fail-closed;
- checkbox zostaje usunięty albo zmieniony na przełącznik wyłącznie soft warnings.

### M2-SEC-04 — mutacje danych przy samym CurrentUser

**Potwierdzone przypadki**

- <code>backend/app/api/notes.py:117-192</code>: każdy zalogowany może tworzyć notatkę i powiadomienia; list endpoint nie ma obowiązkowego filtra ani pełnej paginacji.
- <code>backend/app/api/candidate_sources.py:87-124</code>: viewer może dodać i backdate’ować source event.
- <code>backend/app/api/talent_pools.py:105-121,175-352</code>: każdy może tworzyć firmowe pule i zmieniać membership.
- <code>backend/app/api/candidates.py:2975-3085</code>: stawki mają słabszy guard niż istniejący kontrakt <code>financial_access.py</code>.
- <code>CandidateUpdate</code> pozwala RecruiterPlus zmienić także pola prawne, finansowe i weryfikacyjne bez field-level policy.
- kilka add-to-job entrypointów ma inne lub słabsze guardy; recommendations używa <code>CurrentUser</code>.

**Rekomendacja**

- osobne request schemas per use-case, nie jeden szeroki <code>CandidateUpdate</code>;
- action-specific dependencies i field-level guard;
- corporate pool writes dla RecruiterPlus lub dedykowanej capability; personal pool tylko owner/admin;
- source event jako append-only, z aktorem, idempotency i correction event zamiast mutacji historii;
- finansowe i prawne pola przez istniejący, ujednolicony resolver;
- wszystkie add-to-job wyłącznie przez jedną komendę domenową.

**Kryteria akceptacji**

- rola <code>user</code> nie wykonuje żadnej mutacji kandydata, puli ani source eventu;
- każda dozwolona akcja ma negatywne testy dla wszystkich niższych ról;
- personal pool non-owner otrzymuje 403;
- bulk write jest atomowy albo raportuje dokładny, idempotentny wynik per row;
- zmiany finansowe/prawne wymagają właściwej capability niezależnie od body.

## 7.2. Prywatność, retencja i zewnętrzne przetwarzanie

### M2-PRIV-01 — „anonymize_pii” nie obejmuje danych kandydata

Po operacji pozostają między innymi:

- <code>raw_cv_text</code>, legacy CV content/path/storage key;
- wszystkie <code>CandidateDocument</code> i obiekty storage;
- avatar, lokalizacja i współrzędne;
- doświadczenie, edukacja, języki, AI summary i extracted data;
- salary, rate, preferences i engagement notes;
- legal_name, NIP, REGON i business address;
- notes, activities, calls, transcripts, chats i LinkedIn snapshots;
- source/UTM/external IDs;
- wektory Qdrant i payload z imieniem;
- telemetryczne payloady;
- nowe JSONB-y integracji Traffit: snapshots, outbox/webhook payloads i conflicts.

**Rekomendacja**

Zastąpić akcję przez trwały <code>CandidatePrivacyRequest</code> i worker wykonujący manifest artefaktów. Status sourcingowy nie może być stanem privacy. Executor ma rozróżniać:

- archive;
- do-not-contact;
- restrict processing;
- retention review;
- pseudonymize z zachowaniem wymaganych rekordów;
- erase po uwzględnieniu legal hold i zatwierdzonej polityki;
- merge do kanonicznego podmiotu.

**Kryteria akceptacji**

- preview zwraca deterministyczny manifest stores i planowane działania;
- drugi run jest no-op;
- audit nie zawiera raw PII;
- obiekty storage, local legacy, Qdrant i nowe tabele Traffit są objęte manifestem;
- retained legal/finance data jest oddzielone, ograniczone i nie pozostaje w zwykłej projekcji Candidate;
- failure tworzy retryable job, nie fałszywy status „done”.

### M2-PRIV-02 — hard delete niszczy historię, ale nie gwarantuje usunięcia PII

**Dowód w kodzie**

- <code>backend/app/api/candidates.py:3458-3505</code> pozwala DeliveryLeadPlus hard-delete Candidate.
- Migracje <code>0141_candidate_delete_cascade.py</code> i <code>0146_candidate_fk_cascade_sweep.py</code> ustawiają wiele relacji na cascade, także operacyjne i kontraktowe.
- Handler best-effort usuwa Qdrant, ale nie orkiestruje local CV, <code>cv_storage_key</code> i wszystkich <code>CandidateDocument.storage_key</code>.
- Qdrant delete następuje poza niezawodnym outboxem; błąd DB lub storage może zostawić stan częściowy.
- Nowe tabele Traffit używają w wielu miejscach <code>candidate_id ON DELETE SET NULL</code>; JSONB snapshot/payload może zostać po odłączeniu od kandydata.

**Rekomendacja**

- usunąć zwykły hard delete z UI i endpointu operacyjnego;
- wprowadzić archive oraz osobny privacy executor;
- kontrakty, audit i wymagane rozliczenia łączyć z pseudonymous subject key zamiast cascade;
- storage/vector/integration cleanup tylko przez durable outbox;
- dodać reconciler osieroconych artefaktów.

**Kryteria akceptacji**

- zwykła akcja operacyjna nie może skasować kontraktu, source lineage ani audytu;
- awaria Qdrant/storage nie powoduje utraty informacji o wymaganym cleanupie;
- każdy artifact ma wynik <code>deleted</code>, <code>retained_with_reason</code> albo <code>retry</code>;
- brak jawnego DPO/legal approval blokuje irreversible erase.

### M2-PRIV-03 — brak technicznego privacy ledger

Repo nie ma jednego modelu dla:

- lawful/processing basis;
- privacy notice version i sposobu przekazania;
- scope/purpose;
- source oraz <code>obtained_at</code>;
- withdrawal/restriction/do-not-contact;
- retention policy i <code>retention_until</code>;
- legal hold;
- DSAR request i wykonania.

**Rekomendowany model**

- append-only <code>candidate_privacy_events</code>;
- materialized/current <code>candidate_privacy_state</code>;
- polityka per purpose, nie jeden checkbox;
- pochodzenie eventu: public application, import, recruiter, candidate self-service, DPO;
- reference/proof bez trzymania zbędnej kopii PII;
- gate przed kontaktem, eksportem, embeddingiem, search, marketplace i add-to-job.

**Zastrzeżenie**

Dokładne podstawy prawne, treść notice, retencja i znaczenie zgody muszą zostać zatwierdzone przez DPO/legal. Claude ma zbudować techniczny model i enforcement zgodnie z zatwierdzoną matrycą, a nie samodzielnie wymyślać podstawę przetwarzania.

### M2-PRIV-04 — raw CV/PII może trafiać do zewnętrznych providerów

**Dowód w kodzie**

- <code>backend/app/core/config.py:77-84</code>: <code>AI_TEXT_SCHEMA_V2=False</code> domyślnie.
- Legacy builder w <code>embedding_service.py:267-345</code> zawiera imię, nazwisko, AI summary i do 3000 znaków raw CV; tekst jest wysyłany do Voyage.
- Qdrant payload w <code>embedding_service.py:371-389</code> zawsze zapisuje pełne imię i nazwisko, także przy V2.
- <code>canonical_text.py:111-166</code> deklaruje PII-free, lecz w fallbacku umieszcza do 2000 znaków raw CV i nie wykonuje redakcji danych kontaktowych; <code>_PII_FIELDS</code> nie jest egzekwowane.
- <code>cv_parser.py:257-307</code> może wysłać do Anthropic do 8000 znaków surowego CV.
- Produkcyjny healthcheck potwierdził <code>anthropic=configured</code>, ale nie dowodzi, które flow i feature flags są aktywne.

**Rekomendacja**

- fail-closed egress policy registry per provider/purpose/region;
- prawdziwa redakcja kontaktów przed embeddingiem i parsingiem, z canary tests;
- Qdrant payload wyłącznie z pseudonymous candidate ID i bez nazwiska;
- nowa kolekcja Qdrant dla bezpiecznego schematu, reindex i usunięcie starej po potwierdzeniu;
- audit outbound bez treści CV;
- brak zatwierdzonej konfiguracji ma blokować zewnętrzny call, nie wracać do legacy PII path;
- decyzja provider/DPA/region i lawful basis po stronie DPO/security.

**Kryteria akceptacji**

- canary email/telefon/adres nie pojawia się w request payload ani Qdrant;
- raw CV fallback nie omija redakcji;
- nazwa kandydata nie jest częścią vector payload;
- stara kolekcja ma policzalny plan retire;
- config endpoint/admin snapshot pokazuje wyłącznie bezpieczny status, bez sekretów.

### M2-TOKEN-01 — engagement magic-link nie jest bezpiecznie konsumowany

- Token jest przechowywany plaintext i zwracany przez endpoint.
- Publiczny handler sprawdza i aktualizuje bez blokady/atomowego consume; równoległe POST mogą przejść jednocześnie.
- Notes nie mają odpowiedniego limitu i są mieszane z wewnętrznym <code>engagement_notes</code>.

**Rekomendacja i AC**

- przechowywać tylko hash tokena;
- atomowy <code>UPDATE ... WHERE used_at IS NULL AND expires_at &gt; now() RETURNING</code>;
- bounded candidate note jako osobny <code>CandidateDeclaration</code> z actor/source/time;
- drugi concurrent request zwraca jednoznaczne „already used” i nie nadpisuje pierwszego;
- link i endpoint respektują privacy state oraz nie ujawniają profilu.

## 7.3. Intake, tożsamość, deduplikacja i lineage

### M2-INTAKE-01 — public apply może przejąć lub zatruć istniejący profil

**Dowód w kodzie**

<code>backend/app/api/public_share.py:273-468</code> po emailu odnajduje istniejącego Candidate, a następnie może:

- nadpisać imię i nazwisko;
- dopisać dane kontaktowe;
- dokleić wiadomość do <code>ai_summary</code>;
- zmienić <code>created_by</code> na właściciela linku;
- zastąpić CV i <code>raw_cv_text</code>;
- dodać stage i source event.

Formularz <code>frontend/src/app/apply/[token]/ApplyForm.tsx</code> nie utrwala privacy notice version, processing context ani potwierdzenia zapoznania. Link jest multi-use, a email nie jest weryfikowany jako własność istniejącego kandydata.

**Rekomendacja**

- każda aplikacja tworzy immutable <code>CandidateSubmission</code>/<code>CandidateApplication</code>;
- anonimowa aplikacja nigdy nie mutuje kanonicznego Candidate;
- dokument jest nową revision powiązaną z submission;
- deterministic identity match może zasugerować Candidate, ale merge wymaga email proof albo autoryzowanej decyzji;
- owner Candidate nie zmienia się automatycznie;
- stage powstaje dopiero po bezpiecznym accept/merge;
- <code>idempotency_key</code> i constraint chronią double-submit;
- privacy metadata jest zapisana z submission.

**Kryteria akceptacji**

- osoba znająca email nie może zmienić istniejącego profilu ani CV;
- publiczne zgłoszenie tworzy osobny rekord i status review/accepted/rejected;
- double-submit nie tworzy drugiego submission/stage/source eventu;
- merge ma actor, reason, before/after manifest i audit;
- aktywny link ma limit użyć, expiry i rate limit;
- test utrwalający ownership transfer zostaje zastąpiony testem bezpieczeństwa.

### M2-ID-01 — dedup jest nieatomowy i zależy od ścieżki

**Dowód w kodzie**

- <code>Candidate.email</code> ma raw case-sensitive unique; phone/LinkedIn nie mają pełnych unique constraints.
- <code>dedup_service.py</code> wykonuje aplikacyjny lookup, ale nazwa jest tylko lower/trim, bez jednego NFC/alias contract.
- manual create i bulk import tworzą Candidate bez centralnego dedup.
- from-CV ma <code>force=true</code>, a frontend pozwala kontynuować po miękkim ostrzeżeniu.
- check-then-insert nie chroni dwóch równoległych requestów.
- name-only score 0.90 może fałszywie łączyć osoby.
- migracja <code>0106_candidate_linkedin_slug.py</code> dokumentuje historyczne realne grupy duplikatów i uszkodzone slugi, ale aktualna liczebność wymaga SQL.

**Docelowy kontrakt**

<code>candidate_identities</code>:

- <code>candidate_id</code>;
- type: email, phone, linkedin, external;
- normalized value i opcjonalnie display value;
- source, verified_at, confidence, first_seen, last_seen;
- partial unique dla zweryfikowanych/canonical identities;
- osobne unique <code>(source, external_id)</code>;
- status active/superseded/disputed.

<code>candidate_identity_reviews</code>:

- incoming submission/intake ID;
- candidates considered i reason codes;
- status pending/resolved/rejected;
- resolver, decision, timestamp;
- brak auto-merge dla ambiguous i name-only.

**Kryteria akceptacji**

- równoległy create i wariant case/Unicode email tworzą maksymalnie jedną tożsamość;
- znormalizowany telefon i LinkedIn mają deterministyczny wynik;
- wiele external identities pozostaje zachowane;
- collision daje 409/review, nigdy arbitralne <code>.limit(1)</code>;
- override wymaga capability, reason i audytu;
- placeholder <code>? ?</code> nie uczestniczy w name auto-merge.

### M2-ID-02 — obecny merge może usuwać poprawną historię

<code>backend/scripts/merge_duplicate_candidates.py</code> dynamicznie wyszukuje tabele z <code>candidate_id</code>. Jeżeli zbiorczy UPDATE tabeli trafi na choć jeden konflikt unique, kod rollbackuje update tej tabeli, a następnie usuwa wszystkie rows duplikatu w tej tabeli. W ten sposób jeden konflikt może spowodować utratę innych, niekolidujących rekordów.

**Rekomendacja**

- product-grade <code>CandidateMergeService</code>, nie uniwersalny SQL sweep;
- jawna policy per tabela: reparent, dedupe by natural key, preserve both, summarize, block;
- dry-run manifest z licznikami pre/post;
- <code>merged_into_candidate_id</code> i redirect ze starego ID;
- merge event immutable;
- storage, Qdrant, identities, source lineage i privacy records w manifest;
- backup/rollback plan przed batch merge.

**Kryteria akceptacji**

- fixture z jednym conflicting i jednym non-conflicting child row zachowuje ten drugi;
- drugi run jest no-op;
- aktywny kontrakt lub legal hold może zablokować automatyczny merge;
- żadne dziecko nie jest usuwane bez jawnej table policy;
- stare linki prowadzą do kanonicznego profilu z informacją audytową dla uprawnionej roli.

### M2-ID-03 — lineage i source attribution są niepełne

<code>Candidate.source</code> jest scalar first-touch, <code>CandidateSourceEvent</code> jest marketingowym touch, a external ID bywa nadpisywany przez import. Source event:

- nie ma <code>created_by</code>;
- nie ma idempotency key;
- pozwala callerowi arbitralnie ustawić <code>captured_at</code>;
- nie wymusza spójności candidate–job;
- raport może przypisać hire do wielu touches kandydata, nawet jeśli hire dotyczy innego Job.

**Rekomendacja**

Rozdzielić:

- <code>CandidateIntakeEvent</code> — techniczne wejście i payload hash;
- <code>CandidateExternalIdentity</code> — trwałe source record ID;
- <code>CandidateSourceEvent</code> — marketing/recruitment touch;
- <code>CandidateFieldProvenance</code> — skąd pochodzi konkretna wartość;
- <code>CandidateApplication</code> — candidate + konkretny Job;
- atrybucję first-touch/last-touch/application-touch z jawną definicją.

**Kryteria akceptacji**

- retry importu nie duplikuje eventu;
- każde zdarzenie ma aktora albo source system;
- backdate wymaga jawnego import context i przechowuje received_at osobno;
- job-bound source jest liczony jako hire tylko dla tego samego candidate + job;
- raport pokazuje zastosowany model atrybucji.

### M2-IMP-01 — Traffit może przesunąć watermark mimo błędów

**Dowód w kodzie**

- <code>backend/app/tasks/traffit_sync.py:330-379</code> zapisuje <code>last_synced_at=run_start</code> także przy błędach i kontynuuje zależne fazy.
- Importer commitujący batch może rollbackować wcześniejsze elementy po pojedynczym wyjątku, podczas gdy liczniki/in-memory map są już przesunięte.
- Po wyjściu rekordu poza 48-godzinny overlap błąd może nie zostać ponownie pobrany.

**Stan nowego fundamentu**

Commit <code>bbee39e</code> dodał runs/phases, cursors, outbox/inbox, conflicts i leases, z env gates OFF i dry-run ON. Commit <code>e25225b</code> dodał czysty, dobrze przetestowany 3-way merge z <code>MISSING ≠ null</code>, nested paths i conflict preservation. To dobry kierunek, ale kierunki integracji nadal są OFF, a legacy watermark problem nie jest przez sam merge naprawiony.

**Rekomendacja**

- SAVEPOINT per item albo atomowy committed batch;
- counters aktualizowane dopiero po commit;
- phase <code>complete=true</code> tylko po spełnieniu warunków sukcesu;
- watermark przesuwany wyłącznie po krytycznych fazach complete;
- dependency skip po failed phase;
- durable row error/dead-letter z safe fingerprint;
- shadow run na nowych tabelach przed aktywacją inbound/outbound;
- file reconcile po source manifest/hash, nie tylko „czy istnieje jakikolwiek dokument”.

**Kryteria akceptacji**

- injected row failure nie cofa poprzednio zatwierdzonych rows;
- counts odpowiadają DB;
- watermark pozostaje poprzedni po błędzie krytycznym;
- retry obejmuje błąd po upływie zwykłego lookback;
- wszystkie nowe env gates pozostają OFF do zatwierdzonego canary.

### M2-DATA-01 — walidacja modeli i liczniki pomocnicze mogą dryfować

**Potwierdzone problemy**

- <code>NoteCreate</code> może nie wskazać ani candidate, ani Job; API nie wymusza poprawnej relacji.
- Globalna lista notes nie ma pełnego bounded pagination contract.
- <code>candidate.notes_count</code> rośnie przy create, ale delete nie koryguje go w tej samej ścieżce.
- Szeroki <code>CandidateUpdate</code> dopuszcza jawne <code>null</code> dla części pól, które DB traktuje jako wymagane; zamiast 422 może powstać 500.
- Stawki, salary, lata doświadczenia i currency nie mają wszędzie jednolitego positive/range/currency contract.
- Część JSONB jest typowana jako dict, ale historyczne/default shapes bywają listą lub swobodnym <code>Any</code>.
- Brak optimistic version pozwala dwóm edycjom nadpisać się last-write-wins.

**Rekomendacja i AC**

- use-case-specific create/update schemas z required relation i field constraints;
- orphan note = 422; candidate/job relation weryfikowana;
- notes_count jako SQL aggregate albo atomowo utrzymywany i okresowo reconciled;
- delete notatki daje poprawny count;
- money/rate przez wspólny typed value i <code>Decimal</code>, z ISO currency;
- JSONB zastępować versioned typed facts w krytycznych polach;
- <code>Candidate.version</code>/<code>If-Match</code>; konflikt edycji = 409, nie ciche nadpisanie;
- testy malformed/null/negative/wrong-shape nie kończą się 500.

## 7.4. Dokumenty, ekstrakcja, import i eksport

### M2-DOC-01 — kilka konkurencyjnych źródeł CV

Obecnie istnieją równolegle:

- lokalny <code>UPLOAD_DIR</code> i <code>cv_filename</code>;
- legacy <code>Candidate.cv_file_content</code>;
- <code>Candidate.cv_storage_key</code>;
- <code>CandidateDocument.file_content</code>;
- <code>CandidateDocument.storage_key</code>;
- per-stage CV snapshot.

Pojedynczy download, bulk ZIP, lista dokumentów, profile UI i <code>cv_source</code> stosują różne priorytety. Frontend potrafi pobrać <code>/documents</code>, ale nadal warunkuje kartę po legacy <code>cv_filename</code>. Kandydat z prawidłowym document może wyglądać jak osoba bez CV.

**Rekomendacja**

- <code>CandidateDocument</code> jako jedyna prawda binary;
- immutable revision i dokładnie jeden aktywny primary;
- <code>Candidate.document_summary</code> w DTO, bez legacy gate;
- legacy read adapter tylko na czas migracji;
- stage snapshot wskazuje konkretną revision/hash;
- upload/replace/set-primary/archive w jednym serwisie;
- cleanup przez outbox;
- po backfillu usunąć direct local/BYTEA writes.

**Kryteria akceptacji**

- wszystkie surface wybierają ten sam primary document;
- kandydat z document i <code>cv_filename=NULL</code> poprawnie pokazuje CV;
- dokładnie jeden primary jest wymuszony constraint/transakcją;
- failed replacement zostawia stary primary;
- rollback nie pozostawia orphan object;
- usunięcie wersji respektuje retention/legal hold.

### M2-DOC-02 — upload i parser nie mają jednego bezpiecznego pipeline’u

**Potwierdzone problemy**

- request bywa czytany w całości przed limitem;
- walidacja akceptuje MIME **lub** rozszerzenie, bez magic-byte contract;
- from-CV używa deterministycznej nazwy temp, więc równoległe takie same filename mogą kolidować;
- zapis pliku i DB nie są jedną niezawodną operacją;
- stary plik może zostać po replacement;
- bulk ZIP buduje całość w pamięci do 200 plików;
- CV import tworzy aktywnego Candidate przed review wyniku;
- extraction nie ma twardego document revision precondition;
- nie wszystkie pola respektują manual authority.

**Docelowy pipeline**

1. Bounded streaming do quarantine object key.
2. Limit per file i per batch przed pełną alokacją.
3. Sanityzacja filename tylko do display; storage key losowy.
4. Detekcja MIME z magic bytes i zgodność z allowlistą.
5. Malware scan/quarantine state.
6. SHA-256 i idempotency.
7. Utworzenie <code>CandidateDocument revision</code>.
8. Async extraction run z <code>document_revision</code> i content hash.
9. Parse do draft facts.
10. Zastosowanie tylko, jeśli revision nadal aktualna i authority pozwala.
11. Cleanup quarantine/orphan przez outbox/reconciler.

**Kryteria akceptacji**

- oversized/spoofed file jest odrzucony przed parsingiem;
- dwa równoległe pliki o tej samej nazwie nie kolidują;
- ten sam content hash nie tworzy drugiej wersji bez jawnej potrzeby;
- starszy extraction result nie nadpisuje nowszego dokumentu;
- manual/verified field wygrywa z AI/import;
- failed N-ty element batcha jest retryable i nie psuje zatwierdzonych elementów;
- download ma <code>Content-Disposition</code>, <code>X-Content-Type-Options: nosniff</code> i autoryzację;
- duży ZIP jest background exportem ze streamem i całkowitym limitem.

### M2-EXP-01 — eksport jest za szeroki i podatny na formula injection

**Dowód**

- legacy GET export może ładować do 50 000 ORM rows;
- pola kontrolowane przez kandydata trafiają do CSV/XLSX bez neutralizacji prefixów <code>=</code>, <code>+</code>, <code>-</code>, <code>@</code>;
- openpyxl może potraktować <code>=...</code> jako formułę;
- eksport nie ma osobnego permission/purpose/audit;
- szeroki ORM może pobierać raw CV/BLOB mimo że eksport ich nie potrzebuje.

**Rekomendacja i AC**

- jeden POST background export z frozen filter snapshot;
- special capability, reason/purpose, expiry download i audit;
- jawna SQL projection bez raw CV/BLOB;
- sanitization wszystkich untrusted string cells;
- <code>=HYPERLINK(...)</code> pozostaje inert text w CSV i XLSX;
- limit rows/bytes i bezpieczna paginacja cursorowa;
- legacy GET endpoint wycofany po okresie kompatybilności.

## 7.5. Dostępność, eligibility, pule, marketplace i źródła

### M2-ELIG-01 — wiele pól próbuje odpowiedzieć na to samo pytanie

Candidate przechowuje równolegle:

- sourcing status: active/passive/blacklisted;
- <code>availability_status</code>;
- availability date i notice;
- engagement flags/timestamps/notes;
- preferences i excluded clients;
- contracts i employment state;
- CandidateConflict;
- pipeline state;
- data completeness i freshness.

Nowy <code>candidate_job_eligibility.py</code> jest dobrym, czystym zalążkiem, ale nie jest używany przez wszystkie write paths. Marketplace auto-sync patrzy głównie na availability, nie na pełny privacy/blacklist/conflict contract. Reverse scan może objąć kandydata, który nie powinien być kontaktowany.

**Rekomendacja**

Wprowadzić rozdzielone osie:

- <code>CandidateLifecycleStatus</code>: draft/quarantined/active/archived/merged;
- <code>CandidatePrivacyState</code>: permitted/restricted/retention_review/erasure_pending;
- <code>CandidateAvailabilityClaim</code>: value/source/observed_at/expires_at;
- <code>CandidateEmploymentState</code>: derived from contracts;
- <code>CandidateJobEligibility</code>: candidate + konkretny Job;
- <code>CandidateMarketabilityDecision</code>: searchable/contactable/marketplace_eligible/client_shareable/assignable + reason codes.

**Kryteria akceptacji**

- do-not-contact/restricted nigdy nie trafia do contact/marketplace/client share;
- hard conflict zawsze blokuje konkretny Job;
- stale availability wygasa do unknown;
- wszystkie entrypointy add-to-job używają tej samej decyzji;
- decyzja jest explainable i nie loguje PII;
- blacklisted nie jest używane jako zamiennik privacy erase.

### M2-POOL-01 — pule talentów nie mają właściwej własności ani pełnej paginacji

- Każdy zalogowany użytkownik może tworzyć i edytować firmową pulę.
- Personal pools są widoczne dla całego zespołu, a firmowe nie mają ACL/team scope.
- Member endpoint domyślnie kończy się na 500; frontend nie ma pełnej pagination/search/sort.
- Błąd query często wygląda jak pusta pula.

**Docelowy kontrakt**

- visibility: personal/team/organization/system;
- personal: owner/admin write;
- team/org: jawna capability;
- marketplace: system-managed, ręczne operacje tylko przez dedykowany service;
- membership zawsze sprawdza marketability/privacy;
- cursor pagination, server search/sort i URL state;
- error, empty i permission-denied jako różne stany.

### M2-MKT-01 — marketplace ma drift progów, danych i zachowania

**Potwierdzone**

- frontend <code>page.tsx:84</code> mówi score ≥ 70;
- <code>backend/app/core/config.py:236</code> ma default 80;
- production pokazała 18 „szukających”, bez jednego wyniku powyżej progu, i 5 ręcznych wpisów ze statusem „Nieznany”;
- seeking-contractors i marketplace korzystają z różnych candidate text/source paths;
- candidate selection/cap może być niedeterministyczny;
- owner ręcznego wpisu nie zawsze odzwierciedla osobę, która wystawiła na targ;
- remove nie ma pełnego confirm/undo/error UX;
- seeking board pobiera sztywne 50 bez dalszej paginacji.

**Rekomendacja**

- threshold i jego znaczenie zwraca backend jako część kontraktu;
- jeden canonical text/query/eligibility path przed tuningiem score;
- deterministic sort przed cap/pagination;
- <code>marketplace_membership</code> ma <code>added_by</code>, <code>source</code>, <code>reason</code>, <code>observed_at</code>, <code>expires_at</code>;
- status availability pokazuje źródło i świeżość;
- zero-match actions disabled z wyjaśnieniem;
- paginacja seeking i marketplace;
- remove z confirmation, undo lub bezpiecznym restore.

**Kryteria akceptacji**

- UI nigdy nie hardcoduje progu;
- ten sam kandydat i Job mają ten sam eligibility/text input we wszystkich surface;
- total i pagination są deterministyczne;
- wpis z expired/stale availability znika lub trafia do review;
- error API nie jest wyświetlany jako „0 kandydatów”;
- hard conflicts nie dają się ominąć.

### M2-SRC-01 — atrybucja źródeł może zawyżać skuteczność kanałów

Raport source funnel uznaje kandydata za hired, jeżeli ma hired stage w okresie, bez wystarczającego powiązania z <code>source_event.job_id</code>. Jeden hire może więc zostać przypisany do kilku niezwiązanych touches.

**Rekomendacja i AC**

- job-bound attribution po candidate + job/application;
- jawny model first-touch, last-touch albo application-touch;
- source event immutable, idempotentny i z aktorem;
- correction jako nowy event;
- raport pokazuje denominator, attribution model i data freshness;
- test: source dla Job A nie dostaje hire z Job B.

## 7.6. Search, index i wydajność

### M2-SEARCH-01 — V3 jest kontraktem, ale nie jednym silnikiem

- <code>CandidateSearchQueryV3</code> definiuje lepsze units i unknown policy, lecz endpointy nadal używają różnych requestów.
- Istnieją osobne list filters, advanced search, FTS, hybrid, semantic, saved search, pools i marketplace.
- Hybrid pool ma hard cap 200; późniejsze strony mogą być puste mimo większego total.
- JSONB cast + substring może dopasować Java do JavaScript.
- Language code i level mogą pochodzić z innych obiektów JSON.
- <code>has_cv</code> patrzy na legacy <code>cv_filename</code>.
- diagnostics są dostępne zbyt szeroko i mogą ujawniać rozkład danych.

**Rekomendacja**

- V3 jako jedyny request AST i executor;
- canonical SkillFact/LanguageFact/taxonomy IDs;
- jawne strict/lenient unknown semantics;
- <code>has_document</code> przez EXISTS aktywnego CandidateDocument;
- cursor pagination dla hybrid/search;
- permission-aware projection i diagnostics capability;
- saved search przechowuje versioned V3 JSON.

**Kryteria akceptacji**

- ten sam V3 query zwraca te same ID we wszystkich surface;
- Java nie matchuje JavaScript bez jawnego aliasu;
- EN/B2 musi pochodzić z tego samego fact;
- total i kolejne strony są prawdziwe;
- viewer nie dostaje PII ani wewnętrznych diagnostics;
- legacy adapter ma testy parytetu i jawny sunset.

### M2-INDEX-01 — profil może pozostać nieaktualny w search/Qdrant

Lista pól invalidujących match cache pomija m.in. część stawek, lat doświadczenia, AI summary, experience, competence facts, languages, availability i notice. Create/update nie zawsze enqueue re-embedding. Outbox helper potrafi sam commitować mimo kontraktu caller transaction, a worker może być OFF przy enqueue ON.

**Rekomendacja**

- domain event w tej samej transakcji co zmiana źródła;
- jeden manifest pól wpływających na search/matching;
- desired revision/content hash;
- coalescing do latest revision;
- invariant: enqueue i worker config nie mogą tworzyć nieskończonego lag bez health degradation;
- bezpieczna V2/V3 kolekcja bez PII;
- admin metrics coverage/lag/dead.

**Kryteria akceptacji**

- każda istotna zmiana generuje dokładnie latest reindex revision;
- nowy kandydat staje się searchable w SLO;
- starszy event nie nadpisuje nowszego;
- worker-off przy rosnącej kolejce degraduje health/admin snapshot;
- DB↔Qdrant coverage jest mierzalne.

### M2-PERF-01 — listy i eksporty pobierają za dużo danych

**Potwierdzone problemy**

- <code>Candidate.raw_cv_text</code> i część legacy binary nie są konsekwentnie deferred;
- list options eager-loadują szeroki graph contracts/conflicts/stages/job/client/creator/pools/snapshots;
- search snippets pobierają notes dla strony;
- match stats może liczyć wiele score w request listy i używa capped jobs jako total;
- export ładuje do 50 000 ORM rows;
- global search ma dodatkowe lookupy klientów.

**Rekomendacja i budżety**

- jawne SQL projections list/detail/export;
- raw CV/BLOB zawsze deferred i tylko w dedykowanym serwisie;
- SQL aggregates zamiast pełnych relacji;
- bounded notes query i top-N snapshot w SQL;
- match stats w async/cache, nie O(candidates × jobs) podczas listy;
- cursor exports i background jobs;
- test query count/bytes oraz p95 budgets przed i po.

## 7.7. Frontend, UX, dostępność i testy

### M2-FE-01 — formularz traci notatkę, a LinkedIn używa złego pola

- <code>frontend/src/components/AppShell.tsx</code> renderuje <code>notes</code>, ale <code>candidateFormToPayload()</code> ich nie wysyła.
- Profil sprawdza <code>candidate.linkedin_url</code>, podczas gdy DTO używa <code>linkedin</code>.
- Dedup failure potrafi ustawić stan „sprawdzone” i pozwala zapisać.
- Lookup users/clients może wyglądać jak prawidłowa pusta lista po błędzie.

**Rekomendacja i AC**

- notatka jako osobny timeline command po create albo usunięcie pola do czasu wsparcia;
- typed generated DTO lub wspólne schema contract;
- LinkedIn tylko bezpieczny <code>https</code> URL;
- create blokuje się przy niedostępnym dedup service, z retriable state;
- lookup error różni się od empty;
- wpisana notatka jest po reopen albo pole nie istnieje.

### M2-FE-02 — stale/error jest prezentowane jako prawda biznesowa

W wielu miejscach error zamienia się w:

- „Brak źródeł”;
- pustą pulę;
- zero matchy;
- brak saved searches/stages;
- pusty marketplace.

Dodatkowo <code>CandidateEngagementPanel</code> i <code>CandidateLocationPanel</code> resetują lokalny draft przy zmianie referencji inline <code>initial</code>; refetch rodzica może wyczyścić wpisywany tekst. Część mutations nie ma <code>onError</code>, a błąd magic-link jest połykany.

**Rekomendacja i AC**

- wspólny <code>Loading/Empty/Error/Permission/Degraded</code> state;
- reset draft tylko po candidate ID/server version, z dirty guard;
- centralna invalidacja candidate query keys;
- każda mutation ma success/error toast i retry;
- HTTP 500 nigdy nie wygląda jak empty;
- unrelated refetch nie usuwa wpisywanych zmian.

### M2-FE-03 — list/search/compare mają błędy kontraktu

- page z URL nie jest zawsze clampowany do dodatniej liczby;
- bulk compare po cichu bierze pierwsze trzy ID;
- advanced search nie ma pełnego URL/deep-link state i może zostawić stare wyniki pod nowymi filtrami;
- selection między stronami istnieje, ale compare patrzy tylko na bieżące <code>data.items</code>;
- link wyniku nie zachowuje kontekstu Job;
- compare uruchamia <code>useQuery</code> wewnątrz <code>ids.map</code>, łamiąc Rules of Hooks;
- compare pokazuje wymyślone procenty kompletności/skills bez zatwierdzonej metryki.

**Rekomendacja i AC**

- versioned URL codec i clamp;
- React Query z AbortSignal i jawnym stale/error;
- selection store po ID oraz batch fetch wybranych;
- <code>useQueries</code> i jawny limit porównania;
- <code>from=job&jobId=...</code> zachowany;
- brak cichego truncation;
- żadnego procentu bez backendowego, opisanego metric ID/version;
- refresh/back/share reprodukują ten sam query state.

### M2-UX-01 — import, marketplace i legacy modal wymagają hardeningu

Potwierdzone przykłady:

- custom modal bez pełnego dialog semantics/focus trap/Escape;
- labels nie zawsze są związane z input;
- dropzone sprawdza <code>e.key === ""</code> zamiast spacji;
- copy obiecuje 10 MB, ale klient sprawdza głównie rozszerzenie;
- CVDropzone może uruchomić równoległe requesty i starszy response nadpisze nowszy;
- marketplace remove nie ma confirm/onError, search strzela per znak, Fragment ma błędny key placement;
- Seeking Board ma sztywne 50, martwe „Pokaż wszystkie” i <code>alert()</code>;
- hardcoded palette classes i angielskie/raw statusy omijają tokeny/i18n.

**Rekomendacja**

- DS Dialog/FormGroup/token-only;
- shared file validator i accessible dropzone;
- abort/latest-request guard;
- server pagination/debounce/URL state;
- standard confirm, toast, retry i cache invalidation;
- status dictionary PL;
- responsive table wrapper i mobilne kontrakty.

### M2-TEST-01 — wymagany CI nie uruchamia pełnego modułu

<code>.github/workflows/ci.yml:98-189</code> ma ręcznie wybraną listę. Od <code>e25225b</code> uruchamia pięć suite’ów Traffit, w tym sync/integration/merge, ale nadal pomija m.in. istotne testy candidate core, from-CV, LinkedIn, export V2, talent pools API, invite links, bulk CV i część stage CV. Frontend ma helper/quick-view tests, ale brakuje integracji dla głównych ekranów CandidateList, CandidateDetail, Search, Add/Edit, import, Talents, Marketplace i Seeking.

**Rekomendacja**

- marker/directory gate <code>module_candidates</code> zamiast rosnącej ręcznej listy;
- collection check w CI potwierdzający obecność security suites;
- nie akceptować testu, który uznaje 500 za prawidłową odpowiedź;
- kontraktowe testy wszystkich intake i add-to-job entrypointów;
- security matrix, concurrency, storage rollback, formula injection, privacy executor i importer partial failure jako wymagane.

---

## 8. Docelowa architektura modułu

### 8.1. Główne byty

| Byt | Odpowiedzialność | Najważniejsze pola/inwarianty |
|---|---|---|
| <code>Candidate</code> | Kanoniczny, szybki profil operacyjny | lifecycle, current display facts, merged_into, optimistic version; bez binary jako prawdy |
| <code>CandidateSubmission</code> | Immutable wejście manual/public/import | source, source_record_id, payload_hash, idempotency_key, received_at, privacy context, status |
| <code>CandidateIdentity</code> | Znormalizowana tożsamość osoby | type, normalized value, verified/confidence, source, active/superseded/disputed |
| <code>CandidateIdentityReview</code> | Niejednoznaczne dopasowania | submission, candidates considered, reason codes, decision, resolver |
| <code>CandidateExternalIdentity</code> | Wiele identyfikatorów systemów źródłowych | unique source + external_id → jeden candidate |
| <code>CandidateDocument</code> | Jedyna prawda o pliku i wersji | object key, hash, detected MIME, size, revision, primary, scan/extraction state |
| <code>CandidateExtractionRun</code> | Wynik parsera dla konkretnej revision | document revision/hash, extractor version, status, result, stale-discard |
| <code>CandidateFieldProvenance</code> | Źródło i authority pola | field path, source event, confidence, observed_at, manual lock/superseded |
| <code>CandidatePrivacyEvent/State</code> | Techniczny ledger przetwarzania | purpose/basis/notice/source, restriction, DNC, retention, legal hold, DSAR |
| <code>CandidateAvailabilityClaim</code> | Czasowa deklaracja dostępności | status, source, observed_at, expires_at, note, superseded |
| <code>CandidateSourceEvent</code> | Marketing/recruitment touch | actor/source, candidate, optional application/job, idempotency, captured/received |
| <code>CandidateMerge</code> | Audytowalne scalenie | survivor, duplicate, manifest, policy version, actor, result |
| <code>CandidateApplication</code> | Powiązanie kandydata z konkretnym Job | source submission, status, add-to-job idempotency, CV revision |
| <code>CandidateOutboxEvent</code> | Niezawodne side effects | aggregate/revision, destination, attempts, status, no raw PII in log |

### 8.2. Serwisy domenowe

- <code>CandidateAccessPolicy</code> — capability i projekcja odpowiedzi.
- <code>CandidateIntakeService</code> — wspólny kontrakt wszystkich adapterów.
- <code>CandidateIdentityResolver</code> — deterministic match albo review; nigdy arbitralny merge.
- <code>CandidateMergeService</code> — policy per child table.
- <code>CandidateDocumentService</code> — upload, version, primary, scan, cleanup.
- <code>CandidateEnrichmentService</code> — revision-aware extraction i field authority.
- <code>CandidatePrivacyService</code> — current state i gates.
- <code>CandidatePrivacyExecutor</code> — manifest/dry-run/execute/retry.
- <code>CandidateAvailabilityService</code> — claims, expiry i derived current value.
- <code>CandidateMarketabilityService</code> — decyzje per surface i Job.
- <code>CandidateSearchV3Executor</code> — jeden AST/query contract.
- <code>AddCandidateToJobService</code> — jedna idempotentna komenda graniczna.

### 8.3. Authority pól

Rekomendowana kolejność, którą można nadpisać tylko jawną policy per field:

1. ręczna wartość zweryfikowana przez uprawnionego użytkownika;
2. deklaracja kandydata z ważnego self-service tokena;
3. zweryfikowany system źródłowy z field contract;
4. import source bez weryfikacji;
5. AI extraction;
6. heurystyka/regex.

Każdy update ma zachować <code>source</code>, <code>observed_at</code>, <code>authority</code> i <code>superseded_by</code>. AI nie może nadpisać ręcznie zweryfikowanej wartości.

---

## 9. Docelowa macierz uprawnień

Poniższa tabela jest rekomendacją techniczną; dokładne nazwy ról i globalny vs team scope wymagają zatwierdzenia biznesowego.

| Operacja | Anonymous | user/client | sourcer/recruiter | TAC/DL/HoR | admin/privacy officer |
|---|---:|---:|---:|---:|---:|
| Public application | Tylko token | — | — | — | — |
| Global search summary | Nie | Nie; tylko jawny client share | Tak, safe projection | Tak | Tak |
| Contact details | Nie | Nie | Tak w zatwierdzonym scope | Tak | Tak |
| CV view/download | Nie | Nie | Tak w zatwierdzonym scope | Tak | Tak |
| Rates/finance | Nie | Nie | Domyślnie nie | Zależnie od capability | Tak |
| JDG/legal data | Nie | Nie | Nie | Wybrane role | Tak |
| Create/update profile | Nie | Nie | Tak, pola operacyjne | Tak | Tak |
| Add note/source/pool | Nie | Nie | Tak w scope | Tak | Tak |
| Corporate pool create | Nie | Nie | Zależnie od capability | Tak | Tak |
| Export | Nie | Nie | Domyślnie nie | Z reason + audit | Tak |
| Merge | Nie | Nie | Propose only | Wybrane role | Tak |
| Archive/do-not-contact | Nie | Nie | Propose/operacyjne DNC | Tak | Tak |
| Privacy execute/erase | Nie | Nie | Nie | Nie bez privacy capability | Tak + reauth/approval |
| Hard conflict override | Nigdy | Nigdy | Nigdy | Nigdy | Tylko correction event, nie bypass |

Zasady:

- permission ma uwzględniać union primary i secondary roles;
- bycie ownerem nie daje prawa do privacy erase ani danych prawnych;
- client-facing view jest osobnym, jawnie udostępnionym artefaktem, nie ogólnym Candidate DTO;
- 403/404 nie mogą umożliwiać enumeracji;
- middleware frontendowy ma poprawiać UX, ale nie zastępuje backendu;
- <code>/sourcing/marketplace</code> należy dodać do protected routes.

---

## 10. Inwarianty, których system ma zawsze pilnować

1. Anonimowy lub niezweryfikowany submission nigdy nie mutuje kanonicznego Candidate.
2. Retry tego samego intake nie tworzy drugiego Candidate, document, stage ani source eventu.
3. Ambiguous identity nigdy nie jest auto-merge’owana ani wybierana przez <code>.limit(1)</code>.
4. Name-only match jest sugestią, nie podstawą automatycznego merge.
5. <code>(source, external_id)</code> wskazuje dokładnie jednego kandydata, a kandydat może mieć wiele takich identyfikatorów.
6. CandidateDocument/object storage jest jedyną prawdą binary; aktywny kandydat ma maksymalnie jeden primary document.
7. Extraction result stosuje się tylko do tej samej document revision/content hash.
8. Manual/verified fact ma wyższy authority niż import, AI i heurystyka.
9. Privacy state jest sprawdzany przed search PII, contact, export, embedding, marketplace, client share i add-to-job.
10. Twarde NDA/blacklist/competitor conflicts są zawsze fail-closed i nie mają user-controlled bypass.
11. Availability bez świeżego źródła i expiry wraca do unknown.
12. Wszystkie surface używają jednej marketability/eligibility policy i reason codes.
13. Add-to-job jest jedną idempotentną komendą, tworzącą właściwy stage, source/application, activity, CV snapshot i outbox.
14. Żaden operacyjny endpoint nie wykonuje hard delete Candidate.
15. Privacy executor ma manifest wszystkich stores, w tym local legacy, object storage, Qdrant, telemetry i integracje Traffit.
16. Watermark importu przesuwa się tylko po commit i sukcesie wszystkich krytycznych faz.
17. Outbox event powstaje w tej samej transakcji co zmiana źródłowa; worker nie przetwarza starej revision nad nowszą.
18. Eksport i download wymagają capability oraz audytu; eksportowane komórki nie wykonują formuł.
19. Error API nigdy nie jest prezentowany jako prawidłowy empty state.
20. Search total, sort i pagination są deterministyczne i nie ukrywają hard capu.

---

## 11. Plan implementacji — dokładnie 7 PR-ów

Każdy PR ma być mały w sensie jednej odpowiedzialności i odwracalnego rollout’u, nawet jeśli zawiera kilka warstw potrzebnych do zamknięcia tej odpowiedzialności. Claude nie powinien otwierać jednego megapr-a obejmującego cały dokument.

Wspólne zasady dla wszystkich PR-ów:

- zacząć od aktualnego <code>origin/main</code> i sprawdzić, czy zakres nie został już wdrożony;
- zachować niezwiązany lokalny WIP;
- nie używać lokalnego Dockera;
- przy każdej tabeli/kolumnie: Alembic z <code>upgrade heads</code> oraz wymagane idempotentne lustro w <code>backend/entrypoint.sh</code>;
- feature flags mają domyślnie być OFF, z wyjątkiem poprawek P0, których flaga nie może przywracać niebezpiecznego zachowania;
- każdy PR: focused host-native checks → push → PR → wymagany CI → merge → deploy → exact-SHA health → produkcyjny curl/Chrome;
- nie usuwać legacy storage/kolumn do czasu zakończenia dual-read, backfillu i okresu stabilizacji;
- logi i telemetry nie mogą zawierać PII ani treści CV.

## PR 1/7 — P0 containment, CandidateAccessPolicy i fail-closed conflicts

### Cel

Natychmiast zamknąć możliwość masowego odczytu/mutacji przez viewerów i wyłączenia hard NDA/blacklist. Ten PR nie czeka na nowy model privacy ani pełny redesign.

### Zakres backendu

1. Utworzyć centralne capability/dependencies, np.:
   - <code>CandidateSearchAccess</code>;
   - <code>CandidatePIIAccess</code>;
   - <code>CandidateDocumentAccess</code>;
   - <code>CandidateExportAccess</code>;
   - <code>CandidateWriteAccess</code>;
   - <code>CandidateFinanceAccess</code>;
   - <code>CandidatePrivacyExecuteAccess</code>.
2. Capability muszą korzystać z union primary i secondary roles, a nie tylko <code>user.role</code>.
3. Zastąpić <code>CurrentUser</code> we wszystkich trasach modułu zgodnie z macierzą:
   - candidates list/detail/search;
   - documents/content/presigned URL/CV ZIP;
   - export;
   - notes/source events;
   - talent pools/marketplace;
   - rate/legal mutations;
   - recommendations add-to-job.
4. Wprowadzić bezpieczną projekcję list/search; nie zwracać pól wrażliwych jako przypadkowego superset DTO.
5. Zablokować <code>anonymize_pii</code> do czasu PR 2; odpowiedź ma być jednoznaczna i testowana.
6. Wyłączyć operacyjny hard delete; zastąpić tymczasowo archive albo 409 „privacy workflow required”.
7. W <code>recommendation_filters</code> zawsze ładować i egzekwować hard conflicts; usunąć wpływ user flag na hard set.
8. Użyć istniejącego mechanizmu audit albo dodać minimalny immutable event dla:
   - export requested/completed/downloaded;
   - CV/document downloaded;
   - denied sensitive operation;
   - bulk operation preview/execute.
9. Nie logować query payload zawierającego PII.

### Zakres frontendu

1. Dodać <code>/sourcing/marketplace</code> do protected routes.
2. Pobierać capability/current-user permissions i ukryć niedozwolone akcje:
   - import/export/add/invite;
   - edit contact/full profile;
   - bulk actions;
   - pool writes;
   - source mutation;
   - CV download.
3. Usunąć albo przekształcić checkbox hard NDA/blacklist; użytkownik może sterować tylko soft warnings.
4. Dodać jawny 403/permission state, nie generic empty.
5. Nie dodawać client-side „ochrony” jako substytutu API.

### Pliki do rozpoczęcia inspekcji

- <code>backend/app/api/deps.py</code>;
- <code>backend/app/models/user.py</code>;
- <code>backend/app/api/candidates.py</code>;
- <code>backend/app/api/candidates_bulk.py</code>;
- <code>backend/app/api/search.py</code>;
- <code>backend/app/api/notes.py</code>;
- <code>backend/app/api/candidate_sources.py</code>;
- <code>backend/app/api/talent_pools.py</code>;
- <code>backend/app/api/marketplace.py</code>;
- <code>backend/app/api/recommendations.py</code>;
- <code>backend/app/services/recommendation_filters.py</code>;
- <code>backend/app/api/financial_access.py</code>;
- <code>frontend/src/middleware.ts</code>;
- <code>frontend/src/components/v2/pages/CandidatesListV2.tsx</code>;
- <code>frontend/src/components/v2/pages/CandidateDetailV2.tsx</code>;
- <code>frontend/src/app/talents/page.tsx</code>;
- <code>frontend/src/components/sourcing/RecommendationFiltersBar.tsx</code>.

### Testy wymagane w tym PR

- parametryzowana macierz role × endpoint × action;
- primary i secondary role parity;
- viewer list/detail/search/export/CV/document/bulk/pool/source/note = 403 albo zatwierdzona redacted projection;
- body action escalation: zmiana <code>add_tags</code> na <code>anonymize_pii</code> nie omija guarda;
- direct ID enumeration nie ujawnia rekordu;
- <code>industry_blocklist=false</code> nadal usuwa hard conflicts ze wszystkich wyników/countów;
- export/download audit event bez raw PII;
- frontend permission-state tests;
- anonymous marketplace route przekierowuje do login z <code>next</code>.

### Rollout

- security changes wdrożyć od razu po zielonym CI;
- nie tworzyć flagi typu <code>CANDIDATE_RBAC_V2=false</code>, która przywraca <code>CurrentUser</code>;
- jeżeli potrzebny jest rollout projekcji, wolno mieć temporary compatibility endpoint wyłącznie dla jawnie allowlistowanej roli wewnętrznej, z telemetry i krótkim sunsetem;
- po deploy wykonać curl jako konta testowe każdej roli oraz Chrome dla admin/recruiter/viewer.

### Rollback

- rollback UI i formatu DTO jest możliwy;
- zakaz cofania blokady viewer/export/bulk/hard-conflict bez równoważnego server-side guarda;
- awaryjny access grant ma być jawny, czasowy i audytowany, nie globalny bypass.

### Kryteria zakończenia PR 1

- wszystkie P0 endpointy mają capability, nie sam <code>CurrentUser</code>;
- viewer nie czyta PII/CV ani nie mutuje danych;
- pseudo-anonymize i hard delete nie są dostępne jako zwykła akcja;
- hard conflicts są fail-closed;
- wymagane testy naprawdę są uruchamiane w CI;
- produkcja działa na dokładnym SHA PR i Chrome potwierdza różnice ról.

## PR 2/7 — Privacy lifecycle, bezpieczny egress i executor DSAR

### Warunek wejścia

- PR 1 na produkcji;
- zatwierdzona przez DPO/legal minimalna macierz purposes/basis/notice/retention;
- spis providerów i miejsc przechowywania zaakceptowany przez security/ops.

### Cel

Oddzielić lifecycle prywatności od sourcing status i zastąpić pseudo-anonymize/hard delete policzalnym, retry-safe workflow.

### Model danych

Dodać addytywnie:

1. <code>candidate_privacy_events</code>:
   - candidate/subject ID;
   - event type;
   - purpose/scope;
   - basis code zatwierdzony biznesowo;
   - notice version/reference;
   - source/actor;
   - occurred_at/received_at;
   - reason/reference bez surowego PII;
   - supersedes/correlation ID.
2. <code>candidate_privacy_state</code> albo deterministyczny materialized read model:
   - contactable;
   - processing_restricted;
   - do_not_contact;
   - retention_until/next_review_at;
   - legal_hold;
   - erasure status;
   - version.
3. <code>candidate_privacy_requests</code>:
   - type, status, requested/verified/approved/executed timestamps;
   - requester verification reference;
   - approver/actor;
   - idempotency key;
   - policy version.
4. <code>candidate_privacy_artifacts</code>:
   - store/artifact type;
   - stable opaque locator/hash;
   - action planned/result;
   - retained reason;
   - attempts/error class;
   - completed_at.

Nie zapisywać pełnego request payload zawierającego PII w audit/log.

### Privacy executor

1. Tryb <code>preview</code> tworzy manifest bez mutacji.
2. Approval/reauth wymagane dla irreversible execute.
3. Worker wykonuje idempotentnie:
   - Candidate direct identifiers;
   - documents i legacy storage;
   - notes/activities/calls/chats zgodnie z policy;
   - Qdrant points/payload;
   - LinkedIn snapshots;
   - source/UTM/external identities;
   - integration payloads i snapshots Traffit;
   - telemetry/cache/search index;
   - retained finance/legal records przez pseudonymous subject key.
4. Każdy artifact kończy jako deleted, pseudonymized, retained_with_reason albo retry/dead.
5. Archive/do-not-contact działa od razu, przed zakończeniem długiego cleanupu.

### Egress hardening

1. Dodać provider/purpose policy registry.
2. Zbudować i przetestować redactor kontaktów/identyfikatorów.
3. Usunąć imię/nazwisko z Qdrant payload.
4. Wyłączyć raw-CV fallback bez redakcji.
5. Wprowadzić bezpieczny, wersjonowany embedding schema i nową kolekcję.
6. Parser zewnętrzny działa tylko przy zatwierdzonym purpose/config; brak konfiguracji fail-closed.
7. Dodać outbound payload canary tests, nie snapshot z prawdziwymi danymi.

### Engagement link

- zahashować token;
- atomowy consume;
- bounded CandidateDeclaration zamiast dopisywania do ogólnego engagement note;
- privacy/expiry/rate-limit checks.

### Feature flags

- <code>CANDIDATE_PRIVACY_V2_ENABLED=false</code> dla nowych odczytów/UI;
- <code>CANDIDATE_PRIVACY_ENFORCEMENT=false</code> początkowo audit-only;
- <code>CANDIDATE_PRIVACY_EXECUTOR_ENABLED=false</code> do canary;
- <code>AI_PII_SAFE_SCHEMA_ENABLED=false</code> do nowej kolekcji;
- żadna flaga nie może ponownie udostępniać viewerom PII zamkniętego w PR 1.

### Testy

- state derivation z sekwencji eventów;
- restriction blokuje contact/export/marketplace/add-to-job;
- legal hold i retained reason;
- preview/execute/retry/idempotency;
- awaria storage/Qdrant zostawia retry artifact;
- wszystkie znane stores w manifest registry;
- canary PII nie wychodzi do Voyage/Anthropic/Qdrant payload;
- concurrent magic-link consume: dokładnie jeden sukces;
- audit bez raw PII.

### Rollout

1. migracja addytywna;
2. audit-only backfill statusów i raport braków;
3. DPO review próby;
4. enforcement tylko dla nowych submissions;
5. pojedynczy synthetic/canary privacy request;
6. mały, ręcznie zatwierdzony batch istniejących rekordów;
7. dopiero potem szerszy worker;
8. stara kolekcja Qdrant usuwana po coverage/parity/retention approval.

### Rollback

- enforcement flag OFF wraca do read-only ledger, ale nie przywraca wykonanych usunięć;
- worker można pauzować bez utraty queue;
- alias Qdrant może wrócić do poprzedniej bezpiecznej kolekcji; nie wracać do kolekcji z PII po jej zatwierdzonym wycofaniu.

### Kryteria zakończenia PR 2

- każdy nowy aktywowany kandydat ma privacy context albo pozostaje quarantined;
- do-not-contact/restricted jest egzekwowane przez wszystkie wybrane surface;
- pseudo-anonymize nie istnieje jako alternatywa;
- DSAR ma preview, manifest, approval, retry i audit;
- PII canary nie pojawia się w zewnętrznym payload/Qdrant;
- decyzje DPO/legal są zapisane jako wersjonowana konfiguracja/policy, nie komentarz w kodzie.

## PR 3/7 — Jeden bezpieczny intake i CandidateSubmission

### Cel

Wprowadzić jedną, idempotentną bramę dla manual create, public apply i importów, bez bezpośredniego mutowania Candidate przez niezaufane źródło.

### Model danych

<code>candidate_submissions</code>:

- source/adapter/version;
- source record ID;
- idempotency key i payload hash;
- received_at/source_observed_at;
- raw payload locator lub zredagowany manifest — nie niekontrolowany JSON z PII;
- privacy context/reference;
- status: received/quarantined/parsed/identity_pending/accepted/rejected/error;
- candidate/application/document references;
- error code bez PII;
- actor albo source system.

Opcjonalnie osobne <code>candidate_applications</code>, jeżeli submission dotyczy konkretnego Job.

### CandidateIntakeService

Jeden kontrakt adaptera:

1. validate envelope/source authentication;
2. enforce idempotency;
3. validate privacy context;
4. persist immutable submission;
5. persist quarantined document reference;
6. invoke identity resolver;
7. accept to canonical profile dopiero po deterministic/review decision;
8. emit source/application/outbox w tej samej transakcji;
9. return stable intake result.

### Kolejność migracji adapterów w tym PR

1. public apply — najwyższe ryzyko;
2. manual create;
3. from-CV i bulk CV jako draft/review;
4. CSV import.

LinkedIn, TalentRadar i Traffit mogą jeszcze przez krótki czas korzystać z adaptera compatibility, ale muszą emitować intake event; pełne przełączenie kończy PR 4.

### Public apply V2

- aktywny token z expiry/use limit;
- submission zawsze osobny;
- email verification/proof przed automatycznym połączeniem z istniejącym Candidate;
- żadnej zmiany <code>created_by</code>;
- wiadomość nie trafia do <code>ai_summary</code>;
- CV jako revision submission;
- privacy notice version/context zapisane;
- rate limit i generic responses bez enumeracji;
- stage dopiero po accept przez <code>AddCandidateToJobService</code> lub tymczasowy bezpieczny command adapter.

### Frontend

- public form pokazuje zatwierdzone notice i zapisuje version/reference;
- after submit pokazuje status submission, nie obietnicę natychmiastowej modyfikacji profilu;
- AddFromCV/Bulk: parse → draft → review → confirm;
- low confidence queue i edycja przed accept;
- wspólny file preflight i accessible dropzone;
- duplicate/ambiguous pokazuje review, nie <code>force save</code> bez reason.

### Testy

- public email poisoning nie zmienia istniejącego Candidate;
- double submit z tym samym key/hash tworzy jeden submission;
- ten sam key z innym payload = conflict;
- request timeout + retry nie duplikuje stage/source/document;
- parse bez confirm nie tworzy aktywnego kandydata;
- invalid/spoofed/oversized file zostaje quarantined/rejected;
- privacy context persisted;
- owner unchanged;
- generic anti-enumeration responses;
- Enter i Space obsługują dropzone.

### Rollout

- <code>CANDIDATE_INTAKE_V2_ENABLED=false</code>;
- osobne flagi per adapter, np. public/manual/cv/csv;
- shadow write submission dla manual flow, porównanie bez przełączenia;
- public apply przełączyć jako pierwszy po security tests;
- canary per adapter i dashboard pending/error/duplicate/ambiguous;
- legacy fallback nie może ponownie mutować istniejącego Candidate w public flow.

### Rollback

- flaga adaptera może wrócić do bezpiecznego legacy/manual path dla wewnętrznych flow;
- public apply nie wraca do auto-mutation; awaryjnie przyjmuje submission do kolejki manual review;
- nowe submissions pozostają audytem i mogą zostać później wznowione.

### Kryteria zakończenia PR 3

- public/manual/CV/CSV przechodzą przez jeden intake contract;
- niezaufane źródło nie mutuje Candidate;
- retry jest idempotentny;
- low-confidence i ambiguous trafiają do review;
- dokument i privacy context mają lineage do submission;
- produkcyjny public flow sprawdzony read-only do momentu submit oraz kontrolowanym test submission zgodnie z procedurą.

## PR 4/7 — CandidateIdentity, bezpieczny merge i integralność importów

### Cel

Zapewnić jedną tożsamość osoby przy wielu źródłach i zakończyć ścieżkowy dedup, bez automatycznego niszczenia danych.

### Model i migracje

1. <code>candidate_identities</code> z normalizacją:
   - email: NFC, trim, casefold zgodnie z zatwierdzonym kontraktem;
   - phone: E.164, a last-9 tylko jako candidate hint, nie arbitralny klucz;
   - LinkedIn: canonical host/path/slug;
   - external: source + external ID.
2. <code>candidate_identity_reviews</code>.
3. <code>candidate_merges</code> i <code>Candidate.merged_into_candidate_id</code>.
4. Optymistyczna <code>Candidate.version</code> dla konfliktów edycji.
5. Addytywne unique indexes dopiero po backfillu i review duplikatów.

### Staged constraint rollout

1. policzyć duplikaty;
2. backfill identities w shadow;
3. klasyfikować deterministic/ambiguous/conflict;
4. nie scalać automatycznie;
5. naprawić przypadki high-confidence w zatwierdzonym batchu;
6. założyć partial unique dla canonical/verified;
7. przełączyć writes;
8. zostawić scalar legacy w read compatibility do końca stabilizacji.

### Merge service

- dry-run manifest;
- jawna policy dla każdej tabeli z <code>candidate_id</code>;
- row-level natural keys, nie delete-all po jednym konflikcie;
- storage/document revisions;
- privacy state i legal hold;
- contracts/audit zachowane;
- external identities i source/application lineage;
- Qdrant/outbox;
- redirect ze starego ID;
- reauth/reason/audit;
- batch limit i backup checkpoint.

### Integracje

1. LinkedIn: identity po canonical slug; invalid/short slug do review.
2. TalentRadar: zachować własną external identity także przy adopcji po emailu.
3. Traffit:
   - użyć nowych entity links;
   - użyć i rozszerzyć istniejący <code>backend/app/services/traffit/merge.py</code>; nie tworzyć drugiego silnika 3-way merge;
   - poprawić SAVEPOINT/counters/watermark;
   - failed phase nie przesuwa cursora;
   - zależne fazy skip;
   - source manifest/hash dla dokumentów;
   - gates pozostają OFF do shadow/canary.
4. CloudTalk: wiele trafień phone-last9 → review/no match, nigdy <code>.limit(1)</code>.
5. GoWork/future: tylko adapter contract; brak direct Candidate write.

### Testy

- case/Unicode/concurrent email;
- phone E.164 i ambiguous last9;
- LinkedIn variants/broken slug;
- wiele external identities;
- unique race kończy się jednym candidate lub review;
- name-only nigdy auto-merge;
- merge fixture zachowuje non-conflicting child rows;
- merge repeat no-op;
- legal hold/active contract policy;
- Traffit injected item failure, committed counters i unchanged watermark;
- CloudTalk ambiguous phone nie przypina arbitralnie.

### Rollout

- <code>CANDIDATE_IDENTITY_V2_SHADOW=true</code>, enforce false;
- metryki parity/ambiguous/false-positive review;
- per adapter canary;
- unique constraint dopiero po zero unresolved violating rows;
- merge tylko manualnie zatwierdzone batch’e;
- Traffit nowe inbound/outbound gates pozostają domyślnie OFF zgodnie z <code>bbee39e</code>.

### Rollback

- resolver enforce OFF wraca do legacy lookup, ale nowe identities pozostają;
- nie usuwać identities ani merge audit;
- po wykonanym merge rollback wyłącznie przez przygotowany reverse manifest/backup, nigdy ad-hoc SQL;
- watermark pozostaje na ostatnim bezpiecznym sukcesie.

### Kryteria zakończenia PR 4

- wszystkie źródła tworzą/odnajdują Candidate przez wspólny resolver;
- brak arbitralnego match przy ambiguity;
- external lineage nie jest nadpisywane;
- merge nie usuwa poprawnych children;
- Traffit nie przesuwa watermark przy błędzie;
- quality endpoint pokazuje pending identity reviews i duplicate backlog.

## PR 5/7 — CandidateDocument V2, extraction authority i bezpieczny eksport

### Cel

Uczynić CandidateDocument jedyną prawdą o pliku, zapewnić bezpieczny upload/extraction i zamknąć formula injection/masowe eksporty.

### Backend

1. Rozszerzyć CandidateDocument o potrzebne pola:
   - revision/version;
   - detected MIME;
   - original display filename;
   - scan status/result reference;
   - extraction status/current run;
   - archived/deleted timestamps;
   - primary uniqueness.
2. Wykorzystać istniejące na <code>bbee39e</code> hash i source manifest fields.
3. Dodać <code>candidate_extraction_runs</code> i field provenance/authority.
4. Wspólny CandidateDocumentService:
   - bounded stream;
   - random object key;
   - magic MIME;
   - size/batch limit;
   - quarantine/scan;
   - checksum/idempotency;
   - transactional metadata + outbox cleanup;
   - primary switch;
   - authorized download headers.
5. Dual-read resolver: document → storage → legacy tylko jako fallback z metryką.
6. Backfill hash/metadata bez wczytywania całej bazy do pamięci.
7. Reconciler:
   - DB row bez object;
   - object bez DB row;
   - multiple/no primary;
   - legacy-only;
   - stale extraction.
8. Background export:
   - typed SQL projection;
   - formula neutralization;
   - permission/reason/audit;
   - row/byte caps;
   - expiring authorized download.

### Frontend

- <code>document_summary</code> i primary document w typed DTO;
- Pliki: upload/replace/set-primary/archive/download zgodnie z capability;
- progress, scan/parsing status, retry i error;
- confirmation przy replacement/archive;
- Candidate z documents-only nie zależy od <code>cv_filename</code>;
- import review pokazuje extraction source/confidence i manual override;
- export pokazuje background status zamiast blokującego requestu.

### Testy

- magic/MIME/ext mismatch;
- oversized przed pełną alokacją;
- concurrent same filename;
- checksum idempotency;
- failed upload/DB commit/storage cleanup;
- dokładnie jeden primary pod concurrency;
- stale extraction discarded;
- manual authority nie jest nadpisana;
- single/bulk/profile używają tego samego resolvera;
- nosniff/content disposition/auth;
- orphan reconciler;
- CSV/XLSX formula canaries;
- background export limits/expiry/audit.

### Rollout

- <code>CANDIDATE_DOCUMENTS_V2_DUAL_WRITE=false</code>;
- <code>CANDIDATE_DOCUMENTS_V2_READ=false</code>;
- najpierw nowe uploady dual-write/compare;
- następnie read V2 dla admin canary;
- backfill hash i inventory w checkpointowanych batchach;
- read switch per surface;
- legacy cleanup dopiero po 100% coverage, okresie stabilizacji i zatwierdzonym backupie.

### Rollback

- read flag wraca do compatibility resolvera;
- nie usuwać legacy binary/keys w tym PR przed zakończeniem soak;
- failed cleanup pozostaje w outbox;
- primary switch ma transakcyjny rollback.

### Kryteria zakończenia PR 5

- jeden resolver i jeden primary we wszystkich surface;
- nowe pliki nie trafiają na lokalny dysk jako prawda;
- spoof/oversize/malware state jest egzekwowany;
- stale parser nie nadpisuje profilu;
- eksport jest background, audytowany i odporny na formuły;
- admin quality pokazuje zero nowych orphanów i malejący legacy backlog.

## PR 6/7 — Marketability, Availability Claims, Search V3 i centralne add-to-job

### Cel

Zbudować jedną decyzję „czy i gdzie wolno użyć kandydata”, a następnie podłączyć do niej search, pools, marketplace i przejście do Job.

### Model/serwisy

1. <code>candidate_availability_claims</code>:
   - status;
   - source/actor;
   - observed_at;
   - expires_at;
   - evidence/reference;
   - superseded.
2. <code>CandidateMarketabilityService</code> wykorzystuje:
   - lifecycle;
   - privacy state;
   - availability freshness;
   - employment/contracts;
   - hard conflicts per Job;
   - preferences/exclusions;
   - dokument/readiness;
   - role/surface.
3. Wynik:
   - searchable;
   - contactable;
   - marketplace_eligible;
   - client_shareable;
   - assignable_to_job;
   - reason codes i soft warnings.
4. Rozszerzyć czysty <code>candidate_job_eligibility.py</code>, nie tworzyć drugiej konkurencyjnej polityki.

### Search V3

- jeden executor AST;
- canonical structured facts;
- strict/lenient unknown;
- candidate access projection;
- document EXISTS;
- cursor pagination i deterministic sort;
- saved searches V3 z version;
- diagnostics tylko capability;
- index outbox w tej samej transakcji i latest revision;
- nowa PII-safe Qdrant collection z alias/canary.

### Pools/marketplace/seeking

- visibility/ACL personal/team/org/system;
- server pagination/search/sort i URL state;
- membership sprawdza marketability;
- stale availability expiry worker;
- backend zwraca effective thresholds/config version;
- jeden canonical candidate text/input;
- deterministic candidate/job ordering;
- paginacja >50/>500;
- owner/source/reason/expiry ręcznego wpisu;
- error ≠ empty, remove confirm/undo;
- zero-match actions disabled.

### AddCandidateToJobService

Jedna idempotentna komenda ma:

1. sprawdzić actor capability i candidate visibility;
2. pobrać Candidate i Job z odpowiednim lock/version;
3. ocenić privacy i eligibility;
4. wymusić hard conflicts;
5. wybrać prawidłowy pierwszy stage z template;
6. zagwarantować idempotency/unique application;
7. utworzyć CandidateApplication/CandidateStage;
8. wskazać konkretną CandidateDocument revision jako snapshot;
9. utworzyć source/application/activity/audit;
10. enqueue cache/index/notifications w tej samej transakcji;
11. zwrócić stabilny result dla retry.

Następnie przepiąć wszystkie bezpośrednie writery: candidate endpoint, LinkedIn, recommendations, shortlist, proposals bulk, public application acceptance, jobs/signing hooks i inne znalezione przez <code>rg "CandidateStage\("</code>.

### Testy

- marketability truth table;
- privacy/DNC/stale availability/hard conflict;
- jeden V3 query daje parity IDs we wszystkich surface;
- Java vs JavaScript, language same-fact, has-document;
- deterministic total/page/cursor;
- outbox latest revision i worker health;
- pool ACL/pagination >500;
- seeking pagination >50;
- marketplace threshold z backendu;
- każdy add-to-job entrypoint przechodzi wspólny contract suite;
- retry/concurrency tworzy jeden application/stage/source/snapshot;
- terminal/arbitrary stage injection niemożliwy;
- grep/architecture test zabrania nowych <code>CandidateStage(...)</code> poza serwisem/migracją/test fixture.

### Rollout

- <code>CANDIDATE_MARKETABILITY_V2_SHADOW=false</code>;
- <code>CANDIDATE_SEARCH_V3_SURFACES=""</code>;
- <code>ADD_CANDIDATE_TO_JOB_V2_CALLERS=""</code>;
- shadow compare decyzji i search, reason-code diff metrics;
- per surface/caller canary;
- nowa Qdrant collection i alias;
- availability expiry najpierw report-only, później enforce;
- threshold nie zmieniać w tym samym deployu co builder bez eval/reportu.

### Rollback

- per-surface/per-caller flag wraca do legacy, ale PR 1 hard guards i privacy enforcement pozostają;
- alias Qdrant wraca do poprzedniej bezpiecznej kolekcji;
- claims i audit pozostają;
- nie przywracać user-controlled hard conflict bypass.

### Kryteria zakończenia PR 6

- jedna marketability/eligibility decision jest używana w search, pools, marketplace i add-to-job;
- availability ma źródło i expiry;
- V3 wykonuje realne queries z prawdziwą paginacją;
- marketplace pokazuje backendowy próg i deterministic wyniki;
- wszystkie add-to-job entrypointy używają jednej komendy;
- index lag/coverage jest zdrowy i mierzalny.

## PR 7/7 — Spójny frontend, wydajność, obserwowalność i pełny CI gate

### Cel

Dokończyć użytkowy przepływ od listy do Job, usunąć silent failures i pseudo-metryki, zoptymalizować queries oraz uczynić cały moduł wymaganym kontraktem CI/produkcji.

### Frontend

1. Add/Edit:
   - DS Dialog/FormGroup;
   - focus trap/Escape/labels;
   - notes jako jawny timeline command;
   - typed DTO LinkedIn;
   - lookup loading/error/retry;
   - dedup review, brak fail-open.
2. Profile:
   - privacy status i source/provenance w uprawnionym widoku;
   - dokument lifecycle;
   - availability source/freshness;
   - dirty guard i reset po version;
   - mutation errors/toasts;
   - cache invalidation.
3. List/Search:
   - versioned URL state;
   - page clamp;
   - AbortSignal/latest request;
   - stale/error/degraded;
   - cross-page selection po ID;
   - preserve Job/pool/marketplace context.
4. Compare:
   - <code>useQueries</code>;
   - unique positive IDs i jawny limit;
   - per-item error/retry;
   - żadnych wymyślonych procentów.
5. Pools/Marketplace/Seeking:
   - pagination/search/sort/URL;
   - error ≠ empty;
   - confirmation/undo;
   - responsive tables;
   - implementować „Pokaż wszystkie” albo usunąć copy;
   - latest CV match request wins.
6. Token-first colors, spójny słownik PL i brak nowych palette classes.

### Backend performance

- list/detail/export projections;
- deferred raw CV/BLOB;
- SQL aggregates i bounded relations;
- cached/async match stats;
- bounded notes/source lists;
- cursor pagination;
- Proxycurl bounded retries, jitter, deadline, distributed lease;
- query count/bytes/p95 regression tests.

### Admin quality endpoint

Dodać <code>GET /api/admin/candidates/quality</code> albo rozszerzyć snapshot o:

- submissions pending/quarantined/error i oldest age;
- ambiguous identities/duplicate backlog;
- placeholders/incomplete profiles;
- documents: missing object, orphan object, legacy-only, multiple/no primary;
- extraction queue lag/fail/stale-discard;
- privacy missing/restricted/retention due/DSAR queue;
- stale availability;
- pool/marketplace counts i stale/blocked members;
- index queue depth/age/dead i DB↔Qdrant coverage;
- Traffit phase lag/errors/last safe watermark;
- add-to-job accepted/rejected/idempotent/conflict;
- export/download counts i denied attempts.

Endpoint jest admin-only i nie zwraca PII ani surowych candidate IDs w ogólnej odpowiedzi.

### CI

1. Zastąpić ręczną listę kandydackich testów markerem/directory manifestem.
2. Dodać collection assertion dla security/privacy/intake/document/identity/marketability suites.
3. Uruchamiać istniejące pomijane testy, po naprawieniu kontraktów oczekujących 500.
4. Frontend integration tests dla głównych ekranów.
5. Contract test dla każdego adaptera intake i caller add-to-job.
6. Architecture tests:
   - brak <code>CurrentUser</code> na wrażliwych route bez jawnej allowlisty;
   - brak direct CandidateStage writers;
   - brak nowych local CV writes;
   - brak raw CandidateResponse w client/viewer route;
   - brak hardcoded marketplace threshold;
   - brak PII w vector payload builder.
7. E2E smoke dla admin/recruiter/viewer/public apply.

### SLO i alerty

- intake oldest pending;
- identity review backlog;
- document/extraction lag;
- privacy executor retry/dead;
- index queue lag/coverage;
- search error/p95/empty-rate drift;
- marketplace scan success/no-result distribution;
- Traffit last safe watermark;
- denied sensitive operations spike;
- export volume anomaly.

### Testy UX/a11y

- axe critical/serious = 0 dla Add/Edit, import, profile, pools, marketplace;
- focus trapped/restored, Escape, labels;
- Enter/Space dropzones;
- 320 px bez poziomego overflow strony, z opisanym scroll tabeli gdzie potrzebny;
- error/empty/permission/degraded snapshots;
- refresh/back/share URL parity;
- newest-request-wins.

### Rollout

- frontend surface flags mogą przełączać pojedyncze ekrany, ale API contracts pozostają bezpieczne;
- optymalizacje mierzyć przed/po na production metrics;
- admin quality najpierw read-only;
- pełny module gate staje się required przed usuwaniem legacy;
- Chrome verification każdej roli i screenshoty kluczowych ekranów.

### Rollback

- UI może wrócić do poprzedniego renderer’a, korzystając z bezpiecznego API;
- query projection może mieć compatibility fallback, ale nie pobierać raw BLOB dla listy;
- quality endpoint może zostać wyłączony, workery zachowują queue;
- required tests nie powinny być usuwane jako „rollback”; naprawić regresję.

### Kryteria zakończenia PR 7

- cały flow list/search/profile/intake/pool/marketplace/add-to-job ma jawne loading/empty/error/permission states;
- nie ma cichej utraty notatki, złego LinkedIn, resetu draftu ani Hook violation;
- p95/query count/bytes mieszczą się w przyjętych budżetach;
- admin quality daje operacyjny obraz modułu bez PII;
- pełny module test gate jest wymagany;
- produkcyjny exact-SHA i Chrome potwierdzają rolę admin/recruiter/viewer oraz public flow.

---

## 12. Zależności między PR-ami

~~~mermaid
flowchart LR
    P1["PR1: P0 containment + access"] --> P2["PR2: Privacy + safe egress"]
    P1 --> P3["PR3: Submission + intake"]
    P3 --> P4["PR4: Identity + merge + imports"]
    P2 --> P5["PR5: Documents + extraction + export"]
    P3 --> P5
    P4 --> P5
    P2 --> P6["PR6: Marketability + Search V3 + add-to-job"]
    P4 --> P6
    P5 --> P6
    P6 --> P7["PR7: Frontend + performance + ops + CI"]
~~~

Zasady kolejności:

- PR 1 nie czeka na decyzje DPO i ma iść pierwszy;
- PR 2 może rozpocząć model addytywny równolegle z częścią PR 3, ale privacy enforcement musi być gotowy przed szerokim intake rollout;
- PR 4 nie wykonuje masowego merge przed preflightem i review;
- PR 5 nie usuwa legacy binary;
- PR 6 nie tunuje progu score równocześnie z migracją buildera bez osobnego eval;
- PR 7 nie staje się magazynem niedokończonych P0/P1 — brakujący kontrakt wraca do właściwego wcześniejszego PR.

---

## 13. Preflight danych przed migracjami

Claude ma przygotować read-only skrypt/SQL, zapisać wyniki jako zagregowany artefakt bez PII i uzyskać approval przed jakimkolwiek merge/delete/backfill enforce.

### 13.1. Role i ekspozycja

~~~sql
SELECT role, is_active, COUNT(*)
FROM users
GROUP BY role, is_active
ORDER BY role, is_active;
~~~

Dodatkowo policzyć secondary roles oraz użytkowników <code>user</code> z aktywną sesją/self-registration, bez wypisywania emaili.

### 13.2. Duplikaty email

~~~sql
SELECT lower(btrim(email)) AS email_norm,
       COUNT(*) AS rows_count,
       array_agg(id ORDER BY id) AS candidate_ids
FROM candidates
WHERE email IS NOT NULL AND btrim(email) <> ''
GROUP BY lower(btrim(email))
HAVING COUNT(*) > 1
ORDER BY rows_count DESC;
~~~

W raporcie ogólnym przechowywać liczniki; lista IDs tylko w bezpiecznym artefakcie operacyjnym.

### 13.3. Duplikaty telefonu

~~~sql
WITH normalized AS (
  SELECT id,
         regexp_replace(coalesce(phone, ''), '\D', '', 'g') AS digits
  FROM candidates
)
SELECT right(digits, 9) AS phone_last9,
       COUNT(*) AS rows_count,
       array_agg(id ORDER BY id) AS candidate_ids
FROM normalized
WHERE length(digits) >= 9
GROUP BY right(digits, 9)
HAVING COUNT(*) > 1
ORDER BY rows_count DESC;
~~~

To jest raport ambiguity, nie automatyczna lista merge. Last-9 nie może być jedynym kluczem tożsamości.

### 13.4. LinkedIn i external IDs

~~~sql
SELECT linkedin_slug, COUNT(*), array_agg(id ORDER BY id)
FROM candidates
WHERE linkedin_slug IS NOT NULL AND btrim(linkedin_slug) <> ''
GROUP BY linkedin_slug
HAVING COUNT(*) > 1;

SELECT external_source, external_id, COUNT(*), array_agg(id ORDER BY id)
FROM candidates
WHERE external_source IS NOT NULL AND external_id IS NOT NULL
GROUP BY external_source, external_id
HAVING COUNT(*) > 1;
~~~

Policzyć także jednego kandydata z wieloma historycznymi źródłami na podstawie obecnych tables/logów, aby zaplanować backfill <code>CandidateExternalIdentity</code>.

### 13.5. Placeholdery i jakość profilu

~~~sql
SELECT
  COUNT(*) FILTER (WHERE btrim(coalesce(name, '')) IN ('', '?', 'Nieznane')) AS bad_name,
  COUNT(*) FILTER (WHERE btrim(coalesce(lastname, '')) IN ('', '?', 'Nieznane')) AS bad_lastname,
  COUNT(*) FILTER (WHERE email IS NULL AND phone IS NULL AND linkedin IS NULL) AS no_contact_identity,
  COUNT(*) FILTER (WHERE raw_cv_text IS NULL AND cv_filename IS NULL) AS no_legacy_cv
FROM candidates;
~~~

### 13.6. Dokumenty i źródła binary

~~~sql
SELECT candidate_id, COUNT(*) AS primary_count
FROM candidate_documents
WHERE is_primary = true AND source_deleted_at IS NULL
GROUP BY candidate_id
HAVING COUNT(*) > 1;

SELECT
  COUNT(*) FILTER (WHERE storage_key IS NOT NULL) AS object_storage_rows,
  COUNT(*) FILTER (WHERE file_content IS NOT NULL) AS bytea_rows,
  COUNT(*) FILTER (WHERE storage_key IS NULL AND file_content IS NULL) AS missing_binary_rows,
  COUNT(*) FILTER (WHERE content_sha256 IS NULL) AS missing_hash_rows
FROM candidate_documents
WHERE source_deleted_at IS NULL;

SELECT COUNT(*)
FROM candidates c
WHERE c.cv_filename IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM candidate_documents d
    WHERE d.candidate_id = c.id AND d.source_deleted_at IS NULL
  );
~~~

Object storage inventory i local filesystem inventory wykonać osobnym read-only skryptem porównującym opaque keys/hash, bez pobierania treści do raportu.

### 13.7. Blacklisted/privacy/marketplace niespójności

~~~sql
SELECT COUNT(*)
FROM candidates c
WHERE c.status = 'blacklisted'
  AND (
    c.email IS NOT NULL OR c.phone IS NOT NULL OR c.raw_cv_text IS NOT NULL
    OR EXISTS (
      SELECT 1 FROM candidate_documents d
      WHERE d.candidate_id = c.id AND d.source_deleted_at IS NULL
    )
  );

SELECT COUNT(*)
FROM talent_pool_memberships m
JOIN talent_pools p ON p.id = m.talent_pool_id AND p.is_marketplace = true
JOIN candidates c ON c.id = m.candidate_id
WHERE c.status = 'blacklisted'
   OR c.availability_status = 'not_looking';
~~~

Po dodaniu privacy state rozszerzyć o restricted/DNC/retention due.

### 13.8. Pule i marketplace

~~~sql
SELECT p.id, p.is_personal, p.is_marketplace,
       COUNT(m.id) AS member_count,
       COUNT(*) FILTER (WHERE m.marketplace_until < current_date) AS expired_members
FROM talent_pools p
LEFT JOIN talent_pool_memberships m ON m.talent_pool_id = p.id
GROUP BY p.id, p.is_personal, p.is_marketplace
ORDER BY member_count DESC;

SELECT COUNT(*) FILTER (WHERE added_by IS NULL) AS missing_actor,
       COUNT(*) FILTER (WHERE source_event IS NULL) AS missing_source,
       COUNT(*) FILTER (WHERE marketplace_until IS NULL) AS no_expiry
FROM talent_pool_memberships m
JOIN talent_pools p ON p.id = m.talent_pool_id
WHERE p.is_marketplace = true;
~~~

### 13.9. Source event duplicates i atrybucja

~~~sql
SELECT candidate_id, job_id, channel, captured_at,
       COUNT(*) AS rows_count
FROM candidate_source_events
GROUP BY candidate_id, job_id, channel, captured_at
HAVING COUNT(*) > 1
ORDER BY rows_count DESC;
~~~

Dodatkowy raport ma policzyć hires przypisane source eventowi z innym/NULL job_id.

### 13.10. Hard delete impact

Przygotować read-only query pokazujące liczbę kandydatów z:

- aktywnymi/draft/ending contracts;
- notes/activities/calls/chats;
- stages i applications;
- privacy/legal hold po wdrożeniu;
- documents/object keys;
- integration snapshots/outbox/conflicts.

Nie uruchamiać <code>DELETE</code> ani testowego cascade na produkcji.

### 13.11. Search/index

Zmierz:

- candidates eligible for indexing;
- candidates z <code>embedding_id</code>;
- punkty w aktywnej kolekcji Qdrant;
- content hash parity;
- outbox pending/retry/dead i oldest age;
- records updated po ostatniej index revision;
- strony hybrid, dla których <code>total</code> przekracza realnie możliwy cap.

### 13.12. Traffit

Z nowych i starych tabel odczytać:

- last attempt/success/safe cursor per phase;
- errors i consecutive failures;
- phase ze statusem error przy przesuniętym watermark;
- orphan/duplicate entity links;
- pending conflicts/outbox/webhooks;
- gates env/runtime, bez wypisywania sekretów;
- file manifest/hash gaps.

### 13.13. Export formula canary

Na środowisku testowym utworzyć rekord z wartościami zaczynającymi się od:

- <code>=HYPERLINK(...)</code>;
- <code>+cmd</code>;
- <code>-1+2</code>;
- <code>@SUM(...)</code>.

Po eksporcie potwierdzić, że CSV/XLSX traktuje je jako tekst. Nie używać realnych danych kandydata.

### 13.14. Artefakt preflight

Claude ma zapisać:

- SHA kodu i timestamp;
- same liczniki i zakresy;
- listę blokujących kategorii;
- decyzję proceed/hold per migracja;
- bez emaili, telefonów, nazwisk, treści CV i NIP;
- secure path do osobnego, ograniczonego manifestu IDs tylko jeśli jest konieczny operacyjnie.

---

## 14. Strategia migracji i kompatybilności

### 14.1. Zasada additive-first

1. Dodać tabele/kolumny/indexy bez zmiany odczytu.
2. Shadow write lub dual-write.
3. Backfill w małych, checkpointowanych batchach.
4. Parity/quality metrics.
5. Canary read/enforcement.
6. Stopniowy switch surface/adapter.
7. Okres stabilizacji.
8. Dopiero osobny PR usuwa legacy.

### 14.2. Migracje Postgres

- używać <code>alembic -c alembic/alembic.ini upgrade heads</code>;
- każdą nową kolumnę/tabelę odzwierciedlić idempotentnie w <code>backend/entrypoint.sh</code> zgodnie z repo contract;
- NOT NULL dodawać etapami: nullable → backfill → validation → constraint;
- unique identity index dopiero po rozwiązaniu konfliktów;
- duże indexy rozważyć jako osobny etap zgodny z możliwościami produkcyjnego deployu;
- żadnego masowego update bez batch/cursor/progress/resume;
- downgrade nie może udawać bezpiecznego, jeśli oznacza utratę privacy/identity/audit data.

### 14.3. Kompatybilność API

- nowe DTO pod wersjonowanym kontraktem lub additive safe fields;
- nie poszerzać starego CandidateResponse o kolejne wrażliwe pola;
- legacy export i file endpoints oznaczyć deprecation i mierzyć użycie;
- saved searches migrować lossless adapterem do V3;
- stare candidate IDs po merge przekierowują do survivor, nie zwracają przypadkowego 404;
- client/viewer nie korzysta z operational DTO.

### 14.4. Feature flags

Minimalny zestaw:

- <code>CANDIDATE_PRIVACY_V2_ENABLED</code>;
- <code>CANDIDATE_PRIVACY_ENFORCEMENT</code>;
- <code>CANDIDATE_PRIVACY_EXECUTOR_ENABLED</code>;
- <code>CANDIDATE_INTAKE_V2_{ADAPTER}</code>;
- <code>CANDIDATE_IDENTITY_V2_SHADOW/ENFORCE</code>;
- <code>CANDIDATE_DOCUMENTS_V2_DUAL_WRITE/READ</code>;
- <code>CANDIDATE_MARKETABILITY_V2_SHADOW</code>;
- <code>CANDIDATE_SEARCH_V3_SURFACES</code>;
- <code>ADD_CANDIDATE_TO_JOB_V2_CALLERS</code>;
- <code>AI_PII_SAFE_SCHEMA_ENABLED</code>.

Flagi:

- muszą mieć bezpieczne defaulty;
- mają być widoczne w admin status bez sekretów;
- runtime flag nie może włączyć kierunku wyłączonego env gate’em;
- nie mogą osłabiać containmentu PR 1;
- powinny mieć ownera, sunset date i rollback procedure.

### 14.5. Dane nieodwracalne

- erase, merge i usunięcie starej kolekcji/storage wymagają preview, backup/manifest i approval;
- soft archive/restriction jest preferowane przed irreversible cleanup;
- legal/finance retention decyzja musi być utrwalona;
- nie budować automatycznego „undo erase”, które trzyma ukrytą kopię PII.

---

## 15. Test plan

### 15.1. Backend unit

- role/capability union;
- identity normalizers;
- identity resolver reason codes;
- marketability truth table;
- privacy state reducer;
- export cell sanitizer;
- MIME/magic/size validation;
- field authority;
- availability expiry;
- V3 AST/adapter/executor semantics;
- source attribution model.

### 15.2. Backend integration z Postgres

- concurrent create/identity unique;
- submission idempotency;
- public apply poisoning regression;
- merge per-table policies;
- privacy executor manifest/retry;
- document primary concurrency i rollback;
- outbox same-transaction/revision;
- Traffit partial failure/watermark;
- pool ACL/pagination;
- add-to-job contract dla każdego callera;
- formula-safe export;
- viewer PII/export/document matrix.

### 15.3. Object storage/Qdrant adapters

- storage timeout po upload przed DB commit;
- DB rollback po storage success;
- cleanup retry/dead-letter;
- object missing;
- orphan object;
- Qdrant PII canary;
- collection alias switch/rollback;
- privacy delete retry;
- index latest revision.

### 15.4. Frontend component/integration

- capabilities hide actions, API 403 state;
- Add/Edit notes i LinkedIn;
- intake draft/review/confirm;
- file progress/error/retry;
- source error vs empty;
- engagement/location dirty draft;
- URL codec/page clamp/back/refresh;
- cross-page selection/compare;
- pool >500 pagination;
- marketplace threshold/error/remove;
- seeking >50;
- dropzone keyboard/latest request;
- permission/degraded states;
- no pseudo-score.

### 15.5. Security regression

- anonymous vs user/client vs internal vs admin;
- direct ID enumeration;
- presigned URL authorization;
- bulk action body escalation;
- hard conflict bypass parameter;
- source backdate/write;
- corporate pool write;
- public email poisoning;
- formula injection;
- upload content spoof;
- magic-link replay/race;
- PII outbound canary;
- log redaction.

### 15.6. E2E/Chrome po deploy

1. Viewer:
   - brak candidate base/PII/export/CV i mutacji;
   - client-safe share działa tylko po jawnym grant.
2. Recruiter/sourcer:
   - search → profile → note/source/document zgodnie z capability;
   - add to Job przez centralną komendę.
3. DL/admin:
   - finance/legal tylko właściwe role;
   - export audit;
   - pool management.
4. Public applicant:
   - token → notice → submission;
   - ponowny submit idempotentny;
   - istniejący profil nie ulega zmianie.
5. Marketplace:
   - próg z backendu;
   - expiry/availability/source;
   - error i empty rozróżnione.
6. Privacy canary:
   - tylko na synthetic/test candidate zgodnie z approval;
   - preview → execute → artifact status;
   - żadnego testu erase na realnej osobie.

### 15.7. Testy wydajnościowe

Ustalić budżety przed implementacją. Minimalnie mierzyć:

- candidate list query count, DB time i response bytes;
- detail query count;
- search p50/p95 i realną paginację;
- export memory/throughput;
- bulk ZIP/background job memory;
- extraction queue throughput/oldest age;
- index queue lag;
- marketplace scan duration;
- Traffit items/min i retry rate.

### 15.8. Wymagany CI gate

- nie polegać na ręcznej liście, która może zapomnieć nowy test;
- marker/manifest modułu ma failować, jeśli wymagany suite nie został zebrany;
- gitleaks → lint → typecheck → module tests → build pozostają zielone;
- pełne integracje/build pozostawić hosted CI; lokalnie tylko najmniejsze host-native checks.

---

## 16. Obserwowalność i alerty

### 16.1. Metryki

**Access/security**

- sensitive access allowed/denied per capability/route/role class;
- exports requested/completed/failed/downloaded;
- CV/document downloads;
- bulk operations preview/execute;
- hard conflict exclusions i attempted bypass parameter.

**Intake/identity**

- submissions by source/status;
- duplicate/idempotent/ambiguous/conflict rates;
- oldest pending review;
- merge preview/executed/failed;
- source adapter errors.

**Documents/enrichment**

- uploads accepted/rejected by reason;
- quarantine/scan/extraction queue depth/age;
- extraction stale-discard;
- orphan/missing object;
- legacy-only coverage;
- primary invariant violations.

**Privacy**

- candidates missing required privacy context;
- DNC/restricted/retention due;
- requests by type/status/age;
- artifacts retry/dead/retained;
- egress blocked/allowed by provider/purpose;
- PII canary failures jako page-level alert.

**Search/marketplace**

- search p95/errors/zero-result rate;
- V3/legacy parity diff w shadow;
- DB↔Qdrant coverage i index lag;
- availability stale/expired;
- marketplace eligible/blocked reason distribution;
- threshold/config version;
- scan duration/no-match distribution/alerts deduped.

**Integracje**

- Traffit last attempt/success/safe watermark per phase;
- consecutive failures/dead letters/conflicts;
- webhook/outbox oldest age;
- Proxycurl retry/deadline/lease contention;
- CloudTalk ambiguous phone matches.

### 16.2. Logi

Structured fields:

- <code>event</code>;
- <code>source</code>;
- <code>submission_id</code> lub opaque correlation ID;
- <code>candidate_id</code> tylko jeśli zgodne z polityką logów;
- <code>operation</code>;
- <code>phase</code>;
- <code>policy_version</code>;
- <code>reason_code</code>;
- <code>request_id</code>;
- <code>duration_ms</code>.

Nigdy:

- email/phone/name/NIP;
- CV text;
- note/transcript content;
- auth/public tokens;
- storage presigned URL;
- provider secret;
- pełny inbound/outbound payload.

### 16.3. Alerty

**Page/critical**

- PII canary wykryte w outbound/vector payload;
- privacy executor usuwa artifact spoza manifest policy;
- viewer successful sensitive endpoint;
- watermark przesunięty po failed critical phase;
- index/storage invariant masowo naruszony po deployu.

**High**

- DSAR/privacy request przekracza zatwierdzone SLO;
- dead-letter rośnie;
- DB↔Qdrant coverage spada;
- intake/identity review backlog przekracza próg;
- Traffit safe watermark stale;
- anomalny wzrost eksportów/downloadów;
- hard conflict bypass attempt spike.

**Warning**

- document/extraction/index lag;
- stale availability;
- marketplace no-result rate drift;
- orphan files;
- V3 parity diff;
- Proxycurl retry exhaustion.

### 16.4. Health/snapshot

Nie rozszerzać stabilnego publicznego <code>/api/health</code> o PII/liczniki biznesowe. Health może pokazywać bounded status zależności/workerów. Szczegóły jakości trafiają do admin snapshot/quality endpoint z osobną autoryzacją.

---

## 17. Definition of Done całego modułu

Moduł 2 jest ukończony dopiero, gdy:

- rola viewer/client nie ma globalnego dostępu do Candidate PII/CV/export ani mutacji;
- hard conflicts są zawsze fail-closed;
- publiczny intake nie mutuje istniejącego profilu;
- wszystkie adaptery używają idempotentnego CandidateIntakeService;
- identities są znormalizowane, wieloźródłowe i chronione constraintami;
- ambiguous trafia do review, a merge jest per-table, audytowalny i bezpieczny;
- CandidateDocument jest jedyną prawdą binary, z wersją, scanem i revision-aware extraction;
- privacy ledger i executor obejmują wszystkie stores oraz respektują legal hold;
- zewnętrzny AI/vector path nie otrzymuje canary PII;
- availability ma source/freshness/expiry;
- search, pools, marketplace i add-to-job używają jednej marketability policy;
- Search V3 ma jeden executor i prawdziwą pagination;
- wszystkie direct CandidateStage writers zostały przepięte;
- exports są background, audytowane i formula-safe;
- frontend nie myli error z empty i nie traci notatki/draftu;
- admin quality mierzy backlog, coverage i niespójności bez PII;
- pełny moduł jest obowiązkowym gate CI;
- każdy PR jest merged, deployed i exact-SHA verified;
- kluczowe flow sprawdzone na produkcji w Chrome dla właściwych ról;
- legacy cleanup nastąpił dopiero po coverage, stabilizacji i osobnym approval.

---

## 18. Instrukcja startowa dla Claude Code

Poniższy blok można przekazać Claude przed rozpoczęciem implementacji:

> Pracujesz w repozytorium NEXUS. Najpierw przeczytaj całe <code>AGENTS.md</code> oraz dokument <code>docs/candidate-talent-module-audit-and-claude-implementation-plan-2026-07-16.md</code>. Nie używaj lokalnego Dockera. Nie dotykaj niezwiązanych zmian w worktree.
>
> Wykonaj <code>git fetch origin</code>, zapisz aktualny SHA <code>origin/main</code>, sprawdź <code>git status</code> oraz <code>git log origin/main..HEAD</code>. Zweryfikuj, czy zakres PR nie został już wdrożony. Jeżeli <code>origin/main</code> zmienił się od SHA raportu, przeanalizuj diff w audytowanych plikach i zaktualizuj założenia, zamiast ślepo realizować stary line number.
>
> Zacznij wyłącznie od PR 1/7: P0 containment, CandidateAccessPolicy i fail-closed hard conflicts. Nie implementuj równolegle pozostałych sześciu PR. Najpierw przygotuj route/action inventory i macierz rola × operacja × projekcja. Zablokuj viewerowi PII/CV/export/mutations server-side, zablokuj pseudo-anonymize i zwykły hard delete, wymuś hard NDA/blacklist niezależnie od query param, dodaj security tests do faktycznie uruchamianego CI. Frontend ma odzwierciedlać capability, ale nie jest granicą bezpieczeństwa.
>
> Nie twórz flagi przywracającej niebezpieczne <code>CurrentUser</code>. Nie zmieniaj thresholdów ani algorytmu scoringu w PR 1. Nie wykonuj masowych migracji, merge, erase ani cleanup storage. Nie wyciągaj wrażliwych danych produkcyjnych do raportów/logów.
>
> Dla każdej zmiany DB użyj Alembic <code>upgrade heads</code> i idempotentnego lustra w <code>backend/entrypoint.sh</code>. Uruchom najmniejsze host-native testy. Następnie commit conventional, push task branch, PR, wymagany green CI, squash merge, deploy, sprawdzenie <code>/api/health.version</code> względem pełnego merged SHA oraz produkcyjny curl/Chrome dla admin/recruiter/viewer. Nie raportuj PR jako ukończony przed merge, deploy i production verification.
>
> Po PR 1 zatrzymaj się i przedstaw: route inventory, finalną macierz capability, testy, PR/commit/SHA, CI, deployed SHA, produkcyjne wyniki ról i świadomie odłożony zakres. Dopiero po akceptacji przejdź do PR 2.

### Checklist startowa PR 1

- [ ] Najnowszy <code>origin/main</code> i czysty, izolowany branch.
- [ ] Pełna lista candidate routes i ich obecne dependencies.
- [ ] Lista frontend actions i protected routes.
- [ ] Zatwierdzona minimalna macierz ról.
- [ ] Security tests napisane przed/razem z fixem.
- [ ] Hard conflict contract przetestowany direct API.
- [ ] Pseudo-anonymize i hard delete zablokowane.
- [ ] Export/download audit bez PII.
- [ ] Required CI naprawdę zebrał nowe testy.
- [ ] Diff scope review.
- [ ] PR, CI, merge, deploy, exact SHA, role curl, Chrome.

---

## 19. Decyzje produktowe i prawne do potwierdzenia

### Przed PR 1

1. Czy rola <code>user</code> jest wyłącznie klient/viewer i ma stracić całą globalną bazę kandydatów? Rekomendacja: tak.
2. Czy recruiter/sourcer ma widzieć operacyjną safe summary globalnie, czy tylko assigned/team scope? Rekomendacja: global search summary dla wewnętrznego sourcingu, ale osobne capability na contact/CV i brak legal/finance.
3. Kto może eksportować: DL/HoR/admin czy wybrane role z reason? Rekomendacja: dedykowana capability, reason i audit; domyślnie nie recruiter.
4. Kto może tworzyć corporate pools i zmieniać membership? Rekomendacja: RecruiterPlus membership, wyższa capability na pool administration.

### Przed PR 2

5. Zatwierdzona matryca purposes/bases/notice versions/retention/legal hold/DSAR approvals.
6. Które provider calls są dozwolone, w jakim regionie i dla jakiego purpose; DPA/retention dla Anthropic, Voyage, Proxycurl, Qdrant i telemetry.
7. Które dane kontraktowe/finansowe muszą zostać po privacy request i w jakiej pseudonimizowanej formie.
8. Kto jest technical privacy officer capability holder i czy wymagane jest four-eyes approval.

### Przed PR 3/4

9. Czy istniejący kandydat potwierdza publiczną aplikację przez email magic link, czy zawsze trafia do recruiter review? Rekomendacja: verified email proof dla deterministic link; ambiguity/restricted zawsze manual review.
10. Jakie identity claims są canonical i które mogą być tylko hints.
11. Jak traktować kandydatów bez email/phone/LinkedIn, w tym placeholdery z importu.
12. Które źródło ma authority per pole; czy Traffit/NEXUS jest master dla konkretnych pól po włączeniu bidirectional sync.
13. Kto zatwierdza merge i jaki aktywny kontrakt/legal hold go blokuje.

### Przed PR 5/6

14. Maksymalny plik, batch, ZIP i okres przechowywania kolejnych wersji CV.
15. Wymagany malware scanner i quarantine SLO.
16. Docelowy czas ważności availability per źródło.
17. Semantyka marketplace threshold; nie ustalać liczby przed jednym builderem i evalem.
18. Czy personal pools są prywatne, team-visible read-only czy całkowicie team-visible.
19. Jawna definicja source attribution: first/last/application touch.
20. Limit porównania kandydatów i zatwierdzone metryki profilu; rekomendacja: żadnych pseudo-procentów bez wersjonowanej definicji.

Brak decyzji blokującej nie powinien wstrzymywać PR 1. Powinien natomiast zatrzymać enforcement/irreversible działania w odpowiednim późniejszym PR.

---

## 20. Ostateczna rekomendacja

Modułu nie należy ulepszać przez dodawanie kolejnych formularzy, importerów i widoków na obecny model. NEXUS ma już więcej niż wystarczającą liczbę surface. Każdy nowy direct writer zwiększa dziś liczbę wyjątków, duplikatów i niejawnych kopii danych.

Rekomendowana kolejność jest jednoznaczna:

1. zamknąć P0 access/destructive/NDA;
2. oddzielić privacy od sourcing status i zabezpieczyć egress;
3. przyjmować wszystko przez immutable submission;
4. rozwiązywać jedną tożsamość i scalać wyłącznie przez bezpieczną policy;
5. uczynić CandidateDocument jedyną prawdą pliku;
6. zbudować jedną decyzję marketability/search/add-to-job;
7. dopiero wtedy domknąć UX, wydajność, obserwowalność i pełny CI.

Najważniejszy warunek sukcesu: **jedna osoba, jeden audytowalny profil, wiele zachowanych źródeł, jeden dokumentowy kontrakt, jawna podstawa i zakres użycia, jedna decyzja eligibility oraz zero ścieżek omijających te reguły**.

---
