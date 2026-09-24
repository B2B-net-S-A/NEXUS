# W5 — pulpit, Insights, Finanse, Cortex, DynaReporter: poprawki responsywności

Źródło: `docs/responsiveness-audit-2026-09-23/06-dashboard-insights-finance.md` (całość) + `04-clients-orders.md` P1-4 (AnalyticsTab).
Ścieżki względem `frontend/`. Nic nie było sprawdzane w przeglądarce — tylko kod, eslint, tsc i vitest.

## Ustalenia

| Ustalenie | Stan | plik:linia | Uwagi |
|---|---|---|---|
| P1-01 „Edytuj układ" przy siatce w trybie listy | zrobione | `src/components/v2/dashboard/custom/CustomDashboard.tsx:312`, `DashboardGrid.tsx:101` | `DashboardGrid` zgłasza tryb (`onModeChange`: `grid`/`list`) z tej samej szerokości kontenera, która przełącza na listę. Przycisk pokazuje się tylko przy `grid`. Usunięte `hidden md:inline-flex`. |
| P1-02 widżety w kafelkach reagują na szerokość okna | zrobione | `TileFrame.tsx:150` (`@container` na treści), `RecruitmentCompetenceDashboard.tsx:801`, `RecruitmentActivityDashboard.tsx:529`, `ContactOversightPanel.tsx:132`, `MyKpiWidget.tsx:150`, `TeamAllocationBoard.tsx:1666`, `AllocationWorkloadBoard.tsx:39`, `MyTasksDashboard.tsx:302` | Każdy widżet ma własny `@container` na korzeniu, więc działa też poza pulpitem (np. w Insights). Zamiana: `sm:`→`@xl:`, `md:`→`@2xl:`, `lg:`→`@4xl:` (896 px, więcej niż 782 px wymagane przez 3 kolumny kompetencji), `xl:`→`@5xl:`. MyKpiWidget: zmieniony tylko wariant `dashboard`; wariant `compact` w pasku górnym bez zmian. MyTasksDashboard dodany dodatkowo (ten sam błąd, `md:grid-cols-3` w kafelku). |
| P1-03 menu kafelka niewidoczne na dotyku | zrobione | `TileFrame.tsx:160` | `pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100 focus-within:opacity-100`; na dotyku menu jest zawsze widoczne. |
| P1-04 kafel liczby ucina wartość | zrobione | `MetricTileBody.tsx:85` | `min-w-0 flex-1`, liczba `truncate text-2xl @[12rem]:text-3xl` + `title`, wykresik `hidden @[14rem]:flex`. Składnia `@[12rem]` sprawdzona kompilatorem Tailwinda z `node_modules` (daje `@container (width >= 12rem)`). |
| P1-05 przełącznik rozdziałów Body Leasing | zrobione | `BodyLeasingPanel.tsx:75` | poniżej `sm`: pełna szerokość z `overflow-x-auto`, przyciski `shrink-0 whitespace-nowrap px-3`, ikony schowane poniżej 420 px. |
| P1-06 pasek okresu szerszy niż telefon | zrobione | `PeriodPicker.tsx:160` | korzeń `w-full items-stretch sm:w-auto sm:items-end`, grupa `max-w-full overflow-x-auto`, przyciski `shrink-0 whitespace-nowrap px-2.5 sm:px-3`, strzałki `pointer-coarse:p-2.5`, podpis wyrównany do lewej poniżej `sm`. |
| P1-07 nagłówek Rady się nie zawija | zrobione | `RadaNadzorczaPanel.tsx:78` | `flex-col lg:flex-row`, akapit `lg:max-w-xl`. |
| P1-08 kafle KPI z kwotami PLN wychodzą poza kartę | zrobione | `sections/_shared.tsx:78`, `InsightsClientsRanking.tsx:102`, `InsightsBoardKPI.tsx:128,171,235` + `DeltaTile`, `InsightsDlPortfolio.tsx`, `InsightsInviteLinks.tsx:79`, `AnalyticsTab.tsx:104` | Siatki `grid-cols-1 min-[420px]:grid-cols-2 …`; karta `min-w-0 p-4 sm:p-5`; wartość `truncate text-lg sm:text-2xl tabular-nums` + `title`. AnalyticsTab: `lg:grid-cols-4`, wartość `text-lg sm:text-xl`. |
| P1-09 lejek traci pasek na telefonie | zrobione | `RecruitmentFunnel.tsx:78` | etykieta `w-24 sm:w-44 shrink-0`, liczba `w-10 sm:w-12`, procent `hidden sm:block`, pasek `min-w-12`. |
| P1-10 tabela źródeł ucina kolumny | zrobione | `SourcesFunnelSection.tsx:48` | wewnętrzny `overflow-x-auto`, tabela `min-w-[520px]`, kolumna „Kanał" przyklejona poniżej `md`, sekcja `p-4 sm:p-6`. |
| P1-11 wartości trendu Rady tylko w `title` | zrobione | `InsightsBoardKPI.tsx:415` | `<details>` „Pokaż wartości” z listą miesięcy i kwot (niepełne z gwiazdką); podpisy miesięcy 11 px, na telefonie co drugi. `title` na słupku zostaje dla myszy. |
| P1-12 przełącznik trybów Finansów | zrobione | `src/app/finance/page.tsx:133` | poniżej `sm`: pełna szerokość z `overflow-x-auto`, przyciski `shrink-0 whitespace-nowrap`. |
| P1-13 edycja komórki finansów tylko dwuklikiem | zrobione | `src/components/finance/EditableCell.tsx:28` | przy `(pointer: coarse)` edycję otwiera pojedyncze stuknięcie; na dotyku widać ikonę ołówka (`pointer-coarse:inline`). Mysz bez zmian (dwuklik). Powiększanie przy fokusie w iOS załatwia wspólna reguła w `globals.css`. |
| P1-14 daty DynaReportera bez etykiet, 10 px | zrobione | `EmployeesManager.tsx:348` | widoczne etykiety `<label>` (Start akceleracji / Senior od / Expert od), `grid-cols-1 sm:grid-cols-3`, pola `text-xs py-1`. |
| P2-01 podwójny margines strony | zrobione | `CustomDashboard.tsx` (bez `p-4 sm:p-6`), `InsightsView.tsx:218`, `CortexView.tsx:99`, `dynareporter/page.tsx:122`, `dynareporter/profile/page.tsx:83`, dodatkowo `dynareporter/admin-dashboard/page.tsx:158` | Harness `/preview/custom-dashboard` owinięty w `p-4 md:p-6`, żeby wyglądał jak w powłoce. |
| P2-02 tabele rok do roku | zrobione | `InsightsBoardYoY.tsx:478` | `min-w-[560px]`, „Miesiąc” przyklejony (`bg-card`; wiersz sumy `bg-card` + gradient `from-muted/40`, żeby wyglądał tak samo); wybór karty poniżej `xl` przewija do tabeli (`scrollIntoView`, zabezpieczone w jsdom). |
| P2-03 rozbicie placementów na klientów | zrobione | `InsightsBoardYoY.tsx:592` | `min-w-[720px]`, kolumny lat `min-w-[12rem]`, „Miesiąc” przyklejony. |
| P2-04 ranking klientów | zrobione | `InsightsClientsRanking.tsx:148` | `min-w-[900px]`, „Klient” przyklejony (narożnik nagłówka `z-20`), przypis wyjaśniający `*` pod tabelą. |
| P2-05 przyklejona pierwsza kolumna | zrobione | `InsightsTeamTable.tsx:258`, `FinanceResultsTable.tsx:144`, `CompetenceMatrix.tsx:124`, `InsightsDlPortfolio.tsx` (Klient) | `SortableHeader` dostał prop `className`; `FinanceResultsTable` ma też `max-h-[60dvh]`. |
| P2-06 wiersz DL w portfelach | zrobione | `InsightsDlPortfolio.tsx:211` | `ml-auto` → `md:ml-auto`; wcięcie klienta `pl-6 sm:pl-14`. |
| P2-07 wykresy roczne | częściowo | `InsightsYearlyStats.tsx:177` | zrobione: `flex-wrap` nagłówka, podsumowanie `basis-full sm:basis-auto`, `p-4 sm:p-6`, `h-64 sm:h-80`. Nie zrobione: węższa oś Y i chowanie prawej osi poniżej `sm` — to wymaga JS (matchMedia) w recharts, a schowanie osi przestawiłoby linie na złą skalę. Tooltip po stuknięciu — do sprawdzenia na urządzeniu. |
| P2-08 próg wyścigu tylko w `title` | zrobione | `InsightsRaces.tsx:400` | ten sam tekst jako przypis pod rankingiem rekomendacji; `title` zostaje (test go wymaga). |
| P2-09 małe cele dotykowe | zrobione | `PeriodPicker.tsx` (strzałki), `InsightsSectionNav.tsx:76`, `InsightsBoardYoY.tsx` (zakładki grup) | `pointer-coarse:p-2.5` / `pointer-coarse:min-h-10`. |
| P2-10 filtr dat w „Zmianach w zamówieniach” | zrobione | `OrderChangesPanel.tsx:232` | grupa `w-full sm:w-auto`, pola `min-w-0 flex-1 sm:w-[150px] sm:flex-none`. |
| P2-11 Zamówienia PDF — długi stos kolumn | zrobione | `OrderPdfsPanel.tsx:79` | listy `max-h-64 overflow-y-auto lg:max-h-none`; wybór klienta poniżej `lg` przewija do plików. Kolumna plików w opakowaniu `grid`, więc na desktopie dalej się rozciąga. |
| P2-12 filtr kategorii katalogu na telefonie | zrobione | `TileCatalogSheet.tsx:91` | chipy `sm:hidden` z przewijaniem w poziomie, te same filtry i liczniki. |
| P2-13 uchwyty przeciągania i zmiany rozmiaru | zrobione | `TileFrame.tsx:71`, `DashboardGrid.tsx:128` | uchwyt `hit-area touch-none`; uchwyt rozmiaru 32 px przez `pointer-coarse:[&_.react-resizable-handle]:h-8! w-8!` na siatce (bez zmian w `globals.css`). Selektor sprawdzony kompilatorem Tailwinda. |
| P2-14 lejek w kafelku metryki | zrobione | `MetricTileBody.tsx:152` | `grid-cols-[minmax(0,8rem)_1fr_auto]`, etykieta `min-w-0 truncate` + `title`. |
| P2-15 wyszukiwarka technologii Cortex | zrobione | `SkillSearchPanel.tsx:104` | `min-w-0 basis-full sm:basis-auto sm:min-w-[16rem]`, karta `p-4 sm:p-6`. |
| P2-16 nagrody pod podium Ligi | zrobione | `ChampionsSection.tsx:431` | komórka `min-w-0`, kwota `truncate text-xs sm:text-sm tabular-nums` + `title`. |
| P2-17 tekst poniżej 11 px | zrobione | `InsightsBoardKPI.tsx` (11 px), `StatsBoundary.tsx:75`, wszystkie `text-[10px]` w `src/app/dynareporter/**` → `text-[11px]` | Nagłówki tabel DynaReportera: 11 px zamiast proponowanego `text-xs` (mniejsza zmiana wyglądu desktopu). |
| P2-18 powiększanie iOS przy polach | pominięte (zrobione globalnie) | `src/app/globals.css` | wspólna reguła `@media (pointer: coarse)` z innego agenta już to pokrywa. |
| P2-19 nagrody w ScoringConfig | zrobione | `ScoringConfig.tsx:138` | `grid-cols-1 sm:grid-cols-3`. |
| 04 P1-4 AnalyticsTab — kwoty wychodzą z kafli | zrobione | `src/components/AnalyticsTab.tsx:104` | patrz P1-08. |
| wysokości vh → dvh (w zakresie) | zrobione | `DzReviewDialog.tsx:257,439`, `FinanceResultsTable.tsx` | |

