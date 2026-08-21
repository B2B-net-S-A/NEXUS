# Edycja zamówień Draft + PDF · moduł Finanse — raport z wdrożenia

> **Status:** scalone jako [#1161](https://github.com/artur-t-96/Nexus/pull/1161), raport
> zaktualizowany w [#1166](https://github.com/artur-t-96/Nexus/pull/1166), dwa defekty UI naprawione
> w [#1171](https://github.com/artur-t-96/Nexus/pull/1171). Produkcja: `00c5104`, `/api/health/deep`
> zielony, obie nowe tabele obecne, interfejs przeklikany.

Dwa tickety, jeden PR, dwa rozłączne obszary kodu. Migracja `0228` obsługuje oba,
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

**Świadomie idziemy dalej niż [#1163](https://github.com/artur-t-96/Nexus/pull/1163).** Ten PR,
zmergowany w tym samym dniu, poluzował zapis dla Delivery Leada wyłącznie na kolumnach `md_rate_*`
(powierzchnia order-groups) i zapisał, że legacy `rate_client` / `rate_candidate` / `total_value`
**zostają admin-only**. Tutaj są otwarte dla przypisanego DL — decyzja produktowa, potwierdzona przy
planowaniu.

Uzasadnienie: bez tego draft, którego automat każe uzupełnić, nadal pokazuje DL-owi „—" w miejscu,
gdzie ma wpisać stawkę. #1163 tych pól nie zakazał — po prostu ich nie ruszał w swoim zakresie.
Konsekwencja do posprzątania: dwie bramki finansowe na sąsiednich powierzchniach liczą uprawnienia
niezależnie (patrz „Do zrobienia po deployu", pkt 4).

**Poza zakresem (świadomie):** promocja `draft → active` z UI. Ticket wymienia wyłącznie pola i PDF,
a promocja pociąga walidację kompletności i stemplowanie `filled_at`.

## B. Moduł Finanse

Route `/finance`, API `/api/finance`, tabele `finance_*`, w UI „Finanse" (reguła z `CLAUDE.md`:
etykiety PL, warstwa techniczna EN — ta sama co `/jobs` ↔ „Rekrutacje").

### Trasa dzielona z importem MD (#1162)

W trakcie prac na `main` wszedł [#1162](https://github.com/artur-t-96/Nexus/pull/1162), który
postawił pod `/finance` **inny** moduł: „Import zużycia MD" (`MdImportWorkspace`), zasilający budżety
MD zamówień wielo-konsultantowych. Dwa różne moduły, ta sama trasa, ta sama nazwa, te same role.

Rozstrzygnięte na **trzy zakładki jednej strony** zamiast dwóch adresów:

`Wyniki miesięczne` · `Archiwum` · `Import zużycia MD`

Dwa wpisy „Finanse" w nawigacji zmuszałyby użytkownika do zgadywania, w którym siedzi jego arkusz.
`MdImportWorkspace` osadzony **bez zmiany jego kodu**; w sidebarze jedna pozycja. Przełącznik to ten
sam wzorzec co w module Kontrakty (lokalny `ModeButton`, stan w URL przez History API — nie
`useSearchParams`, który w Next 15 wymusza granicę Suspense wokół całej strony).

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

### Archiwum jest zamrożone

`PATCH /finance/results/{id}` działa **wyłącznie** na wierszach wersji aktualnej. Wiersz z wersji
zastąpionej zwraca **409** (a nie 404 — „jest, ale zamrożony" to co innego niż „nie ma"). Bez tego
„Przywróć jako aktualny" kłamie: przywrócony bieg wracałby ze zmianami wprowadzonymi już **po** jego
zarchiwizowaniu, czyli nie w stanie, w jakim go porzucono. Archiwum ma być zapisem historii, a nie
drugą, edytowalną kopią danych.

### Kafle

Liczone serwerowo **z tych samych wierszy, które zwraca `/results`** — kafel będący sumą innych liczb
niż widoczne pod nim jest niemożliwy do zweryfikowania wzrokiem (ta sama lekcja co `active_mrr`
w profilu klienta).

Auto-review zgłosiło tu podwójny skan tabeli i zaproponowało agregat SQL. **Odrzucone świadomie** —
`SELECT SUM(...)` wprowadza dokładnie ten problem, którego ten kod unika. Arkusz miesięczny to
dziesiątki wierszy, więc koszt jest teoretyczny, a spójność realna. Gdyby moduł urósł do tysięcy
wierszy, właściwą kolejnością jest paginacja tabeli i **dopiero potem** osobna agregacja — z jawną
świadomością, że kafle przestają być sumą tego, co widać.

### RBAC — 7 miejsc

Rola `finance` już istniała i jest **wyłączna** (CHECK `ck_users_exclusive_finance_viewer_roles`):
użytkownik `finance` ma tylko tę rolę i nigdy nie jest jednocześnie adminem. „Admin lub Finanse" to
**dwie rozłączne publiczności**, nie suma uprawnień — dlatego wpis w sidebarze musiał trafić do
`NAV_SECTIONS` **oraz** `FINANCE_NAV_SECTIONS` (użytkownik `finance` nigdy nie widzi tego pierwszego).

Reszta: `middleware.ts` `ROLE_ROUTES`, `capabilities.ts` + jego test, `CommandPaletteV2`,
`RequireRole` na stronie, `FinanceModuleUser` w `deps.py`.

## Trzy błędy znalezione przez auto-review (naprawione)

Wszystkie trzy przeszły przez pełny zestaw testów i dopiero review je wychwyciło — warto zapamiętać
ich wspólną cechę: **żaden nie objawiłby się od razu**.

1. **Edycja wierszy zarchiwizowanego importu.** Opisana wyżej. Łamała gwarancję, którą sam wpisałem
   do docstringa metody `restore_import` — czyli kod obiecywał coś, czego sąsiedni handler nie
   respektował.

2. **Stary PDF kasowany przed commitem.** `_attach_po_bytes` zwalniał poprzedni blob, zanim wiersz
   został utrwalony. Nieudany commit (błąd wstawienia `Activity`, zerwana sesja) zostawiał bazę
   wskazującą na plik, którego już nie ma: podgląd 410, treści nie da się odtworzyć. Kasowanie
   przeniesione **za** commit — najgorszy przypadek to teraz osierocony plik do posprzątania, a nie
   bezpowrotnie utracony dokument. Ta sama zmiana objęła import arkusza (sprzątanie w `except`, bo
   `file_path` jest NOT NULL i plik musi powstać przed wierszem).

3. **Cichy brak advisory locka.** Najgroźniejszy, bo **bezobjawowy**. `AsyncSession.bind` jest
   w SQLAlchemy 2.0 wycofywane i w części konfiguracji zwraca `None`; warunek „pomiń, jeśli to nie
   postgres" zamieniał taki przypadek w brak blokady **bez śladu w logach**. Ujawniłby się dopiero
   losowym 500, gdy dwa importy tego samego miesiąca ścigają się o indeks częściowy. Teraz przy
   nierozpoznanym silniku **próbujemy** wziąć blokadę, a brak wsparcia jest logowany — tryb awarii
   przesunięty z „cicho bez blokady" na „blokada wzięta albo wpis w logu".

Każda ma test broniący jej przed regresją (zamrożone archiwum z rozróżnieniem 409/404, brak sieroty
po nieudanym imporcie, próba blokady przy nierozstrzygalnym bindzie).

## Weryfikacja

| Co | Wynik |
|---|---|
| Łańcuch migracji od zera na czystym Postgresie 16 (`0226 → 0227_multi_consultant_orders → 0228`) | ✅ przechodzi |
| Jedna głowa alembica | ✅ 1 głowa |
| Backend: szeroki przemiat 113 plików testowych | ✅ **1170 passed**, 9 skipped |
| Backend: zestaw dotknięty po poprawkach z review | ✅ **135 passed** |
| `ruff check app/` + `ruff format --check` na zmienionych plikach | ✅ czysto |
| Frontend: `type-check`, `lint` (0 błędów), `build` | ✅ `/finance` 15.8 kB |
| Frontend: pełny vitest | ✅ **1193 passed** (124 pliki) |
| CI na PR (10 checków, w tym 4 shardy pytest) | ✅ 10/10 |
| **Produkcja:** `/api/health` wersja == `f1c7e5f` | ✅ |
| **Produkcja:** `/api/health/deep` + obie nowe tabele | ✅ `healthy`, zero niezdrowych pozycji |

`test_team_structure_dl_clients_dedup.py` pada — sprawdzone na **czystym checkoucie bazowego
commita**: pada tam identycznie, jest w `--ignore` w `ci.yml` i w zadeklarowanej liście znanych
awarii w `test_ci_coverage_contract.py`. Nie jest efektem tych zmian.

### Smoke UI na produkcji — wykonany, znalazł dwa błędy

Pierwotnie ta sekcja mówiła „nie wykonano" (brak sesji SSO dla automatyzacji). Smoke odbył się
później, na zalogowanej sesji, i **znalazł dwa defekty, których nie złapał żaden z 1193 testów
frontendu ani zielone CI** — naprawione w [#1171](https://github.com/artur-t-96/Nexus/pull/1171).

Oba były tej samej natury: **stan NIEWIEDZY renderował się jako konkretne, fałszywe twierdzenie.**

1. **Admin widział „Brak uprawnień" na `/finance`.** `RequireRole` czytał wyłącznie `user`, a ten
   jest `null` do czasu `hydrate()` (tożsamość leży w localStorage, SSR jej nie zna). Dla wszystkich
   dotychczasowych wywołań z domyślnym `fallback={null}` to okno było **niewidoczne** — wystarczyło
   podać własny komunikat, żeby zaczęło twierdzić, że użytkownik nie ma uprawnień. Efekt: admin
   czytał „Poproś administratora o dostęp", będąc administratorem. Komponent sprawdza teraz
   `hydrated` i dopóki tożsamość jest nieznana, nie orzeka w żadną stronę.

2. **Pusty moduł udawał zaimportowany miesiąc.** Warunek pustki brzmiał
   `periods.length === 0 && !isLoading`, więc stan „lista miesięcy się wczytuje" spadał do gałęzi
   z danymi i rysował trzy kafle z „—" oraz pusty selektor miesiąca. Kolejność gałęzi to teraz
   `awaria → nie wiem → pustka → dane`.

**Wniosek, który wykracza poza ten PR.** Ten sam dokument wyżej opisuje regułę „awaria nie może
renderować się jak pustka" i chwali się jej pilnowaniem w cudzym kodzie. Lustrzany błąd —
**niewiedza renderująca się jako odmowa i jako dane** — został tu popełniony w dwóch miejscach naraz
i przeżył pełny zestaw testów, bo żaden test nie odtwarzał okna przed hydracją z jawnym fallbackiem.
Testy sprawdzały `hasRole` (poprawne) i bramki backendu (poprawne); defekt siedział w szczelinie
między nimi. Dopisanie własnego `fallback` do `RequireRole` jest odtąd zmianą, która wymaga pytania
„co ten komunikat mówi, dopóki nic nie wiemy?".

Oba testy sprawdzono jako **nośne**: po tymczasowym cofnięciu poprawek padają 3/6 i 1/4, a asercje
pozytywne (po hydracji, z danymi) nadal przechodzą — poprawka nie osłabiła bramki.

**Uwaga metodyczna:** pomiary czasu okna błędu przez `javascript_tool` były **niewiarygodne** —
kontekst wykonania odpadał po nawigacji i raportował brak tekstu, który zrzut ekranu wyraźnie
pokazywał. Diagnoza opiera się wyłącznie na zrzutach i czytaniu kodu. Gdybym uwierzył tamtym
liczbom, wyciągnąłbym błędne wnioski o przyczynie.

### Co potwierdzono klikaniem (produkcja, `00c5104`)

- Trzy zakładki ze stanem w URL (`?view=archive`, `?view=md`); `MdImportWorkspace` z #1162 bez zmian.
- Uczciwy pusty stan modułu przy zerze importów, także na **zimnym wejściu** (1 s i 5 s po nawigacji).
- „Uzupełnij zamówienie" **wyłącznie** na draftach — kontraktor bez zamówień go nie pokazuje.
- Dialog: numer, okres, obie stawki (widoczne dla admina), opis, sekcja PDF z podmianą.
- **Podgląd PDF otwiera się inline** w nowej karcie (blob z prawdziwym tytułem dokumentu) — wymóg
  „widoczny/dostępny do podglądu" spełniony, nie tylko pobranie.
- Sekcja „Dokumenty zamówień" w Dokumentach kontraktu: kolumna **Typ = „Zamówienie"** i e-mail
  wgrywającego. W trakcie weryfikacji widoczny był plik wgrany przez realną użytkowniczkę
  (`anna.korycka@…`) — czyli nowa ścieżka jest już w użyciu produkcyjnym.
- `can_manage_finance` przychodzi z serwera `true` dla admina na 10 klientach z draftami.

Nadal **nieprzetestowany**: sam import arkusza i edycja komórek dwuklikiem — wymagałyby wgrania
danych testowych na produkcję, a moduł nie ma endpointu usuwania importu (tylko archiwizację), więc
taki wiersz zostałby tam na stałe. Do sprawdzenia pierwszym prawdziwym arkuszem.

### Testy, które zmieniły znaczenie (świadomie)

Trzy testy asertowały, że **przypisany** Delivery Lead widzi zredagowane kwoty. Po poszerzeniu
uprawnień odwracają się — ale zamiast je usunąć, dowód domknięcia przeniesiono na role, które nadal
nie mają dostępu:

- `test_extract_redacts_finance_and_metadata_for_delivery_lead` → **`…_for_head_of_recruitment`**.
  HoR to jedyna rola, która przechodzi guard trasy, ale nie predykat finansowy — czyli mocniejszy
  dowód niż poprzedni.
- Dołożone: nieprzypisany DL → 403, HoR/TAC/recruiter → brak dostępu do kwot, DL nie może przepisać
  `rate_unit`.

## Kolizja z równoległymi PR-ami — lekcja do zapamiętania

W ciągu jednego dnia na `main` weszły cztery PR-y, z czego trzy dotykały tego samego terenu. Merge
blokowały po kolei **trzy różne rzeczy i żadnej nie wykryły lokalne testy**:

1. **Podwójna migracja `0227`.** #1162 wprowadził `0227_multi_consultant_orders`, ta gałąź miała
   własne `0227_*`. **Git nie zgłasza konfliktu** — różne nazwy plików — ale alembic dostałby dwie
   głowy. Przenumerowane na `0228` z `down_revision` na ich rewizję. To ten sam wzorzec, który już
   raz wystąpił przy równoległych PR-ach: *dubel migracji bez konfliktu = dwie głowy*.

2. **Test przypinający NAZWĘ głowy alembica.** #1162 napisał
   `assert _alembic_heads() == ["0227_multi_consultant_orders"]`. Taki test pada przy **każdej**
   następnej migracji w repo, niezależnie od tego, czy cokolwiek się rozszczepiło — a jego własny
   docstring mówi „nowa migracja nie rozszczepia łańcucha", czyli asercję o *liczbie* głów.
   Poprawione na: dokładnie jedna głowa **+** ich rewizja nadal wisi w łańcuchu (osierocona nigdy się
   nie wykona, a licznik głów tego nie wykryje). Nie przestawiono stałej na własną nazwę, bo to tylko
   przesuwa problem na kolejny PR.

3. **Nierozwiązane wątki auto-review.** Branch protection wymaga rozwiązania konwersacji, więc CI
   zielone 10/10 **nie wystarczało** do merge'u. 13 wątków okazało się 4 ustaleniami powtórzonymi
   przez trzy przebiegi review.

Do tego dwukrotnie `main` uciekł w trakcie i `strict=true` odmówił scalenia nieaktualnej gałęzi —
zachowanie prawidłowe: to ten sam bezpiecznik, którego brak sprawił kiedyś, że squash nieaktualnej
gałęzi cofnął sześć merge'y na produkcji.

**Wniosek operacyjny:** przy ruchliwym `main` każdy rebase resetuje ~20-minutowe CI. Przy więcej niż
jednym PR-ze właściwym narzędziem jest `scripts/merge-train.sh`, nie ręczne rebase'y.

## Do zrobienia po deployu

1. ~~`/api/health/deep` musi być zielony~~ — **zweryfikowane**, `finance_import_runs`
   i `finance_monthly_results` obecne na produkcji. To był jedyny realny dowód, że migracja utworzyła
   tabele (prodowy alembic bywa osierocony, stąd lustro DDL w `entrypoint.sh`).
2. ~~Ręczny smoke UI~~ — **wykonany**, znalazł dwa defekty (naprawione w #1171). Patrz sekcja
   „Smoke UI na produkcji". Zostaje do sprawdzenia pierwszym prawdziwym arkuszem: import i edycja
   komórek dwuklikiem.
3. Archiwalne pliki xlsx lądują na wolumenie lokalnym, który — jak reszta uploadów w NEXUSIE — **nie
   ma kopii off-site**. Archiwum to ślad audytowy, nie backup.
4. Do rozważenia w osobnym ticketcie: zunifikowanie `_can_manage_order_finance` (ten PR) z
   `_manages_md_lines` (#1163) w jedną funkcję. Dziś dwie bramki finansowe na sąsiednich
   powierzchniach liczą uprawnienia niezależnie i mogą się rozjechać.
