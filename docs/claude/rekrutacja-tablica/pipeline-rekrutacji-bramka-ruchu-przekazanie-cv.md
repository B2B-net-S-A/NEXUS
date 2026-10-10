# Pipeline rekrutacji — bramka ruchu, przekazanie CV, spójność ekranów (11.09.2026)

Poprawki z przeglądu kodu spoza Codexa. Wspólny mianownik: ekran mówił co
innego niż serwer albo nadpisywał cudzą pracę.

- **Frontendowa bramka ruchu to WYŁĄCZNIE `moveBlockedReason`**
  (`lib/pipeline-flow.ts`). **Od 17.09.2026 blokuje tylko `readOnly`** — karta
  „Oczekuje” nie powstaje, a weto HM jest ostrzeżeniem serwera (sekcja
  „Kanban bez bramek”); akapit niżej opisuje stan z 11.09.
  Były cztery kopie tej reguły (w tym `InterviewDecisionDock`) i żadna nie
  zgadzała się z serwerem. Nie dokładaj kopii — przeciąganie, przyciski i doki
  wołają tę jedną funkcję. **Główny przycisk „dalej” w doku
  (`primaryForwardMove`) zatrzymuje się na pierwszym etapie objętym wetem** i
  pokazuje go wyłączonego z powodem — wcześniej przeskakiwał „CV Wysłane” na
  następny etap (w „Default B2B” to „Preparation Meeting”, spotkanie u klienta,
  którego serwerowe weto — kluczowane legacy enumem — nie zna).
- **Przekazanie CV klientowi: ruch → link → stawka.** Odmowa ruchu nie tworzy
  linku. Link celuje w etap SPRZED ruchu (tam leży brandowane CV); gdy link padnie
  po udanym ruchu, workbench pokazuje „Utwórz link ponownie”. Brak odpowiedzi
  albo 5xx przy ruchu to „nie wiadomo, czy ruch się zapisał — odśwież kartę”,
  nie „nic nie zostało zmienione” (`isDefiniteRefusal` — tylko 4xx jest pewną
  odmową); ponowienie mogłoby dodać drugi wpis „CV Wysłane”.
- **Link jednorazowy tylko przez `OneTimeLinkField` + wynik `lib/clipboard.ts`** —
  URL zostaje na ekranie, a toast „skopiowano” pojawia się tylko po udanym
  kopiowaniu (link Championa, interview z klientem). Link przeżywa przemontowanie
  karty po zapisie werdyktu.
- **Po ruchu kanban unieważnia OBA klucze** (`["kanban", String(id)]`
  i `["kanban", id]`; przy operacjach zbiorczych raz, po pętli). Zapisy Championa
  idą przez `invalidateChampionDependents` (`lib/champion-cache.ts`), który
  odświeża też `["job-readiness", id]`. Edycja samej rekrutacji (tytuł, klient,
  rubryki) jeszcze tego nie robi — znany dług.
- **Dok kandydata porównuje stawkę po przeliczeniu na miesięczną**
  (`normalizeRateToMonthly`); waluta inna niż PLN albo nieznana jednostka =
  „nie do porównania”, nie fałszywe „powyżej widełek”.
- **Werdykt HM** (`api/hiring_manager_feedback.py`): odczyt za
  `ensure_job_read_access` (także Finanse); cudzy werdykt nadpisuje autor,
  KAŻDY Delivery Lead (DL omija członkostwo w zespole), Head of Recruitment
  albo admin — inaczej 403
  z nazwiskiem autora. GET zwraca `{can_record, items}`: `can_record` liczy
  DOKŁADNIE te same warunki co POST (impersonacja, zapis sekcji pipeline, role
  RecruiterPlus, członkostwo z obejściem DL), a formularz renderuje się tylko przy
  `can_record === true` — Finanse spoza zespołu widzą werdykt tylko do odczytu
  zamiast przycisku kończącego się 403. Wiersze niosą `author_id`,
  `author_name`, `can_edit`. HoR od 17.09.2026 zapisuje i nadpisuje cudze
  werdykty (decyzja Artura: parytet z rekruterem + nadzór jak DL).
- **Shortlista nie nadpisuje zmiany kolegi i nie gubi wpisanego tekstu:**
  `ServerSyncedInput` (`JobShortlist.tsx`) — wersja bazowa idzie za serwerem do
  pierwszej zmiany użytkownika, potem zamarza; brak zapisu przy niezmienionym
  blur. 409: tekst zostaje w polu; jeśli kolega zmienił INNE pole, zapis ponawia
  się raz na nowej wersji, a jeśli to samo — toast o konflikcie i przyjęcie nowej
  wersji, więc następny zapis nadpisuje świadomie. Backend najpierw sprawdza
  członkostwo w zespole, potem blokuje wiersz (`with_for_update()`) i dopiero
  wtedy porównuje wersję — dwa równoczesne zapisy nie przejdą oba, a osoba spoza
  zespołu nie założy blokady na cudzy wpis.
