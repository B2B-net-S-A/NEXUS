# Edycja zamówień Draft + PDF · moduł Finanse — raport z wdrożenia

Dwa tickety, jeden PR, dwa rozłączne obszary kodu. Migracja `0227` obsługuje oba,
bo rozbicie na dwie rewizje dałoby wyłącznie drugą okazję do rozjazdu głów alembica.

## A. Zamówienia w profilu klienta

### Co było nie tak

Zamówienia `draft` powstają automatycznie z hooka „hired/signed"
([`b2b_contract_automation.py:409`](../backend/app/services/b2b_contract_automation.py)) z notatką,
która dosłownie każe użytkownikowi „uzupełnić stawkę klienta, daty i **wgrać PDF zamówienia**".
Backend miał gotowy `PUT /api/clients/{cid}/orders/{oid}/file` — **i ani jednego wywołania z frontu**.
Rejestr prosił o czynność, której nie dało się wykonać.

### Zmiany

| Obszar | Co |
|---|---|
| Edycja draftu | Nowy `EditOrderDialog` (na `ds/AppModal`) dostępny z **każdego** slotu karty — draft trafia do aktywnego, przyszłego albo historycznego zależnie od dat, a draft bez dat ląduje w aktywnym |
| PDF | `dlPortalApi.replaceOrderPo` — pierwszy konsument istniejącego endpointu. Podgląd inline (`openOrderDocument`) + pobranie + „Zamień plik" |
| Most dokumentów | `OrderDocumentsSection` zyskał kolumnę **Typ** („Zamówienie") i e-mail wgrywającego pod datą — 1:1 jak główna tabela Dokumentów kontraktu |

**Most zostaje read-time, bez kopii.** Plik żyje na `ClientOrder.file_path`, a zakładka Dokumenty
kontraktu tylko go listuje. To dlatego wymóg „podmiana aktualizuje, a nie dubluje" jest spełniony
**strukturalnie** — nie ma drugiego zapisu, który mógłby się rozjechać. Test
`test_replacing_pdf_updates_row_instead_of_duplicating` broni tej własności przed „ulepszeniem"
polegającym na kopiowaniu pliku do `contract_documents`.

### Utwardzenie uploadu

1. **Tylko PDF na tej ścieżce** (415 inaczej). Flow A („Dodaj przedłużenie") nadal przyjmuje DOCX —
   globalne zawężenie zepsułoby działającą od dawna ścieżkę, w której klienci przysyłają PO w Wordzie.
   *Skutek uboczny: historycznego PO w .docx nie da się podmienić na .docx.*
2. **Kontrola magicznych bajtów** (`%PDF-`). Rozszerzenie deklaruje nadawca; bez tego dowolne bajty
   przemianowane na `.pdf` były potem serwowane z `media_type=application/pdf`.
3. **Rozmiar sprawdzany PRZED zapisem na dysk** — wcześniej odrzucony upload najpierw materializował
   plik na wolumenie.
4. **Atrybucja wgrania** — nowe kolumny `file_uploaded_by` / `file_uploaded_at`. Dotąd w kodzie stał
   tam no-op `_ = user, datetime, timezone` z komentarzem, że atrybucja jest „gdzie indziej"; nie była.
5. **Naprawiony `order_id=0`** — Flow A zapisywał każdy PO do wspólnego katalogu `client_orders/0/`
   zamiast do katalogu swojego zamówienia. Plik leci teraz po `flush()`, gdy Order ma już id.

### Poszerzenie uprawnień finansowych (decyzja produktowa)

Kwoty na zamówieniach były zamknięte potrójnie (F-13/P0.12): zapis tylko admin, odczyt tylko
`VIEW_FINANCE`, front `admin && manage_finance`. **Rozszerzone na Delivery Leada przypisanego do
klienta.**

Domknięcie opiera się na jednym predykacie `_can_manage_order_finance(user, dl_assigned=...)`, który
sprawdza rolę i przypisanie **niezależnie**. To nie jest stylistyka:

> Guard trasy `require_dl_assigned_or_admin` przepuszcza **head_of_recruitment GLOBALNIE**, bez
> patrzenia na przypisanie. Reguła „ktokolwiek przeszedł ten guard" po cichu dałaby HoR zapis stawek
> u **wszystkich** klientów.

Pilnuje tego `test_head_of_recruitment_never_gains_order_finance`.

Dalsze zawężenia:

- **DL dostaje węższy zestaw pól niż admin** (`_DL_ORDER_FINANCE_WRITE_FIELDS`). `rate_unit`
  i `billing_hours_per_month` to nie kwoty, tylko **reguła ich przeliczania** — ich zmiana przelicza
  wstecz każdą kwotę i marżę na kontrakcie, w tym historyczne, a ticket prosi o dwie stawki.
- **`contracts.py` nietknięty.** Ma ~20 miejsc redakcji i własną admin-only bramkę na 17 pól.
  Stawka kosztowa idzie przez powierzchnię zamówień (`ClientOrderUpdate.rate_candidate` → zapis na
  `order.contract`), więc promień rażenia to jeden moduł.
- **Bramka jest fail-closed z domyślnym `can_finance=False`** i przepuszcza admina niezależnie od
  flagi. Endpoint, który zapomni ją policzyć, zamyka się dla wszystkich poza adminem, zamiast
  otwierać dla wszystkich.
- **Front czyta flagę z serwera** (`can_manage_finance` w odpowiedzi `/orders`), bo nie zna przypisań
  DL. Bez tego renderowałby kontrolkę, która na zapisie kończy się 403 — a to czyta się jak „zapis
  nie działa", nie jak „nie masz uprawnień".

**Poza zakresem (świadomie):** promocja `draft → active` z UI. Ticket wymienia wyłącznie pola i PDF,
a promocja pociąga walidację kompletności i stemplowanie `filled_at`.

## B. Moduł Finanse

Route `/finance`, API `/api/finance`, tabele `finance_*`, w UI „Finanse" (reguła z `CLAUDE.md`:
etykiety PL, warstwa techniczna EN — ta sama co `/jobs` ↔ „Rekrutacje").

### Schemat

`finance_import_runs` (wgrany plik) + `finance_monthly_results` (jego treść). Rozdzielenie jest tym,
co czyni **„Przywróć jako aktualny" wykonalnym**: wiersze wiszą na konkretnym biegu i nigdy nie są
nadpisywane, więc wersja zastąpiona zachowuje własne ręczne poprawki i wraca dokładnie w tym stanie,
w jakim ją porzucono. Gdyby wiersze wisiały na (rok, miesiąc), re-import musiałby je skasować,
a przywracanie odtwarzałoby dane z pliku — czyli gubiło każdą korektę.

Trzy decyzje warte zapamiętania:

- **Status jako VARCHAR + CHECK, nie natywny enum PG.** Poszerzenie domeny to DROP+ADD CHECK-a,
  a nie `ALTER TYPE … ADD VALUE`, które w lustrze `entrypoint.sh` bywa opakowane w
  `EXCEPTION WHEN duplicate_object` i po pierwszym wykonaniu nigdy więcej nie działa (lekcja z 0226).
- **Indeks CZĘŚCIOWY zamiast UNIQUE** na (rok, miesiąc): aktualna wersja musi być jedna, ale
  zastąpionych wolno mieć wiele — to cała treść Archiwum.
- **`file_sha256` celowo BEZ UNIQUE.** `client_import_runs` ma taki indeks i tam jest poprawny;
  tutaj najczęstszy scenariusz „Zastąp" to poprawka w arkuszu i ponowne wgranie, przy którym bajty
  bywają identyczne. Unikalność blokowałaby dokładnie tę ścieżkę.

**Sześciu kolumn spoza tabeli wynikowej (Uwagi, Projekt, Stawka z VD, Czy wystawiono fakturę,
Data wysłania, Płatny urlop) NIE MA W SCHEMACIE.** Ticket wymaga, żeby nie były widoczne w żadnym
widoku; trzymanie ich „na wszelki wypadek" w JSONB tworzyłoby stałą powierzchnię wycieku — każda
przyszła serializacja wiersza by je wyniosła, a żadna nie byłaby świadoma tego zakazu. Oryginalny
plik i tak jest zachowany i pobieralny z Archiwum. Pilnuje tego
`test_import_results_and_hidden_columns_never_serialised` (arkusz testowy niesie je z rozpoznawalnymi
wartościami).

### Parser (pierwszy odczyt XLSX w tym backendzie)

`openpyxl` służył dotąd wyłącznie do **eksportu**. Dwie klasy błędu, celowo rozdzielone:

1. **Nagłówki** — arkusz bez wymaganych kolumn to nie „arkusz z brakami", tylko inny plik.
   Odrzucany w całości, z listą braków i nadmiarów.
2. **Wiersz** — brak lub niepoprawna liczba **nie pomija wiersza**. Pole zostaje `NULL`, liczy się do
   `needs_completion`, operator uzupełnia je dwuklikiem w tabeli. Pomijanie takich wierszy było
   najgorszym z możliwych zachowań: suma w kaflu cicho przestawałaby obejmować kogoś, kogo w arkuszu
   widać. Odrzucany jest wyłącznie wiersz bez nazwiska — bez niego nie ma czego uzupełniać.

Koercja jest jawna i wybaczająca: `„20 900,00 zł"` (twarda spacja) → `20900.00`, `„20,2%"` → `20.2`,
`„b/d"` → `NULL`. Parser leci przez `run_in_threadpool` — uvicorn ma jednego workera.

### Zastępowanie i przywracanie

`POST /imports` z `replace=false` przy istniejącej wersji zwraca **409** z liczbą wierszy **oraz
liczbą wierszy niosących ręczne poprawki**. Front zamienia to na pytanie „Zastąpić?" i wysyła
ponownie z `replace=true` — dwa kroki, ale plik idzie przez sieć raz.

> **Bug złapany przez własny test:** zapytanie liczące te poprawki robiło `edited_fields != "[]"`,
> czyli `jsonb <> varchar`. Postgres nie ma takiego operatora → **500 dokładnie w ścieżce, która ma
> ostrzec użytkownika przed utratą pracy**. Naprawione CAST-em na tekst.

### Kafle

Liczone serwerowo **z tych samych wierszy, które zwraca `/results`** — kafel będący sumą innych liczb
niż widoczne pod nim jest niemożliwy do zweryfikowania wzrokiem (ta sama lekcja co `active_mrr`
w profilu klienta).

### RBAC — 7 miejsc

Rola `finance` już istniała i jest **wyłączna** (CHECK `ck_users_exclusive_finance_viewer_roles`):
użytkownik `finance` ma tylko tę rolę i nigdy nie jest jednocześnie adminem. „Admin lub Finanse" to
**dwie rozłączne publiczności**, nie suma uprawnień — dlatego wpis w sidebarze musiał trafić do
`NAV_SECTIONS` **oraz** `FINANCE_NAV_SECTIONS` (użytkownik `finance` nigdy nie widzi tego pierwszego).

Reszta: `middleware.ts` `ROLE_ROUTES`, `capabilities.ts` + jego test, `CommandPaletteV2`,
`RequireRole` na stronie, `FinanceModuleUser` w `deps.py`.

## Weryfikacja

| Co | Wynik |
|---|---|
| Migracja `0227` od zera na czystym Postgresie 16 | ✅ przechodzi |
| Jedna głowa alembica (`test_no_new_alembic_heads`) | ✅ 1 głowa |
| Backend: szeroki przemiat 109 plików testowych | ✅ **1124 passed**, 9 skipped |
| Backend: nowe testy (`test_finance_module`, `test_client_order_file_upload`) | ✅ 22 passed |
| `ruff check app/` + `ruff format --check` na zmienionych plikach | ✅ czysto |
| Frontend: `type-check`, `lint` (0 błędów), `build` | ✅ `/finance` 17.1 kB |
| Frontend: pełny vitest | ✅ **1177 passed** (122 pliki) |

`test_team_structure_dl_clients_dedup.py` pada — sprawdzone na **czystym checkoucie bazowego
commita**: pada tam identycznie, jest w `--ignore` w `ci.yml` i w zadeklarowanej liście znanych
awarii w `test_ci_coverage_contract.py`. Nie jest efektem tych zmian.

### Testy, które zmieniły znaczenie (świadomie)

Trzy testy asertowały, że **przypisany** Delivery Lead widzi zredagowane kwoty. Po poszerzeniu
uprawnień odwracają się — ale zamiast je usunąć, dowód domknięcia przeniesiono na role, które nadal
nie mają dostępu:

- `test_extract_redacts_finance_and_metadata_for_delivery_lead` → **`…_for_head_of_recruitment`**.
  HoR to jedyna rola, która przechodzi guard trasy, ale nie predykat finansowy — czyli mocniejszy
  dowód niż poprzedni.
- Dołożone: nieprzypisany DL → 403, HoR/TAC/recruiter → brak dostępu do kwot, DL nie może przepisać
  `rate_unit`.

## Do zrobienia po deployu

1. `/api/health/deep` musi być zielony — to **jedyny** realny dowód, że obie tabele powstały
   na produkcji (prodowy alembic bywa osierocony).
2. Archiwalne pliki xlsx lądują na wolumenie lokalnym, który — jak reszta uploadów w NEXUSIE — **nie
   ma kopii off-site**. Archiwum to ślad audytowy, nie backup.
