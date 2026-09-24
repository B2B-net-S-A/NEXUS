# 09 — Skan wzorców responsywności (frontend NEXUS)

Data: 2026-09-23 · gałąź `claude/app-responsiveness-audit-cb0a5f` (HEAD `5f7d89d1f`) · tryb: tylko odczyt.
Zakres: `frontend/src/**/*.tsx|ts`, bez `__tests__/`, `*.test.*`; `src/app/preview/**` liczone osobno (43 pliki, w liczbach poniżej pominięte, chyba że napisano inaczej).
Metoda: skrypt `scan.py` (ten katalog) wycina każdy atrybut `className=` (łącznie z `cn(...)`/template stringami) i traktuje go jako „ten sam element”; wyniki surowe w `scan.json`, `tables.json`. To heurystyka — tam, gdzie wynik był wątpliwy, sprawdziłem kod ręcznie (oznaczone „sprawdzone”). Nic nie było oglądane w przeglądarce — kolizje wizualne są **niepotwierdzone zrzutem**.

## Podsumowanie liczbowe

| # | Wzorzec | Wynik | Ocena |
|---|---|---|---|
| — | Pliki TSX (bez testów i preview) | **717** | — |
| — | …z jakimkolwiek prefiksem `sm:/md:/lg:/xl:/2xl:` | **210 (29%)** | niskie pokrycie |
| — | Użycia prefiksów łącznie | sm 317 · md 153 · lg 106 · xl 170 · 2xl 8 · `max-*` 1 (≈755) | mało jak na 717 plików |
| 1 | Stałe szerokości ≥360 px bez wariantu responsywnego | 30 trafień arbitralnych (`w-[…]`), z tego **realnych problemów 4**; + `w-96` ×3, `w-80` ×7 | niski wolumen, kilka realnych błędów |
| 2 | `grid-cols-N` (N≥2) bez `sm:/md:/lg:/xl:` na tym samym elemencie | **114** (N=2: 66, N=3: 23, arbitralne: 19, 4:1, 5:2, 7:2, 12:1) | średnie |
| 3 | `<table>`/`<Table>` bez przewijania poziomego | 85 tabel: 8 `ui/Table` (same się owijają), 62 owinięte, **15 nieowiniętych** (w tym 3 w `overflow-hidden` = obcinanie) | średnie |
| 4 | `h-screen`/`min-h-screen`/`vh` | **97** (min-h-screen 18, h-screen 2, `100vh` 11, `max-h-[Nvh]` 42, `h-[Nvh]` 13…); **dvh/svh: 0** | wysokie — root shell na `h-screen` |
| 5 | Akcje ujawniane tylko hoverem | **9** (4 bez żadnej alternatywy, 5 z `focus-visible`); alternatywa dotykowa: **0** | niski wolumen |
| 6 | Mały tekst `text-[9/10/11px]` | **613** użyć w **178** plikach (11px: 363, 10px: 230, 9px: 20) | wysoki |
| 7 | Pola formularzy <16 px (zoom iOS) | **wszystkie**: prymitywy `Input/Textarea/Select` = `text-sm`, a `globals.css` (`@layer base`) wymusza `text-sm` na każdym `input/select/textarea` | wysokie (systemowe, jedna poprawka) |
| 8 | Pliki z układem flex/grid i **bez żadnego prefiksu** | **362 z 714** (51%), 87 605 linii | wysokie |
| 9 | `whitespace-nowrap` bez `truncate/overflow-hidden/min-w-0/shrink-0` | 68 z 72 | niskie (większość w komórkach tabel w scrollu) |
| 10 | Pływające `fixed` w rogach | 18 elementów; prawy dolny róg: **10** kandydatów do nakładania się; `safe-area-inset`: **0** | średnie |
| 11 | `export const viewport` w `app/layout.tsx` | **brak** → domyślne Next.js `width=device-width, initial-scale=1`; zoom **nie** zablokowany | OK |
| 12 | Hooki mediów / szuflada mobilna | `useMediaQuery`/`useIsMobile`: **0**; `matchMedia` do układu: 1 plik; `innerWidth`: 2; szuflada nawigacji mobilnej **jest** | OK / ubogie |
| + | Przyciski `size="sm"` (h-8 = 32 px) | **707** użyć; `icon-sm` (32 px) 33; `icon` (36 px) 16 | cel dotykowy <44 px |

## Najgorsze miejsca (priorytet naprawy)

1. **Root shell na `h-screen`** — `src/components/v2/shell/AppShellV2.tsx:166` (`flex h-screen overflow-hidden`). Cała aplikacja przewija się w `<main overflow-y-auto>` w kontenerze o wysokości `100vh`. W Safari iOS / Chrome Android `100vh` = wysokość z **schowanym** paskiem adresu, więc dół każdej strony (przyciski formularzy, stopki, paski zbiorcze w treści) chowa się pod paskiem przeglądarki. Jedna zmiana (`h-dvh`) naprawia wszystkie ekrany wewnątrz shellu. W repo jest **0** użyć `dvh/svh`.
2. **Pola formularzy 14 px → auto-zoom iOS przy każdym fokusie** — `globals.css:541–551` (`@layer base`: `input[type=text|email|…], select, textarea { @apply text-sm }`) plus `ui/input.tsx:19`, `ui/textarea.tsx:16`, `ui/select.tsx:19` (plain `text-sm`, nie shadcn-owe `text-base md:text-sm`). Dotyczy 242 `<Input>`, 47 `<Textarea>` i 549 surowych pól (298 input, 175 select, 76 textarea). Poprawka w 4 miejscach.
3. **`NotificationsDropdown`** (dzwonek w topbarze, widoczny na każdym ekranie):
   - `src/components/NotificationsDropdown.tsx:643` — lista `absolute right-0 w-96` (384 px) zakotwiczona do dzwonka; na 375 px lewa krawędź wychodzi poza ekran (dzwonek nie stoi przy samej prawej krawędzi). *Niepotwierdzone zrzutem.*
   - `src/components/NotificationsDropdown.tsx:468` — popup `fixed bottom-6 right-6 max-w-sm w-full`: przy `w-full` + `right-6` element ma szerokość viewportu przesuniętą o 24 px w lewo → ucięty lewy brzeg na telefonie.
4. **Panel propozycji „Do przejrzenia”** — `src/components/v2/recruitment/ProposalPanel.tsx:116,131` (`aside w-[372px] shrink-0`) w rzędzie `flex` (`ProposalsSegment.tsx:416`) bez wariantu mobilnego: na telefonie lista kandydatów ściska się do zera, panel wychodzi poza ekran.
5. **Prymityw `Dialog`** — `src/components/ui/dialog.tsx:59`: `w-full` + `max-w-lg` (i większe) bez marginesu bocznego → na telefonie okno od krawędzi do krawędzi (zaokrąglone rogi przycięte, brak „oddechu”), a `max-h-[90vh]` ma ten sam problem co pkt 1. Dotyczy wszystkich modali (`AppModal`, dialogi zamówień itd.).
6. **Pokrycie responsywne największych ekranów roboczych** — pliki > 800 linii bez ani jednego prefiksu: `OrdersAndContractsTab.tsx` (1793), `MultiConsultantOrdersTab.tsx` (1312), `PipelineCandidateDock.tsx` (1256), `ChampionVerificationChecklist.tsx` (879), `NotificationsDropdown.tsx` (843), `ClientContractRegister.tsx` (834, 7× `w-[≥100px]`), `JobChatTab.tsx`/`CandidateChatTab.tsx` (833/830). Pełna lista w Załączniku F.
7. **Tabele obcinane zamiast przewijane** (owinięte w `overflow-hidden`, sprawdzone): `app/dashboard/delivery-lead/_components/DlClientsTable.tsx:26`, `components/marketplace/MarketplaceTable.tsx:150`, `app/contracts/[id]/page.tsx:2287`.
8. **Publiczne ekrany z zerowym pokryciem prefiksami** (otwierane z telefonu przez kandydatów/klientów): `app/engagement/**` (0 prefiksów), `app/share/**` (1), `app/sign/**` (1), `app/apply/**` (5), `app/login/**` (0; `AuthShell` 4), `app/register/**` (0). Wyjątek: strona kariery (`components/career/**` — 1 prefiks, ale `career.css` ma **13** `@media`, więc jest responsywna w CSS).

