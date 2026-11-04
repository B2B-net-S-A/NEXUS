# Duży podgląd po lewej stronie panelu osoby (D1–D6) — raport

Gałąź `claude/recruitment-info-layout-13e69d`, 09.10.2026. Makiety:
https://claude.ai/artifact/WPwic4nk1U1RghZo1qkjMr. Tylko front — bez API i migracji.

## Skąd zmiana

Po #2083 (formularz screeningu z podglądem) i #2087 (przegląd Delivery Leada v2) podgląd stał po prawej stronie
panelu 1200 px. Zmierzone przed zmianą w `/preview/screening-form` przy 1280 × 720:

- strona CV miała 533 px szerokości (67%), tekst 10,8 px,
- nad podglądem stały głowa doku, zakładki i przyciski, więc z CV widać było okno ok. 575 × 250 px,
- w przeglądzie DL kolumna CV miała 380–463 px.

## Decyzje Artura (08–09.10.2026)

| | Decyzja |
|---|---|
| D1 | Podgląd po lewej na całą wysokość panelu, praca w stałej prawej kolumnie (460 px, od 1536 px okna 520 px) |
| D2 | Panel na całą szerokość okna, zakrywa Tablicę i menu boczne |
| D3 | Na dużym monitorze (okno od ok. 1700 px) dwa podglądy naraz: CV i wymagania z „Po ludzku” |
| D4 | Przegląd DL: CV pierwsze i największe; „Wymagania i ocena” zakładką na laptopie, kolumną na dużym monitorze; przyciski decyzji zawsze widoczne |
| D5 | Pod każdym wymaganiem jedno zdanie ze słowniczka „po ludzku” |
| D6 | To samo dla „Zweryfikowany” (CV do klienta) i „Rozmowa u klienta” |

## Co się zmieniło

### Panel osoby (D1, D2)

- `person/PersonPanelShell.tsx`: rozmiary `dock | wide | split | review`. `split` i `review` zajmują całe okno
  (`data-cover`). W `split` lewa strefa podglądu + kolumna pracy 460/520 px.
- `person/PersonPanelSide.tsx` (nowy): strefa, dostawca i portal. Treść podglądu należy do warsztatu głęboko
  w doku, więc trafia do strefy portalem; poniżej 1024 px i bez dostawcy zostaje w miejscu.
- Menu boczne ma `z-40`, a panel siedzi w kontekście warstw treści strony — `z-index` panelu nic nie daje.
  `SidebarV2` dostał `data-app-sidebar`, a `globals.css` regułę, która zdejmuje menu `z-index` na czas otwarcia
  panelu z `data-cover`.
- `pages/KanbanBoardV2.tsx`: `split` dla zakładek z podglądem (Screening, CV, Rozmowy), `wide` dla pozostałych,
  `review` dla przeglądu DL.

### Podgląd (D3, D5)

- `screening-form/CandidatePreviewPane.tsx`: większe zakładki, PDF dopasowany do szerokości z sufitem 125%
  (`fit="auto"`), tryb dwóch podglądów od 1150 px szerokości strefy, opcje `preferCompanyCv` i `extraTab`.
- `lib/docx-fit.ts` (wyniesione z `FilePreviewModal`) — CV firmowe (DOCX) mieści się w strefie bez przewijania
  w bok (`person/StageCvPreview.tsx`).
- `champion/JobRequirementsSummary.tsx`: lista zamiast chipów — nazwa, zdanie ze słowniczka, „Szukaj w CV”.
- „Po ludzku” w kolumnie do czytania, większym tekstem (`jobs/DockCallCheatsheet.tsx`, prop `roomy`).

### Przegląd Delivery Leada (D4)

- `recruitment/DlReviewPanel.tsx`: układ liczony z szerokości przeglądu — `stack` (< 1100 px), `tabs`
  (1100–1639 px: CV + decyzja 460 px, wymagania zakładką), `columns` (od 1640 px: CV + wymagania 440 px +
  decyzja 520 px). Zawsze te same cztery elementy w tej samej kolejności — zmiana trybu niczego nie montuje
  ponownie.
