# Import zamówień Alior + ułamkowe stawki (NUMERIC(12,3)) — raport

**Data:** 2026-06-26
**Zakres:** Wstawienie 11 zamówień/kontraktów klienta ALIOR BANK (id 39) z Excela
`Zamówienia Alior.xlsx`, z wierną (dokładną co do ułamka) stawką godzinową.

## Problem

Excel Aliora zawiera stawki klienta z **trzema** miejscami po przecinku
(przykład: 100,125 zł/h). Kolumny stawek były `NUMERIC(10,2)`
(po migracjach 0147/0148, import Erste) — skala 2 zaokrąglałaby te wartości.
Dodatkowo handler `contract-with-order` **celowo zaokrąglał** `Contract.rate_client`
do liczby całkowitej (zaległy komentarz „Contract.rate_client jest Integer"),
a walidacja `decimal_places=2` zwracała 422 dla stawek z 3 miejscami.

## Zmiany (kod)

PR #597 — `NUMERIC(10,2) → NUMERIC(12,3)`:
- Migracja `0149_contract_rates_scale3` (na bazie 0148): `contracts.rate_candidate
  / rate_client / margin`, `contract_candidate_rates.rate`,
  `candidate_rate_history.rate`, `client_orders.rate_client` → `NUMERIC(12,3)`
  (ALTER tylko dodaje precyzję; downgrade zaokrągla do 2 miejsc).
- Modele: `Numeric(12,3)` na ww. kolumnach.
- Frontend: inputy stawek `step="0.001"`; formatery (`formatCurrency`, `formatPLN`)
  `maximumFractionDigits: 3`.

PR #610 — fix zaokrąglania w „Nowy kontraktor":
- `client_orders.create_contract_with_order`: `Contract.rate_client =
  payload.rate_client` (bez `int()/quantize`); usunięty nieużywany
  `ROUND_HALF_UP`; multipart `Form` rate_client → `Decimal`.
- `new_contractor_order`: `rate_client/rate_candidate` `max_digits=12,
  decimal_places=3`.
- `client_order`: `ClientOrderCreate/Update.rate_client` `decimal_places=3`.

## Dane wstawione

11 kontraktów + 11 zamówień (atomic `POST /api/clients/39/contract-with-order`,
`rate_unit=hourly`, `billing_hours_per_month=160`, status `active`). Kandydaci
dopasowani do rekordów `[zatrudniony]` (kanoniczny rekord zatrudnionego):
kontrakty 487–497, po jednym na konsultanta. Osoby i stawki nie są wypisane w
raporcie, bo repo jest publiczne — są w NEXUSIE na tych kontraktach.

(Pierwsza, częściowa próba — kontrakty 480–486 z zaokrągloną stawką — została
usunięta przed wdrożeniem fixu i wstawiona ponownie jako 487–497.)

## Weryfikacja

- Migracja zdeployowana, `/api/health` = `d3ef048`, status `healthy`.
- API: wszystkie 11 `rate_client` zgodne co do ułamka z Excelem (w tym 3-miejscowe).
- UI (Chrome): ALIOR BANK → Zamówienia → „Wszyscy (11)" renderuje dokładne
  stawki (z trzema miejscami po przecinku) i marże.

## Znane ograniczenia / poza zakresem

- Karta konsultanta sufiksuje stawkę `/mc` niezależnie od `rate_unit` — dla
  kontraktów godzinowych to mylące (powinno być `/h`). Pre-existing, dotyczy
  wszystkich godzinowych kontraktów (nie tylko Alior), nie ruszane w tym zadaniu.
