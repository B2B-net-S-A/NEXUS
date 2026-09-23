# Audyt responsywności — Rekrutacje, Tablica (pipeline), Champion, prep, feedback, sourcing/targ

Zakres: `src/app/jobs/**`, `src/components/v2/jobs/**`, `src/components/v2/recruitment/**`,
`src/components/v2/pages/KanbanBoardV2.tsx` + `JobsListV2.tsx` + `JobChatTab.tsx`,
`src/components/Champion*.tsx`, `EditJobModal` (`src/components/AppShell.tsx`),
`src/components/prep/**`, `src/components/feedback/**`, `src/app/sourcing/**`,
`src/app/marketplace/**`, `src/components/marketplace/**`, `src/components/sourcing/**`,
`BoardTasksPanel`/`DlReviewPanel`.

Metoda: statyczny przegląd kodu (bez uruchamiania). Breakpointy domyślne Tailwind v4
(`globals.css` `@theme inline` nie nadpisuje `--breakpoint-*`): sm 640 · md 768 · lg 1024 · xl 1280 · 2xl 1536.

Kontekst powłoki, który wpływa na liczenie szerokości (`AppShellV2.tsx:185-208`):
sidebar widoczny od `md` (60 px zwinięty / 240 px przypięty), `<main>` ma `p-4 md:p-6`
i jest jedynym pionowym kontenerem przewijania; topbar `h-12`. Przy 375 px zostaje
343 px treści; przy 768 px — ok. 660 px (sidebar zwinięty) albo 480 px (przypięty).

Podsumowanie: **P0: 1 · P1: 6 · P2: 23** (+3 uwagi „niepotwierdzone”).

---

## P0 — nieużywalne na telefonie

### P0-1. „Do przejrzenia” → Propozycje z bazy: panel osoby ma sztywne 372 px obok tabeli
- **Plik:** `src/components/v2/recruitment/ProposalsSegment.tsx:416-455` (kontener
  `flex min-w-0 items-start gap-4`), `src/components/v2/recruitment/ProposalPanel.tsx:116` i `:131`
  (`w-[372px] shrink-0`).
- **Ekran:** `/jobs/{id}?tab=people&seg=proposals` (pełny ekran „Do przejrzenia”).
- **Co się psuje:** panel jest zawsze w tym samym wierszu co tabela (`showPanel` domyślnie `true`)
  i nie może się skurczyć. Przy 375 px (343 px treści) panel 372 px sam jest szerszy niż ekran —
  strona dostaje poziomy scroll, a `PeopleTable` (flex-1 min-w-0) dostaje 0 px. Tabela to
  `VirtualTable` z kolumnami ~124+92+116+70+… px, więc i tak nie ma jak się pokazać.
  Przy 768 px (660 px treści) tabela ma ~270 px na grid, który potrzebuje ~550 px → przewijanie
  poziome w wąskim pasku (P1 na tablecie).
- **Naprawa:** `flex flex-col lg:flex-row lg:items-start` na kontenerze, panel
  `w-full lg:w-[372px] lg:shrink-0`; lepiej: poniżej `lg` panel w `Sheet side="right"`
  (jak `PersonPanel` — `PersonPanel.tsx:889` ma już `w-full lg:w-[372px]`) otwierany kliknięciem wiersza.

---

## P1 — rozjechany układ / ukryta treść

### P1-1. Tablica na telefonie: plansza ma 280 px wysokości i własny pionowy scroll
- **Plik:** `src/components/v2/pages/KanbanBoardV2.tsx:1366-1368` (`BOARD_BOTTOM_GAP = 40`,
  `MIN_COLUMN_HEIGHT = 280`), `:1571-1578` (`innerHeight - top - 40`), `:2549-2553`.
- **Co się psuje:** wysokość planszy = wysokość okna minus pozycja planszy. Na telefonie nad planszą
  stoją: nagłówek rekrutacji (EntityHeader łamie się na kolumnę, wiersz „Zlecenie / Historia i czat /
  Podobne / Champion” to 2–3 linie przycisków), `PipelineFilterBar` (2–3 linie), nawigator etapów,
  pasek zamkniętych. Planszę łatwo zaczyna się ~600 px od góry, więc przy 812 px dostaje podłogę
  280 px — widać ~2 karty, a przewijanie jest zagnieżdżone (strona + plansza). Pomiar jest robiony
  względem aktualnej pozycji, więc po przewinięciu strony w dół plansza NIE rośnie.
