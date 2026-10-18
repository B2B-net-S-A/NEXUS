# „Ludzie w NEXUSIE” — dostęp, schemat, przełączenie z Compassa (16.10.2026)

Artur 16.10.2026 przyjął rekomendacje D1–D13 (raport „Ludzie w NEXUSIE”) i D2–D10
ze sprzętu recepcji. Wszystko z Compassa poza Akademią działa w NEXUSIE:
urlopy, obecność i timesheety, stawki i premie, kartoteka, wejście i odejście,
opieka nad konsultantami z mapą technologii, skrzynka administracja@, sprzęt
z protokołami. Compass zostaje z Akademią i czyta listę osób z NEXUSA.

## Główny wyłącznik programu (Artur 18.10.2026)

`HR_PROGRAM_ENABLED` (env, domyślnie `false`, zmiana tylko workflow „Coolify set
env”) zamyka cały program — kadry, czas, płace, rozliczenia, e-teczkę, umowy
z ludźmi, opiekę, sprawy, sprzęt i faktury do klientów — **dla wszystkich, także
admina**. Artur: dopóki integracje nie są dopracowane, programu nie widzi nikt;
„nie możemy deployować po prostu pustych modułów” — włączamy dopiero, gdy moduły
mają dane (import z Compassa, plików recepcji, kartotek, wzorów umów).

- Każdy router programu w `main.py` ma `dependencies=_HR_PROGRAM`
  (`app/services/hr/program.require_hr_program`): wyłączony = `404 Not Found`,
  ta sama odpowiedź co nieistniejąca trasa. Wyjątek: dwie sondy, o które pyta
  każdy ekran (`/api/hr/config`, `/api/clients/sales-invoices/module`) —
  odpowiadają „wszystko zamknięte”. Strażnik `test_hr_program_switch.py`
  sprawdza, że każda trasa programu (dziś 335) stoi za wyłącznikiem — nowy
  router programu bez niego = czerwony test.
- Podgląd admina przy wyłączonym module (`hr.modules.module_open_for`,
  `client_invoicing.settings.open_for`, `hr.agreements.open_for`) działa tylko
  przy włączonym programie.
- Front czyta `program` z `/api/hr/config` (`useHrProgram`): `HrConfigGate`
  pokazuje „Nie znaleziono”, menu i kafelki są puste, Ustawienia nie mają pozycji
  z `gate.hrProgram` (Kadry, Płace, Import z Compassa), „Osoby i role” nie
  pokazują roli „Pracownik” ani grupy uprawnień „Ludzie” (chyba że ktoś już je ma),
  okno zakończenia współpracy nie ma „Zwrotu sprzętu”, kontrakt nie ma
  „Menedżera u klienta”.
- Wyłączony program: pętle `hr_loops` nie startują, dostępność nie przechodzi na
  urlopy NEXUSA, kategoria i mail „Czas i ludzie” znikają z ustawień powiadomień,
  zakresy kluczy API `people_roster:read`, `absences:read`, `equipment:read`
  znikają z pickera.
- Testy backendu działają przy włączonym programie (autouse w `conftest.py`),
  stos E2E też (`docker-compose.e2e.yml`).

## Dostęp

- **Bez sekcji produktu.** Moduł kadrowy nie ma sekcji w `section_permissions`
  (sekcje opisują pracę rekrutacyjną). Dostęp = kartoteka (`employee_profiles`,
  status ≠ `exited`) LUB uprawnienie z grupy „Ludzie” LUB admin, plus przełącznik
  modułu. Bramki tras w `app/api/hr_gates.py`, nazwy fabryk zaczynają się od
  `require_hr_` — test kontraktu tras i test sufitu sekcji
  (`test_section_ceiling_contract.py`) rozpoznają je jako bramki. Nowa trasa HR
  bez bramki `require_hr_*` = czerwony test.
- **Cztery uprawnienia** na końcu katalogu: `people_admin` „Kadry”, `payroll`
  „Płace” (Finanse z roli), `equipment` „Sprzęt” (osobno od Kadr, D13), `cases`
  „Sprawy” (TCM z roli). Admin ma wszystkie.
- **Rola „Pracownik” (`employee`) jest wyłączna**: widzi „Mój czas”, „Ludzie”,
  Pomoc i Ustawienia; po logowaniu ląduje na `/my-time`. Osoba z inną rolą
  dostaje „Mój czas” przez wiersz kartoteki, nie przez drugą rolę.