## 1. Stałe szerokości ≥360 px

Wzorzec: `w-[N]`, `min-w-[N]`, `max-w-[N]` (px lub rem) i `style={{ width|minWidth: N }}` z N≥360, bez prefiksu na samej klasie i bez `sm:/md:…w-*` na tym samym elemencie. Klasy z prefiksem (`sm:w-[420px]` w JarvisPanel itp.) są poprawne i nie są liczone. Dodatkowo policzyłem skalę numeryczną Tailwind v4 (`w-N` = N×4 px).

| Typ | Trafień | Realny problem | Przykłady |
|---|---|---|---|
| `max-w-[1100–2400px]` na kontenerach stron | 21 | **nie** (to sufit, na telefonie szerokość i tak = 100%) | `CandidatesListV2.tsx:1388`, `ContractsListV2.tsx:770`, `HelpPageV2.tsx:187` |
| `max-w-[360–420px]` z `w-full` | 3 | nie | `MyPeoplePanel.tsx:247`, `KanbanBoardV2.tsx:2653`, `TopbarV2.tsx:117` |
| `min-w-[560–1100px]` na tabeli | 4 | **nie**, jeśli tabela w scrollu — sprawdzone: `ClientsListV2.tsx:692` (w `ui/Table`, sam się przewija), `PermissionsTab.tsx:598` (`hidden md:block` + wersja mobilna — wzorcowe), `StageBreakdownSection.tsx:101`, `CandidateListPreview.tsx:74` | — |
| **`w-[372px]` aside w rzędzie flex** | 2 | **tak** | `components/v2/recruitment/ProposalPanel.tsx:116,131` |
| `style` inline | 3 | nie — fałszywe trafienia: `JobsListV2.tsx:145` (string media query 1536 px), `B2BContractGeneratorV2.tsx:442` (okno wydruku), `career/og.tsx:14` (obraz OG 1200 px) | — |
| `w-96` (384 px) | 3 | **tak** (>375 px) | `NotificationsDropdown.tsx:643`, `ScoreBreakdownTooltip.tsx:66` (`absolute right-0`), `calendar/WeekCalendar.tsx:1366` (`absolute right-0`) |
| `w-80` (320 px) | 7 | graniczne (mieści się, ale bez marginesu na 360 px) | `settings/templates/page.tsx:629` (`w-80 shrink-0` kolumna — **tak**, stała kolumna obok treści), popovery `ContractsListV2.tsx:919`, `MarkEmployedAction.tsx:123`, `StageFilterPanel.tsx:129`, `CandidateProcessCell.tsx:79`, `CandidateFilterBar.tsx:357` |
| `w-72` (288 px) | 16 | nie | — |

Podział wg kontekstu (dla trafień arbitralnych, heurystyka po nazwie pliku/klasach): dialogi/popovery 2, kolumny tabel 4, układ strony 24 — ale układ strony to prawie wyłącznie nieszkodliwe `max-w-[…]`.

**Wniosek:** stałe szerokości to **nie** jest główny problem tej aplikacji; szkodzą pojedyncze panele boczne i rozwijane listy 384 px.

## 2. Siatki bez wariantu responsywnego

114 elementów z `grid-cols-N` (N≥2) lub `grid-cols-[…]` bez żadnego `sm:/md:/lg:/xl:grid-cols-*` (dla porównania: 315 użyć responsywnych `*:grid-cols-*` w repo — wzorzec jest znany, ale nie stosowany konsekwentnie).

| N | Liczba | Ryzyko na 375 px |
|---|---|---|
| 2 | 66 | niskie/średnie: w formularzach dialogów (`EditOrderDialog` 4, `NewContractorOrderDialog` 3, `ExtendOrderDialog` 2, `OrderSlideOver` 2) dwa pola po ~150 px z etykietami → ciasno |
| 3 | 23 | średnie: `settings/page.tsx:332`, `rate-benchmarks/page.tsx:315`, `ImportTab.tsx:77/178`, `B2BContractGeneratorV2.tsx:3928/3965`, `ContactQueueWorkspace.tsx:287`, `InterviewFeedbackModal.tsx:453`, `DebriefDialog.tsx:193` |
| 4–7 | 5 | wysokie: `ImportTab.tsx:160` (4), `WeekCalendar.tsx:972/979` (7 — mini-kalendarz, akceptowalne), `WeekCalendar.tsx:1129` (5), `JarvisAppearanceForm.tsx:77` (5) |
| 12 | 1 | brak — `CustomDashboard.tsx:399` to szkielet ładowania z `col-span-12 md:col-span-3` (sprawdzone) |
| arbitralne | 19 | głównie etykieta+wartość (`grid-cols-[76px_minmax(0,1fr)]` w `PersonPanel`, `ScreeningForm`, `workbench-chrome`) — **OK**; ryzykowne: `WeekCalendar.tsx:328/499/699` (`48px_repeat(7,1fr)` — tydzień na telefonie ≈ 46 px/dzień), `calendar/cycle/CycleBoard.tsx:50` (`repeat(7,minmax(180px,1fr))` = 1260 px — wymaga scrolla), `AppShell.tsx:611` (`1fr_1.2fr`), `CvHandoffWorkbench.tsx:1050`, `VerifiedRateFields.tsx:83` |

Najwięcej w jednym pliku: `components/AppShell.tsx` (14 — legacy `EditJobModal`/`JobFormFields`, nadal w użyciu), `calendar/WeekCalendar.tsx` (7). Pełna lista: Załączniki A i B.

## 3. Tabele bez przewijania poziomego

- 85 znaczników `<table>`/`<Table>`.
- `ui/table.tsx` owija tabelę w `div.relative.w-full.overflow-auto` — 8 użyć jest bezpiecznych z definicji.
- Z 77 pozostałych: 60 ma `overflow-x-auto`/`overflow-auto` w 6 liniach wyżej, 62 w 12 liniach; **15 nie ma** (heurystyka — owinięcie może być wyżej, w rodzicu).
- Sprawdzone ręcznie jako realnie obcinające (`overflow-hidden` zamiast `overflow-x-auto`): `DlClientsTable.tsx:26`, `MarketplaceTable.tsx:150`, `contracts/[id]/page.tsx:2287`. `AdminUsersTab.tsx:301` i `OrderMailQueue.tsx:678` — bez żadnego owinięcia.

Pełna lista 15: Załącznik C. Tabele `sticky left-0` (pierwsza kolumna przyklejona) — 11 w 5 plikach (`linkedin-metrics`, `contracts/analytics`, `CandidateListPreview`, `PermissionsTab`, `TechMapHeatmap`) — to dobry wzorzec dla szerokich tabel.

## 4. Wysokość viewportu (`vh`/`screen`)

97 użyć, **0** `dvh/svh/lvh`.

| Token | Liczba | Komentarz |
|---|---|---|
| `max-h-[Nvh]` | 42 | modale/popovery (`max-h-[90vh]` w `ui/dialog.tsx`) — na iOS przy otwartej klawiaturze okno może wyjść poza widoczny obszar |
| `min-h-screen` | 18 | strony publiczne i layouty (`apply`, `cv`, `sign`, `engagement`, `onboarding`, `login`, `AuthShell`) — łagodne (min-h), ale dają zbędny scroll/ukryte stopki |
| `h-[Nvh]` | 13 | — |
| `100vh` (w `calc`/style) | 11 | `candidates/layout.tsx:31`, `jobs/layout.tsx:21` (`max-h-[calc(100vh-7rem)]` rail — tylko `lg:`), `JobReadinessDock.tsx:883`, `workbench-chrome.tsx:455`, `CandidatesListV2.tsx:1636`, `ds/Kanban.tsx:50`, `JarvisPanel.tsx:67` (`sm:`), `cv/i/[token]/page.tsx:569/878`, `cv/[token]/page.tsx:139`, `global-error.tsx:36` |
| `h-[calc(100vh-Npx)]` | 4 | `KanbanBoardV2.tsx:1563/2551`, `WeekCalendar.tsx:270`, `settings/templates/page.tsx:581` |
| `h-screen` | 2 | **`AppShellV2.tsx:166` (root całej aplikacji)**, `login4.tsx:41` |
| `min-h-[Nvh]` | 5 | — |

