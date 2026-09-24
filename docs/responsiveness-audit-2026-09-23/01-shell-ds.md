# Audyt responsywności — shell aplikacji, warstwy pływające, kit DS i prymitywy UI

Zakres: `src/components/v2/shell/*`, `src/app/layout.tsx`, `src/app/globals.css`, warstwy pływające (Jarvis, Moi ludzie, powiadomienia, toasty, skróty, onboarding), `src/components/ds/*`, `src/components/ui/*`.
Metoda: statyczny odczyt kodu (bez uruchamiania). Szerokości w pikselach szacowane z klas Tailwind — oznaczone „≈”.

**Breakpointy:** `globals.css` ma `@theme inline` wyłącznie z kolorami/animacjami — **brak nadpisań `--breakpoint-*`**, więc obowiązują domyślne Tailwind v4: sm 640 · md 768 · lg 1024 · xl 1280 · 2xl 1536.

**Viewport meta:** `layout.tsx` nie eksportuje `viewport`, więc Next 15 wstawia domyślne `width=device-width, initial-scale=1` — poprawne (brak `user-scalable=no`, zoom działa).

**Podsumowanie:** P0 — 2 · P1 — 8 · P2 — 18

---

## P0 — nie da się używać na telefonie

### P0-1. Pasek górny wypycha „Dodaj” i dzwonek poza ekran przy 375–430 px
- **Plik:** `src/components/v2/shell/TopbarV2.tsx:103-150` (header), `:121-137` (przycisk wyszukiwania), `:139-150` (klaster ikon)
- **Co się psuje:** na telefonie w pasku są: hamburger 32 px, przycisk wyszukiwania (`flex-1`) i klaster `shrink-0`: PaletteSwitcher 32 + tryb Kids 32 + motyw 32 + Moi ludzie 36 (`size="icon"`) + dzwonek 36 (`p-2` + ikona 20) + „Dodaj” ≈40 (`size="sm"`, sama ikona) + 5 × `gap-2` ≈ **248 px**. Do tego `px-4` (32) i 2 × `gap-3` (24). Przy 375 px na wyszukiwanie zostaje ≈39 px, a jego minimalna szerokość to ≈100 px (`px-3` 24 + ikona 16 + gap 8 + `<Kbd>⌘</Kbd><Kbd>K</Kbd>` ≈44, `shrink-0`; na Androidzie „Ctrl” ≈114 px). Wiersz przelewa się o ≈60 px (Android ≈75 px). Rodzic (`AppShellV2.tsx:196`, `overflow-hidden`) ucina nadmiar — **przycisk „Dodaj” i część dzwonka są poza ekranem i nie da się ich kliknąć**. Przy 390 px (iPhone 14) nadal ≈45 px; dopiero ≈430 px mieści się na styk. Użytkownik bez „Moich ludzi” też przelewa się na Androidzie.
- **Poprawka:**
  - Klaster: `PaletteSwitcher`, `KidsModeToggleButton`, `ThemeToggleButton` → owinąć w `<div className="hidden sm:flex items-center gap-2">` (na telefonie przenieść do menu profilu w szufladzie).
  - Skróty w przycisku wyszukiwania: `<div className="ml-auto hidden sm:flex items-center gap-1 shrink-0">`.
  - Przycisk wyszukiwania: `min-w-0` + na telefonie sama ikona: `<span className="truncate hidden sm:inline">…</span>` i `className="flex-1 min-w-0 sm:max-w-md …"`; albo na <sm `w-9 flex-none justify-center px-0`.
  - Header: `gap-2 sm:gap-3 px-3 md:px-5`.

### P0-2. `h-screen` w korzeniu shella — dół każdej strony pod paskiem przeglądarki mobilnej
- **Plik:** `src/components/v2/shell/AppShellV2.tsx:166` (`flex h-screen overflow-hidden`), przewijanie w `:207` (`main … overflow-y-auto`)
- **Co się psuje:** `100vh` na iOS Safari i Chrome Android to wysokość „dużego” viewportu (pasek adresu schowany). Ponieważ strona przewija się w `<main>`, a nie w `body`, pasek przeglądarki **nigdy się nie chowa**, więc dolne ≈56–80 px shella leży stale pod paskiem narzędzi. Ostatnie wiersze list, przyciski „Zapisz” na końcu formularzy i paski akcji przyklejone do dołu `<main>` są niewidoczne i nie da się ich przewinąć do widoku. Dotyczy **każdego ekranu z shellem** na telefonie. W całym `src/` jest 0 użyć `dvh`/`svh` i 52 pliki z `h-screen`/`100vh`.
- **Poprawka:** `className="app-shell-root flex h-dvh overflow-hidden …"` (Tailwind v4 ma `h-dvh`; przeglądarki bez `dvh` → fallback `h-screen h-dvh`, bo późniejsza klasa wygrywa tylko tam, gdzie jest wspierana — w v4 zapis `h-screen supports-[height:100dvh]:h-dvh`). Tę samą zamianę zastosować w `Kanban.tsx:50`, `dialog.tsx:60`, `sheet.tsx:35-36`, `JarvisPanel.tsx:67`, `SidebarMore.tsx:207`.

