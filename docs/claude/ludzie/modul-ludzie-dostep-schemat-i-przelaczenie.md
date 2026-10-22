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
  „Sprawy” (TCM z roli). Admin ma wszystkie. Od 19.10.2026 rola Finanse ma też
  „Kadry” (decyzja Artura przy starcie e-teczki: na produkcji nikt poza adminami
  nie miał Kadr) — zapis w siatce ról na produkcji, domyślna siatka w kodzie bez zmian.
- **Rola „Pracownik” (`employee`) jest wyłączna**: widzi „Mój czas”, „Ludzie”,
  Pomoc i Ustawienia; po logowaniu ląduje na `/my-time`. Osoba z inną rolą
  dostaje „Mój czas” przez wiersz kartoteki, nie przez drugą rolę.
- **Pierwsze logowanie Microsoftem zakłada konto „Pracownik”** (decyzja Artura
  19.10.2026, `_provision_sso_user` w `auth_microsoft.py`), nie „Rekruter”.
  Konsultant z adresem w domenie firmy loguje się po godziny, umowę i sprzęt,
  a samo konto nie może dawać wglądu w kandydatów. Nowego rekrutera albo DL
  przestawia admin w „Osoby i role”; `profile_completed` zostaje `false`, więc
  po nadaniu roli wchodzi onboarding. Konto założone wcześniej przez admina
  zachowuje swoją rolę — logowanie tylko przypina tożsamość Microsoft. Przy
  włączonym `AAD_GROUP_RBAC_ENABLED` rolę i tak ustala grupa AAD.
- **D6 — rodzaj nieobecności widzą tylko osoba, jej przełożony, Kadry i admin.**
  Zespół, kalendarz, plakietka, powiadomienie i mail zastępcy, Outlook i Teams widzą
  „nieobecny”. Każde nowe miejsce, które pokazuje nieobecność, bierze dane
  z `app/services/hr/absence.py` (odczyty bez rodzaju), a nie z `leave_requests`.
- **Przełożony nie widzi stawek ani kwot** (D2) — godziny i premie zespołu tak.
- **„Nie sobie” w kartotece** (decyzja Artura 19.10.2026, audyt A4): Kadry i Finanse
  nie zmieniają własnej kartoteki ani puli urlopowej — `refuse_self_edit` w
  `hr_gates.py` na trasach kartoteki, puli, „składa raport godzin”, „Struktury”
  (przełożony, pion) i formy umowy; 403 z prośbą o inną osobę z Kadr albo admina.
  Admin przechodzi. Ten sam guard co przy premiach, umowach i rozliczeniach.
  „Wyrównaj wg konta” też (audyt 21.10.2026): własne id w `user_ids` = 403,
  a wyrównanie wszystkich rozjazdów (`user_ids` puste) pomija własną kartotekę
  (`account_profiles.align(skip_user_ids=…)`); admin wyrównuje także siebie.
- Ślad wrażliwych zapisów: `app/services/hr/audit.record(...)` z `sensitivity`
  `health` (L4) albo `payroll` (kwoty). Kwot nie ma w `critical_events` ani logach.

## API v1 i Jarvis

- Zakresy kluczy `absences:read` (kto i kiedy, bez rodzaju) i `equipment:read`
  (wydania i zwroty, bez wartości i numerów S/N/IMEI). Trasy `/api/integrations/v1/absences`
  (zakres dat ≤ 93 dni) i `/api/integrations/v1/equipment/assignments/{id}`; wyłączony moduł = 404.
- Zdarzenia `leave.approved` / `leave.cancelled` powstają ze śladu `hr_audit_events`
  (`leave.approved` także po edycji zatwierdzonego i po zgłoszeniu z Outlooka — upsert po `leave_request_id`)
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
  B2B / Zlecenie) — tylko dla admina i Finansów (19.10.2026, niżej).
