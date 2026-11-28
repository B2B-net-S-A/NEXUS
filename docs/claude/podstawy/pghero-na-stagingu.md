# PgHero na stagingu — wolne zapytania, indeksy, rozmiary tabel i blokady · port 8280, reset po nocnej kopii, produkcja tylko do odczytu
<!-- indeks: ankane/pghero przypięty do wersji, pg_stat_statements, http://localhost:8280, refresh_pghero w nightly_sync.py, pg_stat_statements_reset jednej bazy, tunel SSH, rola pg_monitor, pganalyze odrzucony -->

Decyzja Artura z 28.11.2026, po przeglądzie narzędzi. Wolne `GET /api/candidates`
z 26.11.2026 szukano ręcznie w `pg_stat_statements` produkcji
(`kandydaci-wyszukiwanie/szukanie-osoby-w-trakcie-pisania.md`). PgHero (MIT) daje
to samo na jednym ekranie: wolne zapytania, brakujące, zduplikowane i nieużywane
indeksy, rozmiary tabel, blokady i połączenia. Komercyjny pganalyze (od ok. 150 $
miesięcznie) odrzucony jako za drogi na jedną bazę.

## Gdzie i jak

- Usługa `pghero` w `docker-compose.staging.yml`, ten sam projekt `nexus-staging`
  (bez drugiego stosu). Adres `http://localhost:8280`, port tylko na `127.0.0.1`.
  Port leży poza 8101–8199, bo tamte bierze `scripts/staging/free_ports.py`
  dla backendów gałęzi.
- Obraz `ankane/pghero` przypięty do dokładnej wersji. Podnosisz ją PR-em z wersją
  starszą niż dwa tygodnie, bo to narzędzie z dostępem do całej kopii produkcji.
- PgHero czyta bazę z `STAGING_DATABASE_NAME`, tą samą co backend. Pokazuje tylko
  zapytania tej bazy: `pg_stat_statements` jest wspólne dla serwera, a PgHero
  filtruje po `current_database()`. Backendy gałęzi na `nexus_branch_*` tu nie
  wchodzą.
- `pg_stat_statements` ładuje `shared_preload_libraries` w compose, tak samo jak
  na produkcji. Rozszerzenie przychodzi w zrzucie produkcji.
- Start ręczny, np. po świeżym `restore_from_backup.sh` (z katalogu, z którego stoi
  staging, zwykle `~/.nexus-staging/code`):

  ```bash
  docker compose -p nexus-staging -f docker-compose.staging.yml --env-file .env.staging.local up -d --no-deps pghero
  ```

## Nocna kopia

`refresh_pghero` w `scripts/staging/nightly_sync.py` biegnie po przełączeniu na
nową kopię i po wyrównaniu Qdranta:

1. `CREATE EXTENSION IF NOT EXISTS pg_stat_statements` i
   `pg_stat_statements_reset(0, <oid nowej bazy>, 0)` w nowej bazie. Zeruje
   wyłącznie jej wiersze, więc znika szum odtworzenia, migracji i wyrównania,
   a statystyki baz gałęzi zostają.
2. `up -d --no-deps pghero`: nowa wartość `STAGING_DATABASE_NAME` zmienia
   konfigurację, więc compose odtwarza kontener na nowej bazie.

Krok musi być przed porządkami, bo PgHero podłączony do starej kopii trzyma
połączenie w `pg_stat_activity` i porządki jej nie usuną. Błąd kroku nie cofa
kopii, tylko trafia do „Czeka na Artura” w `staging-kopia.md`. Cofnięte
przełączenie zostawia PgHero na poprzedniej kopii, tej samej co backend.

Nocna kopia biegnie z kopii skryptu w `~/.claude/nexus-rutyny/bin/kopia/`
(`rutyny-nocne.md`), więc krok zadziała dopiero po przegraniu tam
`nightly_sync.py` z maina. Do tego czasu raport kopii zgłasza różnicę, a PgHero
zostaje na bazie z chwili ostatniego ręcznego startu.

Reset w ciągu dnia, np. przed pomiarem jednej ścieżki, też tylko dla bieżącej bazy
(nazwa z `.env.staging.local`):

