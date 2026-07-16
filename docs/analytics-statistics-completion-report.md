# Analytics/Statystyki — raport realizacji (2026-07-16)

> Realizacja planu `docs/analytics-statistics-claude-implementation-plan-2026-07-16.md`.
> Wykonawca: Claude Code (jedna sesja, 2026-07-16). Wszystkie PR-y: zielone CI,
> squash-merge, deploy z weryfikacją exact-SHA przez nowy status-gate.

## Zrealizowane PR-y

| PR planu | GitHub | Deploy (SHA) | Zakres |
|---|---|---|---|
| PR 0 | #764 | `2a1056e` | deploy.yml: poll statusu deploymentu po UUID, fail-fast + log tail, retry 20×30s na 429 queue-full; coolify-ops.yml (list/cancel); nightly E2E bez sekretu → tylko public specs; PR #710 zamknięty jako obsolete |
| PR 1 (R0) | #769 | `254d574` | `app/analytics/capabilities.py` (macierz §4.3, multi-role = unia), `/api/auth/me.analytics_capabilities`; guardy: contracts/invoices/orders/framework→TacPlus, rate-benchmarks + reports sales/board/tenders→DL+, clients→OperationalUser, client profile redaguje MRR/LTV/stawki bez VIEW_FINANCE; Dyna: finansowe sekcje = VIEW_FINANCE ∩ allowed_sections (fail-closed), writes→admin, upload XLSX→410; IDOR-y KPI/activities zamknięte; admin_snapshot JWT naprawiony; stary KPI Coach nudger za flagą (off); InfraReporter usunięty z kodu; frontend: syntetyczne trendy/sparklines/fake-healthy wycięte, TAC bez finansów w Insights, viewer nie pyta o feed/ranking. **Zweryfikowane na prodzie impersonacją** (viewer/TAC) |
| PR 2 | #772 | `78aab28` | `periods.py` (Warsaw, [start,end), custom≤366), `scope.py`, `cache.py` (klucz §4.6), `schemas.py` (koperta §4.5); migracja **0174**: 6 indeksów + views `analytics_current_pipeline` / `analytics_first_milestones` / `analytics_candidate_first_sources`; flagi `ANALYTICS_V1_MODE=off` / `DYNAREPORTER_MODE=read_only` / `KPI_COACH_V2_NUDGES_ENABLED=false`; entrypoint mirror |
| PR 3 | #775 | `6472b67` | `metrics.py` (jedyna implementacja §4.2) + router `/api/analytics/v1` (18 endpointów, koperta, capability guards, cache, 422 na zły okres, CloudTalk off→unavailable, 503 przy mode=off); `LegacyStatsDeprecationMiddleware` (Deprecation/Sunset/Link na legacy, body nietknięte) |
| PR 4 | #779 | `9d0a16e` | VERIFIER_ANCHORED_CTE→view (koniec 400d lookbacku), migracja **0175** (+`acceptance`); reports/recruitment totals = pierwsze milestone'y; konkursy = ta sama atrybucja (weryfikacje=verified); dashboard funnel = latest stage, typed `/recent-hires`; sources hired=DISTINCT (rate≤100%); tenders=close_reason; **KPI Coach v2**: KpiMetric zamiast UserActivity, targety **15 rozmów / 4 weryfikacje** dziennie (override→rola→default), CloudTalk off = KPI znika, **DRY-RUN** dopóki `KPI_COACH_V2_NUDGES_ENABLED=false` |
| PR 5 | #781 | `b90a45f` | `lib/stats-api.ts` (fail-closed: request tylko live+capability), `/me.analytics_v1_mode`, `StatsBoundary` (10 stanów; unavailable≠0), `/dashboard?view=&period=` (URL=źródło prawdy, default per rola, przełącznik multi-role), Insights period w URL. Shipowane na ciemno |
| PR 6 | #783 | `77c7bde` | FX z `fx_rates` (**brak kursu = unavailable, nigdy 1:1**); `/finance/trend` (prawdziwa arytmetyka miesięcy) + `/finance/clients`; bench/utilization; `client_orders.filled_at` (fakt, nie estymata; migracja **0176**); `financial_adjustments` (immutable, draft→approved, write admin / read DL+) |
| PR 7 | #785 | `cc0732e` | `analytics_metric_snapshots` + `analytics_cutovers` (migracja **0177**); idempotentny backfill Board (`POST /api/analytics/v1/admin/backfill-board-snapshots`, checksum, zero nadpisań); resolver legacy/live w `/finance/trend` (bez overlapu); `DYNAREPORTER_MODE=off`→410 + telemetria `legacy_dynareporter_hit`; redirecty **307** `/dynareporter/*`→`/insights?tab=` |
| PR 8 | #787 | — | Bramki blocking CI: zero nowych headów Alembica (baseline 25), zakaz CurrentUser-only mutacji w analytics/Dyna, viewer-safe denylist finansów na realnych odpowiedziach, kontrakt OpenAPI v1 vs committed snapshot |

