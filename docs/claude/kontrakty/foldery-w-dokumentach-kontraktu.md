# Foldery w zakładce Dokumenty kontraktu (0494, 21.10.2026)

Ticket Ani: dokumenty starej i nowej umowy mieszały się na jednej liście.
Makiety i decyzje Artura 21.10.2026 (https://claude.ai/artifact/DbL73J4pHAd7dWr2Mv4WV5):
folder „Zamówienia” wyliczany z typu, podpowiedź „Poprzednia umowa” jako
podpowiedź, nie automat. Kod: `services/contract_document_folders.py`,
`api/contract_document_folders.py`, front `components/ContractDocumentsTab.tsx`
+ `components/contracts/documents/`, logika `lib/contract-document-folders.ts`,
harness `/preview/contract-documents-folders`.

- **Plik bez folderu = sekcja „Aktualna umowa”, zawsze na górze.** Foldery
  pod nią, jeden poziom (bez podfolderów). `contract_documents.folder_id`,
  FK `ON DELETE SET NULL` — usunięcie folderu oddaje pliki, nie kasuje ich.
  Nazwa unikalna w kontrakcie bez względu na wielkość liter (409).
- **Folder „Zamówienia” wynika z typu dokumentu (`order`), nie z `folder_id`.**
  Zbiera dokumenty typu Zamówienie (SharePoint, PDF zamówienia zbiorczego,
  ręczne) i PDF-y z zakładki Zamówienia (dawna sekcja „Dokumenty zamówień”,
  ta sama trasa `order-documents/by-contract`, 403 = cicho bez tych plików).
  Dzięki temu żadne z ~10 miejsc zapisujących dokumenty nie musi pamiętać
  o folderze, a istniejące zamówienia nie wymagały migracji danych.
  Zamówienia nie przenosi się ręcznie (422), nie da się go usunąć jako
  folderu; wiersz `kind = 'orders'` trzyma tylko własną nazwę po zmianie.
  Pusty folder „Zamówienia” się nie pokazuje.
- **Podpowiedź „Poprzednia umowa – nr …”** (`build_suggestions`): numer
  z nazwy pliku tylko dla typów umowa/aneks/wypowiedzenie/porozumienie
  („ZUS 03-2026” to miesiąc), bez dat z kropkami i „01-10-2026”. Bieżący
  numer: `b2b_contract_details`, potem ostatnia `b2b_generated_contracts`,
  a bez nich najnowszy (rok, numer) z plików. Wypowiedzenie bez numeru
  dołączamy tylko przy żywym kontrakcie i jednej starszej umowie. Niczego
  nie przenosi sama; „Nie teraz” pamięta przeglądarka.
- **Plik w folderze to archiwum:** nie zapala alarmu wygasania
  (`contract_alerts._compliance_documents_expiring`) ani plakietki
  „Compliance” na stronie kontraktu (`summariseComplianceRisk`).
- **Bramki jak dokumenty kontraktu:** odczyt `AmountsViewUser` + zakres
  klienta DL, zapis `ContractsOrdersEditUser`. Wzorzec
  `tests/data/authz_golden/contract_document_folders.json`.
- **Scalanie kontraktów:** foldery idą za kontraktem zachowanym; te same
  nazwy łączą się w jeden folder, nazwa „Zamówień” przegranego znika
  (`contract_merge._resolve_child_duplicates`).
- **SharePoint nie wie o folderach** — przeniesienie niczego tam nie
  przesuwa, usunięcie folderu niczego nie kasuje.
