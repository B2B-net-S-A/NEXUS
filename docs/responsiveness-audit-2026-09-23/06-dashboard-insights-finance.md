# Audyt responsywności 06 — Pulpit, Insights, Finanse, Cortex, DynaReporter

Zakres: `src/app/dashboard/**`, `src/components/v2/dashboard/**` (w tym siatka własnego pulpitu), widżety ze starego pulpitu ról montowane jako kafelki, `src/app/insights/**` + `src/components/insights/**`, `src/app/finance/**` + `src/components/finance/**`, `src/app/dynareporter/**`, `src/app/cortex/**` + `src/components/cortex/**`, `src/app/manager/**`, wykresy (recharts), `AnalyticsTab.tsx`, `StatsCard`, `ds/FunnelChart`, `ds/Leaderboard`.

Metoda: statyczny odczyt kodu (bez uruchamiania). Każde ustalenie sprawdzone w pliku; szerokości policzone z rzeczywistych klas powłoki. Nic nie zostało sprawdzone w przeglądarce — zachowanie na urządzeniu jest **niepotwierdzone**, chyba że wynika wprost z CSS.

## Założenia do liczenia szerokości

- Breakpointy Tailwind domyślne (`@theme inline` w `globals.css` ich nie nadpisuje): sm 640, md 768, lg 1024, xl 1280, 2xl 1536.
- Tailwind v4: `hover:`/`group-hover:` działa tylko pod `@media (hover: hover)` — na dotyku te style **nigdy** się nie włączają.
- Powłoka (`AppShellV2.tsx:185-208`): pasek boczny od `md` (768), domyślnie zwinięty 60 px (przypięty 240 px), `<main>` ma `p-4 md:p-6`.
- Szerokość treści (zwinięty pasek): 375 → **343 px**, 768 → **660 px**, 1024 → **916 px**, 1280 → **1172 px**, 1920 → **1812 px**. Strony, które dokładają własne `p-6`, tracą kolejne 48 px (np. Insights przy 375 → **295 px**).
- Siatka pulpitu: 12 kolumn, odstęp 16 px (`layout.ts:14-16`). Szerokość kafelka `w` = `w·kol + (w−1)·16`.

| Szerokość okna | treść pulpitu* | kolumna | kafelek w=2 | w=4 | w=6 |
|---|---|---|---|---|---|
| 768 | 612 | — (lista mobilna) | — | — | — |
| 1024 | 868 | 57 | 130 | 276 | 422 |
| 1280 | 1124 | 79 | 174 | 364 | 554 |
| 1920 | 1764 | 132 | 280 | 576 | 872 |

\* `CustomDashboard` dokłada własne `p-4 sm:p-6`, więc od szerokości treści powłoki odejmuje się jeszcze 48 px.

## Podsumowanie

| Waga | Liczba |
|---|---|
| P0 — nieużywalne na telefonie/tablecie | 0 |
| P1 — rozjechany układ, poziomy scroll strony, ukryta treść, funkcja nieosiągalna dotykiem | 14 |
| P2 — kosmetyka, ergonomia | 19 |

Brak P0: każdy ekran w zakresie da się przeczytać i obsłużyć, choć czasem przez poziome przewijanie całej strony. Największe ryzyko to dwa błędy systemowe: (1) widżety w kafelkach reagują na szerokość **okna**, a nie kafelka, oraz (2) kafle KPI z kwotami PLN (twarda spacja z `Intl`) wypychają treść poza kartę w siatce `grid-cols-2`.

---

## P1

