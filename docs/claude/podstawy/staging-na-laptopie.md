# Staging na laptopie — pełna kopia produkcji bez wyjścia na świat · `NEXUS_ENV=staging`, lista pętli, zapora HTTP, odtworzenie z backupu

Decyzja Artura z 22.10.2026: laptop jest stałym stagingiem NEXUSA na pełnej kopii
produkcji, a produkcja ma dostawać jedno wdrożenie dziennie z commitu, który
przeszedł staging. Plan z etapami: `docs/staging-laptop-plan.md`.

## Co jest w repo (etap 1)

- `docker-compose.staging.yml` (projekt `nexus-staging`): Dockerfile'e z produkcji,
  trwałe wolumeny, Mailpit, lokalny S3 (versitygw), porty tylko na `127.0.0.1`.
  Front `http://localhost:3100`, API `http://localhost:8100`, poczta `http://localhost:8125`.
- `backend/app/core/staging.py` — przy `NEXUS_ENV=staging`:
  - pętle z rejestru `app.state.background_tasks` stoją, oprócz
    `STAGING_ALLOWED_TASKS` (porządki i przeliczenia na bazie). Anulowane są
    przed pierwszym `await` lifespanu, więc nie wykonują ani linii;
  - zapora wyjścia na klasach transportu httpx/httpx2, urllib3 (msal, boto3),
    smtplib i aiohttp: poza siecią lokalną tylko dostawcy AI
    i `STAGING_EXTRA_ALLOWED_HOSTS`.
- `scripts/staging/restore_from_backup.sh` — kopia offsite z `backup/backup.sh`
  (age + B2) → baza, uploady, Qdrant; potem `sanitize.sql`. Korpus CV z bucketu
  produkcji kluczem tylko do odczytu (`CV_SOURCE_*`, decyzja Artura 22.10.2026),
  bo lustro w B2 ma dzienny limit pobrań klasy B.
  Bucket `nexus-candidate-documents` w lokalnym S3 skrypt zakłada z
  `RCLONE_S3_NO_CHECK_BUCKET=false`: przy `true` (ustawionym w skrypcie
  dla całego biegu) `rclone mkdir` go nie tworzy i na świeżym wolumenie
  sync kończy się samymi `NoSuchBucket` bez skopiowanego pliku.
  Klucz prywatny age bierze z pęku kluczy macOS (`nexus-backup-age`).
- `scripts/staging/env.staging.example` — wzór `.env.staging.local`.
- `scripts/staging/refresh_code.sh` — backend i front z `origin/main` na tej samej
  bazie (co noc, `rutyny-nocne.md`). Kod wyjścia 3 = kopia ma rewizję, której main
  już nie zna: `/api/health` mówi wtedy „healthy”, a schemat jest stary, więc
  potrzebna jest nowa kopia i `STAGING_DATABASE_NAME`. Kod wyjścia 4 = ranking
  liczy co innego niż produkcja (niżej).

## Ranking jak na produkcji

Wnioski ze stagingu idą do decyzji Artura, więc wynik i kolejność muszą się
zgadzać. 02.11.2026 staging nie miał flag z produkcji (ta sama osoba 45,1 i 66,3),
a Qdrant był 10 dni starszy od bazy, co wyrzucało 2 247 osób z rankingu.

- **Flagi:** `docker-compose.staging.yml`, sekcja „Ranking jak na produkcji”.
  Nowa flaga z `_SCORING_CACHE_INPUTS` włączona na produkcji albo inna wartość
  w workflow „Coolify set env” = ta sama zmiana w compose i
  `env.staging.example`. Różnice, które zostają celowo: integracje, poczta,
  pętle w tle.
- **Nowa kopia bazy = wyrównanie Qdranta.** Klon z Hetznera przenosi samą bazę,
  a outbox w kopii ma `indexed_hash` z produkcji. `index_drift_reconciler`
  porównuje z nim treść, nie z Qdrantem, więc tej różnicy nie widzi. Skrypt niżej
  porównuje hasz z punktem w Qdrancie i liczy tylko osoby ze zmianą (02.11: 2 252
  osoby, ok. 3,3 mln tokenów):

  ```bash
  docker exec nexus-staging-backend-1 python -m scripts.reembed_collections --target candidates --resume --commit
  ```

