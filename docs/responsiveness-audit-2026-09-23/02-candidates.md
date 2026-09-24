# Audyt responsywności — obszar „Kandydaci”

Zakres: lista `/candidates` (pasek filtrów, tabela, pasek zaznaczenia, podgląd), profil `/candidates/[id]` (4 zakładki, pasek faktów), wyszukiwarka z rekrutacji (`?mode=search&job=`), „Z requestu” / Talent Radar, porównanie, masowy import CV, kolejka kontaktu, maile, rozmowy, podgląd CV (PDF/DOCX).
Metoda: statyczny przegląd kodu (bez uruchamiania). Szerokości: 375 (telefon), 768 (tablet), 1280 (mały laptop), 1920.
Breakpointy Tailwind domyślne (`globals.css` `@theme` ich nie nadpisuje).

## Kontekst, który zmienia wszystkie liczby

- Pasek boczny jest **domyślnie przypięty** (`useSidebarPinned.ts:18` → `useState(true)`, `SidebarV2.tsx:404` `w-60`). Od `md` zajmuje 240 px, a `main` ma `p-6` (`AppShellV2.tsx:208`).
  Szerokość treści: **768 → 480 px**, **1024 → 736 px**, **1280 → 992 px**, **1920 → 1632 px**.
- Na `/candidates` i `/candidates/<id>` od `lg` stoi dodatkowo szyna ostatnich kandydatów `w-60` + `gap-6` (`app/candidates/layout.tsx:31`), gdy są otwarte karty.
  Wtedy: **1024 → 472 px**, **1280 → 728 px**.
- Wszystkie układy stron są liczone po szerokości OKNA (`md:`, `xl:`), a nie po szerokości kontenera — stąd większość defektów „na laptopie”.

## Podsumowanie

| Waga | Liczba |
|---|---|
| P0 (nie da się użyć na telefonie/tablecie) | 1 |
| P1 (rozjechany układ, ucięta albo niedostępna treść) | 13 |
| P2 (kosmetyka, ergonomia, dotyk) | 11 |

---

## P0

### P0-1. Zakładka „Pliki i umowy”: przyciski „Podgląd” i „Pobierz” ucięte na telefonie
- **Plik:** `src/components/v2/files/CandidateFilesTab.tsx:253-352` (wiersz dokumentu), obcinanie przez `src/components/v2/pages/CandidateDetailV2.tsx:619` (`Card … overflow-hidden`).
- **Co się dzieje:** wiersz to `flex items-center gap-3`, a grupa akcji ma `shrink-0` i zawiera select rodzaju (~110 px), „Ustaw jako główne CV” (~140 px), „Podgląd” (~75 px) i „Pobierz” (~70 px) = do ~430 px. Na 375 px wiersz ma ok. 285 px (main `p-4`, karta `p-4`, wiersz `p-3`). Nazwa pliku (`flex-1 min-w-0`) spada do zera, a akcje wychodzą poza kartę, która ma `overflow-hidden` — **„Podgląd” i „Pobierz” są niewidoczne i nieklikalne**. Nawet bez „Ustaw jako główne CV” (279 px + ikona) wiersz się nie mieści. Główne CV da się otworzyć z karty „CV kandydata” na zakładce Profil, ale certyfikatów, listów i pozostałych plików — nie.
- **Szerokości:** 375 zepsute; 768 (480 px treści) na granicy przy dokumencie CV z opcją „Ustaw jako główne”; od 1024 OK.
- **Poprawka:**
  ```
  wiersz:   flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3
  akcje:    flex flex-wrap items-center gap-x-3 gap-y-2 sm:shrink-0
  select:   min-h-10 sm:min-h-0
  ```
  alternatywnie na `<sm` schować select i „Ustaw jako główne” w menu „⋯” (`DropdownMenu`).

---

## P1

