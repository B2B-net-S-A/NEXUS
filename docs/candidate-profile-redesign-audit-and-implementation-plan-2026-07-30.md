# Profil kandydata — audyt, plan wdrożenia i dziennik dowodów

**Data:** 2026-07-30
**Status:** wdrożenie w toku
**Gałąź feature:** `codex/candidate-profile-redesign`
**Docelowy branch:** `main`

## 1. Cel i wiążące decyzje

Ten dokument jest jedynym planem wdrożenia nowego profilu kandydata. Łączy
decyzje produktowe, architekturę, migracje, testy, rollout, rollback i dowody
wydania. Makieta HTML pozostaje wzorcem hierarchii informacji; nie jest źródłem
kodu ani kontraktów.

Docelowy profil rozwija istniejący `CandidateDetailV2` i wprowadza:

- pasek faktów bezpośrednio pod nagłówkiem;
- deterministyczne języki, lokalizację, dostępność i globalną stawkę;
- jedną globalną stawkę kandydata: B2B, PLN, netto, za godzinę;
- podsumowanie historii AI bez kwot i bez źródeł spoza scope użytkownika;
- pięć ostatnich widocznych rekrutacji w prawej kolumnie;
- funkcjonalne wycofanie miesięcznego `Candidate.salary_expectation`;
- kwarantannę źródeł opisujących inną osobę.

Stawki per rekrutacja, client sell rate, kontrakty, `RateHistory`, budżety jobów
oraz historyczne dane rekrutacyjne pozostają własnością domeny Recruitment i
nie są czyszczone w tym wydaniu.

## 2. Granica dowodowa i preflight

### 2.1. Punkt startowy

| Dowód | Wartość na początku pracy |
|---|---|
| `origin/main` | `31b338c61a21fe15ad2ae0df2993177afb6da265` |
| izolacja | osobne worktree, bez przejęcia lokalnego WIP |
| produkcyjny `/api/health` | HTTP 200, ogólny stan healthy |
| produkcyjny SHA | zgodny z bazowym SHA przy preflight |
| Alembic | stan sprawdzony osobno od globalnego health |
| Traffit | degraded przy preflight; nie jest dowodem awarii profilu |
| liczba/wiek cache | brak bezpiecznego kanału read-only do DB w bieżącej sesji; nie estymować |
| lokalny Docker | nieużywany |

Globalny zielony health nie jest dowodem bezpieczeństwa cache, poprawnego
scope, migracji, realnego flow użytkownika ani gotowości czyszczenia danych.

### 2.2. Wynik kontrolowanego sprawdzenia cache AI

Bezpośredni odczyt istniejącego cache podsumowania na kontrolowanym profilu
zwrócił treść finansową oraz fragment odnoszący się do innej osoby, mimo
wyłączonego generowania. Oznacza to, że bezpieczeństwa cache bez scope nie
dało się dowieść.

Brak dostępu do agregatu liczby i wieku wpisów nie zmienia decyzji
containment: pojedynczy potwierdzony odczyt niedozwolonej treści wystarcza do
zamknięcia ścieżki. Agregat należy uzupełnić z zatwierdzonego kanału
operacyjnego bez pobierania treści cache; nie wolno obchodzić braku dostępu
tymczasowym endpointem ani logowaniem danych kandydatów.

Uruchomiono przewidziany w planie wyjątek P0:

