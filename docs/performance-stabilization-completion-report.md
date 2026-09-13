# Stabilizacja bez zmiany architektury — raport wykonania

**Źródło:** [audyt wydajności i dostępności z 13.09.2026](performance-and-availability-audit-2026-09-13.md).
**Zakres tego PR-a:** punkty 1–7 uzgodnione z Arturem 13.09.2026, czyli wszystko, co da się zrobić
w kodzie aplikacji bez decyzji infrastrukturalnej. Jeden PR, jeden squash-merge.

## Weryfikacja audytu

Wszystkie 12 ustaleń F01–F12 potwierdzono w kodzie na `ab10c8bb` (bez zmian w tych miejscach
do `297f84c0`). Trzy korekty wiedzy względem raportu:

- **Typ hosta jest znany**: CCX33 x86, 8 vCPU / 32 GB (konsola Hetznera, 20.07.2026). Wpis
  „CAX21 ARM” w `CLAUDE.md` był nieaktualny — poprawiony w tym PR-ze. Wniosek „nie kupuj większej
  maszyny” zostaje w mocy: jeden proces uvicorna i tak używa jednego rdzenia.
- **Dwa historyczne 503 frontendu (06.09, 08.09) mają znaną przyczynę**: wyścig demona Dockera
  „No such container” przy tworzeniu kontenera frontendu podczas `compose up` w Coolify
  (powtórka incydentu z 24.08, #1414). To awaria deployu, nie obciążenia — wzmacnia F03.
- **Obserwowalność jest słabsza, niż audyt zakłada**: Alloy stoi za `profiles: ["observability"]`
  i bez `COMPOSE_PROFILES` w Coolify nie startuje wcale.

Drobne: `statement_timeout=0` w fazie `_DATA_STATEMENTS` jest świadome (z `lock_timeout=3s`);
audyt wydajności z 17.07.2026 zgłaszał F05 i F02 już dwa miesiące wcześniej; liczba pętli tła
wzrosła w tym czasie z 24 do 48.

## Co zmieniono

| Ustalenie | Zmiana | Pliki | Test |
|---|---|---|---|
| F10 kolizja pliku roboczego, brak limitu rozmiaru | `from-cv`: `NamedTemporaryFile` per żądanie, `_validate_upload_size` przed zapisem, `_sanitize_upload_filename`, plik roboczy usuwany w `finally`, kopia trwała pisana z bajtów w pamięci (bez `os.replace` współdzielonej ścieżki) | `backend/app/api/candidates.py` | `tests/test_candidates_from_cv_tempfile.py` — na starym kodzie 2/3 czerwone (kolizja odtworzona: „rename failed: No such file”) |
| F07 N+1 KPI na dashboardzie HoR | `load_team_kpis` (4 SQL na roster) zamiast `load_user_kpis` × osoba (3 SQL × roster) | `services/dashboard_v2.py`, `services/dashboard_v2_sources.py` | `tests/test_dashboard_v2.py` (przepięte stuby) |
| F07 równoległe przeliczanie cache | `cache_single_flight` (blokada per klucz, podwójne sprawdzenie) + `jitter_seconds` w `cache_set`; użyte w snapshotcie statystyk rekrutacji, KPI zespołu, `/api/dashboard/kpis` i 7 endpointach Insights odpalanych przez panel Rekrutacja | `core/cache.py`, `api/kpis.py`, `api/dashboard.py`, `api/insights_recruitment.py`, `api/insights_team.py`, `api/insights_charts.py` | `tests/test_core_cache_single_flight.py` (50 równoległych zimnych odczytów → 1 obliczenie) |
| F05 XLSX na pętli zdarzeń | `_build_xlsx_bytes` w `asyncio.to_thread` na małych wierszach; `GET /api/candidates/export` (bez konsumenta) dzieli pomocniki z `POST`, `count()` do audytu zamiast 50k ORM w pamięci | `api/candidates.py` | `tests/test_candidates_export_v2.py` (+2: XLSX obu tras przez `to_thread`, parytet CSV GET/POST) |
| F08 mnożnik retry | `QueryProvider.retry: 0`; axios: jitter 0–500 ms, `Retry-After` z sufitem 10 s; zapisy bez zmian | `components/QueryProvider.tsx`, `lib/api.ts` | `api-transient-retry.test.ts` (+2), `QueryProvider.test.tsx` |
| F08 polling | stałe w `lib/polling.ts`: dzwonek 5 min przy zdrowym WS / 60 s bez; fallback WS 60 s; KPI 5 min; sekcje dashboardu i onboarding 5 min + `refetchOnWindowFocus`; obłożenie 2 min; dashboard zadań nie nadpisuje interwału dzwonka | `hooks/useNotifications.ts`, `hooks/useMyKpis.ts`, `NotificationsDropdown.tsx`, `v2/dashboard/*`, `priority-work/AllocationWorkloadBoard.tsx` | `QueryProvider.test.tsx` (budżet ≤2 GET/min) |
| F09 Insights montuje wszystko naraz | 13 sekcji poza pierwszą w każdym panelu owinięte w istniejący `DeferUntilVisible` (kotwica `id` na zewnątrz) | `components/insights/*Panel.tsx` | `InsightsSectionNavContract.test.ts` (+3) |
| F04 UPDATE bez guardu na starcie | `AND document.document_kind IS DISTINCT FROM 'cv'` | `backend/entrypoint.sh` | `tests/test_entrypoint_document_kind_guard.py` |
| F01 Sentry ignoruje błędy sieci | `ERR_NETWORK` próbkowany 10 % z fingerprintem `network-error` zamiast `ignoreErrors` | `frontend/sentry.client.config.ts` | — |

Model ruchu tła bezczynnego dashboardu przy zdrowym WebSockecie: ~1,5 GET/min na kartę (było ~9,5).

## Świadomie poza zakresem

- **F02 wydzielenie workera** — 4 moduły pętli tła (`saved_search_alerts`, `notification_triggers`,
  `kpi_coach_service`, `mention_dispatch`) piszą na WebSocket przez in-process `ConnectionManager`;
  worker w osobnym procesie bez kanału między procesami wyciszyłby powiadomienia. Wymaga decyzji
  i projektu (LISTEN/NOTIFY albo przeniesienie tylko pętli ciężkich dla DB/CPU).
- **F03 deploy bez przerwy** — compose build pack Coolify nie ma rolling update; realna droga to
  rozbicie FE/API na osobne aplikacje Dockerfile w Coolify. To też wygasza wyścig „No such container”.
- **F06 budżet pul** — bez drugiego procesu nic nie zmienia. **F11** readiness/nadzorca, **F12**
  profilowanie, staging i testy 50/100 (audyt zakłada staging z 60 tys. kandydatów, którego nie ma).
- Pętla po wszystkich stronach kursora w `MyOnboardingTasks` (zmiana kształtu UI).

## Kroki ręczne po merge’u (poza kodem)

1. Sekret `SENTRY_AUTH_TOKEN` w GitHub Actions — dzienny monitor Sentry dziś pisze „secret not set — skipping digest”.
2. Coolify (workflow „Coolify set env”): `COMPOSE_PROFILES=observability` + `GRAFANA_LOKI_URL/USER/TOKEN`,
   żeby Alloy w ogóle startował; potem zwykły deploy.
3. Zewnętrzny monitor co 1 min na `https://nexus.dynaminds.pl/login` (oczekiwane 200 po `-L`)
   i `https://api.nexus.dynaminds.pl/api/health/live` — sonda GH Actions jest godzinowa.

## Jak zweryfikowano

- Backend: `ruff check app/` + `ruff format --check app/` czyste; w kontenerze z obrazem backendu
  i Postgresem po `alembic upgrade heads`: `test_candidates_from_cv_tempfile`, `test_dashboard_v2`,
  `test_dashboard_v2_recruitment_stats`, `test_dashboard`, `test_insights_recruitment_funnel`,
  `test_insights_team`, `test_insights_charts`, `test_insights_seniority`, `test_kpi_team_bounds`,
  `test_core_cache_single_flight`, `test_candidates_export_v2`, `test_candidate_module_access`,
  `test_entrypoint_document_kind_guard` + lustra entrypointu (`test_office_presence_rubric_mirror`,
  `test_entrypoint_ddl_guards`, `test_cv_rule_startup_schema`), `test_ci_coverage_contract` — zielone.
- Frontend: `tsc --noEmit`, `next lint` (bez nowych ostrzeżeń), vitest dla `lib/__tests__`,
  `components/insights`, `components/__tests__/QueryProvider`, `v2/dashboard` — 242 testy zielone;
  `next build` zielony.
- Po deployu: `/api/health` z nowym SHA, Chrome na dashboardzie i `/insights?tab=rekrutacja`
  (sekcje ładują się przy scrollu, kotwice działają), eksport XLSX z listy kandydatów.