- **Naprawa:** poniżej `md` liczyć wysokość bez offsetu nagłówka:
  `height = innerHeight - 48 (topbar) - 16` i pozwolić stronie zjechać nad planszę
  (użytkownik przewija nagłówek raz, potem ma planszę na cały ekran); w CSS fallback
  `h-[calc(100dvh-4rem)] md:h-[calc(100vh-240px)]`. Alternatywnie `sticky top-0` dla planszy na mobile.

### P1-2. Dok „Karta kandydata” na tablecie (768–1279 px) zasłania prawe kolumny planszy
- **Plik:** `KanbanBoardV2.tsx:2653` (`fixed right-0 top-12 bottom-0 z-30 w-full max-w-[380px]`,
  bez tła), `:2365` (`xl:pr-[380px]` — rezerwa miejsca tylko od `xl`).
- **Co się psuje:** na md/lg dok nakrywa 380 px planszy, a plansza nie ma prawego paddingu.
  Ostatnia kolumna po przewinięciu do końca stoi dokładnie pod dokiem — jest nieosiągalna,
  dopóki dok jest otwarty (np. „Zatrudniony”/„Umowa” przy pracy z kartą).
- **Naprawa:** `lg:pr-[380px]` zamiast `xl:pr-[380px]` (przy lg plansza i tak przewija się w poziomie),
  a poniżej `lg` dok jako modalny `Sheet` z tłem (na 375 px dok i tak jest `w-full`).

### P1-3. Lista `/jobs`: „Podgląd” poniżej `xl` otwiera dok na samym dole strony
- **Plik:** `src/components/v2/pages/JobsListV2.tsx:153-168` (`LAYOUT_GRID` — kolumna doku tylko
  `xl:`), `:1918-1945` (aside doku jako ostatni element siatki), `:660-687` (ikona Eye).
- **Co się psuje:** na telefonie i tablecie siatka jest jednokolumnowa (lub `lg:col-span-2`),
  więc dok renderuje się POD całą listą (20 wierszy + paginacja). Klik „Podgląd” nie daje
  widocznego efektu — wygląda na zepsuty przycisk. Brak `scrollIntoView`.
- **Naprawa:** poniżej `xl` renderować `JobReadinessDock` w `Sheet side="right"`
  (`className="sm:max-w-[420px]"`); ewentualnie minimum: `ref.scrollIntoView({block:"start"})`
  po otwarciu, gdy `!matchMedia('(min-width:1280px)').matches`.

### P1-4. Feedback po interview: trzy pola ocen 1–5 nachodzą na siebie (także na desktopie)
- **Plik:** `src/components/feedback/InterviewFeedbackModal.tsx:453` (`grid grid-cols-3 gap-2`),
  `:569-576` (`RatingField`: 5 × `w-10 h-10` + `gap-1` = 216 px, bez zawijania).
- **Co się psuje:** dialog `size="lg"` = `max-w-2xl` (672) − `px-6` = 624 px → kolumna 202 px < 216 px:
  piąty przycisk wchodzi na następną kolumnę nawet na desktopie. Na 375 px kolumna ma ~100 px,
  więc rzędy przycisków nakładają się na siebie i część jest nieklikalna.
- **Naprawa:** `grid grid-cols-1 gap-3 sm:grid-cols-3` + w `RatingField`
  `flex flex-wrap gap-1` i przyciski `size-9 sm:size-8` albo `grid grid-cols-5 gap-1` z `aspect-square w-full`.

### P1-5. Targ kandydatów: tabela 8 kolumn ucięta (`overflow-hidden`)
- **Plik:** `src/components/marketplace/MarketplaceTable.tsx:149-150`.
- **Ekran:** `/sourcing/marketplace?tab=manual` (i `/marketplace` → redirect).
- **Co się psuje:** wrapper `rounded-2xl overflow-hidden` nie przewija — na 375–768 px kolumny
  „Na targu”, „Ważne do” i przycisk „zdejmij z targu” (X) są przycięte i niedostępne.
