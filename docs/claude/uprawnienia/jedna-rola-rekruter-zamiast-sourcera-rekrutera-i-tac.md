# Jedna rola „Rekruter” zamiast sourcera, rekrutera i TAC (0411, 02.10.2026)

Decyzja Artura 02.10.2026: „sourcer, rekruter, TAC jako jedno — rekruter”.
Raport: `docs/merge-recruiter-roles-completion-report.md`. Reguły, które łatwo
cofnąć:

- **Ról `sourcer` i `tac` nie ma.** W `UserRole` zostały jako ALIASY
  `recruiter` (zadeklarowane po nim) wyłącznie po to, żeby wiersz ze starą
  etykietą dał się odczytać — typ kolumny ma `omit_aliases=False`
  (`user_role_column_type`), bez tego SQLAlchemy rzuca `LookupError` i wywraca
  każde zapytanie ładujące takie konto. **W kodzie ich nie używaj**: alias
  jako klucz słownika po cichu nadpisuje wpis rekrutera. Pilnuje
  `tests/test_retired_roles_guard.py` (AST po `app`, `tests`, `scripts`, `seed.py`).
- **Rekruter ma prawa dawnego rekrutera.** Dodatki TAC zniknęły: pełna edycja
  rekrutacji i widełki (admin albo uprawnienie „Rekrutacje”), priorytet (+ HoR),
  eksport kandydatów, terminy rozmów u klienta (admin, HoR, DL), raporty
  klientów, zespół klienta z przypisań TAC. Komu potrzebne — rola Delivery
  Leada albo uprawnienie nadane osobie. Nie przywracaj ich rekruterowi bez decyzji.
- **Rola pracy przy requeście jest jedna** (`job_work_assignment.WORK_ROLE`):
  automat nie wybiera już „rekruter czy sourcer”, próg `sourcer_threshold`
  zniknął (stary klucz w `app_settings['request_allocation_rules']` jest
  ignorowany), pulpit nie pyta o rolę. Kolumna `job_work_assignments.role`
  i pole `role` w odpowiedziach zostają jako stała `recruiter`.
- **Każdy rekruter ma trzy kanały Priority Work**; zastępuje go rekruter.
  Cel „rekomendacje w tygodniu” = 15 (do 0411: rekruter 15 / TAC 12 / sourcer
  bez celu). Praktykant awansuje tylko na rekrutera.
- **Migracja jest zbieżna i biegnie przy KAŻDYM starcie** (`services/role_merge.py`
  — jedno źródło dla 0411 i `entrypoint.sh`, po preflagu onboardingu): konto
  i lista `roles` → `recruiter`, sesje zmienionych kont unieważnione, wiersze
  wycofanych ról skasowane z RBAC i `kpi_role_defaults`. Drugi przebieg zmienia
  0 wierszy. Stan sprzed zmiany: `role_session_migration_audit` (klucz
  `0411_merge_recruiter_roles`), skasowane wiersze RBAC:
  `app_settings['repair_details_0411_merge_recruiter_roles']`.
- **Etykiety `sourcer`/`tac` w typie `userrole` i w CHECK-ach tabel RBAC
  ZOSTAJĄ** — po rollbacku obrazu stary kod wstawia wiersze tych ról, a wąski
  CHECK zatrzymałby start. `permission_catalog.ROLES` ich NIE ma: zasiew przy
  starcie dopełnia wiersze dla ról z tej listy, więc wycofana rola odtwarzałaby
  skasowane wiersze co restart.
- **Stara wartość wchodzi tylko przez normalizację** (`role_merge.normalize_role_value`,
  `models.user.known_roles`): mapper Traffita (pisze rolę surowym SQL co noc),
  mapa AAD, `?roles=` listy osób, `UserResponse.roles`. Front: `normalizeRole`
  w middleware i store (cookie sprzed wdrożenia żyje do 8 h).
- **Funkcja „opiekun TAC” zostaje jako dane** (`jobs.tac_id`,
  `client_tac_assignments`, `TAC_UI_ENABLED`), bez roli: opiekunem może być
  DL, admin albo HoR.
- Wzmianki w starszych sekcjach o roli `tac` albo `sourcer` (zbiory ról,
  „admin lub TAC”, „rekruter/sourcer” przy requestach) opisują stan sprzed 0411.