### P1-1. Tabela kandydatów: wiersze ucinają ostatnie kolumny („Przypisz”, część „CV”), nagłówek nie
- **Pliki:** `src/lib/candidate-table-columns.ts:83-86`, `src/components/v2/pages/CandidatesListV2.tsx:1614`, `:1638-1640`, `:1705`, `:1712-1714`.
- **Przyczyna:** `candidateGridLayout().minWidth` = 32 + Σ `minWidth` kolumn (domyślnie 910 px), **bez odstępów `gap-3` (8 × 12 = 96 px) i paddingu `px-4` (32 px)**. Siatka realnie potrzebuje ~1038 px. Nagłówek przelewa się w kontenerze `overflow-x-auto` (widać go po przewinięciu), ale kontener wierszy ma `overflow-x-hidden` (`:1640`), a sam wiersz `overflow-hidden` (`:1705`) — **ostatnie ~128 px wiersza jest ucięte**.
- **Szerokości:** 375/768/1024 — kolumna „Przypisz” niewidoczna w wierszach, a pasek przewijania sugeruje, że jest; **1280 z domyślnie przypiętym paskiem (992 px)** — przycisk „Przypisz” ucięty o ~16 px, CV ścieśnione; 1280 + szyna (728 px) — „Przypisz” całkiem zniknął; 1920 OK.
- **Poprawka (1 linia):** w `candidateGridLayout` liczyć `minWidth: 32 + Σmin + 12 * columns.length + 32`. Dodatkowo na kontenerze wierszy zamienić `overflow-x-hidden` na `overflow-x-visible` (albo dać wierszom `min-w-full w-max`), żeby przyszła rozbieżność nie cięła po cichu.

### P1-2. Lista kandydatów na telefonie: podwójne przewijanie i brak widoku kart
- **Plik:** `src/components/v2/pages/CandidatesListV2.tsx:1606`, `:1633-1640`.
- **Co się dzieje:** tabela ma własny obszar przewijania `height: calc(100vh - 300px)`, `minHeight: 360`, osadzony w `main overflow-y-auto`. Na 375×812 nad tabelą stoi tytuł, wyszukiwarka, przycisk słów kluczowych, rząd filtrów, licznik z chipami, zapisane wyszukiwania, sort, „Kolumny” — razem wyraźnie ponad 300 px, więc strona przewija się i tabela przewija się osobno (pułapka przewijania na dotyk). `100vh` na iOS to „duży” viewport — dolna część listy chowa się pod paskiem Safari. Do tego poziome przewijanie 1038 px bez przyklejonej kolumny „Kandydat” — po przesunięciu w prawo nie wiadomo, czyj to telefon/stawka.
- **Poprawka:** poniżej `md` renderować listę kart (nazwisko + stanowisko, telefon, stawka, dostępność, „W procesie”, przycisk „Przypisz”) bez wirtualizacji w osobnym kontenerze albo z wirtualizacją po oknie (`useWindowVirtualizer`); jeśli tabela zostaje: `h-[calc(100dvh-300px)]` → na `<md` `h-auto` + przewijanie strony, oraz kolumna „Kandydat” `sticky left-0 z-[1] bg-card` (w nagłówku i wierszach).

### P1-3. Stopka paginacji nie zawija się i ucieka poza ekran
- **Plik:** `src/components/v2/pages/CandidatesListV2.tsx:1902-1945`.
- **Co się dzieje:** `flex h-12 items-center justify-between` bez `flex-wrap`, a zawartość to licznik (~110 px) + select `w-[152px]` + „Poprzednia” + „Następna” ≈ 470 px. Stopka siedzi w poziomo przewijanym kontenerze, więc na 375 px „Następna” jest poza ekranem (trzeba przewinąć tabelę w bok).
- **Poprawka:** `flex min-h-12 flex-wrap items-center justify-between gap-2 py-2`, select `hidden sm:flex` (albo `w-auto`), a stopkę wynieść POZA `overflow-x-auto` (pod wrapper), żeby nie przewijała się z kolumnami.

### P1-4. Pasek zaznaczenia listy (`CandidateBulkBar`) ma na telefonie ~187 px szerokości
- **Plik:** `src/components/v2/candidates/CandidateBulkBar.tsx:49`.
- **Co się dzieje:** `fixed bottom-5 left-1/2 -translate-x-1/2 flex flex-wrap` bez szerokości. Element pozycjonowany z `left: 50%` i `width: auto` dostaje szerokość „shrink-to-fit” liczoną od `left` do prawej krawędzi, czyli **50% ekranu**. Na 375 px to 187 px — „N zaznaczonych”, „Dodaj do rekrutacji”, „Porównaj”, „Więcej”, „Wyczyść” łamią się w wysoki słup zasłaniający listę. Na tablecie centruje się względem okna, nie treści obok paska bocznego.
- **Poprawka:** wzór z `EmailBulkActionBar.tsx:193`: zewnętrzny `fixed inset-x-0 bottom-4 z-40 flex justify-center px-4 pointer-events-none`, wewnętrzny `pointer-events-auto flex max-w-full flex-wrap items-center gap-2 …`.