- osobny, minimalny hotfix odcina odczyt legacy cache i blokuje generowanie;
- PR bezpieczeństwa: [#1007](https://github.com/artur-t-96/Nexus/pull/1007);
- commit źródłowy: `966aae2a9f43d69c1e968532c1f7d16d05977bc2`;
- testy PR: backend, frontend, skany i automatyczny review — zielone;
- merge/deploy: oczekuje na wymagane przez ochronę `main` niezależne approval.

Feature release nie może zostać uznany za gotowy, dopóki hotfix albo pełne
rozwiązanie zakresowe nie działa w produkcji.

## 3. Architektura docelowa

### 3.1. Granice domen

- Talent 360 jest właścicielem profilu i globalnych faktów.
- Recruitment jest właścicielem etapów, jobów, stawek per rekrutacja,
  kontraktów, client sell rate i historii procesowej.
- Podsumowanie AI jest projekcją, nie źródłem prawdy.
- Brak wartości jest poprawnym stanem; system nie zapisuje wartości domyślnej.
- Ręczna korekta faktu ma pierwszeństwo przed parserem CV i integracjami.

### 3.2. Kolejność jednego feature PR

Zmiany są porządkowane logicznie w jednym PR:

1. bezpieczny cache AI, DLP, scope, lease i kwarantanna;
2. typowane fakty, jeden writer i migracje addytywne;
3. wycofanie miesięcznej stawki w runtime;
4. API i interfejs profilu;
5. testy, dokumentacja, hosted CI i pojedynczy deploy.

Późniejsze czyszczenie danych jest kontrolowaną operacją, a nie drugim
wydaniem aplikacji.

## 4. Fundament bezpieczeństwa AI

### 4.1. Cache i wersjonowanie

Klucz cache:

```text
(candidate_id, visibility_scope_hash, content_policy_version)
```

Wymagania:

- stare rekordy otrzymują status `legacy-unscoped`;
- rekord `legacy-unscoped` nigdy nie może być serwowany;
- `serve` i `generate` podlegają temu samemu kill-switchowi;
- odpowiedź zawiera `source_version`, `current_source_version`, `is_stale`,
  `visibility_scope_hash` i zminimalizowany `source_manifest`;
- zmiana źródeł lub policy version oznacza cache jako stale;
- wynik zapisuje się dopiero po ponownym sprawdzeniu aktualnej wersji źródeł.

### 4.2. Efektywny scope

Joby, notatki, feedback, screening i rozmowy są filtrowane według efektywnego
scope użytkownika. Źródło bez dowiedzionego powiązania z dozwolonym jobem jest
odrzucane fail-closed. `source_manifest` nie ujawnia treści, identyfikatorów ani
liczników zasobów spoza scope.

### 4.3. DLP i niezaufany tekst

Przed budową promptu:

- odrzucane są wszystkie pola finansowe;
- odrzucany jest cały fragment wolnego tekstu zawierający kwotę, symbol waluty,
  kod waluty lub wzorzec stawki;
- źródła są sanityzowane i jednoznacznie delimitowane jako niezaufane;
- instrukcje znalezione w źródłach nie mogą zmienić promptu systemowego.

Po wygenerowaniu:

- wynik i manifest przechodzą niezależny skan DLP;
- wynik z kwotą albo niedozwolonym źródłem nie jest zapisywany;
- błąd skanera działa fail-closed;
- logi i audyt nie zawierają treści kandydata.

### 4.4. Krótki lease

Długi `pg_advisory_xact_lock` zostaje zastąpiony przez:

1. krótki zapis lease z TTL;
2. commit i zwolnienie połączenia;
3. wywołanie modelu bez otwartej transakcji DB;
4. finalizację compare-and-swap tylko przez właściciela aktualnego lease;
5. bezpieczne przejęcie wygasłego lease.

Metryki obejmują kolizje, przejęcia, timeouty, odrzucenia DLP i latency.

## 5. Kwarantanna źródeł tożsamości

Notatka albo CV z potwierdzonym mismatchem osoby:

- nie trafia do promptu, cache ani `source_manifest`;
- ma jawny status i przyczynę kwarantanny;
- nie jest automatycznie przywracane przez ponowny parsing;
- może zostać odblokowane wyłącznie przez `admin` lub
  `head_of_recruitment`;
- override wymaga niepustego powodu i tworzy audyt bez treści dokumentu.

Testy obejmują pełne imię i nazwisko, transliterację, brak nazwiska, wynik
niejednoznaczny, potwierdzony mismatch oraz audytowany override.

## 6. Typowane fakty

### 6.1. Języki

Addytywna tabela `candidate_languages` przechowuje:

- `language_code` oraz nazwę prezentacyjną;
- CEFR `A1`–`C2` albo jawny stan nieznanego poziomu;
- osobne `is_native`;
- provenance i identyfikator źródła;
- `manual_lock`;
- `version` do optimistic concurrency control;
- tombstone zamiast destrukcyjnego usunięcia.

Ręczna edycja, enrichment CV, Traffit, Talent Radar, CSV i dotychczasowe raw SQL
korzystają z jednego serwisu zapisu. Automatyczny writer:

- nie nadpisuje ręcznie zablokowanego faktu;
- nie wskrzesza ręcznego tombstone;
- nie mapuje poziomu opisowego na CEFR bez potwierdzenia;
- deduplikuje język według kanonicznego kodu.

Migracja Alembic tworzy wyłącznie schemat. Backfill jest osobnym narzędziem z
`--dry-run`, checkpointem, licznikami konfliktów i raportem parity z legacy
JSONB. Nie uruchamia się przy starcie aplikacji.

### 6.2. Lokalizacja

`city` i `country` są kanoniczne. `location` pozostaje tylko projekcją
kompatybilności. `PATCH /api/candidates/{id}/location` zapisuje manual lock,
wersję i audyt. Parsery nie nadpisują ręcznej korekty.

### 6.3. Globalna stawka

`expected_rate_hourly` ma typ `NUMERIC(10,2)` i stałe znaczenie:

```json
{
  "amount": "175.50",
  "currency": "PLN",
  "unit": "hour",
  "tax_basis": "net",
  "contract_type": "b2b"
}
```

Waluta, jednostka, podstawa i kontrakt nie są wybieralne. Jawnych wartości w
innej walucie nie przeliczamy; trafiają do raportu konfliktów. Istniejące,
jednoznacznie godzinowe wartości PLN są traktowane jako netto.

Odczyt i zapis globalnej stawki mają role:

- `admin`;
- `head_of_recruitment`;
- `delivery_lead`;
- `tac`;
- `recruiter`;
- `sourcer`.

Rola `user` i użytkownicy zewnętrzni nie otrzymują nawet klucza stawki w
odpowiedzi. Uprawnienia kontraktów i client sell rate pozostają bez zmian.

## 7. Wycofanie miesięcznej stawki kandydata

`salary_expectation` i `salary_currency` zostają fizycznie w tabeli jako pola
deprecated. Runtime może ich dotknąć tylko w:

- modelu legacy;
- kontrolowanym, szyfrowanym eksporcie;
- transakcyjnym narzędziu czyszczącym.

Pola są usuwane ze schematów create/update/read, formularzy, filtrów,
structured search, scoringu, matchingu, rekomendacji, prep kitów, zwykłego
importu/eksportu, adapterów Traffit/Talent Radar i buildera AI.

Reguły kompatybilności:

- nowy zapis miesięcznej wartości: HTTP 422,
  `candidate_monthly_rate_retired`;
- import zbiorczy raportuje błąd pola, ale zachowuje pozostałe poprawne dane;
- brak automatycznej konwersji miesiąc → godzina;
- nieporównywalne jednostki mają `not_comparable` i nie obniżają score;
- zapisane wyszukiwania tracą miesięczne kryteria bez konwersji, mają wyłączone
  alerty i `requires_reapproval=true`.

## 8. Kontrakty API

### 8.1. Fakty

| Endpoint | Kontrakt |
|---|---|
| `GET /api/candidates/{id}/languages` | pełna lista i `ETag` |
| `PUT /api/candidates/{id}/languages` | wymagany `If-Match`; `409/412` przy konflikcie |
| `PATCH /api/candidates/{id}/location` | `city`, `country`, manual lock i audyt |
| `GET /api/candidates/{id}/profile-rate` | decimal/null oraz stałe literały |
| `PATCH /api/candidates/{id}/profile-rate` | `If-Match`, clear przez `null`, audyt |
| `GET /api/candidates/{id}/recent-recruitments?limit=5` | najwyżej 5 rekordów bez notatek i finansów |

### 8.2. Ostatnie rekrutacje

`last_activity_at` jest maksimum z:

- ruchu etapu;
- notatki przypisanej do joba;
- feedbacku;
- screeningu;
- wysłania CV.

Sortowanie:

```text
last_activity_at DESC, latest_stage_id DESC
```

Aktywny proces nie ma dodatkowego priorytetu. Endpoint ponownie stosuje
autoryzację job scope, ogranicza `limit` do 5 i zwraca wyłącznie dane potrzebne
do karty i bezpiecznego deep-linku.

## 9. Interfejs `CandidateDetailV2`

### 9.1. Hierarchia

- Pod nagłówkiem: języki, lokalizacja, dostępność, globalna stawka B2B.
- Główna szeroka kolumna: podsumowanie AI.
- Prawa szyna: pięć ostatnich rekrutacji.
- Brak uprawnienia do stawki: całkowity brak faktu, nie placeholder.

Karta AI pokazuje aktualność, czas generacji, zakres źródeł i komunikat
„Zweryfikuj przed decyzją”. Karta rekrutacji prowadzi wyłącznie do procesu,
który użytkownik może odczytać.

### 9.2. Stany

Każdy moduł obsługuje niezależnie:

- loading;
- empty;
- partial;
- forbidden;
- stale;
- refreshing;
- error.

Konflikt OCC nie usuwa lokalnego draftu. Elementy dotykowe mają co najmniej
44×44 px, layout nie ma poziomego scrolla na 320, 768, 1280 i 1440 px, a
automatyczny audyt a11y nie zgłasza critical ani serious.

## 10. Testy i bramy akceptacji

### 10.1. Backend

- RBAC wszystkich ról, bezpośrednich endpointów i projekcji stawki.
- Canary z kwotą oraz dane obcego joba nie pojawiają się w prompt context,
  odpowiedzi, cache ani manifeście.
- Prompt injection, skaner wyniku i fail-closed.
- Lease: kolizja, TTL, przejęcie, CAS i brak transakcji podczas LLM.
- Mismatch, transliteracja, brak nazwiska, kwarantanna i override.
- Języki: CEFR, native, unknown, deduplikacja, lock, tombstone, OCC i writerzy.
- Stawka: decimal, `null`, stałe literały, miesięczna wartość 422, brak konwersji.
- Repo-wide allowlist legacy miesięcznych odwołań.
- Ostatnie rekrutacje: 0/1/5/>5, remisy, reopening, membership i deep-link.
- p95 endpointu: nie gorzej niż `max(300 ms, 1,2 × baseline)`.

### 10.2. Frontend

- testy loading/empty/partial/forbidden/stale/refreshing/error;
- widoczność stawki zgodna z rolą;
- edycja języków, lokalizacji i stawki z OCC;
- draft zachowany po konflikcie;
- safe deep-link i niedozwolony `focusJobId`;
- viewporty 320/768/1280/1440;
- WCAG 2.2 AA i zero critical/serious.

### 10.3. Weryfikacja techniczna

Lokalnie są dozwolone wyłącznie małe testy host-native. Pełne testy, build,
Alembic probes i skany wykonuje hosted CI. Zakaz lokalnego Dockera.

Aktualne dowody lokalne:

| Kontrola | Wynik |
|---|---|
| backend, testy fokusowe profilu i bezpieczeństwa | 202 passed, 4 skipped; skipy PostgreSQL wykona hosted CI |
| Ruff `app/` | lint i format check zielone |
| Alembic | jedna głowa: `0207_monthly_rate_retired` |
| import/OpenAPI | aplikacja importuje się; 676 ścieżek i 825 operacji |
| frontend, testy zmienionych powierzchni | 126/126 zielone |
| frontend lint | zero błędów; historyczne ostrzeżenia mieszczą się w limicie repo |
| guard tokenów design systemu | zielony |
| lokalny type-check | wyłącznie cztery istniejące błędy w niezmienionym `ui/chart.tsx`; rozstrzyga czyste `npm ci` w hosted CI |
| lokalny harness wizualny | nieuzyskany: współdzielony hostowy `node_modules` nie zawierał zadeklarowanego `@tailwindcss/postcss`; nie instalowano zależności w głównym WIP |

Brak lokalnego renderu nie jest zaliczeniem kryterium wizualnego. Viewporty,
a11y i prawdziwe role pozostają obowiązkowymi bramkami hosted/produkcyjnymi.

## 11. Delivery i dowody

| Etap | Wymagany dowód | Status |
|---|---|---|
| hot containment | zielony PR, merge, dokładny prod SHA, blokada unsafe cache | oczekuje na approval do merge |
| feature PR | jeden PR do `main`, uporządkowane commity | przygotowanie do publikacji |
| hosted CI | wszystkie wymagane checki zielone | oczekuje |
| migracje | jedna głowa Alembic i udany deploy | oczekuje |
| produkcja | dokładny SHA w health/deploy | oczekuje |
| Chrome | role, scope, fakty, kwarantanna, deep-link, stale→current | oczekuje |
| obserwacja | minimum 24 h metryk i błędów | oczekuje |
| cleanup | osobna zgoda po stabilnym oknie | nieautoryzowany |

Nie wolno uznać wdrożenia za zakończone na podstawie lokalnych testów ani
samego HTTP 200.

## 12. Obserwacja przez 24 godziny

Po produkcyjnym deployu obserwujemy:

- błędy endpointów profilu;
- odrzucenia DLP i ich przyczyny bez logowania treści;
- lease contention, timeout i takeover;
- latency `recent-recruitments` oraz podsumowania;
- 401/403 i próby użycia wycofanych pól;
- stale rate i błędy odświeżenia;
- sygnały kwarantanny i override.

Okno liczy się od potwierdzonego produkcyjnego SHA. Brak błędów w krótkim smoke
teście nie zastępuje pełnych 24 godzin.

## 13. Ręczne czyszczenie danych miesięcznych

Czyszczenie nie należy do migracji ani entrypointu. Po stabilnych 24 godzinach:

1. uruchomić dry-run i zapisać wyłącznie liczbę rekordów;
2. wyeksportować `candidate_id`, wartość, walutę i `updated_at` do
   zatwierdzonego, szyfrowanego magazynu poza repo i logami;
3. zapisać w dowodach tylko liczbę oraz SHA-256 artefaktu;
4. potwierdzić odtwarzalny backup albo próbny odczyt eksportu;
5. uzyskać osobną, jawną zgodę produkcyjną;
6. uruchomić narzędzie z `--apply`, `--expected-count` i oczekiwanym SHA-256;
7. wyzerować oba pola tylko dla rekordów objętych zatwierdzonym eksportem;
8. potwierdzić changed count, zero pozostałych wartości, health, Alembic i flow;
9. przechować eksport 30 dni, potem usunąć zgodnie z polityką retencji.

Narzędzie działa transakcyjnie i fail-closed przy różnicy liczby, skrótu lub
zbioru rekordów. Operacja nie jest obecnie autoryzowana.

## 14. Rollback

Przed czyszczeniem można wdrożyć poprzedni sprawdzony SHA; addytywne tabele i
migracje pozostają. Nie wolno przywracać:

- cache `legacy-unscoped`;
- kwot w AI;
- szerszego RBAC;
- źródeł z potwierdzonym mismatchem.

Problemy AI obsługujemy przez serve/generate gate i fix-forward. Po czyszczeniu
odtworzenie miesięcznych wartości jest możliwe tylko z zaszyfrowanego eksportu
i wymaga kolejnej jawnej zgody. Fizyczny `DROP` kolumn jest osobnym zadaniem po
oknie retencji.

## 15. Definition of Done

Feature jest gotowy dopiero, gdy jednocześnie:

- kod i dokument znajdują się w jednym feature PR;
- wymagane CI jest zielone;
- PR jest zmergowany do `main`;
- migracje zakończyły się z jedną głową;
- produkcja raportuje dokładny oczekiwany SHA;
- role i dwa rozłączne scope zostały sprawdzone w produkcyjnym Chrome;
- żadna kwota ani obce źródło nie przechodzi przez AI;
- fakty zachowują manual lock i OCC;
- miesięczny runtime jest odcięty z kodem 422;
- rozpoczęto 24-godzinną obserwację.

Czyszczenie historycznych wartości nie jest częścią Definition of Done
wydania. Pozostaje osobną, późniejszą operacją z osobną zgodą.
