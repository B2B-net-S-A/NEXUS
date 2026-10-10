# Finanse → „Zamówienia PDF" (21.09.2026)

`/finance?view=order-pdfs`: miesiąc startu → klient → PDF-y do pobrania.
Serwis `services/finance_order_pdfs.py`, trasy `/api/finance/order-pdfs*`
(bramka sekcji Finance, jak cały moduł — roli „Finanse admin" nie ma).

- **Liczone przy odczycie, bez tabeli i migracji** — historia jest objęta od
  razu, nowe zamówienie z PDF-em pojawia się samo. Nie dokładaj tabeli-wykazu.
- **Trzy źródła:** `client_orders.file_path` (okres `COALESCE(linia, grupa)`),
  `client_order_groups.file_path`, aneks `extension` z `document_id` (start =
  `old_values.end_date` + 1). Anulowane zamówienia i kopie PDF-u grupy
  w dokumentach kontraktu (`source_order_group_id`) są pomijane.
- **Nazwisko z przypisania, nigdy z PDF-a;** PDF grupy dostaje nazwisko tylko
  przy DOKŁADNIE jednej osobie. Nazwa pliku: `build_download_name`
  (`<oryginał>_<Nazwisko>_DD.MM.RRRR-DD.MM.RRRR`, brak końca = `-bezterminowo`);
  lista i pobranie liczą ją tą samą funkcją (`find_entry`).
- Klucze URL `pdfMonth`/`pdfClient` (nie `month` — ten należy do „Zmian").
