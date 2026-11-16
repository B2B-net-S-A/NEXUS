# Nakładanie kontenerów backendu i workera (etap B2)

Plan i pomiary: `przerwa-przy-wdrozeniu.md`. Cel Artura (13.11.2026): przerwa API najwyżej
ok. 1 s, najlepiej zero błędów widocznych dla ludzi. Backend (rola web) i worker są osobnymi
aplikacjami Coolify z Dockerfile. Coolify 4.5.3 robi wtedy rolling update
(`ApplicationDeploymentJob.php`, `rolling_update()`): start nowego kontenera, healthcheck,
`rolling_update_drain_seconds` czekania, aż proxy skieruje ruch na nowy, i dopiero wtedy
`docker stop` starego z `stop_grace_period`.

## Jak żądanie przeżywa podmianę kontenera

1. **Nowy wchodzi do routingu dopiero zdrowy.** Traefik pomija kontenery, które nie są
   `healthy` (`pkg/provider/docker/config.go:228`, „Filtering unhealthy or starting
   container”), więc w trakcie `entrypoint.sh` ruch zostaje na starym.
2. **Stary schodzi z routingu, zanim przestanie słuchać.** `NEXUS_SHUTDOWN_DRAIN_SECONDS`
   (`app/core/shutdown_drain.py`): pierwszy SIGTERM ustawia drenaż, `/api/health/live`
   zwraca 503, Docker po kilku sondach oznacza kontener `unhealthy`, Traefik go zdejmuje
   (odświeża konfigurację najwyżej co 2 s, `providersThrottleDuration`). Proces przez cały
   drenaż obsługuje żądania normalnie, potem oddaje sygnał uvicornowi.
3. **Żądania w toku kończą się.** `UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN` po drenażu.
4. **Retry Traefika** (`retry.attempts=3`, `initialinterval=100ms`) łapie resztę: połączenie
   zamknięte bez odpowiedzi. Od Traefika 3.7 retry **nie ponawia POST, PATCH, LOCK**
   (`retryNonIdempotentMethod` domyślnie `false`) i nie włączamy tej opcji: ponowienie
   po zerwanym połączeniu mogłoby trafić w zapis, który backend już przyjął. Zapisy
   chroni krok 2, nie retry. Wersję Traefika na serwerze sprawdź przed włączeniem retry:
   starsze nie mają tej opcji, a ich zachowanie dla POST trzeba odczytać z ich dokumentacji.

Bez drenażu uvicorn zamyka gniazdo nasłuchu od razu po SIGTERM, a Traefik kieruje tam
ruch jeszcze przez kilka sekund: GET ratuje retry, POST dostaje 502.

## Ustawienia aplikacji backendu w Coolify

Liczby zależą od siebie; zmiana jednej = przeliczenie reszty.

| Ustawienie | Wartość | Dlaczego |
|---|---:|---|
| healthcheck `/api/health/live` | co 2 s, timeout 5 s, 3 próby | drenaż widać po ok. 6 s; jedna wolna sonda przy obciążeniu nie zdejmuje jedynego kontenera |
| `NEXUS_SHUTDOWN_DRAIN_SECONDS` | 15 | 3 sondy + odświeżenie Traefika z zapasem |
| `UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN` | 20 | zwykłe żądania; stary kontener nikomu już nie przedłuża przerwy |
| `stop_grace_period` (Coolify) | 60 | drenaż + łagodne zamknięcie + zamknięcie lifespanu; potem SIGKILL |
| `rolling_update_drain_seconds` | 10 | nowy kontener jest w routingu, zanim stary dostanie SIGTERM |

Compose (do przepięcia) zostaje przy drenażu 0: tam Coolify zatrzymuje wszystko naraz,
więc czekanie tylko wydłużałoby przerwę.

## Sieci

Aplikacje backendu i workera stoją w destination `nexus-front`, tym samym co front (etap B1).
Do sieci `coolify` nie dołączamy, bo jest w niej `postgres` Coolify.

- **Sieć wpisana jawnie w każdej usłudze compose, z którą rozmawia osobna aplikacja.**
  Coolify 4.5.3 nie przenosi sieci z najwyższego poziomu compose do usług: `parsers.php:1735`
  wstawia ją jako `null`, a `:1775` przyjmuje tylko napis i tablicę, więc sieć znika bez
  błędu. 13.11.2026 front po przepięciu nie widział `backend:8000` i logowanie Microsoft
  kończyło się `backend_unreachable` (#3389: `networks: [nexus-front]` w `backend`).
  Przed startem aplikacji backendu i workera to samo dostają `postgres` i `qdrant`.
  Sieć bazową Coolify usługa dostaje i tak; dowód to backend po #3389, który dalej widzi
  `postgres`. Pilnuje tego `backend/tests/test_compose_networks_contract.py`.
- **Front znajduje backend po aliasie `backend`.** Aplikacja z Dockerfile dostaje w sieci
  destination alias równy nazwie kontenera, a ta zmienia się przy każdym wdrożeniu. Dodatkowe
  aliasy ustawia pole `custom_network_aliases` (`ApplicationDeploymentJob.php:4479-4495`,
  API `PATCH /applications/{uuid}`). Aplikacja backendu dostaje alias `backend`, więc
  `INTERNAL_API_URL=http://backend:8000` we froncie zostaje bez zmian. W chwili przepięcia
  alias `backend` mają naraz usługa compose i aplikacja, a DNS Dockera zwraca adresy obu.
  Obie obsługują ruch, więc przerwy nie ma. Wyłączenie `backend` w compose zostawia już tylko
  aplikację. W czasie rolling update alias mają stary i nowy kontener; stary jest wtedy
  w drenażu i dalej odpowiada.

## Gniazda

Stary kontener zamyka gniazda (czat, obecność, `pipeline_changed`) przy zamknięciu.
Klient łączy się ponownie z opóźnieniem 0,5–30 s (`reconnectDelayMs`), po powrocie
odświeża dzwonek, KPI i Tablicę i odnawia subskrypcje obecności
(`frontend/src/hooks/__tests__/useNotifications.test.tsx`).

## Luka przy przejęciu pętli przez nowy worker

Nowy worker startuje w `standby` (blokada lidera, `app/core/background_leader.py`).
Stary po SIGTERM anuluje pętle i zwalnia blokadę na końcu lifespanu, nowy przejmuje ją
w ciągu 1 s (`retry_seconds`). Pętle startują od nowa, każda ze swoim opóźnieniem
początkowym (np. sync M365 45 s, retencja kolejek 180 s). Praca w tle stoi więc przez
czas zamknięcia starego workera plus opóźnienie danej pętli; ludzie tego nie widzą,
bo żadne żądanie nie czeka na pętlę. Przebieg anulowany w połowie nowy worker podejmuje
od stanu w bazie, tak samo jak po każdym dzisiejszym restarcie (wysyłki i synchronizacje
M365 sprząta `m365_interrupted_reset`).

## Co jeszcze musi być spełnione

- Sieci: `postgres` i `qdrant` jawnie w `nexus-front`, alias `backend` dla aplikacji (wyżej).
- Pule: `max_connections=150` na 2 × web + worker (`web-i-worker-osobno.md`).
- Schemat zgodny wstecz: `migracje-zgodne-wstecz.md`.
- DDL pominięty przy żywym ruchu: `checks.migrations: degraded` + Sentry.
- Start nie zakłada, że poprzednik nie żyje: `m365_interrupted_reset` (pętla w workerze).