---

## P1 — rozjechany układ, przelew, ukryta treść

### P1-1. Pasek górny przelewa się także na tablecie i małym laptopie (768–1100 px)
- **Plik:** `TopbarV2.tsx:117` (`hidden md:flex min-w-0 max-w-[360px] flex-1 md:flex-none`), `:140` (`MyKpiWidget … hidden md:block`), `MyKpiWidget.tsx:211-219` (3 wartości KPI od `lg`)
- **Co się psuje:** od `md` okruszki mają `md:flex-none` (`flex: 0 0 auto`) — **nie kurczą się**, mimo `min-w-0` i `truncate` wewnątrz. Przy 768 px z domyślnie przypiętym paskiem bocznym (240 px, patrz P1-4) na header zostaje ≈488 px, a potrzeba ≈690 px (okruszki ≈250 + wyszukiwanie ≈100 + „KPI” ≈60 + klaster 248 + odstępy) → ≈200 px ucięte (dzwonek, „Dodaj”, Moi ludzie). Przy 1024 px z przypiętym paskiem: ≈744 px dostępne vs ≈830 px (od `lg` KPI pokazuje 3 wartości ≈200 px) → „Dodaj” ucięte. Od 1280 px mieści się.
- **Poprawka:** `TopbarV2.tsx:117` → `hidden md:flex min-w-0 max-w-[360px] md:flex-initial md:shrink` (albo `md:flex-1 lg:max-w-[360px]`); w `MyKpiWidget.tsx:211` i `:219` zmienić `lg:` → `xl:`; przełączniki motywu/palety/Kids pokazywać dopiero od `xl` (`hidden xl:flex`), a poniżej przenieść je do menu profilu.

### P1-2. Lista powiadomień ucięta z lewej na telefonie
- **Plik:** `src/components/NotificationsDropdown.tsx:643` (`absolute right-0 top-full mt-2 w-96 …`), `:711` (`max-h-[420px]`)
- **Co się psuje:** panel ma 384 px i jest przyklejony prawą krawędzią do dzwonka, który na telefonie stoi ≈60 px od prawej krawędzi (za nim „Dodaj”). Lewa krawędź wypada ≈−70 px, a kolumna shella (`overflow-hidden`) ją ucina: ikony typów, początki tytułów i nagłówek „Powiadomienia” są niewidoczne. `max-h-[420px]` nie liczy się z wysokością ekranu — na telefonie w poziomie dół listy i stopka „Pokaż więcej” wypadają poza kolumnę.
- **Poprawka:** `fixed inset-x-2 top-14 sm:absolute sm:inset-x-auto sm:right-0 sm:top-full sm:mt-2 sm:w-96 …`; lista: `max-h-[min(420px,calc(100dvh-10rem))] overflow-y-auto`.

### P1-3. Toast powiadomienia w czasie rzeczywistym wyjeżdża za lewą krawędź
- **Plik:** `NotificationsDropdown.tsx:468` (`fixed bottom-6 right-6 … max-w-sm w-full`)
- **Co się psuje:** `w-full` = 100% viewportu (375 px), `max-w-sm` = 384 px nie ogranicza, a `right-6` przesuwa całość o 24 px → lewa krawędź na −24 px, tekst i ikona ucięte. Leży dokładnie na maskotce Jarvisa.
- **Poprawka:** `fixed inset-x-4 bottom-4 sm:inset-x-auto sm:right-6 sm:bottom-6 sm:w-full sm:max-w-sm …`.

