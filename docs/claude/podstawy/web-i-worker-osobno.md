# Web i worker osobno — pętle w tle poza procesem obsługującym żądania

Audyt 07.11.2026, pozycja B2. Pomiar 04.11: kanban 0,14 s na stagingu, 13,8 s w szczycie,
bo żądania i ok. 110 pętli dzielą jeden wątek Pythona. Plan wdrożenia i liczby ze stagingu
są w opisie PR-a.

## Role

`NEXUS_PROCESS_ROLE`: `web` (HTTP), `worker` (pętle), `all` (jeden proces: testy, wycofanie).
Produkcja: `backend` ma `${NEXUS_BACKEND_PROCESS_ROLE:-web}`, usługa `worker` ma `worker`.
Rejestr pętli jest jeden (`lifespan` w `main.py`), a `app/core/process_role.py` decyduje,
co zostaje w procesie danej roli.

- **Worker** ma ten sam obraz, nie robi migracji i czeka, aż web odpowie (`entrypoint.sh`).
  Zawsze jeden proces uvicorna (`WEB_CONCURRENCY=1`), bo pętle pilnuje blokada lidera.
- **Nazwa `worker`, nie `backend-…`:** `prod_readonly.py` i nocna kopia szukają po prefiksie
  `backend-ocgkw`, więc inny prefiks nie myli im kontenera.
- **Web** nie bierze blokady lidera. Stan pętli do `/api/health` i `/api/admin/snapshot`
  czyta z workera (`GET /api/health/background`, bufor 10 s). Worker nie odpowiada =
  `checks.background_tasks` zaczyna się od `unhealthy` i alarmuje `uptime-probe`.
- **Pule:** web 40+10, worker 15+15, razem 80 przy `max_connections=100`.

## Co musi zostać w web

Nowa pętla idzie domyślnie do workera. Do `WEB_ONLY_TASKS` trafia tylko ta, która pracuje
na pamięci procesu czytanej przez trasy albo gniazda:

| Pętla | Powód |
|---|---|
| `access_usage` | opróżnia licznik, który zbierają trasy |
| `chat_email_fallback` | „kto jest online” znają gniazda w web |
| `requirement_row_counts` | wypełnia bufory czytane przez edytor wymagań |
| `keyword_corpus_backfill` | ustawia flagi gotowości korpusu czytane przez wyszukiwarkę |
| `critical_stats_cache` | statystyki krytycznych dla bramki w trasach |

W obu procesach biegną `runtime_metrics` (mierzy własną pętlę zdarzeń, pole `process_role`)
i `process_bus`.

Flagi korpusu są pamięcią procesu, a worker też szuka kandydatów (`saved_search_alerts` przez
ASGITransport). Dlatego przy starcie workera `keyword_corpus_readiness` czyta z bazy te same
warunki, po których web ustawia flagi, i ponawia odczyt, aż web skończy uzupełnianie. Bez tego
worker liczył zapisane wyszukiwania inną ścieżką niż lista w web.

## Współpraca web i workera

- **`app/core/process_bus.py`:** LISTEN/NOTIFY Postgresa, tylko sygnały do zgubienia, do 7,9 kB.
  Worker wysyła tędy powiadomienia na żywo (`ConnectionManager.notify_user`), a webhook M365
  prosi o dodatkowy przebieg. `asyncio.Event` nie przechodzi między procesami:
  `integration_webhooks.request_wakeup` budzi pętlę najpóźniej po swoim 10-sekundowym timeoucie.
- **`app/core/process_lock.py`:** blokada doradcza na czas biegu tam, gdzie trasa i pętla mogą
  ruszyć tę samą pracę (sync skrzynki M365, poczta zamówień, dokumenty kontraktów, wnioski z notatek).
  Nowy `asyncio.Lock` dzielony przez trasę i pętlę potrzebuje też jej.
- **`reset_interrupted_m365_state`** biegnie przy starcie web i przy przejęciu pętli przez workera.
- Jednorazowe uzupełnienia z początku lifespanu wykonują się w obu procesach. Są idempotentne,
  a worker startuje po web, więc nie biegną równolegle.

## Kilka procesów web (etap 2, jeszcze nie włączony)

`WEB_CONCURRENCY` uvicorn czyta sam, ale dopiero po tych zmianach:

- limiter slowapi ma pamięć procesu, więc limity (także logowania) byłyby N× luźniejsze;
- gniazda: `pipeline_changed`, czat i presence dochodzą tylko do gniazd własnego procesu,
  czyli `process_bus` musi nadawać także z web;
- `ALIAS_MAP` i mapa wiedzy: wymaga zmiany z sesji `slownik-cache`, a przed jej scaleniem także
  worker zostaje na mapie ze startu;
- bufor replay webhooka M365, „Zatrzymaj” Jarvisa, statusy ręcznych backfilli (`_running`, `_TASKS`),
  limit `hr/white_list`;
- jednorazowe uzupełnienia lifespanu biegłyby równolegle w każdym procesie.

Staging: `worker` jest w `docker-compose.staging.yml`. Backend z gałęzi na własnej bazie
potrzebuje `-e NEXUS_PROCESS_ROLE=all`, inaczej nie ma tam pętli.