### P1-01. „Edytuj układ” widoczny, ale siatka jest w trybie listy — edycja nic nie robi
- **Plik:** `src/components/v2/dashboard/custom/CustomDashboard.tsx:309` (`hidden md:inline-flex`) vs `src/components/v2/dashboard/custom/DashboardGrid.tsx:26,88-91` (`MOBILE_BREAKPOINT = 768` liczony od szerokości **kontenera**) i `:57` (lista zawsze `editing={false}`).
- **Co się psuje:** przycisk pokazuje się od okna 768 px, a siatka przełącza się na tryb pulpitu dopiero przy kontenerze ≥ 768 px, czyli przy oknie ≥ ~924 px (zwinięty pasek) albo ≥ ~1104 px (przypięty pasek). W tym przedziale (iPad pionowo 768–834, mały laptop z przypiętym paskiem) po kliknięciu pojawia się czarny pasek „Tryb edycji” z „Zapisz układ”, ale kafelków nie da się przeciągnąć ani zmienić ich rozmiaru.
- **Poprawka:** jedno źródło prawdy. Albo `DashboardGrid` wystawia `mobile` (np. callback `onModeChange`) i `CustomDashboard` renderuje przycisk tylko przy `!mobile`, albo próg liczony od okna (`useMediaQuery("(min-width: 1024px)")`) w obu miejscach. Najprościej: przycisk z `hidden lg:inline-flex`, a `MOBILE_BREAKPOINT` porównywany z `window.innerWidth` zamiast szerokości kontenera.

### P1-02. Widżety w kafelkach używają breakpointów okna, nie kafelka (błąd systemowy)
- **Pliki i szerokości:**
  - `src/components/v2/dashboard/RecruitmentCompetenceDashboard.tsx:403` — `lg:grid-cols-[minmax(190px,0.8fr)_minmax(330px,1.5fr)_minmax(230px,1fr)]` wymaga ≥ 782 px; kafelek `recruitment_competence` ma min. w=6 = **554 px przy 1280** i **422 px przy 1024**. Wynik: poziomy scroll wewnątrz kafelka i ucięta prawa kolumna.
  - `src/components/v2/dashboard/RecruitmentActivityDashboard.tsx:283` — `sm:grid-cols-[minmax(180px,…)_minmax(220px,…)_auto]` (≥ ~516 px) w kafelku w=6 przy 1024 (422 px); `:680` — `lg:grid-cols-5` w kafelku 422–554 px daje kolumny ~80 px.
  - `src/components/candidate-contact/ContactOversightPanel.tsx:154` — `lg:grid-cols-6` liczb w kafelku w=6 (6 kafli po ~75 px).
  - `src/components/v2/kpi/MyKpiWidget.tsx:156,167` — `lg:grid-cols-3` w kafelku `my_kpis_today` o min. w=4 (**364 px przy 1280** → 3 karty po ~110 px).
  - `src/components/v2/priority-work/TeamAllocationBoard.tsx:1781` — `xl:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]` w kafelku w=6 przy 1280 (554 px) → główna kolumna ~250 px.
- **Co się psuje:** odwrotność problemu mobilnego: im **szersze okno**, tym gęstszy układ w **wąskim** kafelku. Treść kafelka ma `overflow-auto` (`TileFrame.tsx:148`), więc zamiast zawijania pojawia się poziomy pasek przewijania w kafelku.
- **Poprawka:** kontenerowe zapytania Tailwind v4. W `TileFrame.tsx` na div treści (`:145`) dodać `@container`, a w widżetach zamienić `lg:`/`xl:`/`sm:` na `@3xl:` / `@5xl:` / `@lg:` (np. `@4xl:grid-cols-[minmax(190px,0.8fr)_minmax(330px,1.5fr)_minmax(230px,1fr)]`, `@2xl:grid-cols-6`, `@xl:grid-cols-3`). Poza pulpitem (ekrany, na których te widżety są pełnej szerokości) `@container` na rodzicu zachowuje dzisiejszy wygląd. Alternatywa minimalna: podnieść `minSize.w` tych kafelków do 12.

### P1-03. Menu kafelków z własną kartą jest niewidoczne na dotyku
- **Plik:** `src/components/v2/dashboard/custom/TileFrame.tsx:155` — `opacity-0 … group-hover:opacity-100`.
- **Co się psuje:** w Tailwind v4 `group-hover` działa tylko pod `(hover: hover)`, więc na telefonie i tablecie przycisk „⋯” widżetów ze starego pulpitu (`ownChrome`: zadania, kolejki, KPI, alerty DL…) ma zawsze przezroczystość 0. Na telefonie tryb edycji jest ukryty (P1-01), więc to menu jest **jedynym** miejscem na „Ustawienia kafelka / Duplikuj / Usuń z pulpitu” — a użytkownik go nie widzi (działa tylko przypadkowe stuknięcie w prawy górny róg).
- **Poprawka:** `opacity-100 pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100 pointer-fine:focus-within:opacity-100` (albo `[@media(hover:hover)]:opacity-0`).

