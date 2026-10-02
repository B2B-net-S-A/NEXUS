# Jedna rola „Rekruter” zamiast sourcera, rekrutera i TAC — raport

Data: 02.10.2026 · migracja `0411_merge_recruiter_roles` · gałąź `claude/merge-roles-recruiter-96d5b5`

## Decyzje Artura (02.10.2026)

1. **Rekruter = dzisiejszy rekruter.** Dodatki roli TAC znikają.
2. **Znika podział rekruter / sourcer przy requestach** i próg „sourcer od 15 pasujących w bazie”.
3. **Cel „rekomendacje w tygodniu” = 15 dla wszystkich** (do tej pory: rekruter 15, TAC 12, sourcer bez celu).
4. Praca na wspólnych plikach dopiero po wejściu PR #1976 (9 uprawnień).

Przyjęte bez sprzeciwu: każdy rekruter ma trzy kanały Priority Work; rola dodatkowa `tac` / `sourcer`
u Delivery Leada, Head of Recruitment i TCM staje się dodatkową rolą `recruiter`; przekonwertowane
konta nie przechodzą onboardingu ponownie (logują się raz od nowa); każdy rekruter zastępuje każdego
rekrutera; kolumny i tabele nazwane od TAC zostają.

## Co się zmienia dla ludzi

| Kto | Co się zmienia |
|---|---|
| Rekruter | Nic w uprawnieniach. Ma wszystkie trzy kanały Priority Work. |
| Były sourcer (3 aktywne konta, 31 nieaktywnych) | Rola „Rekruter”, cel 15 rekomendacji w tygodniu, awans praktykanta prowadzi już tylko na rekrutera. Uprawnienia jak dotąd — sekcje i bramki były identyczne. |
| Były TAC (2 aktywne konta) | Rola „Rekruter”, cel rośnie z 12 do 15. Traci dodatki TAC (lista niżej). |
| DL, HoR, TCM z dodatkową rolą TAC albo sourcera (5 kont) | Dodatkowa rola „Rekruter”. Konto TCM z dodatkową rolą TAC traci dodatki TAC; DL i HoR mają je z własnej roli. |

### Dodatki TAC, które znikają

Komu są dalej potrzebne — rola Delivery Leada albo uprawnienie nadane osobie
(„Edytuj użytkownika” → „Dodatkowe uprawnienia”).

- pełna edycja rekrutacji (status, klient, właściciele, cykl życia) — zostaje admin i uprawnienie „Rekrutacje”,
- widełki wynagrodzenia rekrutacji — zostaje admin,
- priorytet rekrutacji — zostaje uprawnienie „Rekrutacje” i Head of Recruitment,
- eksport kandydatów do pliku,
- dodawanie i potwierdzanie terminów rozmów u klienta — zostaje admin, HoR, Delivery Lead,
- raporty klientów i operacje klienta w analityce,
- zespół klienta liczony z przypisań TAC, oznaczanie podpisu B2B z roli TAC.

### Zmiana dostępu do tras (diff wzorca macierzy bramek)

`tests/data/authz_golden/` przegenerowany. Porównanie starego wzorca z nowym, persona po personie:

- persony o tej samej nazwie (w tym `recruiter`): **0 zmian**,
- `sourcer` → `recruiter`: **0 zmian**,
- `delivery_lead+tac` → `delivery_lead+recruiter`: **0 zmian**,
- `tac` → `recruiter` traci 8 tras:
  `GET /api/analytics/v1/clients/{client_id}/operations`, `GET /api/analytics/v1/commercial/tenders`,
  `GET /api/candidates/export`, `POST /api/candidates/export`, `GET /api/export/candidates`,
  `GET /api/reports/clients`, `GET /api/reports/clients/at-risk`, `GET /api/reports/clients/{client_id}/trend`,
- `head_of_recruitment+tac` → `head_of_recruitment+recruiter` traci 1 trasę:
  `GET /api/analytics/v1/commercial/tenders`.

Macierz widzi tylko zależności tras. Reguły w środku handlerów (pełna edycja rekrutacji, widełki,
priorytet, terminy rozmów) mają własne testy.

## Jak to jest zrobione

- **Jedno źródło SQL:** `backend/app/services/role_merge.py` — czyta je migracja 0411 i `entrypoint.sh`
  (zaraz po cutoverze 0210). Instrukcje są zbieżne: biegną przy każdym starcie, drugi przebieg zmienia
  0 wierszy i nie unieważnia sesji ponownie.
- **Konta:** `role` i lista `roles` → `recruiter` (bez duplikatów), `profile_completed = TRUE` tylko
  gdy wycofana była rola główna, `authorization_version` + `tokens_valid_after` tylko dla zmienionych.
  Stan sprzed zmiany: `role_session_migration_audit`, klucz `0411_merge_recruiter_roles`.
- **RBAC i cele:** wiersze wycofanych ról skasowane z `rbac_role_section_permissions`,
  `rbac_role_action_permissions` i `kpi_role_defaults`. Skasowane wiersze RBAC do przywrócenia:
  `app_settings['repair_details_0411_merge_recruiter_roles']`; paragon (same liczby):
  `app_settings['0411_merge_recruiter_roles']`.
