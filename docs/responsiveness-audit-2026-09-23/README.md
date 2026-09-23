# Audyt responsywności NEXUS — 23.09.2026

Dziesięciu agentów pracowało równolegle. Ośmiu czytało kod po obszarach, jeden skanował wzorce w całym repo, a jeden mierzył strony w przeglądarce (Playwright, produkcyjny build, harnessy `/preview/*` w szerokościach 360–1920 px, 156 zrzutów).
Raporty cząstkowe leżą obok, w plikach `01-…10-*.md`, i mają pełne `plik:linia` dla każdego znaleziska.

Zakres i ograniczenia:
- Ekrany po zalogowaniu sprawdzone są z kodu. Do tego pomiar na tych harnessach, które renderują prawdziwe komponenty.
- Nic nie było testowane na fizycznym iPhonie ani Androidzie.
- Najważniejsze ustalenia sprawdziłem sam w kodzie: `AppShellV2:166`, `globals.css:541`, `NotificationsDropdown:468/643`, `ProposalPanel:116/131`, `ui/input:19`, `ui/dialog:59`, `cv_html_renderer.py:340`, `WeekCalendar:270`, `settings/templates:627`. Kafelek zamówienia obejrzałem też na zrzucie.

## Wynik w liczbach

| Obszar | P0 | P1 | P2 |
|---|---:|---:|---:|
| Shell + kit DS + prymitywy | 2 | 8 | 18 |
| Kandydaci | 1 | 13 | 11 |
| Rekrutacje + Tablica | 1 | 6 | 23 |
| Klienci + zamówienia | 0 | 14 | 19 |
| Kontrakty + generatory B2B/CV | 1 | 19 | 18 |
| Dashboard / Insights / Finanse | 0 | 14 | 19 |
| Ustawienia / Kalendarz / Pomoc | 3 | 9 | 22 |
| Strony publiczne | 1 | 4 | 20 |
| **Razem (po odjęciu dubli)** | **≈8** | **≈85** | **≈145** |

P0 oznacza, że na telefonie lub tablecie czegoś nie da się użyć. P1 to rozjechany układ, poziomy scroll albo ucięta treść. P2 to kosmetyka i ergonomia.

Skala w całym repo:
- 29% plików TSX (210 z 717) ma jakikolwiek prefiks responsywny.
- 0 użyć `dvh`.
- 114 siatek `grid-cols-N` bez wariantu dla węższych ekranów.
- 15 tabel bez przewijania w poziomie.
- 707 przycisków `size="sm"` o wysokości 32 px.
- 613 miejsc z tekstem 9–11 px.
- W pomiarze przy 390 px 58,6% elementów klikalnych (776 z 1325) ma mniej niż 32 px.

## Pięć przyczyn systemowych — każdą naprawia się raz

1. **Shell ma `h-screen`** (`AppShellV2.tsx:166`). Na telefonie dolne 56–80 px każdej strony leży pod paskiem przeglądarki. Naprawa to `h-dvh`, jedna linia.
2. **Pola mają globalnie 14 px** (`globals.css:541-553`, `ui/input.tsx:19`, `ui/textarea.tsx:16`, `ui/select.tsx:19`, `ui/command.tsx:63`). iOS powiększa stronę przy każdym fokusie, a dotyczy to ok. 840 pól. Naprawa: `text-base md:text-sm` w tych miejscach. W `globals.css` selektor atrybutowy wygrywa z klasą, więc zmiana musi być tam, nie w pojedynczych polach.
3. **Okna dialogowe dotykają krawędzi i używają `vh`** (`ui/dialog.tsx:59`). Naprawa: `w-[calc(100%-1rem)] sm:w-full`, `max-h-[90dvh]`. Te same wzorce powtarzają się w oknach pisanych ręcznie (`ModalShell`, `UserModal`, okna w `MaterialsTab` i `FrameworkContractsTab`): brak `p-4` na tle, brak `max-h`, brak przewijania. Przycisk zapisu znika wtedy pod klawiaturą.
4. **Pasek boczny jest domyślnie przypięty (240 px) także na tablecie** (`useSidebarPinned.ts:18`), a na dotyku rozwinięcie „po najechaniu” zostaje po stuknięciu (`SidebarV2.tsx:162`). Do tego szyna ostatnio oglądanych kandydatów od `lg` (`app/candidates/layout.tsx:31`). Przy 1024 px strona kandydata ma przez to ok. 472 px. Naprawa: przypinać domyślnie dopiero od 1280 px, hover tylko dla `pointerType === "mouse"`, szynę pokazywać od `2xl`.
5. **Układ reaguje na szerokość okna, nie kontenera.** Kafelki pulpitu, doki i okna mają `lg:grid-cols-4` itp., choć same mają 400–670 px (`OrderPlanLineCard.tsx:251`, widżety w `TileFrame`). Naprawa: container queries z Tailwind v4 (`@container` + `@lg:`). Obok tego kwoty PLN (`Intl` pl-PL daje twarde spacje) nie zawijają się i wychodzą poza kafle. Naprawa: `text-lg sm:text-2xl` i `min-w-0` na kaflach.

