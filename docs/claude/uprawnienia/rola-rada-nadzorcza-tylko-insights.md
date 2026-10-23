# Rola „Rada nadzorcza” — tylko Insights z kwotami (0490, 21.10.2026)

Decyzje Artura 21.10.2026: członkowie Rady nadzorczej oglądają zbiorcze
raporty i statystyki, a zakładanie rekrutacji czy kontraktów ich nie dotyczy.
Rola Finanse odpadła, bo czyta wszystko (CV, notatki, stawki osób) i zmienia
zamówienia, faktury i zgody; „Automatyzacje + Moduł Finanse” z tego samego
powodu. Powstała osobna rola `board`, na ekranie „Rada nadzorcza”.

- **Co widzi:** sekcję Insights do odczytu — Rywalizację, Zespół **imiennie**
  (capability `VIEW_TEAM_KPI`, tabela ludzi i „Do uwagi”), Firmę **z kwotami**,
  Raporty z rankingiem klientów i tabelami rok do roku z kwotami, mail
  `board_monthly_report`. „Mój miesiąc” nie (nie ma własnych KPI).
- **Kwoty wpuszcza rola, nie uprawnienie.** `deps.BoardReader` =
  „Moduł Finanse” albo rola `board`; `BoardTrendReader` dokłada `board`, a
  redakcję kwot decyduje `action_permissions.reads_board_money` (HoR dalej bez
  kwot). Rada **nie** ma `VIEW_FINANCE` ani `VIEW_EXECUTIVE` — te capability
  otwierają stawki konsultantów na 40+ trasach poza Insights. Nie dokładaj
  `board` do `default_roles` „Modułu Finanse” w katalogu uprawnień: otworzyłoby
  to moduł Finanse z zapisami i (przez zależności) Delivery.
- **Niczego nie zmienia i nie przyjmuje nadań** (`UNGRANTABLE_ROLES`, jak
  Viewer i Praktykant) — nadanie „Modułu Finanse” dałoby jej faktury KSeF,
  zgody na wydatki i „Zmiany w zamówieniach”.
- **Nie jest pracownikiem firmy:** `board` stoi na listach ról niebędących
  pracą (`hr.people.NON_STAFF_ROLES`, `_NOT_STAFF` w `hr_leave` i
  `hr_dashboard`) — bez tego „Nieobecni dziś” pokazywały Radzie nazwiska.
  Zdarzenia Insights → Integracje bez odczytu kandydatów idą bez osoby
  (`integrations_runs.event_to_dict`). Nowa bramka „każdy oprócz…” ma Radę
  wykluczać.
- **Rola wyłączna** (CHECK `ck_users_exclusive_finance_viewer_roles`,
  `ensure_exclusive_roles`, `_normalized_role_values`, mapowanie grup AAD,
  `EXCLUSIVE_ROLES` na froncie).
- **Front:** Insights i lista umów przedwstępnych. Middleware przekierowuje
  wszystko poza Insights, `/profile`, `/settings`, `/help` i
  `/jobs/umowy-przedwstepne` na `/insights?tab=firma`
  (`lib/board-access.ts`, to samo czyta `postLoginDestination`); menu boczne
  ma tylko Insights, Pomoc i Ustawienia, paleta dokłada „Umowy przedwstępne”. Linki z Insights do profilu klienta i rekrutacji
  są dla konta bez tych sekcji tekstem.
- **Logowanie:** konto M365 w b2bnetwork.pl (gość albo konto w tenancie) przez
  SSO — pierwsze logowanie zakłada „Pracownika”, admin zmienia rolę w „Osoby
  i role” na „Rada nadzorcza”. MFA daje M365; NEXUS własnego nie ma.
- **Pilnują tego testy:** `tests/test_board_role_access.py` (we wzorcu bramek
  rola przechodzi tyle co „Pracownik” plus odczyty Insights; zamknięte moduły
  kandydatów, rekrutacji, klientów, kontraktów, zamówień, Finansów, faktur,
  zgód, Generatora i Historii zdarzeń), `tests/test_board_role_migration_mirror.py`
  (SQL z `services/board_role_schema.py` przez `hr_schema_bundle`) i persona
  `board` we wzorcu `tests/data/authz_golden/`; na froncie
  `lib/__tests__/board-role.test.ts` i przypadki w `middleware.test.ts`
  oraz `InsightsAccess.test.ts`.
- **Nowa trasa:** rolę dopisuj tylko do bramek odczytu raportów. Zbiór, który
  otwiera zapis, dane kandydatów albo stawki osób, ma jej nie zawierać.
- **Wyjątek: umowy przedwstępne** (22.10.2026, decyzja Artura, audyt F54).
  Rada ma pełny dostęp do `/api/pre-contracts` jak rekruter — odczyt, pliki
  z PESEL i akcje — z tytułu roli (`PRE_CONTRACT_ROLES`, bramka
  `require_pre_contract_access`; bez sekcji „Rekrutacje” i bez członkostwa
  w rekrutacji). To jedyny moduł z zapisem i danymi kandydatów otwarty
  Radzie; `test_board_role_access.py` wyłącza go z reguły „tylko odczyty
  ponad Pracownika”. Na froncie Rada ma capability `pre_contract.work`.
- **Lista „Umowy przedwstępne” otwarta Radzie** (23.10.2026, decyzja Artura).
  Rada otwiera samą listę `/jobs/umowy-przedwstepne` (wpis `pre-contracts`
  w `BOARD_NAV_IDS`, czyli paleta; `isBoardAllowedPath`; reguła middleware
  z `PRE_CONTRACT_ROLES` z `lib/pre-contract-access.ts`, bez sekcji, bo Rada
  nie ma Rekrutacji) i widzi na niej wszystkie prośby, jak Head of Recruitment
  (`_lists_every_request` w `api/pre_contracts.py`). Panel osoby, Tablica
  i reszta `/jobs` zostają dla niej zamknięte — osoba na liście jest dla Rady
  tekstem, nie linkiem (`PreContractsList`). Decyzji o karze i wycofania
  cudzej prośby Rada nie dostaje. Pilnują: `board-role.test.ts`,
  `middleware.test.ts`, `PreContractsList.test.tsx`.