- **Powiadomienia etapów:** reguły i nadpisania klientów wskazujące wycofaną rolę przepisane na
  rekrutera, duplikaty usunięte przed zmianą.
- **Enum:** `UserRole.sourcer` i `UserRole.tac` zostały jako aliasy `recruiter`; typ kolumny ma
  `omit_aliases=False`, więc wiersz ze starą etykietą czyta się jako rekruter zamiast wywracać zapytanie.
  Strażnik AST (`tests/test_retired_roles_guard.py`) zakazuje sięgania po aliasy w `app`, `tests`,
  `scripts` i `seed.py`.
- **Granice wejścia** normalizują starą wartość: mapper Traffita (pisze rolę co noc), mapa grup AAD,
  filtr `?roles=` listy osób, `UserResponse.roles`. Front: `lib/role-normalize.ts` w middleware
  i w store (cookie sprzed wdrożenia żyje do 8 h).
- **Etykiety `sourcer` / `tac` w typie `userrole` i w CHECK-ach tabel RBAC zostają** — po rollbacku
  obrazu stary kod wstawia wiersze tych ról. `permission_catalog.ROLES` ich nie ma, żeby zasiew przy
  starcie nie odtwarzał skasowanych wierszy.
- **Rola pracy przy requeście jest jedna** (`job_work_assignment.WORK_ROLE`): planer nie wybiera
  „rekruter czy sourcer”, pulpit nie pyta o rolę. Kolumna `job_work_assignments.role` i pole `role`
  w odpowiedziach zostają jako stała `recruiter`. Klucz `sourcer_threshold`
  w `app_settings['request_allocation_rules']` jest ignorowany.

## Weryfikacja

| Co | Wynik |
|---|---|
| `ruff check app`, `ruff check tests --select DTZ005,DTZ011`, `ruff format --check app` | czyste |
| Strażnik wycofanych ról + macierz bramek (lokalnie, bez bazy) | 8 passed |
| Lustra migracji 0269 i 0273 (lokalnie) | 8 passed |
| Frontend `npm run type-check`, `npm run lint` | bez błędów |
| Frontend `vitest run --changed origin/main` | 491 plików, 5493 testy, wszystkie zielone |
| Pełne CI na gałęzi (12 shardów pytest z Postgresem, frontend, Trivy) | zielone — bieg 37069129517 na commicie sprzed poprawek z przeglądów; po poprawkach bieg powtórzony, wynik w PR |
| Podgląd przy 1280 × 720 (cele KPI, „Requesty i obłożenie”, „Kategorie kompetencji”, panel „Zespół”, „Osoby i role”, „Praktykanci”) | jedna rola „Rekruter”, bez błędów w konsoli |

## Poprawki po przeglądach (bezpieczeństwo i kod)

Oba przeglądy bez blokerów. Poprawione przed otwarciem PR:

- **Zakres Championa:** ścieżka opiekuna wymaga roli rekrutera obok wpisu w `jobs.tac_id`. Opiekunem
  bywa dziś Delivery Lead, a sam wpis nie może poszerzać jego zakresu poza portfel.
- **`User.has_role`** normalizuje stare etykiety tak samo jak `get_all_roles` — lista `roles`
  ze starym napisem nie daje dwóch różnych odpowiedzi.
- **Przywracanie ze snapshotu** porównuje też listę ról: konto, któremu admin po migracji odebrał
  rolę dodatkową, nie wraca do stanu sprzed migracji.
- **Rola pracy w odpowiedziach** to stała `recruiter`, a nie wartość z wiersza — wiersz ze starą
  etykietą (stary obraz po rollbacku) nie wywróci listy rekrutacji na walidacji odpowiedzi.
- **OpenAPI** wymienia każdą rolę raz (aliasy enuma dawały trzy razy „recruiter”).

Świadomie bez zmian: usuwanie zdublowanych reguł powiadomień etapu zostawia regułę rekrutera także
wtedy, gdy jest wyłączona, a reguła wycofanej roli była włączona. Produkcja nie ma takich wierszy.

## Po wdrożeniu — do sprawdzenia

1. `/api/health` → `version` = SHA z maina zawierający zmianę.
2. Odczyt SQL na produkcji:
   - `SELECT count(*) FROM users WHERE role::text IN ('sourcer','tac') OR roles ?| ARRAY['sourcer','tac']` = 0,
   - liczba wierszy `role_session_migration_audit` z kluczem `0411_merge_recruiter_roles` = liczba
     przekonwertowanych kont (około 41 według odczytu z 02.10: 5 aktywnych, 31 nieaktywnych sourcerów,
     5 kont z rolą dodatkową),
   - 0 wierszy `sourcer` / `tac` w obu tabelach RBAC.
3. To samo po drugim restarcie kontenera i rano po nocnym imporcie Traffita.
4. Ekrany przy 1280 × 720: cele KPI, „Requesty i obłożenie”, panel „Zespół”, „Osoby i role”.

## Poza zakresem

- Usunięcie kolumn i tabel TAC (`jobs.tac_id`, `client_tac_assignments`, `tac_*`) i `TAC_UI_ENABLED`.
- Usunięcie etykiet `sourcer` / `tac` z typu `userrole` i zwężenie CHECK-ów RBAC.
- Kanały Priority Work jako funkcja — zostają, tylko bez podziału na role.
