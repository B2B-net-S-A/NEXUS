# Przerwa przy wdrożeniu — skąd się bierze i jak ją skracamy

Pomiar z 02–03.11.2026, Coolify 4.5.3. Cel Artura: przerwa 1–2 s zamiast minut
(decyzja 03.11.2026: pełna ścieżka, trzy etapy niżej).

## Mechanizm

Coolify w trybie compose nie ma rolling update. Buduje obrazy (ok. 5 min, system
wtedy działa), a potem zatrzymuje po kolei **wszystkie** kontenery aplikacji, także
Postgresa i Qdranta, i dopiero po ostatnim uruchamia nowe
(`ApplicationDeploymentJob.php:887`, `stop_running_container(force: true)` przed
`up -d`; `docker stop --time=30` na kontener). Dopisuje też `.env` do każdej usługi
(`parsers.php:3616`), więc brak `env_file` w naszym compose niczego nie izoluje:
kontener bazy ma 203 zmienne, także klucze API. Stwierdzenia w starszych notatkach,
że to rolling update albo że baza się nie restartuje, są błędne.

## Na co idzie czas (wdrożenie 02.11.2026 23:39 UTC)

| Odcinek | Czas | Przerwa API | Przerwa frontu |
|---|---:|---|---|
| Stop backupu (ignorował SIGTERM) | 30 s | nie, stary backend jeszcze działa | nie |
| Stop backendu, bazy, Qdranta, Alloya, frontu | 13 s | tak | ostatnia 1 s |
| Stop budzika (ignorował SIGTERM) | 30 s | tak | tak |
| Tworzenie kontenerów i baza healthy | 8 s | tak | ok. 2 s |
| `entrypoint.sh` | 170 s | tak | nie |
| Import aplikacji i lifespan uvicorna | 15 s | tak | nie |

Razem API ok. 245 s, front ok. 40 s. W `entrypoint.sh` DDL to ok. 25 s, a ok. 130 s
to 42 kroki naprawcze, zwykle po 3–4 s: osobny proces Pythona na każdy, ze znacznikiem, że
praca jest dawno zrobiona. Sama przerwa rosła z każdą taką naprawą: 62 s (15.09),
116 s (28.09), 165 s (14.10), 245 s (11.2026).

Skutki uboczne restartu bazy: pusty `shared_buffers` (8 GB) po każdym wdrożeniu,
czyli wolne pierwsze zapytania, i zerwane połączenia wszystkich zadań w tle.

## Etapy

1. **Szybkie poprawki** (bez zmian w infrastrukturze).
   Pułapka SIGTERM w sidecarach (−30 s na API i froncie) i pominięcie kroków
   naprawczych ze znacznikiem bez uruchamiania Pythona. Szacunek: API ok. 75 s,
   front ok. 8 s.
2. **Baza osobno.** Postgres i Qdrant w osobnym zasobie Coolify, którego wdrożenie
   aplikacji nie zatrzymuje. Ciepły cache, baza bez sekretów aplikacji, trwałe nazwy
   hostów. Wymaga jednego zaplanowanego okna (przepięcie wolumenów bez kopiowania),
   zmiany skryptów szukających kontenera po nazwie `postgres-ocgkw…`, backupu
   i odświeżania stagingu.
3. **Nakładanie kontenerów.** Backend i front jako osobne aplikacje Coolify
   z budowaniem z Dockerfile: dla nich Coolify robi rolling update (start nowego,
   healthcheck, dopiero potem stop starego, `rolling_update()`), wymaga braku
   mapowania portów i nazwy niespójnej (`is_consistent_container_name_enabled = false`).
   Tylko ten etap daje 1–2 s.

## Warunki etapu 3 (bez nich nakładanie psuje dane)

- **Pętle w tle mają jednego właściciela.** 24 pętle bez wyboru lidera: dwa procesy
  naraz to podwójne maile i alerty. Nowy kontener startuje pętle dopiero po przejęciu
  blokady (`pg_try_advisory_lock`), którą stary zwalnia przy SIGTERM.
- **Start nie zakłada, że poprzedni proces nie żyje.** Wprost: `m365-sync-reset`
  oznacza wysyłki `pending` jako `uncertain`, bo proces, który je trzymał, „już nie
  żyje”. Przy nakładaniu żyje. Takie kroki idą za blokadę lidera.
- **Schemat zgodny wstecz.** Stary kod chodzi na nowym schemacie przez czas startu:
  najpierw dodanie kolumny, usunięcie dopiero w kolejnym wdrożeniu.
- **DDL przy żywym ruchu.** Dziś w trakcie `entrypoint.sh` nikt nie pisze do bazy.
  Przy nakładaniu `lock_timeout` zacznie realnie odpuszczać instrukcje; pominięty DDL
  ma być widoczny jako błąd, a nie cicho iść dalej.
- **Pula połączeń.** 2 × 60 potencjalnych połączeń przy `max_connections=100`.

## Pomiar

Każdy bieg Deploy raportuje przerwę frontu i API oraz restart Postgresa
(`.github/scripts/deploy_downtime_report.py`). Odbiór każdego etapu to te liczby na
kolejnych wdrożeniach, nie sam zielony workflow.

## Sieć osobnych aplikacji: `nexus-front`, nie `coolify`

