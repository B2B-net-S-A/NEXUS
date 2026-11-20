# Jeden plik raz w Dokumentach kontraktu (20.11.2026)

Produkcja 19.11.2026 (1574 dokumenty): ten sam SHA-256 w jednym kontrakcie
w 12 kontraktach, 17 zbędnych kopii. Wszystkie to ręczny upload z X–XI (plik
ściągnięty już z SharePointa albo wgrany drugi raz), 13 z nich NEXUS wysłał do
SharePointa jako osobne pliki. W czterech parach drugą kopię dołożył skan
podpisanego aneksu z Generatora. Do tego kopia PDF-u zamówienia zbiorczego obok
ręcznego pliku i 14 par „PDF linii + kopia PDF-u grupy” w folderze
„Zamówienia”. Kopie usunięto 19.11 przez API za zgodą Artura; Artur wybrał
wariant „Blokada uploadu + jedna kopia”.

- **„Kontrakt ma już ten plik” = ten sam SHA-256 na tym kontrakcie**
  (`contract_folder_docs.store.same_content_documents`), jak przy imporcie
  z SharePointa. Typ i folder istniejącego pliku nie mają znaczenia. Wiersz,
  którego pliku nie ma na dysku, się nie liczy, bo zgubiony plik musi dać się
  wgrać z powrotem.
- **Skrót w bazie tylko zawęża szukanie, rozstrzyga plik na dysku.** Kopia
  PDF-u grupy do 20.11 nie dostawała skrótu, import z SharePointa go dopisywał
  (`_backfill_missing_hashes`), a podmiana PDF-u grupy zostawiała stary
  (przegląd kodu 20.11). Kopie grup i wiersze bez skrótu porównujemy z plikiem
  zawsze, także w `order_document_copies`. Skrótów przy tym NIE zapisujemy:
  skan aneksu i zapis linii zamówienia trzymają już wiersz kontraktu `FOR
  UPDATE`, a aktualizacja cudzych wierszy dokumentów mogłaby się zakleszczyć
  z `attach_file`. Na kopii danych z 19.11 nieaktualnego skrótu nie miała żadna
  z 28 kopii grup ze skrótem, ale `attach_file` nadal ufa kolumnie.
- **Ręczny upload** (`upload_contract_document`): 409 `{code:
  "document_duplicate", message, document: {id, filename, created_at}}`,
  zapisany plik znika z dysku. Nazwę istniejącego pliku dostaje tylko ktoś,
  kto widzi listę Dokumentów (`_can_read_contract_finance`); dodanie pliku jest
  otwarte szerzej (`dodanie-pliku-bez-podgladu-kwot.md`), więc wtedy zostaje
  sama data. Przed sprawdzeniem trasa bierze blokadę doradczą dokumentów
  kontraktu (`store.lock_contract_documents`, ta sama co `attach_file`), bo
  podwójne kliknięcie inaczej przechodziło dwa razy. Tę blokadę bierze się
  przed blokadą wiersza kontraktu, nigdy po niej.
- **Front:** okno „Dodaj plik” pokazuje zdanie z serwera (`apiErrorMessage`).
  Okna „Zakończ współpracę” i „Rozwiązanie umowy” traktują 409
  `document_duplicate` jako „załącznik już jest” (`isDocumentDuplicate`
  w `lib/contract-document-folders.ts`). Ich komunikat „załącznik nie trafił do
  dokumentów… Dodaj go w zakładce Dokumenty” byłby wtedy nieprawdą.
- **Kopia PDF-u zamówienia zbiorczego** (`_sync_group_pdf_documents`) liczy
  `content_sha256` i nie powstaje na kontrakcie, który ma już ten plik.
  Istniejąca kopia grupy podmienia się jak dotąd, także gdy nowa treść jest
  już gdzie indziej na kontrakcie. Po „Usuń PDF” w zamówieniu zostaje plik
  ręczny.
- **Skan podpisanego aneksu** (`signed_scan.attach`): plik, który kontrakt już
  ma, nie dostaje drugiej kopii, tylko aneksy wskazują istniejący dokument.
  „Podmień skan” nadpisuje w miejscu WYŁĄCZNIE skan zapisany przez Generator
  dla tego dokumentu (klucz pliku `b2b-document-<id>-skan-…`, `_owned_scan`).
  Istniejący dokument zostaje nietknięty, bo był w Dokumentach przed skanem
  i należy do tego, kto go dodał. Nowy skan zapisuje się wtedy obok. Skan nie
  wskazuje kopii PDF-u grupy ani pliku Generatora (`b2b-…`: skan innego aneksu,
  np. jeden PDF z dwoma aneksami, podpisana umowa, DOCX), bo ich własne
  „Podmień” zmieniłoby skan pod tym aneksem. Wtedy powstaje osobna kopia, jak
  przed 20.11. Świadomy wyjątek: „Podmień skan” na własnym skanie plikiem, który
  leży już gdzie indziej w Dokumentach, nadpisuje w miejscu jak dotąd.
  Inaczej trzeba by kasować wiersz skanu razem z jego stanem w SharePoincie
  i odczytem stawek.
- **Grupa zamówień („Zamówienia klienta”, dawny folder „Zamówienia”):** gdy PDF
  linii zamówienia zbiorczego i kopia PDF-u jej grupy
  (`source_order_group_id == order_group_id`) to ten sam plik, zakładka pokazuje
  jeden wiersz, czyli PDF z zakładki Zamówienia (z numerem i statusem
  zamówienia, liczy się też do karty „Obowiązuje teraz”). Kopia nie niesie nic
  więcej, a PDF zamówienia nie ma „Usuń”, więc wiersz nie wraca po usunięciu.
  O tożsamości decyduje serwer: `services/order_document_copies.py`, pole
  `same_file_document_id` w `order-documents/by-contract`, SHA-256 z pliku
  liczony tylko przy równym rozmiarze. Front pomija kopię w `buildDocumentsView`
  (`components/contracts/documents/document-groups.ts`), więc para nie dostaje
  też plakietki „możliwy duplikat”. Sam rozmiar nie wystarcza, bo dwa różne PO
  bywają tej samej wielkości.
- **Czego tu nie ma:** sprzątania istniejących par (#527, #621 zostały dla DL),
  kasowania czegokolwiek w SharePoincie i tej samej blokady dla podpisanej
  umowy B2B z Generatora (`b2b_contract_generator/signed_file.py`).
- Testy: `tests/test_contract_document_duplicates.py`,
  `components/contracts/documents/__tests__/document-groups.test.ts`,
  `src/lib/__tests__/contract-document-folders.test.ts`,
  `ContractDocumentsTabFolders.test.tsx`, `ContractTerminationDialog.test.tsx`,
  `ContractAgreementRecordDialog.test.tsx`.
