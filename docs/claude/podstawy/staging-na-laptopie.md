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
- `scripts/staging/nightly_sync.py` — co noc nowa kopia produkcji (niżej).
- `scripts/staging/refresh_code.sh` — backend i front z `origin/main` na tej samej
  bazie (co noc, `rutyny-nocne.md`). Czeka, aż nocna kopia skończy, bo odtworzenie
  backendu przerwałoby wyrównanie Qdranta (kod 5 po 3 godzinach). Kod wyjścia 3 = kopia ma rewizję, której main
  już nie zna: `/api/health` mówi wtedy „healthy”, a schemat jest stary, więc
  potrzebna jest nowa kopia i `STAGING_DATABASE_NAME`. Kod wyjścia 4 = ranking
  liczy co innego niż produkcja (niżej).

## Ranking jak na produkcji

Wnioski ze stagingu idą do decyzji Artura, więc wynik i kolejność muszą się
zgadzać. 02.11.2026 staging nie miał flag z produkcji (ta sama osoba 45,1 i 66,3),
a Qdrant był 10 dni starszy od bazy, co wyrzucało 2 247 osób z rankingu.

- **Flagi:** `docker-compose.staging.yml`, sekcja „Ranking jak na produkcji”.
  Wartości bierze co noc `nightly_sync.py`. Nowa nazwa w `_SCORING_CACHE_INPUTS`
  wymaga wpisu w compose, bo inaczej nie dojdzie do backendu (pilnuje
  `tests/test_staging_nightly_sync.py`). `QUERY_ADAPTER_ENABLED` też idzie z produkcji
  (`RANKING_POOL_FLAGS`), bo włączony zmienia stempel: 09.11.2026 produkcja liczyła
  `dc1ff64ccd10`, a staging bez niego `bdba10363617`. `SALES_BOT_TASKS_ENABLED` i `SALES_REGISTRY_ENABLED` też idą z produkcji
  (`SALES_FLAGS`, 14.11.2026); pętla `sales_signals` stoi, więc zmieniają tylko trasy. Różnice, które zostają celowo:
  integracje, poczta, pętle w tle, `REVIEW_BATCH_ENABLED` z
  `AUTO_FULL_REVIEW_DAYTIME_FIRST_ENABLED` (silnik porcji stoi, a włączona blokada 423
  zamknęłaby rekruterowi wyszukiwanie bez kart do oceny) i `DB_MAX_OVERFLOW`.
- **Nowa kopia bazy = wyrównanie Qdranta** (co noc robi to `nightly_sync.py`). Klon z Hetznera przenosi samą bazę,
  a outbox w kopii ma `indexed_hash` z produkcji. `index_drift_reconciler`
  porównuje z nim treść, nie z Qdrantem, więc tej różnicy nie widzi. Skrypt niżej
  porównuje hasz z punktem w Qdrancie i liczy tylko osoby ze zmianą (02.11: 2 252
  osoby, ok. 3,3 mln tokenów). Masowy zapis na produkcji przekracza limit nocy
  (`MAX_REEMBED_PEOPLE`) i wtedy wyrównuje się ręcznie: ponowny odczyt CV z 07.11.2026
  (`scripts/reparse_cv_batch.py`) to 54 540 osób na stagingu, a produkcja przeliczyła je
  sama przez outbox:

  ```bash
  docker exec nexus-staging-backend-1 python -m scripts.reembed_collections --target candidates --resume --commit
  ```

- **Strażnik:** `scripts/staging_ranking_parity.py` (też z `refresh_code.sh`)
  porównuje `ranker_version` z ostatnim automatycznym przeglądem z kopii i liczy
  osoby z innym wektorem. Stempel nie obejmuje `HYBRID_POOL_ENABLED`,
  `KNOWN_PEOPLE_BOOST_ENABLED`, `KEYWORD_SEARCH_FOLDED_FTS` ani `MATCH_POOL_SIZE`.
- **Skrypt pomiarowy poza procesem web** wywołuje `refresh_alias_map()`
  i `critical_skills.refresh_cache()`, bo robi to dopiero lifespan.

## Listy klientów jak na produkcji