Ustalone na kodzie Coolify 4.5.3 (13.11.2026). Aplikacja z Dockerfile dołącza
wyłącznie do sieci swojego destination (`--network` w opcjach `docker run` jest
ignorowane). Przełącznik `connect_to_docker_network` na aplikacji compose wpina do
wspólnej sieci `coolify` **każdą** usługę (`parsers.php`, `applicationParser`), a w tej
sieci Coolify ma własną usługę o nazwie `postgres` (kontener `coolify-db`). Backend
łączy się z `postgres:5432`, więc nazwa miałaby dwa adresy. Dlatego:

- front (i później backend) stoi w osobnym destination `nexus-front`; Coolify przy jego
  założeniu tworzy sieć i podłącza do niej `coolify-proxy`,
- compose dołącza `nexus-front` jako sieć zewnętrzną; parser dopisuje każdą sieć
  z najwyższego poziomu do każdej usługi, co tu jest nieszkodliwe, bo w `nexus-front`
  są tylko kontenery NEXUSA i proxy,
- `connect_to_docker_network` na aplikacji NEXUSA zostaje wyłączony.

## Etap B1: front jako aplikacja `nexus-frontend` — kolejność

Wszystko przez workflow „Coolify frontend app” (`coolify-frontend-app.yml`, tylko z maina,
konto `env -u GH_TOKEN gh`), każdy krok zmieniający produkcję w oknie wdrożeń.

1. `mode=plan` — odczyt: identyfikatory, sieć `nexus-front`, zmienne, usługi compose z domeną.
2. `mode=create` — destination `nexus-front` (sieć + `coolify-proxy`) i aplikacja bez domeny.
3. `mode=deploy` — wdrożenie próbne; zielone = `finished`, SHA w `version.json` z logu builda,
   kontener `running:healthy`.
4. PR z `networks: nexus-front` w `docker-compose.yml` wchodzi dopiero po kroku 2 i musi być
   wdrożony przed krokiem 5: od niego front widzi `backend`. Coolify zatrzymuje wszystkie
   kontenery compose, zanim odkryje brak sieci zewnętrznej, więc Deploy ma bramkę
   „Frontend app preflight” przed wyzwoleniem compose (brak sieci = czerwony bieg, produkcja
   nietknięta). Ten sam PR dodaje do Deploy kroki frontu: po udanym compose wdrażają
   `nexus-frontend` z tego samego commitu, ale tylko gdy aplikacja ma domeny (przed `switch`
   pomijają). `switch` odmawia, gdy wdrożony compose nie ma sieci `nexus-front`.
5. Po „przepnij” Artura: `mode=switch` — aplikacja dostaje domeny frontu i wdraża się
   (rolling update), dopiero potem compose oddaje domeny frontu w Coolify. Do następnego
   wdrożenia compose Traefik ma dla tych domen dwa zdrowe kontenery.
   `switch` zapisuje też etykiety: te, które Coolify wygenerował z domen, plus middleware
   `nexus-front-retry` (Traefik `retry`, 3 próby od 100 ms) na początku łańcucha każdego
   routera, i wyłącza przepisywanie etykiet przez Coolify
   (`is_container_label_readonly_enabled=false`), bo inaczej kolejny PATCH domen zgubiłby
   retry. Logika etykiet jest wspólna dla frontu i backendu (B2): `.github/scripts/coolify_labels.py`.
   Zmiana domen frontu = ponowne dołożenie retry (funkcja `set_domains`), nie edycja
   w panelu. Do tego `rolling_update_drain_seconds=10` i `stop_grace_period=30`.

   Dlaczego bez błędów przy podmianie: Coolify startuje nowy kontener, czeka na healthcheck
   i 10 s na przejęcie ruchu (etykiety obu kontenerów są identyczne, więc Traefik ma jedną
   pulę z dwoma serwerami), potem `docker stop`. Next standalone na SIGTERM przestaje
   przyjmować połączenia i kończy żądania w toku (`server.close()` w
   `next/dist/server/lib/start-server.js`; `node` jest PID 1, więc dostaje sygnał). Żądanie,
   które Traefik wyśle w tej chwili do starego kontenera, dostaje odmowę połączenia
   i `retry` ponawia je na nowym.
6. PR usuwający usługę `frontend` z compose do kolejki (bramka Deploy wymaga od niego, żeby
   front miał domeny, a compose ich nie miał — `FRONTEND_APP_REQUIRED=true`). Jego
   wdrożenie zdejmuje stary kontener; od niego raport przerwy mierzy front jako
   osobną aplikację (`--frontend-app true`). Odbiór: 0 próbek frontu bez 200 na kolejnych
   wdrożeniach; każda zła próbka to ostrzeżenie w biegu Deploy.

Sprawdzenie po 5 i 6: `curl -s https://nexus.b2bnetwork.pl/version.json` (SHA maina),
kilka razy `curl -sI 'https://nexus.b2bnetwork.pl/auth/microsoft/callback?error=access_denied'`
(302 z backendu, nie 5xx: front doszedł do `backend:8000`), logowanie i jedna strona SSR.

**Wycofanie.**
- Zły kod frontu: `mode=deploy` z `commit=<poprzedni SHA>` — rolling update, bez przerwy.
- Zła aplikacja frontu przed krokiem 6: `mode=rollback` (domeny wracają do compose;
  wczytany compose ma jeszcze usługę `frontend`), Deploy z `force_rebuild=true`, potem `mode=stop`.
- Po kroku 6: revert PR-a z kroku 6 i Deploy (front dalej obsługuje `nexus-frontend`), potem
  `mode=rollback`, Deploy z `force_rebuild=true` (stary front dostaje domeny), na końcu `mode=stop`.
  Każdy Deploy compose to przerwa API, więc w oknie wdrożeń.
