# Kilka procesów web — zastój jednego nie zatrzymuje wszystkich (`WEB_CONCURRENCY`)

24.11.2026 proces web stawał 9 razy na ok. 52 s (CPU 86–100%, bez pełnego GC). Jeden
proces uvicorna = wszyscy czekali, przeglądarki zrywały żądania po 30 s, Traefik dawał 503.
Decyzja Artura z 24.11.2026: obok poprawki przyczyny drugi proces web jako ubezpieczenie.
Strażnik stosu przy zastoju (`loop_stall`) to osobny temat.

## Wariant: dwa procesy w jednym kontenerze, nie druga replika

`WEB_CONCURRENCY` czyta uvicorn sam (`exec uvicorn` w `entrypoint.sh` bez `--workers`).
Nadzorca binduje gniazdo, dwa procesy dzielą jedną kolejkę `accept`. Zablokowany proces
nie woła `accept`, więc nowe połączenia bierze drugi. Tracą tylko żądania, które w chwili
zastoju już wisiały na połączeniach do zablokowanego procesu.

Druga replika za Traefikiem dostawałaby połowę nowych żądań (round-robin), aż healthcheck
(3 × 15 s) ją zdejmie, a Coolify w trybie compose i tak nie ma rolling update.

- **Nadzorca uvicorna (0.54) nie ubija procesu za zastój w Pythonie.** Odpowiada na ping
  z osobnego wątku, który dostaje GIL co 5 ms. Zastój w kodzie C, który trzyma GIL dłużej
  niż `--timeout-worker-healthcheck` (5 s), kończy się SIGKILL i startem nowego procesu
  (ok. 15 s importu i lifespanu, żądania w toku przepadają).
- **Procesy startują przez `spawn`, bez współdzielenia pamięci.** RSS procesu web 24.11:
  1,53–1,92 GB, więc `mem_limit` backendu to 6g.
- **Pula jest na proces** (20+30 od 25.11.2026, wcześniej 40+10; szczyt 50 bez zmian,
  → `pamiec-postgresa.md`). Budżet `max_connections=250`: 2 kontenery (rolling update B2)
  × 2 procesy × 50 + worker 30 = 230, zapas 15. Jeden proces 30+10 by się dławił: 24.11
  szczyt ≥ 40 połączeń był w 16 z 69 minut. Pilnuje `tests/test_process_roles.py`.
- **Więcej niż 2 procesy** = przeliczenie `max_connections`, `mem_limit` i `WEB_PROCESSES_MAX`
  w teście.

## Włączenie i wycofanie

Compose: `WEB_CONCURRENCY: ${NEXUS_WEB_CONCURRENCY:-1}`. Domyślnie jeden proces, jak przed 24.11.
Włączenie: workflow „Coolify set env” `NEXUS_WEB_CONCURRENCY=2` z `redeploy=true`, w oknie
wdrożeń i dopiero po „włącz” Artura. Wycofanie: ta sama zmienna na `1`. `max_connections`
i `mem_limit` obowiązują od wdrożenia PR-a, niezależnie od przełącznika.

Kilka procesów działa tylko w roli `web`. Przy `NEXUS_BACKEND_PROCESS_ROLE=all` (wycofanie
workera bez rewertu) `entrypoint.sh` ustawia `WEB_CONCURRENCY=1`: w `all` blokady doradcze
i bus są wyłączone, a pętle ma tylko lider, więc dwa procesy `all` dublowałyby pracę.

Po włączeniu `runtime_metrics` ma dwie linie na minutę z `process_role=web`, rozróżnia je `pid`.
Obciążenie procesu web licz per `pid`, a sumę połączeń jako sumę obu.

**Na produkcji od 24.11.2026, 19:13** (czas warszawski; Deploy po set env zielony o 19:23). Do 20:47
były cztery kontenery z rzędu, bo po zmianie wdrażały jeszcze slot 20:05 i dwie inne sesje
(„Coolify set env” z redeployem). W każdym proces miał `WEB_CONCURRENCY=2`, a `runtime_metrics`
dawał co minutę linie z dwóch `pid`. Ostatni kontener: `pid` 279 i 280 po 37 linii bez przerwy,
`/api/health` healthy w każdej rundzie co 5 min.