## Świadome odstępstwa od planu

- **„Dokładnie jeden head Alembica"** → repo ma chronicznie 24 (teraz 25 — równoległa sesja dołożyła wiszący `0175_stage_notif_user_fk_cascade` z dublem numeru). Bramka pilnuje **zera nowych**; scalenie do jednego = osobna, ryzykowna operacja.
- **Body-level adaptery legacy→v1** (PR 3) → nagłówki deprecation teraz; podmiana body przy cutoverze (plan i tak zabrania zmian odpowiedzi w shadow).
- **Codegen typów TS z OpenAPI** → bramka kontrakt-snapshot; pełny codegen przy przejściu na live.
- **Cele redirectów** `/settings/data-imports` i `/assistant` nie istnieją w NEXUS → upload zostaje archiwum (POST i tak 410), mindy→insights.
- **Scoping DL→zespół** dla cudzych KPI → wymaga kanonicznego modelu zespołu rekruterów (nie istnieje); obecnie VIEW_TEAM_KPI = admin/HoR/DL.
- **Playwright PR-smoke 7 ról** → zablokowane brakiem sekretów `E2E_USER_*` (patrz niżej).

## Akcje operatorskie (wymagają Artura — plan §11)

1. **Rotacja sekretu InfraReporter** — klucz `ir_c45b…` usunięty z kodu, ale żyje w historii gita i jest aktywny po stronie `infrareporter.onrender.com`. Unieważnić/zrotować.
2. **Sekrety E2E**: `E2E_USER_EMAIL`/`E2E_USER_PASSWORD` (dedykowane konto prod) → pełne nightly E2E + przyszły PR-smoke ról.
3. **Aktywacja shadow**: Coolify env `ANALYTICS_V1_MODE=shadow` → endpointy v1 liczą, legacy nietknięte. Minimum **7 pełnych dni** (plan §7-8).
4. **Dry-run KPI Coach v2**: `KPI_COACH_NUDGER_ENABLED=true` przy `KPI_COACH_V2_NUDGES_ENABLED=false` → 7 dni logów „would send" do porównania.
5. **Backfill + cutover** (po shadow): `POST /api/analytics/v1/admin/backfill-board-snapshots`, potem `POST /admin/cutover {module:"finance", cutover_date:"YYYY-MM-01"}`.
6. **Kursy NBP**: `POST /api/fx/refresh` (admin) — bez kursów kontrakty walutowe raportują unavailable.
7. **Canary** (plan §8): `ANALYTICS_V1_MODE=live` — admin 48h → DL/HoR 48h → TAC 72h → user; bramki cutoveru z §8 (parity ≤1 PLN, ratio ≤0,1 pp, Chrome per rola).
8. **Decommission** (plan §Legacy): redirecty 307→308 po parity; usunięcie routerów po 30 dniach bez ruchu (telemetria `legacy_dynareporter_hit` w logach); `dr_*`/`allowed_sections` po 90 dniach + backup + restore drill + **osobna zgoda**.

## Znane ograniczenia

- Wpięcie zatwierdzonych `financial_adjustments` do sum `/finance/summary` — po pierwszych realnych korektach (do ustalenia znak/kategorie).
- `weekly_screenings` usunięte z katalogu KPI (brak kanonicznego źródła w ATS).
- `/reports/funnel` (phase3, template-stage, all-time) — inna semantyka, nieruszany.
- Panel „Moje KPI"/zespołu — od PR 4 liczy kanonicznie; rebranding na `PersonalKpiCoach`/`TeamKpiCoachSummary` przy canary.