- **D6 — rodzaj nieobecności widzą tylko osoba, jej przełożony, Kadry i admin.**
  Zespół, kalendarz, plakietka, powiadomienie i mail zastępcy, Outlook i Teams widzą
  „nieobecny”. Każde nowe miejsce, które pokazuje nieobecność, bierze dane
  z `app/services/hr/absence.py` (odczyty bez rodzaju), a nie z `leave_requests`.
- **Przełożony nie widzi stawek ani kwot** (D2) — godziny i premie zespołu tak.
- Ślad wrażliwych zapisów: `app/services/hr/audit.record(...)` z `sensitivity`
  `health` (L4) albo `payroll` (kwoty). Kwot nie ma w `critical_events` ani logach.

## API v1 i Jarvis

- Zakresy kluczy `absences:read` (kto i kiedy, bez rodzaju) i `equipment:read`
  (wydania i zwroty, bez wartości i numerów S/N/IMEI). Trasy `/api/integrations/v1/absences`
  (zakres dat ≤ 93 dni) i `/api/integrations/v1/equipment/assignments/{id}`; wyłączony moduł = 404.
- Zdarzenia `leave.approved` / `leave.cancelled` powstają ze śladu `hr_audit_events`
  (decyzje o wniosku idą warunkowym `UPDATE`, którego listener ORM nie widzi) —
  zmiana kształtu `leave_service._audit` wywraca zdarzenia. `equipment.issued` /
  `equipment.returned` tylko dla wydań z protokołem (import arkusza = stan początkowy).
- Narzędzia Jarvisa dla HR są tylko do odczytu, mają `hr_module` (i ewentualnie
  `any_permission`); `tools_for_user(sekcje, permissions=, hr_modules=)` dostaje moduły
  otwarte dla osoby. Do modelu nie trafia rodzaj nieobecności (także przy własnym
  wniosku — L4 to dane o zdrowiu), notatki, kwoty płac, wartości sprzętu ani S/N.

## Pulpit i Ustawienia → Płace (17.10.2026)

- **Cztery kafelki pulpitu** w kategorii „Czas i ludzie”: `hr_substitution`
  „W zastępstwie”, `hr_my_time` „Mój czas”, `hr_approvals` „Do akceptacji”,
  `equipment_tasks` „Sprzęt do zrobienia” (cztery miejsca jak każdy kafelek:
  `TileType`, `TILE_TYPES`, katalog, `TileContent`). Moduł, kartotekę i rolę
  przełożonego zna dopiero `/api/hr/config`, więc rozstrzyga je jedna funkcja
  `hrTileGate` (`lib/dashboard-tiles/catalog.ts`) — w katalogu, w układzie roli
  i w zapisanym kafelku (`HrTileGate`). Wyłączony moduł = kafelka nie ma
  w katalogu ani w układzie roli (a nie „Brak dostępu”); zapisany wcześniej
  mówi zdaniem, że moduł jest wyłączony.
- **„W zastępstwie”** czyta `GET /api/hr/dashboard/substitution`
  (`services/hr/substitution_summary.py`): wyłącznie delegacje silnika
  zastępstw (`workforce_context`) i to, co silnik już przekazał — rekrutacje
  nieobecnego (Rekruter bez uśpienia albo DL, jak „Moje”), jego rozmowy
  u klienta do końca zastępstwa, jego otwarte procesy. Przeglądu DL przed
  wysłaniem CV nie obiecuje, bo `board_tasks.reviews_as_dl` nie idzie za
  zastępstwem. Ostrzeżenie `substitute_absent` widzą wpisany zastępca
  i przełożony nieobecnego; bez rodzaju nieobecności (D6).
- **„Mój czas”** i **„Sprzęt do zrobienia”** czytają trasy swoich ekranów
  (te same klucze zapytań), **„Do akceptacji”** — `GET /api/hr/counts`, czyli
  tę samą liczbę co zakładka „Akceptacje”. Awaria to blok błędu, nigdy „0”.
