# W6 — Ustawienia, Kalendarz, Pomoc (poprawki responsywności)

Źródła: `docs/responsiveness-audit-2026-09-23/07-settings-calendar-misc.md` (bez pozycji dzwonka) + pozycje `09-pattern-scan.md` w moich plikach. Ścieżki względem `frontend/`.

## Ustalenia

| Ustalenie | Stan | Plik:linia | Uwagi |
|---|---|---|---|
| P0-1 Kalendarz „Tydzień” — widok 1 dnia poniżej md | zrobione | `components/calendar/WeekCalendar.tsx:84` (`GRID_COLUMNS`, `dayColumnVisibility`), `:305`, `:353` | Czysto w CSS (render SSR = klient): poniżej `md` widać tylko kolumnę wybranego dnia (`hidden md:block` na pozostałych), strzałki „Poprzedni/Następny dzień” (`md:hidden`), strzałki tygodnia `hidden md:flex` z aria-label, „Dzisiaj”. Stan to `selectedDay`, poniedziałek liczony z niego (useMemo) — desktop bez zmian. `?event=` ustawia dzień wydarzenia. Wysokość `100dvh-220px`. |
| P0-1 panel boczny 256 px | zrobione | `WeekCalendar.tsx:309` | `hidden xl:flex` (nie `lg` — przy lg+pasek aplikacji dzień miałby ~60 px; ≥1280 bez zmian). Poniżej xl: w nagłówku „Nowe wydarzenie” i „Panel” → `Sheet` z tym samym panelem (wybór dnia/wydarzenia zamyka arkusz). |
| P0-2 `/settings/templates` lista + edytor | zrobione | `app/settings/templates/page.tsx:588`, `:639`, `:715` | Poniżej lg lista ALBO edytor (przycisk „← Szablony”), `lg:h-[calc(100dvh-8rem)]` tylko od lg; nagłówek `flex-wrap`; formularz `grid-cols-1 sm:grid-cols-2`; kosz: `pointer-fine:opacity-0 …` + `hit-area` + aria-label; podgląd `85dvh`. |
| P0-3 / P1-1 / P2-6 dzwonek | poza zakresem | — | NotificationsDropdown należy do innego agenta. |
| P1-2 UserModal / ResetPasswordModal | zrobione | `components/settings/admin/UserModal.tsx:101`, `ResetPasswordModal.tsx:29` | Nakładka `p-4`, karta `max-h-[90dvh] overflow-y-auto`, `p-4 sm:p-6`, „Zamknij” z aria-label + hit-area (minimalna zmiana zamiast przepisywania na AppModal). |
| P1-3 PipelineTemplatesTab | zrobione | `components/settings/PipelineTemplatesTab.tsx` | Nagłówki `flex-wrap`, wiersz etapu `flex-wrap`, nazwa `min-w-0 flex-1 basis-40`, akcje w grupie `ml-auto`, etykiety Scorecard/Powiadomienia `hidden sm:inline` (nazwa z `title`), układ `lg:grid-cols-4`; wiersze powodów `flex-wrap`. |
| P1-4 Pule talentów — wiersz | zrobione | `app/talents/page.tsx:~458` | `flex-col sm:flex-row`, lewy blok `min-w-0 flex-1`, imię `truncate`, prawy `flex-wrap sm:shrink-0`. |
| P1-5 Agenda — karta pod listą | zrobione | `components/calendar/cycle/AgendaView.tsx:81` | Po kliknięciu (lista „Do zrobienia” i agenda) przewinięcie do karty, gdy `<1280px` (karta jest pod spodem do xl). Bez `behavior:"smooth"` — w powłoce Chrome go pomija (patrz `ProcedureTableOfContents`). |
| P1-6 Pomoc — procedury/klienci | zrobione | `v2/pages/HelpPageV2.tsx:146`, `HelpClientPlaybooksSection.tsx:64` | scrollIntoView treści po kliknięciu poniżej md; `min-w-0 scroll-mt-4`. |
| P1-7 typy wydarzeń `grid-cols-5` | zrobione | `WeekCalendar.tsx:1230` | `grid-cols-2 sm:grid-cols-3`, przycisk `min-h-10 break-words`. |
| P1-8 iCal `w-96` | zrobione | `WeekCalendar.tsx:1470` | `max-sm:fixed max-sm:inset-x-4 max-sm:top-24` (przycisk bywa w 2. wierszu po lewej); desktop `w-96` bez zmian. |
| P1-9 tabele Markdown | zrobione | `HelpPageV2.tsx:55` | `components.table` → `div.overflow-x-auto`; artykuł `p-4 md:p-8`. |
| P2-1 CycleBoard 7×180 | zrobione | `cycle/CycleBoard.tsx:52` | Telefon: kolumny 80% szerokości, `pointer-coarse:snap-x snap-mandatory`, `snap-start`. |
| P2-2 przełącznik „Zakres” | zrobione | `cycle/CalendarCycleScreen.tsx:182`, `Segmented` | `overflow-x-auto`, `whitespace-nowrap`, krótkie etykiety poniżej sm (Moi/Rekrutacje/Zespół), aria-label = pełna etykieta. |
| P2-3 strzałki tygodnia/„Dzisiaj” | zrobione | `WeekCalendar.tsx` nagłówek | 40 px na telefonie (`h-10 w-10 md:h-8 md:w-8`), aria-label. |
| P2-4 Od/Do datetime | zrobione | `WeekCalendar.tsx` CreateEventModal, `EventDetailModal.tsx:593`, `ScheduleInterviewModal.tsx:462` | `grid-cols-1 sm:grid-cols-2`. |
| P2-5 dialog `w-full` bez marginesu | poza zakresem | `components/ui/dialog.tsx` | Prymitywy — inny agent. |
| P2-7 kosz szablonu hover-only | zrobione | `templates/page.tsx:715` | wzorzec pointer-fine. |
| P2-8 nagłówek Szablony | zrobione | `templates/page.tsx` | `flex-wrap`. |
| P2-9 / P2-10 rate-benchmarks | zrobione | `app/settings/rate-benchmarks/page.tsx` | nagłówek `flex-wrap`; formularz `grid-cols-1 sm:grid-cols-3`, `sm:col-span-2`. |
| P2-11 scoring suwak | zrobione | `app/settings/scoring/page.tsx` | wiersz `flex-wrap sm:flex-nowrap`, etykieta `w-full sm:w-64`; także nagłówek edytora, nagłówek strony i wiersz profilu. |
| P2-12 AdminUsersTab nagłówek | zrobione | `components/settings/admin/AdminUsersTab.tsx` | `flex-wrap gap-3`. |
| P2-13 / pattern-scan AdminUsersTab tabela | zrobione | `AdminUsersTab.tsx:304` | `overflow-x-auto` + `min-w-[960px]` + przyklejona kolumna „Imię” (decyzja: scroll + sticky pierwsza kolumna); ikony akcji `pointer-coarse:p-2.5`. Kolumna akcji NIE przyklejona (decyzja mówi o pierwszej). |
| P2-14 PermissionsTab wyjątki | zrobione | `admin/PermissionsTab.tsx:841` | scrollIntoView szczegółów poniżej lg; lista `max-h-80 lg:max-h-[38rem]`. |
| P2-15 sticky lista Pomocy bez limitu | zrobione | `HelpPageV2.tsx`, `HelpClientPlaybooksSection.tsx` | `md:max-h-[calc(100dvh-12rem)] md:overflow-y-auto` na `nav`. |
| P2-16 podwójne dopełnienie | zrobione | `settings/cv-rules`, `ai`, `api-integration`, `rate-benchmarks`, `applications` + dodatkowo `dictionaries`, `entity-fields`, `diagnostics`, `chats`, `pipeline-templates` | padding strony tylko od md. |
| P2-17 pola < 16 px | zrobione częściowo | `app/settings/page.tsx` wyszukiwarka | `text-base md:text-[15px]`; reszta pól pokryta regułą `pointer-coarse` w globals.css (inny agent), prymityw `input` — poza zakresem. |
| P2-18 / P2-19 ScorecardSchemaBuilder | zrobione | `components/ScorecardSchemaBuilder.tsx` | ▲/▼ → przyciski 32 px z ChevronUp/Down i aria-label; nagłówek `flex-wrap`, tytuł `truncate`; `grid-cols-1 sm:grid-cols-3` (pattern-scan :255); `90dvh`; aria-label „Zamknij”. |
| P2-20 talents filtr kategorii | zrobione | `app/talents/page.tsx` | `flex-wrap`, `w-full sm:w-[220px]`. |
| P2-21 słowniki | zrobione | `app/settings/dictionaries/page.tsx` | klucz `hidden sm:block`, etykieta `min-w-0 break-words`, nagłówek `flex-wrap`. |
| P2-22 profil | zrobione | `app/profile/page.tsx` | `flex-col sm:flex-row`, karty `p-4 sm:p-6`; nakładka awatara `pointer-fine:group-hover` (pattern-scan :308). |
| Pattern-scan ImportTab 3/4/3 kolumny | zrobione | `components/settings/admin/ImportTab.tsx` | `sm:` warianty. |
| Pattern-scan SystemTab/Microsoft365Card 2 kolumny | zrobione | `SystemTab.tsx`, `Microsoft365Card.tsx` | `grid-cols-1 sm:grid-cols-2`. |
| Pattern-scan settings/page.tsx:780 skróty | zrobione | `app/settings/page.tsx` | `grid-cols-1 sm:grid-cols-2`. `:332` (3 kolumny, 1+2) zostawione — mieści się. |
| Pattern-scan contract-templates tabela | zrobione | `app/settings/contract-templates/page.tsx` | `overflow-x-auto`, nagłówek `flex-wrap`. |
| cv-rules komponenty (bez breakpointów) | zrobione | `CvRuleEditor.tsx`, `CvRuleHistoryTab.tsx`, `CvRulePreviewTab.tsx`, `app/settings/cv-rules/page.tsx` | `flex-wrap` w wierszach akcji/wersji/potwierdzenia usunięcia, `min-w-64`→`min-w-0 basis-64`; tabela reguł `min-w-[900px]` + przyklejona kolumna „Klient” (do xl, od xl wygląd jak dotąd). Formularze już miały `sm:grid-cols-2`. |
| StageNotificationRulesModal / StageRuleForm | zrobione | oba pliki | `flex-wrap` wierszy, `90dvh`, aria-label „Zamknij”. |
| Onboarding / harnessy | zrobione | `app/onboarding/{layout,page}.tsx`, `preview/calendar-cycle`, `preview/procedure-help` | `min-h-dvh`/`h-dvh`, `p-4 md:p-6`. |
| `min-h-screen` w pipeline-templates/diagnostics | pominięte | — | łagodne (min-h), usunięcie zmienia tło na desktopie. |
| Lista „+N” w kolumnie | zrobione | `WeekCalendar.tsx` OverflowEventsChip | `max-w-[calc(100vw-2rem)]`. |

