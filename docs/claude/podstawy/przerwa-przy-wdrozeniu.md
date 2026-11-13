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

## Stan 13.11.2026 i kolejność dalej

Pomiar 11 wdrożeń z 11–12.11 (raport przerwy z biegów Deploy): Coolify 290–350 s,
przerwa API 83–102 s, front 5–9 s, Postgres restartuje się za każdym razem.
Etap 1 działa, a etapu 3 nikt nie zaczął: `coolify-frontend-app.yml` do 13.11 nie
miał ani jednego uruchomienia. Przed uvicornem ok. 50 s; siatka DDL to 24–28 s na
produkcji, ale 5–10 s na stagingu z ciepłym cache, czyli większość jej czasu to
zimna baza po restarcie.

Decyzja Artura 13.11.2026:

1. **Wieczorne grupowanie** (od razu): pon–pt 18:00–21:59 merge nie przebudowuje
   produkcji, tylko czeka na slot budzika 20:05 / 22:05 (`BATCH_WINDOW` w
   `deploy.yml`, `head_status=evening_batch`). 12.11 byłyby 3 przebudowy zamiast 7.
   Ręczny bieg wdraża od razu.
2. **Front osobno** (etap 3 dla frontu), równolegle.
3. **Backend i worker osobno od razu po froncie**: compose zostaje z bazą, która
   przestaje się restartować. Warunki niżej.
4. **Obrazy budowane w GitHubie (GHCR)** dopiero po backendzie osobno.

Przebudowy `entrypoint.sh` w jeden proces Pythona (ok. 12 faz importuje aplikację
osobno, razem ok. 15–25 s) świadomie nie robimy: po etapie 3 dla backendu cały
entrypoint biegnie, gdy stary kontener obsługuje ruch.

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