- **Strażnik:** `scripts/staging_ranking_parity.py` (też z `refresh_code.sh`)
  porównuje `ranker_version` z ostatnim automatycznym przeglądem z kopii i liczy
  osoby z innym wektorem. Stempel nie obejmuje `HYBRID_POOL_ENABLED`,
  `KNOWN_PEOPLE_BOOST_ENABLED`, `KEYWORD_SEARCH_FOLDED_FTS` ani `MATCH_POOL_SIZE`.
- **Skrypt pomiarowy poza procesem web** wywołuje `refresh_alias_map()`
  i `critical_skills.refresh_cache()`, bo robi to dopiero lifespan.

## Kopia bez klucza age i późniejsze przenoszenie zmian

Decyzja Artura z 22.10.2026: lokalna kopia może też powstać ze świeżego zrzutu
bazy na Hetznerze przez SSH. `scripts/staging/clone_from_hetzner.py` pobiera
spójny `pg_dump` z jawnie wskazanego kontenera PostgreSQL. Nie zmienia danych
źródłowych, nie usuwa istniejących baz i odtwarza wyłącznie do **nowej** lokalnej
bazy `nexus_staging_*`. Odtworzenie i sanitizacja są jedną transakcją; aplikacja
nie jest uruchamiana automatycznie. Tryb `--dump-only` pozwala pobrać kopię przed
uruchomieniem lokalnego PostgreSQL, a `--restore-manifest` wznowić odtwarzanie
bez ponownego pobierania. Ten wariant obejmuje bazę PostgreSQL; pliki CV,
uploady i Qdrant wymagają odrębnego odtworzenia zgodnie z opisem powyżej.

Na produkcję trafiają kod i wersjonowane migracje przez istniejącą ścieżkę
PR → CI → Deploy. **Lokalnej bazy nie wysyłamy z powrotem na produkcję.**
Wybrane zmiany danych przenosi `backend/scripts/staging_data_promotion.py`:
stan przed edycją → paczka wybranych pól → podgląd na docelowej bazie → jawne
zatwierdzenie skrótu podglądu → transakcja z ponowną kontrolą konfliktów.
Nowe rekordy produkcyjne i pola poza paczką pozostają nietknięte. Brak zgodności
z oczekiwanym stanem zatrzymuje całą paczkę. Obsługiwane są wyłącznie pola
z jawnej listy; pola wymagające przeliczeń lub obsługi zdarzeń domenowych muszą
najpierw dostać osobny handler. Instrukcja i aktualny zakres:
`docs/staging-data-promotion-runbook.md`.

Dump, selection, baseline, paczka i podgląd zawierają dane produkcyjne lub
biznesowe: wyłącznie prywatny katalog poza repo, bez przesyłania do Actions.

## Reguły, które łatwo cofnąć

- **Nowa pętla w lifespanie = wpis w `STAGING_ALLOWED_TASKS` albo
  `STAGING_BLOCKED_TASKS`.** Bez tego pada `tests/test_staging_background_tasks.py`.
  Wątpliwość = zablokowana: na stagingu leżą prawdziwe adresy kandydatów.
- **Nowy klient HTTP nie potrzebuje niczego**, o ile idzie przez httpx, urllib3,
  smtplib albo aiohttp. Inna biblioteka sieciowa (np. własne gniazdo, gRPC) musi
  dostać łatkę w `install_egress_guard`, zanim trafi do kodu.
- **Tabela albo kolumna z `scripts/staging/sanitize.sql` zmienia nazwę** —
  popraw plik SQL; pilnuje tego `tests/test_staging_sanitize_sql.py`.
- **`CANDIDATE_IDENTITY_FINGERPRINT_KEY` na stagingu = ten z produkcji**, reszta
  sekretów (`SECRET_KEY`, `M365_TOKEN_ENCRYPTION_KEY`) własna — inaczej
  wykrywanie duplikatów rozjeżdża się z odciskami w kopii.
- Kopia ma dane osobowe: porty tylko na `127.0.0.1`, nic ze stagingu do repo,
  logów Actions ani artefaktów CI.