Plus dwa wzorce do wymiany hurtowo:
- **Akcje widoczne tylko po najechaniu** (`opacity-0 group-hover:opacity-100`), 9 miejsc. W Tailwind v4 `hover:` nie działa na dotyku, więc tych akcji na telefonie nie ma wcale. Naprawa: `opacity-100 md:opacity-0 md:group-hover:opacity-100 focus-within:opacity-100` albo wariant `pointer-coarse:`.
- **Tabele w `overflow-hidden` zamiast `overflow-x-auto`.** Kolumny i przyciski akcji są wtedy ucięte bez możliwości przewinięcia.

## P0 — nieużywalne na telefonie / tablecie

| # | Gdzie | Co się dzieje | Naprawa |
|---|---|---|---|
| 1 | `v2/shell/TopbarV2.tsx:103-150` | Przy 375–430 px pasek górny przelewa się o ok. 60 px, a `overflow-hidden` ucina „Dodaj” i dzwonek | przełączniki palety, trybu Kids i motywu oraz skróty w `hidden sm:flex`, przycisk wyszukiwania `min-w-0` |
| 2 | `v2/shell/AppShellV2.tsx:166` | `h-screen`: dół każdej strony pod paskiem przeglądarki | `h-dvh` |
| 3 | `NotificationsDropdown.tsx:643` (+ toast `:468`) | Panel dzwonka `w-96` przyklejony prawą krawędzią, ok. 70 px poza ekranem z lewej. Toast `right-6 w-full` wystaje 24 px | `fixed inset-x-2 top-14 sm:absolute sm:inset-x-auto sm:right-0 sm:w-96`; toast `inset-x-4 sm:inset-x-auto sm:right-6` |
| 4 | `v2/recruitment/ProposalPanel.tsx:116,131` + `ProposalsSegment.tsx:416` | „Do przejrzenia”: panel `w-[372px] shrink-0` obok tabeli, więc na telefonie lista ma 0 px (potwierdzone pomiarem) | `flex-col lg:flex-row`, panel `w-full lg:w-[372px]` albo `Sheet` poniżej `lg` |
| 5 | `calendar/WeekCalendar.tsx:270,819,328/499` | Tydzień zawsze z panelem bocznym 256 px i 7 dniami, więc siatka ma ok. 70 px. Linki z przypomnień `?event=` otwierają właśnie ten widok | panel `hidden lg:flex`, poniżej `md` widok jednego dnia albo agenda, wysokość w `dvh` |
| 6 | `app/settings/templates/page.tsx:627-629` | Szablony maili: lista `w-80 shrink-0` obok edytora, więc edytor ma ok. 7 px przy 375 | `flex-col lg:flex-row`; na telefonie lista ALBO edytor |
| 7 | `candidates/…/CandidateFilesTab.tsx:253-352` | Pliki kandydata: „Podgląd” i „Pobierz” ucięte przez `overflow-hidden` karty i niedostępne | `flex-col sm:flex-row`, przyciski `flex-wrap` |
| 8 | `backend/app/services/cv_html_renderer.py:333-350` (+ `html_export.py:345`) | Publiczne CV `/cv/…` otwierane z maila na telefonie: `grid-template-columns: 230px 1fr` bez media query, na tekst zostaje 30–47 px. Dotyczy linków sprzed `CV_CLIENT_LINKS_UI_ENABLED=false` | `@media (max-width:640px){.cv-body{grid-template-columns:1fr}.cv-header-date{position:static}}`, a dla zamrożonego HTML ten sam blok doklejony do `srcDoc` na froncie |

## P1 — rozjechany układ / ucięta treść (najważniejsze, po obszarach)

