# `statement_timeout` 120 s tylko dla procesu WWW
<!-- indeks: bezpiecznik instrukcji SQL, 57014, pomiar 04–05.11.2026, wyjątki, jak zmienić wartość -->

Decyzja Artura z 05.11.2026 po pomiarze na produkcji, po zamknięciu #2633 (60 s dla
całego silnika). Limit to bezpiecznik przed instrukcją bez końca. Nie przyspiesza
wolnych tras, bo ich czas nie siedzi w instrukcjach.

## Jak działa

- `entrypoint.sh` robi `export DB_STATEMENT_TIMEOUT_MS=120000` w linii tuż przed
  `exec uvicorn`, a `_connect_args` w `core/database.py` przekazuje wartość do
  `server_settings`.
- **Nie przenoś tej zmiennej do `environment:` w compose ani do env w Coolify.** Dostałby
  ją każdy `docker exec` ze skryptem, a skrypty i CLI mają biec bez limitu. Pilnuje tego
  `tests/test_statement_timeout.py`.
- Start kontenera (alembic, DDL z entrypointu, moduły `*_schema`) biegnie przed tą linią.
  DDL w samym procesie uvicorna nie ma; `pg_dump`, backup i `psql` mają własne połączenia.
- Limity punktowe (`SET LOCAL`, `set_config`, osobne silniki) działają jak dawniej.
  Instrukcja z `SET LOCAL statement_timeout = 0` może trwać dłużej, gdy naprawdę musi.
- Przekroczenie w żądaniu daje 500 z własnym komunikatem z `core/statement_timeout.py`
  i wpis w logu oraz Sentry z trasą. Świadomie nie 504: front ponawia odczyty na
  502/503/504, a to zapytanie właśnie trwało 2 minuty.
- Wyłączenie albo inna wartość: zmiana tej jednej linii i wdrożenie.

## Czego limit nie załatwi

- Liczy też czekanie na blokadę, więc przerywa czekającego, nie tego, kto blokadę trzyma.
- Nie pomoże przy zawieszonym dysku. 04.11.2026 wolumen z bazą stał 10 minut, a 37 z 60
  stojących instrukcji to `COMMIT` w kolejce do zapisu WAL. Z działania Postgresa wynika,
  że takiego `COMMIT` nie da się anulować; tego nie testowaliśmy na produkcji.
- `idle in transaction` nie jest instrukcją, więc limit go nie dotyczy (do 243 s poza awarią).

## Pomiar, na którym oparto wartość

| Źródło | Wynik |
|---|---|
| `pg_stat_statements` od 20.07 | poza awarią dysku najwięcej 78,7 s; rzadkie wpisy wypadają, więc to dolna granica |
| Próbki `pg_stat_activity` co 5 s, ok. 18 h, 04–05.11 | `nexus-backend` poza awarią najwięcej 58 s, nic ponad 60 s |
| Logi tras, 90 min w szczycie 04.11 | najdłużej 101 s, nic ponad 120 s |

Limit 60 s przerwałby `FOR UPDATE` na `candidates` i licznik słów kluczowych, czyli głównie
ludzi czekających na blokadę w `POST /move`. Po pierwszych tygodniach sprawdź w Sentry
`Statement timeout on`: wpis poza awarią to sygnał do oceny tego zapytania, a nie do
podnoszenia limitu.
