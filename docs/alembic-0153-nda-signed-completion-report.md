# Naprawa migracji 0153 (nda_signed) + procedura zejścia z alembicowego driftu

Data: 2026-07-29

## Problem

Na prodzie każdy start backendu logował błąd:
`Running upgrade 0152 -> 0153_client_min_sprawiedliwosci` →
`asyncpg.exceptions.NotNullViolationError: null value in column "nda_signed" of relation "clients"`.

Przyczyna: INSERT wyróżnionego klienta „Ministerstwo Sprawiedliwości" w
`backend/alembic/versions/0153_client_min_sprawiedliwosci.py` nie ustawiał `nda_signed`,
a na prodzie ta kolumna jest **NOT NULL bez defaultu** (drift względem `0001_initial`,
które tworzy ją jako nullable z `DEFAULT FALSE`). Entrypoint toleruje błąd (celowo, bez
`exit 1`), więc apka startowała, ale `alembic_version` utknął na `0152` — schemat
utrzymywał wyłącznie safety-net w `entrypoint.sh`.

## Co zostało zmienione

1. **`backend/alembic/versions/0153_client_min_sprawiedliwosci.py`** — INSERT ustawia
   teraz jawnie `nda_signed = false` (jedyna kolumna NOT NULL z DETAIL błędu; reszta
   NOT NULL — `name`, `status`, `hidden`, `created_at`, `updated_at` — była już ustawiana).
   Migracja pozostaje w pełni idempotentna (guardy `NOT EXISTS` bez zmian).
2. **`backend/entrypoint.sh`** — dodane lustro danych 0153 do `_DATA_STATEMENTS`
   (promocja istniejącego klienta LUB insert ręcznego sentinela), zgodnie z konwencją
   repo (docstringi 0180/0181: „migracje ≥0153 nie odpalą się na prodzie; lustrem jest
   entrypoint"). Oba statementy strażowane — no-op gdy wyróżniona pozycja już istnieje.
   Zachowanie entrypointu (tolerancja błędów, brak hard-exit) **niezmienione**.

## Analiza: czy łańcuch 0154..head przejdzie na prodzie? — NIE (zweryfikowane empirycznie)

Symulacja prod lokalnie (Postgres 16, obraz `nexus-test:fresh`): pełny schemat na head
→ `alembic stamp 0152` → odtworzony drift (`nda_signed` NOT NULL bez defaultu, brak
wiersza Ministerstwa). Wyniki:

- **Stary 0153**: reprodukcja 1:1 błędu produkcyjnego (NotNullViolation na `nda_signed`).
- **Naprawiony 0153**: przechodzi; łańcuch idzie dalej 0154→…→0180.
- **Łańcuch pada na 0181** (`champion_share_token_hash`): nieosłonięty
  `op.add_column("token_sha256")` na kolumnie, którą safety-net już dodał →
  `DuplicateColumnError`. Analogicznie nieodporne są 0182 i 0183. To celowa konwencja
  repo — te migracje pisano dla świeżych baz, prod obsługuje lustro w entrypoint.
- **Niuans transakcyjny**: migracja 0159 (`CREATE INDEX CONCURRENTLY`) wymusza commit,
  więc po pierwszym boocie z fixem **0153–0159 komitują się** (bookmark 0152→0159),
  w tym migracje danych: wpis Ministerstwa (0153), backfill statusów kontraktów (0155)
  i seed `ai_features('scoring')` (0156). Kolejne booty ponawiają 0160→0181, padają na
  0181 i rollbackują — stan jest stabilny (zweryfikowane powtórnym runem).

Migracje danych w zakresie 0160..head, które stamp pominie, są już zlustrowane w
`entrypoint.sh`: 0165 (strip markera „zatrudniony"), 0187 (dedup notatek fireflies),
0195 (document_kind backfill), 0197 (seed rejection_reasons z markerem), 0200
(singleton recruitment_priority_state). Schemat: prod utrzymywany do head przez
safety-net + pomiar driftu (`/api/admin/schema-drift`, migracja 0180).

## Procedura na prod (dwa kroki, kolejność ISTOTNA)

**Krok 1 — deploy tego fixa** (merge PR → auto-deploy Coolify). Pierwszy boot:
alembic przechodzi 0153→0159 i komituje (dane 0153/0155/0156 lądują). Boot nadal
zaloguje tolerowany błąd na 0181 — to oczekiwane.

Weryfikacja po deployu (bookmark powinien być `0159_candidate_search_doc_unaccented`):

```bash
curl -fsSL -H "X-Snapshot-Token: $SNAPSHOT_TOKEN" https://api.nexus.dynaminds.pl/api/admin/snapshot | jq .alembic
```

**Krok 2 — jednorazowy `alembic stamp head`** (po potwierdzeniu bookmarka 0159):

```bash
ssh root@91.99.199.112
```

```bash
docker exec $(docker ps --format '{{.Names}}' | grep -m1 backend) alembic -c alembic/alembic.ini stamp head
```

Alternatywa bez wchodzenia w kontener backendu (przez psql; wartość = aktualny head,
sprawdź `alembic heads` w repo — w chwili pisania `0203_b2b_generated_contract_status`,
po merge #1000):

```sql
UPDATE alembic_version SET version_num = '0203_b2b_generated_contract_status';
```

**Dlaczego stamp, nie upgrade:** 0181/0182/0183 nie są idempotentne wobec kolumn
dodanych przez safety-net (dowód wyżej), a env.py nie używa `transaction_per_migration`
— każdy boot rollbackuje segment 0160→0181 w nieskończoność. Schemat na prodzie jest
już head-equivalent, a efekty danych są zlustrowane.

**Weryfikacja końcowa:** kolejny deploy — log bootu bez `Running upgrade` błędów;
`/api/admin/snapshot` → alembic = head; `/api/health/deep` zielone. Od tej pory nowe
migracje (0203+) będą aplikować się normalnie przez Alembica, safety-net zostaje jako
backstop.

**Jeśli ktoś wykona stamp PRZED deployem fixa:** dane 0155 (backfill statusów) i 0156
(seed ai_features) nie zaaplikują się przez migracje — 0153 jest od teraz zlustrowane
w entrypoint, tamte dwa nie. W takim wypadku odpal ręcznie SQL z tych dwóch migracji
(oba idempotentne).

## Weryfikacja lokalna (wykonana)

- Czysta baza: `alembic upgrade head` → zielone, head `0202_cv_content_mode` (jedna
  głowa), wiersz Ministerstwa z `nda_signed=false`.
- Baza symulująca prod (j.w.): naprawione 0153 przechodzi; pad na 0181 zgodnie z
  analizą; `stamp head` → `upgrade head` czysty no-op.
- Statementy lustra w entrypoint: przetestowane na schemacie z NOT NULL — no-op gdy
  wiersz istnieje, poprawny INSERT gdy brak; heredoc kompiluje się, `bash -n` czysty.
- `ruff check` na zmienionej migracji: bez uwag.

## Znane ograniczenia

- Krok 2 (stamp) wymaga ręcznego SSH — nie ma administracyjnego endpointu mutującego
  `alembic_version` (celowo; `/api/admin/schema-drift` jest read-only).
- Downgrade 0153 bez zmian (nie kasuje danych z historii, od-wyróżnia tylko promocję).