- **Słowa zgodne z PIP na ekranach wielu osób** (decyzja Artura 21.10.2026):
  „przełożony”, „podwładni”, „pracownik”, „w pracy” i „delegacja” to język
  stosunku pracy, a inspektor PIP może sam go stwierdzić. Ekran jednej osoby
  bierze słowo z jej formy (`hr-employment-terms`); ekran wielu osób
  (Akceptacje, Katalog, Struktura, kreatory wejścia i odejścia, Zgody, Płace,
  Opieka, puste stany) mówi neutralnie: „koordynator” (też zbiór mieszany
  i pusty w `managerWords` — słowo nie zdradza formy Kadrom bez Płac),
  „osoby w zespole”, „konsultant/kontraktor” (rola `employee`, „Wpisz
  nieobecność za konsultanta/kontraktora”), „kartoteka w NEXUSIE”, „dostępny(a)”,
  „wyjazd” (litera „W” w kalendarzu), „ostatni dzień współpracy”, „Koszty
  podróży” zamiast „Delegacji”. Bez zmian: pola w bazie, słowa UoP na ekranach
  osoby na UoP, nazwa folderu „Umowy pracowników” w SharePoincie, etap
  „Zatrudniony” w rekrutacji. Nie wpisuj tych słów na sztywno w nowych ekranach.