Najwięcej w plikach: `AppShell.tsx` 5, `candidate-profile/HistoryTab.tsx` 5, `JobChatTab.tsx`/`CandidateChatTab.tsx` po 3. Lista pełnoekranowych: Załącznik D.

## 5. Akcje widoczne tylko po najechaniu

W repo jest tylko 18 użyć `group-hover`, więc problem jest mały. 11 × `group-hover:opacity-100`, z czego 2 są widoczne domyślnie (`opacity-60/70`). Pozostałe 9:

| plik:linia | Co chowa | Alternatywa klawiatura | Alternatywa dotyk |
|---|---|---|---|
| `app/settings/templates/page.tsx:703` | akcje szablonu (usuń) | brak | brak |
| `app/clients/[id]/page.tsx:344` | przycisk usuwania notatki | brak | brak |
| `components/v2/pages/JobChatTab.tsx:720` | „Odpowiedz”, reakcje wiadomości | brak | brak |
| `components/v2/pages/CandidateChatTab.tsx:717` | „Odpowiedz”, reakcje wiadomości | brak | brak |
| `app/profile/page.tsx:308` | zmiana avatara | `focus-visible` | brak |
| `components/NotificationsDropdown.tsx:781` | akcja na powiadomieniu | `group-focus-within`, `focus-visible` | brak |
| `components/v2/pages/CandidateSearchView.tsx:1042` | usuń | `focus-visible` | brak |
| `components/v2/pages/KanbanBoardV2.tsx:1084` | „usuń z rekrutacji” na karcie | `focus-visible` | brak |
| `components/v2/dashboard/custom/TileFrame.tsx:155` | menu kafelka pulpitu | `focus-within` | brak |

Na urządzeniach dotykowych przyciski są niewidoczne, ale klikalne „w ciemno” (opacity 0 nadal łapie tap). Tailwind v4 ma warianty `pointer-coarse:`/`pointer-fine:` — w repo używa ich **tylko** `KanbanBoardV2.tsx` (37×, do układu kart), nigdzie do odsłaniania akcji.

## 6. Mały tekst

613 użyć w 178 plikach: `text-[11px]` 363, `text-[10px]` 230, `text-[9px]` 20. Dodatkowo `ui/command.tsx:48` ustawia nagłówki grup palety ⌘K na 10 px. 9 px występuje prawie tylko w `KanbanBoardV2.tsx` (11×).

| Plik | Razem | 9 | 10 | 11 |
|---|---|---|---|---|
| `components/ChampionVerificationChecklist.tsx` | 36 | 0 | 8 | 28 |
| `components/v2/pages/JobsListV2.tsx` | 19 | 1 | 6 | 12 |
| `components/v2/jobs/JobReadinessDock.tsx` | 17 | 0 | 3 | 14 |
| `components/v2/pages/KanbanBoardV2.tsx` | 17 | 11 | 3 | 3 |
| `components/client-profile/orders/OrderGroupCard.tsx` | 13 | 0 | 12 | 1 |
| `components/v2/pages/ContractsListV2.tsx` | 13 | 0 | 7 | 6 |
| `app/dynareporter/admin-dashboard/page.tsx` | 11 | 0 | 11 | 0 |
| `app/dynareporter/admin-dashboard/_modules/EmployeesManager.tsx` | 11 | 0 | 11 | 0 |

(30 pierwszych: Załącznik E.)

## 7. Pola formularzy a zoom iOS

iOS Safari powiększa stronę przy fokusie w polu o `font-size` < 16 px.

| Miejsce | Klasa | Stan |
|---|---|---|
| `components/ui/input.tsx:19` | `h-10 … text-sm` | 14 px, bez `text-base md:text-sm` |
| `components/ui/textarea.tsx:16` | `… text-sm` | 14 px |
| `components/ui/select.tsx:19` (trigger Radix — to przycisk, nie pole, więc nie wywołuje zoomu) | `text-sm` | nieistotne dla zoomu |
| `app/globals.css:541–551` (`@layer base`) | `input[type=text/email/password/number/tel/url/date/datetime-local], select, textarea { @apply text-sm }` | **wymusza 14 px na każdym natywnym polu w aplikacji** |

Zasięg: 242 `<Input>`, 47 `<Textarea>`, 549 natywnych pól (298 `input`, 175 `select`, 76 `textarea`); tylko 4 mają jawnie jeszcze mniejszy tekst (`text-xs`). Żadne pole nie ma `text-base` ani wariantu `md:text-sm`. Poprawka: w regule z `globals.css` i dwóch prymitywach `text-base md:text-sm`. Zoom nie jest blokowany w viewport (pkt 11), więc to uciążliwość, nie blokada.

## 8. Komponenty „tylko desktop” (brak jakiegokolwiek prefiksu)

362 z 714 plików TSX w `src/app` i `src/components` (51%) ma klasy `flex`/`grid`, ale ani jednego `sm:/md:/lg:/xl:/2xl:`; łącznie 87 605 linii. Wiele z nich to drobne komponenty, dla których brak prefiksu jest poprawny (rząd dwóch ikon) — liczy się rozmiar i rola ekranu.

| Linie | Plik |
|---|---|
| 1793 | `components/OrdersAndContractsTab.tsx` |
| 1312 | `components/client-profile/orders/MultiConsultantOrdersTab.tsx` |
| 1256 | `components/v2/jobs/PipelineCandidateDock.tsx` |
| 879 | `components/ChampionVerificationChecklist.tsx` |
| 843 | `components/NotificationsDropdown.tsx` |
| 834 | `components/contracts/ClientContractRegister.tsx` |
| 833 | `components/v2/pages/JobChatTab.tsx` |
| 830 | `components/v2/pages/CandidateChatTab.tsx` |
| 830 | `app/dynareporter/admin-dashboard/_modules/MasterDataManager.tsx` |
| 784 | `app/settings/cv-rules/page.tsx` |
| 771 | `app/settings/templates/page.tsx` |
| 763 | `components/v2/jobs/workbench-chrome.tsx` |
| 730 | `components/calendar/EventDetailModal.tsx` |
| 700 | `components/FrameworkContractsTab.tsx` |
| 695 | `components/calendar/ScheduleInterviewModal.tsx` |
| 689 | `components/v2/filters/ActiveFilterChips.tsx` |
| 688 | `components/finance/MdImportWorkspace.tsx` |
| 685 | `components/v2/modals/CVBrandedEditModal.tsx` |
| 663 | `components/v2/modals/CVGeneratorV2.tsx` |
| 627 | `components/ds/VirtualTable.tsx` |
| 624 | `components/v2/recruitment/PeopleTable.tsx` |
| 621 | `components/v2/files/FilePreviewModal.tsx` |

Strony (`page.tsx`) bez prefiksów: 22, m.in. `settings/cv-rules` (784), `settings/templates` (771), `settings/api-integration` (483), `settings/rate-benchmarks` (462), `settings/scoring` (431), `login` (391), `register` (305), `finance` (236), `engagement/[token]` (226, **publiczna**). Pełna lista 60: Załącznik F.

## 9. `whitespace-nowrap`

72 elementy, 68 bez `truncate`/`overflow-hidden`/`min-w-0`/`shrink-0` w tej samej klasie. Większość siedzi w komórkach tabel (kwoty, daty) owiniętych w scroll — tam `nowrap` jest zamierzony. Skupiska: `ContractsListV2.tsx` 8, `contracts/FinancialRatesCard.tsx` 7 (karta, nie tabela — ryzyko wypychania), `JobListCells.tsx` 4, `contracts/analytics/page.tsx` 3, `InsightsBoardYoY.tsx` 3, `FinanceResultsTable.tsx` 3. Załącznik G.

## 10. Elementy pływające (`fixed`) — kolizje