### P1-4. Tablet: pasek boczny domyślnie przypięty (240 px), a rozwinięcie po najechaniu zostaje po dotknięciu
- **Plik:** `src/components/v2/shell/useSidebarPinned.ts:18` (`useState(true)` — domyślnie przypięty), `SidebarV2.tsx:162-163` (`onMouseEnter/onMouseLeave`), `:158`, `AppShellV2.tsx:185` (`hidden md:flex` — pełny pasek od 768 px)
- **Co się psuje:** (a) na iPadzie w pionie (768–1023) domyślnie przypięty pasek 240 px zostawia treści ≈528 px (≈480 po `p-6`) — strony projektowane na desktop ściskają się, a topbar przelewa się (P1-1). (b) Na urządzeniach dotykowych stuknięcie w ikonę zwiniętej szyny emituje `mouseenter` → szyna rozwija się **nakładką 240 px nad treścią** i zostaje rozwinięta po nawigacji (zmiana trasy nie zeruje `hovered`) — zasłania 180 px strony, dopóki użytkownik nie stuknie gdzie indziej (a to stuknięcie trafia w treść pod spodem).
- **Poprawka:** (a) domyślne `pinned` zależne od szerokości: w efekcie `if (stored === null) setPinned(window.matchMedia("(min-width: 1280px)").matches)`; (b) rozwijanie po najechaniu tylko dla myszy: `onPointerEnter={(e) => e.pointerType === "mouse" && !mobileOpen && setHovered(true)}` / `onPointerLeave` analogicznie, plus `setHovered(false)` w efekcie na zmianę `pathname`.

### P1-5. Pola tekstowe 14 px → automatyczny zoom na iOS
- **Plik:** `src/app/globals.css:541-554` (`input[type=…], select, textarea { @apply text-sm; }`), `src/components/ui/input.tsx:19`, `textarea.tsx:16`, `select.tsx:19`, `command.tsx:63` (pole palety ⌘K, autofocus), `ds/FilterBar.tsx:100` (`h-9 … text-sm`), `jarvis/JarvisPanel.tsx:282` (autofocus)
- **Co się psuje:** iOS Safari powiększa stronę przy fokusie pola z czcionką < 16 px i nie oddala po wyjściu. Przy shellu `h-screen overflow-hidden` po powiększeniu topbar i pasek boczny wyjeżdżają poza widok, a strona wygląda na „rozjechaną” w poziomie. Najbardziej odczuwalne w palecie ⌘K i Jarvisie (pola dostają fokus automatycznie).
- **Poprawka:** w `globals.css` zamienić regułę na `@apply text-base sm:text-sm;`; w prymitywach `text-base sm:text-sm` (input, textarea, select trigger, `CommandPrimitive.Input`, pole FilterBar, textarea Jarvisa).

### P1-6. Paleta ⌘K na krótkich ekranach: dół wyników nieosiągalny, brak zamknięcia na dotyk
- **Plik:** `src/components/ui/command.tsx:43` (`DialogContent size="lg" className="p-0 overflow-hidden" hideClose`), `:78` (`CommandList max-h-[420px]`), `dialog.tsx:59-60` (`top-[50%] translate-y-[-50%] … max-h-[90vh] overflow-hidden`)
- **Co się psuje:** lista ma stałe 420 px + pole 48 px = 468 px, a okno ma `max-h-[90vh]` i `overflow-hidden`. Na telefonie w poziomie (≈360–390 px wysokości → 90vh ≈330 px) i przy otwartej klawiaturze dolne ≈130 px listy są ucięte przez okno, a sama lista przewija się tylko w obrębie swoich 420 px — ostatnie wyniki są nieosiągalne. Okno jest wyśrodkowane w pionie, więc klawiatura iOS zasłania jego dolną połowę. `hideClose` = brak widocznego przycisku zamknięcia (na telefonie nie ma Esc). Na telefonie to **główne wejście do wyszukiwania** (przycisk w topbarze otwiera paletę).
- **Poprawka:** `DialogContent … className="p-0 overflow-hidden top-4 translate-y-0 sm:top-[50%] sm:translate-y-[-50%] max-h-[calc(100dvh-2rem)]"`; `Command` jako `flex flex-col min-h-0`, `CommandList` → `max-h-[min(420px,calc(100dvh-7rem))]` (lub `flex-1 min-h-0`); na <sm dodać przycisk „Anuluj” obok pola (`sm:hidden`).