## Zmienione testy
- `src/components/finance/__tests__/EditableCell.test.tsx` — dopisane 2 testy: przy wskaźniku coarse pojedyncze stuknięcie otwiera edycję; myszą pojedyncze kliknięcie nie otwiera, dwuklik otwiera (`matchMedia` podstawiane na czas testu, bo jsdom go nie ma). Żaden istniejący test nie wymagał zmiany.

## Poza zakresem
- `src/app/globals.css` — nie ruszany. Uchwyt rozmiaru jest powiększony klasą na siatce.
- `src/app/dashboard/delivery-lead/_components/DlClientsTable.tsx` jest zmodyfikowany w drzewie roboczym, ale nie przeze mnie (inny agent).
- `MyClientsAlertsPanel.tsx:170` (`sm:flex-row` karty w kafelku) — działa, można przejść na `@xl:` przy okazji; nie ma go w raporcie.

## Wyniki sprawdzeń
- `npx eslint` na wszystkich zmienionych plikach: czysto.
- `npx tsc --noEmit -p .`: jedyny błąd to nieaktualne `.next/types/app/settings/cv-rules/page.ts` (znana pułapka, nie w moim zakresie, `rm -rf .next/types`); żadnych błędów w moich plikach.
- Tymczasowy config vitest z `asyncUtilTimeout` 30 s (`.w5-vitest.config.ts`, `src/test/.w5-rtl-timeout.ts`) był używany tylko do powtórek i jest usunięty.
- `npx vitest` (custom dashboard, finance, AnalyticsTab, insights/__tests__): 139/141; dwa czerwone testy finance (`FinanceResultsTab`, `FinanceArchiveTab`) padały na domyślnym 1 s w `findBy*` przy obciążeniu maszyny (load average 300–1000). Po powtórce z `asyncUtilTimeout` 30 s: 8/8 zielone. `FinanceArchiveTab` nie importuje niczego, co zmieniałem.
- Reszta (insights sections/chapters, v2/dashboard, priority-work, kpi, candidate-contact, preview, cortex, dynareporter): 37 plików / 283 testy: 282 zielone. Jeden czerwony (`RecruitmentCompetenceDashboard.test.tsx` — reset wyszukiwania po zmianie zakresu) i 5 plików, których worker nie wystartował (timeout pul przy load average ~1000). Po powtórce pojedynczo (`--maxWorkers=1`): 6 plików / 32 testy zielone, w tym RecruitmentCompetenceDashboard, WidgetState, MyPriorityQueue, AllocationWorkloadBoard, ContactOversightPanel, MyKpiWidget. Zmiany w tych widżetach dotyczą wyłącznie klas CSS.
- Klasy Tailwinda nieużywane wcześniej w repo (`@[12rem]:`, `pointer-coarse:[&_…]:h-8!`, `max-sm:[&:nth-child(even)]:invisible`, `bg-linear-to-r from-muted/40`) sprawdzone kompilatorem `tailwindcss` z `node_modules`: generują oczekiwany CSS.
- Nie sprawdzone w przeglądarce (niepotwierdzone): wygląd na 375/768/1024, zachowanie dotyku.