18 pływających elementów poza pełnoekranowymi nakładkami (`inset-0`). Brak `env(safe-area-inset-*)` gdziekolwiek w repo.

| Element | plik:linia | Pozycja | z-index | Uwaga mobilna |
|---|---|---|---|---|
| Toast globalny | `components/Toast.tsx:136` | bottom-4 right-4 | 9999 | — |
| Toasty lokalne ekranów | `CandidatesListV2.tsx:2074`, `ClientsListV2.tsx:1016`, `HelpPageV2.tsx:381`, `QuickActionsV2.tsx:177` | bottom-4 right-4 | 9999 | 5 osobnych systemów toastów w tym samym rogu |
| Toasty lokalne (wyżej) | `ContractsListV2.tsx:1380`, `ClientContractRegister.tsx:816` | bottom-24 right-4 | 9999 | — |
| Toast legacy | `components/AppShell.tsx:156` | bottom-6 right-6 | 200 | — |
| Popup powiadomienia | `NotificationsDropdown.tsx:468` | bottom-6 right-6, `max-w-sm w-full` | 300 | **wychodzi 24 px za lewą krawędź** |
| KPI nudge | `v2/kpi/KpiNudgeToaster.tsx:108` | top-20 right-4, `max-w-sm` | 10000 | — |
| Maskotka Jarvisa | `jarvis/JarvisMascot.tsx:47` | bottom-4 right-4 (sm: bottom-5 right-5) | 30 | w tym samym rogu co toasty |
| Postać „Moi ludzie” | `v2/my-people/MyPeopleLauncher.tsx:102` | bottom-5 right-5 (+dymek `max-w-[260px]`) | 30 | ustępuje Jarvisowi (logika), ale nie toastom |
| Panel Jarvisa | `jarvis/JarvisPanel.tsx:67` | mobile: `inset-0` (pełny ekran), sm: bottom-24 right-5 `w-[420px]` | 40 | poprawny wariant mobilny |
| Panel „Moi ludzie” | `v2/my-people/MyPeoplePanel.tsx:247` | top-12 right-0 bottom-0, `w-full max-w-[420px]` | 40 | na telefonie zakrywa cały ekran pod topbarem |
| Dok kanbanu | `v2/pages/KanbanBoardV2.tsx:2653` | top-12 right-0 bottom-0, `w-full max-w-[380px]` | 30 | jw. |
| Pasek zbiorczy kandydatów | `v2/candidates/CandidateBulkBar.tsx:49` | bottom-5 left-1/2 −translate | 40 | `left-1/2` bez `w-`/`max-w` → dostępna szerokość ≈ 50vw, na telefonie zawija się w wysoki słupek (*niepotwierdzone*) |
| Pasek zbiorczy kontraktów | `v2/modals/ContractsBulkActionsBar.tsx:102` | bottom-5 left-1/2 | 40 | jw., bez `flex-wrap` |
| Pasek zbiorczy maili | `emails/EmailBulkActionBar.tsx:193` | bottom-6 left-1/2, `w-full max-w-3xl px-4` | 40 | poprawny |
| Szuflada nawigacji | `v2/shell/AppShellV2.tsx:191` | inset-y-0 left-0 | 50 (tło 40) | poprawna |
| Dialog / Sheet | `ui/dialog.tsx:59`, `ui/sheet.tsx:61` | środek / bok | 50 | Sheet `w-full sm:max-w-*` poprawny; Dialog bez marginesu |

Kolizje do sprawdzenia zrzutem na 375 px: (a) toasty (z 9999) przykrywają maskotkę Jarvisa / postać „Moi ludzie” (z 30) — w tym samym rogu, mniej więcej ten sam offset; (b) paski zbiorcze na środku dołu (`bottom-5`, z 40) przy szerokości zbliżonej do ekranu nachodzą na maskotkę w prawym dolnym rogu (z 30); (c) `MyPeoplePanel` i dok kanbanu mają `top-12` (48 px), podczas gdy `ImpersonationBanner` nad topbarem przesuwa topbar w dół — panel wejdzie pod topbar przy podglądzie jako inny użytkownik.

Elementy `sticky`: 48 (Załącznik H) — głównie nagłówki tabel i paski akcji, bez oczywistego konfliktu.

## 11. Viewport

`src/app/layout.tsx` nie eksportuje `viewport` ani `generateViewport`; nigdzie w `src/app` nie ma `<meta name="viewport">`. Next.js 15 wstawia wtedy `width=device-width, initial-scale=1` — **zoom nie jest zablokowany** (brak `maximumScale`/`userScalable: false`). Brak `viewportFit: "cover"` i `themeColor` (bez znaczenia, dopóki nie ma safe-area).

## 12. Hooki mediów i nawigacja mobilna

- `useMediaQuery` / `useIsMobile` / `useBreakpoint`: **brak** w repo (`src/hooks/` ma 23 hooki, żaden o mediach).
- `window.matchMedia` do układu: 1 miejsce — `v2/pages/JobsListV2.tsx:794–996` (auto-rozwijanie kolumny filtrów od 1536 px). Pozostałe 2 użycia to `prefers-reduced-motion`.
- `window.innerWidth`: `v2/candidates/CandidateTabsRail.tsx:39,42` (zwinięcie szyny < 1600 px), `jarvis/JarvisRoot.tsx:507` (zamknięcie panelu < 640 px).
- `pointer-fine:`/`pointer-coarse:`: tylko `KanbanBoardV2.tsx` (37×).
- **Szuflada nawigacji mobilnej istnieje**: `TopbarV2.tsx:112` (hamburger `md:hidden`) → `AppShellV2.tsx:176–193` (tło `z-40 md:hidden`, szuflada `z-50`, zamyka się przy zmianie trasy) → `SidebarV2` w trybie `mobileOpen` (`w-64`). Sidebar desktopowy `hidden md:flex`. Treść ma `p-4 md:p-6`.
- Pary „pokaż/ukryj” (`md:hidden`, `hidden md:block`, `lg:hidden`…): 15 w całym repo — alternatywne widoki mobilne są wyjątkiem (wzorcowy przykład: `settings/admin/PermissionsTab.tsx:597`).

## Dodatkowo: cele dotykowe

`ui/button.tsx:28–32`: `sm` = `h-8` (32 px), `md` = `h-9` (36 px), `lg` = `h-10` (40 px), `icon` = 36 px, `icon-sm` = 32 px. Żaden rozmiar nie osiąga 44 px (wytyczne Apple/WCAG 2.5.5). Użycia: `size="sm"` **707**, `lg` 48, `icon-sm` 33, `icon` 16 (reszta domyślne `md`).

## Rekomendowana kolejność (najwięcej efektu za najmniej zmian)

1. `AppShellV2.tsx:166` `h-screen` → `h-dvh`; `ui/dialog.tsx` `max-h-[90vh]` → `max-h-[90dvh]` + boczny margines (`w-[calc(100%-2rem)]`). Jedna zmiana = wszystkie ekrany.
2. `globals.css:541–551`, `ui/input.tsx`, `ui/textarea.tsx`: `text-base md:text-sm` — koniec zoomu iOS na ~840 polach.
3. `NotificationsDropdown.tsx:643` (`w-96` → `w-[min(24rem,calc(100vw-1rem))]`) i `:468` (`w-full` → `w-[calc(100vw-3rem)]`).
4. `ProposalPanel`/`ProposalsSegment.tsx:416`: `flex-col lg:flex-row`, panel `w-full lg:w-[372px]`.
5. Trzy tabele w `overflow-hidden` → `overflow-x-auto`; 12 pozostałych z Załącznika C sprawdzić.
6. Siatki N≥3 z tabeli w sekcji 2 → `grid-cols-1 sm:grid-cols-N`.
7. 4 akcje ukryte hoverem bez alternatywy → `pointer-coarse:opacity-100` (Tailwind v4) + `focus-within`.
8. Ujednolicić 7 lokalnych toastów na `Toast.tsx` i odsunąć maskotki (`bottom-20` gdy toast/pasek zbiorczy jest widoczny); dodać `pb-[env(safe-area-inset-bottom)]`.

---

## Załączniki

