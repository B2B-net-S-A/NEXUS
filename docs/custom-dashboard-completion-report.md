# Własny pulpit startowy — raport wdrożenia (21.09.2026)

Makiety zaakceptowane przez Artura: https://claude.ai/artifact/P5Dx5ZdPNmMd1rNAJBmfqX

## Decyzje

| Pytanie | Decyzja |
|---|---|
| Punkt startu | Pusty pulpit z kafelkami polecanymi dla roli („Dodaj wszystkie”) |
| Co pokazuje kafelek | Katalog gotowych kafelków z ustawieniami + kreator własnej metryki |
| Układ | Siatka 12 kolumn, przeciąganie i zmiana rozmiaru; telefon: jedna kolumna |
| Zakres v1 | Jeden pulpit na osobę |
| Stare presety ról | Zastąpione od razu (widżety żyją dalej jako kafelki) |
| Finanse w kreatorze | Od razu, z redakcją jak w Insights |

## Backend

- Migracja `0336_user_dashboards` (+ lustro w `entrypoint.sh`, sonda w `/api/health/deep`).
- `app/models/user_dashboard.py`, `app/services/dashboard_tiles.py` (walidacja układu).
- `app/api/user_dashboard.py` — `GET/PUT /api/users/me/dashboard` (kontrola wersji, 409).
- `app/services/custom_metrics/` — `definition.py`, `windows.py`, `engine.py`.
- `app/api/dashboard_metrics.py` — `GET /api/dashboard-metrics/catalog`,
  `POST /api/dashboard-metrics/evaluate` (odczyt, limit 60/min, cache 120 s).
- Źródła metryki: ruchy w pipeline (kamienie milowe D2), kandydaci, rekrutacje,
  kontrakty, zamówienia, finanse (`fold_money`, portfel DL).

## Frontend

- `/dashboard` → `components/v2/dashboard/custom/CustomDashboard.tsx`.
- Siatka: `react-grid-layout` 2.2.4 (MIT) — nowa zależność.
- Katalog i reguły dostępu: `lib/dashboard-tiles/catalog.ts`; arytmetyka układu:
  `lib/dashboard-tiles/layout.ts`; zdanie „Kafelek liczy…”: `describe.ts`.
- Usunięte: `RoleDashboard.tsx`, `DashboardShell.tsx` (+ testy). Stare trasy
  `/dashboard/{recruiter,delivery-lead,head-of-recruitment}` przekierowują na `/dashboard`.
- Harness: `/preview/custom-dashboard`.

## Testy

- Backend: `test_user_dashboard_api.py`, `test_dashboard_metrics.py`,
  `test_user_dashboard_migration_mirror.py`, `test_dashboard_tile_types_mirror.py`
  + dopisy w kontraktach (section ceiling, route authz, rate limit).
- Frontend: `layout.test.ts`, `catalog.test.ts`, `CustomDashboard.test.tsx`,
  przepisany `PriorityWorkIsMounted.test.ts`, wpis w `harness-seeds.test.ts`.

## Znane ograniczenia (świadomie poza v1)

- Jeden pulpit na osobę — bez zakładek, szablonów od kierownika i udostępniania.
- Kreator liczy tylko kamienie milowe pipeline'u (nie dowolne etapy szablonu).
- Filtr klienta w kreatorze: jeden klient (API przyjmuje do 20).
- Edycja układu tylko na szerokim ekranie.
- Kwoty bez porównania z poprzednim okresem.