### P1-04. Kafel liczby ucina wartość w wąskim kafelku
- **Plik:** `src/components/v2/dashboard/custom/MetricTileBody.tsx:80-101` (`text-3xl` + stały wykresik `w-24`), przycięcie przez `TileFrame.tsx:148` (`overflow-hidden` dla `metric_number`).
- **Co się psuje:** na telefonie kafel liczby ≤ w=4 idzie w pół szerokości (`isCompactOnMobile`, `layout.ts:153`): ~150 px − `p-4` = ~118 px; przy 1024 kafel w=2 ma 130 − 32 = ~98 px. Kwota „1 234 567 zł” w `text-3xl` (~200 px) plus 96 px wykresiku nie mieści się i jest ucinana bez wielokropka; lewy blok nie ma `min-w-0`.
- **Poprawka:** lewy div `min-w-0 flex-1`, liczba `truncate text-2xl @[12rem]:text-3xl` (z `@container` jak w P1-02), wykresik `hidden @[14rem]:flex`; tooltip/`title` z pełną wartością.

### P1-05. Przełącznik rozdziałów Body Leasing wychodzi poza ekran na telefonie
- **Plik:** `src/components/insights/BodyLeasingPanel.tsx:74-77` — `inline-flex gap-0.5` bez zawijania, przyciski `px-4` z ikoną.
- **Co się psuje:** trzy przyciski (Rywalizacja / Wyniki / Klienci) mają razem ~330 px, a treść Insights przy 375 to 295 px (P2-01). Strona przewija się w poziomie.
- **Poprawka:** `flex w-full overflow-x-auto sm:inline-flex sm:w-auto`, przyciski `shrink-0 whitespace-nowrap px-3 sm:px-4`; albo ukryć ikony poniżej `sm` (`hidden sm:block` na `<Icon>`).

### P1-06. Pasek okresu (`PeriodPicker`) szerszy niż telefon
- **Plik:** `src/components/insights/PeriodPicker.tsx:155-175` — grupa 5 przycisków (Tydzień / Miesiąc / Kwartał / Rok / Wszystko) w `flex overflow-hidden` bez zawijania, ~340 px.
- **Co się psuje:** przy 375 (295 px treści) grupa wystaje poza stronę; dotyczy Wyników, Klientów i Rady. Strzałki `p-1.5` to cele 28 px.
- **Poprawka:** na grupie `max-w-full overflow-x-auto`, przyciski `shrink-0 whitespace-nowrap px-2.5 sm:px-3`; albo poniżej `sm` zastąpić grupę `<select>`. Korzeń `flex-col items-end` → `items-stretch sm:items-end`. Strzałki `p-2.5` (≥ 40 px).

### P1-07. Nagłówek Rady nie zawija się — opis ściśnięty do jednego słowa w linii
- **Plik:** `src/components/insights/RadaNadzorczaPanel.tsx:76` — `flex items-start justify-between gap-4` bez `flex-wrap`, obok `PeriodPicker` o minimalnej szerokości ~340 px.
- **Co się psuje:** przy 375 akapit dostaje ujemne miejsce → pionowa kolumna pojedynczych słów i poziomy scroll strony (~130 px nadmiaru). Przy 768 akapit ma ~256 px (czytelne, ale ciasne).
- **Poprawka:** `flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between`, akapit `lg:max-w-xl`.