- Układ roli: „Pracownik” dostaje „Mój czas” (konto wyłącznie z tą rolą
  i tak ląduje na `/my-time`), osoba z uprawnieniem „Sprzęt” — „Sprzęt do
  zrobienia” na końcu układu (admin, który ma je z urzędu, nie). Reszta do
  wyboru w „Dodaj kafelek”.
- **Reguły premii są w Ustawienia → Zespół i dostęp → Płace**
  (`/settings/payroll`, pozycja `payroll` w `settings-registry`, bramka
  uprawnienia „Płace”). „Kadry” mają tylko drogowskaz — osoba z samymi
  „Płacami” (Finanse) do „Kadr” nie wchodzi.

## Struktura i „Mój zespół” (etap 2, D4–D7, 17.10.2026)

- **„Ludzie → Struktura”** (`/people/structure`, `api/hr_structure.py`,
  `services/hr/structure.py`, bramka `require_hr_people_admin` — Kadry i admin,
  bez czekania na przełącznik modułu jak trasy Kadr). Drzewo z kartotek
  (status ≠ `exited`), najpierw po **pionie**: kartoteka ma `division`
  (`front_office` — sprzedaż i rekrutacja do podpisania zamówienia,
  `back_office` — opieka, administracja, rozliczenia; decyzja Artura 17.10),
  head pionu w `app_settings['hr_divisions']` (`PUT /divisions`, aktywne
  konto). W pionie drzewo po przełożonym; osobno „Bez przełożonego” (bez
  przełożonego i bez podwładnych, poza headem) i przełożony, który odszedł.
- **Zmiana przełożonego dla wielu osób naraz działa OD RAZU** — bez daty „od
  kiedy” z makiety, bo kartoteka nie ma harmonogramu zmian. Wnioski urlopowe
  i timesheety w toku przechodzą do nowego przełożonego: akceptującego liczy
  się w chwili decyzji (`leave_service._decision_scope`,
  `time_access.Actor.can_approve`). Reguły jak w kartotece dla całego zbioru
  (`people.validate_managers`: nie sam sobie, aktywne konto, bez pętli) pod
  `pg_advisory_xact_lock` (kartoteka, Struktura i przekazanie biorą tę samą
  blokadę); ślad `profile_updated` per osoba (`source: structure`).
- **Podpowiedzi bez zapisu**: osoba w pionie z headem i bez przełożonego —
  „przełożony = head pionu”; rozjazd z Microsoft 365 (D7) — dzienna
  synchronizacja profili czyta `/users/{upn}/manager` i zapisuje tylko
  `m365_manager_upn` (404 = bez przełożonego, `manager_user_id` nigdy). Oba
  mają „Przyjmij” = zwykła zmiana przełożonego.
- **Koordynator czy przełożony**: przy B2B i zleceniu ekrany mówią
  „koordynator”, przy UoP „przełożony” (`managerWords` w `lib/api/hr-structure.ts`) —
  tylko etykieta, pole to dalej `manager_user_id`. Przy osobie forma (UoP /
  B2B / Zlecenie).
- **„Ludzie → Mój zespół”** (`/people/team`, `api/hr_team.py`,
  `services/hr/team.py`, bramka `require_hr_team_reader`: moduł „Ludzie” +
  podwładni z kartoteką albo Kadry/admin). Wiersz na bezpośredniego
  podwładnego, złożony z istniejących odczytów: dziś (z rodzajem — przełożony
  jest w kręgu D6), nieobecności (pula z `balance_payload` tylko u osób
  z pulą, u reszty zaplanowane dni — prawie wszyscy są na B2B albo zleceniu),
  miesiąc z `team_queue`, premie w drodze (propozycje i przyznane w otwartych
  miesiącach) z kwotą, **bez stawek i bez `rule_snapshot`** (D2, test
  `test_team_response_never_carries_rates_or_margin`), sprawy do decyzji.
  Propozycje premii tylko do wiadomości — decydują Płace. Kadry i admin
  oglądają zespół dowolnego przełożonego (`?manager=`, link „Zespół”
  w Strukturze); kwoty premii widzi wtedy tylko osoba z Płacami.
  `leave.has_paid_pool` (pula > 0 — to samo co w `GET /api/hr/leave/balance`)
  decyduje we froncie o „zostało”; `has_pool` zostaje (17.10.2026).

## Moduły ciemne