### P1-5. Pasek zbiorczy w wyszukiwarce rekrutacji nie mieści się na telefonie
- **Plik:** `src/components/v2/pages/CandidateSearchView.tsx:1302`, `:1366`.
- **Co się dzieje:** pigułka `flex w-fit items-center gap-3` bez zawijania: „Wybrano N” + „Notatka i tagi” + „Wyczyść” + „Do shortlisty” + „Dodaj do rekrutacji” ≈ 590 px. Rodzic ma `max-w-full`, ale pigułka jest `w-fit` i się nie łamie → na 375 px (i na 768 z przypiętym paskiem, 480 px treści) wystaje poza ekran; przyciski `h-7` (28 px).
- **Poprawka:** `flex max-w-full flex-wrap items-center justify-center gap-2 rounded-2xl` (zamiast `rounded-full` przy zawijaniu), przyciski `h-9 sm:h-7`; na `<sm` rozważyć przyklejony dolny pasek na całą szerokość.

### P1-6. Usuwanie zapisanego wyszukiwania widoczne tylko po najechaniu (niewidoczny, ale klikalny kosz)
- **Plik:** `src/components/v2/pages/CandidateSearchView.tsx:1042`.
- **Co się dzieje:** `opacity-0 group-hover:opacity-100` — na dotyku kosz jest niewidoczny, a ikona 12 px przy nazwie zapisu przechwytuje tapnięcie: użytkownik może usunąć zapis, celując w nazwę. Brak `focus-within`.
- **Poprawka:** `opacity-100 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100 focus-visible:opacity-100`, obszar dotyku `p-1.5 -m-1`.

### P1-7. Czat o kandydacie: „Odpowiedz”, „Reakcja”, „Kto przeczytał” tylko po najechaniu
- **Plik:** `src/components/v2/pages/CandidateChatTab.tsx:717`.
- **Co się dzieje:** `opacity-0 group-hover:opacity-100` bez `focus-within`. Na telefonie/tablecie akcji wiadomości nie widać (iOS czasem emuluje hover po pierwszym tapnięciu, Android nie).
- **Poprawka:** `opacity-100 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100 group-focus-within:opacity-100`; przyciski `min-h-9` na dotyku.

### P1-8. Szyna „ostatni kandydaci” od `lg` zjada pół ekranu na 1024 i 1280
- **Plik:** `src/app/candidates/layout.tsx:31` (`hidden … lg:flex`), `src/components/v2/candidates/CandidateTabsRail.tsx:106` (`w-60`).
- **Co się dzieje:** z domyślnie przypiętym paskiem bocznym treść listy/profilu ma na 1024 px **472 px**, na 1280 px **728 px**. To wywołuje P1-1 (ucięte kolumny), P1-9 (ściśnięty profil) i P2-8 (pasek faktów).
- **Poprawka:** `2xl:flex` zamiast `lg:flex`, albo od `lg` do `2xl` domyślnie wersja zwinięta (ikona z licznikiem — już istnieje, `CandidateTabsRail.tsx:78`).

### P1-9. Profil: prawa kolumna 320 px włącza się po szerokości okna, nie treści
- **Pliki:** `src/components/v2/candidate-profile/ProfileTab.tsx:105-108`, `src/components/v2/candidate-profile/RecruitmentsTab.tsx:148`.
- **Co się dzieje:** `xl:grid-cols-[minmax(0,1fr)_320px]`. Na 1280 px z szyną (728 px treści − `p-5` karty) główna kolumna ma **~348 px** — podsumowanie AI, doświadczenie i umiejętności łamią się co 2–3 słowa. Bez szyny (992 px) ~612 px — w porządku.
- **Poprawka:** kontener `@container` na karcie zakładek i `@4xl:grid-cols-[minmax(0,1fr)_320px]` (Tailwind v4 ma container queries wbudowane), albo przesunąć na `2xl:`.