### P1-08. Kafle KPI z kwotami PLN wychodzą poza kartę
- **Pliki:** `src/components/insights/sections/_shared.tsx:67-75` (`KpiCard`: `p-5`, wartość `text-2xl font-bold` bez zawijania) w siatkach `grid-cols-2`: `InsightsClientsRanking.tsx:102`, `InsightsBoardKPI.tsx:128,171,235`, `InsightsDlPortfolio.tsx:321`, `InsightsInviteLinks.tsx:79`. Też `src/components/AnalyticsTab.tsx:104` (+ wartość `text-xl` w `:185`).
- **Co się psuje:** `Intl.NumberFormat("pl-PL", {style:"currency"})` (`_shared.tsx:18-24`) wstawia **twardą spację** między grupy cyfr, więc „12 772 543 zł” nie zawija się. Przy 375 karta ma ~140 px, wnętrze ~100 px, a kwota w `text-2xl` ~180 px — tekst wychodzi poza obramowanie karty (i poza ekran w prawej kolumnie).
- **Poprawka:** `grid-cols-1 min-[420px]:grid-cols-2 md:grid-cols-4`, na karcie `min-w-0`, wartość `truncate text-xl sm:text-2xl tabular-nums` + `title={value}`; `p-4 sm:p-5`. Dla kafli pieniężnych rozważyć format skrócony na telefonie („12,8 mln zł”).

### P1-09. Lejek rekrutacji traci pasek na telefonie
- **Plik:** `src/components/insights/sections/RecruitmentFunnel.tsx:74-104` — etykieta `w-44`, liczba `w-12`, procent `w-16` + 3×`gap-3`.
- **Co się psuje:** stałe elementy zajmują ~324 px, a karta przy 375 ma ~247 px wnętrza. Pasek (`flex-1`) spada do 0 px — lejek przestaje być lejkiem; liczby i procenty się ściskają.
- **Poprawka:** etykieta `w-24 sm:w-44 shrink-0`, liczba `w-10 sm:w-12 shrink-0`, procent `hidden sm:block w-16 shrink-0`, pasek `min-w-12`. Na telefonie można też przenieść etykietę nad pasek (`flex-col sm:flex-row`).

### P1-10. Tabela źródeł kandydatów ucina kolumny zamiast przewijać
- **Plik:** `src/components/insights/sections/SourcesFunnelSection.tsx:44` — wrapper `overflow-hidden`, tabela `w-full` bez `min-w`.
- **Co się psuje:** w trybie „Grupuj po UTM” 6 kolumn z `px-4` i paskiem `w-20` nie mieści się w ~247 px; kolumny „Zatrudnieni” i „Hire-rate” zostają ucięte bez możliwości przewinięcia.
- **Poprawka:** `overflow-x-auto` (zostawić zaokrąglenie przez `rounded-xl` + `overflow-hidden` na zewnętrznym divie, tabela w wewnętrznym `overflow-x-auto`), tabela `min-w-[520px]`, komórki `px-3 sm:px-4`.

### P1-11. Wykres trendu Rady ma wartości tylko w `title` (hover)
- **Plik:** `src/components/insights/sections/InsightsBoardKPI.tsx:359-392` (wartość słupka wyłącznie w `title=` na `div`, `cursor-help`), `:398` (etykiety miesięcy `text-[9px]`).
- **Co się psuje:** na dotyku nie ma sposobu, żeby odczytać kwotę słupka ani informację „dane niepełne, brak kursu NBP”; etykiety 9 px są nieczytelne przy 12 słupkach w ~250 px.
- **Poprawka:** słupki jako `<button>` z Popoverem po stuknięciu albo tabela/lista wartości pod wykresem (`<details>` „Pokaż wartości”); etykiety `text-[11px]`, na telefonie co druga (`max-sm:[&:nth-child(even)]:invisible`).

### P1-12. Przełącznik trybów Finansów wychodzi poza ekran
- **Plik:** `src/app/finance/page.tsx:128-162` (+ `ModeButton` `:225`) — `inline-flex` z 5 przyciskami o długich etykietach („Zmiany w zamówieniach”, „Import zużycia MD”).
- **Co się psuje:** suma szerokości minimalnych ~460 px > 343 px przy 375 → poziomy scroll strony; przy 768 (660 px) etykiety łamią się na 2 linie w nierównych przyciskach.
- **Poprawka:** kontener `flex w-full max-w-full overflow-x-auto sm:inline-flex sm:w-auto`, przyciski `shrink-0 whitespace-nowrap`; albo użyć istniejącego `ds/TabbedNav` z `overflow="scroll"` (tak jak `OrderChangesPanel`).