```bash
docker exec nexus-staging-postgres-1 psql -U nexus -d <STAGING_DATABASE_NAME> -c "SELECT pg_stat_statements_reset(0, oid, 0) FROM pg_database WHERE datname = current_database()"
```

Przycisk „Reset” na stronie „Queries” robi to samo: `reset_query_stats` w PgHero
4.0.1 zeruje tylko bazę, do której PgHero jest podłączony.

## Czego staging nie pokaże

- Czasy ze stagingu to nie czasy produkcji: inny sprzęt, pusty bufor po kopii,
  brak ruchu ludzi. 28.11.2026 zapytanie strony listy kandydatów z ILIKE miało na
  stagingu średnio 4–6 s, a ten sam `GET /api/candidates` z curla trwał 0,1 s. Do
  decyzji bierz kształt zapytania i liczbę wywołań, a czas potwierdzaj na produkcji.
- Zrzuty PgHero są ze stagingu, więc obowiązuje reguła z
  `ui/makiety-na-stagingu.md`: prywatny artefakt, nie PR. Tekst zapytań w
  `pg_stat_statements` ma stałe zamienione na `$1`, ale „Live Queries” pokazuje
  `pg_stat_activity.query` z literałami ze skryptów uruchamianych ręcznie.
  `PGHERO_FILTER_DATA` by je usunął, tyle że w 4.0.1 wywraca stronę „Queries”
  (500, `incompatible character encodings` w `pg_query`, sprawdzone 28.11.2026),
  więc jest wyłączony. Po podniesieniu wersji sprawdź to jeszcze raz.

## Produkcja tylko do odczytu (decyzja Artura, nieuruchomione)

Na produkcji PgHero nie stoi i ten plik niczego tam nie uruchamia. Gdy staging nie
wystarczy (czas zależny od ruchu, blokady w godzinach pracy), produkcję da się
obejrzeć z laptopa bez zmiany compose produkcji:

1. **Rola tylko do odczytu, jednorazowo** (zmiana w bazie produkcji, więc
   decyzja Artura). `pg_monitor` daje `pg_read_all_stats` i `pg_read_all_settings`:
   zapytania, statystyki tabel i indeksów, połączenia i blokady. Nie daje odczytu
   danych tabel, resetu statystyk ani zabicia cudzego połączenia. Hasło zna tylko
   Artur i wpisuje je sam, w terminalu, nie w czacie:

   ```sql
   CREATE ROLE pghero_ro LOGIN PASSWORD '<hasło>' IN ROLE pg_monitor;
   ALTER ROLE pghero_ro SET default_transaction_read_only = on;
   GRANT CONNECT ON DATABASE nexus TO pghero_ro;
   ```

   Bez `pg_read_all_data` PgHero nie zaproponuje brakujących indeksów ani nie
   zrobi EXPLAIN, bo `pg_stats` ukrywa kolumny tabel bez prawa SELECT. Dodanie tej
   roli to dostęp do danych kandydatów, czyli osobna decyzja.
2. **Tunel SSH** do kontenera Postgresa (jego nazwa i adres zmieniają się po
   każdym wdrożeniu; host i klucz w `~/.claude/nexus-rutyny/prod-readonly.conf`):

   ```bash
   IP=$(ssh -i <klucz> root@<host> "docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' \$(docker ps --format '{{.Names}}' | grep '^postgres-ocgkw' | head -1)" | awk '{print $1}')
   ssh -i <klucz> -N -L 127.0.0.1:15432:$IP:5432 root@<host>
   ```

3. **PgHero na laptopie, jednorazowo**, poza compose stagingu i na innym porcie:

   ```bash
   docker run --rm -p 127.0.0.1:8281:8080 -e DATABASE_URL='postgres://pghero_ro:<hasło>@host.docker.internal:15432/nexus' ankane/pghero:<wersja z compose stagingu>
   ```

Bez roli `pghero_ro` jedyną drogą jest użytkownik `nexus` z
`default_transaction_read_only`, ale to superużytkownik: PgHero dałby wtedy z
laptopa reset statystyk i zabijanie połączeń produkcji. Tego nie robimy.
Rutyny czytają produkcję dalej przez `scripts/prod_readonly.py`
(`rutyny-nocne.md`), nie przez PgHero.