03.11.2026 `GET /api/clients/12/order-groups` dawał na stagingu 8 zamówień, a po
ustawieniu `MULTI_CONSULTANT_ORDER_CLIENT_IDS` 50. Klient spoza tej listy nie widzi
starych zamówień bez `order_type` (`list_order_groups`), a staging miał ją pustą.

- `CLIENT_LIST_FLAGS` w `nightly_sync.py`: ta lista, `COST_ORDER_CLIENT_IDS`
  i `EXTENDED_ORDER_ALERT_CLIENT_IDS`. Wartości przychodzą co noc z produkcji w
  `.env.staging-flags.local`, razem z flagami rankingu, więc nowy klient pojawia się
  na stagingu bez zmiany w repo.
- Do pliku idą same identyfikatory, a wpis inny niż liczba jest pomijany, tak jak
  w `config.py`. Pusta lista na produkcji daje pustą listę na stagingu.
- Wartości nie wpisuj do repo ani do `env.staging.example`: repo jest publiczne.
- `ORDER_MAIL_AUTOAPPLY_EXCLUDE_CLIENT_IDS` zostaje poza listą, bo poczta zamówień
  na stagingu jest wyłączona.
- Raport różnic ustawień (`other_differences`) porównuje tylko bool i liczby, więc
  nowej listy tekstowej sam nie zgłosi. Nowa lista z wpływem na ekran wymaga wpisu
  w `CLIENT_LIST_FLAGS` i w compose.

## Nocna kopia produkcji

Decyzja Artura z 02.11.2026: staging co noc staje się aktualną kopią produkcji,
bo stara kopia i inne flagi dawały złe liczby przy działającym stagingu.
`scripts/staging/nightly_sync.py` (rutyna 00:00, `rutyny-nocne.md`) robi po kolei:

1. Czyta z procesu backendu produkcji przez SSH ustawienia bool i liczbowe oraz
   listę dozwolonych: `_SCORING_CACHE_INPUTS`, flagi puli, listy klientów, flagi
   Sprzedaży i dzienny limit próśb o warunki (`CANDIDATE_TERMS_DAILY_LIMIT`). Do
   `.env.staging-flags.local` obok głównego pliku env idzie tylko ta lista. Inne
   różnice trafiają do raportu, bez sekretów: filtr nazw działa już na serwerze.
   Przełączniki integracji i poczty są w compose na sztywno, więc flaga z produkcji
   ich nie włączy.
2. Zrzuca bazę do `~/.local/share/nexus-staging-nightly/<RRRRMMDD>/` i odtwarza ją
   z `sanitize.sql` do nowej `nexus_staging_nightly_<RRRRMMDD>`. Kontener produkcji
   ustala przy każdym biegu. Wdrożenie restartuje Postgresa produkcji i zrywa zrzut
   (03.11.2026 w 9. minucie), więc skrypt czeka na nowy kontener i ponawia aż do
   terminu, najwyżej 12 razy. 20.11.2026 cztery wdrożenia w 35 min wyczerpały
   dawny limit 4 prób przy 85 min zapasu. Zrzut jest przerywany o 02:15 UTC, przed
   backupem produkcji.
3. Buduje kod z `origin/main`, dosyła brakujące pliki CV (niżej), przełącza
   `STAGING_DATABASE_NAME`, odtwarza backend i front. Sprawdza `/api/health` na nowej
   bazie. Gdy jest niezdrowy, cofa plik env i flagi.
4. Wyrównuje Qdrant (`--target candidates --resume`, `--target jobs --only-missing`)
   i uruchamia strażnika. Powyżej 5 000 różnic nie liczy, tylko pyta w raporcie,
   bo to zwykle zmiana tekstu albo modelu.
5. Porządki: zostają 2 ostatnie dobre kopie nocne i ich zrzuty, bo zawierają dane
   osobowe. Usuwa wyłącznie nazwy z tego wzorca, nigdy kopii aktywnej, i bez
   `FORCE`, więc baza z połączeniem w `pg_stat_activity` zostaje.

Laptop musi być nocą na zasilaczu. 21.11.2026 o 00:20 zasnął przy 1% baterii
(`pmset -g log`: „Low Power Sleep”) i spał do 14:46 następnego dnia: `caffeinate -i`
nie chroni przed uśpieniem przy rozładowanej baterii, bieg z 21.11 wisiał do
przebudzenia, a noc 22.11 przepadła.