- `dl-review/CvColumn.tsx`: pasek z przełącznikiem CV firmowe / CV oryginalne / Wymagania i ocena, plakietką QC
  i „Otwórz QC”.
- `dl-review/DecisionPanel.tsx`: pasek „Wymagania N/M · brak: …” z „Pokaż”, przyciski decyzji w przyklejonej
  stopce; formularz odrzucenia przewija się do widoku.
- Okno przeglądu na pulpicie: do 2000 px szerokości.

### CV do klienta i Rozmowy (D6)

- `person/PersonSidePreview.tsx` (nowy): ten sam podgląd po lewej, zaczyna od CV firmowego, gdy para je ma.
  Przy Rozmowach dodatkowa zakładka „Pytania klienta”.
- Klik w osobę od „Zweryfikowany” wzwyż nadal otwiera wąski dok; duży podgląd po „Rozwiń”.

### Pozostałe

- Harnessy: `/preview/screening-form` (ramka z prawdziwą strefą, słowniczek i pytania kandydata w danych),
  `/preview/dl-review?layout=panel` (przegląd jak na Tablicy, z plikiem CV), `/preview/job-detail` (replika
  menu `z-40` i `animate-fadeIn`).
- `lib/recruitment-feature-inventory.json`: nowy wpis `person-panel.side-preview`, zaktualizowane opisy.
- Przewodniki Jarvisa `jobs.person` i `jobs.board` poprawione i przestemplowane.
- CLAUDE.md: nowa sekcja „Duży podgląd po lewej stronie panelu osoby” (w środku pliku) i poprawki w trzech
  istniejących akapitach.

## Pomiar po zmianie (lokalny podgląd, 09.10.2026)

| Okno | Ekran | Przed | Po |
|---|---|---|---|
| 1280 × 720 | formularz screeningu — szerokość strony CV | 533 px (67%) | 703 px (89%) w harnessie; strefa 819 px w replice powłoki |
| 1280 × 720 | wysokość podglądu | ok. 250 px | 672 px (cała wysokość panelu) |
| 1536 × 864 | strona CV | — | 899 px (113%), kolumna pracy 520 px |
| 1920 × 1008 | dwa podglądy naraz | — | CV 842 px + kolumna 440 px + formularz 520 px |
| 1280 × 720 | przegląd DL — pole CV | 380–463 px | 786 px, decyzja 460 px, przyciski przyklejone |
| 1920 × 1008 | przegląd DL | — | CV 816 px + wymagania 440 px + decyzja 520 px |
| 1024, 390 px | wszystkie | jedna kolumna | jedna kolumna, bez poziomego przewijania |

## Czego świadomie nie zrobiłem

- Dwukolumnowego „Po ludzku” ze słowniczkiem obok — zdania ze słowniczka stoją przy wymaganiach (D5).
- Automatycznego otwarcia dużego podglądu po kliknięciu osoby od „Zweryfikowany” wzwyż — schowałoby „Otwórz QC”
  i ramkę „Następny etap”, które są tylko w sekcjach doku.
- Osadzenia Prep-kitu (strona generuje go wywołaniem AI przy każdym wejściu).
- Zmian w tym, kto co może przesunąć, w QC i w treści formularzy.

## Przegląd kodu (09.10.2026)

Niezależny przegląd (agent `typescript-reviewer`) znalazł jeden problem blokujący i został on naprawiony przed
otwarciem PR-a:

- W trybie dwóch podglądów (strefa od 1150 px, okno od ok. 1700 px) podgląd CV odmontowywał się, gdy strefa
  znikała — „Zwiń”, Esc, zakładka „Notatki”/„Umowa”/„Dopasowanie” albo inna sekcja z podglądem. Ukryta strefa ma
  `display: none`, pomiar zwracał 0, układ wracał do zakładek i wyrzucał CV, którego nikt nie kliknął jako zakładki.
  Po powrocie plik pobierał się drugi raz, a pozycja i szukane słowo znikały. W jsdom nie do złapania (szerokość 0).