**Klienci i zamówienia**
- `OrdersAndContractsTab.tsx:1379`: pasek akcji kafelka zamówienia (`flex-wrap … shrink-0`) ma 772 px i nie zawija się. Przy 390 px przyciski sięgają 817 px, a cała strona zmniejsza się dwukrotnie. **Zmierzone i widoczne na zrzucie.** Naprawa: usunąć `shrink-0` i dać `w-full`/`min-w-0` na kontenerze.
- `clients/[id]/ProjectsTab.tsx:100`: akcje `shrink-0` zjadają ok. 230 z 290 px, a z tytułu rekrutacji zostaje „…”.
- `client-profile/SummaryBar.tsx:45` + `StatsCard.tsx:98` i `AnalyticsTab.tsx:104`: kwoty wychodzą poza kafle. Naprawa: `grid-cols-1 min-[420px]:grid-cols-2`.
- Tabele w `overflow-hidden`:
  - `RateCardsTab.tsx:404`
  - `DlClientsTable.tsx:26`
- Okna bez `max-h` i przewijania:
  - `MaterialsTab.tsx:402,934,1064`
  - `FrameworkContractsTab.tsx:490,640`
  - `CloseJobAsLostModal.tsx:107` (`ModalShell`)
- Skrzynka zamówień `OrderMailQueue.tsx`:
  - `:405` zakładki nie zawijają się, co daje +59 do +90 px poziomego scrolla (zmierzone);
  - `:430` poniżej `lg` szczegóły renderują się pod całą listą bez przewinięcia, więc stuknięcie wygląda jak martwe;
  - `:678` tabela bez przewijania.
- Przyciski bez `flex-wrap`:
  - `clients/[id]/page.tsx:939`
  - `ClientsListV2.tsx:498`
  - `ContractStructureSection.tsx:180` (zmierzone +39 px)
- `OwnersTab.tsx:250,378`, `FrameworkContractsTab.tsx:282`: długie e-maile i nazwy plików bez `min-w-0 truncate`.
- `clients/[id]/page.tsx:344`: usuwanie wpisu z bazy wiedzy tylko po najechaniu.

**Kandydaci**
- `lib/candidate-table-columns.ts:83-86` + `CandidatesListV2.tsx:1634`: minimalna szerokość wiersza pomija odstępy i padding (910 zamiast 1022 px), a kontener ma `overflow-x-hidden`. Kolumna „Przypisz” jest niedostępna poniżej ok. 1100 px. **Zmierzone** (+271 px przy 1024, +15 px przy 1280). Poprawka to jedna linia.
- `CandidatesListV2.tsx:1633-1640`: na telefonie przewijanie w przewijaniu (`100vh-300px`), brak widoku kart i przyklejonej kolumny nazwiska.
- `CandidatesListV2.tsx:1902`: paginacja ma ok. 470 px bez zawijania, więc „Następna” jest poza ekranem.
- Paski zaznaczenia:
  - `CandidateBulkBar.tsx:49`: przy 375 px pasek ma 187 px. Wzór do skopiowania jest w `EmailBulkActionBar.tsx:193`.
  - `CandidateSearchView.tsx:1366`: pasek ma 590 px bez zawijania.
- Akcje tylko po najechaniu:
  - `CandidateSearchView.tsx:1042` (usuń zapisane wyszukiwanie)
  - `CandidateChatTab.tsx:717` (odpowiedz/reakcja)
- `FilePreviewModal.tsx:305-312`: DOCX renderuje się w pełnej szerokości strony, więc trzeba przewijać w bok. PDF już dopasowuje się do szerokości.
- `EmailThreadView.tsx:166`: wcięcie wątku rośnie do 480 px. `BulkImportCVsV2.tsx:382`: tabela ucięta.
- Profil przy 1024–1279 px jest ściśnięty przez szynę (`ProfileTab.tsx:105`, `RecruitmentsTab.tsx:148`, `CandidateProfileFactsBar.tsx:1124`). Naprawia to przyczyna systemowa nr 4.

**Rekrutacje i Tablica**
- `KanbanBoardV2.tsx:1366-1368,1571-1578,2549`: na telefonie nad tablicą stoją nagłówek, filtry i nawigator, więc zostaje 280 px z własnym przewijaniem, czyli ok. 2 karty.
- `KanbanBoardV2.tsx:2653` + `:2365`: dok kandydata 380 px bez tła, a rezerwa `pr-[380px]` jest dopiero od `xl`. Przy 768–1279 px ostatnie kolumny są pod dokiem.
- `JobsListV2.tsx:153-168,1918-1945`: poniżej `xl` „Podgląd” otwiera dok pod listą i nie przewija do niego.
- `InterviewFeedbackModal.tsx:453,569-576`: oceny 1–5 to 3 kolumny po 216 px w oknie, które daje ~202 px na kolumnę. Przyciski nachodzą na siebie nawet na desktopie.
- Tabela targu `MarketplaceTable.tsx:149-150`: 8 kolumn w `overflow-hidden`.
- `JobChatTab.tsx:720`: odpowiedz/reakcja tylko po najechaniu.
- `recruitment-v3`: status przeglądu `FullCandidateSearchStatus.tsx:54` łamie się po słowie i nachodzi na „Poprzednia” (zmierzone +45 px przy 360).