### P1-10. Podgląd DOCX nie dopasowuje się do szerokości (PDF tak)
- **Plik:** `src/components/v2/files/FilePreviewModal.tsx:305-312` (`inWrapper: true, ignoreWidth: false`), `:428`.
- **Co się dzieje:** `docx-preview` rysuje stronę w szerokości z dokumentu (~794 px A4) + padding wrappera. Na 375 px CV w DOCX czyta się tylko przesuwając w bok; brak „dopasuj do szerokości” i powiększenia, które ma PDF (`PdfDocumentViewer.tsx:148,175-185` — `page-width` + `ResizeObserver`, dobrze zrobione).
- **Poprawka:** po renderze skalować sekcje do szerokości hosta (ResizeObserver: `section.docx { zoom: host.clientWidth / sectionWidth }`) albo CSS poniżej `md`:
  `.docx-preview-host .docx-wrapper{padding:8px} .docx-preview-host section.docx{width:100%!important;min-height:auto!important;padding:16px!important}`.

### P1-11. Wątek e-mail: wcięcie odpowiedzi do 480 px
- **Plik:** `src/components/emails/EmailThreadView.tsx:166`, `src/lib/email-threading.ts:16` (`MAX_DEPTH = 20`).
- **Co się dzieje:** `paddingLeft: depth * 24px`. Typowy łańcuch 6–8 odpowiedzi daje 144–192 px wcięcia; w oknie na telefonie (375 px, `p-4`) treść najgłębszej wiadomości ma ~100 px.
- **Poprawka:** wcięcie zależne od szerokości i przycięte: `style={{ "--d": Math.min(depth, 6) }}` + `pl-[calc(var(--d)*0.5rem)] sm:pl-[calc(var(--d)*1.5rem)]`.

### P1-12. Masowy import CV: tabela ucięta na telefonie
- **Plik:** `src/components/v2/pages/BulkImportCVsV2.tsx:382-383`.
- **Co się dzieje:** `<table className="w-full">` w `overflow-hidden`, 5 kolumn, długie nazwy plików bez łamania. Na 375 px ostatnia kolumna (akcja wiersza) jest poza obszarem i obcięta.
- **Poprawka:** wrapper `overflow-x-auto`, tabela `min-w-[640px]`, nazwa pliku `break-all` (albo na `<sm` karty zamiast tabeli).

### P1-13. Słowa kluczowe: 4 kolumny od `md` przy 480 px treści
- **Plik:** `src/components/v2/candidates/CandidateSearchFields.tsx:71` (`md:grid-cols-[1.2fr_1fr_1fr_auto]`), `:106` (`md:w-40`).
- **Co się dzieje:** na 768 px z przypiętym paskiem (480 px treści − `p-3`) trzy pola chipów mają po **~75 px**; chip ma `max-w-[180px]` (`AdvancedSearchPopover.tsx:152`) i wystaje z kolumny, placeholdery „np. Java, Kafka” są ucięte. Do tego na 768 pas jest już zawsze rozwinięty (`max-md:hidden` kończy się na `md`).
- **Poprawka:** `lg:grid-cols-[1.2fr_1fr_1fr_auto]` + `md:grid-cols-2` pomiędzy; `lg:w-40`; chip `max-w-full`.

---

## P2

### P2-1. Okienka filtrów bez limitu wysokości i z `collisionPadding` 0
- `src/components/v2/candidates/CandidateFilterBar.tsx:355-358` (bazowy `PopoverContent` pigułek), `src/components/ui/popover.tsx:17-19`.
- Tylko „Historia z nami” ma `max-h-[70vh]` (`:522`). „Lokalizacja” (pole + promień + województwa) i „Dostępność” na telefonie w poziomie (~375 px wysokości) wychodzą poza ekran; `w-80` dotyka krawędzi ekranu na 375 px.
- **Poprawka:** w `FilterPill` `max-h-[var(--radix-popover-content-available-height)] overflow-y-auto` + `collisionPadding={8}`; `w-80 max-w-[calc(100vw-1rem)]`.

### P2-2. iOS powiększa ekran przy każdym polu filtra
- `src/components/ui/input.tsx` (bazowo `text-sm` = 14 px), `CandidateFilterBar.tsx:199,210,245,262,770,778` (`h-8 text-sm`/`text-xs`), `CandidateSearchFields.tsx:43-44,359,367`, `AdvancedSearchPopover.tsx:174`; w `globals.css` brak reguły 16 px dla dotyku.
- Safari na iOS przybliża stronę po fokusie pola < 16 px i nie oddala po wyjściu — przy filtrach w okienkach i szufladzie to rozjeżdża cały widok.
- **Poprawka (globalnie):** w `globals.css` `@media (pointer: coarse) { input, select, textarea { font-size: 16px; } }` albo w `Input` `text-base md:text-sm`.