## Testy
- `components/calendar/__tests__/WeekCalendar.test.tsx` — nowy `describe` „widok jednego dnia na telefonie” (3 testy): domyślnie dziś, strzałki dnia ±1 i „Dzisiaj”, strzałki tygodnia zachowują dzień tygodnia, `?event=` wybiera dzień wydarzenia. Kolumny mają `data-testid="calendar-day-column"` i `data-selected-day`. Istniejących testów nie zmieniałem.

## Poza zakresem
- `components/NotificationsDropdown.tsx` (P0-3, P1-1, P2-6), `components/ui/dialog.tsx` (P2-5), `components/ui/input.tsx` (P2-17) — inni agenci.
- `components/v2/forms/OnboardingDLV2.tsx`, `OnboardingRecruiterV2.tsx` (`min-h-screen`) — poza moim zakresem plików.
- `app/settings/linkedin-metrics/page.tsx` — już zmieniony przez inną sesję, nie dotykałem.

## Wyniki sprawdzeń
- `eslint` na 43 zmienionych plikach: 0 błędów, 14 ostrzeżeń — wszystkie istniejące wcześniej (nieużywane importy, exhaustive-deps).
- `tsc --noEmit -p .`: jedyny błąd w nieaktualnym `.next/types/app/settings/cv-rules/page.ts` (eksport `QUERY_KEY` istniał przed zmianą; znany problem przestarzałych `.next/types`), 0 błędów w `src/`.
- Vitest (maszyna pod obciążeniem, load average 400–500 — timeouty i `findBy` 1 s zawodzą losowo): pojedynczo zielone: WeekCalendar (36 w izolowanych przebiegach, różne testy padają zależnie od obciążenia; test „500 renderuje awarię” zielony pojedynczo), CalendarCycleScreen 10/10, ScheduleInterviewModal (flaky timeout 5 s, nie mój kod), pipeline-templates 3/3, UserModal 8/8, PermissionsTab 9/9, cv-rules page 8/8, rate-benchmarks 1/1, scoring 4/4, ai 6/6, settings page 17/17, help-client-playbooks 8/8, markdown-rendering 10/10, CvRuleEditor 9/9.
- `talents/pool-members-load-more` i `CvRulePreviewTab` padają — **tak samo na wersji bazowej plików** (sprawdzone podmianą pliku na `HEAD` i przywróceniem) → obciążenie maszyny, nie regresja. Do powtórzenia na spokojnej maszynie.
