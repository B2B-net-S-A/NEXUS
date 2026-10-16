# „Ludzie w NEXUSIE” — dostęp, schemat, przełączenie z Compassa (16.10.2026)

Artur 16.10.2026 przyjął rekomendacje D1–D13 (raport „Ludzie w NEXUSIE”) i D2–D10
ze sprzętu recepcji. Wszystko z Compassa poza Akademią działa w NEXUSIE:
urlopy, obecność i timesheety, stawki i premie, kartoteka, wejście i odejście,
opieka nad konsultantami z mapą technologii, skrzynka administracja@, sprzęt
z protokołami. Compass zostaje z Akademią i czyta listę osób z NEXUSA.

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
  Zespół, kalendarz, plakietka, dzwonek zastępcy, Outlook i Teams widzą
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
- Powiadomienia HR (`hr_*`, `admin_case_assigned`, `equipment_*`) są osobiste:
  widoczne bez sekcji, kategoria „Czas i ludzie”. `care_contact_due` należy do
  sekcji Delivery.

## Schemat

- Każdy moduł ma `app/services/<moduł>_schema.py` (`TABLE_DDL, COLUMN_DDL,
  INDEX_DDL, CONSTRAINT_DDL, DATA_DDL, TABLES, DOWNGRADE_DDL, ALL_DDL`), który czyta
  jego migracja i — przez `app/services/hr_schema_bundle.py` — `entrypoint.sh`.
  Łańcuch: `0452_hr_foundation → 0453_hr_access → 0454_hr_notifications →
  0455_hr_leave → 0456_hr_time → 0457_hr_payroll → 0458_hr_lifecycle →
  0459_contract_care → 0460_admin_cases → 0461_equipment → 0462_equipment_extras`.
  Nowy moduł = nowy plik schematu + wpis w `MODULES` agregatora + wiersz w
  `tests/test_hr_module_chain.py`. Testy szukają migracji po sufiksie, nie po
  numerze (po synchronizacji z mainem numery się przesuwają — `rechain_migration.py`).
- VARCHAR + CHECK zamiast nowych typów enum; nowe wartości tylko w `userrole`
  (`employee`) i `notificationtype`, literalnie w `_ENUM_STATEMENTS` entrypointu.
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
- Błędy Compassa naprawiamy, nie przenosimy — każdy ma test w module
  (pula urlopu przez Nowy Rok, pula B2B liczona dniami płatnymi, samozatwierdzanie,
  placement poza zakresem managera, wektory `pdf_hash` z kodu Compassa).

## Przełączenie (runbook w planie programu)

Kolejność ma znaczenie: najpierw Compass przestaje pisać (moduł tylko do odczytu,
wyłączony `oof-reconcile`), potem eksport i import na sucho z raportem do Artura,
zapis po OK, M365 `live` na jednej skrzynce z listy, potem dla wszystkich, źródło
dostępności `local`, włączenie modułów. Czas pracy od 1. dnia miesiąca, płace po
miesiącu liczonym równolegle w obu systemach. Danych Compassa nie kasujemy.
