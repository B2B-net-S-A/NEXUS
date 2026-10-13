# Dokumenty kontraktów z SharePointa (ticket 9, 0402, 29.09.2026)

Folder „Umowy pracowników” (podfolder „Nazwisko Imię” na osobę) ↔ zakładka
Dokumenty kontraktu. Kod: `services/contract_folder_docs/` (klasyfikator,
matcher, plan, zapis, przebiegi, synchronizacja), `services/m365/sharepoint_docs.py`,
`api/contract_folder_docs.py`, pętla `tasks/contract_docs_sharepoint.py`, panel
Ustawienia → Umowy i stawki (`ContractDocsSharePointPanel`, harness
`/preview/contract-docs-sharepoint`). Konfiguracja: `docs/contract-docs-sharepoint-setup.md`.

- **Osobna rejestracja „NEXUS Contract Documents” z `Sites.Selected`** na jedną
  witrynę — nie dokładaj tego uprawnienia do rejestracji poczty ani Teams.
  Bez `CONTRACT_DOCS_SP_CLIENT_ID/SECRET` pętla kończy się przed `while`, a panel
  mówi „dokończ konfigurację w Azure”. Linku udostępnienia nie trzymamy w repo
  (publiczne) — admin wkleja go w panelu (`app_settings['contract_docs_sharepoint']`).
- **Punktem wyjścia jest NEXUS:** folder bez kontraktu niczego nie zakłada.
  Osoba z kilkoma kontraktami dostaje pliki na każdym. Filip Jabłoński
  (`is_excluded_person`) jest pomijany w obu kierunkach. Dopasowanie
  (`matching.py`) po zbiorze słów bez polskich znaków: `sure` / `uncertain`
  (polskie znaki, drugie imię/człon nazwiska, literówka, dwa rekordy kandydata)
  / `ambiguous` (kilka folderów — nie zgadujemy) / `none`.
- **Typ z nazwy pliku** (`classify.py`): aneks/wypowiedzenie/porozumienie
  sprawdzane PRZED formatem „numer B2B data” (umowa), „OC”/„NDA”/„ZUS” tylko
  jako całe słowo. Tylko PDF i JPG, ≤ 20 MB.
- **„Kontrakt ma już ten dokument” = ten sam SHA-256 albo ten sam plik
  SharePointa** (`contract_documents.content_sha256`, `sharepoint_item_id`);
  stare wiersze dostają skrót leniwie (`store.attach_file`, blokada doradcza
  per kontrakt). Ręczny upload też liczy skrót.
- **Pierwsze pobranie** = przebieg z dzierżawą (`listing → preview → applying →
  applied`, cofnięcie tylko ostatniego); przerwany deployem podejmuje pętla.
  Paragon `0402_contract_docs_sharepoint_run_<id>` = liczby i ID.
- **Synchronizacja** (`CONTRACT_DOCS_SP_SYNC_ENABLED`, OFF): pełny spis
  folderu co godzinę (delta nie działa na podfolderze), stan pliku w
  `contract_doc_sp_items` — decyzja o pliku jest ostateczna, wracają tylko
  `waiting_contract`; niepewne → kolejka „Do przypisania”. NEXUS → SharePoint:
  dokumenty dodane PO pierwszym pobraniu (`push_since`), bez
  `sharepoint_item_id`, nie z SharePointa i bez PDF-ów zamówień; folder
  wspólny dla dwóch rekordów kandydata = pominięcie. `conflictBehavior=rename`,
  PUT uploadu bez ponowienia po utracie odpowiedzi. Usunięcie po żadnej
  stronie nie kasuje drugiej. Folder synchronizacji ustawia dopiero ZAPIS
  pierwszego pobrania, nie podgląd. Klucz pliku na dysku nie niesie nazwy
  (podfoldery miewają dwa „umowa.pdf”).
- **Treść podmieniona w NEXUSIE po wysyłce** (skan podpisanego aneksu —
  jedyny dokument podmieniany w miejscu, 13.10.2026): wołający cofa stan na
  „czeka” przez `store.requeue_replaced_content` (`sharepoint_item_id`
  zostaje), a `sync._replace_one` podmienia treść TEGO pliku
  (`sp.replace_content`, PUT po id elementu) zamiast dokładać drugi. Do
  13.10.2026 wiersz z `sharepoint_item_id` nie wracał do wysyłki wcale i
  w SharePoincie zostawał stary skan. Podmieniamy wyłącznie plik, który
  wysłał NEXUS (`contract_doc_sp_items.status = 'pushed'`) i który nadal jest
  w folderze — plik powiązany z dokumentem tylko po treści należy do działu,
  wtedy nowa treść idzie jako nowy plik. Najpierw nazwa, potem treść: przy
  zmianie typu pliku nieudana zmiana nazwy przerywa podmianę (ponowi ją
  następny bieg), przy tym samym typie zostaje stara nazwa. Plakietka
  dokumentu z `sharepoint_item_id` i stanem innym niż `done` mówi
  „w SharePoincie poprzednia wersja”. Nowy dokument podmieniany w miejscu =
  to samo wywołanie przed nadpisaniem pól.
