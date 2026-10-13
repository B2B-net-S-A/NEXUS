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
etapem) po podpięciu szkicu woła `cv_qc.run_after_move` (flaga
`CV_QC_GATE_ENABLED`, nigdy nie rzuca). Karta i Tablica pokazują liczbę rzeczy
do sprawdzenia bez otwierania okna QC.

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
  (`selectGenerated` z wersją szkicu); gdy to się nie uda, przycisk zostaje.
  Nieudana generacja zostawia bieżące CV („Nowa wersja nie powstała: …”).
- **Jedna liczba w karcie** (`CvToClientChecks`, `cvChecksBeforeSending`
  w `lib/cv-to-client.ts`): zadania QC blokujące + uwagi QC poza wyciszonymi +
  uwagi generatora bez duplikatów QC + uwagi kontroli AI. „Sprawdź i popraw”
  otwiera edytor na „Do poprawy”. Awaria któregokolwiek odczytu = komunikat
  z „Ponów”, nigdy zero; „Nic do sprawdzenia” tylko po obu udanych odczytach.
- **Okno generatora** ma te same przełączniki w kroku „Proces” („Co jeszcze
  przeczyta AI”).
- **Edytor:** jedna lista „Do poprawy” — patrz `edytor-cv-pelny-ekran.md`.
- **Świadomie bez zmian:** inne wejścia do `CvGeneratorDialog` (profil, dok,
  okno QC) i linia QC w doku kanbanu (`earlyQcSentence` liczy tylko blokady,
  więc może się różnić od liczby w karcie). Karta liczy wszystkie uwagi
  kontroli AI, edytor — te, których linia nadal stoi w CV.
- Harness `/preview/cv-to-client` (panel z domyślnymi, „Wygeneruj ponownie”
  z ostatnim wyborem, liczba 4, nic do sprawdzenia, awaria QC).