- `app_settings['hr_modules']` = `people, leave, time, payroll, lifecycle, care,
  cases, equipment`. Brak wiersza albo nieznany klucz = wyłączony. Wyłączony
  moduł odpowiada 404 (`MODULE_DISABLED_DETAIL`) każdemu poza adminem; admin
  widzi ekrany, żeby przygotować import. Przełącza admin w Ustawienia → Kadry
  → „Moduły”, bez wdrożenia.
- Źródło urlopów dla zastępstw, dni pracy i tempa celów:
  `app_settings['hr_availability_source']` = `compass | local`
  (`app/services/hr/availability_local.py`, cache procesu 60 s). Przełączać na
  `local` dopiero po imporcie kartotek i urlopów — wcześniej snapshot byłby pusty
  i zastępcy straciliby pracę osób na urlopie.
- Pętle HR (`app/tasks/hr_loops.py`, `run_periodic`) działają, gdy
  `HR_LOOPS_ENABLED=true`; każda ma heartbeat z literalną nazwą (test
  `test_loop_heartbeat`) i rezerwację przebiegu w `hr_job_runs`, więc restart
  przy nocnym wdrożeniu nie robi niczego dwa razy.
- Powiadomienia HR (`hr_*`, `admin_case_assigned`, `equipment_*`,
  `care_front_office_handoff`) są osobiste: widoczne bez sekcji, kategoria
  „Czas i ludzie”. `care_contact_due` należy do sekcji Delivery. **Dzwonka nie ma** (pasek z ikonami jednego tematu,
  `powiadomienia/pasek-tematy-bez-dzwonka.md`): typy HR mają temat `other`
  (poza `care_front_office_handoff` — temat „Rekrutacje” z dymkiem),
  czyli dymek dla zalogowanych, mail i liczniki na ekranach — bez listy i bez
  nowej ikony w pasku.
- **Mail „Czas i ludzie” (`hr_people`, 17.10.2026)** — kolejka maili natychmiast
  (`tasks/notification_email_outbox.py`), typy `notification_delivery.HR_MAIL_TYPES`:
  wniosek do decyzji, decyzja i przeliczenie dni, anulowana i zgłoszona
  nieobecność, zastępstwo, timesheet zaakceptowany/zwrócony/cofnięty
  i przypomnienie o wysłaniu, timesheet wysłany do akceptacji (`hr_timesheet_submitted`,
  18.10.2026 — jak mail Compassa do akceptującego), przekazana praca, zadania wejścia i odejścia,
  sprawa administracja@, zadania sprzętu, podpisany protokół, konsultant
  przekazany do front office, komunikat do konsultantów (do zatwierdzenia,
  zatwierdzony, zwrócony, niedoręczony — `care_announcement`). Bez maila: premie
  i stawki (kwoty), `care_contact_due`. Treść składa `services/hr/hr_mail.py`:
  tytuł i treść powiadomienia przechodzą tylko bez rodzaju nieobecności i kwot,
  inaczej stałe zdanie typu („nieobecność”, nie „L4” — także dla przełożonego
  i Kadr, bo mail wychodzi poza aplikację); tytuł sprawy i uwagi przy zwrocie
  timesheetu nie idą mailem nigdy. Nowy typ HR = wpis w `HR_MAIL_TYPES` albo
  świadomie w liście „bez maila” w `tests/test_hr_mail.py`, plus zdanie
  w `hr_mail.FALLBACK`. Rodzaj jest za polityką z Ustawień → Powiadomienia
  (domyślnie wyłączony, włącza admin) i własnym wyłącznikiem w „Moich
  powiadomieniach” (`APPLIES`: konto, dla którego działa któryś moduł „Ludzi”;
  admin zawsze). Wyciszona kategoria „Czas i ludzie” zatrzymuje też mail.
- **Liczniki zakładek „Ludzi”** — `GET /api/hr/counts` (`api/hr_counts.py`,
  bramka `require_hr_config_reader`): `approvals` = wnioski
  (`leave_service.pending_queue`) + wysłane timesheety z każdego miesiąca,
  które osoba może zaakceptować (`time_access.Actor.can_approve`), `cases` =
  jej otwarte sprawy administracja@ (tylko z dostępem do Spraw). `null` =
  nie dotyczy; awaria to brak liczby w zakładce, nigdy „0”
  (`PeopleSectionNav`, `sectionCount`). Zmiana zakresu akceptujących = ta sama
  funkcja liczy ekran i licznik.