### P1-13. Edycja komórek wyników finansowych tylko dwuklikiem
- **Plik:** `src/components/finance/EditableCell.tsx:101-103` (`onDoubleClick={begin}`, wskazówka tylko w `title`).
- **Co się psuje:** na tablecie dwukrotne stuknięcie w Safari jest gestem powiększenia, a `dblclick` na dotyku nie jest niezawodny (niepotwierdzone na urządzeniu). Wskazówka „Kliknij dwukrotnie” jest w `title`, więc na dotyku niewidoczna — edycja kwot (główna funkcja zakładki dla Finansów) może być nieosiągalna. Pole edycji `text-sm` powoduje też powiększanie strony w iOS.
- **Poprawka:** `onClick` gdy `matchMedia("(pointer: coarse)")` albo widoczna ikona ołówka (`pointer-coarse:inline-flex hidden`) w komórce; `<input className="text-base sm:text-sm">`.

### P1-14. DynaReporter → Pracownicy: trzy daty bez etykiet, 10 px
- **Plik:** `src/app/dynareporter/admin-dashboard/_modules/EmployeesManager.tsx:343-371` — `grid grid-cols-3` trzech `type="date"` z `text-[10px]`, opisane tylko przez `title`.
- **Co się psuje:** na dotyku nie wiadomo, które pole to „Acceleration start”, „Senior since”, „Expert since”; pola 10 px wywołują powiększenie w iOS i są za małe do stuknięcia (wiersz tabeli ma kolumny `px-2`).
- **Poprawka:** widoczne etykiety (`<label className="text-[11px]">`), `grid-cols-1 sm:grid-cols-3`, pola `text-base sm:text-xs py-1`.

---

## P2

### P2-01. Podwójny margines stron na telefonie
- `src/components/v2/dashboard/custom/CustomDashboard.tsx:294` (`p-4 sm:p-6`), `src/components/insights/InsightsView.tsx:218` (`p-6`), `src/components/cortex/CortexView.tsx:99` (`p-6`), `src/app/dynareporter/page.tsx:122` i `profile/page.tsx:83` (`p-6`) — dodawane do `p-4 md:p-6` z `<main>`. Przy 375 treść ma 295–311 px zamiast 343 px; przy 768 traci 48 px.
- **Poprawka:** usunąć poziomy padding strony (`py-6` / `max-md:px-0`) albo `p-0 md:p-0` i zostawić padding powłoki.

### P2-02. Tabele rok do roku: bez przyklejonej kolumny „Miesiąc”, tabela daleko pod kartą
- `src/components/insights/sections/InsightsBoardYoY.tsx:460-490` — 7 kolumn (3 lata + 2 delty + Ocena) z kwotami; w poziomym przewijaniu znika kolumna miesiąca. `:166` — tabela renderuje się pod **wszystkimi** kartami; na telefonie (`grid` 1 kolumna, `:155`) stuknięcie w pierwszą kartę zmienia tabelę kilka ekranów niżej, bez przewinięcia.
- **Poprawka:** pierwsza `th`/`td` `sticky left-0 z-10 bg-card` (wiersz podsumowania `bg-muted`); tabela `min-w-[560px]`; po `onSelect` `scrollIntoView({block:"nearest"})` na tabeli poniżej `xl`, albo tabela zaraz pod wybraną kartą na telefonie.

### P2-03. „Rozbicie placementów na klientów” ściska tekst do wąskich kolumn
- `InsightsBoardYoY.tsx:571-610` — `table w-full` bez `min-w`, komórki z długimi listami klientów `text-xs`. Przy 295 px 4 kolumny po ~60 px → komórki po kilkanaście linii.
- **Poprawka:** tabela `min-w-[720px]`, `td` `min-w-[12rem]`; kolumna miesiąca `sticky left-0 bg-card`.