Każdy błąd przed przełączeniem zostawia staging na poprzedniej kopii. Start poza
oknem 22:00–01:00 UTC jest pomijany, bo rutyna po zamkniętej aplikacji rusza przy
następnym otwarciu, a przełączenie w dzień przerwałoby pracę sesji. Wynik:
`~/.claude/nexus-rutyny/raporty/<dzień>/staging-kopia.ok` i `.md`, wyjście procesów
w `~/.nexus-staging/logs/`.

**Co się dzieje z sesjami na głównym stagingu w chwili przełączenia:**

- **Testowe karty i inne zapisy na głównym stagingu znikają razem ze starą kopią.**
  Główny staging nie jest miejscem na dane, które mają przetrwać noc. Rzeczy
  potrzebne dłużej: własna baza `nexus_branch_*`. Po zapisy z poprzedniej nocy
  można sięgnąć do poprzedniej kopii, dopóki jej porządki nie usuną.
- Backend i API stoją kilka minut (start z migracjami), a skrypt z `docker exec`
  w głównym backendzie kończy się błędem. Bieg, który ma trwać przez noc, zaczynaj
  po 01:30 albo na własnym backendzie.
- Token z logowania działa dalej, bo `SECRET_KEY` się nie zmienia.
- Backend gałęzi już uruchomiony zostaje na starej kopii, bo adres bazy ma zapisany
  przy starcie. Połączenie chroni tę kopię przed porządkami. Po restarcie backend
  gałęzi wstaje na nowej kopii.
- `nexus_sales`, `nexus_branch_*` i `nexus_staging_2026*` skrypt pomija. Stare kopie
  `nexus_staging_2026*` usuwa się ręcznie.

## Pliki CV jak na produkcji

03.11.2026 podgląd oryginału dawał na stagingu 503, a QC pisał „Brak tekstu
oryginalnego CV” i odkładał sprawdzenia, choć na produkcji pliki były. Baza była
z tej nocy, a lokalny S3 z pełnego odtworzenia 23.10: brakowało 5 571 plików (1,5 GB).
Rekordy z 23–27.10 mieszały 200 i 503, bo klucz `stage-cv/<kandydat>/<sha256>` jest
wspólny dla tej samej osoby i treści, więc nowy wiersz trafiał czasem na stary plik.
Brak pliku na stagingu nie mówi więc nic o produkcji, dopóki krok niżej nie przeszedł.

- `scripts/staging/sync_cv_files.sh` biegnie co noc z `send_cv_files`, przed
  przełączeniem bazy, w kontenerze `restore` (ten sam obraz, bez drugiego stosu):
  `rclone copy --ignore-existing` z bucketu produkcji kluczem tylko do odczytu.
  Zapis idzie wyłącznie do lokalnego S3.
- **Nie zamieniaj na lustro w B2**: dzienny limit pobrań klasy B. Bez `CV_SOURCE_*`
  skrypt kończy się błędem, nie szuka innego źródła.
- **Koszt nocy** zmierzony 03.11: lista ok. 196 tys. obiektów to ok. 200 zapytań do
  bucketu (25 s), a pobranie idzie tylko dla brakujących plików. 1 013 plików
  i 257 MB trwało 46 s. Dobowy przyrost to kilkaset plików. Nie dodawaj porównania
  czasu ani sumy kontrolnej, bo przy tej liczbie plików daje zapytanie na każdy
  obiekt, a klucze nie zmieniają treści (uuid albo sha256).
- **Błąd nie zatrzymuje kopii.** Trafia do „Czeka na Artura” w `staging-kopia.md`,
  a następna noc dosyła resztę. Limit biegu to 1 h. Laptop uśpiony w trakcie kończy
  się błędami DNS i kodem 1 (03.11: 913 plików), a kolejny bieg je dosyła.
- Ręcznie, gdy brak pliku przeszkadza w ciągu dnia (z `~/.nexus-staging/code`, gdy
  ma już ten skrypt):

  ```bash
  docker compose -p nexus-staging -f docker-compose.staging.yml --env-file .env.staging.local --profile restore run --rm -T --no-deps --entrypoint /bin/sh restore /staging/sync_cv_files.sh
  ```