## Wspólne mechanizmy — nie pisz kopii (audyt 17.10.2026)

Audyt jakości 17.10 znalazł te same kawałki skopiowane w 3–16 miejscach; po
porządkach każdy ma jedno źródło. Nowy kod modułów „Ludzi” używa tych, a nie
własnych wersji:
- rezerwacja przebiegu w tle: `services/hr/job_runs.py` (`claim`, `finish`,
  `mark_once` dla „raz na osobę i miesiąc”); wyłączona pętla albo moduł zwraca
  `{"status": "disabled"}`;
- powiadomienie kilku osób: `services/hr/notify.notify_each` (savepoint na
  odbiorcę, awaria jednego nie cofa reszty, log tylko z identyfikatorami);
- bramka modułu w trasie: `hr_gates.ensure_module(db, user, HrModule.x)`;
- przełożony/koordynator: `services/hr/recipients.supervisor_of`;
- kalendarz firmy (święta + dni wolne firmy): `services/hr/calendar.load_calendar`
  / `WorkCalendar` — urlopy, czas pracy i termin premii liczą tym samym;
  dzień dla podanej chwili: `scheduling.business_date(moment)`;
- słowa według formy współpracy i nazwy rodzajów nieobecności:
  `services/hr/employment_terms.py`, `leave_policy.LEAVE_TYPE_LABELS`
  (lustra we froncie pilnują testy `test_hr_employment_terms_mirror.py`,
  `test_hr_leave_labels_mirror.py`);
- statusy zatrudnienia: `EmploymentType` / `EmploymentStatus` /
  `WORKING_STATUSES` z `hr_foundation_schema.py`.

Kolejka maili natychmiast przegląda kolejne strony kursorem, aż spróbuje 50
wysyłek — wiersze, których odbiorca nie dostaje (wyciszenie), nie blokują już
reszty (`tasks/notification_email_outbox.py`, 17.10.2026).

## Schemat

- Każdy moduł ma `app/services/<moduł>_schema.py` (`TABLE_DDL, COLUMN_DDL,
  INDEX_DDL, CONSTRAINT_DDL, DATA_DDL, TABLES, DOWNGRADE_DDL, ALL_DDL`), który czyta
  jego migracja i — przez `app/services/hr_schema_bundle.py` — `entrypoint.sh`.
  Łańcuch: `0455_hr_foundation → 0456_hr_access → 0457_hr_notifications →
  0458_hr_leave → 0459_hr_time → 0460_hr_payroll → 0461_hr_lifecycle →
  0462_contract_care → 0463_admin_cases → 0464_equipment → 0465_equipment_extras →
  0466_care_announcements`. Etap 3 dopisał tabele w miejscu do 0461, 0462 i 0464
  (rytm kontaktu, pakiet klienta, wzory protokołów, maile powitalne).
  Nowy moduł = nowy plik schematu + wpis w `MODULES` agregatora + wiersz w
  `tests/test_hr_module_chain.py`. Testy szukają migracji po sufiksie, nie po
  numerze (po synchronizacji z mainem numery się przesuwają — `rechain_migration.py`).
- VARCHAR + CHECK zamiast nowych typów enum; nowe wartości tylko w `userrole`
  (`employee`) i `notificationtype`, literalnie w `_ENUM_STATEMENTS` entrypointu.
  Nowy typ HR (np. `hr_leave_conflict`, etap 2 D5) = `hr_notification_schema`,
  enum w `models/notification.py`, linia w entrypoincie, kategoria „Czas i
  ludzie”, `HR_MAIL_TYPES` + zdanie w `hr_mail.FALLBACK` (wolny tekst →
  `_FREE_TEXT_TYPES`); temat `other` przypisuje się sam.
- Kartoteka (etap 2, forma współpracy): `employee_profiles` ma
  `student_contribution_exempt` / `contribution_exempt_until`
  (`ck_employee_profiles_exempt_until`) i `leave_seniority_years` /
  `zus_certificate_received_on` (`ck_employee_profiles_seniority` 0–60) —
  dopisane w miejscu do `hr_foundation_schema.py` (0455 nie jest wdrożona).