### P2-04. Ranking klientów (Rada): 9 kolumn bez przyklejonej nazwy
- `src/components/insights/sections/InsightsClientsRanking.tsx:145-160` — dobre `max-h + overflow-auto` i przyklejony nagłówek, ale brak `min-w` (kolumny się ściskają, nagłówki łamią) i przyklejonej kolumny „Klient”. `:258` — gwiazdka „kwota niepełna” wyjaśniona tylko w `title`.
- **Poprawka:** tabela `min-w-[900px]`, kolumna Klient `sticky left-0 bg-card`; `IncompleteMark` jako Popover/tekst przypisu.

### P2-05. Pozostałe szerokie tabele bez przyklejonej pierwszej kolumny
- `InsightsTeamTable.tsx:246` (Osoba + wiele metryk), `src/components/finance/FinanceResultsTable.tsx:130,174` (Konsultant), `CompetenceMatrix.tsx:146`, `InsightsDlPortfolio.tsx:175`.
- **Poprawka:** `sticky left-0 z-[1] bg-card` na pierwszej kolumnie (w `FinanceResultsTable` nagłówek już `sticky top-0` — dodać `left-0 z-20` na pierwszym `th`).

### P2-06. Wiersz nagłówka DL w portfelach rozciąga się na całą szerokość przewijanej tabeli
- `src/components/insights/sections/InsightsDlPortfolio.tsx:193-215` — `td colSpan` z `ml-auto` na liczbach DL; w tabeli szerszej niż ekran liczby lądują przy prawej krawędzi, poza widokiem.
- **Poprawka:** usunąć `ml-auto` poniżej `md` (`md:ml-auto`) albo owinąć zawartość w `sticky left-0 w-[calc(100vw-4rem)] md:w-auto`.

### P2-07. Wykresy roczne: nagłówek bez zawijania, dwie osie Y na ~250 px
- `src/components/insights/sections/InsightsYearlyStats.tsx:165-172, 255-262` — `flex items-center` bez `flex-wrap` z długim podsumowaniem `ml-auto`; `:176-215` wykres `h-80`, dwie osie Y i legenda przy ~250 px wnętrza (sekcja `p-6`). Wartości miesięcy tylko w tooltipie recharts (na dotyku działa stuknięcie — do sprawdzenia).
- **Poprawka:** `flex flex-wrap`, podsumowanie `basis-full sm:basis-auto`; sekcja `p-4 sm:p-6`; na telefonie `h-64`, `YAxis width={32}`, prawa oś schowana poniżej `sm`.

### P2-08. Wyjaśnienie progu wyścigu tylko w `title`
- `src/components/insights/sections/InsightsRaces.tsx:249-253` — kropkowane podkreślenie obiecuje wyjaśnienie, które na dotyku jest nieosiągalne.
- **Poprawka:** Popover po stuknięciu albo ikona ⓘ z tekstem w `<details>`.

### P2-09. Małe cele dotykowe w Insights
- `PeriodPicker.tsx:186,197` (strzałki ~28 px), `InsightsSectionNav.tsx:76` (`px-3 py-1.5 text-xs`, ~28 px), `InsightsBoardYoY.tsx:124` (`min-h-8`).
- **Poprawka:** `min-h-10` / `p-2.5` na `pointer-coarse:`.

### P2-10. Filtr dat w „Zmianach w zamówieniach” o kilka pikseli za szeroki
- `src/components/finance/OrderChangesPanel.tsx:223-244` — dwa pola `w-[150px]` + „–” w `flex` bez zawijania (~316 px) w sekcji o wnętrzu ~311 px przy 375.
- **Poprawka:** grupa `flex-wrap`, pola `w-full sm:w-[150px]` (albo `flex-1 min-w-0`).

### P2-11. Zamówienia PDF: trzy kolumny układają się w długi stos poniżej `lg`
- `src/components/finance/OrderPdfsPanel.tsx:58` — poniżej 1024 miesiąc → klient → pliki jeden pod drugim; lista miesięcy bez `max-h`, więc po wyborze klienta pliki są kilka ekranów niżej.
- **Poprawka:** listy `max-h-64 overflow-y-auto lg:max-h-none`; albo na telefonie miesiąc i klient jako `<select>`; po wyborze `scrollIntoView` kolumny plików.