- **Naprawa:** `overflow-x-auto` na wrapperze (zostawić `rounded-2xl`), `min-w-[720px]` na `<table>`;
  albo ukryć mniej ważne kolumny: `hidden md:table-cell` dla „Kategoria”, „Owner”.

### P1-6. Czat rekrutacji: „Odpowiedz” i „Reakcja” widoczne tylko po najechaniu
- **Plik:** `src/components/v2/pages/JobChatTab.tsx:720` (`opacity-0 group-hover:opacity-100`).
- **Ekran:** okno „Historia i czat” → Czat.
- **Co się psuje:** na dotyku nie ma hover — akcji nie widać (są klikalne, ale niewidoczne);
  brak też `focus-within`, więc z klawiatury również nie wyskakują.
- **Naprawa:** `opacity-100 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100 focus-within:opacity-100`
  (albo wariant `pointer-coarse:opacity-100`).

---

## P2 — kosmetyka / ergonomia

### Formularze i iOS
1. **iOS zoom przy fokusie (systemowo).** `src/components/ui/input.tsx:19` i `textarea.tsx:16`
   mają `text-sm` (14 px) → Safari na iPhonie powiększa stronę przy każdym polu (formularz `/jobs/new`,
   edytor Championa, ChampionIntake, EditJobModal). W zakresie dodatkowo mniejsze:
   `PipelineFiltersRail.tsx:146` (`text-xs`, „Filtruj po nazwisku”), `PersonPanel.tsx:765`
   (select etapu `text-[13px]`), `ChampionIntake.tsx:209-212` (textarea `text-sm`),
   `NewJobPage.tsx:482` (select „Prowadzi”). **Naprawa:** w prymitywach `text-base sm:text-sm`;
   w polach ręcznych to samo.
2. **`/jobs/new` — podwójne marginesy.** `NewJobPage.tsx:341` dokłada `px-4 pt-6 md:px-8` do `<main p-4 md:p-6>`,
   a sekcje mają `p-6` (`NewJobRequestStep.tsx:58`, `NewJobReviewForm.tsx:232`) → na 375 px pole
   formularza ma ~263 px. **Naprawa:** `px-0 pt-0 md:px-2`, sekcje `p-4 sm:p-6`.
3. **`/jobs/new` krok 2 — mail klienta zajmuje 70vh nad formularzem** poniżej `xl`
   (`NewJobPage.tsx:385`, `max-h-[70vh]`). **Naprawa:** `max-h-[35vh] xl:max-h-[70vh]` albo `<details>` zwinięte na mobile.
4. **`NewJobReviewForm.tsx:263` `md:grid-cols-4`** — przy 768–1023 px cztery kolumny po ~125 px
   (Budżet / Tryb pracy ×2 / Dni w biurze); przycisk „Stacjonarnie” w `h-9` przy 375 px ~85 px szerokości
   (`:288-309`, stała wysokość, tekst może wyjść poza pigułkę). **Naprawa:** `md:grid-cols-2 lg:grid-cols-4`,
   pigułki `min-h-9 h-auto px-2 leading-tight`.
5. **`/jobs/new` stopka przyklejona dopiero od `md`** (`NewJobPage.tsx:440`, `md:sticky`) — na telefonie
   „Utwórz i przekaż do searchu” jest na końcu długiego formularza. Świadome? Jeśli nie:
   `sticky bottom-0` także na mobile, z `[@media(max-height:600px)]:static`.
6. **EditJobModal — siatki bez breakpointu** (`src/components/AppShell.tsx:1312` `grid-cols-2`,
   `:1330` `grid-cols-3` — „Miasto biura / Tryb pracy (remote policy) / …”). Na 375 px trzy pola po ~100 px
   z długimi etykietami. **Naprawa:** `grid-cols-1 sm:grid-cols-3`, `grid-cols-1 sm:grid-cols-2`.
7. **AIJobWriterModal** (`src/components/v2/jobs/AIJobWriterModal.tsx:82`) — `grid-cols-2` bez breakpointu,
   własny overlay. **Naprawa:** `grid-cols-1 sm:grid-cols-2`.