| | 1 proces (18:31–19:11) | 2 procesy (19:18–20:47) |
|---|---:|---:|
| `rss_mb` na proces | 1211–1234 | 902–1101 |
| `pool_in_use_max` na proces | do 28 | do 43 |
| połączenia w `pg_stat_activity` (z 250) | 63 | 29–100, na koniec 57 (web 38, worker 18) |
| 5xx w `http_outcome` | 0 z 2886 | 0 (poza 503 `/api/health/deep` przy starcie kontenera) |
| żądania > 30 s | 0 | 0 |

- To wieczór i świeży start. Dzień roboczy jest niżej (25.11).
- Set env z `redeploy=true` w oknie 18–22 wdraża cały HEAD maina, także merge'e czekające na
  slot (24.11 z przełącznikiem poszło 8 PR-ów). Sama zmienna: zaraz po wdrożeniu slotu albo po 22:00.
- `pid` w świeżym kontenerze się powtarza (279 i 280 po dwóch wdrożeniach z rzędu), więc ten sam
  `pid` nie dowodzi, że kontenera nie podmieniono. Nowy kontener widać po `deployedAt`
  w `/api/health`, padnięcie procesu po nowym `pid` w tym samym kontenerze.
- `prod_readonly.py logs` przepuszcza tylko `runtime_metrics`, `http_outcome` i `loop_stall`,
  więc „Child process died” tam nie widać. Dowodem jest ciągłość: co minutę linia z każdego `pid`.
- Web i worker mają w Postgresie ten sam `application_name` `nexus-backend`. Rozróżnia je
  `client_addr`: przy adresie weba są dwa połączenia `nexus-process-bus`, przy workerze
  `nexus-background-leader`.

**Dzień roboczy 25.11.2026.** Kontener z wdrożenia o 06:41, pula web 40+10, jeszcze przed
#3995 i #3996. `runtime_metrics` 06:46–17:19 z lukami 11:16–12:15 i 13:17–13:31, razem
164 302 żądania.

| | 2 procesy (06:46–17:19) |
|---|---:|
| `rss_mb` na proces | 956–1985, rośnie przez dzień; suma obu do 3869 z 6144 |
| `pool_in_use_max` na proces | do 50; ≥ 45 w 4 i 8 minutach z ok. 557, = 50 w 1 i 2; mediana 12 |
| `cpu_pct` na proces | do 127 i 136 |
| `loop_lag_ms_p99` / `loop_lag_ms_max` | do 12,9 s / do 34,6 s |
| bloki pętli > 10 s (`loop_lag_ms_max`) | 26, od 10,3 do 34,6 s, mediana 22,3 s |
| połączenia w `pg_stat_activity` (z 250) | szczyt 121 o 13:24 (web 99, worker 21); web + worker: mediana 108 z 230 |
| 5xx w `http_outcome` | 157 (0,10%), z tego 156 w dwóch restartach Postgresa po OOM |
| żądania > 30 s | 32 |
| 429 | 60 |