### P2-12. Katalog kafelków: brak filtra kategorii na telefonie
- `src/components/v2/dashboard/custom/TileCatalogSheet.tsx:91` — nawigacja kategorii `hidden … sm:flex` bez zamiennika.
- **Poprawka:** poniżej `sm` rząd chipów `flex gap-1 overflow-x-auto sm:hidden` z tymi samymi przyciskami.

### P2-13. Uchwyty przeciągania i zmiany rozmiaru za małe na tablecie
- `TileFrame.tsx:67-76` — uchwyt to sama ikona `h-4 w-4` (16 px); `DashboardGrid.tsx:105` — domyślny uchwyt „se” react-resizable (~20 px). Przy 1024 (iPad poziomo) siatka jest w trybie pulpitu i edycji.
- **Poprawka:** uchwyt `p-2 -m-2 touch-none` (min. 32–40 px), w `globals.css` pod `@media (pointer: coarse)` powiększyć `.react-resizable-handle` do 28–32 px.

### P2-14. Lejek w kafelku metryki: stała kolumna wartości 40 px
- `src/components/v2/dashboard/custom/MetricTileBody.tsx:147` — `grid-cols-[8rem_1fr_2.5rem]`; liczby 4–5-cyfrowe („1 234”) przekraczają 40 px, a w kafelku w=4 przy 1024 (~244 px wnętrza) pasek ma ~70 px.
- **Poprawka:** `grid-cols-[minmax(0,8rem)_1fr_auto]`, etykieta `min-w-0 truncate`.

### P2-15. Cortex → wyszukiwarka technologii: pole wystaje z karty przy 375
- `src/components/cortex/SkillSearchPanel.tsx:103-104` — `min-w-[16rem]` w karcie `p-6` (wnętrze ~247 px przy podwójnym marginesie).
- **Poprawka:** `min-w-0 basis-full sm:basis-auto sm:min-w-[16rem]`, karta `p-4 sm:p-6`.

### P2-16. Nagrody pod podium Ligi ciasne na telefonie
- `src/components/insights/sections/ChampionsSection.tsx:421-436` — `grid-cols-3` z kwotą `text-sm` w komórkach ~64 px wnętrza; „10 000 zł” (twarda spacja) na granicy przepełnienia.
- **Poprawka:** `text-xs sm:text-sm tabular-nums`, komórka `min-w-0` + `truncate`.

### P2-17. Tekst poniżej 11 px
- `InsightsBoardKPI.tsx:398` (9 px, patrz P1-11), `src/components/v2/dashboard/StatsBoundary.tsx:75` (10 px), `src/app/dynareporter/page.tsx:195,200` (10 px), nagłówki tabel DynaReportera `text-[10px]`: `admin-dashboard/page.tsx:253-268, 325-337`, `_modules/EmployeesManager.tsx:276-294`, `_modules/DataHistoryView.tsx:138-208`, `_modules/MasterDataManager.tsx:564+`; `_modules/ScoringConfig.tsx:253`.
- **Poprawka:** minimum `text-[11px]` (jak reszta repo), nagłówki tabel `text-xs`.

### P2-18. Powiększanie strony w iOS przy polach formularzy (systemowe)
- Bazowy `src/components/ui/input.tsx:19` ma `text-sm` (14 px); brak `viewport` w `src/app/layout.tsx`. W zakresie: `FinanceResultsTab.tsx:181,192`, `MdImportWorkspace.tsx:239-251,647`, `FinanceImportPanel.tsx:160,193`, `OrderChangesPanel.tsx:180,227,237`, `TileSettingsDialog.tsx`/`MetricBuilderForm.tsx` (pola `Input`), `EditableCell.tsx:72`.
- **Poprawka (globalnie, jedna zmiana):** w `input.tsx` i odpowiednikach select/textarea `text-base md:text-sm`.

### P2-19. DynaReporter → Konfiguracja punktacji: 3 pola nagród w jednym rzędzie
- `src/app/dynareporter/admin-dashboard/_modules/ScoringConfig.tsx:138` — `grid-cols-3` bez breakpointu; przy 375 pola ~95 px, etykiety „🥇 1. miejsce (PLN)” łamią się w 2–3 linie.
- **Poprawka:** `grid-cols-1 sm:grid-cols-3`.