- Minimalna stawka na zleceniu (D7): `app_settings['hr_minimum_hourly_rates']`
  (`{"2025": "30.50", "2026": "31.40"}`, brak wpisu = te wartości), edycja
  w Ustawienia → Płace (`GET/PUT /api/hr/payroll/settings/minimum-rates`,
  bramka Płace). Stawka osoby na zleceniu poniżej minimum roku `effective_from`
  = 422 „Minimalna stawka na zleceniu w RRRR to X zł/h brutto.”; rok bez
  minimum albo inna waluta = zapis z `warning`. Nowy rok dopisują Płace bez
  wdrożenia. Stawka z poprzedniego roku (też po usunięciu kroku nowego roku)
  poniżej minimum roku miesiąca = ostrzeżenie `below_minimum_rate` w raporcie
  miesiąca płac do potwierdzenia przed zamknięciem, bez stawek osób (17.10.2026).
- Każda instrukcja idempotentna — entrypoint wykonuje je przy każdym starcie.
  Zmiana istniejącego CHECK-a idzie blokiem `DO`, który podmienia go tylko przy
  starej definicji (wzór: posiadacz sprzętu w `equipment_extras_schema.py`).

## Import z Compassa

- Paczka `compass-bundle` v1 (specyfikacja kolumn:
  `app/services/hr/compass_import/BUNDLE.md`) — same `SELECT`-y po stronie
  Compassa, tylko kolumny, których import potrzebuje. Plik leży poza repo,
  z dostępem tylko dla importującego, i jest kasowany po imporcie.
- `scripts/hr_compass_import.py --bundle … --module …` = plan na sucho z raportem
  (liczby i identyfikatory, bez imion i kwot); `--apply <batch_id>` zapisuje
  tę samą paczkę (`bundle_sha256` partii) po przeliczeniu planu na świeżych
  danych. Mapa id (`hr_import_id_map`) robi z drugiego zapisu same „bez zmian”.
  Kolejność: `profiles → leave → time → payroll → lifecycle → cases → care`.
- **Ekran Ustawienia → „Import z Compassa”** (`/settings/hr-import`,
  `api/hr_import.py`, prefiks `/api/hr/admin/import`, 17.10.2026) — ten sam
  przebieg dla wszystkich modułów naraz, bez wchodzenia do kontenera. Plik
  `.json` albo `.zip` z jednym `.json` (limit 25 MB pliku, 64 MB po
  rozpakowaniu, archiwum sprawdzane po nagłówkach przed rozpakowaniem).
  Na sucho sprawdzają Kadry (`people_admin`) i admin; **zapisuje tylko admin**
  (hurtem dane płacowe i zdrowotne). Na sucho moduły liczą się łańcuchem
  w kolejności zależności — próbny zapis każdego idzie do SAVEPOINT-u
  i na końcu jest cofany — więc urlopy, czas i płace przy pierwszym imporcie
  nie wyglądają jak „osoba bez kartoteki”. Zapis wymaga SHA-256 z raportu,
  sprawdzenia młodszego niż 24 h i braku innego zapisu po nim (też z CLI);
  idzie w jednej transakcji, a gdy paczka zakłada nowe kartoteki, inne moduły
  bez kartotek są odrzucane (422). Import na sucho i zapis biorą
  `pg_try_advisory_xact_lock` — drugi równoległy dostaje 409.
- **Co zostaje po zapisie:** surowa paczka leży w `hr_import_uploads.bundle`
  tylko do zapisu albo 24 h (CHECK: plik tylko w stanie `dry_run`); po zapisie,
  wygaśnięciu albo zapisie innej paczki (`superseded`) zostają SHA-256, liczby
  per moduł, kto i kiedy (historia na ekranie, `GET /batches`) oraz partie
  modułów w `hr_import_batches`. Raport i logi niosą liczby i identyfikatory
  Compassa; e-mail osoby przy pozycji do wyjaśnienia dostaje wyłącznie admin,
  w odpowiedzi na sucho. Ślad w `hr_audit_events` (`compass_import_dry_run`,
  `compass_import_apply`). Wygasłe paczki sprząta kolejny przebieg na sucho
  (`purge_expired_uploads`).
- Błędy Compassa naprawiamy, nie przenosimy — każdy ma test w module
  (pula urlopu przez Nowy Rok, pula B2B liczona dniami płatnymi, samozatwierdzanie,
  placement poza zakresem managera, wektory `pdf_hash` z kodu Compassa).