- **Drugi proces robi to, po co jest.** `loop_stall` (blok > 5 s) był 79 razy, z czego 70
  w `GET /api/pipeline/my-next-steps` (`_text_hit`, poprawka w #3996). W każdym z 26 bloków
  > 10 s drugi proces odpowiadał dalej: 17–357 odpowiedzi na blok, 1,3–10,7 na sekundę
  (5 min wcześniej 4,1–11,3). W środku bloków nie było 5xx, z wyjątkiem bloku o 16:50, który
  zbiegł się z awarią Postgresa. Razem z blokiem kończyło się 1–13 żądań, które już były
  w zablokowanym procesie. 24.11 przy jednym procesie 9 zastojów ok. 52 s kończyło się 503
  z Traefika.
- **Zastoje licz z `loop_lag_ms_max`, nie z p99.** Przy mniej niż 100 próbkach na minutę p99
  to druga największa próbka: z 26 bloków > 10 s p99 pokazał 2. `loop_stall` loguje się po
  powrocie pętli, więc początek bloku = czas `loop_stall` minus `loop_lag_ms_max`.
  `http_outcome.duration_ms` liczy od wejścia do aplikacji, więc żądanie czekające w gnieździe
  zablokowanego procesu nie ma długiego czasu.
- **5xx dał Postgres, nie procesy web.** Było 38 × 500 o 10:19:19–10:19:23 i 118 × 5xx
  (111 × 500, 7 × 503) o 16:50:10–16:51:04. Oba razy był to OOM cgroupa Postgresa
  (`oom_kill` 1, potem 2) i crash recovery w ok. 3–4 s; poza tym była jedna 500 o 08:25.
  Drugi proces to druga pula: w dzień mediana trzymanych połączeń wynosiła 108, a 24.11
  wieczorem przy jednym procesie 63. Każde połączenie to ok. 35 MB w limicie bazy.
  Poprawka: #3995, → `pamiec-postgresa.md`.
- **429.** 56 × `POST /api/search/candidates/scores` przyszło o 13:39:48–13:40:04, po 116
  żądaniach w ok. minutę. Przeszło dokładnie 60, czyli pełny limit `60/minute` na użytkownika
  (2 × 30 po `share_per_process`), więc to nagły wyrzut klienta, nie skutek podziału limitu. Do tego
  4 × `GET /api/candidates/{id}/recommendations` o 08:33–08:35 (limit 20/min, 10 na proces).
- **Wynik: dwa procesy zostają** (decyzja Artura z 25.11). RSS jest daleko od 2,6 GB na proces,
  pula była pełna najwyżej 2 minuty na proces, a 5xx wzięły się z OOM bazy, który naprawia
  #3995. Po wdrożeniu #3995 zapas pamięci bazy sprawdzaj jak w `pamiec-postgresa.md`
  („Jak sprawdzić”).
- **Jak mierzyć.** Logi pobieraj przez `prod_readonly.py logs` co 30 min, nie co godzinę.
  Przy dziennym ruchu log kontenera web nie sięga godziny wstecz: kawałek pobrany po godzinie
  zaczynał się 13 min za późno. `pg_stat_activity` próbkuj co minutę przez
  `prod_readonly.py sql`. 25.11 próbek brakuje z 11:48–12:20 (laptop bez sieci), więc
  szczytu z tego okna nie potwierdzono.

## Pomiar na stagingu (24.11.2026)

Kontener z obrazu stagingu, kod z gałęzi, `WEB_CONCURRENCY=2`, baza stagingu. 16 klientów
z pulą keep-alive (jak Traefik) pyta o `/api/health/live`. Po 10 s jeden proces dostaje
SIGUSR1 i 30 s kręci pętlę Pythona (`sitecustomize.py` tylko w kontenerze testowym).
Skrypty: `scripts/staging/stall_probe/`.

| | 2 procesy | 1 proces |
|---|---:|---:|
| odpowiedzi w czasie 30 s zastoju | 2785, wszystkie 200 w ≤ 0,1 s | 0 |
| żądania, które przepadły (timeout 30 s) | 8, wisiały na połączeniach do zablokowanego | 16, czyli wszystkie w toku |
| przepustowość przed zastojem | ok. 250 żądań/s | ok. 145 żądań/s |

W czasie zastoju przepustowość spada o połowę (pracuje jeden proces), po nim wraca.
Zablokowany proces przeżył: nadzorca go nie ubił, w logu nie ma „Child process died”.
Kroki startu poszły po kolei: w logu pierwszy proces ma je o 48,98–49,03 s, drugi od 49,06 s.

Ta sama karta, osoba A z gniazdem w procesie 8, osoba B w procesie 9 (sprawdzane w `/proc`):

| | gałąź | main (bez tej zmiany) |
|---|---|---|
| A i B widzą się nawzajem | tak | nie |
| po zamknięciu gniazda B A widzi tylko siebie | tak | nie (nie dostaje aktualizacji) |
| 40 nieudanych logowań z jednego IP, limit 30/min | przeszło 28 | przeszło 40 |

Jak powtórzyć (kontener obok stagingu, bez entrypointu, więc bez DDL na wspólnej bazie;
nazwa inna niż `nexus-staging-backend-branch`, którą zajmują testy ścieżki):

```bash
W=~/.codex/worktrees/nexus-staging-data-promotion; C=~/.nexus-staging/code; R=<repo>
docker compose -p nexus-staging --project-directory $C -f $C/docker-compose.staging.yml \
  --env-file $W/.env.staging.local --env-file $W/.env.staging-flags.local \
  run -d --rm --no-deps --name nexus-staging-backend-2web -p 127.0.0.1:8142:8000 \
  -v "$R/backend:/app" -v "$R/scripts/staging/stall_probe:/stall:ro" \
  -e WEB_CONCURRENCY=2 -e PYTHONPATH=/stall -e NEXUS_PROCESS_ROLE=web \
  --entrypoint sh backend -c 'exec uvicorn app.main:app --host 0.0.0.0 --port 8000'
python scripts/staging/stall_probe/stall_load.py http://127.0.0.1:8142 nexus-staging-backend-2web
docker cp scripts/staging/stall_probe/presence_cross.py nexus-staging-backend-2web:/tmp/
docker exec -w /app nexus-staging-backend-2web python /tmp/presence_cross.py
docker cp scripts/staging/stall_probe/bus_chunk_probe.py nexus-staging-backend-2web:/tmp/
docker exec -w /app -e PYTHONPATH=/app nexus-staging-backend-2web python /tmp/bus_chunk_probe.py
docker stop nexus-staging-backend-2web
```

Duża wiadomość przez prawdziwy NOTIFY (`bus_chunk_probe.py`, ok. 15 kB) poszła w 3 kawałkach
i doszła cała.

`stall_load.py` i `login_limit.py` potrzebują `httpx` (venv backendu).

## Co przechodzi między procesami (`process_bus`)

Temat z `subscribe(..., others_only=True)` pomija własne NOTIFY (`PROCESS_TOKEN`, nie PID:
web i worker to osobne kontenery). Nadawca robi swoją część lokalnie, pozostali przez bus.
`publish_soon` wysyła w tle, także z kodu synchronicznego; w roli `all` nic nie robi.

- **Wiadomość ponad 7900 B idzie w kawałkach** (base64 po 5600 B) w jednej transakcji:
  NOTIFY z jednej transakcji dochodzą w kolejności wysłania, a odbiorca skleja je po `c`.
  Bez tego ramka czatu z długą wiadomością (do 10 000 znaków) nie dochodziła do drugiego
  procesu, a front dokleja wiadomość prosto z ramki. Odmowa dopiero ponad 512 kB; niepełne
  kawałki wygasają po 60 s.
- **Obecność ma numer kolejny per proces** (`seq`). `publish_soon` z dwóch transakcji może
  dojść w odwrotnej kolejności (wejście i wyjście tuż po sobie), więc starsza wiadomość po
  nowszej jest pomijana.

| Temat | Co | Kiedy |
|---|---|---|
| `ws_notify`, `ws_broadcast` | ramki na żywo (`pipeline_changed`, czat, dzwonek, wzmianki) | web: tylko przy > 1 procesie web; worker: zawsze |
| `ws_presence`, `ws_presence_sync` | „kto ogląda / edytuje”: zmiana od razu, pełny stan co 30 s, wpis bez odświeżenia wygasa po 75 s | > 1 proces web (pętla `presence_sync`) |
| `cache_invalidate` | `app.core.cache.cache_invalidate(prefix)` po zmianie danych: KPI, raporty klientów, mapa technologii | zawsze (także worker) |
| `policy_cache_invalidate` | migawka uprawnień po zapisie (bez tego odebrane prawo działało do 30 s) | zawsze |
| `jarvis_cancel` | „Zatrzymaj” trafił do innego procesu niż tura | zawsze |
| `job_twins_reset` | podpowiedzi „bliźniaków” po decyzji | zawsze |

`get_viewers` i `viewer_ids` (HTTP `/api/presence`, `pipeline_realtime`) łączą widzów obu procesów.
Osoba w dwóch procesach to jeden wpis.

**Sprzątanie to nie unieważnienie.** Wyrzucenie starszych migawek tuż przed zapisem nowej
(`kpi_engine` kamienie milowe, `custom_metrics` zaliczone CTE) idzie przez `cache_evict_local`.
Rozgłoszone kasowałoby drugiemu procesowi jego świeżą migawkę i oba liczyłyby ciężkie CTE
na zmianę zamiast raz na minutę.

## Co dzielimy, a co robi tylko jeden proces

- **Stan w bazie:** odczyt CV z podglądu „Dodaj kandydata” (`cv_preview_reads`, 0771,
  `services/cv_preview_cache.py`). `/from-cv` w drugim procesie bierze odczyt z podglądu,
  zamiast czytać CV modelem drugi raz. Pierwszy zapis wygrywa (`cache_single_flight` jest
  per proces), więc podgląd pokazuje odczyt z tabeli, czyli ten, który zapisze `/from-cv`.
  Retencja jak w pamięci procesu: 30 min, wiersz znika po zapisie kandydata, a odczyt
  i tekst są zaszyfrowane kluczem z bajtów pliku, więc kopia bazy ich nie odczyta.
- **Limity w pamięci procesu dzielimy przez `web_process_count()`, z zaokrągleniem w górę**
  (decyzja Artura 24.11.2026, bez Redisa): slowapi (`ProcessShareLimiter` w `rate_limit.py`),
  dzienny limit białej listy VAT, godzinowy budżet podglądu z KSeF. Suma zostaje jak przy
  jednym procesie, a przy nieparzystym limicie rośnie o 1 (3/min to 2 + 2). Koszt: osoba,
  której wszystkie żądania trafią do jednego procesu, dostaje 429 przy połowie limitu
  (logowanie 15/min zamiast 30).
- **Tylko jeden proces:** uzupełnianie korpusu słów (`keyword_corpus_backfill`, blokada doradcza;
  drugi czyta gotowość z bazy jak worker) i przebieg JJIT (blokada `jjit_run`, chroni też
  przed wyścigiem web ↔ worker).
- **Ręczne przebiegi z tras, jeden naraz w całym backendzie** (`app/core/manual_runs.py`):
  import talent-radar, backfill pul, cztery backfille kandydatów, backfill procesów rekrutacji,
  karty z portali, arkusze z notatek, wnioski z notatek, poczta zamówień (admin i przycisk
  operatora). `start_exclusive` bierze blokadę w zadaniu biegu i trzyma ją do końca; drugi
  start z dowolnego procesu web albo przy biegu w workerze dostaje 409, a nie cichy drugi bieg
  ani „started” dla biegu, który się pominie. Status: `is_running` czyta `pg_locks`, postęp
  i wynik idą do `app_settings` (`publishing`, `admin_backfill_progress:*`). Blokadę sprawdza się
  przed odczytem zapisu: bieg zapisuje stan końcowy, zanim ją zwolni, więc zapis „trwa” przy
  wolnej blokadzie znaczy proces, który padł (import pokazuje wtedy błąd „Bieg przerwany”).
- **Po kolei:** jednorazowe kroki lifespanu od `retire_candidate_saved_searches` do seedu B2B
  (`cross_process_wait_lock("startup_oneoffs")`, najwyżej 180 s czekania, potem bez blokady).

## Świadomie per proces

- Pamięci podręczne z TTL bez unieważnienia (liczniki wymagań, embeddingi, słowniki, tokeny
  M365): podwójne rozgrzanie, poza tym bez skutku. Najdroższe jest `requirement_row_counts`:
  po starcie każdy proces web liczy ok. 7 min zapytań (pomiar 27.10), potem odświeża wpisy
  raz na dobę. Do rozgrzania pulpit może w jednym procesie pokazać powód `rare_word`,
  a w drugim jeszcze nie.
- `cache_single_flight`: ten sam drogi snapshot może się policzyć raz w każdym procesie.
- Semafory (LibreOffice, wątki modeli): w kontenerze 2× więcej naraz.
- „Kto jest online” dla maila z czatu (`get_connected_user_ids`): drugi proces nadrabia
  `last_seen_at` (stempel co 5 min, próg 15 min).

## Nowy kod

Stan w pamięci procesu, który czytają trasy: unieważnienie przez `cache_invalidate` (po zmianie
danych; samo sprzątanie przez `cache_evict_local`) albo temat `process_bus` z `others_only=True`,
stan w bazie albo blokada doradcza
(`app/core/process_lock.py`), albo świadomie per proces z wpisem w tym pliku. Nowy licznik
limitu w pamięci dzieli się przez `web_process_count()`. Nowa pętla, która pisze do bazy
i musi zostać w web, potrzebuje blokady, bo biegnie w każdym procesie web.
Ręczny bieg z trasy startuje przez `manual_runs.start_exclusive`, a status czyta
`manual_runs.is_running` — nie flaga `running` ani słownik zadań w pamięci procesu.
Testy: `tests/test_multi_web_processes.py`, `tests/test_process_roles.py`,
`tests/test_manual_runs_cross_process.py`.
