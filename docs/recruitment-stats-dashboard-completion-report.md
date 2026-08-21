# Sekcja „Statystyki rekrutacji" na stronie głównej /dashboard — completion report

> Data: 2026-08-07. Plan zatwierdzony przez Artura (pełny pakiet, 5 kafli z Akceptacjami,
> widoczność dla wszystkich ról operacyjnych, default miesiąc, punktacja 150/15/5).
> Geneza: parytet ze stroną `/rekrutacja` InfraReportera (DynaReporter), ale liczony
> NATYWNIE z pipeline'u — zero ręcznego wpisywania statystyk.

## Co powstało

Wspólna sekcja **„Statystyki rekrutacji"** renderowana pod KAŻDYM presetem `/dashboard`
(`RoleDashboard` → sibling `presetContent`), dla każdej roli operacyjnej
(sourcer/tac/recruiter/DL/HoR/admin). Rola `finance` (containment danych osobowych)
i legacy `user` nie widzą sekcji (gate FE + guard BE `OperationalUser`).

Zawartość (wszystko z JEDNEGO zapytania `GET /api/dashboard/v2/recruitment-stats`):

1. **5 kafli**: Weryfikacje / Rekomendacje / Interviews / **Akceptacje** / Placements —
   zawsze równe stopce „Razem" tabeli (jedno przeliczenie `VERIFIER_ANCHORED_CTE`).
   Akceptacje = etap pipeline `acceptance` („Klient akceptuje kandydata").
2. **Tabela per osoba** (`RecruitmentTeamTable` — prezentacyjna ekstrakcja z
   `TeamKpiPanel`): sort, filtr roli, szukajka, wiersz Razem z widocznych wierszy,
   precision vs target 75%.
3. **Trend 12 miesięcy** (recharts, tokeny `--chart-1..5`) + **lejek konwersji** okresu
   (ds `FunnelChart`; konwersje ze zliczeń okresu — nie kohorty; mianownik 0 → „—").
4. **Rywalizacje** (własne okresy biznesowe, nie okres sekcji): hero Ligi Mistrzów
   (`HeroLigaMistrzow` — pierwsze użycie), 2× wyścig miesięczny (`RaceCard` — pierwsze
   użycie; wymogi 4 weryfikacje/dzień + precision ≥75%, min. 2 placementy, wykluczenie
   lidera kwartału), Hall of Fame (all-time top + zamrożone podia z `competition_winners`).
5. **LinkedIn Performance** — pierwszy FE konsument `/api/linkedin-metrics` summary
   (totals + tabela per osoba, progi response rate 20%/10%).

Okres sekcji: własny selektor Dziś/Tydzień/Miesiąc/Kwartał/Rok, **default miesiąc**,
niezależny od `?period=` presetu.

## PR-y

| PR | Zakres |
|---|---|
| #1067 | RBAC: `/api/kpis/team/panel` → `OperationalUser` (pełna tabela imienna dla całego zespołu); higiena `_LEGACY_STATS_PREFIXES` (`/api/competitions` wyjęte z legacy, `/api/dashboard/v2` bez omyłkowych nagłówków Deprecation/Sunset) |
| #1068 | `compute_team_panel` z jawnym oknem `[start, end)` (bounds > period, default bez zmian); nowy `services/recruitment_trend.py` (trend 12-mies. na kanonicznym CTE + `funnel_conversions`) |
| PR 3 | Composite `GET /api/dashboard/v2/recruitment-stats` — koperta v2, `_capture` per pod-blok, shape-guards, **cache org-level** (klucz bez user_id, scope nadpisywany per widz, TTL 120 s complete / 30 s degraded); `compose_monthly_races` wyniesione do serwisu (API i composite używają tej samej funkcji) |
| PR 4 | FE szkielet: `RecruitmentStatsSection` + `RecruitmentTeamTable` + typy w `dashboard-v2-api.ts` + wpięcie w `RoleDashboard` |
| PR 5 | FE pełny pakiet: `RecruitmentCompetitions` + `RecruitmentLinkedInPanel` + `RecruitmentTrendChart`; usunięcie `CompactGamification` z RoleDashboard (sekcja go zastępuje); fix labelu podium rekruterów „placementów"→„pkt" w `ChampionsSection`; tokenizacja badge w `RaceCard`; ten raport |

## Kluczowe decyzje projektowe

- **Cache org-level**: payload identyczny dla każdego uprawnionego widza (dane org-wide
  by design), więc klucz cache NIE zawiera user_id — ciężkie CTE liczy się ≤1×/TTL
  niezależnie od liczby userów na stronie głównej. `scope` w kopercie jest nadpisywany
  per widz przy odczycie z cache.
- **Kafle = totals tabeli** — jedno przeliczenie, zero rozjazdów kafel↔tabela.
- **Brak danych ≠ 0**: `StatsBoundary` + pod-blokowe `data_quality.sections`;
  awaria źródła → blok `null` + „dane chwilowo niedostępne (to NIE jest zero)".
- **Rozjazd definicji kafle vs liga jest świadomy**: kafel „Interviews" liczy etap
  `interview`, punktacja ligi liczy `client_interview` — różne silniki biznesowe,
  pola `definition` w kaflach to opisują.
- **Konwersje = period conversions**, nie kohorty (kandydat zweryfikowany w maju może
  mieć placement w lipcu) — adnotacja w docstringu i w komentarzu FE.

## Znane ograniczenia / follow-upy (świadomie poza zakresem)

1. **Kafel Akceptacje będzie ~zerowy**, dopóki zespół nie zacznie konsekwentnie używać
   etapu „Akceptacja" w pipeline (~7 ruchów/90 dni historycznie). **Wymagany komunikat
   Artura do zespołu.** Licznik jest uczciwy od teraz.
2. **`days_worked` / nieobecności** — bez nich brak metryk per-dzień (Power Calling,
   cele 4/dzień z urlopami). Osobna decyzja.
3. **Acceleration Path** (Junior→Senior→Expert) i **cel zespołowy** (Summer Race) —
   osobne decyzje produktowe.
4. **Legacy `/api/kpis/*` zostaje po stronie backendu.** `/api/kpis/me/today` ma nadal
   żywego konsumenta (topbarowy `MyKpiWidget`); `/api/kpis/me/panel` i
   `/api/kpis/team/panel` po sprzątaniu z pkt. 5 nie mają już ŻADNEGO konsumenta we
   froncie — endpointy zostają świadomie (mogą mieć konsumentów spoza repo), ale okno
   rozjazdu ≤120 s między composite a legacy przestało być widoczne dla użytkownika,
   bo nie ma już drugiego widoku karmionego z legacy.
5. ~~Osierocone `DashboardV2.tsx` + fetchujące `MojeKpiPanel`/`TeamKpiPanel`~~ —
   **zrobione 2026-08-20** (opcjonalny PR 6). Usunięte: `components/v2/pages/DashboardV2.tsx`,
   `components/v2/kpi/MojeKpiPanel.tsx`, `components/v2/kpi/TeamKpiPanel.tsx`,
   `components/v2/pages/dashboard/MyJobsWidget.tsx` (trzy ostatnie osierociłyby się razem
   z pierwszym) + osierocony wrapper `postingsApi.stats` w `lib/api.ts`.
   **Nie podpinaliśmy `DashboardV2` z powrotem**: `RoleDashboard` renderuje już następcę
   każdej sekcji, więc remount dałby dwie tabele „KPI zespołu" obok siebie — jedną
   z legacy `/api/kpis/team/panel`, drugą z composite `/api/dashboard/v2/recruitment-stats`,
   z osobnymi cache. Dwie różne liczby pod tym samym nagłówkiem to pogorszenie, nie naprawa.
   **Znika przy okazji to, czego żaden preset `RoleDashboard` nie renderuje** (nieosiągalne
   z żadnej trasy od 2026-08-04, więc nikt tego dziś nie widzi — kasacja usuwa złudzenie,
   że istnieje; wypisane, żeby dało się je świadomie odtworzyć):
   (a) wiersz czterech kafli ogólnofirmowych (Kandydaci / Otwarte rekrutacje / Klienci /
   Aktywne kontrakty z `/api/dashboard/stats`), (b) „Ostatnie zatrudnienia"
   z `/api/activities/feed`, (c) pełny panel „Moje KPI" (target-vs-wykonanie
   z `/api/kpis/me/panel`).
   Efekt uboczny, który był celem sam w sobie: bramka rolowa w `TeamKpiPanel` była
   listą inline zamiast wpisu w rejestrze capability **właśnie dlatego**, że jej jedyny
   importer był sierotą. Panel znika, więc ten dług znika razem z nim.

## Weryfikacja

- BE: ruff 0.15.22 check+format czyste; pytest lokalnie (kontener prod-parity +
  postgres + `alembic upgrade heads`): RBAC/nagłówki 34/34, bounds+trend 8/8,
  composite 5/5, sąsiedzi (dashboard_v2 + competitions) 61/61.
- FE: `tsc --noEmit` czyste; vitest suite dashboard+insights 37/37; ESLint bez nowych
  problemów; CI dodatkowo: `next build`.
- Po deployu: smoke `/api/health` + Chrome na prod — sekcja per rola (6 ról + finance
  negative), przełącznik okresów, dark/light, Network bez nagłówków Deprecation na
  `/api/dashboard/v2/*` i `/api/competitions/*`.