- Poprawka: `lib/use-element-width.ts` zostawia ostatni pomiar, gdy element ma szerokość 0; podgląd pamięta, że
  tryb dwóch podglądów zamontował już wszystko (`everDual`), więc także zwężenie okna niczego nie odmontowuje.
- Testy, które padały przed poprawką: `CandidatePreviewPane.test.tsx` („ukrycie strefy…”, „zwężenie okna…”),
  plus `lib/__tests__/use-element-width.test.tsx`.

Pozostałe sprawdzone obszary bez uwag: cykl życia portalu, rozmiary panelu, zakładki warsztatu, przegląd DL
(zawsze te same cztery elementy), reguła CSS menu.

## Weryfikacja

| Część | Stan | Dowód |
|---|---|---|
| Testy zmienionych plików i strażników | zielone | `npx vitest run …` — 21 plików, 743 testy, 09.10.2026 06:04 |
| Typy | czyste | `npx tsc --noEmit -p .` → exit 0 |
| Lint zmienionych plików | czysty | `eslint` → exit 0 |
| Moduły bez wejścia | czyste | `npm run check:unreachable-modules` → exit 0 |
| Stemple przewodników | zgodne | `python3 scripts/check_stamps.py` → exit 0 po przestemplowaniu `jobs.person`, `jobs.board` |
| Formularz screeningu 1280 × 720 | przeklikane | harness `/preview/screening-form`: strona CV 703 px, podgląd na całą wysokość, „Szukaj w CV” zaznacza w CV |
| Dwa podglądy 1920 × 1008 | przeklikane | CV 842 px + kolumna 440 px + formularz 520 px |
| „Zwiń” → „Rozwiń” w dwóch podglądach | przeklikane | `/preview/job-detail` przy 1920 px: ten sam węzeł DOM podglądu CV przed i po, `data-dual` bez zmian |
| Panel nad menu bocznym | przeklikane | replika menu `z-40` w `/preview/job-detail`; `elementFromPoint(100, 300)` trafia w panel |
| Przegląd DL — trzy tryby | przeklikane | `/preview/dl-review?layout=panel` przy 1280 (zakładki), 1920 (kolumny), 390 (jedna kolumna); okno z pulpitu przy 1280 |
| Przegląd DL na Tablicy | przeklikane | `/preview/pipeline-v4?as=dl` → `data-size="review"`, tryb `tabs` |
| 1024 px i 390 px | przeklikane | jedna kolumna albo strefa 514 px + kolumna 460 px, bez poziomego przewijania |
| E2E — dwa nowe testy laptopa | zielone lokalnie | `responsive-preview.spec.ts`, projekt `preview-chromium` na serwerze deweloperskim |
| E2E — test laptopa `/preview/job-detail?empty=1` | niepotwierdzone lokalnie | na serwerze deweloperskim kończy się limitem czasu `networkidle`; ręczny pomiar: nagłówek „Nowi” na 41% wysokości, bez przewijania w bok. Do potwierdzenia biegiem `e2e.yml` na gałęzi |
| Prawdziwa powłoka aplikacji (zalogowana) | niepotwierdzone | lokalnie tylko harnessy; sprawdzenie po wdrożeniu |
| Produkcja | niepotwierdzone | po wdrożeniu: `/api/health` z SHA z maina, potem odczyt na rekrutacji QA przy 1280 × 720 |

## Znane ograniczenia

- Przejście szerokości okna przez 1024 px (zmiana z portalu na treść w miejscu) montuje podgląd od nowa: zakładka
  zostaje, ale wybrane źródło CV, szukane słowo i pozycja przewijania znikają, a plik pobiera się jeszcze raz.
- CV firmowe (DOCX) nie jest powiększane ponad 100% — w bardzo szerokiej strefie ma margines po bokach.
- Podgląd sekcji „CV” i „Rozmowy” montuje się dopiero przy pierwszym wejściu w sekcję.
