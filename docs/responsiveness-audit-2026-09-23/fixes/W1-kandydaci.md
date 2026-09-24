# W1-kandydaci — poprawki responsywności (raport 02-candidates + 10-runtime)

Ścieżki względem `frontend/`. Numery linii po zmianach.

| Ustalenie | Stan | Plik:linia | Uwagi |
|---|---|---|---|
| P0-1 Pliki i umowy: akcje ucięte na telefonie | zrobione | `src/components/v2/files/CandidateFilesTab.tsx:255`, `:303`, `:316` | Wiersz `flex-col sm:flex-row`, ikona+nazwa w osobnym `min-w-0 flex-1`, akcje `flex-wrap sm:shrink-0`, select `min-h-10 sm:min-h-0`. Naprawia też runtime (−12 px przy 360). |
| P1-1 Wiersze ucinają „Przypisz”/CV (minWidth bez gap i paddingu) | zrobione | `src/lib/candidate-table-columns.ts:96`; `src/components/v2/pages/CandidatesListV2.tsx:1618` | `minWidth = 32 + Σmin + 12·kolumny + 32`. Nagłówek przeniesiony DO kontenera przewijania (przyklejony u góry, nieprzezroczyste tło pod `bg-muted/60`), jeden kontener `overflow-auto` w obu osiach, kontener wierszy ma `minWidth`, wirtualizacja `scrollMargin: 40` + `translateY(start − 40)`. Wiersz `overflow-hidden` → `overflow-clip` (hidden robił z wiersza scroller i psuł sticky). Zewnętrzna ramka `overflow-hidden` tylko dla zaokrągleń — nic w niej nie wystaje. |
| P1-2 Podwójne przewijanie na telefonie, brak przyklejonej kolumny | zrobione (bez widoku kart — decyzja) | `CandidatesListV2.tsx:1618`, `:1648`, `:1751` | Wysokość `md:h-[calc(100dvh-300px)] md:min-h-[360px]`; poniżej `md` kontener bez wysokości → przewija się strona (wirtualizator renderuje całą stronę wyników). Kolumna „Kandydat” `max-lg:sticky left-0 z-[1] bg-card` w wierszach i nagłówku (`bg-muted`). Od `lg` wygląd bez zmian (poświata hover/„Nowy” zostaje). |
| P1-3 Stopka paginacji nie zawija się | zrobione | `CandidatesListV2.tsx:1926` | `min-h-12 flex-wrap py-2`, licznik `whitespace-nowrap`, grupa przycisków `flex-wrap`, select `h-9 w-auto sm:h-8 sm:w-[152px]`. Stopka jest poza kontenerem przewijania (nie jeździ z kolumnami). |
| P1-4 CandidateBulkBar ma 50% szerokości | zrobione | `src/components/v2/candidates/CandidateBulkBar.tsx:48` | Wzór `EmailBulkActionBar`: zewnętrzny `fixed inset-x-0 bottom-4 flex justify-center px-4 pointer-events-none`, wewnętrzny `pointer-events-auto max-w-full flex-wrap`. „Odznacz” `min-h-9 sm:min-h-0`. |
| P1-5 Pasek zbiorczy w wyszukiwarce rekrutacji | zrobione | `src/components/v2/pages/CandidateSearchView.tsx:1370` | `max-w-full flex-wrap justify-center rounded-2xl lg:rounded-full`, przyciski `h-9 sm:h-7`, „Dodaj do „…”” z `truncate`. |
| P1-6 Kosz zapisanego wyszukiwania tylko po najechaniu | zrobione | `CandidateSearchView.tsx:1046` | `pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100 focus-visible:opacity-100` + `hit-area`. |
| P1-7 Akcje wiadomości czatu tylko po najechaniu | zrobione | `src/components/v2/pages/CandidateChatTab.tsx:721` | `focus-within:opacity-100 pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100`, widoczne też przy otwartym wyborze reakcji; przyciski `pointer-coarse:min-h-9`. |
| P1-8 Szyna ostatnich kandydatów od `lg` | zrobione | `src/app/candidates/layout.tsx:33` | Od `2xl` (`2xl:flex`, `2xl:gap-6`), `max-h-[calc(100dvh-7rem)]`. |
| P1-9 Profil: kolumna 320 px po szerokości okna | zrobione | `src/components/v2/pages/CandidateDetailV2.tsx:630`; `src/components/v2/candidate-profile/ProfileTab.tsx:107`; `RecruitmentsTab.tsx:148` | `@container` na treści karty zakładek, `@4xl:grid-cols-[minmax(0,1fr)_320px]` i `@4xl:sticky`. |
| P1-10 DOCX bez dopasowania do szerokości | zrobione | `src/components/v2/files/FilePreviewModal.tsx:83` (helper), efekt z `ResizeObserver` | Po renderze `section.docx` dostaje `zoom = dostępna szerokość / szerokość strony` (tylko gdy strona szersza), na <640 px padding wrappera 8 px. Przelicza się przy zmianie szerokości. |
| P1-11 Wcięcie wątku e-mail do 480 px | zrobione | `src/components/emails/EmailThreadView.tsx:170` | Zmienne CSS: telefon 0,5 rem × min(głębokość, 6), od `sm` 1,5 rem × głębokość (jak dotąd 24 px). |
| P1-12 Import CV: tabela ucięta | zrobione | `src/components/v2/pages/BulkImportCVsV2.tsx:385` | `relative overflow-x-auto`, tabela `min-w-[640px]`, kolumna „Plik” `max-md:sticky left-0 bg-card max-w-[160px]`, nazwa `break-all`, „Usuń” z `hit-area`. |
| P1-13 Słowa kluczowe: 4 kolumny od `md` | zrobione | `src/components/v2/candidates/CandidateSearchFields.tsx:72` | `md:grid-cols-2 lg:grid-cols-[1.2fr_1fr_1fr_auto]`, „Szukaj w” `lg:w-40`. Chip `max-w-[180px]` jest w `v2/filters/AdvancedSearchPopover.tsx` — poza zakresem. |
| P2-1 Okienka filtrów bez limitu wysokości / collisionPadding | zrobione | `src/components/v2/candidates/CandidateFilterBar.tsx:359` | `collisionPadding={8}`; limit wysokości i `max-w-[calc(100vw-1rem)]` daje już prymityw `ui/popover` (inny agent) — usunięte dublujące `max-h-[70vh] overflow-y-auto` z „Historii z nami”. |
| P2-2 iOS zoom na polach | pominięte (zrobione globalnie) | — | Reguła w `globals.css` (pointer-coarse → 16 px) już jest. |
| P2-3 Małe cele dotyku na liście i w filtrach | zrobione częściowo | `CandidateFilterBar.tsx:323`, `:556` (pigułki `h-9 md:h-8`), „✕ wyczyść” i „Usuń język” `hit-area`; `CandidatePhoneCell.tsx:48`, `CandidateCvCell.tsx:67` `hit-area` | Checkbox (`ui/checkbox`) i usuwanie chipu (`AdvancedSearchPopover`) — poza zakresem. |
| P2-4 Małe cele w podglądzie plików i Radarze | zrobione | `FilePreviewModal.tsx` (poprzedni/następny `p-2.5 md:p-1.5`, zamknij `p-2.5 md:p-1`); `SearchablePdfPreview.tsx:133` (zoom `p-2.5 md:p-1`); `TalentRadarWorkspace.tsx:745-746` (`h-9 md:h-6`) | |
| P2-5 `vh` zamiast `dvh` | zrobione | `CandidatesListV2.tsx` (lista, pula `50dvh`), `HistoryTab.tsx`, `CandidateChatTab.tsx:345,362,382`, `FilePreviewModal.tsx` (`92dvh`), `CandidateCompareModal.tsx`, `RequestSearchDialog.tsx`, `RequirementVerificationDialog.tsx`, `EmailThreadView.tsx` (okno `90dvh`), harnessy `preview/{candidates,candidates-list,candidate-profile,cv-search}` | |
| P2-6 „Pokaż CV obok” na telefonie | zrobione | `src/components/v2/candidate-profile/HistoryTab.tsx:114`, `:391` | Domyślnie tylko przy `matchMedia("(min-width:1024px)")`; `h-[60dvh] lg:h-[78dvh]`; własne przewijanie historii tylko od `lg`. |
| P2-7 HTML maili i załączniki szersze niż telefon | zrobione | `EmailThreadView.tsx:250`, przycisk załącznika | `break-words`, `[&_table]:block max-w-full overflow-x-auto`, `[&_img]:max-w-full h-auto`; przycisk `min-w-0 max-w-full`, ikony `shrink-0`. |
| P2-8 Pasek faktów 5 kolumn od `xl` | zrobione | `src/components/v2/pages/CandidateProfileFactsBar.tsx:1127` | Wrapper `@container`, `@lg:grid-cols-2 @4xl:grid-cols-5` (bez stawki `@3xl:grid-cols-4`). |
| P2-9 Porównanie 3 kandydatów od `md` | zrobione | `src/app/candidates/compare/page.tsx:541` | `md:grid-cols-2 xl:grid-cols-3`. |
| P2-10 Podwójny margines w wyszukiwarce | zrobione | `CandidateSearchView.tsx:825` | `p-0 md:p-4` (shell / wysuwka dają padding). |
| P2-11 Fakty w podglądzie / Radar / dialog | zrobione (bez dialogu) | `CandidateQuickView.tsx:593` (`grid-cols-2 sm:grid-cols-3`, lokalizacja `col-span-2 sm:col-span-1`); `TalentRadarWorkspace.tsx:544` (`lg:`) | `ui/dialog` — poza zakresem (prymitywy). |
| Runtime: `sr-only` „Akcje” rozpycha stronę | zrobione | `src/components/candidates/preview/CandidateListPreview.tsx:75` | `relative` na `overflow-x-auto`; to samo w realnych tabelach: `CvRichProfileSections.tsx:53`, `CandidateCompareModal.tsx:161`, `BulkImportCVsV2.tsx:385`, kontener listy kandydatów. |
| Runtime: paginacja statusu przeglądu nachodzi na tekst | pominięte (już w drzewie) | `src/components/talent-radar/FullCandidateSearchStatus.tsx:54` | Poprawkę (`flex-[1_1_16rem]` + `flex-wrap`) wprowadził równolegle inny agent zanim tu doszedłem — nie ruszałem pliku. |