### Załącznik A — siatki bez wariantu responsywnego (pełna lista, N≥3 i arbitralne)

| plik:linia | N | klasa |
|---|---|---|
| `src/app/settings/page.tsx:332` | 3 | `grid grid-cols-3 gap-4 mb-5` |
| `src/app/settings/rate-benchmarks/page.tsx:315` | 3 | `grid grid-cols-3 gap-3` |
| `src/app/contracts/[id]/page.tsx:2363` | arb | `grid-cols-[auto_1fr]` |
| `src/app/dynareporter/admin-dashboard/_modules/EmployeesManager.tsx:343` | 3 | `grid grid-cols-3 gap-1` |
| `src/app/dynareporter/admin-dashboard/_modules/ScoringConfig.tsx:138` | 3 | `grid grid-cols-3 gap-3` |
| `src/components/AppShell.tsx:611` | arb | `grid-cols-[1fr_1.2fr]` |
| `src/components/AppShell.tsx:681` | 3 | `grid grid-cols-3 gap-3` |
| `src/components/AppShell.tsx:1330` | 3 | `grid grid-cols-3 gap-3` |
| `src/components/ScorecardSchemaBuilder.tsx:255` | 3 | `grid grid-cols-3 gap-2` |
| `src/components/insights/sections/ChampionsSection.tsx:421` | 3 | `grid grid-cols-3 gap-2` |
| `src/components/settings/admin/ImportTab.tsx:77` | 3 | `grid grid-cols-3 gap-4 mb-4` |
| `src/components/settings/admin/ImportTab.tsx:160` | 4 | `grid grid-cols-4 gap-2 text-xs text-muted-foreground` |
| `src/components/settings/admin/ImportTab.tsx:178` | 3 | `grid grid-cols-3 gap-2 text-xs text-muted-foreground` |
| `src/components/candidate-contact/ContactQueueWorkspace.tsx:287` | 3 | `grid grid-cols-3 gap-2` |
| `src/components/calendar/WeekCalendar.tsx:328` | arb | `grid-cols-[48px_repeat(7,1fr)]` |
| `src/components/calendar/WeekCalendar.tsx:499` | arb | `grid-cols-[48px_repeat(7,1fr)]` |
| `src/components/calendar/WeekCalendar.tsx:699` | arb | `grid-cols-[48px_repeat(7,1fr)]` |
| `src/components/calendar/WeekCalendar.tsx:972` | 7 | `grid grid-cols-7 gap-0.5 mb-1` |
| `src/components/calendar/WeekCalendar.tsx:979` | 7 | `grid grid-cols-7 gap-0.5` |
| `src/components/calendar/WeekCalendar.tsx:1129` | 5 | `grid grid-cols-5 gap-1.5` |
| `src/components/calendar/cycle/DebriefDialog.tsx:193` | 3 | `grid grid-cols-3 gap-2` |
| `src/components/calendar/cycle/CycleBoard.tsx:50` | arb | `grid-cols-[repeat(7,minmax(180px,1fr))]` |
| `src/components/contracts/ContractRateBenchmarkCard.tsx:55` | 3 | `grid grid-cols-3 gap-4 text-sm` |
| `src/components/feedback/InterviewFeedbackModal.tsx:453` | 3 | `grid grid-cols-3 gap-2` |
| `src/components/v2/candidates/SkillBucketsField.tsx:141` | 3 | `cn( "rounded-md border border-border p-0.5", compact ? "grid w-full grid-cols-3" : "inline` |
| `src/components/v2/career-share/GeneralLinkTab.tsx:310` | 3 | `grid grid-cols-3 gap-2` |
| `src/components/v2/gamification/HeroLigaMistrzow.tsx:216` | 3 | `grid grid-cols-3 gap-4 md:gap-8 items-end max-w-2xl mx-auto` |
| `src/components/v2/gamification/HeroLigaMistrzow.tsx:241` | 3 | `grid grid-cols-3 gap-2 md:gap-3 mt-4 max-w-2xl mx-auto` |
| `src/components/v2/recruitment/PersonPanel.tsx:320` | arb | `grid-cols-[76px_minmax(0,1fr)]` |
| `src/components/v2/recruitment/PersonPanel.tsx:340` | arb | `grid-cols-[76px_minmax(0,1fr)]` |
| `src/components/v2/recruitment/PersonPanel.tsx:346` | arb | `grid-cols-[76px_minmax(0,1fr)]` |
| `src/components/v2/recruitment/PersonPanel.tsx:353` | arb | `grid-cols-[76px_minmax(0,1fr)]` |
| `src/components/v2/modals/ImportCandidatesV2.tsx:100` | 3 | `grid grid-cols-3 gap-3 text-sm` |
| `src/components/v2/dashboard/custom/CustomDashboard.tsx:399` | 12 | `grid grid-cols-12 gap-4` |
| `src/components/v2/dashboard/custom/MetricTileBody.tsx:147` | arb | `grid-cols-[8rem_1fr_2.5rem]` |
| `src/components/v2/dashboard/custom/MetricBuilderForm.tsx:321` | 3 | `grid grid-cols-3 gap-2` |
| `src/components/v2/dashboard/custom/TileSettingsDialog.tsx:140` | arb | `grid-cols-[1fr_1.4fr_auto]` |
| `src/components/v2/jobs/CvHandoffWorkbench.tsx:1050` | arb | `grid-cols-[1.2fr_minmax(0,1fr)]` |
| `src/components/v2/jobs/workbench-chrome.tsx:542` | arb | `grid-cols-[104px_minmax(0,1fr)]` |
| `src/components/v2/jobs/workbench-chrome.tsx:600` | arb | `grid-cols-[14px_minmax(0,1fr)]` |
| `src/components/v2/jobs/PipelineCandidateDock.tsx:243` | arb | `grid-cols-[10px_minmax(0,1fr)]` |
| `src/components/v2/jobs/PipelineCandidateDock.tsx:916` | arb | `grid-cols-[92px_minmax(0,1fr)]` |
| `src/components/v2/pages/B2BContractGeneratorV2.tsx:3928` | 3 | `grid flex-1 grid-cols-3 gap-3` |
| `src/components/v2/pages/B2BContractGeneratorV2.tsx:3965` | 3 | `grid grid-cols-3 gap-3` |
| `src/components/v2/pages/CandidateQuickView.tsx:585` | 3 | `grid grid-cols-3 gap-2` |
| `src/components/v2/screening/VerifiedRateFields.tsx:83` | arb | `grid-cols-[1.2fr_minmax(0,1fr)]` |
| `src/components/v2/screening/ScreeningForm.tsx:342` | arb | `grid-cols-[92px_minmax(0,1fr)]` |
| `src/components/jarvis/JarvisAppearanceForm.tsx:77` | 5 | `grid grid-cols-5 gap-2` |

### Załącznik B — `grid-cols-2` bez wariantu (per plik)

