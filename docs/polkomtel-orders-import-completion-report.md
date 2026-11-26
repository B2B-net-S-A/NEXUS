[← docs](./)

# Import zamówień Polkomtel + dziesiętna stawka klienta — raport

Data: 2026-06-26 · PR [#594](https://github.com/artur-t-96/Nexus/pull/594) (merged, SHA `329a7bc`)

## Cel

Wstawienie do Nexus 6 zamówień od klienta **Polkomtel** (id 15) z pliku
`Zamówienia_Polkomtel.xlsx`. Dane wymusiły dwie zmiany modelu:

1. **Stawka klienta dziesiętna** (dwie z sześciu stawek miały dwa miejsca po
   przecinku) — kolumny stawek były `Integer`.
2. **Brak daty rozpoczęcia** — kolumna „Zamówienie od" pusta dla wszystkich;
   `contracts.start_date` było `NOT NULL`.

Decyzje (uzgodnione z Arturem): stawki **jak w Excelu** (2 miejsca po przecinku),
daty start **puste**, stawki traktowane jako **godzinowe** (`rate_unit=hourly`).

## Zmiany kodu

- **Migracja `0147_client_order_rate_decimal`** (na bazie `0146`):
  - `client_orders.rate_client` `Integer → Numeric(10,2)`
  - `contracts.start_date` `NOT NULL → nullable`
  - odwracalna (`downgrade` zaokrągla z powrotem)
- Dziesiętną precyzję trzyma **Order** (PO klienta). `Contract.rate_client`
  pozostaje `int` (zaokrąglenie `ROUND_HALF_UP`) → raporty/analityka kontraktów
  nietknięte.
- Schematy zamówień (`new_contractor_order`, `client_order`): `rate_client`,
  marże → `Decimal`; `order_start_date`/`contract_start_date` → opcjonalne.
- Read-schematy kontraktów i profilu klienta: `start_date` `required → Optional`.
- Brak zmian frontendu — `fmtMoney` w `OrdersAndContractsTab` już przyjmuje
  `number | string`.

Pliki: `backend/alembic/versions/0147_*.py`, `app/models/{client_order,contract}.py`,
`app/api/client_orders.py`, `app/schemas/{new_contractor_order,client_order,contract,client_profile}.py`.

## Wstawione dane (klient 15, status active, rate_unit hourly, 160 h/mc)

Osoby i stawki nie są wypisane w raporcie, bo repo jest publiczne — są w
NEXUSIE na kontraktach i zamówieniach z tej tabeli.

| Konsultant | candidate_id | Contract | Order | do |
|---|---|---|---|---|
| A | 12576 | #471 | #7 | — |
| B | 12628 | #472 | #8 | 2026-08-31 |
| C | 5367 | #473 | #9 | 2026-08-31 |
| D | 64386 | #474 | #10 | — |
| E | 18542 | #475 | #11 | — |
| F | 64163 | #476 | #12 | — |

Uwaga: konsultant F ma stawkę kosztową wyższą niż przychodową → ujemna marża;
tak wynika z Excela.

## Weryfikacja (DoD)

- CI PR #594: Backend (ruff + pytest, w tym `alembic upgrade`) ✅, Frontend ✅.
- Deploy: `/api/health` → `version=329a7bc…`, `status=healthy` ✅ (migracja przeszła).
- API `GET /api/clients/15/contracts-with-orders`: dokładne stawki dziesiętne
  (bez zaokrągleń), daty start `null` ✅.
- UI (Chrome, zalogowany Admin): zakładka **Zamówienia** Polkomtel — 6 zamówień,
  stawka dziesiętna i marża renderują się z groszami, daty „od" puste ✅.

## Znane ograniczenia

- Profil klienta („Obecni konsultanci") pokazuje marżę z **zaokrąglonej**
  stawki kontraktu, bo `Contract.rate_client` jest `int`. Dokładna marża
  (z groszami) widoczna na poziomie **Zamówienia**.
  To świadoma decyzja izolująca zmianę do podsystemu zamówień.