- **„Godziny ponad 8 h” i „wynagrodzenie dodatkowe” poza UoP** (decyzja Artura
  21.10.2026): „nadgodziny” z bramką uprawnienia i „premia poza umową” to
  język Kodeksu pracy i regulaminu nagród. Słowa są w słowniku form
  (`employment_terms.py` ↔ `hr-employment-terms.ts`, klucze `overtime*`
  i `bonus*`; `BACKEND_TERMS` niesie tytuły dzwonków o premii,
  `bonus_message()` ich treść). Ekran i dzwonek jednej osoby biorą słowo z jej
  formy: wpis dnia, „Mój miesiąc”, „Wypełnij miesiąc”, podgląd raportu, PDF,
  kartoteka, karta i zakładka premii („Wynagrodzenie dodatkowe i stawka”),
  „Moje rozliczenie”, pozycja premii do faktury (`bonus_label`), opis premii ze
  zgody. Ekrany wielu osób i plik CSV godzin mówią neutralnie: „Ponad 8 h”,
  „Czego dotyczyły godziny ponad 8 h”, w Zgodach rodzaj „Wynagrodzenie
  dodatkowe” z podpowiedzią „wymaga podstawy: punkt umowy albo aneks”. Bez
  zmian: bramka `can_log_overtime` i jej pola, kategorie premii (`Premia
  rekrutera` — opis zapisany w bazie), ekrany działu Płac, eksport Symfonii
  (dotyczy UoP).
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
- **Układ z makiet (decyzje z kanwy 19.10.2026).** „Mój zespół”: pasek „Dziś”
  (awatar z obwódką: w pracy / nieobecność do… / delegacja / zdalnie), karty
  „Do Twojej decyzji”, tabela z mini-tygodniem pn–pt i paskiem godzin miesiąca
  (`components/hr/team/team-week.ts`). **Wniosek i timesheet decyduje się
  z „Mojego zespołu”** (decyzja Artura) — te same hooki i trasy co
  „Akceptacje” (`useDecideLeave`, `useDecideTimesheet`, odrzucenie przez
  `RejectLeaveDialog` z powodem), bez nowej logiki serwera; prawo do decyzji
  sprawdza serwer. **Toast po decyzji idzie z obietnicy `mutateAsync`, nie
  z callbacków `mutate()`** (20–21.10.2026): po decyzji lista odświeża się bez
  sprawy, a komponent z przyciskiem albo oknem się odmontowuje (szczegół
  „Akceptacji” ma `key` sprawy, „Do Twojej decyzji” bez kart zwraca `null`) —
  callbacki `mutate()` TanStack Query wtedy przepadają. Sekcja bez kart zeruje
  też otwarte okno odrzucenia, żeby nie wróciło samo przy następnej karcie. Propozycje premii tylko do wiadomości (decydują Płace), karta
  premii tylko przy `sees_bonuses` (D2). Mini-tydzień to pole `week` trasy
  `GET /api/hr/team` (`team._week`): stan dnia `work` / `off` / `absent` /
  `pending` / `business_trip` / `remote` / `unknown`, **bez rodzaju nieobecności** (D6 —
  także dla przełożonego; rodzaj zostaje w `today`), oczekujące tylko dla kręgu
  D6, praca zdalna i delegacja z `leave_calendar.presence_between` tylko przy
  module czasu; urlopy i czas zamknięte = `week: null`. Sam moduł czasu (urlopy
  zamknięte dla patrzącego, audyt 21.10.2026): nieobecności nie są czytane, więc
  dzień bez wpisu obecności to `unknown` („—”), nigdy `work` — „w pracy” mówimy
  tylko, gdy znamy nieobecności (`team.day_state`, `todayStatus`). Do kart doszły
  `created_at` wniosku i `submitted_at` timesheetu („czeka 5 dni”).
  „Kalendarz zespołu”: ciągłe paski (`components/hr/leave/calendar-bars.ts`),
  wiersz „Nieobecnych” (½ = pół dnia, „?” = wliczony wniosek, który czeka,
  delegacja się nie liczy), kolumna „dziś” z obwódką, „Znajdź osobę”, widok
  „2 tygodnie / Miesiąc” (na przełomie dwa zapytania `?month=` złożone we
  froncie) i panel „W tym tygodniu nie ma” + „Najtrudniejszy dzień”.
  „Akceptacje”: skrzynka (lista „Do decyzji” i „Do wiadomości · B2B
  i zlecenie”, szczegół z kaflami „Zastępca / Wypada w tym czasie / Też
  nieobecni” i mini-kalendarzem zespołu na termin z `department_absent`),
  podsumowanie statusów timesheetów nad sekcją „Timesheety” (miesiąc, od którego
  sekcja się otwiera — sekcja należy do modułu czasu, `components/hr/time/`),
  „Historia wniosków” zwinięta do linku (zapytania historii dopiero po
  rozwinięciu). „Przypomnij” przy timesheecie „nie założony” czeka na trasę
  przypomnienia z modułu czasu — bez niej przycisku nie ma.

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
  „Czas i ludzie”. `care_contact_due` i `care_client_structure` należą do sekcji Delivery. **Dzwonka nie ma** (pasek z ikonami jednego tematu,
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
  i stawki (kwoty), `care_contact_due`, `care_client_structure`. Treść składa `services/hr/hr_mail.py`:
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
- **NEXUS wygrywa z paczką** (audyt A4, 19.10.2026, #2347): od 18.10 kartoteki,
  płace i czas prowadzi NEXUS, a Compass jest tylko do odczytu. Wiersz z mapy id
  zmieniony w NEXUSIE po zapisie partii (`changed_in_nexus`) dostaje „conflict”
  bez zapisu — także kartoteka (przełożeni przepięci w „Strukturze”), stawka
  i premia; wiersz usunięty w NEXUSIE (obecność, opis roli, fragment) — „skip”.
  Kartoteki z Compassa nie odświeżamy (decyzja 18.10).
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
  Usunięcie oświadczenia jako pomyłki (19.10.2026, `documents_student.unsync`) cofa datę, którą
  ono wpisało: wraca data najnowszego pozostałego ważnego oświadczenia, a bez niego zwolnienie
  znika; data wpisana ręcznie zostaje. Usunięcie po retencji kartoteki nie rusza.
- Pobranie i podgląd pliku dokumentu zostawia ślad `document_downloaded` w `hr_audit_events`
  (19.10.2026; przy potwierdzeniu nieobecności `sensitivity='health'`). Ten sam ślad przy
  pobraniu załącznika z wniosku urlopowego — trasą osoby i trasą Kadr (`hr_leave._proof_file`,
  audyt 21.10.2026). Nowa trasa wydająca plik e-teczki = ten sam `audit.record`. Plik zapisany przed
  wierszem znika z dysku, gdy zapis wiersza albo kartoteki się wycofa.
- Retencja: lata na rodzaj w `app_settings['hr_document_retention']` (domyślnie 10 lat dla
  każdego rodzaju, także „inne” — decyzja Artura 19.10.2026), liczone od końca roku ostatniego
  dnia pracy. Nic nie kasuje się samo: lista w Ustawienia → Kadry, usunięcie z zaznaczeniem
  i potwierdzeniem; plik znika, wiersz zostaje jako ślad. PESEL-u i numeru dowodu nie ma
  w żadnym polu.
  Okres co najmniej 10 lat, najwyżej 50 (decyzja Artura 19.10.2026,
  `RETENTION_MIN_YEARS`; serwer i karta w Ustawieniach odmawiają krótszego).

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
- **Stawkę z umowy przepisują Płace** (decyzja Artura 19.10.2026): podpis osoby bez
  uprawnienia Płac (i bez roli admin) zapisuje umowę, formę i dokument, ale nie stawkę —
  Płace (bez adminów, gdy są inni; nigdy sama osoba) dostają dzwonek `hr_rate_changed`
  „Stawka z umowy do przepisania” bez kwoty, z linkiem `/people/<id>#place`; ślad
  `agreement_applied` ma `rate = "pending_payroll"` (inaczej `set` / `unchanged`).
  Stawkę z ostatniej umowy w oknie „Nowa umowa” (`defaults.hourly_rate`) widzą tylko
  Płace i admin; `applies_rate` mówi frontowi, czy dopisać „Stawkę przepisze osoba z Płac”.

### Start na produkcji (19.10.2026)

- E-teczka działa od włączenia modułu `people` (bez osobnego przełącznika); `hr_agreements`
  włączony 19.10. Okres przechowywania: 10 lat dla każdego rodzaju, także „inne” (Artur).
- Na start bez generatora (Artur): wzorów DOCX nie ma — umowy wchodzą do e-teczki jako skany
  (rodzaj umowa/aneks). Generator działa, gdy Kadry dodadzą wzór z polami `{{ … }}`
  (Ustawienia → Zespół i dostęp → Kadry → Wzory umów; okno „Nowa umowa” mówi, że wzorów brak).
- Podpis ręczny ze skanem; Autenti wyłączone (`AUTENTI_ENABLED` nieustawione) — nic nie wychodzi
  do ludzi. Na start Kadry wgrywają skany aktywnych umów i aneksów oraz oświadczenia studentów
  z „ważny do”.
- Pełna ścieżka (wzór, odmowa poniżej 31,40 zł, szkic, PDF, podpis ze skanem → stawka i forma
  w kartotece, oświadczenie studenta → zwolnienie ze składek, krąg widzących) przeklikana na
  lokalnym stosie nexus-hr z kodem 071549443; na produkcji żadnych danych testowych.

## Forma umowy i kartoteka za kontem (decyzje Artura 19.10.2026)

**Forma umowy (UoP / B2B / zlecenie): „Przełożony, admin, Finanse, sama osoba”.**

- Jedna reguła na serwerze: `people.form_viewer` + `people.form_payload`. Forma i pola,
  z których da się ją odczytać (`people.FORM_FIELDS`: znacznik studenta, koniec zwolnienia
  ze składek, „składki od”, staż do urlopu, zaświadczenie ZUS, podpowiedź 20/26), idą tylko do:
  samej osoby, jej bezpośredniego żywego przełożonego (`direct_report_ids`), admina i Finansów
  (uprawnienie „Płace” — `people.sees_every_form`). Przełożony dostaje formę i znacznik
  studenta, bez dat (przegląd 17.10). Zastępca przełożonego nie ma pełnej kartoteki, więc i formy.
- Kadry bez Płac: pełna kartoteka z `employment_type: null` i bez kluczy `FORM_FIELDS` —
  w katalogu, kartotece, Strukturze, cudzym „Moim zespole” i w odpowiedzi na własny zapis.
  Finanse dostały pełną kartotekę (`viewer_scope`). Podpowiedź 20/26 w odpowiedzi „Zmień
  pulę” idzie przez tę samą regułę. Były przełożony osoby, która odeszła (`exited`), widzi
  już tylko wizytówkę — jak `direct_report_ids` (audyt A4). Jarvis nie ma osobnego narzędzia o ludziach
  — czyta te same trasy. Lista dla Compassa (`roster_export`) formy nie miała i nie ma.
- **Zmiana formy: admin, Finanse i Kadry** (Kadry zapisują bez podglądu: w „Edytuj kartotekę”
  pole „Bez zmian (forma ukryta)”, zapis bez wybranej formy jej nie wysyła; pól zależnych
  od formy Kadry bez Płac nie widzą). Finanse zmieniają formę osobną trasą
  `PATCH /api/hr/people/{id}/employment-type` (bramka `require_hr_people_records`: Kadry albo
  Płace) — okno „Zmień formę” na kartotece.
- **Moduły procesowe zostają** (decyzja „zostają jak są”): umowy z ludźmi, wejście konsultanta,
  urlopy (zgłoszenie vs wniosek, okno „wniosek za kogoś” potrzebuje formy do typów nieobecności),
  czas i Płace dalej czytają formę, bo od niej zależy działanie. Pole `employment_type` w listach
  urlopów zostało — usunięcie go z samej listy nic nie ukrywa, skoro okno wniosku za kogoś je ma.

**Katalog = konta NEXUSA: „Konto decyduje + lista rozjazdów”** (`services/hr/account_profiles.py`).

- Aktywne konto pracownicze (`people.is_staff_account`: bez „Automatyzacji”, starego podglądu
  `user`, niepotwierdzonej rejestracji i kont integracji OAuth; klucze API to `service_accounts`,
  nie `users`) ma kartotekę.
- **Konto integracji OAuth** (`oauth_clients.acting_user_id`, migracja 0311 — scrapery
  pracuj.pl / JJIT) nie jest pracownikiem, choć ma rolę rekrutacyjną (TCM): przez nią idzie RBAC
  zapisu kandydatów, a „Automatyzacje” są tylko do odczytu. Rozpoznajemy je po kliencie
  (`people.integration_account_ids`), nie po roli (decyzja Artura 20.10.2026 — konto stało
  w kolejce timesheetów jako „Nie założony”). Kartotekę założoną mu 19.10 usuwa jednorazowa
  faza startu `cleanup-integration-profiles` (`hr/integration_profile_cleanup.py`, paragon
  `hr_integration_profile_cleanup_2026_10_20`; tylko `created_from_account` bez danych kadrowych). Brakującą zakłada `ensure_profile` przy założeniu konta przez admina i przy każdym
  logowaniu SSO (w savepoincie — kartoteka nie blokuje logowania; tylko przy włączonym
  programie) oraz „Wyrównaj wg konta”: „Aktywny”, forma B2B tylko jako wartość domyślna
  z `employment_type_pending` (ekrany: „do uzupełnienia”; znacznik gaśnie przy pierwszym zapisie
  formy, także tej samej), `created_from_account` bez przełożonego = przełożony do uzupełnienia.
  Migracja `0476_hr_profile_follows_account`, SQL w `hr_account_profile_schema.py`.
- **Status idzie za kontem**: listener `after_flush` na `users.is_active` (wszystkie ścieżki —
  Osoby i role, usunięcie konta, SSO bez roli, synchronizacja grup AAD, sprawa odejścia).
  Wyłączenie → `exited`, `exited_at`, ostatni dzień = dzień wyłączenia albo wcześniejsza data
  z kartoteki; odejście w toku też. Włączenie → stan sprzed wyłączenia: status i ostatni dzień
  ze śladu `profile_follows_account` (np. `offboarding` z jego ostatnim dniem) — decyzja Artura
  21.10.2026, pomyłkowe wyłączenie nie kasuje odejścia. Tylko gdy kartotekę zamknęło samo
  wyłączenie (ślad z tej samej transakcji co `exited_at`) i ostatni dzień od tamtej pory się nie
  zmienił; inaczej `active` bez ostatniego dnia. `exited_at` zawsze znika.
  Ślad `hr_audit_events` `profile_follows_account` (`source: account` / `align`), w tej samej
  transakcji co zmiana konta. Zapis surowym SQL-em listener omija — łapie go lista rozjazdów.
- **Lista rozjazdów** w „Ludzie → Katalog” (admin, Finanse, Kadry; `GET /api/hr/people/
  account-mismatches`): konto wyłączone przy otwartej kartotece, konto włączone przy zamkniętej,
  konto bez kartoteki, plus liczniki „do uzupełnienia”. „Wyrównaj wg konta” (`POST …/align`)
  z potwierdzeniem; dzień wyłączenia z `activities` (`user_deactivated`, `sso_aad_role_denied`…),
  potem `tokens_valid_after`, potem dziś.
- Skutki zamkniętej kartoteki (sprawdzone 19.10): sprawy odejścia dla niej się nie zakłada
  (`lifecycle_service.create_offboarding`) — **decyzja Artura: blokada zostaje**, lista
  rozjazdów i Struktura („przełożony nieaktywny”) mówią, ilu ludzi przepiąć. Akceptacje
  podwładnych przechodzą na heada pionu albo Kadry (`recipients.supervisor_of`), opieka
  kontraktu na DL (`care/access.py`), M365 pomija odeszłych (#2338), płace liczą osobę do
  miesiąca ostatniego dnia (`payroll_report.employed_in_month`). Wnioski urlopowe osoby
  zostają (przełożony ich nie widzi, Kadry tak); propozycje premii z lig i placementów nie
  patrzą na status — bez zmian.

## Katalog, kartoteka i Struktura wg makiet (19.10.2026)

Artur przyjął makiety kanwy „Ludzie i Sprzęt” (strona „Ludzie”, karteczki n_pe1–n_pe3)
razem z dodatkami. Logika i krąg widzących bez zmian — zmienił się układ.

- **Katalog** (`PeopleDirectory`, logika w `components/hr/people/directory-view.ts`):
  chipy działów z licznikami (grupy po dziale, „Bez działu” na końcu), chipy formy
  tylko z wierszy, w których serwer zwrócił `employment_type` (admin, Finanse,
  przełożony swoich), „Dziś nieobecni”, „Odchodzą”, dla Kadr „Bez raportu godzin”
  (dawna kolumna „Raport godzin” = ostrzeżenie przy osobie). Kolumna **„Dziś”**
  zamiast „Domyślnie”: `GET /api/hr/people` niesie `today` per osoba
  (`hr_people._today_by_user`) — nieobecność z `absence.absences_on` **bez rodzaju**
  (D6; katalog widzi cała firma), praca zdalna i delegacja z `attendance_days`
  (`leave_calendar.presence_between`, bez notatek); nieobecność tylko przy module
  urlopów, Z/D tylko przy module czasu otwartym dla patrzącego. Słowo nieobecności
  zawsze „nieobecność”, także gdy patrzący widzi formę — słowo formy „urlop” opisywało też
  L4 osoby na umowie o pracę (decyzja Artura 21.10.2026; wcześniej „przerwa”/„urlop”). „W pracy” i chip „Dziś nieobecni” tylko przy module urlopów
  otwartym dla patrzącego (`todayKnown` w `directory-view.ts`, audyt 21.10.2026) —
  sam moduł czasu daje zdalnie i delegację, reszta to „—”.
  Pasek rozjazdów nazywa pozycje (konto + kartoteki „do uzupełnienia” z katalogu)
  i ma „Przejrzyj po kolei” (rozwija tabelę) i „Wyrównaj wg konta”.
- **Kartoteka** (`PersonProfile`, `person-view.ts`): wizytówka z rzędem faktów — staż,
  forma (gdy widoczna), stawka (tylko `scope: "full"` Płac; przełożony jej nie
  dostaje, D2), dni przerwy, premie roku, sprzęt; zakładki Przegląd · Czas i przerwy ·
  Płace i premie · Dokumenty · Umowy · Sprzęt · Historia, każda tylko dla tych, którym
  dotąd montowała się sekcja. Kotwice: `#place` (dzwonek Płac) otwiera „Płace i
  premie”, `#dokumenty`, `#umowy`, `#sprzet`, `#czas`, `#historia`. Pierścień czyta
  `leave_balance` z `GET /api/hr/people/{id}` (pełny zakres, moduł urlopów otwarty,
  pula w umowie) — tylko `hr_people.LEAVE_RING_FIELDS`, bez liczników „na żądanie”,
  opieki i bezpłatnych (kartotekę czytają też Finanse spoza kręgu D6). Tytuł puli bez
  widocznej formy: „Pula płatnych dni”. „Rozpocznij odejście” i „Otwórz sprawę” są
  w menu ⋯ (ta sama reguła `can_manage` co dawna sekcja „Wejście i odejście”, która
  jest teraz linią w Przeglądzie). Oś „Ostatnio” składa się z danych, które patrzący
  już dostał (stawki, premie, wydania sprzętu, start, ostatni dzień).
  **Zakładka „Płace i premie”** (audyt 21.10.2026) powstaje przy module płac, chyba że
  serwer płac odmówił (403/404 — `refused`), ORAZ przy pełnej kartotece z widocznymi
  danymi do rozliczeń (`billingVisible`), bo `BillingDetailsSection` stoi tylko tam —
  Kadry bez Płac w cudzej kartotece i wyłączony moduł płac nie mogą tracić danych do
  rozliczeń. Awaria zapytania o płace (np. 500) to nie odmowa: zakładka zostaje,
  karta „Premie” mówi „Nie udało się wczytać płac.” z „Spróbuj ponownie”; „Płace
  niedostępne dla Ciebie.” tylko przy 403/404.
- **Struktura** (`StructureScreen`, `structure-tree.ts`): przełącznik Lista | Schemat
  (domyślnie Schemat — drzewo kart per pion; Lista = dotychczasowy widok z
  zaznaczaniem i zmianą hurtową). **Przeciągnięcie karty na inną = zmiana przełożonego**
  tą samą trasą `POST /api/hr/structure/reassign`, po potwierdzeniu `useConfirmV2`;
  front odcina siebie, własne poddrzewo i obecnego przełożonego (`canDropOn`), serwer
  i tak pilnuje `people.validate_managers`. To samo z menu ⋯ karty („Zmień
  przełożonego…”, „Ustaw pion…”). Panel **„Do uporządkowania”** (`todoItems`): odejście
  przełożonego z podwładnymi, przełożony, który odszedł, rozjazd z M365 („Przyjmij
  z M365”), podpowiedź „head pionu” („Przyjmij”), bez przełożonego, bez pionu.
  **Duże zespoły (decyzja Artura 20.10.2026):** przełożony z więcej niż czterema
  podwładnymi stawia tych bez własnych ludzi w pionowej kolumnie pod sobą
  (`childLayout`, `ROW_MAX`); podwładni z ludźmi zostają w rzędzie gałęzi.
  Schemat otwiera się na pierwszym korzeniu (`centeredScrollLeft`), raz — zapis
  po przeciągnięciu nie przesuwa widoku. Powód: prod 20.10 — 44 osoby „Bez
  pionu” pod dwiema osobami dawały rząd 5384 px przy 623 px okna i otwarcie
  na pustym polu. Harness `/preview/hr-structure?state=big`.

## Zakładki po przebudowie (22.10.2026)

Decyzja Artura z 22.10.2026, makiety „Przed i po”: https://claude.ai/artifact/Ty1KJh5AaBcGA5s6EtVF3A.
Moduł miał osiem zakładek, każda rola widziała inny zestaw i inną kolejność.
Artur chciał uproszczenia bez wielkiego łączenia, tak żeby ludzie nie musieli
szukać funkcji. Poniższe reguły łatwo cofnąć „przy okazji”, dlatego je spisujemy.

### Pasek zakładek

- Kolejność jest stała: **Katalog · Mój zespół · Kalendarz · Akceptacje · Płace**.
  Kto nie ma dostępu, nie widzi zakładki, ale
  reszta się nie przestawia (`peopleSections()` w `PeopleSectionNav.tsx`).
- Nie przywracaj zakładek „Struktura” ani „Moje zgody”:
  - Struktura to widok **„Schemat”** w Katalogu (przełącznik „Lista | Schemat”,
    tylko Kadry i admin). `/people/structure` przekierowuje na `/people?view=schemat`.
  - Moje prośby o zgodę są w **Mój czas → „Zgody i wydatki”** (`/my-time?tab=consents`).
    `/people/consents` przekierowuje tam z `request` i `new`, a link z maila
    (`approvals/service.py`) prowadzi od razu do Mojego czasu.
- Nie przywracaj zakładki „Sprawy” (decyzja Artura 22.10.2026, makieta R0): sprawy
  administracja@ są w **Opieka → „Do zrobienia”**. `/people/cases` przekierowuje na
  `/care`; tylko przy wyłączonym module `care` tablica spraw zostaje pod starym adresem.
  Szczegóły sprawy dalej są pod `/people/cases/{id}` (linki z maili i dzwonków).
  Menu „Opieka nad konsultantami” widzi też osoba bez roli opieki, gdy ma uprawnienie
  „Sprawy” albo przypisaną sprawę (`casesInCare` w `lib/api/hr.ts`); dostaje wtedy
  samo „Do zrobienia” ze sprawami — bez Konsultantów, Klientów, Zespołu i Komunikatów.
- Etykieta to „Kalendarz”, nie „Kalendarz zespołu”.

### Katalog

- Rozjazdy kont z kartoteką („Do wyrównania”) i „Do uporządkowania” ze Struktury
  to jedna lista **„Porządki · N”**. Otwiera się z przycisku w nagłówku w panelu
  bocznym, a na co dzień nie zajmuje miejsca nad tabelą. Każda sekcja zachowuje
  swoją bramkę. N z nieudanego odczytu to brak liczby, nigdy „0”.
- Filtry Katalogu (szukaj, pion, forma, stan, widok) są w adresie, więc powrót
  z kartoteki je zachowuje.

### Mój zespół, Kalendarz, Akceptacje

- Mój zespół: decyzje zostają na ekranie (decyzja Artura), ale jako zwarte wiersze
  z linkiem „Wszystkie w Akceptacjach”, a nie duże karty.
- Kalendarz ma pasek filtrów taki jak Katalog: szukaj i chipy. Lista „Kto” zniknęła,
  a „Dziś nieobecni” i „Zdalnie dziś” są chipami. Koordynator zaczyna od
  „Mój zespół”, a pozostali od „Wszyscy”.
- Akceptacje: zamiast przełącznika „Co akceptujesz” jest jedna lista z chipami
  rodzaju (Wszystko · Nieobecności · Raporty godzin · Zgody · Do wiadomości)
  i przełącznik „Czeka | Zdecydowane” (dawna zwinięta „Historia wniosków”).
  Działają stare linki z powiadomień: `?tab=consents[&request=]` otwiera
  chip Zgody, a `?kind=timesheet…` otwiera Raporty godzin.

### Kartoteka osoby

- Zakładka „Czas i przerwy” nazywa się teraz **„Nieobecności i godziny”**
  (kotwica `#czas` bez zmian). Pokazuje nieobecności i raporty godzin tej osoby,
  które wcześniej były tylko w Akceptacjach. Dane: `GET /api/hr/people/{id}/history?year=`
  (`services/hr/person_history.py`) — krąg pełnej kartoteki (`viewer_scope == "full"`),
  rodzaj nieobecności przez `can_see_type` (D6), przy ukrytej formie etykieta
  „Nieobecność”, Finanse spoza kręgu widzą tylko zatwierdzone. Moduł zamknięty
  dla patrzącego = `null`, nie pusta lista.
- Mój zespół: znacznik „brak dd.mm” przy godzinach miesiąca bierze się z
  `missing_dates` w `/api/hr/team` (`team_queue(..., missing_before=dziś)`):
  dni robocze przed dziś bez wpisu i bez całodniowej nieobecności, tylko w szkicu
  albo przy braku raportu. Dzisiejszy dzień się nie liczy.

Reguły dostępu, D2, D6, słownictwo PIP i zasada „nie sobie” są bez zmian
(`modul-ludzie-dostep-schemat-i-przelaczenie.md`, `urlopy-czas-place-wejscie-odejscie.md`).