**Kontrakty i generatory**
- Tabele ucięte bez przewijania, więc kolumna akcji jest niedostępna:
  - `ContractDocumentsTab.tsx:259,270`
  - `ContractInvoicesTab.tsx:232`
  - `contracts/[id]/page.tsx:2269,2287`
- JSON w `<pre>` rozpycha kartę, bo brakuje `min-w-0`:
  - `ContractAmendmentsTab.tsx:421,433,437`
  - `contracts/[id]/page.tsx:2343,2381`
- Generator B2B:
  - `B2BContractGeneratorV2.tsx:501`: podwójny padding.
  - `:524-536`: zakładki się nie przewijają.
  - `:2032,2600`: wyszukiwarka z `min-w-[18rem]` rozpycha stronę.
  - `:2167,2398,2707,2757`: kolumna akcji przyklejona na telefonie zasłania 45% tabeli.
  - `:3883,3928,3965`: stawki progresywne w `grid-cols-3`, pole daty ma ok. 60 px.
- Przycisk X przykrywa inne elementy w każdej szerokości:
  - `CVGeneratorStandaloneV2.tsx:2355`: przykrywa „Pobierz”, więc stuknięcie zamyka okno.
  - `CVBrandedEditModal.tsx:425,444`: przykrywa status.
  - Naprawa: `pr-16`.
- Pozostałe:
  - `CVGeneratorStandaloneV2.tsx:2122,2201`: akcje wiersza „Wygenerowane CV” zjadają kolumnę nazwiska.
  - `ContractsClientPicker.tsx:58`: `min-w-[260px]`.
  - `CandidateRateScheduleFields.tsx:60`: trzy pola w jednym wierszu.
  - `contracts/analytics/page.tsx:148,167`: rankingi ucięte.
  - `ContractsListV2.tsx:788`: nagłówek bez zawijania, +9 px (zmierzone).

**Dashboard, Insights, Finanse**
- `CustomDashboard.tsx:309` + `DashboardGrid.tsx:26,88-91`: „Edytuj układ” widać od `md`, ale siatka przechodzi w listę przy kontenerze < 768 px. Między 768 a ~924 px (do ~1104 z przypiętym paskiem) edycja nic nie robi.
- `TileFrame.tsx:155`: menu kafelka tylko po najechaniu, a na telefonie to jedyna droga do ustawień i usunięcia kafelka.
- Widżety w kafelkach reagują na szerokość okna (przyczyna nr 5):
  - `RecruitmentCompetenceDashboard.tsx:403` (potrzebuje 782 px)
  - `RecruitmentActivityDashboard.tsx:283,680`
  - `ContactOversightPanel.tsx:154`
  - `MyKpiWidget.tsx:156`
  - `TeamAllocationBoard.tsx:1781`
- Kafle z kwotami (`insights/_shared.tsx:67-75`) w `grid-cols-2` na telefonie:
  - `InsightsClientsRanking.tsx:102`
  - `InsightsBoardKPI.tsx:128,171,235`
  - `InsightsDlPortfolio.tsx:321`
- Paski, które się nie zawijają:
  - `PeriodPicker.tsx:155-175` (~340 px)
  - `BodyLeasingPanel.tsx:74-77`
  - `RadaNadzorczaPanel.tsx:76`
  - `finance/page.tsx:128-162` (5 trybów)
- `EditableCell.tsx:101-103`: edycja komórek Finansów tylko dwuklikiem, podpowiedź tylko w `title`.
- `RecruitmentFunnel.tsx:74-104`: stałe `w-44/w-12/w-16` sprawiają, że pasek lejka ma 0 px. `SourcesFunnelSection.tsx:44` ma `overflow-hidden`.
- `InsightsBoardKPI.tsx:359-398`: wartości trendu Rady tylko w `title`, etykiety 9 px. `MetricTileBody.tsx:80-101`: liczba ucięta w wąskim kafelku.

