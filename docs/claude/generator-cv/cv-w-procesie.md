# CV w procesie (13.10.2026, D4)
<!-- indeks: źródła AI w karcie, jedna lista „Do poprawy” -->

PR 4 z 4 po weryfikacji generatora CV i QC (makiety:
https://claude.ai/artifact/BZZRshjBDC4CMEGGP6m4Wr). Uzupełnia „Generator CV
tylko w rekrutacji” (`generator-cv-tylko-w-rekrutacji.md`) — tamta reguła
mówi, GDZIE powstaje CV, ta — z czego i jak rekruter widzi, co sprawdzić.

## Źródła dla AI (D4)

- **Rodzaje materiału** (`standalone_service.AI_SOURCE_DEFAULTS`):
  odpowiedzi ze screeningu (domyślnie tak), notatki tej rekrutacji (tak),
  transkrypty rozmów (nie), podsumowania prepu (nie). Oryginalne CV i Profil
  Championa wchodzą zawsze. Notatki ze stawką i dostępnością są wycinane
  zawsze (`money_text`) — tego nie da się włączyć.
- **`POST /api/cv-generator/generate`** przyjmuje `sources` (tylko z etapem).
  `collect_screening_notes_text` pomija wyłączone źródła; przy wyłączonych
  notatkach i prepie nie czyta notatek wcale. Minimum notatek z reguły klienta
  liczy ten sam tekst.
- **Wybór zostaje przy wersji CV:** migawka zadania (`CandidateGenerationSource
  .ai_sources`, stare migawki dekodują się bez niego) i `render_payload
  ["ai_sources"]` (klient tego nie dostaje — `public_view` wybiera pola
  dokumentu). Karta otwiera panel z wyborem bieżącej wersji (`last_used`).
- **`GET /api/candidates/stages/{id}/cv/ai-sources`** (odczyt rekrutacji,
  `cv_ai_sources.py`): same liczby, bez treści — odpowiedzi (ile przeczy
  pytaniu), notatki, ze stawką, prep, transkrypty (ile spoza okna tej
  rekrutacji), oryginalne CV (plik, data), Champion, domyślne i bieżący wybór.

## QC zaraz po podpięciu CV

`cv_auto_generate.attach_as_stage_draft` (auto-CV i ręczna generacja z
etapem) po podpięciu szkicu, a `POST …/cv/branded/select-generated` („Użyj
nowej wersji” i podmiana szkicu z karty) w tle, woła `qc_after_attach` →
`cv_qc.run_after_move` (flaga `CV_QC_GATE_ENABLED`, nigdy nie rzuca). Karta
i Tablica pokazują liczbę rzeczy do sprawdzenia bez otwierania okna QC.

## Karta „CV do klienta” i edytor

- **Generacja w karcie, nie w oknie.** „Generuj CV”, „Wygeneruj ponownie”
  i „Spróbuj ponownie” otwierają w karcie panel „Z czego powstało”
  (`recruitment/CvGeneratePanel.tsx`, wiersze `cv-generator/AiSourcesRows.tsx`,
  logika `lib/cv-ai-sources.ts`): oryginalne CV i Champion („zawsze” albo
  „brak”), przełączniki odpowiedzi, notatek, transkryptów i prepu (stan
  początkowy = `last_used`, inaczej domyślne), notatki ze stawką zablokowane,
  obróbka i język jak w generatorze. Panel używa `useCvGenerator` okna
  generatora — te same reguły klienta, zgoda RODO i komunikaty 422.
  `cv_document_id` = oryginał z `…/ai-sources`. Awaria odczytu źródeł nie
  blokuje generacji: żądanie idzie bez `sources` (domyślne serwera) i panel
  to mówi.
- **Nowa wersja zastępuje szkic** raz, istniejącym „Użyj nowej wersji”
  (`selectGenerated`) z wierszem etapu i wersją szkicu zapamiętanymi w chwili
  zlecenia generacji — edycja szkicu w trakcie generacji kończy się 409, a nie
  nadpisaniem. Gdy podmiana się nie uda, przycisk zostaje.
  Nieudana generacja zostawia bieżące CV („Nowa wersja nie powstała: …”).
- **Jedna liczba w karcie** (`CvToClientChecks`, `cvChecksBeforeSending`
  w `lib/cv-to-client.ts`): zadania QC blokujące + uwagi QC poza wyciszonymi +
  uwagi generatora bez duplikatów QC + uwagi kontroli AI. „Sprawdź i popraw”
  otwiera edytor na „Do poprawy”. Awaria któregokolwiek odczytu = komunikat
  z „Ponów”, nigdy zero; „Nic do sprawdzenia” tylko po obu udanych odczytach.
- **Prosta karta (Edytor CV 3, PR 3, 14.10.2026).** Gotowe CV to miniatura
  prawdziwej pierwszej strony (`cv/CvFirstPageThumb.tsx`, PDF z pliku Word,
  ładowany dopiero na ekranie, pdf.js leniwie, awaria = ikona pliku) z liczbą
  stron, „Otwórz i popraw”, „Pobierz Word” i menu „⋯”: „Pobierz PDF”, „Użyj
  innego CV”, „Historia wersji” (edytor otwarty na historii), „Wygeneruj
  ponownie”. Klik w miniaturę = okno ze wszystkimi stronami (to samo żądanie
  PDF co miniatura — jedna zamiana na wersję CV). Bez zgody RODO miniatura
  nie pyta serwera. Liczba rzeczy do sprawdzenia stoi na pełnej szerokości
  karty — obok miniatury łamała się w słupek. Panel „Z czego powstało” jest
  zwinięty do zdania („Z oryginału CV, Championa… · tryb · język · Zmień”,
  `aiSourcesSentence`) i rozwija się sam, gdy czegoś brakuje albo serwer
  odmówił; zgoda RODO, braki, błąd i „Generuj” widać zawsze.
- **Okno generatora** ma te same przełączniki w kroku „Proces” („Co jeszcze
  przeczyta AI”).
- **Edytor:** jedna lista „Do poprawy” — patrz `edytor-cv-pelny-ekran.md`.
- **Świadomie bez zmian:** inne wejścia do `CvGeneratorDialog` (profil, dok,
  okno QC) i linia QC w doku kanbanu (`earlyQcSentence` liczy tylko blokady,
  więc może się różnić od liczby w karcie). Karta liczy wszystkie uwagi
  kontroli AI, edytor — te, których linia nadal stoi w CV.
- Harness `/preview/cv-to-client` (panel z domyślnymi, „Wygeneruj ponownie”
  z ostatnim wyborem, liczba 4, nic do sprawdzenia, awaria QC, dwa stany po
  przekazaniu — niżej).

## Blok postępu po „Zapisz i przekaż dalej” (14.10.2026, P3)

Część „Drogi rekrutera do DL” (`rekrutacja-tablica/droga-rekrutera-do-dl.md`).
Po przekazaniu z formularza screeningu panel przechodzi na „CV”, a karta
(`forwarded` z `CvHandoffWorkbench`) pokazuje nad treścią trzy kroki:

- **Screening zapisany ✓ → CV → QC** (`forwardProgress` w
  `lib/cv-to-client.ts`). CV: „generuje się (ok. 40 s)”, „gotowe”, przy CV,
  które para już miała — „CV firmowe: <źródło>” z plakietki pochodzenia
  (`stageCvOrigin`: z pliku Word, z rekrutacji X, przeniesione), a gdy automat
  pominął osobę — powód z „Pracy w tle” (`autoCvSkipReason`). QC: „liczę…”,
  „N do poprawy” (ta sama liczba co „N rzeczy do sprawdzenia”, te same
  zapytania — `useCvChecksCount`), „bez uwag”.
- **Karta pyta sama.** Tuż po ruchu wiersza auto-CV jeszcze nie ma (stan
  „brak”), a dotąd karta w tym stanie nie pytała wcale. Z `forwarded` pyta co
  4 s (`cvToClientShouldPoll(…, { awaitingAuto })`: lista generacji, CV etapu,
  „Praca w tle”), aż pojawi się wiersz CV albo powód pominięcia, najdłużej
  5 minut — potem krok CV prosi o ręczną generację. Pominięcie starsze niż
  przekazanie (z zapasem 2 min na zegar) nie jest odpowiedzią.
- **„Dam znać dzwonkiem, gdy CV będzie gotowe…”** stoi, dopóki CV robi
  automat (dzwonek `cv_ready` wysyła serwer tylko po podpięciu przez automat).
  Po pominięciu przez automat i przy generacji zleconej z karty zdania nie ma
  (`forwardProgress(…, { manual })`, poprawka po teście na produkcji 14.10.2026). **„Następna w Screeningu: <Imię> ·
  Otwórz ›”** pokazuje się, gdy `nextInColumn(osoba, "screening")` kogoś
  zwraca; panel nie skacze sam (`openPerson` dopiero po kliknięciu).
- Harness `/preview/cv-to-client`: osoba „po przekazaniu — CV się generuje”
  (po 12 s automat „kończy” CV, QC daje liczbę; odczyty karty odpowiada
  pamięć harnessu, bez sieci) i „automat pominął osobę”.