- Błędy rclone niosą klucze z nazwami plików, a te bywają nazwiskami, więc wyjście
  idzie tylko do prywatnego logu, nigdy do raportu ani repo.
- `copy` nie kasuje: lokalne zapisy sesji zostają, a plik usunięty na produkcji zostaje
  na laptopie do następnego pełnego odtworzenia. 03.11 takich plików nie było: 26
  plików spoza produkcji to zapisy ze stagingu.
- **Uploady nie są objęte tym krokiem.** Wolumen `uploads_data` (m.in. `branded_cvs/`)
  zostaje z pełnego odtworzenia: 03.11 ze 358 ścieżek `branded_snapshot_path` lokalnie
  było 168, więc gotowe PDF-y CV firmowego nowszych rekordów mogą na stagingu nie działać.

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

## Pamięć maszyny Dockera i OOM-killer

24.11.2026 Postgres stagingu padł dwa razy (sygnał 9, „recovery mode”) i przerwał
przebiegi poczty, kopie nocne i s4. Od 05.11.2026 takich zabić było osiem.

- **Zabija brak pamięci w całej maszynie Dockera, nie limit 8g.** W dmesg maszyny
  stoi `constraint=CONSTRAINT_NONE … global_oom`, a `memory.events` kontenera ma
  `oom 0`. Maszyna ma 32 GiB i 1 GiB swapu. O 20:42 UTC miała 24 GiB pamięci
  anonimowej i 5 GiB shmem, w tym ok. 12 GiB w Pythonie: przebiegi poczty (ok.
  1,5 GiB każdy, we własnym kontenerze) i pytesty innych sesji. Wyższy `mem_limit`
  ani mniejsze `work_mem` czy `max_connections` nic tu nie dają: prywatnie Postgres
  miał 0,74 GiB w 46 procesach, a w trakcie przebiegu 0,1 GiB.
- **Ofiarą był Postgres, bo jądro wybiera największy RSS**, a proces Postgresa,
  który dotknął `shared_buffers`, liczy w nim całe 2 GB (zabity: anon 32 MB, shmem
  2,06 GB). Dlatego `oom_score_adj: -500` (decyzja Artura z 24.11.2026): przy braku
  pamięci jądro zabije inny proces, np. przebieg albo pytest jednej sesji.
- **Wartość z compose wchodzi dopiero z nowym kontenerem** (`up -d postgres`,
  `restore_from_backup.sh`). `docker restart` i restart Dockera wracają do 0 ze
  starej konfiguracji. Działający kontener dostał −500 na żywo 24.11.2026. Po takim
  restarcie ustaw ją tak samo, bez przerwy w pracy (nowe połączenia dziedziczą):

  ```bash
  CID=$(docker inspect --format '{{.Id}}' nexus-staging-postgres-1)
  docker run --rm --privileged --pid=host --cgroupns=host --network none --entrypoint sh postgres:16-alpine \
    -c "for p in \$(cat /sys/fs/cgroup/docker/$CID/cgroup.procs); do echo -500 > /proc/\$p/oom_score_adj; done"
  ```

- **Kto zabił:** `docker run --rm --privileged --network none --entrypoint dmesg postgres:16-alpine | grep -A1 oom-kill:`
  sięga kilku godzin wstecz. Docker Desktop zapisuje te linie też w
  `~/Library/Containers/com.docker.docker/Data/log/vm/init.log*`.
- **Przed przebiegiem poczty** sprawdź `MemAvailable` maszyny
  (`docker exec nexus-staging-postgres-1 grep MemAvailable /proc/meminfo`). Przebieg
  zajmuje ok. 1,5 GiB, a pytesty innych sesji potrafią dołożyć 3 GiB w dwie minuty,
  więc poniżej ok. 6 GiB poczekaj. Pamięci Docker Desktop nie zwiększamy (decyzja
  Artura z 24.11.2026), bo macOS ma zajęte 116 z 128 GB.

## Reguły, które łatwo cofnąć

- **`oom_score_adj: -500` Postgresa zostaje, a `mem_limit` nie rośnie „na zapas”**:
  zabija brak pamięci w maszynie, nie limit kontenera (sekcja wyżej). Pilnuje
  `tests/test_staging_postgres_oom.py`.
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