## Przełączenie

Krok po kroku: `ludzie/runbook-przelaczenia-z-compassa.md`.

Kolejność ma znaczenie: najpierw Compass przestaje pisać (moduł tylko do odczytu,
wyłączony `oof-reconcile`), potem eksport i import na sucho z raportem do Artura,
zapis po OK, M365 `live` na jednej skrzynce z listy, potem dla wszystkich, źródło
dostępności `local`, włączenie modułów. Czas pracy od 1. dnia miesiąca, płace po
miesiącu liczonym równolegle w obu systemach. Danych Compassa nie kasujemy.

## E-teczka — dokumenty osoby (etap 5, E4, 18.10.2026)

- Tabela `hr_documents` (migracja `0469_hr_documents`). Rodzaje: umowa, aneks, oświadczenie,
  zaświadczenie, protokół, potwierdzenie nieobecności, inne (`documents_rules.KIND_LABELS`,
  lustro we froncie). Potwierdzenie nieobecności bywa załącznikiem wniosku urlopowego
  (`leave_request_id`, 0473) — reguły w `urlopy-czas-place-wejscie-odejscie.md`.
- Plik w wolumenie uploadów `hr_documents/<osoba>/<sha256>.<rozszerzenie>`; tylko PDF, DOCX bez
  makr, JPG i PNG, typ rozpoznany z treści; w przeglądarce otwierają się tylko typy bezpieczne.
- Kadry i admin widzą wszystko; osoba, Płace i recepcja — dokumenty ze swoim znacznikiem;
  przełożony nie widzi niczego z e-teczki (404). Protokoły sprzętu to odnośniki do modułu sprzętu.
- Dokument z generatora umów wchodzi tylko przez `documents.attach_generated(source="agreement")`
  (powtórne wołanie nie dubluje); ręcznie się go nie usuwa (409).
- Oświadczenie studenta (`purpose=student_status`, wymaga „ważny do”) na zleceniu wpisuje datę
  w `contribution_exempt_until`; przypomnienie dla Płac daje istniejąca pętla `student_reminders`.
- Retencja: lata na rodzaj w `app_settings['hr_document_retention']` (domyślnie 10, „inne” 5 —
  do potwierdzenia z Kadrami), liczone od końca roku ostatniego dnia pracy. Nic nie kasuje się
  samo: lista w Ustawienia → Kadry, usunięcie z zaznaczeniem i potwierdzeniem; plik znika,
  wiersz zostaje jako ślad. PESEL-u i numeru dowodu nie ma w żadnym polu.

## Umowy z ludźmi (etap 5, E5, 18.10.2026)

- Moduł za przełącznikiem `app_settings['hr_agreements']` (domyślnie wyłączony, włącza admin,
  działa przy włączonym module „Ludzie”). Migracja `0470_hr_agreements` (wzory, wersje, umowy;
  typ powiadomienia `hr_agreement_update` do osoby z Kadr, bez kwot).
- Treść prawną daje wzór DOCX od Kadr: pola z `agreements_templates.FIELDS`, sandbox wzorów
  protokołów sprzętu; nowy plik = nowa wersja, umowa pamięta swoją. Żadnego pola PESEL ani dowodu.
- Stany: szkic, wysłana, podpisana, odrzucona, anulowana; wycofanie albo termin w Autenti cofa do
  szkicu z powodem. Proces Autenti w `hr_agreements` (nie w `document_signatures`): pętla
  `hr_agreements_signing` co 15 minut (nie startuje bez `AUTENTI_ENABLED`) i webhook Autenti.
  Podpis ręczny wymaga skanu, daty i powodu w śladzie. Nikt nie przygotowuje umowy ze sobą.
- Po podpisie w jednej transakcji i raz: stawka od 1. dnia miesiąca (`payroll_rates.set_rate`),
  forma i potwierdzanie godzin (`people.update_profile`; aneks zmienia tylko stawkę), dokument
  w e-teczce, dla UoP i zlecenia znacznik `symfonia_pending`. Nieudane przepisanie zostawia umowę
  podpisaną z `apply_error` i przyciskiem „Przepisz ponownie”. Minimalna stawka zlecenia z D7.