### P1-7. Maskotki w prawym dolnym rogu zasłaniają treść na telefonie
- **Plik:** `src/components/jarvis/JarvisMascot.tsx:47` (`fixed bottom-4 right-4 z-30`, rozmiar 64 px, `:43`), `src/components/v2/my-people/MyPeopleLauncher.tsx:102` (`fixed bottom-5 right-5 z-30`, 48 px), `AppShellV2.tsx:208` (`p-4 md:p-6` — brak zapasu na dole)
- **Co się psuje:** na 375 px maskotka Jarvisa (64 px) leży na treści `<main>`, a `<main>` ma tylko 16 px dolnego paddingu — ostatnie przyciski po prawej (paginacja „Dalej”, „Zapisz” wyrównane do prawej, akcje ostatniego wiersza tabeli, paski akcji przyklejone do dołu) są zasłonięte i nie da się ich wyprzewijać spod maskotki. Dymek Jarvisa (`max-w-[240px]`) i dymek „Moich ludzi” (`max-w-[260px]`) zakrywają dodatkowo ≈2/3 szerokości ekranu.
- **Poprawka:** na <md maskotka domyślnie zminimalizowana (40 px) i `bottom-[max(1rem,env(safe-area-inset-bottom))]`; zapas w treści: `AppShellV2.tsx:208` → `p-4 pb-24 md:p-6` (albo warunkowo, gdy maskotka jest widoczna); dymki `max-w-[min(240px,calc(100vw-6rem))]`.

### P1-8. Kafle `StatCard` w siatce 2-kolumnowej przelewają się na 375 px
- **Plik:** `src/components/ds/StatCard.tsx:148` (`grid grid-cols-2 gap-4 lg:grid-cols-4`), `:107` (`p-5`), `:121-130` (wartość `text-[32px]` + sparkline `shrink-0`)
- **Co się psuje:** przy 375 px kafel ma ≈163 px, treść ≈123 px. Wartość 32 px bez `truncate`/łamania (np. „12 345 zł”) ma ≈150 px i wychodzi poza kafel; ze sparkline (stała szerokość, `shrink-0`) na liczbę zostaje ≈20–30 px. Wiersz etykiety (`:110-119`) z ikoną, etykietą i pigułką trendu nie ma `min-w-0`. Używane w Cortex (`TechMapPanel`, `CoverageView`) i `PastelKpi` pulpitu DL.
- **Poprawka:** siatka `grid-cols-1 min-[420px]:grid-cols-2 lg:grid-cols-4`; wartość `text-2xl sm:text-[32px] break-words`; sparkline `hidden sm:block`; kafel `p-4 sm:p-5`; wiersz etykiety `min-w-0` + `truncate` na etykiecie.

---

## P2 — kosmetyka i ergonomia

