# Dodanie pliku do kontraktu bez podglądu kwot (22.10.2026)

Zgłoszenie z zespołu 22.10.2026: osoba z „Kontrakty i zamówienia”, ale bez
„Stawki i kwoty: podgląd” kończyła współpracę z wypowiedzeniem w załączniku.
Zakończenie się zapisywało, a plik nie — `POST /api/contracts/{id}/documents`
wymagał podglądu kwot, bo pliki umów niosą stawki i nie da się ich zaczernić.
Decyzja Artura 22.10.2026: dodanie pliku niczego nie odsłania, więc go nie
blokujemy; odczyt zostaje tam, gdzie był.

- **Dodanie pliku** (`upload_contract_document`) = „Kontrakty i zamówienia”
  w zakresie konta: konto z rolą Delivery Leada tylko u klienta z przypisania
  (`_assert_contract`), każdy inny posiadacz u wszystkich. Bez
  `_assert_contract_document_client_access`. Dotyczy też załącznika z okna
  „Zakończ współpracę” (`ContractTerminationDialog`).
- **Lista, pobranie, zmiana i usunięcie pliku** zostają za podglądem kwot
  (`_assert_contract_document_client_access`) — bez zmian.
- **Front:** `contractAccess().canUploadContractDocuments` (edycja kontraktu
  + `isClientInAssignedScope`). Gdy osoba nie widzi dokumentów, ale może
  dodawać, zakładka „Dokumenty” na karcie kontraktu pokazuje
  `UploadOnlyDocuments`: „Dodaj plik”, zdanie, dlaczego listy nie widać,
  i pliki dodane w tej wizycie (z odpowiedzi serwera, bez pobierania listy).
  Harness: `/preview/contract-documents-folders`, „Bez podglądu kwot”.
- Testy: `tests/test_permissions_contracts_rules.py`
  (`test_contract_editor_adds_a_file_without_the_amounts_view`),
  `src/components/__tests__/UploadOnlyDocuments.test.tsx`,
  `src/lib/__tests__/contract-access.test.ts`.
