# Duży podgląd po lewej stronie panelu osoby (D1–D6, 09.10.2026)

Zgłoszenie Artura 08.10.2026: po #2083/#2087 podgląd (CV, wymagania, „po ludzku”) stał po prawej i był za mały —
strona CV miała 533 px (67%), a na laptopie 1280 × 720 widać było z niej ok. 250 px wysokości. Decyzje D1–D6
(makiety https://claude.ai/artifact/WPwic4nk1U1RghZo1qkjMr), raport `docs/person-panel-preview-left-completion-report.md`.
Tylko front, bez API i migracji.

- **Rozmiary panelu: `dock | split | review`** (`person/PersonPanelShell.tsx`). `split` i `review` zajmują
  całe okno i mają `data-cover`. W `split` panel dzieli się na lewą strefę podglądu (`PersonPanelSideZone`, cała
  wysokość, od 1024 px okna) i stałą prawą kolumnę z dokiem (460 px, od 1536 px okna 520 px). `split` ma KAŻDA
  zakładka rozwiniętego panelu, przegląd DL ma `review`. Rozmiaru `wide` (760 px, Umowa / Dopasowanie / Notatki bez
  podglądu) nie ma od 09.10.2026 — pasek zakładek przesuwał się przez niego w bok.
- **Panel zakrywa menu boczne regułą CSS, nie `z-index`.** Menu ma `z-40`, a panel siedzi w kontekście warstw
  treści strony (`animate-fadeIn` z wypełnieniem `both`), więc jego `z-30` nigdy nie wygra. Menu ma atrybut
  `data-app-sidebar`, a `globals.css` zdejmuje mu `z-index` na czas otwarcia panelu z `data-cover`. Pilnuje
  `AppShellLayout.test.ts` i e2e (`elementFromPoint` nad menu). Nie podbijaj `z-index` panelu.
- **Podgląd trafia do strefy portalem** (`person/PersonPanelSide.tsx`): stan podglądu (zakładka, szukane słowo)
  należy do warsztatu głęboko w doku. Strefa jest zamontowana zawsze (poza `split` ukryta), więc zwinięcie panelu
  i zmiana zakładki nie pobierają pliku CV drugi raz; `PersonPanelSideSection` chowa portal niewidocznej zakładki.
  Poniżej 1024 px i bez dostawcy (testy, zwykłe strony) treść zostaje w miejscu pod przyciskiem „Pokaż CV
  i wymagania”. Szerokość okna czytana synchronicznie (`useSyncExternalStore`) — efekt po malowaniu montował
  podgląd dwa razy.
- **Podgląd (`screening-form/CandidatePreviewPane.tsx`):** PDF dopasowany `fit="auto"` (szerokość, najwyżej 125% —
  bez sufitu strefa 1400 px dawała 170%), CV firmowe (DOCX) dopasowane `lib/docx-fit.ts`. Od 1150 px szerokości
  podglądu (okno ok. 1700 px) dwa podglądy naraz: CV i kolumna 440 px z „Wymaganiami” i „Po ludzku” (D3). Tryby
  liczy `lib/use-element-width.ts` — w jsdom szerokość to 0, więc testy widzą najwęższy wariant. **Pomiar ignoruje
  szerokość 0 po wcześniejszym pomiarze** (ukryta strefa ma `display: none`), a podgląd po trybie dwóch podglądów
  niczego nie odmontowuje (`everDual`): bez tego „Zwiń” i zmiana zakładki pobierały CV drugi raz (przegląd kodu
  09.10.2026). Układ liczony w JS z szerokości elementu = ten hak, nie własny `ResizeObserver`.
- **„Wymagania” to lista, nie chipy (D5,** `champion/JobRequirementsSummary.tsx`): nazwa, pod nią jedno zdanie ze
  słowniczka „po ludzku” (`summary` hasła w stanie `ready`), obok „Szukaj w CV”. Wymaganie bez gotowego hasła
  pokazuje samą nazwę — nie wstawiaj tekstu zastępczego.
- **Podgląd po lewej w każdej zakładce (D6, od 09.10.2026 także Umowa, Dopasowanie, Notatki):** po „Rozwiń” ten
  sam podgląd (`person/PersonSidePreview.tsx`, za `next/dynamic`), zaczyna od CV firmowego, gdy para je ma. CV,
  Umowa, Dopasowanie i Notatki mają JEDEN wspólny egzemplarz (`SHARED_PREVIEW_SECTIONS` w `PersonWorkbenchTabs`) —
  zmiana zakładki nie przewija CV od początku; Rozmowy mają własny z zakładką „Pytania klienta”, Screening własny
  w warsztacie. Nowa zakładka panelu = wpis w `SHARED_PREVIEW_SECTIONS` albo własny podgląd, nigdy pusta strefa.
  Klik w osobę od „Zweryfikowany” wzwyż nadal otwiera wąski dok — „Otwórz QC” i ramka „Następny etap” są tylko
  w jego sekcjach.
- **Formularz Generatora B2B układa pola po szerokości kontenera** (`@container` + `@xl:grid-cols-*`
  w `GeneratorForm`, `Field`, `RoleScopeEditor`): w kolumnie panelu jedno pole w rzędzie, na stronie Generatora
  dwa albo trzy jak dotąd. Nie wracaj tam do `sm:grid-cols-*` — w kolumnie 460 px dawało trzy pola po 120 px.
- **Pasek zakładek stoi w miejscu (09.10.2026, zgłoszenie rekruterów).** Po „Rozwiń” głowa panelu ma tę samą
  wysokość w każdej zakładce: `PipelineCandidateDock` przy `tabsOpen` nie renderuje w niej faktów („Warunki wobec
  rekrutacji”), rzędu „Biorę / Nie odebrał” ani ramki „Następny etap”. Te same bloki stoją POD paskiem jako jedna
  zwinięta linia `DockStageFold` („Warunki i następny etap · Zweryfikowany · brakuje 4 z 4”), którą dok podaje
  zakładkom przez `WorkbenchBelowTabsContext` (`person/WorkbenchBelowTabs.tsx`). Do tej daty poza „Screeningiem”
  wracały do głowy i przy oknie 1536 × 780 na treść zakładki zostawało ok. 70 px. Zakładka z własnym ruchem
  i własnymi warunkami (Screening w „Nowych”) linii nie ma. Przypięte notatki są po „Rozwiń” zawsze zwinięte, bo
  stoją nad paskiem. Nowy blok w głowie rozwiniętego panelu musi mieć tę samą wysokość w każdej zakładce — inaczej
  pasek znowu skacze (pilnuje e2e „pasek zakładek stoi w miejscu”). Wąski dok bez zmian.
- **Wąski dok przewija się w całości (09.10.2026, zgłoszenie z laptopa 1280 × 650).** W miejscu stoi tylko
  pasek osoby (`dock-person-bar`: nawigator, nazwisko z kontaktem, plakietki ostrzeżeń, „Rozwiń”, zamknij) i pole
  notatki; „Warunki”, sprawa zmiany stawki, „Następny etap”, przyciski etapów i sekcje przewijają się razem
  (`dock-body` z `data-person-scroll`). Do tej daty cała głowa stała w miejscu: na sekcje zostawały 92 px,
  a z otwartą sprawą zmiany stawki przyciski i pole notatki wypadały poza okno (po zmianie 393 px). Po „Rozwiń”
  blok akcji (`dock-actions`) stoi nad paskiem zakładek jak dotąd, a `data-person-scroll` przechodzi na treść
  zakładki — zmieniają się wyłącznie klasy, elementy zostają w tym samym miejscu drzewa. Nowy blok wąskiego doku
  idzie do `dock-actions` albo sekcji, nigdy do paska osoby (pilnuje e2e „wąski dok osoby przewija się w całości”).
- **Telefon i e-mail pod nazwiskiem** (`person/PersonContactLine.tsx`, wąski dok i po „Rozwiń”): numer to link
  `tel:`, ikony kopiują; czego profil nie ma, tego nie pokazujemy. Dane z zapytania o profil, które dok i tak robi.
- **Formularz screeningu zaczyna się od „Warunków”** (stawka, dostępność, tryb), potem pytania z Profilu
  Championa i „Ocena” — także w widoku tylko do odczytu. Prośba rekruterów 09.10.2026; nie odwracaj kolejności.
- Harnessy: `/preview/screening-form` (ramka z prawdziwą strefą), `/preview/job-detail` (replika menu `z-40`
  i `animate-fadeIn`), `/preview/dl-review?layout=panel`. Każdą zmianę panelu sprawdź przy 1280 × 720: strona CV
  ma tam ok. 700–750 px szerokości.