| # | Plik:linia | Element | Problem (szerokość) | Poprawka |
|---|---|---|---|---|
| 1 | `ui/dialog.tsx:59-60` | `DialogContent` | `w-full` → przy <448 px okno dotyka krawędzi ekranu (zaokrąglone rogi i ramka ucięte wizualnie); `max-h-[90vh]` na iOS liczy duży viewport — stopka potrafi wejść pod pasek Safari | `w-[calc(100%-1.5rem)] sm:w-full`, `max-h-[calc(100dvh-2rem)]` |
| 2 | `ui/sheet.tsx:35-36`, `:70-71` | `SheetContent` top/bottom, przycisk zamknięcia | `max-h-[85vh]` (vh na mobile); przycisk zamknięcia `p-1` = 24 px (w `dialog.tsx:75` jest 44 px — niespójność); dolny arkusz bez `env(safe-area-inset-bottom)` | `max-h-[85dvh]`; zamknięcie `flex h-11 w-11 items-center justify-center`; bottom: `pb-[env(safe-area-inset-bottom)]` |
| 3 | `ui/popover.tsx:21`, `ui/dropdown-menu.tsx:41,58`, `ui/select.tsx:70` | Popover / menu / Select | brak ograniczenia wysokości do dostępnego miejsca — długie menu (np. filtry) na telefonie w poziomie wychodzą poza ekran (menu ma `overflow-hidden`, więc dół niedostępny); Select `max-h-96` (384 px) > wysokość telefonu w poziomie | popover/menu: `max-h-(--radix-popover-content-available-height)` / `max-h-(--radix-dropdown-menu-content-available-height) overflow-y-auto`, `max-w-[calc(100vw-1rem)]`; select: `max-h-[min(24rem,var(--radix-select-content-available-height))]` |
| 4 | `ui/tabs.tsx:15` | `TabsList` | `inline-flex` bez zawijania/przewijania — 5 miejsc używa go bezpośrednio; przy 375 px wiele zakładek przelewa się poza kontener. `ds/TabbedNav.tsx:40` domyślnie `overflow="wrap"` — zakładki łamią się w 2–3 rzędy z podkreśleniami w złych miejscach | `TabsList`: `max-w-full overflow-x-auto` (+ `scrollbar-none`); `TabbedNav`: domyślnie `scroll` poniżej `sm` |
| 5 | `ds/DataTable.tsx:52-53` | `DataTable` | wzorzec Tailwind Plus zakłada padding strony `px-4 / sm:px-6 / lg:px-8`, a shell ma `p-4 md:p-6` i hosty (np. `cortex/CoveragePanel.tsx:126`) `p-6`. Od `lg` `-mx-8` wystaje 8 px poza kartę z obu stron (podkreślenia wierszy i tło hover wychodzą za kartę); na 640–767 px wychodzi poza padding `<main>` | ujednolicić z shellem: `-mx-4 sm:-mx-6` bez `lg:-mx-8` i `sm:px-6` bez `lg:px-8`, albo prop `bleed={false}` dla użycia w kartach |
| 6 | `ds/VirtualTable.tsx:515`, `:220`, `:523` | `VirtualTable` | brak `min-width` dla siatki — przy wąskim kontenerze kolumny `px` przelewają się, a tło/ramka nagłówka (szerokość 100%) nie idą za przewijaniem w poziomie; checkboxy `size-3.5` (14 px) jako cel dotyku | prop `minWidth` → `style={{ minWidth }}` na nagłówku i kontenerze wierszy; checkbox w komórce z `min-h-10 min-w-10` obszarem kliknięcia (label) |
| 7 | `TopbarV2.tsx:36,70,112`, `PaletteSwitcher.tsx:43`, `SidebarV2.tsx:222,366,390`, `SidebarNavLink.tsx:30`, `ds/FilterBar.tsx:111,149`, `ui/dropdown-menu.tsx:76`, `MyPeopleLauncher.tsx:112`, `JarvisMascot.tsx:60` | cele dotyku | przyciski 32 px (topbar, hamburger), 24 px (zamknij/wyloguj w szufladzie, przypięcie), pozycje menu 36 px (`h-9`), usuwanie chipa filtra 16 px (`size-4`), czyszczenie wyszukiwania 24 px, pozycje dropdownu ≈32 px, zamknięcie dymków 16–20 px | na <md `h-10 w-10` (topbar, hamburger, szuflada), pozycje nawigacji w szufladzie `h-10`, chip `size-6` + większy obszar (`p-1.5`), `DropdownMenuItem` `py-2.5 sm:py-1.5` |
| 8 | `SidebarV2.tsx:193,359,383`, `SidebarMore.tsx:77,214`, `SidebarNavLink.tsx:15`, `ui/kbd.tsx`, `ui/table.tsx:104`, `ui/command.tsx:48,57`, `ui/dropdown-menu.tsx:158`, `MyPeopleLauncher.tsx:60,161`, `ds/DataTable.tsx:68`, `ds/VirtualTable.tsx:536`, `SidebarMore.tsx:262` | czcionki | `text-[10px]` (nagłówki grup, rola pod nazwiskiem, liczniki, nagłówki tabel `TableHead`, nagłówki grup palety) i `text-[11px]` — poniżej 12 px, na telefonie trudne do czytania | minimum `text-xs` (12 px) dla treści czytanej; 10 px zostawić tylko w licznikach-plakietkach |
| 9 | `NotificationsDropdown.tsx:781` | wyciszenie kategorii w powiadomieniu | `opacity-0 group-hover:opacity-100 group-focus-within:opacity-100` — na dotyku niewidoczne; stuknięcie w wiersz od razu nawiguje (`:726-733`), więc fokus nigdy nie zostaje; przycisk da się trafić tylko „na ślepo” | `opacity-100 md:opacity-0 md:group-hover:opacity-100 …` (albo `[@media(hover:none)]:opacity-100`) |
| 10 | `AppShellV2.tsx:176-194` | szuflada nawigacji na telefonie | własna implementacja: brak zamknięcia Esc, brak pułapki fokusu, brak `role="dialog" aria-modal`, fokus nie wraca na hamburger | przenieść na `Sheet side="left"` (Radix Dialog) z `SheetContent className="w-64 p-0"` — reszta zachowania (zamykanie przy zmianie trasy) zostaje |
| 11 | `Toast.tsx:136-145`, `QuickActionsV2.tsx:177`, `NotificationsDropdown.tsx:468` | trzy systemy toastów | trzy niezależne kontenery w prawym dolnym rogu (`bottom-4 right-4`, `bottom-4 right-4`, `bottom-6 right-6`) nakładają się na siebie i na maskotkę; toasty z `Toast.tsx` nie mają `max-w` — długi komunikat na desktopie rozciąga się na całą szerokość | jeden kontener: `fixed inset-x-4 bottom-4 sm:inset-x-auto sm:right-4 sm:max-w-sm flex flex-col gap-2`; lokalny toast w `QuickActionsV2` zastąpić `useToast` |
| 12 | `ImpersonationBanner.tsx:23-35` | pasek „Podgląd jako” | na 375 px przycisk „Wróć do swojego konta” (`shrink-0`, ≈190 px) zostawia ≈100 px na komunikat → widać „Podgląd jako Jan…” | `flex-wrap`, tekst `line-clamp-2 sm:truncate`, przycisk na <sm skrócony do „Wróć” (`<span className="hidden sm:inline">…</span>`) |
| 13 | `my-people/MyPeoplePanel.tsx:247` | panel „Moi ludzie” | `top-12` na sztywno = wysokość topbaru; przy widocznym pasku podglądu (≈36 px) panel zachodzi na topbar | pozycjonować względem kolumny shella (np. zmienna CSS `--shell-top` ustawiana przez shell) albo `top-[var(--topbar-bottom,3rem)]` |
| 14 | `jarvis/JarvisPanel.tsx:67` | panel Jarvisa | od `sm` (640 px) tryb pływający — telefon w poziomie (≈740×360) dostaje okno o `max-h-[calc(100vh-7.5rem)]` ≈240 px: nagłówek + pole + przypis zjadają prawie całość; na <sm `fixed inset-0` bez uwzględnienia klawiatury (pole może zejść pod klawiaturę iOS) | pływający od `md` zamiast `sm`; `max-h-[calc(100dvh-7.5rem)]`; w trybie pełnoekranowym `h-dvh` zamiast `inset-0` na wysokość |
| 15 | `OnboardingWalkthrough.tsx:114` | karta powitalna | brak `max-h`/`overflow-y-auto` — karta ≈450 px; na telefonie w poziomie przyciski „Dalej/Pomiń” poza ekranem | `max-h-[calc(100dvh-2rem)] overflow-y-auto` |
| 16 | `ds/Kanban.tsx:50` | kolumna kanbanu DS | `max-h-[calc(100vh-16rem)]` — vh na mobile | `max-h-[calc(100dvh-16rem)]` |
| 17 | `ds/FunnelChart.tsx:56,74` | lejek | stałe `w-24` (etykieta) + `w-16` (procent) + `gap-4` ×2 w karcie `p-6` — przy 375 px pasek ma ≈100 px, a długie etykiety („Rozmowa u klienta”) łamią się w 2–3 linie | etykieta `w-20 sm:w-24 truncate` + `title`; kolumna procentu `hidden sm:block`; karta `p-4 sm:p-6` |
| 18 | `ds/PageHeader.tsx:81-104`, `ds/EntityHeader.tsx:89` | nagłówki | od `sm` akcje mają `shrink-0` obok tytułu — przy 640–900 px i 3+ akcjach tytuł ściska się do wąskiej kolumny; `h1` bez `break-words` | akcje: `sm:shrink sm:justify-end sm:max-w-[60%]`; `h1`: `break-words`; przejście na wiersz od `md` zamiast `sm` |