### P2-3. Małe cele dotyku na liście i w filtrach
- Pigułki filtrów `h-8` (32 px) i „✕ wyczyść” `h-6 w-6` (`CandidateFilterBar.tsx:322,367`); usuwanie chipu `w-3 h-3` bez paddingu (`AdvancedSearchPopover.tsx:157`); kopiowanie telefonu `p-0.5` ≈ 18 px (`CandidatePhoneCell.tsx:48`); CV `h-7` (`CandidateCvCell.tsx:67`); checkbox wiersza 16 px (`ui/checkbox.tsx:14`, kolumna 32 px).
- **Poprawka:** `h-9 md:h-8`, dla ikon `relative after:absolute after:-inset-2` (powiększony obszar bez zmiany wyglądu), `min-h-10 min-w-10` na `pointer-coarse:`.

### P2-4. Małe cele dotyku w podglądzie plików i Radarze
- `FilePreviewModal.tsx:566,580` (poprzedni/następny `p-1.5` ≈ 28 px), `:601` (zamknij `p-1` ≈ 24 px); `SearchablePdfPreview.tsx:132-133` (zoom `p-1`); `TalentRadarWorkspace.tsx:~746-747` („→ obowiązkowe/dodatkowe” `h-6`).
- **Poprawka:** `p-2.5 md:p-1.5`, `h-9 md:h-6`.

### P2-5. Jednostki `vh` zamiast `dvh`
- `CandidatesListV2.tsx:1635` (`calc(100vh - 300px)`), `HistoryTab.tsx:384,436` (`78vh`), `CandidateChatTab.tsx:345,362,382` (`70vh` — po otwarciu klawiatury pole wpisywania chowa się pod nią), `FilePreviewModal.tsx:541` (`h-[92vh]`, i tak ścinane do `max-h-[90vh]` z `ui/dialog.tsx:60`).
- **Poprawka:** `dvh` (`h-[78dvh]`, `h-[70dvh]`, `calc(100dvh-300px)`).

### P2-6. „Pokaż CV obok” na telefonie
- `HistoryTab.tsx:108` (domyślnie włączone po wejściu z rekrutacji), `:381-436`.
- Poniżej `lg` CV (78vh) staje NAD historią, a historia ma własne przewijanie `max-h-[78vh] overflow-y-auto` — dwa zagnieżdżone obszary przewijania i historia dopiero po przewinięciu ekranu CV.
- **Poprawka:** domyślnie `showCv` tylko od `lg` (`matchMedia`), `h-[60dvh] lg:h-[78vh]`, `lg:max-h-[78vh] lg:overflow-y-auto`.

### P2-7. Treść maili HTML i załączniki szersze niż telefon
- `EmailThreadView.tsx:240-243` (`prose max-w-none` bez ograniczeń dla tabel i obrazków — newsletterowe `<table width=600>` rozpychają cały panel), `:269` (nazwa załącznika `max-w-[20rem]` w przycisku z ikonami ≈ 390 px > 343 px).
- **Poprawka:** `break-words [&_table]:max-w-full [&_table]:block [&_table]:overflow-x-auto [&_img]:max-w-full [&_img]:h-auto`; przycisk `max-w-full min-w-0`, nazwa `max-w-[min(20rem,100%)] truncate`.

### P2-8. Pasek faktów profilu: 5 kolumn od `xl` bez względu na szerokość treści
- `src/components/v2/pages/CandidateProfileFactsBar.tsx:1124-1125` (`xl:grid-cols-5`), kafel z ikoną `size-8` (`:218`).
- Na 1280 px z szyną kafel ma ~125 px, na wartość zostaje ~70 px — stawka i dostępność się łamią/ucinają.
- **Poprawka:** container query (`@container` na karcie nagłówka, `@3xl:grid-cols-4 @5xl:grid-cols-5`) albo `2xl:grid-cols-5`.

### P2-9. Porównanie 3 kandydatów od `md`
- `src/app/candidates/compare/page.tsx:540-541`.
- Na 768 px (480 px treści) trzy karty po ~145 px.
- **Poprawka:** `md:grid-cols-2 xl:grid-cols-3` dla `ids.length >= 3`.

### P2-10. Podwójny margines w wyszukiwarce rekrutacji
- `src/components/v2/pages/CandidateSearchView.tsx:823` — `p-4` wewnątrz `main` z `p-4`: na 375 px treść ma 311 px.
- **Poprawka:** `p-0 md:p-4` (albo usunąć padding — shell już go daje).

