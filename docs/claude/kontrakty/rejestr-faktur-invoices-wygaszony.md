# Rejestr faktur `invoices` wygaszony (20.11.2026)

Ręczny rejestr faktur kontraktu (Phase 9 C1, #35, tabela `invoices`) zniknął
z kodu. Na produkcji tabela od powstania 17.04.2026 nie dostała ani jednego
wiersza (20.11.2026: 0 wierszy, 0 zdarzeń `invoice.*`, 0 zapisów przez API v1).
Faktury, które naprawdę istnieją, przychodzą z KSeF: sprzedaż do
`client_sales_invoices`, faktury konsultantów do `client_contractor_invoices`
(od #3646 to one są w zakładce faktur kontraktu).

## Co zniknęło

- `/api/invoices` (lista, `/dso`, `/export.csv`, odczyt, POST, PATCH, DELETE).
- `/api/integrations/v1/invoices`, scope'y `invoices:read|write` i zdarzenia
  `invoice.created|updated`. To świadomy wyjątek od reguły v1 „usunięcie = v2”
  (`podstawy/konta-serwisowe-klucze-api-x-api-key.md`): jedyny klucz z
  `invoices:read` był użyty tylko w dniu założenia, a rejestr był pusty.
- Model `Invoice` i relacja `Contract.invoices`.
- Kafle DSO i „faktury po terminie” pulpitu `/api/dashboard/v2/finance`
  (`outstanding_pln`, `overdue_pln`, `exceptions_board`). Pulpit nie ma ekranu
  od #1304 (31.08.2026), a kafle pokazywały „0 zł” z jakością `complete`.
- Surowe odczyty tabeli: kontrola `duplicate_invoice_number` i licznik
  `invoices_total` w `/api/admin/engagement-inventory`, licznik
  `blast_invoices_via_candidate_contracts` w `/api/admin/candidate-pii-orphans`.

## Co zostało i dlaczego

- **Tabela i enumy `invoicedirection`, `invoicestatus`.** `DROP` to osobna
  migracja w kolejnym wdrożeniu (`podstawy/migracje-zgodne-wstecz.md`), tylko
  za zgodą Artura, bo jest nieodwracalny.
- **Wpis `("invoices", "contract_id")` w `contract_merge._KNOWN_CONTRACT_FKS`.**
  Scalanie kontraktów porównuje listę z żywym katalogiem Postgresa i blokuje
  scalenie zarówno przy nieznanym, jak i przy brakującym kluczu obcym. Wpis
  wychodzi więc w tym samym PR-ze co `DROP`, ani wcześniej, ani później.
- **Lustro migracji 0394 w `entrypoint.sh`** (`ALTER TABLE invoices …
  NUMERIC(14, 2)`; komentarz w pliku nazywa je „0391”) i jego test
  w `tests/test_audit_r10_money.py`. Za `IF EXISTS` jest bezczynne na bazie bez
  tabeli; usuwa je PR z `DROP`.
- **Napis `invoices:read` w koncie serwisowym, które go miało.** Nie otwiera już
  niczego; ekran „Klucze API” pokazuje go w grupie „Inne”, a zapis konta go usuwa.

## Na przyszłość

Nowa funkcja z fakturami czyta KSeF (`client_sales_invoices`,
`client_contractor_invoices`) i nie zakłada drugiego rejestru. Strażnik
`tests/test_invoice_register_retired_guard.py` pilnuje, żeby trasy, scope'y,
zdarzenia, model i kafle nie wróciły starym merge'em.