**Obserwacja (bez numeru, poza zakresem shella):** na 1920 px `<main>` (`AppShellV2.tsx:208`) nie ma maksymalnej szerokości — strony tekstowe mają bardzo długie wiersze. Nie dodawać globalnego `max-w` w shellu (tablice kanbanu i tabele potrzebują pełnej szerokości); ograniczać per strona (`max-w-7xl mx-auto` dla formularzy/ustawień).

---

## Co już jest zrobione dobrze (nie ruszać)

- **Szuflada nawigacji na telefonie:** hamburger `md:hidden` (`TopbarV2.tsx:109-115`), tło z zamykaniem stuknięciem (`AppShellV2.tsx:177-182`), szuflada `fixed inset-y-0 left-0 z-50 w-64` z własnym przewijaniem nawigacji (`SidebarV2.tsx:231`), automatyczne zamykanie przy zmianie trasy (`AppShellV2.tsx:100-102`), „Więcej” w szufladzie renderowane w linii zamiast popovera (`SidebarV2.tsx:260-267`).
- **Kolumna treści:** `flex-1 flex flex-col overflow-hidden min-w-0` (`AppShellV2.tsx:196`) — szeroka treść przewija się w `<main>`, a nie wypycha strony; body nie ma poziomego przewijania.
- **Topbar na telefonie** chowa okruszki i widżet KPI (`hidden md:…`), napis „Dodaj” tylko od `sm` (`QuickActionsV2.tsx:120`).
- **Okruszki:** stałe nazwy sekcji `shrink-0`, skraca się ostatni okruszek i nazwy encji (`BreadcrumbV2.tsx:180-203`).
- **Rozwinięcie szyny po najechaniu jako nakładka** — treść nie przeskakuje w bok (`SidebarV2.tsx:156-171`), stałe pionowe wymiary B57.
- **Popover „Więcej”** ma `max-h-[min(80vh,640px)] overflow-y-auto` (`SidebarMore.tsx:207`).
- **Widżet KPI** otwiera szczegóły kliknięciem/fokusem, nie tylko najechaniem (`MyKpiWidget.tsx:183-203`).
- **Prymityw `Table`** owija tabelę w `overflow-auto` (`ui/table.tsx:27`); `Leaderboard` z niego korzysta.
- **Dialog:** `DialogBody` przewija się (`overflow-y-auto flex-1 min-h-0`), stopka `flex-col-reverse sm:flex-row` (przyciski na pełną szerokość na telefonie), przycisk zamknięcia 44 × 44 px (`dialog.tsx:75`), rozmiary `max-w-*` zamiast stałych szerokości.
- **Sheet** boczny na telefonie `w-full`, od `sm` `max-w-*` (`sheet.tsx:33-43`); `SheetBody` przewija się.
- **Jarvis** na <sm otwiera się pełnoekranowo (`JarvisPanel.tsx:67`), maskotka ma mniejsze odsunięcie na telefonie (`JarvisMascot.tsx:47`); „Moi ludzie” ustępują rogu Jarvisowi (`MyPeopleLauncher.tsx:180-226`) i znikają na `/jobs/{id}`.
- **Panel „Moi ludzie”** `w-full max-w-[420px]` (`MyPeoplePanel.tsx:247`).
- **Toasty** mają cele dotyku `min-h-11 min-w-11` dla akcji i zamknięcia (`Toast.tsx:179,188`).
- **Kit DS:** `PageHeader` i `EntityHeader` `flex-col sm:flex-row`; `FormGroup` `grid-cols-1 sm:grid-cols-2` i `sm:grid-cols-[minmax(0,12rem)_minmax(0,1fr)]`; `KeyFacts` responsywne kolumny 1→2→3/4; `FilterBar` `flex-wrap` i pole `min-w-48 flex-1 sm:max-w-sm`; `MatchCard` siatka `1 → sm:2 → lg:3`; `TabbedNav` ma tryb `overflow="scroll"`; `Kanban` `overflow-x-auto` z kolumnami `w-72` (mieści się w 375 px); `VirtualTable` komórki `min-w-0 truncate`.
- **Pola formularzy** `Input`/`Select` mają wysokość 40 px (`h-10`); skip link „Przejdź do treści” działa klawiaturą.
- **Viewport:** domyślny meta Next 15 (`width=device-width, initial-scale=1`), bez blokady zoomu.

---

## Kolejność napraw (propozycja)

1. P0-2 (`h-dvh`) i P0-1 (klaster topbaru) — jeden mały PR w `AppShellV2`/`TopbarV2`, przeklikać na 375/390/430 px.
2. P1-1 + P1-4 (topbar i pasek boczny na tablecie), P1-2/P1-3 (powiadomienia).
3. P1-5 (16 px w polach — jedna zmiana w `globals.css` + prymitywy) i P1-6 (paleta).
4. P1-7, P1-8, potem P2 zaczynając od prymitywów (`dialog`, `popover`, `dropdown`, `tabs`) — naprawa w prymitywie działa na wszystkich ekranach naraz.
