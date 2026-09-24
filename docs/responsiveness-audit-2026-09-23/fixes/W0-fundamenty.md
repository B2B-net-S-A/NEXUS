# W0-fundamenty — shell, warstwy pływające, prymitywy UI i kit DS

Źródła: `docs/responsiveness-audit-2026-09-23/01-shell-ds.md` (całość) + z `09-pattern-scan.md`: pływające `fixed`/safe-area, `h-screen`/vh w shellu, hover-only w moim zakresie, cele dotyku `Button`.
Ścieżki względem `frontend/`.

## Ustalenia

| Ustalenie | Stan | Plik:linia | Uwagi |
|---|---|---|---|
| P0-1 topbar wypycha „Dodaj”/dzwonek przy 375–430 px | zrobione | `v2/shell/TopbarV2.tsx` header, przycisk wyszukiwania, klaster | przełączniki palety/Kids/motywu `hidden sm:flex`; skróty ⌘K `hidden sm:flex`; wyszukiwanie `min-w-0`; header `gap-2 sm:gap-3 px-3 md:px-5`; hamburger 40 px. Przełączniki przeniesione do nowego `v2/shell/ThemeControls.tsx` i dodane jako wiersz „Wygląd” w szufladzie mobilnej (`SidebarV2.tsx`, stopka przy `mobileOpen`) — na telefonie nie tracimy do nich dostępu (innego miejsca w aplikacji nie było). |
| P0-2 `h-screen` w korzeniu shella | zrobione | `v2/shell/AppShellV2.tsx` korzeń | `h-dvh` (bez fallbacku `supports-` — patrz uwaga o dialogu niżej). |
| P1-1 topbar na tablecie (okruszki `md:flex-none`) | zrobione częściowo | `TopbarV2.tsx` okruszki | okruszki `md:flex-initial` (kurczą się). Wartości KPI od `xl` — **poza zakresem** (`v2/kpi/MyKpiWidget.tsx`). Domyślnie zwinięty pasek < 1280 px (P1-4) zdejmuje większość presji. |
| P1-2 lista powiadomień ucięta z lewej | zrobione | `NotificationsDropdown.tsx` panel (~643) | `fixed inset-x-2 top-14 sm:absolute sm:inset-x-auto sm:right-0 sm:top-full sm:mt-2 sm:w-96`; lista `max-h-[min(420px,calc(100dvh-10rem))]`. |
| P1-3 toast powiadomienia wyjeżdża za lewą krawędź | zrobione | `NotificationsDropdown.tsx` `NotifToast` (~468) | telefon: `inset-x-4` pod topbarem (`top-[calc(3.5rem+env(safe-area-inset-top))]`) — poza rogiem z toastami i maskotką; od `sm` jak dotąd (prawy dół). Zamknięcie: `aria-label` + 40 px na telefonie. |
| P1-4a pasek przypięty domyślnie na tablecie | zrobione | `v2/shell/useSidebarPinned.ts` | bez zapamiętanego wyboru po montażu `matchMedia("(min-width: 1280px)")`; SSR i pierwszy render bez zmian; zapisany wybór wygrywa; brak `matchMedia` (jsdom) = dotychczasowe `true`. |
| P1-4b rozwinięcie po „najechaniu” na dotyku | zrobione | `v2/shell/SidebarV2.tsx` `<aside>` | `onPointerEnter/Leave` tylko `pointerType === "mouse"`; `setHovered(false)` na zmianę `pathname`. `SIDEBAR_VERTICAL_LAYOUT` nietknięty. |
| P1-5 pola 14 px → zoom iOS | pominięte (już zrobione) | `app/globals.css` | reguła globalna `pointer: coarse` → `max(16px,1em)` + `text-base md:text-sm` w base (wspólne, nie moje). |
| P1-6 paleta ⌘K na krótkim ekranie / brak zamknięcia | zrobione | `ui/command.tsx` `CommandDialog`, `CommandList` | telefon: okno u góry (`top-2 translate-y-0`, `max-h-[calc(100dvh-1rem)]`), od `sm` wyśrodkowane (`sm:max-h-[90dvh]`); lista `max-h-[min(420px,calc(100dvh-5rem))]`; widoczny „Anuluj” (`DialogClose`, `sm:hidden`) + `pr-24` na polu tylko < sm. |
| P1-7 maskotki zasłaniają treść | zrobione | `AppShellV2.tsx` `<main>`, `jarvis/JarvisMascot.tsx`, `v2/my-people/MyPeopleLauncher.tsx` | `<main>` `p-4 pb-24 md:p-6`; maskotka Jarvisa 40 px < md (`max-md:[&>svg]:size-10`), pozycja z `env(safe-area-inset-bottom/right)`; dymki `max-w-[min(240px|260px,calc(100vw-6rem))]`; postać „Moi ludzie” z safe-area. |
| P1-8 `StatCard` przelewa się na 375 px | zrobione | `ds/StatCard.tsx` | siatka `grid-cols-1 min-[420px]:grid-cols-2 lg:grid-cols-4` (gap 3→4 od sm); wartość `text-2xl sm:text-[32px] break-words`; sparkline `hidden sm:block`; kafel `min-w-0 p-4 sm:p-5`; etykieta `truncate`, wiersze `min-w-0`. |
| P2-1 `DialogContent` od krawędzi do krawędzi, `90vh` | zrobione | `ui/dialog.tsx` | `w-[calc(100%-1rem)] sm:w-full`, `max-h-[90dvh]`. Sprawdzone: żaden konsument nie nadpisuje `w-*` na `DialogContent`. Konsumenci z własnym `max-h-[90vh]` dalej go wygrywają (poza zakresem). |
| P2-2 `SheetContent` vh, zamknięcie 24 px, safe-area | zrobione | `ui/sheet.tsx` | top/bottom `max-h-[85dvh]`, `pt/pb-[env(safe-area-inset-*)]`; zamknięcie 40 px < sm; lewy arkusz dostał `animate-slide-in-left` (nowy keyframe w `globals.css`, dotąd wjeżdżał z prawej). |
| P2-3 popover/menu/select bez limitu wysokości | zrobione | `ui/popover.tsx`, `ui/dropdown-menu.tsx`, `ui/select.tsx` | `max-h-(--radix-…-available-height)` + `overflow-y-auto` + `max-w-[calc(100vw-1rem)]`; select `max-h-[min(24rem,var(--radix-select-content-available-height,24rem))]`. |
| P2-4 `TabsList` bez przewijania, `TabbedNav` wrap | zrobione | `ui/tabs.tsx`, `ds/TabbedNav.tsx` | `TabsList` `max-w-full max-sm:overflow-x-auto max-sm:pb-px` (pb-px mieści `-mb-px` triggera — bez 1-px pionowego scrolla), trigger `max-sm:shrink-0 whitespace-nowrap`; `TabbedNav` `wrap` → jeden przewijany rząd < sm, od sm zawijanie. Desktop bez zmian. |
| P2-5 `DataTable -mx-8` wystaje | zrobione | `ds/DataTable.tsx` | `-mx-4 sm:-mx-6` / `sm:px-6`, bez `lg:` (zmiana na desktopie celowa — to był błąd desktopowy). |
| P2-6 `VirtualTable` bez min-width, checkbox 14 px | zrobione | `ds/VirtualTable.tsx` | nowy prop `minWidth` (nagłówek + wszystkie rowgroupy); checkbox owinięty w `<label>` na całą komórkę 36 px. Żaden konsument jeszcze nie podaje `minWidth` — do dołożenia przez właścicieli ekranów. |
| P2-7 cele dotyku | zrobione częściowo | `ui/button.tsx`, `TopbarV2.tsx`, `SidebarV2.tsx`, `ds/FilterBar.tsx`, `ui/dropdown-menu.tsx`, `MyPeopleLauncher.tsx`, `JarvisMascot.tsx`, `OnboardingWalkthrough.tsx` | `Button` `sm`/`icon`/`icon-sm`: `pointer-coarse:min-h-10 (min-w-10)`; hamburger 40 px; zamknięcie szuflady 40 px; wyloguj `pointer-coarse:p-3`; chip filtra `hit-area`, czyszczenie wyszukiwania `pointer-coarse:size-8`; pozycje menu `pointer-coarse:py-2.5`; dymki `hit-area`/`pointer-coarse:p-2`. **Pominięte:** pozycje nawigacji `h-9` w szufladzie (niezmiennik B57 wspólnych klas). |
| P2-8 tekst 10–11 px | pominięte | — | reguła globalna podnosi `text-[10px]` do 11 px na dotyku; desktop celowo bez zmian. |
| P2-9 wyciszenie kategorii tylko hoverem | zrobione | `NotificationsDropdown.tsx` (~786) | `pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100` + `group-focus-within`/`focus-visible`; `pointer-coarse:p-2`. |
| P2-10 szuflada nawigacji bez Esc/fokusu | zrobione | `AppShellV2.tsx` | `Sheet side="left"` (Radix Dialog: Esc, pułapka fokusu, `aria-modal`, powrót fokusu), `SheetTitle` sr-only, zamykanie przy zmianie trasy zostaje. |
| P2-11 trzy systemy toastów w jednym rogu | zrobione | `Toast.tsx`, `v2/shell/QuickActionsV2.tsx`, `NotificationsDropdown.tsx` | globalny kontener: telefon `inset-x-4` nad safe-area, od sm prawy dół + `sm:max-w-md`, tekst `min-w-0 break-words`; lokalny toast QuickActions zastąpiony `useToast`; toast powiadomień na telefonie u góry. |
| P2-12 pasek „Podgląd jako” na 375 px | zrobione | `v2/shell/ImpersonationBanner.tsx` | stała `h-9`, na telefonie „Podgląd jako {imię}” + przycisk „Wróć” (`aria-label` pełny), reszta od sm. |
| P2-13 panel „Moi ludzie” `top-12` vs pasek podglądu | zrobione | `v2/my-people/MyPeoplePanel.tsx` | `top-21` przy podglądzie (48 + 36 px), `top-12` normalnie; `pb-[env(safe-area-inset-bottom)]`. Dok kanbanu z tym samym problemem — poza zakresem. |
| P2-14 panel Jarvisa w poziomie telefonu | zrobione | `jarvis/JarvisPanel.tsx`, `jarvis/JarvisRoot.tsx` | pełny ekran `h-dvh` < md, pływający od `md`, `max-h-[calc(100dvh-7.5rem)]`; zamykanie po nawigacji < 768 px (było 640). |
| P2-15 karta powitalna na krótkim ekranie | zrobione | `OnboardingWalkthrough.tsx` | `max-h-[calc(100dvh-2rem)] overflow-y-auto`; zamknięcie z `aria-label` + `hit-area`. |
| P2-16 kolumna kanbanu DS `100vh` | zrobione | `ds/Kanban.tsx` | `100dvh`. |
| P2-17 lejek stałe szerokości | zrobione | `ds/FunnelChart.tsx` | etykieta `w-20 sm:w-24 truncate` + `title`, procent `w-12 sm:w-16`, `gap-2 sm:gap-4`, karta `p-4 sm:p-6`. |
| P2-18 nagłówki ściskają tytuł | zrobione | `ds/PageHeader.tsx`, `ds/EntityHeader.tsx` | akcje `sm:max-w-[60%] sm:justify-end` (zawijają się), `h1` `wrap-break-word`. |
| 09 — `SidebarMore` popover `80vh` | zrobione | `v2/shell/SidebarMore.tsx` | `min(80dvh,640px)`. |
| 09 — safe-area (brak `env()` w repo) | zrobione | maskotki, toasty, sheet, panel „Moi ludzie” | Bez `viewportFit: "cover"` w `layout.tsx` — celowo: `cover` wpuściłby treść pod notch w poziomie, a shell nie ma bocznych wcięć; bez niego `env()` = 0 i nic nie psuje. |
| 09 — `Button` cele dotyku | zrobione | `ui/button.tsx` | jw. |

