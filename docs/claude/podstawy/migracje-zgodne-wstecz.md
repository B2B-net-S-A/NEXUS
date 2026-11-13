# Migracje zgodne wstecz — dodanie teraz, usunięcie w kolejnym wdrożeniu

Etap B2 planu przerwy (`przerwa-przy-wdrozeniu.md`): backend i worker są osobnymi
aplikacjami Coolify z rolling update. Nowy kontener robi `alembic upgrade` i siatkę DDL
z `entrypoint.sh`, **gdy stary kontener dalej obsługuje ruch**, a worker ze starym kodem
chodzi na nowym schemacie jeszcze kilka minut, aż wdroży się jego aplikacja. Do B2
wdrożenie zatrzymywało wszystko przed migracją, więc ta reguła nie była potrzebna.

## Reguła

Każda migracja musi działać ze **starym kodem** na **nowym schemacie**.

- **Dodanie** (tabela, kolumna z wartością domyślną albo NULL, indeks `CONCURRENTLY`,
  nowa wartość enuma, której stary kod nie dostanie) — w jednym PR-ze razem z kodem.
- **Usunięcie, zmiana nazwy, zmiana typu, `NOT NULL` na istniejącej kolumnie** — dwa PR-y
  w dwóch wieczornych wdrożeniach:
  1. kod przestaje czytać i pisać kolumnę (ORM bez niej, zapytania bez niej); wdrożony;
  2. dopiero w kolejnym wdrożeniu migracja z `DROP` / `RENAME` / `ALTER … TYPE`.
- **Zmiana nazwy** to trzy kroki: nowa kolumna + zapis do obu, kod czyta nową,
  usunięcie starej.
- **`NOT NULL`** na istniejącej kolumnie: najpierw kod zawsze ją wypełnia i backfill,
  potem w kolejnym wdrożeniu `SET NOT NULL`.

Stary kod na usuniętej kolumnie to `UndefinedColumnError` na każdym żądaniu, które ją
czyta, przez cały czas nakładania — także z workera, który wdraża się po backendzie.

## Strażnik

`backend/tests/test_migrations_backward_compatible.py` czyta funkcję `upgrade()` migracji
od `0692` i przy usunięciu, zmianie nazwy, zmianie typu albo `SET NOT NULL` wymaga
w pliku linii:

```python
# zgodne-wstecz: kolumny nie czyta kod od #3390 (wdrożone 14.11.2026)
```

Powód ma wskazać PR z kroku 1, który jest już na produkcji. Strażnik nie sprawdza,
czy to prawda; ma zatrzymać migrację, przy której nikt nie pomyślał o starym kodzie.
`downgrade()` nie jest sprawdzane.

## Lustro w `entrypoint.sh`

Ta sama reguła dotyczy siatki DDL w `entrypoint.sh`: biegnie przy żywym ruchu, a krok
pominięty przez `lock_timeout` widać w `/api/health` (`checks.migrations: degraded`)
i w Sentry (`app/services/startup_locks.record_skipped_ddl`). Następny start go ponowi.