| plik | liczba | linie |
|---|---|---|
| `src/components/AppShell.tsx` | 11 | 586, 632, 644, 738, 800, 1312, 1607, 1841, 1937, 1945, 1953 |
| `src/app/clients/[id]/page.tsx` | 4 | 275, 397, 417, 436 |
| `src/components/EditOrderDialog.tsx` | 4 | 564, 590, 615, 641 |
| `src/components/NewContractorOrderDialog.tsx` | 3 | 722, 752, 783 |
| `src/app/contracts/[id]/page.tsx` | 2 | 1966, 2014 |
| `src/components/FrameworkContractsTab.tsx` | 2 | 506, 533 |
| `src/components/ExtendOrderDialog.tsx` | 2 | 356, 395 |
| `src/components/client-profile/orders/OrderListControls.tsx` | 2 | 93, 117 |
| `src/components/v2/recruitment/slideovers/OrderSlideOver.tsx` | 2 | 352, 410 |
| `src/app/clients/[id]/MaterialsTab.tsx` | 1 | 1102 |
| `src/app/settings/page.tsx` | 1 | 780 |
| `src/app/settings/templates/page.tsx` | 1 | 353 |
| `src/app/dynareporter/admin-dashboard/_modules/HallOfFameManager.tsx` | 1 | 605 |
| `src/app/dynareporter/admin-dashboard/_modules/MasterDataManager.tsx` | 1 | 445 |
| `src/app/dynareporter/admin-dashboard/_modules/ScoringConfig.tsx` | 1 | 169 |
| `src/components/ContractAmendmentsTab.tsx` | 1 | 287 |
| `src/components/calls/CallDetailsDialog.tsx` | 1 | 62 |
| `src/components/candidates/CandidateLocationPanel.tsx` | 1 | 87 |
| `src/components/candidates/preview/CandidateListPreview.tsx` | 1 | 147 |
| `src/components/settings/Microsoft365Card.tsx` | 1 | 115 |
| `src/components/settings/admin/SystemTab.tsx` | 1 | 92 |
| `src/components/candidate-contact/MyContactQueueWidget.tsx` | 1 | 88 |
| `src/components/prep/QuestionBankTab.tsx` | 1 | 368 |
| `src/components/calendar/WeekCalendar.tsx` | 1 | 1148 |
| `src/components/calendar/EventDetailModal.tsx` | 1 | 593 |
| `src/components/calendar/ScheduleInterviewModal.tsx` | 1 | 462 |
| `src/components/order-mail/OrderMailQueue.tsx` | 1 | 672 |
| `src/components/contracts/ContractEquipmentTab.tsx` | 1 | 297 |
| `src/components/client-profile/SummaryBar.tsx` | 1 | 45 |
| `src/components/v2/LanguageTiles.tsx` | 1 | 117 |
| `src/components/v2/candidates/CandidateFilterBar.tsx` | 1 | 620 |
| `src/components/v2/priority-work/TeamAllocationBoard.tsx` | 1 | 628 |
| `src/components/v2/priority-work/AllocationWorkloadBoard.tsx` | 1 | 98 |
| `src/components/v2/career-share/JobShareTab.tsx` | 1 | 500 |
| `src/components/v2/modals/CvGeneratedShareModal.tsx` | 1 | 202 |
| `src/components/v2/dashboard/RecruitmentActivityDashboard.tsx` | 1 | 137 |
| `src/components/v2/dashboard/custom/DashboardGrid.tsx` | 1 | 39 |
| `src/components/v2/candidate-profile/RecruitmentsTab.tsx` | 1 | 450 |
| `src/components/v2/jobs/AIJobWriterModal.tsx` | 1 | 82 |
| `src/components/v2/jobs/JobReadinessDock.tsx` | 1 | 1077 |
| `src/components/v2/jobs/workbench-chrome.tsx` | 1 | 555 |
| `src/components/v2/pages/ContractsListV2.tsx` | 1 | 424 |
| `src/components/v2/pages/B2BContractGeneratorV2.tsx` | 1 | 3908 |

### Załącznik C — `<table>` bez `overflow-x-auto` w 12 liniach wyżej

| plik:linia | uwaga |
|---|---|
| `src/app/settings/contract-templates/page.tsx:201` |  |
| `src/app/settings/diagnostics/page.tsx:167` |  |
| `src/app/contracts/[id]/page.tsx:2287` |  |
| `src/app/contracts/analytics/page.tsx:167` |  |
| `src/app/dashboard/delivery-lead/_components/DlClientsTable.tsx:26` |  |
| `src/components/ContractInvoicesTab.tsx:233` |  |
| `src/components/RateCardsTab.tsx:405` |  |
| `src/components/RateHistoryWidget.tsx:196` |  |
| `src/components/ContractDocumentsTab.tsx:270` |  |
| `src/components/insights/sections/SourcesFunnelSection.tsx:45` |  |
| `src/components/settings/CloudTalkSettingsCard.tsx:205` |  |
| `src/components/settings/admin/AdminUsersTab.tsx:301` |  |
| `src/components/order-mail/OrderMailQueue.tsx:678` |  |
| `src/components/marketplace/MarketplaceTable.tsx:150` |  |
| `src/components/v2/pages/BulkImportCVsV2.tsx:383` |  |

### Załącznik D — `h-screen` / `min-h-screen` / `100vh` (bez `max-h-[Nvh]` w modalach)

| plik:linia | token |
|---|---|
| `src/app/error.tsx:28` | `min-h-screen` |
| `src/app/global-error.tsx:36` | `100vh` |
| `src/app/not-found.tsx:6` | `min-h-screen` |
| `src/app/candidates/layout.tsx:31` | `100vh` |
| `src/app/apply/layout.tsx:12` | `min-h-screen` |
| `src/app/settings/pipeline-templates/page.tsx:30` | `min-h-screen` |
| `src/app/settings/diagnostics/page.tsx:82` | `min-h-screen` |
| `src/app/settings/templates/page.tsx:581` | `h-[calc(100vh-8rem)]` |
| `src/app/engagement/layout.tsx:15` | `min-h-screen` |
| `src/app/cv/layout.tsx:12` | `min-h-screen` |
| `src/app/cv/i/[token]/page.tsx:569` | `100vh` |
| `src/app/cv/i/[token]/page.tsx:878` | `100vh` |
| `src/app/cv/[token]/page.tsx:139` | `100vh` |
| `src/app/jobs/layout.tsx:21` | `100vh` |
| `src/app/403/page.tsx:12` | `min-h-screen` |
| `src/app/sign/layout.tsx:13` | `min-h-screen` |
| `src/app/login/page.tsx:382` | `min-h-screen` |
| `src/app/login/microsoft/callback/page.tsx:101` | `min-h-screen` |
| `src/app/login/microsoft/callback/page.tsx:127` | `min-h-screen` |
| `src/app/onboarding/layout.tsx:13` | `min-h-screen` |
| `src/app/onboarding/page.tsx:16` | `min-h-screen` |
| `src/app/share/champion-card/[token]/page.tsx:134` | `min-h-screen` |
| `src/components/login4.tsx:41` | `h-screen` |
| `src/components/blocks/AuthShell.tsx:33` | `min-h-screen` |
| `src/components/calendar/WeekCalendar.tsx:270` | `h-[calc(100vh-220px)]` |
| `src/components/ds/Kanban.tsx:50` | `100vh` |
| `src/components/v2/forms/OnboardingRecruiterV2.tsx:109` | `min-h-screen` |
| `src/components/v2/forms/OnboardingDLV2.tsx:138` | `min-h-screen` |
| `src/components/v2/shell/AppShellV2.tsx:166` | `h-screen` |
| `src/components/v2/jobs/JobReadinessDock.tsx:883` | `100vh` |
| `src/components/v2/jobs/workbench-chrome.tsx:455` | `100vh` |
| `src/components/v2/pages/CandidatesListV2.tsx:1636` | `100vh` |
| `src/components/v2/pages/KanbanBoardV2.tsx:1563` | `h-[calc(100vh-350px)]` |
| `src/components/v2/pages/KanbanBoardV2.tsx:2551` | `h-[calc(100vh-240px)]` |
| `src/components/jarvis/JarvisPanel.tsx:67` | `100vh` |

### Załącznik E — mały tekst (`text-[9|10|11px]`), 30 plików z największą liczbą

