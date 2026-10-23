# Dziewięć uprawnień zamiast ról w bramkach (0410, 02.10.2026)

Zgłoszenie admina 02.10.2026: ekran „Osoby i role” ustawiał sekcje, a o operacjach
decydowało ponad 80 bramek ról w kodzie — Finanse miały Delivery „zapis” i nie
mogły założyć kontraktu, a admin nie miał czego przełączyć. Decyzje Artura
02.10.2026 (makieta: https://claude.ai/artifact/EfjFN2sFCY8tDq6r3XksPt). Kontrakt:
`docs/permissions-nine-switches-contract.md`, raport:
`docs/permissions-nine-switches-completion-report.md`, przegląd: `docs/RBAC.md`.

- **Dziewięć uprawnień tak/nie** (katalog `services/permission_catalog.py`; ten
  sam JSON czyta front — `lib/permission-catalog.json`, `lib/permissions.ts`):
  podgląd Delivery · edycja klientów · kontrakty i zamówienia · status kontraktu
  · podpis B2B · rekrutacje (zakładanie, zamykanie, CV do klienta) · podgląd kwot
  · zmiana kwot · moduł Finanse. Zapis w istniejących tabelach akcji
  (`manage`/`none`); zależności (edycja ⇒ podgląd, zmiana kwot ⇒ podgląd kwot)
  liczą się przy odczycie, ekran pokazuje wymuszoną pozycję jako zablokowaną.
- **Sekcje Delivery i Finanse są WYLICZANE z uprawnień**
  (`section_permissions.derived_section_access`). Zapisane wiersze tych sekcji
  zostają w bazie (powrót do starego obrazu, progi zasiewu), ale resolver ich
  nie czyta; stary wyjątek osoby dla tych sekcji tylko ogranicza.
  `VIEW_FINANCE`/`MANAGE_FINANCE` = uprawnienie „Moduł Finanse”. Sourcing,
  Pipeline, Insights i poziomy Generatora B2B — jak dotąd, z wierszy.
- **Nowa trasa Delivery/Finanse = alias z `api/permission_access.py`** jako
  ZALEŻNOŚĆ trasy (`ContractsOrdersEditUser`, `ClientsEditUser`,
  `ContractStatusUser`, `AmountsEditUser`, `FinanceModuleUser`, …), nie
  `require_roles(admin, delivery_lead)`. Zakres klientów zostaje w handlerze:
  konto z rolą Delivery Leada (`access_scope.is_delivery_lead_governed`) działa
  u swoich klientów, każdy inny posiadacz — u wszystkich.
- **Odmowa nazywa uprawnienie** (`permission_denial.permission_denied`, kod
  `permission_denied`). Bramka sekcji biegnie PRZED bramką uprawnienia
  (zależności routera idą pierwsze), więc `section_access._named_denial` czyta
  uprawnienie zadeklarowane przez trasę (atrybut `required_permissions`).
  Sprawdzenie w środku handlera nie zostanie nazwane przez bramkę sekcji —
  czyste wymaganie deklaruj zależnością.
- **Zmiana dostępu = diff wzorca.** `tests/test_authz_guard_matrix.py` liczy
  werdykt bramek każdej trasy dla 21 person (bez bazy); wzorzec leży w
  `tests/data/authz_golden/`. Zamierzoną zmianę zapisuje
  `AUTHZ_GOLDEN_WRITE=1 python -m pytest tests/test_authz_guard_matrix.py`,
  a diff trafia do PR-a. Macierz widzi tylko zależności tras — reguła w środku
  handlera potrzebuje własnego testu.
- **Uprawnienia osoby tylko dodają** („Edytuj użytkownika” → „Dodatkowe
  uprawnienia”); API odmawia `none` (422 `additive_only`). Role Viewer
  i Praktykant nie przyjmują uprawnień — nadanie zapisane wcześniej przestaje
  działać po zmianie roli (`action_permissions.account_accepts_grants`),
  wiersz zostaje. Zmiana wylogowuje dotknięte konta
  i zostawia wpis w Historii zdarzeń (`rbac.role_permissions`,
  `rbac.user_permissions`).
- **Rola bez wierszy zasiewu** jest liczona funkcją zasiewu z jej zapisanych
  sekcji (start bez migracji nie zamyka Delivery); pierwsza zmiana z ekranu
  zapisuje komplet wierszy. Zasiew: `permission_schema.py` (jedno źródło dla
  migracji 0410, 0282 i `entrypoint.sh`), siatka przy starcie:
  `named_permissions_bootstrap.py`.
- **Kwoty:** kontraktu zmienia „Stawki i kwoty: zmiana”; zamówienia i linii MD
  — to samo albo („Kontrakty i zamówienia” i podgląd kwot u klienta z zakresu),
  jak dotąd przypisany DL (`financial_access.can_write_order_amounts`).
  Posiadacz samych „Kontraktów i zamówień” zakłada kontrakt bez kwot. Budżet
  linii wpisany KWOTĄ (PLN) jest kwotą (z ilorazu kwota ÷ stawka dałoby się
  odczytać stawkę) — budżet w MD zostaje operacyjny. Zamówienie z maila
  zapisuje i odrzuca prowadzący zamówienia z prawem do kwot klienta; sama
  „zmiana kwot” nie wystarcza (to zakładanie zamówienia, nie edycja kwot).
  Kwoty w kreatorze metryk pulpitu (źródło „finance”) liczy „Stawki i kwoty:
  podgląd” w zakresie konta (`custom_metrics/engine.source_denial`,
  `_finance_client_boundary`) — nie rola Delivery Leada. Warunki kontraktowe
  klienta zapisuje „Kontrakty i zamówienia” + podgląd kwot u klienta
  z przypisania (`can_edit_legal_documents`, front
  `canEditClientLegalDocuments`), nie edycja klientów.
- **Status kontraktu to pozycja 4 także bocznymi drogami:** data końca,
  która kończy albo przywraca współpracę (wsteczna na trwającej umowie,
  wyczyszczona na „Kończącym się”, każda zmiana na „Zakończonym”), aneks
  przedłużenia i zbiorcze „Przedłuż” na „Zakończonym” wymagają zmiany statusu
  (`contracts._assert_contract_status_change_allowed`,
  `_assert_ended_revival_allowed`). Skutki podpisanego dokumentu z Generatora
  w kontrakcie wymagają dodatkowo zapisu w sekcji Delivery
  (`b2b_documents.effects.can_write_delivery`) — router Generatora stoi za
  Sourcingiem, więc bramka sekcji z tras Kontraktów tam nie działa.
- **Widełki wynagrodzenia rekrutacji zostają przy roli** (admin albo TAC,
  `jobs._may_write_salary_range`), także dla osoby z nadaną pozycją
  „Rekrutacje”.
- **Stawka do klienta w rekrutacji:** zapisuje ją „Rekrutacje: zakładanie,
  zamykanie, wysyłka CV do klienta”; widzą role z `CLIENT_RATE_VIEW_ROLES`
  oraz każdy, kto ją zapisuje.
- **Front:** przycisk pyta o uprawnienie, którego wymaga trasa
  (`hasPermission`, `<RequirePermission>`), nie o listę ról. Profil sprzed
  wdrożenia (bez klucza `delivery_view` w `effective_action_access`) liczy się
  z domyślnych ról. Harness `/preview/permissions`.
- **Zostaje przy roli (świadomie):** trasy tylko dla admina · „Cofnij
  zakończenie” i „Powrót po przerwie” (admin, Finanse, TCM) · skrzynka alertów
  DL · struktura zespołu i przypisania DL↔klient · Champion (weryfikacja,
  briefing, generowanie) · przypinanie w czacie · szablony pipeline'u · kolejka
  przeglądu DL · pełna edycja rekrutacji przez TAC · tabela rok do roku dla HoR
  bez kwot · podgląd stawki do klienta w rekrutacji · stawki w Generatorze B2B
  · „Może usuwać klientów” · decyzje o propozycjach automatu przydziału (admin,
  HoR) · przydział rekruterów i priorytet dla Head of Recruitment (obok
  uprawnienia „Rekrutacje”).
- Wzmianki w starszych sekcjach o `DeliveryLeadPlus`, `DlAssignedOrAdmin`,
  `MANAGE_FINANCE`, `_ORDER_LIFECYCLE_ROLES`, `ContractStatusWriteUser` albo
  „admin + Delivery Lead” jako bramce operacji w Delivery i Finansach opisują
  stan sprzed 0410 — dziś decyduje uprawnienie z tabeli wyżej, a zakres
  klientów działa jak opisano.

## Rola „Automatyzacje”: podgląd bez kwot i bez zapisu (0446, 14.10.2026)

Decyzje Artura 14.10.2026. Osoba, która podpina procesy firmy pod NEXUSA
(API integracyjne v1), miała dostać rolę Finanse. Finanse czytają jednak
wszystko, z każdą stawką i marżą, a uprawnienia osoby tylko dodają, więc tej
roli nie da się przyciąć. Powstała osobna rola `automation`, na ekranie
„Automatyzacje”.

- **Co widzi:** rekrutacje, Tablicę, kandydatów z CV i notatkami (decyzja:
  „od razu podgląd, jak reszta firmy”), Insights bez imiennych KPI zespołu
  oraz klientów, kontrakty, zamówienia i MD przez uprawnienie „Klienci,
  kontrakty i zamówienia: podgląd”. **Kwot nie widzi:** nie ma „Stawki i kwoty:
  podgląd”, modułu Finanse, rejestru Generatora B2B ani stawki do klienta
  w rekrutacji (`CLIENT_RATE_VIEW_ROLES`). **Opieki nad konsultantami i sprzętu
  konsultanta nie widzi** (decyzja Artura 19.10.2026, audyt A4/A3): rozmowy
  opiekunów, zadowolenie, sygnały odejścia, struktura u klienta, komunikaty
  i sprzęt na kontrakcie (numery seryjne, protokoły) to dane o ludziach, nie
  do integracji — `care_gates.refuse_automation` w bramkach `/api/care`
  i `GET /api/equipment/contracts/{id}`, zakładka „Opieka” kontraktu ukryta.
- **Niczego nie zapisuje na ekranach.** Sekcje Sourcing, Pipeline, Insights
  i Delivery ma tylko do odczytu, więc bramka sekcji odmawia każdego zapisu.
  Rola jest w zbiorach ODCZYTU (`READ_ONLY_ROLES` w `candidate_access.py`,
  `RECRUITMENT_READ_ROLES`) i w żadnym zbiorze zapisu ani eksportu. Imienne
  „Może usuwać klientów” jej nie otwiera (`client_deletion.py`). Zapisy robią
  automatyzacje kluczami API — ze śladem „Integracja: <nazwa>”. Jak stary
  Viewer zostawia tylko własne ślady: przebiegi wyszukiwania, rozmowy
  z Jarvisem, ustawienia pulpitu i powiadomień.
- **Wyjątek: umowy przedwstępne** (22.10.2026, decyzja Artura, audyt F54) —
  pełny dostęp jak rekruter: odczyt, pliki i akcje, także zapis, z tytułu roli
  (`PRE_CONTRACT_ROLES` w `api/pre_contracts.py`). W panelu osoby sekcja
  „Umowa przedwstępna” ma dla tej roli przyciski mimo podglądu Tablicy
  (`pre_contract.work`); `test_automation_role_access.py` nazywa ten moduł
  wyjątkiem od „nie zapisuje”.
- **Rekrutacje bez członkostwa w zespole** (`_JOB_MEMBERSHIP_BYPASS_ROLES`),
  jak reszta firmy. Poczty M365 nie synchronizuje (`eligible_m365_owner`),
  także konto przerobione z rekrutera.
- **Rola wyłączna** (jak Finanse, Viewer, Praktykant): CHECK
  `ck_users_exclusive_finance_viewer_roles`, `ensure_exclusive_roles`,
  `_normalized_role_values`, mapowanie grup AAD i `EXCLUSIVE_ROLES` na froncie.
- **Przyjmuje nadania** z „Osoby i role” (w odróżnieniu od Viewera): gdy
  proces tego wymaga, admin dodaje osobie np. „Stawki i kwoty: podgląd”.
- **Nie gra:** nie trafia na listy rekruterów, do automatu przydziału, ligi
  ani celów — te listy wymieniają role jawnie.
- **Pilnują tego testy:** `tests/test_automation_role_access.py` (w macierzy
  bramek rola nie przechodzi żadnego zapisu, którego nie przechodzi Viewer,
  a jej odczyty to odczyty rekrutera z podglądem Delivery),
  `tests/test_automation_role_migration_mirror.py` (lustro 0446 w
  `entrypoint.sh`) i persona `automation` we wzorcu `tests/data/authz_golden/`.
- **Nowa trasa albo nowy zbiór ról:** rolę dopisuj wyłącznie do zbiorów
  odczytu. Zbiór, który otwiera zapis, eksport albo kwoty po roli, ma jej nie
  zawierać — test macierzy pokaże każdą zmianę.
