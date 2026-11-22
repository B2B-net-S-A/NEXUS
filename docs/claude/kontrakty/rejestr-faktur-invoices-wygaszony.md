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

## Usunięcie tabeli (0748)

Kod przestał czytać tabelę w #3661, a migracja 0748 w kolejnym wdrożeniu
(`podstawy/migracje-zgodne-wstecz.md`, zgoda Artura z 20.11.2026) usunęła
`invoices` i enumy `invoicedirection`, `invoicestatus`, bez CASCADE. Razem
z nią zniknęły:

- wpis `("invoices", "contract_id")` w `contract_merge._KNOWN_CONTRACT_FKS`.
  Audyt scalania kontraktów porównuje tę listę z żywym katalogiem Postgresa
  i blokuje scalenie zarówno przy nieznanym, jak i przy brakującym kluczu
  obcym, więc wpis wychodzi w tym samym PR-ze co `DROP`;
- lustro migracji 0394 w `entrypoint.sh` (`ALTER TABLE invoices …
  NUMERIC(14, 2)`) i jego test.

Lustro `DROP` jest w `entrypoint.sh`; pilnuje go
`tests/test_drop_invoices_register_mirror.py`. Napis `invoices:read` w koncie
serwisowym, które go miało, nie otwiera już niczego: ekran „Klucze API”
pokazuje go w grupie „Inne”, a zapis konta go usuwa.

## Na przyszłość

Nowa funkcja z fakturami czyta KSeF (`client_sales_invoices`,
`client_contractor_invoices`) i nie zakłada drugiego rejestru. Strażnik
`tests/test_invoice_register_retired_guard.py` pilnuje, żeby trasy, scope'y,
zdarzenia, model i kafle nie wróciły starym merge'em.