| plik | razem | 9px | 10px | 11px |
|---|---|---|---|---|
| `src/components/ChampionVerificationChecklist.tsx` | 36 | 0 | 8 | 28 |
| `src/components/v2/pages/JobsListV2.tsx` | 19 | 1 | 6 | 12 |
| `src/components/v2/jobs/JobReadinessDock.tsx` | 17 | 0 | 3 | 14 |
| `src/components/v2/pages/KanbanBoardV2.tsx` | 17 | 11 | 3 | 3 |
| `src/components/client-profile/orders/OrderGroupCard.tsx` | 13 | 0 | 12 | 1 |
| `src/components/v2/pages/ContractsListV2.tsx` | 13 | 0 | 7 | 6 |
| `src/app/dynareporter/admin-dashboard/page.tsx` | 11 | 0 | 11 | 0 |
| `src/app/dynareporter/admin-dashboard/_modules/EmployeesManager.tsx` | 11 | 0 | 11 | 0 |
| `src/components/ChampionProfileEditor.tsx` | 10 | 0 | 5 | 5 |
| `src/components/ChampionRecommendedSearches.tsx` | 10 | 0 | 3 | 7 |
| `src/components/v2/candidates/CandidateFilterBar.tsx` | 10 | 0 | 3 | 7 |
| `src/app/dynareporter/admin-dashboard/_modules/DataHistoryView.tsx` | 9 | 0 | 9 | 0 |
| `src/app/dynareporter/admin-dashboard/_modules/MasterDataManager.tsx` | 9 | 0 | 9 | 0 |
| `src/components/v2/filters/SavedSearchesMenu.tsx` | 9 | 0 | 8 | 1 |
| `src/components/v2/jobs/CvHandoffWorkbench.tsx` | 9 | 0 | 0 | 9 |
| `src/components/v2/jobs/workbench-chrome.tsx` | 9 | 1 | 2 | 6 |
| `src/components/v2/jobs/JobListCells.tsx` | 9 | 1 | 0 | 8 |
| `src/components/insights/sections/InsightsRaces.tsx` | 8 | 0 | 0 | 8 |
| `src/components/v2/recruitment/RequestRequirementsRail.tsx` | 8 | 0 | 1 | 7 |
| `src/app/contracts/[id]/page.tsx` | 7 | 0 | 1 | 6 |
| `src/components/v2/filters/StageFilterPanel.tsx` | 7 | 0 | 6 | 1 |
| `src/components/v2/jobs/JobContractTab.tsx` | 7 | 0 | 0 | 7 |
| `src/components/v2/jobs/PipelineCandidateDock.tsx` | 7 | 0 | 3 | 4 |
| `src/app/settings/team-structure/page.tsx` | 6 | 0 | 0 | 6 |
| `src/components/insights/sections/InsightsFlagAdmin.tsx` | 6 | 0 | 0 | 6 |
| `src/components/v2/candidates/CandidateSearchFields.tsx` | 6 | 0 | 0 | 6 |
| `src/components/v2/recruitment/ProposalsSegment.tsx` | 6 | 0 | 0 | 6 |
| `src/components/v2/jobs/ScreeningWorkbench.tsx` | 6 | 0 | 0 | 6 |
| `src/components/sourcing/ContractorMatchCard.tsx` | 6 | 0 | 2 | 4 |
| `src/app/settings/linkedin-metrics/page.tsx` | 5 | 1 | 1 | 3 |

### Załącznik F — pliki bez żadnego prefiksu responsywnego (60 największych)

| linie | plik | grid-cols-N | w-[≥100px] |
|---|---|---|---|
| 1793 | `src/components/OrdersAndContractsTab.tsx` | 0 | 0 |
| 1312 | `src/components/client-profile/orders/MultiConsultantOrdersTab.tsx` | 0 | 0 |
| 1256 | `src/components/v2/jobs/PipelineCandidateDock.tsx` | 0 | 0 |
| 879 | `src/components/ChampionVerificationChecklist.tsx` | 0 | 0 |
| 843 | `src/components/NotificationsDropdown.tsx` | 0 | 0 |
| 834 | `src/components/contracts/ClientContractRegister.tsx` | 0 | 7 |
| 833 | `src/components/v2/pages/JobChatTab.tsx` | 0 | 1 |
| 830 | `src/app/dynareporter/admin-dashboard/_modules/MasterDataManager.tsx` | 1 | 0 |
| 830 | `src/components/v2/pages/CandidateChatTab.tsx` | 0 | 1 |
| 784 | `src/app/settings/cv-rules/page.tsx` | 0 | 0 |
| 771 | `src/app/settings/templates/page.tsx` | 1 | 0 |
| 763 | `src/components/v2/jobs/workbench-chrome.tsx` | 1 | 0 |
| 739 | `src/app/dynareporter/admin-dashboard/_modules/HallOfFameManager.tsx` | 1 | 0 |
| 730 | `src/components/calendar/EventDetailModal.tsx` | 1 | 0 |
| 700 | `src/components/FrameworkContractsTab.tsx` | 2 | 0 |
| 695 | `src/components/calendar/ScheduleInterviewModal.tsx` | 1 | 0 |
| 689 | `src/components/v2/filters/ActiveFilterChips.tsx` | 0 | 0 |
| 688 | `src/components/finance/MdImportWorkspace.tsx` | 0 | 0 |
| 685 | `src/components/v2/modals/CVBrandedEditModal.tsx` | 0 | 0 |
| 663 | `src/components/v2/modals/CVGeneratorV2.tsx` | 0 | 0 |
| 655 | `src/components/feedback/InterviewFeedbackModal.tsx` | 1 | 0 |
| 627 | `src/components/ds/VirtualTable.tsx` | 0 | 0 |
| 624 | `src/components/v2/recruitment/PeopleTable.tsx` | 0 | 0 |
| 621 | `src/components/v2/files/FilePreviewModal.tsx` | 0 | 0 |
| 611 | `src/components/v2/recruitment/slideovers/HistoryChatSlideOver.tsx` | 0 | 0 |
| 608 | `src/components/prep/QuestionBankTab.tsx` | 1 | 0 |
| 605 | `src/components/v2/recruitment/slideovers/OrderSlideOver.tsx` | 2 | 0 |
| 596 | `src/components/cortex/CurationPanel.tsx` | 0 | 0 |
| 587 | `src/components/emails/EmailThreadList.tsx` | 0 | 0 |
| 576 | `src/components/v2/pages/ContractorsListV2.tsx` | 0 | 0 |
| 568 | `src/app/dynareporter/admin-dashboard/_modules/EmployeesManager.tsx` | 1 | 1 |
| 515 | `src/components/v2/pages/CandidateActivitySummaryCard.tsx` | 0 | 0 |
| 510 | `src/components/v2/jobs/InterviewDecisionDock.tsx` | 0 | 0 |
| 506 | `src/components/settings/admin/AdminUsersTab.tsx` | 0 | 0 |
| 493 | `src/components/insights/PeriodPicker.tsx` | 0 | 0 |
| 489 | `src/components/v2/recruitment/useBulkCvHandoff.tsx` | 0 | 0 |
| 483 | `src/app/settings/api-integration/page.tsx` | 0 | 0 |
| 480 | `src/components/cv-rules/CvRuleEditor.tsx` | 0 | 0 |
| 479 | `src/components/insights/sections/InsightsTeamTable.tsx` | 0 | 0 |
| 479 | `src/components/v2/modals/AddCandidateFromCVModal.tsx` | 0 | 0 |
| 478 | `src/components/v2/screening/ScreeningForm.tsx` | 0 | 0 |
| 469 | `src/components/cortex/SkillCandidatesDrawer.tsx` | 0 | 0 |
| 467 | `src/components/v2/shell/CommandPaletteV2.tsx` | 0 | 0 |
| 462 | `src/app/settings/rate-benchmarks/page.tsx` | 1 | 0 |
| 461 | `src/components/v2/pages/BulkImportCVsV2.tsx` | 0 | 0 |
| 453 | `src/components/v2/candidate-profile/Timeline.tsx` | 0 | 0 |
| 447 | `src/components/client-playbook/ClientPlaybookCard.tsx` | 0 | 0 |
| 432 | `src/components/contracts/FinancialRatesCard.tsx` | 0 | 0 |
| 431 | `src/app/clients/[id]/OwnersTab.tsx` | 0 | 0 |
| 431 | `src/app/settings/scoring/page.tsx` | 0 | 0 |
| 427 | `src/components/emails/EmailThreadView.tsx` | 0 | 0 |
| 420 | `src/components/candidate-contact/ContactOutcomeSheet.tsx` | 0 | 0 |
| 411 | `src/components/v2/shell/SidebarV2.tsx` | 0 | 0 |
| 411 | `src/components/v2/candidate-profile/Notes.tsx` | 0 | 0 |
| 410 | `src/components/insights/sections/InsightsSeniority.tsx` | 0 | 0 |
| 409 | `src/components/v2/my-people/MyPeopleViews.tsx` | 0 | 0 |
| 409 | `src/components/v2/modals/QuickAssignV2.tsx` | 0 | 0 |
| 407 | `src/components/contracts/ContractEquipmentTab.tsx` | 1 | 0 |
| 393 | `src/components/insights/sections/_shared.tsx` | 0 | 0 |
| 391 | `src/app/login/page.tsx` | 0 | 0 |

