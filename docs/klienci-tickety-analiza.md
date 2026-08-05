# Analiza 5 ticketów — moduł Klienci (przegląd inżynierski)

> Ocena zgłoszeń od pracownika skonfrontowana z **rzeczywistym kodem** NEXUS-a
> (nie z opisem, nie z założeniami). Każdy wniosek jest zakotwiczony w `plik:linia`.
> Data: 2026-08-05. Metoda: 6 równoległych agentów czytających backend + frontend,
> synteza + weryfikacja adwersaryjna.

---

## TL;DR — werdykt per ticket

| # | Ticket | Werdykt | Nakład | Sedno |
|---|--------|---------|--------|-------|
| **1** | Statusy klientów + edycja nazwy | ⚠️ **Częściowo błędny** | L | Sekcje **nie wynikają ze statusu** — są sterowane osobnym polem. „Masowa naprawa statusów" jest szkodliwa. Edycja nazwy = realny bug (pisze do złego pola + Traffit nadpisuje). |
| **2** | Wyszukiwarka zamówień | ✅ **Sensowny** | S | Prosty filtr po stronie FE, endpoint zwraca pełną listę (bez paginacji) → bezpieczne. Doprecyzować „numer" i „imię/nazwisko". |
| **3** | „Wybór części umowy" (e-Zdrowie) | ⚠️ **Sensowny z zastrzeżeniami** | L | Nowe pole od zera. Bramkowanie po nazwie klienta jest **kruche** (Traffit + duplikaty rekordów). Filtr jest na poziomie kontraktu, a pole na poziomie zamówienia — kolizja modelu. „Formularz uzupełniania draftu" nie istnieje. |
| **4** | Stawka przychodowa + sprzątanie karty | ✅ **Sensowny z zastrzeżeniami** | S | Pkt 1 (edytowalna stawka przychodowa) jest **w większości już zrobiony**. Pkt 2 i 3 (usuń „Contract #" i rekrutację) — czyste, bezpieczne. RBAC finansowy ogranicza „zawsze widoczne". |
| **5** | Zakończenie projektu + synchronizacja 3 modułów | ⚠️ **Sensowny z zastrzeżeniami** | L | Większość klocków **już istnieje** (terminacja kontraktu, dane archiwum, status `completed`). Screenshot to **makieta**, nie stan appki. Realnie nowa jest **jedna rzecz**: dwukierunkowy sync Contract↔Order. |

**Ogólnie:** zgłoszenia są rozsądne i pochodzą z realnej pracy z systemem, ale **trzy z pięciu** opierają się na częściowo błędnym modelu tego, jak system działa pod spodem. Zanim cokolwiek budujemy, trzeba rozbroić kilka min opisanych niżej — inaczej „naprawy" albo nie zadziałają, albo cofną się po dobie (Traffit), albo zepsują istniejące funkcje (klauzule umów po nazwie klienta).

---

## 🔴 Miny przekrojowe (przeczytaj to najpierw — dotyczą wielu ticketów)

### Mina 1 — Traffit codziennie nadpisuje `name` i `status` klienta
Codzienny sync Traffita robi `ON CONFLICT DO UPDATE SET name = EXCLUDED.name, status = EXCLUDED.status` na **każdym** klienta z Traffita (`importer.py:230-234`), a faza klientów robi **pełny skan przy każdym uruchomieniu** (`traffit_sync.py:225`). Pusty/nieznany status z Traffita „cichaczem" wraca do `active` (`mappers.py:100-102`).

**Konsekwencja:** ręczna zmiana nazwy albo statusu na kliencie z Traffita **cofa się w ~24h**. To jest utrata danych by-design. Dotyczy ticketa #1 (bug 2 i bug 4) bezpośrednio.

Pola **odporne na sync** (nie ma ich w `UPDATE SET`): `display_name`, `legal_name`, `nip`, `regon`, `industry`, `website`, `address`, `hidden`, `nda_signed`, `cv_content_mode_cap` (`importer.py:230-234`, potwierdza komentarz `client.py:53-59`). **`display_name` to gotowy, sync-odporny override nazwy** — dlatego to jest właściwe miejsce na edycję nazwy.

Kontrakty i zamówienia (`client_orders`) Traffit **nigdy nie dotyka** → stawki, daty, `project_part`, end_date są bezpieczne. Więc miny sync-owe dotyczą **tylko ticketa #1**.

### Mina 2 — „Centrum e-Zdrowia" to 2–3 rekordy, nie jeden
W bazie istnieją **dwa** rekordy: `id 115 „eZdrowie"` i `id 5257 „E-Zdrowie"` (`ContractRegisterDialog.tsx:98-101`), plus kanoniczny wpis katalogowy `centrum-e-zdrowia` w portfolio. Bramkowanie funkcji po jednym `id` **cicho ominie drugi rekord**, a agregaty (marża, konsultanci) „dla tego klienta" są rozjechane na dwa wiersze.

**Rekomendacja:** rozważ **scalenie duplikatów** (mechanizm `merged_into_client_id` już istnieje, `client.py:91-93`) **zanim** zbudujesz jakiekolwiek bramkowanie per-klient (ticket #3). Inaczej zakodujesz duplikat w konfiguracji.

### Mina 3 — Bramkowanie po nazwie klienta jest kruche i już dziś niespójne
Istniejące funkcje per-klient bramkują **po podciągu nazwy**: klauzule umów §10 e-Zdrowie/PFRON (`clause_override_content.py:2713-2725`, needle `('centrum e-zdrowia','e-zdrowia')`), etykiety kodów projektu (`ContractRegisterDialog.tsx:102-112`, `includes('e-zdrow')`), klauzule w generatorze (`B2BContractGeneratorV2.tsx:252`).

Problem: faktyczne nazwy rekordów (`E-Zdrowie`/`eZdrowie`) **nie zawierają** podciągu `e-zdrowia`, na który łapie generator — więc dziś **decyduje o tym, który string nazwy zostanie podany**. To już jest niespójne.

**Sprzężenie z ticketem #1:** jeśli pozwolimy edytować nazwę klienta (bug 4), albo Traffit zmieni ją z powrotem, to **§10 e-Zdrowie/PFRON może zniknąć z umowy** albo etykieta zamówienia się rozjedzie. To jest ukryty bug poprawnościowy schowany za niewinnym „pozwólmy edytować nazwę". Ticket #3 dokłada kolejną funkcję na tym kruchym fundamencie.

**Rekomendacja:** bramkuj po **stabilnym sygnale** — dedykowana kolumna boolowska na `Client` (precedens: `cv_content_mode_cap`, `client.py:72-78`) albo zbiór `client_id` rozwiązany przez alias/portfolio — **nigdy po podciągu nazwy**.

### Mina 4 — „Obecni konsultanci" jest per-KONTRAKT, a stawka/część są per-ZAMÓWIENIE
Lista „Obecni konsultanci" buduje się **wyłącznie z `Contract`** (status active/ending), czyta `monthly_rate_client`/`monthly_margin` z właściwości kontraktu i **w ogóle nie dotyka `ClientOrder`** (`clients.py:350-382`). Tymczasem `project_part` (ticket #3) i „bieżąca" stawka przychodowa (ticket #4) żyją na **zamówieniu**, a jeden kontrakt ma **wiele zamówień** w czasie (przedłużenia 3mc→6mc→6mc).

**Konsekwencja:** konsultant na 3. przedłużeniu ma 3 zamówienia — **nie ma jednej wartości** `project_part`/stawki dla jego wiersza. Trzeba ustalić jawną regułę „reprezentatywnego zamówienia". Moduł Kontraktorzy już to rozwiązał: bierze **najnowsze zamówienie po `start_date`** i liczy efektywną stawkę jako `latest.rate_client or contract.rate_client` (`client_orders.py:330-361`). Endpoint profilu tego **nie reużywa** — trzeba to podpiąć. Dotyczy #3, #4, #5.

### Mina 5 — Dyscyplina migracji: prod alembic jest osierocony
`entrypoint.sh` **nie ma żadnego DDL dla `client_orders`** (tworzy tylko `client_tac_assignments`). Nowa kolumna `project_part` (ticket #3) dodana samą migracją **nie dotrze na proda** → ORM 500. Wymaga świeżego mirrora `ALTER TABLE client_orders ADD COLUMN IF NOT EXISTS project_part ...` w `entrypoint.sh`. (Tickety #1/#4/#5 **nie** wymagają migracji — wszystkie potrzebne kolumny już istnieją.)

### Mina 6 — Finanse są gated (RBAC), a 403 na GET renderuje się jako pusty stan
Stawki (koszt/przychód/marża) to dane finansowe: widoczne/edytowalne tylko dla `admin + manage_finance` (`auth.ts:271-281`), backend redaguje odczyt dla nie-`VIEW_FINANCE` (`clients.py:508-518`, `client_orders.py:225-245`), a zapis stawki zamówienia jest **Admin-only** (`client_orders.py:163-176`). „Zawsze widoczne" z ticketa #4 **nie może** obejść tego RBAC. I uwaga: 403 na GET w tej appce renderuje się jako pusty stan („wygląda jak utrata danych") — każdy nowy gated widok musi mieć jawny stan pusty/zredagowany.

---

## Ticket #1 — Statusy klientów + edycja nazwy → ⚠️ częściowo błędny

### Co zgłoszono
4 bugi: (1) klienci ze statusem „Aktywny" są w sekcji „Nieaktywni" + prośba o masową naprawę statusów; (2) nie da się ręcznie zmienić statusu; (3) zmiana statusu ma auto-przenosić do sekcji; (4) edycja nazwy się nie zapisuje.

### Co naprawdę jest w kodzie
- **Sekcje NIE wynikają ze statusu.** Są 3 sekcje (Aktywni/Relacyjni/Nieaktywni — `ClientsListV2.tsx:69-108`), ale przynależność steruje **`ClientPortfolioScope.category`**, a nie `Client.status`. Zapytanie filtruje po `ClientPortfolioScope.category == category` (`client_directory.py:133`), a docstring modelu wprost pisze, że jest to „deliberately separate from Client.status" (`client_directory.py:1-12, 43-48`). `Client.status` to **tylko badge** w kolumnie „Status klienta" (`ClientsListV2.tsx:755-759`).
- **Kontrolka zmiany statusu ISTNIEJE i działa** end-to-end: `EditClientModal` ma dropdown Prospekt/Aktywny/Nieaktywny (`AppShell.tsx:1733-1739`) → `PATCH /api/clients/{id}` z `status` (`AppShell.tsx:1844` → `clients.py:538`). Schemat `ClientUpdate` ma `status` i `name`, ale **nie ma `display_name`**.
- **Nazwa wyświetlana wszędzie = `coalesce(display_name, name)`** (`client_directory.py:45-51`, `clients.py:120-124`). Formularz edycji pisze do **`Client.name`**, nigdy do `display_name`.
- **Nic nie zmienia `ClientPortfolioScope.category` z frontu** — jedyna rzecz przenosząca klienta między sekcjami. Endpoint `PATCH /clients/{id}/portfolio-scopes/{scope_id}` istnieje, ale jest **Admin-only i niepodpięty** (`client_directory.py:547-591`).

### Ocena / czy to ma sens
- **Bug 1 — założenie błędne.** „Aktywny w Nieaktywnych" to **nie bug danych** — to klient, którego *scope.category* = `inactive`, niezależnie od statusu. Proponowana „masowa naprawa statusów" jest **szkodliwa na 3 sposoby**: (a) nie ruszy ich z sekcji (sekcja to category, nie status); (b) oznaczy realnie aktywnych jako nieaktywnych na badge; (c) dla klientów z Traffita status i tak wróci po dobie (Mina 1). Jeśli chcemy poprawić *przynależność do sekcji*, poprawiamy **`scope.category`**, nie `status`.
- **Bug 2 — założenie sprzeczne z kodem.** Kontrolka statusu działa. Realne odczucie to prawdopodobnie: (a) status się zmienił, ale klient nie zmienił sekcji (to bug 3), albo (b) status cofnął się po sync Traffita. Do reprodukcji.
- **Bug 3 — to re-architektura albo mały wiring, zależnie od intencji.** Dwie drogi: **(a)** podpiąć kontrolkę zmieniającą `scope.category` (endpoint istnieje, wystarczy poluzować RBAC i podłączyć FE) — realistyczne; **(b)** przebudować katalog, by grupował po `Client.status` — to **rozbija** zamierzony model wielu scope'ów per klient, import z Excela (`ClientImportRow.category`) i powiązanie z umowami ramowymi. Trzeba dopytać, o którą wersję chodzi.
- **Bug 4 — realny bug, dwie niezależne przyczyny.** Oba wynikają z pisania do `Client.name` zamiast `display_name`: (i) jeśli klient ma niepusty `display_name`, `coalesce` **na stałe** zasłania zmianę `name`; (ii) jeśli `external_source='traffit'`, nazwa cofa się przy następnym sync. Naprawa jednej przyczyny zostawia drugą. **Rozwiązanie:** kieruj edycję nazwy na `display_name`. Kolumna już istnieje — **bez migracji**.
- **Dodatkowo:** przycisk „Edytuj" na froncie **nie jest** RBAC-gated, a backend PATCH jest `TacPlus` (`clients.py:527`) → nie-TAC widzi „Edytuj", edytuje i dostaje 403 na zapisie (renderowane jako generyczny błąd) — co samo w sobie może być mylone z „zapis nie działa".

### Rekomendacja
**Rozdziel i częściowo odrzuć.**
- ✅ **Bug 4 — zrób** (S/M, bez migracji): przełącz edycję nazwy na `display_name` (dodaj `display_name` do `ClientUpdate`, formularz edytuje/wysyła `display_name`). Zdecyduj UX: czy pole „Nazwa firmy" ma pisać do `display_name`, czy dodać osobne „Nazwa wyświetlana".
- ❌ **Odrzuć masową naprawę statusów** z bug 1 — nie ruszy sekcji, mislabeluje aktywnych, cofa się na Traffit. Jeśli chcemy data-fix, celuj w `scope.category`.
- ❓ **Bug 2/3 — najpierw reprodukcja + doprecyzowanie:** czy pracownik chce, by *status* sterował sekcjami (ryzykowna przebudowa), czy tylko UI do przenoszenia klienta między sekcjami przez edycję `scope.category` (endpoint istnieje)? Jeśli status ma być ręcznie edytowalny na klientach z Traffita — potrzebna **ochrona przed sync** (usunąć `status` z `DO UPDATE SET` w importerze, albo osobna kolumna `status_override`) → to już wymaga zmiany importera + schematu + mirrora w `entrypoint.sh`.

---

## Ticket #2 — Wyszukiwarka zamówień → ✅ sensowny (S)

### Co naprawdę jest w kodzie
- **Zakres = per-klient**, nie globalny. „Klienci → Zamówienia" to zakładka `zamowienia` wewnątrz strony jednego klienta (`clients/[id]/page.tsx:767, 934` → `<OrdersAndContractsTab>`). Nie ma globalnej listy zamówień.
- Endpoint `GET /api/clients/{client_id}/orders` (`client_orders.py:299-372`) **zwraca całą listę bez paginacji**. Obecne filtrowanie (piguły all/active/expiring/ended/drafts) jest **po stronie FE** nad pełnym zbiorem (`OrdersAndContractsTab.tsx:80-109`) — i **nie gubi trafień**, bo zbiór jest kompletny (inaczej niż paginowane listy).
- **„Numer zamówienia"** w UI = `ClientOrder.title` (wolny tekst, `String(255)`, etykieta „Numer zamówienia" `OrdersAndContractsTab.tsx:608`). Osobny szary badge „Contract {id}" to `contract_id` — to jest „Contract #411" z ticketa #4, **inny identyfikator**.
- **„Imię/nazwisko klienta"** realistycznie = **nazwisko KONSULTANTA** (`candidate_name` = `candidate.name + lastname`, `client_orders.py:346-350`), bo klient to firma bez imienia/nazwiska, a zakładka i tak jest już zawężona do jednego klienta.
- Gotowy wzorzec do reużycia jest **na tej samej stronie**: `ProjectsTab.tsx:197-233` — `useDebouncedValue(300ms)` + input z ikoną Search + osobny stan pusty „...pasujących do wyszukiwania".

### Ocena / rekomendacja
**Zrób jak proszono, jako filtr po stronie FE** (reużyj `useDebouncedValue` + styl inputu z `ProjectsTab`), dopasowując po `candidate_name` **LUB** dowolnym `order.title` w `contractor.orders` **LUB** `contract_id`. To jest poprawne i **małe**, bo endpoint zwraca pełny zbiór. Dodatkowo:
- Przy aktywnym wyszukiwaniu **wymuś rozwinięcie** sekcji „Historia zamówień" (dziś zwijana `showHistory`), by trafienie w zamówieniu historycznym nie było ukryte.
- Osobny komunikat pustego stanu dla „brak trafień" vs „klient nie ma kontraktorów".
- **Uwaga diakrytyki:** naiwne `.includes()` w JS jest wrażliwe na polskie znaki („jarzab" nie złapie „Jarząb"). Dla małej listy per-klient akceptowalne, ale warto odnotować.
- **Nie kopiuj** serwerowego `?q=` z Kontraktów, chyba że chcesz future-proofing — wtedy dodaj `q` do endpointu. Minimalnie: komentarz przypinający założenie „bez paginacji → filtr FE bezpieczny" (gdyby ktoś kiedyś dodał `limit`, wyszukiwarka zaczęłaby cicho gubić trafienia).

### Do doprecyzowania z pracownikiem
- „Numer zamówienia" = `title` (wpisywany numer PO) i/lub badge „Contract {id}"? (rekomendacja: szukaj po obu)
- „Imię/nazwisko klienta" = konsultant (nie firma)? (rekomendacja: tak)

---

## Ticket #3 — „Wybór części umowy" (project_part) dla e-Zdrowia → ⚠️ sensowny z zastrzeżeniami (L)

### Co naprawdę jest w kodzie
- **`project_part` nie istnieje nigdzie** (0 trafień w grep). Greenfield.
- Pole „Rekrutacja", pod którym ma być dropdown, jest **tylko** w formularzu nowego zamówienia (`NewContractorOrderDialog.tsx:307-322`, Flow B).
- **„Formularz uzupełniania draftu" NIE ISTNIEJE.** Auto-drafty (tworzone przez `_ensure_open_order` po podpisaniu umowy B2B, `b2b_contract_automation.py:409-447`) uzupełnia się przez **inline-edycję** w karcie kontraktora (`OrdersAndContractsTab.tsx:565-731`) — tam nie ma pola „Rekrutacja" ani formularza.
- „Otwarte rekrutacje" (lista) = `OpenJobsSection` (`ProfileTab.tsx:105-159`); kafelek metryki „Otwarte rekrutacje" jest osobny w `SummaryBar.tsx:15-20`. Usunięcie listy jest **w pełni izolowane** od kafelka.
- „Obecni konsultanci" = `active_consultants`, budowane **wyłącznie z Contract** (`clients.py:350-382`) — **brak źródła danych `project_part`** dziś.

### Ocena / czy to ma sens
Pomysł biznesowy jest sensowny, ale ticket ma **4 zderzenia z rzeczywistością**:
1. **Bramkowanie „tylko e-Zdrowie" po nazwie jest kruche** — patrz Mina 2 (2–3 rekordy) i Mina 3 (nazwa edytowalna + Traffit). Bramkuj po stabilnej fladze/`client_id`, nie po nazwie.
2. **Kolizja Order vs Contract** (Mina 4) — `project_part` na zamówieniu, filtr na poziomie kontraktu. Trzeba jawnej reguły „reprezentatywnego zamówienia" (najnowsze po `start_date`, reużyj `client_orders.py:330-361`) i wystawić `project_part` na `ActiveConsultantItem`. Bez tego filtr nie ma danych, a „edycja części natychmiast aktualizuje filtr" jest niejednoznaczna przy przedłużeniach.
3. **„Required" nie może być constraintem DB** — kolumna musi być `nullable` (auto-draft B2B i wszyscy inni klienci tworzą zamówienia bez części). `NOT NULL` **wywali** hook auto-draftu i zepsuje pozostałych klientów. „Wymagane" egzekwuj **tylko w UI e-Zdrowia**.
4. **„Formularz draftu" nie istnieje** — trzeba zdecydować: dokleić gated pole części do inline-edytora w `OrdersAndContractsTab`, czy zbudować realny formularz.

### Rekomendacja
**Idź w to, ale najpierw rozwiąż bramkowanie i regułę zamówienia.** Konkretnie:
- Model: `project_part` jako **5-wartościowy enum** (cz.1/2/4/5/6 — brak cz.3 jawnie), `nullable`. Migracja **+ mirror w `entrypoint.sh`** (Mina 5).
- Bramka e-Zdrowia: **flaga/`client_id`, nie nazwa** (i najpierw scalić duplikaty 115/5257 — Mina 2).
- Reguła „current order" wspólna dla #3/#4/#5.
- ⚠️ **KOREKTA (po weryfikacji Codexa, 2026-08-05):** usunięcie listy „Otwarte rekrutacje" **NIE jest bezpieczne** — sekcja `OpenJobsSection` **nie jest read-only**. Hostuje jedyne w całej appce UI „Oznacz rekrutację jako przegraną" (`CloseJobAsLostModal` = jedyny caller `POST /api/jobs/{id}/close`), akcję „Dodaj kandydata" i link do rekrutacji. Kafelek metryki jest izolowany, ale sama lista niesie akcje. **Przed usunięciem** trzeba przenieść „zamknij jako przegraną" (twarda strata) i najlepiej „dodaj kandydata" (odzyskiwalne przez stronę `/jobs/[id]`) do zakładki Projekty. Szczegóły: patrz [weryfikacja Codexa](klienci-tickety-weryfikacja-codex.md).

### Do doprecyzowania
- Przy wielu zamówieniach jednego kontraktu — które zamówienie napędza filtr (aktywne? najnowsze?). Czy część jest per-zamówienie (zmienia się przy przedłużeniu) czy efektywnie per-kontrakt?
- Czym jest „formularz uzupełniania draftu"? (dziś to inline-edycja)
- Czy walidacja „wymagane" ma odpalać też przy edycji istniejącego zamówienia e-Zdrowia z pustą częścią (legacy/auto-draft), czy tylko przy tworzeniu?

---

## Ticket #4 — Stawka przychodowa + sprzątanie karty → ✅ sensowny z zastrzeżeniami (S)

### Co naprawdę jest w kodzie
- **Pkt 1 jest w większości JUŻ ZROBIONY.** Stawka przychodowa (`ClientOrder.rate_client`) jest **już inline-edytowalna** na każdej karcie z zamówieniem, z placeholderem „ustaw stawkę" gdy `NULL`, zapis przez `dlPortalApi.updateOrder` (`OrdersAndContractsTab.tsx:665-693`). Ten sam UX co stawka kosztowa, obok siebie w tym samym wierszu.
- **Jedyny przypadek** pokazujący tylko „stawkę kosztową" bez pola przychodowego to **kontrakt bez żadnego (nieanulowanego) zamówienia** — wtedy guard `&& activeOrder` jest fałszywy i karta pokazuje „Brak zamówień" (`OrdersAndContractsTab.tsx:665, 785-789`). Screenshot z ticketa to najpewniej **ten przypadek** albo zrzut sprzed obecnego kodu.
- „Contract {id}" = szary span `OrdersAndContractsTab.tsx:597-599` (cel pkt 2). „z rekrutacji: {initial_job_title}" = `OrdersAndContractsTab.tsx:716-721` (cel pkt 3).
- Rekrutacja **nie jest unikatowa dla karty** — ten sam `job_title` jest w Profil → Obecni konsultanci (`ConsultantRow.tsx:61-71`), z tego samego źródła. Usunięcie z karty **nic nie traci**.
- **Koszt vs przychód to dwa różne obiekty i endpointy:** koszt = `Contract.rate_candidate` (`contractsApi.update`), przychód = `ClientOrder.rate_client` (`dlPortalApi.updateOrder`). Karta stawia je obok siebie, ale „edycja obu w jednym miejscu" to **iluzja UI nad dwoma obiektami**. Kontrakt bez zamówienia nie ma gdzie trzymać `rate_client`.

### Ocena / rekomendacja
- ✅ **Pkt 2 i 3 — zrób jak jest** (S, czyste kosmetyczne usunięcia, zero utraty danych): usuń span „Contract {id}" i blok „z rekrutacji". (Zastanów się, czy usunąć też etykietę „Job:" w wierszach historii, `OrdersAndContractsTab.tsx:933-935` — jeśli intencją jest wyczyścić wszystkie odwołania do rekrutacji z widoku Zamówień.)
- ⚠️ **Pkt 1 — najpierw zweryfikuj przeciw screenshotowi** (żeby nie robić już zrobionego). Jedyny realny gap: kontrakt **bez zamówienia** nie ma gdzie zapisać stawki przychodowej → decyzja: auto-tworzyć draft zamówienia przy pierwszym wpisaniu stawki, czy pominąć pole tam.
- 🔒 **„Zawsze widoczne" nie obchodzi RBAC finansowego** (Mina 6): dla ról bez `manage_finance` obie stawki są **ukryte** (redakcja + 403 na zapis). „Zawsze" = „zawsze dla ról finansowych". Nie poszerzaj widoczności bez świadomej decyzji RBAC.

### Do doprecyzowania
- „Na każdym zamówieniu" = każdy wiersz (przyszłe/historyczne dostają własną inline-edycję), czy tylko „widoczne tam, gdzie zamówienie istnieje" (już prawda dla aktywnego)?
- Kontrakt bez zamówienia: auto-tworzyć draft przy wpisaniu stawki, czy pomijać pole?
- Czy stawka ma zostać gated do `admin + manage_finance` (obecny RBAC)?

---

## Ticket #5 — Zakończenie projektu + synchronizacja 3 modułów → ⚠️ sensowny z zastrzeżeniami (L)

### Co naprawdę jest w kodzie (dużo już istnieje!)
- **Terminacja kontraktu działa end-to-end:** `POST /contracts/{id}/terminate` (`contracts.py:2851-2943`) ustawia `terminated_at` + `termination_reason` + koherentny `end_date` + status przez `_status_after_end_date_change` (przyszła data → zostaje active/ending, demon dowozi `ended`). **Dwa** wejścia UI już wołają `contractsApi.terminate`: przycisk „Zakończ" w Profil→Obecni konsultanci (`ProfileTab.tsx:192-200` → `TerminateContractModal.tsx`) i „Zakończ współpracę" na `/contracts/[id]` (`ContractTerminationDialog.tsx`).
- **Dane „archiwum" już istnieją:** `historical.placements` = zakończone kontrakty z `end_date` + `terminated_at` + reason + revenue (`clients.py:384-421`). Dziś pod „Historia → Placementy", **nie** jako zakładka „Archiwum konsultantów".
- **Status zamówienia `completed` istnieje**, `Zakończeni` istnieje już jako **piguła-filtr** (client-side, po statusie kontraktu, `OrdersAndContractsTab.tsx:96-100`). Nie ma dziś przycisku „Zakończ" na poziomie zamówienia.
- **Model czysto reprezentuje kontraktora z 2 projektami u 2 klientów:** `Contract` jest per (candidate, client, job); jeden kandydat = N kontraktów. „Zakończ jeden projekt" = zakończ jeden `Contract` + jego zamówienia. Ale **nie ma jeszcze** widoku per-kandydat listującego wszystkie jego aktywne kontrakty (potrzebny do wyboru w kroku 4).
- **Luka stawki kosztowej na profilu:** `ActiveConsultantItem` ma przychód+marżę, ale **nie ma kosztu** (`client_profile.py:66-78`). Kolumna marży w kroku 1 wymaga rozszerzenia endpointu profilu o `rate_candidate` (dane istnieją na kontrakcie, tylko nie wystawione).

### ⚠️ Dwa błędy w kadrowaniu ticketa
1. **Screenshot to MAKIETA, nie stan appki.** Dziś **nie ma** zakładki „Archiwum konsultantów" (dane są pod „Historia → Placementy") ani kolumny kosztu w „Obecni konsultanci". Krok 1/2 to realny build FE, nie „już jest".
2. **Sprzeczność w kroku 1:** ticket mówi „w Obecni konsultanci NIE ma akcji Zakończ", a **dziś jest** przycisk „Zakończ" tam (`ProfileTab.tsx:192-200`). Implementacja „jak napisano" = **usunięcie** tego przycisku i przeniesienie akcji do Zamówień/Kontraktów.

### Sedno: jedyna naprawdę nowa rzecz to dwukierunkowy sync
`terminate_contract` **nie dotyka** `client_orders`, a `update_order` **nie dotyka** kontraktu. Dwa osobne demony dzienne skanują osobne kolumny `end_date` (`contract_alerts.py:52-75` dla kontraktu, `dl_portal_expiry_scanner.py:96-118` dla zamówienia) i nigdy się nie krzyżują.

Potrzebny **jeden współdzielony serwis**, wołany z Zamówień **i** z Kontraktów, który przy jednej dacie: (a) ustawia kontrakt `terminated_at`/`end_date`/status, (b) ustawia pasujące zamówienia `end_date` + `status=completed`, **idempotentnie** względem obu demonów, i **jawnie nie dotyka** `B2BGeneratedContract` (dzięki temu krok 6 „B2B bez zmian" jest spełniony — dziś jest spełniony tylko dlatego, że `terminate_contract` ignoruje B2B).

### Ryzyka integralności (do zaprojektowania przed kodem)
- **Wiele otwartych zamówień na 1 kontrakcie** (draft+active+przyszłe przedłużenie): kończymy **wszystkie** nieterminalne, czy tylko aktywne? Zamknięcie tylko aktywnego zostawia „sieroty".
- **Data przyszła:** terminacja świadomie trzyma kontrakt active/ending do nadejścia daty (`contracts.py:2891-2897`). Jeśli zamówienie od razu leci na `completed`, przez okno przejściowe strony się nie zgadzają (zamówienie completed, ale konsultant nadal „Obecni"). Sync powinien odwzorować semantykę przyszłej daty też na zamówieniu.
- **Reason vs sama data:** endpoint terminacji **wymaga** `termination_reason` + lessons, a ticket mówi tylko o „Data zakończenia projektu". Doprecyzuj, czy z Zamówień/Kontraktów zbieramy też powód.

### Rekomendacja
**Idź w to — to głównie podpinanie istniejących klocków + jeden nowy serwis.** Kolejność: (1) zbuduj współdzielony serwis sync Contract↔Order (z decyzją o wielu zamówieniach i dacie przyszłej), (2) rozszerz endpoint profilu o koszt (krok 1), (3) wystaw `historical.placements` jako zakładkę „Archiwum konsultantów" (krok 2, głównie restrukturyzacja FE), (4) dołóż przyciski „Zakończ" (Zamówienia) i „Zakończ projekt" + picker wielu projektów (Kontrakty). **Bez migracji.** Najpierw potwierdź z pracownikiem, że przycisk „Zakończ" ma zniknąć z „Obecni konsultanci".

### Do doprecyzowania
- Wiele otwartych zamówień: kończyć wszystkie czy tylko aktywne?
- Zamówienie od razu `completed`, czy odwzorować semantykę daty przyszłej?
- „Profil kontraktora" z kroku 4 = strona `/contracts/[id]` (ma już terminację) czy widok per-kandydat (nie istnieje)?
- Czy „Archiwum konsultantów" zastępuje „Historia → Placementy"? Gdzie trafiają „Przegrane/lost jobs"?
- Czy z Zamówień/Kontraktów wymagamy `termination_reason` + lessons, czy tylko datę?

---

## Sugerowana kolejność wykonania

| Faza | Co | Nakład | Dlaczego teraz |
|------|-----|--------|----------------|
| **A — szybkie wygrane** | #2 wyszukiwarka; #4 pkt 2+3 (usuń „Contract #" i rekrutację); #1 bug 4 (nazwa → `display_name`) | S każdy | Niskie ryzyko, jasne, realna wartość. Bug 4 zamyka realny bug bez migracji. |
| **B — weryfikacja + doprecyzowanie** | #4 pkt 1 (potwierdź przeciw screenshotowi — pewnie już zrobione); reprodukcja #1 bug 2/3; ustal intencję sekcji vs status | — | Tanie ubezpieczenie przed budowaniem czegoś, co istnieje albo opiera się na błędnym modelu. |
| **C — porządki fundamentu** | Scal duplikaty e-Zdrowia (115/5257); zamień bramkowanie po nazwie na flagę/`client_id`; ustal wspólną regułę „reprezentatywnego zamówienia" | M | Odblokowuje #3 i część #4/#5 bez zakodowania długu. |
| **D — większe buildy** | #5 serwis sync + 3 powierzchnie UI; #3 `project_part` end-to-end (migracja + entrypoint mirror) | L każdy | Po fazie C mają czysty fundament. |
| **odrzucone** | #1 masowa naprawa statusów | — | Szkodliwe (Mina 1). Jeśli data-fix, celuj w `scope.category`. |

---

## Pytania do pracownika (skonsolidowane)

1. **#1:** Czy chodzi o to, by *status* fizycznie sterował sekcjami (przebudowa), czy o UI do ręcznego przenoszenia klienta między sekcjami (endpoint już istnieje)? Czy status ma być edytowalny na klientach z Traffita (wtedy trzeba ochrony przed cofnięciem)?
2. **#1 bug 4:** Edytujemy jedno pole „Nazwa firmy" (mapowane na `display_name`), czy dodajemy osobne „Nazwa wyświetlana" obok nazwy prawnej/z Traffita?
3. **#2:** „Numer zamówienia" = wpisywany numer PO (`title`) i/lub „Contract {id}"? „Imię/nazwisko" = konsultant (nie firma)?
4. **#3:** Które zamówienie napędza filtr części przy przedłużeniach? Usunięcie „Otwartych rekrutacji" ma być u **wszystkich** klientów? Czym jest „formularz uzupełniania draftu"?
5. **#4:** Stawka przychodowa na **każdym** wierszu (też historia/przyszłe), czy tylko tam gdzie jest zamówienie? Kontrakt bez zamówienia — auto-draft czy pomijamy pole?
6. **#5:** Kończyć wszystkie zamówienia kontraktu czy tylko aktywne? „Zakończ" ma zniknąć z „Obecni konsultanci"? Zbieramy powód zakończenia czy samą datę? „Profil kontraktora" = `/contracts/[id]` czy nowy widok per-kandydat?

---

*Analiza oparta na 6 równoległych agentach czytających żywy kod (backend `FastAPI` + frontend `Next.js`), 157 wywołań narzędzi, każdy wniosek z cytatem `plik:linia`. Werdykty odzwierciedlają stan `main` w worktree `klienci-status-bugs-ecae8b`.*