8. **QuestionBankTab** (`src/components/prep/QuestionBankTab.tsx:368`) — `grid-cols-2` selectów w dialogu;
   na 375 px ~140 px na select. **Naprawa:** `grid-cols-1 sm:grid-cols-2`.

### Tablica / karty / doki
9. **Kosz na karcie niewidoczny na dotyku, ale klikalny** — `KanbanBoardV2.tsx:1084`
   (`opacity-0 group-hover:opacity-100`, pozycja `top-1 right-1`). Tapnięcie w róg karty otwiera
   potwierdzenie usunięcia zamiast doku, a sama akcja jest nieodkrywalna. Potwierdzenie istnieje
   (`:1882` → `setPendingRemoval`), dlatego P2. **Naprawa:** `[@media(hover:none)]:opacity-100`
   albo przeniesienie „Usuń z rekrutacji” do menu w doku na dotyku.
10. **Brak scroll-snap planszy na mobile** — `KanbanBoardV2.tsx:2549` (`flex gap-3 overflow-auto`).
    Kolumna 17 rem przy 343 px ekranu = jedna kolumna + skrawek następnej. **Naprawa:**
    `snap-x snap-mandatory xl:pointer-fine:snap-none` na planszy, `snap-start` na kolumnie
    (`:1222`). Sprawdzić z auto-scrollem DnD (snap może walczyć z auto-scrollem przy przeciąganiu —
    wtedy `snap-proximity`).
11. **Cele dotyku < 40 px:** checkbox karty 24 px (`KanbanBoardV2.tsx:830-843`), pigułka
    „Screening” `text-[9px] py-0.5` (`:1109`), pigułki filtrów tablicy `py-0.5 text-[11px]`
    (`PipelineFiltersRail.tsx:51`, `:146` `h-7`), „Biorę / Pomiń” w „Do przejrzenia” na Tablicy
    (`BoardReviewSection.tsx:156,165`, ~22 px), strzałki poprzednia/następna w doku
    (`PipelineCandidateDock.tsx:613,625`, `p-0.5` + ikona 14 px; `JobReadinessDock.tsx:900`),
    ikony w wierszu listy „Link zaproszenia” / „Podgląd” (`JobsListV2.tsx:660,678`, `p-1` + 14 px),
    zamknięcie doku (`PipelineCandidateDock.tsx:639`, 24 px). **Naprawa:** na dotyku
    `pointer-coarse:size-10`/`pointer-coarse:min-h-10` albo stałe `size-8` + `before:` z większym polem.
12. **Dok karty przy trybie „podglądaj jako”** — `KanbanBoardV2.tsx:2653` `top-12` zakłada, że topbar
    jest pierwszy; `ImpersonationBanner` stoi nad topbarem (`AppShellV2.tsx:197`), więc dok zachodzi
    na topbar. **Naprawa:** zmienna CSS wysokości chrome (`top-[var(--app-chrome-h,3rem)]`).
13. **PersonPanel — wiersz etapu nie zawija się** (`src/components/v2/recruitment/PersonPanel.tsx:754-802`):
    „Etap” + select + „Odrzuć…” + „Zrezygnował…” w jednej linii; na 375 px select ma ~100 px i nazwy
    etapów są ucięte. **Naprawa:** `flex flex-wrap`, select `basis-full sm:basis-auto sm:flex-1`.
14. **DlReviewPanel — stopka arkusza nie przewija się** (`src/components/v2/recruitment/DlReviewPanel.tsx:501-625`):
    ostrzeżenie + formularz odrzucenia (2 selecty + textarea) + wiersz stawki; na telefonie w poziomie
    (≈375 px wysokości) przyciski „Wyślij”/„Odrzuć” mogą wyjść poza ekran. **Naprawa:**
    `SheetFooter` z `max-h-[50dvh] overflow-y-auto` albo formularz odrzucenia przenieść do `SheetBody`.
15. **Czat w arkuszu ma `h-[70vh]`** (`JobChatTab.tsx:350,365,385`) wewnątrz `SheetBody` z własnym
    przewijaniem → podwójny scroll i zła wysokość przy klawiaturze iOS. **Naprawa:**
    `h-full min-h-0` i flex-col w `SheetBody`, lub `h-[70dvh]`.