### P2-11. Drobne w podglądzie i Radarze
- `CandidateQuickView.tsx:585` — fakty `grid-cols-3` na 375 px: kafel ~105 px, „Lokalizacja” obcięta. Poprawka: `grid-cols-2 sm:grid-cols-3`, lokalizacja `col-span-2 sm:col-span-1`.
- `TalentRadarWorkspace.tsx:544` — „plik ALBO treść” w `md:grid-cols-[1fr_auto_1fr]` na 480 px daje dwie kolumny po ~200 px z textarea. Poprawka: `lg:`.
- `ui/dialog.tsx:59-60` (przekrojowe) — okna `w-full max-w-*` stoją na 375 px od krawędzi do krawędzi z zaokrąglonymi rogami. Poprawka w prymitywie: `w-[calc(100%-1rem)] sm:w-full`.

---

## Co jest zrobione dobrze

- **Pasek filtrów nad tabelą** (`CandidateFilterBar.tsx:432-452`): na telefonie słowa kluczowe schowane za przyciskiem (`max-md:hidden`), rząd pigułek przewija się w poziomie (`overflow-x-auto`, od `md` `flex-wrap`), pigułki `shrink-0`, podsumowanie wartości z `truncate max-w-[200px]`. Szerokie okienka („Historia z nami”, „Umiejętności”) mają `max-w-[calc(100vw-2rem)]`.
- **Szuflada „Więcej filtrów”** (`ui/sheet.tsx:33,40`): na telefonie pełna szerokość, od `sm` `max-w-md`, przycisk „Pokaż N kandydatów” w stopce.
- **Szybki podgląd** (`CandidateQuickView.tsx`): szuflada na całą szerokość telefonu, przyklejony nagłówek z nawigacją, stopka akcji `flex-wrap`, `px-4 sm:px-6`.
- **Nagłówek profilu** (`ProfileHeader.tsx`): wszystkie akcje, linki kontaktu i „Wróć” mają `min-h-11 min-w-11`; pilnuje tego test `CandidateHeaderTouchTargets.test.tsx`. Zakładki profilu przewijają się poziomo (`TabbedNav overflow="scroll"`, `CandidateDetailV2.tsx:624`), filtr historii też (`HistoryTab.tsx:223`).
- **Wiersz CV na profilu** (`ProfileTab.tsx:208`) i **karty rozmów** (`CallsTimeline.tsx:61`) zawijają się poprawnie.
- **Podgląd PDF** (`PdfDocumentViewer.tsx:148-185`): „dopasuj do szerokości” + ponowne dopasowanie przy zmianie szerokości kontenera.
- **„W procesie”** (`CandidateProcessCell.tsx:59-66`): lista otwiera się także kliknięciem, nie tylko najechaniem — działa na dotyku.
- **Tabela „Technologie w czasie”** (`CvRichProfileSections.tsx:53`) ma `overflow-x-auto`.
- **Pasek zbiorczy maili** (`EmailBulkActionBar.tsx:193`) — `w-full max-w-3xl px-4`: wzorzec do skopiowania w `CandidateBulkBar`.
- **Okno „Szukaj z requestu”** (`RequestSearchDialog.tsx:139,147,213`): siatki od `sm`, treść `max-h-[65vh] overflow-y-auto`.
- **Kolejka kontaktu** (`ContactQueueWorkspace.tsx`): `p-4 md:p-6`, siatki z breakpointami, zakładki przewijane poziomo; **wyniki Radaru** jako karty `md:grid-cols-2 xl:grid-cols-3`.
- Szyna ostatnich kandydatów jest schowana poniżej `lg`.

## Rekomendowana kolejność

1. P0-1 (pliki na telefonie) i P1-1 (jedna linia w `candidateGridLayout` — naprawia też 1280 px z domyślnym paskiem).
2. P1-4 i P1-5 (paski zaznaczenia), P1-3 (paginacja), P1-6/P1-7 (hover-only).
3. P1-8 (szyna od `2xl` lub zwinięta) — usuwa przyczynę P1-9 i P2-8 na laptopach.
4. P1-2 (widok kart na telefonie) — największa praca, osobny PR.
5. P2-2 (globalna reguła 16 px dla dotyku) — jedna zmiana w `globals.css`, dotyczy całej aplikacji.