- **ATLAS — firmy z historii kandydata** (`api/integrations_companies.py`
  + `_past_company_predicate` w `api/candidates.py`): `via_us` =
  `placed_contract_clause()` — kontrakty `active`/`ending`/`ended` oraz
  `draft`/`ready_for_signature` z aktywnym zamówieniem u tego klienta albo
  z bieżącym etapem „hired” u niego (zatrudnienie i obsada linii MD zakładają
  kontrakt jako szkic, więc bez tego pracujący konsultant znikał z odpowiedzi).
  Aktywny konflikt = firma obecna, nieaktywny = przeszła. Data końca
  „present/current/obecnie/teraz” (`services/experience_end.py`, po przycięciu
  WSZYSTKICH białych znaków — SQL `btrim(…, E' \t\r\n')` jak Python `.strip()`)
  = praca OBECNA we wszystkich predykatach (lista kandydatów i ATLAS). Pusty
  `end` też, z jednym historycznym wyjątkiem: w filtrze „Poprzednia firma” wpis
  bez daty dalej niż na pierwszej pozycji liczy się jako przeszły. Każde zapytanie ma
  sufit 2000 WIERSZY (`truncated`) i lokalny timeout 8 s (→ 503
  `lookup_timeout`). Surowy alias idzie do `LIKE` tylko, gdy jego forma
  kanoniczna ma co najmniej 3 znaki (koniec z „IT” → `LIKE '%it%'`). Filtr listy
  `_worked_at_client_predicate` nadal liczy szkice i unieważnione kontrakty —
  znany dług.
- **Delivery Lead zakładający rekrutację staje się jej `delivery_lead_id`**
  (`job_lifecycle.create_job_core`): pierwszeństwo jawne `delivery_lead_id` >
  twórca z rolą Delivery Leada > główny DL klienta (`resolve_default_owners`,
  czyli twórca bez roli DL, np. admin). Do 08.10.2026 główny DL klienta
  wygrywał z twórcą: drugi DL tego samego klienta zakładał rekrutację, a
  przegląd DL, alerty i statystyki DL szły do głównego (4 z 62 rekrutacji
  założonych przez DL-i od 17.09). Twórca jest wpisany jak ręcznie
  (`delivery_lead_auto_filled = false`), więc nie idzie za zmianą głównego
  DL-a klienta. Otwarte rekrutacje sprzed zmiany przepina jednorazowo
  `services/job_creator_delivery_lead_repair.py` (blok
  `repair-job-creator-delivery-lead`, paragon
  `job_creator_delivery_lead_2026_10` z ID rekrutacji i poprzedniego DL-a).
  Regułę liczy JEDNA funkcja `auto_assign_owners.pick_delivery_lead` — dla
  zapisu i dla formularza: sekcja 6 `/jobs/new` pokazuje tę osobę przed
  zapisem (`NewJobDeliveryLeadField`, `GET /api/job-intake/delivery-lead?client_id=`)
  z przyciskiem „Zmień”; `POST /api/jobs` niesie `delivery_lead_id` tylko po
  ręcznym wyborze innej osoby (inaczej główny DL klienta przestałby być wpisem
  automatu). `recruiter_id`/`/claim`
  nietknięte, to zmiana ownera, nie autorstwa. `delivery_lead_job_pairs`
  zwraca `None` dla roli DL, więc bramka zakresu klienta nie gryzie własnej
  rekrutacji świeżo utworzonej bez zespołu. 403 przy próbie ustawienia widełek
  wynagrodzenia przez DL/TCM jest teraz po polsku: „Widełki wynagrodzenia może
  ustawić tylko admin lub TAC”.
- **Tworzenie rekrutacji = krótki modal + reszta w doku** (17.09.2026).
  `CreateJobModal` (`components/v2/modals/`) ma 9 pól: tytuł, klient
  (`ClientSinglePicker`), typ, opis (z „Generuj AI”), must-have, miasto, tryb,
  dni w biurze, budżet PLN/h; widełki PLN/mies. tylko dla `canManageRecruitmentBudget`
  (klucz NIEOBECNY dla DL/TCM, nie `null` — backend liczy `fields_set`). Nie
  wysyła statusu, priorytetu, deadline'u, TAC/DL/rekrutera/HM/szablonu/kategorii.
  Po zapisie ląduje na `/jobs/{id}?tab=champion` (+`&intake=1`, gdy jest opis —
  panel AI otwarty z opisem); `?tab=champion-profile` zostaje aliasem
  (`JOB_DETAIL_TAB_ALIASES` w `app/jobs/[id]/page.tsx`). Szkic formularza w `localStorage`
  (`nexus:jobDraft:v1:<userId>`), Escape przy brudnym formularzu pyta.
  `EditJobModal`/`JobFormFields` ZOSTAJĄ w `AppShell.tsx` jako pełna edycja
  (testy źródłowe czytają tam literały `FieldGroup`). TAC, DL, szablon,
  kategoria, Program/Train, priorytet i deadline edytuje `JobSettingsPanel`
  w zakładce „Zespół i ogłoszenie” Profilu Championa. Układ od
  04.10.2026 — sekcja „„Profil Championa” w czterech zakładkach”; szyna „Otwarte karty” domyślnie zwinięta
  (`nexus.jobTabsRail.collapsed.v2`). Sekcja 1 Championa startuje
  z pól rekrutacji per pole (`lib/champion-job-seed.ts`), nietknięte klucze nie
  jadą w PUT; okno „Uzgodnij profil i pola rekrutacji” dostaje widoczny `draft`
  (pusty stack + „Uzgodnij też pole” czyściłby `must_skills`).