16. **Nagłówek rekrutacji na telefonie ucina tytuł** (`JobDetailCompactHeader.tsx:250-256`, `truncate`);
    pełna nazwa tylko w `title` — niedostępna na dotyku. **Naprawa:** `line-clamp-2 sm:truncate`
    na tytule, klient `hidden sm:inline` albo w drugiej linii.
17. **Mikro-typografia KPI w nagłówku** `text-[9.5px]` (`JobDetailCompactHeader.tsx:169`) — na telefonie
    nieczytelne. **Naprawa:** `text-[10px] sm:text-[9.5px]` lub ukrycie etykiet pod `sm`.

### Lista `/jobs`
18. **Tabela 7 kolumn na telefonie** (`JobsListV2.tsx:503-518`: 150+200+210+104+120+64 px + tytuł ≈ 850+ px)
    — działa przez poziomy scroll wrappera `Table` (`ui/table.tsx:27`), ale na 375 px widać tytuł
    i pół statusu. Widok kafelków (`md:grid-cols-2`, `:1679`) jest gotowy do telefonu, a domyślny jest
    zapamiętany `jobsView` (`:786`). **Naprawa:** poniżej `md` wymuszać kafelki
    (`const effectiveView = isNarrow ? "tiles" : jobsView`) albo ukryć kolumny
    `hidden lg:table-cell` dla „Podobne rekrutacje”, „Prowadzi”.
19. **Filtry rozwinięte jawnie + otwarty dok przy `xl`** (`JobsListV2.tsx:156`:
    `xl:grid-cols-[230px_minmax(0,1fr)_360px]`) — przy 1280 px i przypiętym sidebarze tabela dostaje
    ~370 px. Tryb `auto` to rozwiązuje (chowa filtry), `expanded` nie. **Naprawa:** trzy kolumny
    dopiero od `2xl`, na `xl` filtry nad listą albo dok zamiast filtrów.

### Champion / rekrutacja
20. **Edytor Championa poniżej `xl`: „Zapisz” tylko na górze, dok (bramka handoffu) pod całym edytorem**
    (`src/app/jobs/[id]/page.tsx:1098-1135`, `ChampionProfileEditor.tsx:343-377`). Na telefonie/tablecie
    po edycji sekcji 6 trzeba przewinąć cały formularz w górę. **Naprawa:** przycisk zapisu w
    `sticky bottom-0` (lub `sticky top-0` nagłówek edytora) poniżej `xl`.
21. **Porównanie propozycji AI: pionowa kreska w układzie jednokolumnowym**
    (`ChampionProfileSuggestionReview.tsx:412`, `divide-x` przy `grid-cols-1`). **Naprawa:**
    `divide-y md:divide-y-0 md:divide-x`.
22. **Prep kit** (`src/app/jobs/[id]/prep/[candidateId]/page.tsx:113-139`): `p-6` na `<main p-4>`
    + nagłówek `flex justify-between` bez zawijania — na 375 px h1 „Prep kit · Job #… · Kandydat #…”
    dostaje ~90 px obok przycisków „Drukuj”/„← Projekt”. **Naprawa:** `p-0 md:p-6`,
    `flex flex-col gap-3 sm:flex-row sm:items-start`.

### Sourcing / targ / okna
23. **`/sourcing/marketplace` — zagnieżdżony `<main className="container mx-auto p-4">`**
    (`src/app/sourcing/marketplace/page.tsx:38`) w `<main>` powłoki: podwójny padding na mobile
    i drugi landmark `main`. **Naprawa:** `<div className="mx-auto max-w-7xl">`.
    Dodatkowo `ContractorMatchCard.tsx:242-270` — pigułka ostrzeżenia w wierszu bez zawijania
    ściska tytuł rekrutacji na 375 px (`flex-wrap` albo pigułka pod tytułem).
    `PostingsSection.tsx:93-98` (okno publikacji ogłoszenia) — brak `max-h`/`overflow-y-auto`:
    na telefonie w poziomie lista portali wychodzi poza ekran (`max-h-[90dvh] overflow-y-auto`).