## Testy zmienione
- `src/components/v2/shell/__tests__/useSidebarPinned.test.tsx` — 3 nowe przypadki (zwinięty < 1280, przypięty ≥ 1280, zapamiętany wybór wygrywa). Istniejące bez zmian.
- `src/components/ui/__tests__/button.test.tsx` — nowy przypadek: `sm`/`icon`/`icon-sm` mają `pointer-coarse:min-h-10`/`min-w-10`.

## Poza zakresem
- `src/components/v2/kpi/MyKpiWidget.tsx:211,219` — wartości KPI w topbarze od `xl` zamiast `lg` (P1-1).
- `src/components/v2/pages/KanbanBoardV2.tsx` — dok `top-12` nachodzi na topbar przy pasku podglądu (jak P2-13); użyć `top-21` przy `realUser`.
- Konsumenci `DialogContent` z `max-h-[90vh]`/`92vh`/`94vh`/`88vh`/`85vh` (m.in. `v2/modals/*`) — zamienić na `dvh`, bo nadpisują nowy domyślny limit.
- Pozostałe lokalne toasty w rogu (`CandidatesListV2.tsx`, `ClientsListV2.tsx`, `HelpPageV2.tsx`, `ContractsListV2.tsx`, `ClientContractRegister.tsx`, legacy `AppShell.tsx`) — przejść na `useToast`.
- Konsumenci `VirtualTable` — podać `minWidth`, żeby kolumny `px` przewijały się na telefonie.

## Kontrole
- **tsc** (tymczasowy tsconfig obejmujący `v2/shell`, `ui`, `ds`, `jarvis`, `v2/my-people`, `NotificationsDropdown`, `Toast`, `OnboardingWalkthrough`, `layout.tsx` + `src/test/setup.ts`): **0 błędów**. Pełne `tsc -p .` blokują błędy składni w cudzym pliku w toku (`components/marketplace/MarketplaceTable.tsx`) — tsc wtedy nie robi analizy semantycznej, stąd zawężony przebieg. Plik tymczasowy usunięty.
- **eslint** na 35 zmienionych plikach: czysto.
- **vitest** (shell, ui, ds, jarvis, my-people, NotificationsDropdown ×2, Toast ×2, OnboardingWalkthroughAutoStart, query-key-producers): 152 testy, wszystkie zielone. W pełnym przebiegu pod obciążeniem (8 agentów) padały pojedyncze testy na limitach czasu `waitFor` (NotificationsDropdown „Pokaż więcej”, VirtualTable) — każdy uruchomiony osobno przechodzi.
- Przeklikanie w przeglądarce: **niepotwierdzone** (zakaz `next dev` w tym zadaniu).