**Ustawienia, Kalendarz, Pomoc**
- `settings/admin/UserModal.tsx:101-102`, `ResetPasswordModal.tsx:29`: okno użytkownika ma ok. 700 px bez przewijania, więc przycisk „Zapisz” jest nieosiągalny.
- `PipelineTemplatesTab.tsx:364,441`: wiersz etapu się nie zawija, a nazwa etapu przy 768 px ma ok. 60 px.
- `app/talents/page.tsx:458-508`: wiersz puli bez `min-w-0`.
- Szczegóły pod listą bez przewinięcia:
  - `AgendaView.tsx:92,208-220`
  - `HelpPageV2.tsx:236-303`
  - `HelpClientPlaybooksSection.tsx:127`
- Kalendarz:
  - `WeekCalendar.tsx:1129`: 6 typów wydarzeń w `grid-cols-5`, etykiety wychodzą poza przyciski.
  - `WeekCalendar.tsx:1366`: import iCal ma `w-96`.
- `HelpPageV2.tsx:477-482`: tabele Markdown w procedurach bez przewijania. Instrukcja zamówień ma 41 wierszy tabel.
- `components/cv-rules/*`: brak breakpointów, wymaga osobnego przejrzenia.

**Strony publiczne** (kandydat i klient na telefonie)
- `apply/[token]/ApplyForm.tsx:370`: pola 14 px i ~36 px wysokości. Naprawa: `h-11 text-base sm:h-10 sm:text-sm`.
- `ApplyForm.tsx:283-292`: długa nazwa pliku CV rozpycha kartę, więc strona przewija się w bok.
- `apply/[token]/page.tsx:104`: nagłówek `text-3xl` bez `break-words`.
- `cv/[token]/page.tsx:139`: iframe `calc(100vh-220px)` + `min 600px`, czyli przewijanie w przewijaniu. `cv/i/[token]/page.tsx:673-677`: wysokość ramki mierzona raz, obrót telefonu ją psuje.
- Wzorem do skopiowania jest strona kariery: pola 16 px i 48 px, cele dotyku 44 px, `overflow-wrap:anywhere`.

**Shell i kit DS (pozostałe P1)**
- `TopbarV2.tsx:117`: od `md` okruszki `md:flex-none`. Przy 768 px z przypiętym paskiem ucina się ok. 200 px, przy 1024 px „Dodaj”. Trzy KPI (`MyKpiWidget.tsx:211,219`) pokazywać dopiero od `xl`.
- `ui/command.tsx:43,78`: lista paleta ⌘K ma 420 px na sztywno w `max-h-[90vh] overflow-hidden`. Przy klawiaturze wyników nie da się przewinąć. Na telefonie brak przycisku zamknięcia.
- `JarvisMascot.tsx:47`, `MyPeopleLauncher.tsx:102`: maskotka 64 px zasłania dół treści (`<main>` ma `p-4`). Do tego do 10 pływających elementów w prawym dolnym rogu i nigdzie `safe-area-inset`.
- `ds/StatCard.tsx:148,121-130`: `text-[32px]` + sparkline w `grid-cols-2` przy 375 px wychodzą poza kafel.

## P2 — wzorce do przejścia hurtem

- **Cele dotyku.** `Button size="sm"` (32 px) ma 707 użyć, a żaden rozmiar nie daje 44 px. Najmniejsze elementy:
  - ołówki w `InlineOrderFields.tsx` (12×12);
  - „×” w chipach, checkboxy (16×16);
  - uchwyty przeciągania i zmiany rozmiaru kafelków (16–20 px);
  - strzałki tygodnia (bez `aria-label`).

  Propozycja: `pointer-coarse:h-11` w wariantach przycisku albo `after:` z powiększonym polem trafienia.
- **Mały tekst.** `text-[9/10/11px]` występuje 613 razy. W pomiarze `pipeline-v4` ma 122 węzły poniżej 11 px, w tym 9,5 px.
- **Podwójny padding stron** (strona `p-6` wewnątrz shella `p-4 md:p-6`): InsightsView, CustomDashboard, CortexView, DynaReporter, generator B2B, ContractorsListV2, cv-rules, ai, api-integration, NewJobPage, apply/share/sign.
- **Siatki bez wariantu dla węższych ekranów**, 114 miejsc. Najgorsze:
  - `CycleBoard.tsx:50` (7 × 180 px)
  - `ImportTab.tsx:160` (4 kolumny)
  - `EditOrderDialog`, `NewContractorOrderDialog`, formularze kontaktów (`grid-cols-2`)
  - `NewJobReviewForm.tsx:263`