### Uwaga przekrojowa (poza plikami zakresu, ale dotyka wszystkich okien z zakresu)
- `src/components/ui/dialog.tsx:59` — `DialogContent` ma `w-full` bez marginesu: na telefonie każde
  okno (SimilarJobsDialog, InterviewFeedbackModal, QuestionBank, ChampionIntake, JobCloseWithReason,
  CproAssignee) dotyka krawędzi ekranu, a `rounded-xl`/`border` wyglądają na ucięte.
  **Naprawa:** `w-[calc(100%-2rem)] sm:w-full` (albo bottom-sheet jak `Modal` w `AppShell.tsx:199`).

---

## Niepotwierdzone (do sprawdzenia w przeglądarce)
- `JobsListV2.tsx:558` — `max-w-[320px]` na `<td>`: Chrome/Firefox ignorują `max-width` komórek tabeli
  w układzie `auto`, a `block truncate` nie zmniejsza min-content. Długie tytuły mogą rozpychać kolumnę
  „Rekrutacja” i wymuszać poziomy scroll nawet przy 1280 px. Sprawdzić na rekrutacji Nordei z długim
  tytułem; naprawa: `table-fixed` + `w-[…]` kolumn albo `<div className="max-w-[320px]">` w komórce.
- Przeciąganie kart na dotyku: `@hello-pangea/dnd` ma sensor dotyku (long-press), a cała karta jest
  uchwytem (`KanbanBoardV2.tsx:1311-1314`), więc przesunięcie palcem przewija planszę, a przytrzymanie
  zaczyna drag. Nie zweryfikowałem na urządzeniu, czy przy planszy 280 px (P1-1) auto-scroll w pionie
  działa poprawnie w zagnieżdżonym scrollu.
- `ChampionIntake.tsx:196` — `max-h-[90vh] overflow-y-auto` łączy się z `overflow-hidden` z prymitywu;
  kolejność reguł w CSS Tailwind v4 powinna dać przewijanie, ale warto potwierdzić na iOS.

---

## Co jest zrobione dobrze
- **Tablica:** nawigator etapów dla wąskich ekranów (`StageFocusNavigator`, `KanbanBoardV2.tsx:282-373`:
  select „etap N z M” + strzałki), gęsty widok przeglądowy tylko przy `xl:pointer-fine` (dotykowe
  tablety/laptopy dostają przewijane kolumny zamiast kafelków 10 px), jedna plansza jako jedyny
  kontener scrolla (poprawny DnD po auto-scrollu), kolumny z podłogą `min-w-[17rem] sm:min-w-[19rem]`,
  mierzona wysokość planszy zamiast magicznej liczby.
- **Nagłówek rekrutacji:** `flex-wrap` zamiast `overflow-x-auto` dla paska przycisków
  (`JobDetailCompactHeader.tsx:365`), `EntityHeader` przechodzi na kolumnę pod `sm`, klient ucina się
  przed tytułem (`shrink-[4]`).
- **Lista `/jobs`:** baza `grid-cols-1`, pasek narzędzi `flex-wrap`, wyszukiwarka `min-w-[240px] flex-1`,
  tabela w wrapperze `overflow-auto`, kafelki `md:grid-cols-2`, zwijana kolumna filtrów liczona CSS-em
  (bez migotania).
- **Panele i okna:** arkusze `Sheet` są `w-full` na telefonie (`ui/sheet.tsx:33`), `RecruitmentSheet`
  ogranicza szerokość dopiero od `sm`, `PersonPanel` `w-full lg:w-[372px]`, warsztaty (screening, CV,
  rozmowy, umowa) mają osobny układ `layout="panel"` zamiast 3-kolumnowej siatki; `EditJobModal`
  (`Modal` w `AppShell.tsx:199`) to bottom-sheet na telefonie; `JobReadinessDock` ma
  `xl:max-h-[calc(100vh-2rem)] overflow-y-auto` (sticky wyższy od okna nie chowa akcji).
- **Champion:** siatki pól `sm:grid-cols-2/3`, spis sekcji dopiero od `2xl`, zwijany dok tylko od `xl`,
  pod `xl` dok pełnej szerokości z bramką handoffu.
- **Inne:** `BoardTasksPanel` `lg:grid-cols-3` z `min-w-0`/`truncate`; `JobShortlist` `sm:flex-row`;
  `NewJobPage` `xl:grid-cols-[…]`, stopka `flex-wrap`; prep kit z pełnymi stylami druku.