---

## Co jest zrobione dobrze

- **Siatka pulpitu ma tryb listy** (`DashboardGrid.tsx:32-58`): kolejność czytania wiersz→kolumna, małe liczby po dwie w rzędzie, stała wysokość tylko dla wykresu i lejka (recharts potrzebuje wymiaru), reszta rośnie z treścią. Edycja układu świadomie wyłączona na telefonie.
- **Wykresy przez `ResponsiveContainer`** wszędzie w zakresie (`MetricTileBody.tsx:167`, `InsightsYearlyStats.tsx:178,266`, `InsightsPlacementAnalysis.tsx:234`) — brak stałych szerokości w pikselach.
- **Analiza placementów** ma legendę jako listę z wartościami i procentami (`InsightsPlacementAnalysis.tsx:263-290`) — dane dostępne bez hovera.
- **Karty rok do roku** rysują wykresiki jako SVG z `viewBox` i `w-full`; tabele przewijają się **wewnątrz** karty (`InsightsBoardYoY.tsx:458-460`), z komentarzem dlaczego.
- **Zmiany w zamówieniach** (`OrderChangesPanel.tsx:167-179`): podzakładki na `TabbedNav overflow="scroll"`, poniżej `xl` w osobnym wierszu (zmierzony problem „Braki za przewijaniem”); wiersze to lista kart, nie szeroka tabela; `min-w-0 + truncate`.
- **Zamówienia PDF**: wiersz pliku `flex-col sm:flex-row` i `break-all` na długich nazwach (`OrderPdfsPanel.tsx:145-170`).
- **Szerokie tabele z `overflow-x-auto`**: `StageBreakdownSection.tsx:100-101` (z `min-w-[560px]` — wzorzec do powielenia), `InsightsTeamTable`, `InsightsSeniority`, `InsightsTimeToHire`, `InsightsTeamActivity`, `InsightsDlPortfolio`, `CompetenceMatrix`, `FinanceArchiveTab`, `MdImportWorkspace`, tabele DynaReportera.
- **Przyklejone nagłówki** w tabelach przewijanych w pionie: `InsightsClientsRanking.tsx:147`, `FinanceResultsTable.tsx:132`; **przyklejona pierwsza kolumna** w mapie ciepła Cortexu (`TechMapHeatmap.tsx:59,85`).
- **Zakładki Cortexu** z `overflow-x-auto` + `whitespace-nowrap` (`CortexView.tsx:109-117`).
- **Pasek sekcji Insights** (`InsightsSectionNav.tsx:64`) zawija się (`flex-wrap`) zamiast przyklejać i wystawać; kotwice mają `scroll-mt-20`.
- **Listy rankingów** (Hall of Fame, Wyścigi, Liga, `ds/Leaderboard`) konsekwentnie używają `min-w-0` + `truncate` na nazwiskach i `shrink-0` na liczbach.
- **Wybór rozmiaru szuflad** (`SheetContent size="lg"/"xl"`) — na telefonie pełna szerokość, `sm:max-w-*` powyżej.

## Uwagi poza zakresem / niepotwierdzone

- `src/app/dashboard/{recruiter,head-of-recruitment,delivery-lead}/page.tsx` i `src/app/manager/page.tsx` to wyłącznie przekierowania na `/dashboard` — brak UI do audytu. Komponenty w `src/app/dashboard/delivery-lead/_components/` są importowane tylko przez `src/lib/job-pipeline-funnel.ts` (typy/logika); nie są renderowane na żadnym ekranie — nie audytowane.
- Zachowanie `dblclick` na iOS/Android (P1-13) i tooltipów recharts po stuknięciu (P2-07) wymaga sprawdzenia na urządzeniu.
- Obliczenia szerokości zakładają zwinięty pasek boczny (60 px); przy przypiętym (240 px) wszystkie progi przesuwają się o 180 px w górę (np. P1-01 obejmuje wtedy okna do ~1104 px).