- **Tabele szerokie bez przyklejonej pierwszej kolumny**: YoY, ranking klientów, konsultanci, wyniki Finansów, lista rekrutacji (7 kolumn, ~850 px). Poniżej `md` warto dać kafelki.
- **Popovery, menu i select bez ograniczenia wysokości.** Naprawa: `max-h-[var(--radix-popover-content-available-height)]`. `TabsList` nie przewija się w poziomie.
- **Szuflada nawigacji mobilnej** nie zamyka się Esc, nie ma pułapki fokusu ani `aria-modal`.
- **Trzy systemy toastów** nakładają się w tym samym rogu.
- **Pasek „Podgląd jako” i panele z `top-12`** (`MyPeoplePanel`, dok kanbanu) nachodzą na topbar przy aktywnym podglądzie.
- **Strony publiczne:**
  - przycisk pokaż/ukryj hasło ma 16×16 px i brak `pr-10` w polu;
  - strona kariery bez `themeColor`;
  - tytuł 46 px łamie słowa, lepiej `clamp(34px,11.5vw,46px)`;
  - `justify-between` w stopkach się nie zawija.

## Co już działa dobrze — nie ruszać

- Mobilna nawigacja działa: hamburger, szuflada, zamykanie przy zmianie trasy.
- Kolumna treści ma `min-w-0` i przewija się w `<main>`.
- Zoom nie jest blokowany.
- Prymityw `Table` ma owijkę z przewijaniem.
- `DialogBody` przewija się, a stopka dialogu na telefonie ma przyciski w kolumnie.
- `Sheet` jest na telefonie pełnej szerokości.
- `AppModal` ma stały nagłówek i stopkę, więc duży formularz „Nowe zamówienie” działa na telefonie.
- Rejestr kontraktów (`ContractsListV2`) poniżej `xl` pokazuje karty.
- Macierz uprawnień (`PermissionsTab.tsx:597`) to wzór widoku mobilnego: `hidden md:block` + karty ról.
- Tablica ma nawigator etapów na wąskich ekranach. Gęsty widok włącza się tylko przy `xl` z myszą.
- Pulpit ma tryb listy na telefonie, a wykresy używają `ResponsiveContainer`.
- Pasek filtrów Kandydatów i szuflada „Więcej filtrów” działają na telefonie.
- Strona kariery jest wzorcowo mobile-first.
- Tabele z `min-w-[…]` wewnątrz `overflow-x-auto` (`StageBreakdownSection`) to wzór do kopiowania.

## Proponowana kolejność napraw

1. **Fundamenty, jeden mały PR.** Poprawia każdy ekran naraz:
   - `h-dvh` w shellu;
   - `text-base md:text-sm` w `globals.css` i prymitywach pól;
   - margines i `dvh` w `ui/dialog.tsx`;
   - dzwonek i toast;
   - topbar przy 375 px;
   - domyślne przypięcie paska od 1280 px oraz hover tylko dla myszy;
   - `pb-24` pod maskotką;
   - `max-h` popoverów.
2. **Osiem P0.** Każde to kilka klas. Najdroższy jest kalendarz, bo potrzebuje widoku jednego dnia.
3. **Poprawki jednolinijkowe ze zmierzonym skutkiem:**
   - `candidate-table-columns.ts` (kolumna „Przypisz”);
   - `OrdersAndContractsTab.tsx:1379`;
   - `overflow-hidden` → `overflow-x-auto` w 10 tabelach;
   - `flex-wrap` w 8 paskach przycisków;
   - akcje tylko po najechaniu w 9 miejscach.
4. **Okna ręczne bez przewijania** (`UserModal`, `ModalShell`, Materiały, umowy ramowe): przepiąć na `AppModal`.
5. **Container queries w kafelkach pulpitu i dokach**, plus zawijanie kwot.
6. **P2 hurtem:** cele dotyku, mały tekst, podwójny padding, siatki bez wariantu.
7. **Zabezpieczenie przed regresją.** Skrypt pomiarowy agenta (`10-runtime.md`, Playwright po harnessach w 360/768/1280, porównanie z szerokością urządzenia, a nie `innerWidth`) jako test w CI. Pułapka: emulacja mobilna Chrome poszerza stronę przy przelewie, więc zwykłe `scrollWidth > innerWidth` przy 390 px zawsze daje 0.