### Załącznik G — `whitespace-nowrap` bez `truncate`/`overflow-hidden`/`min-w-0`/`shrink-0` (per plik)

| plik | liczba | linie |
|---|---|---|
| `src/components/v2/pages/ContractsListV2.tsx` | 8 | 1240, 1245, 1261, 1270, 1276, 1290, 1304, 1318 |
| `src/components/contracts/FinancialRatesCard.tsx` | 7 | 113, 211, 240, 274, 295, 330, 416 |
| `src/components/v2/jobs/JobListCells.tsx` | 4 | 123, 144, 186, 210 |
| `src/app/contracts/analytics/page.tsx` | 3 | 306, 321, 625 |
| `src/components/candidates/CvRichProfileSections.tsx` | 3 | 69, 74, 141 |
| `src/components/insights/sections/InsightsBoardYoY.tsx` | 3 | 485, 511, 586 |
| `src/components/v2/pages/JobsListV2.tsx` | 3 | 452, 614, 632 |
| `src/components/finance/FinanceArchiveTab.tsx` | 3 | 114, 115, 129 |
| `src/components/finance/FinanceResultsTable.tsx` | 3 | 140, 174, 241 |
| `src/app/dynareporter/admin-dashboard/_modules/DataHistoryView.tsx` | 2 | 155, 216 |
| `src/components/RequestHistorySection.tsx` | 2 | 280, 358 |
| `src/components/settings/PlacementExclusionsTab.tsx` | 2 | 140, 164 |
| `src/components/settings/ConflictsRegistryTab.tsx` | 2 | 253, 271 |
| `src/components/settings/EventHistoryTab.tsx` | 2 | 218, 228 |
| `src/components/cortex/TechMapHeatmap.tsx` | 2 | 63, 85 |
| `src/components/v2/jobs/SimilarJobsDialog.tsx` | 2 | 189, 242 |
| `src/components/Toast.tsx` | 1 | 179 |
| `src/components/insights/InsightsView.tsx` | 1 | 232 |
| `src/components/insights/sections/CompetenceMatrix.tsx` | 1 | 146 |
| `src/components/insights/sections/InsightsDlPortfolio.tsx` | 1 | 278 |
| `src/components/insights/sections/InsightsIntegrations.tsx` | 1 | 291 |
| `src/components/settings/AutoMatchOverview.tsx` | 1 | 108 |
| `src/components/settings/admin/AdminUsersTab.tsx` | 1 | 237 |
| `src/components/cortex/CortexView.tsx` | 1 | 116 |
| `src/components/ds/DataTable.tsx` | 1 | 95 |
| `src/components/v2/recruitment/PostingsSection.tsx` | 1 | 141 |
| `src/components/v2/candidate-profile/ProfileTab.tsx` | 1 | 415 |
| `src/components/v2/jobs/JobShortlist.tsx` | 1 | 576 |
| `src/components/v2/jobs/workbench-chrome.tsx` | 1 | 328 |
| `src/components/v2/pages/B2BContractGeneratorV2.tsx` | 1 | 2390 |
| `src/components/v2/pages/CandidatesListV2.tsx` | 1 | 1918 |
| `src/components/v2/pages/CandidateQuickView.tsx` | 1 | 613 |
| `src/components/v2/pages/CandidateSearchView.tsx` | 1 | 1726 |

### Załącznik H — elementy `sticky` (48)

| plik:linia | offsety | z |
|---|---|---|
| `src/app/candidates/layout.tsx:31` | top-0 | — |
| `src/app/settings/cv-rules/page.tsx:423` | right-0 | — |
| `src/app/settings/cv-rules/page.tsx:580` | right-0 | — |
| `src/app/settings/linkedin-metrics/page.tsx:255` | left-0 | — |
| `src/app/settings/linkedin-metrics/page.tsx:268` | left-0 | — |
| `src/app/settings/linkedin-metrics/page.tsx:292` | left-0 | — |
| `src/app/contracts/analytics/page.tsx:621` | left-0 | — |
| `src/app/contracts/analytics/page.tsx:642` | left-0 | — |
| `src/app/cv/i/[token]/page.tsx:569` | lg:top-4 | — |
| `src/app/jobs/layout.tsx:21` | top-0 | — |
| `src/app/jobs/[id]/page.tsx:1128` | xl:top-4 | — |
| `src/components/StageNotificationRulesModal.tsx:82` | top-0 | — |
| `src/components/ChampionIntake.tsx:215` | bottom-0 | — |
| `src/components/ScorecardSchemaBuilder.tsx:146` | top-0 | 10 |
| `src/components/ScorecardSchemaBuilder.tsx:339` | bottom-0 | — |
| `src/components/candidates/preview/CandidateListPreview.tsx:77` | left-0 | 10 |
| `src/components/candidates/preview/CandidateListPreview.tsx:89` | left-0 | 10 |
| `src/components/insights/sections/InsightsClientsRanking.tsx:147` | top-0 | 10 |
| `src/components/settings/admin/PermissionsTab.tsx:601` | left-0 | 10 |
| `src/components/settings/admin/PermissionsTab.tsx:622` | left-0 | 10 |
| `src/components/settings/admin/PermissionsTab.tsx:774` | bottom-3 | 10 |
| `src/components/cortex/TechMapHeatmap.tsx:59` | left-0 | — |
| `src/components/cortex/TechMapHeatmap.tsx:85` | left-0 | — |
| `src/components/ds/VirtualTable.tsx:511` | top-0 | 10 |
| `src/components/ds/FilterBar.tsx:65` | top-0 | 20 |
| `src/components/ds/FilterBar.tsx:65` | top-0 | 20 |
| `src/components/v2/priority-work/TeamAllocationBoard.tsx:1835` | xl:top-4 | — |
| `src/components/v2/dashboard/custom/CustomDashboard.tsx:331` | top-2 | 20 |
| `src/components/v2/candidate-profile/ProfileTab.tsx:134` | xl:top-4 | — |
| `src/components/v2/candidate-profile/RecruitmentsTab.tsx:264` | xl:top-4 | — |
| `src/components/v2/jobs/ScreeningWorkbench.tsx:1169` | xl:top-4 | — |
| `src/components/v2/jobs/JobContractTab.tsx:799` | xl:top-4 | — |
| `src/components/v2/jobs/CvHandoffWorkbench.tsx:1498` | xl:top-4 | — |
| `src/components/v2/jobs/JobInterviewsTab.tsx:739` | xl:top-4 | — |
| `src/components/v2/jobs/new/NewJobPage.tsx:440` | md:bottom-0 | 20 |
| `src/components/v2/pages/JobsListV2.tsx:1923` | xl:top-4 | — |
| `src/components/v2/pages/CVGeneratorStandaloneV2.tsx:1313` | bottom-0 | 20 |
| `src/components/v2/pages/HelpClientPlaybooksSection.tsx:128` | md:top-4 | — |
| `src/components/v2/pages/B2BContractGeneratorV2.tsx:2167` | right-0 | 10 |
| `src/components/v2/pages/B2BContractGeneratorV2.tsx:2398` | right-0 | 10 |
| `src/components/v2/pages/B2BContractGeneratorV2.tsx:2707` | right-0 | 10 |
| `src/components/v2/pages/B2BContractGeneratorV2.tsx:2757` | right-0 | 10 |
| `src/components/v2/pages/CandidatesListV2.tsx:1613` | top-0 | 10 |
| `src/components/v2/pages/KanbanBoardV2.tsx:1235` | top-0 | 10 |
| `src/components/v2/pages/CandidateQuickView.tsx:420` | top-0 | 20 |
| `src/components/v2/pages/HelpPageV2.tsx:238` | md:top-4 | — |
| `src/components/v2/pages/CandidateSearchView.tsx:1302` | bottom-4 | 10 |
| `src/components/finance/FinanceResultsTable.tsx:132` | top-0 | 10 |