## Zmienione testy
- `src/lib/__tests__/candidate-table-columns.test.ts` — oczekiwany `minWidth` liczy odstępy (8×12) i padding (32); to cel poprawki P1-1.
- `src/components/v2/pages/__tests__/CandidateProfileFactsBar.test.tsx` — `sm:grid-cols-2` → `@lg:grid-cols-2` + sprawdzenie `@container` na rodzicu (P2-8, układ po szerokości kontenera).

## Poza zakresem
- `src/components/v2/filters/AdvancedSearchPopover.tsx:152,157` — chip `max-w-[180px]` → `max-w-full`, usuwanie chipu `w-3 h-3` bez obszaru dotyku (P1-13, P2-3).
- `src/components/ui/checkbox.tsx` — checkbox 16 px (P2-3).
- `src/components/ui/dialog.tsx:59-60` — `w-[calc(100%-1rem)] sm:w-full` (P2-11).
- `src/lib/email-threading.ts` — `MAX_DEPTH` nietknięte; limit wcięcia na telefonie zrobiony w widoku.
- `src/components/v2/files/DocumentSearchBar.tsx` — przyciski poprzednie/następne trafienie `p-1` (~24 px); plik nie był wymieniony wprost w moim zakresie.

## Wyniki sprawdzeń
- ESLint na 34 zmienionych plikach: 0 błędów, 8 ostrzeżeń (wszystkie istniejące wcześniej: `any` w `compare/page.tsx`, `exhaustive-deps` w `CandidateSearchView.tsx:364`).
- Vitest (24 pliki powiązane): pierwszy bieg 12 czerwonych + 6 workerów nie wystartowało — load average 100–290 (inne agenty). Wszystkie czerwone pliki powtórzone przy `asyncUtilTimeout` 30 s: **10/10 plików, 60/60 testów zielone**; `CandidateQuickView` + `CandidateCompareModal` 19/19 zielone. To obciążenie maszyny, nie regresja.
- tsc: zobacz dopisek niżej.

### Dopisek: tsc
`npx tsc --noEmit -p .` — jedyny błąd to przestarzały, wygenerowany `.next/types/app/settings/cv-rules/page.ts` (eksport `QUERY_KEY` z `app/settings/cv-rules/page.tsx`, poza moim zakresem; typowy objaw starego `.next/types` — `rm -rf .next/types` go usuwa). W plikach `src/` zero błędów typów.
