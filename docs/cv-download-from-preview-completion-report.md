# „Pobierz CV” w dużym podglądzie panelu osoby — raport z wdrożenia D1–D5 (15.10.2026)

Prośba z zespołu (przekazana przez Artura): „kafelek, który z tego widoku pozwoli
pobrać aktualne CV kandydata, np. obok Wgraj CV”. Makiety i decyzje D1–D5:
https://claude.ai/artifact/EBFqwhJjt1CoSUGkjYnPTV — decyzja Artura: „tak na A,
D1–D5”. Reguła: `docs/claude/rekrutacja-tablica/nowe-cv-w-rekrutacji.md`,
sekcja „Pobieranie z podglądu”.

## Co było nie tak (sprawdzone w kodzie przed zmianą)

- „CV oryginalne” w dużym podglądzie nie miało pobierania — „Pobierz plik”
  pokazywał się tylko, gdy podgląd się nie wczytał.
- Ten sam plik dało się pobrać wyłącznie z doku: sekcja „CV” → „Pokaż CV
  oryginalne” → okno → „Pobierz”.
- „Inne pliki” — bez pobierania.
- „CV firmowe” miało „Pobierz DOCX” w treści zakładki, w innym miejscu niż „Wgraj CV”.
- Podgląd pokazuje kopię CV ze zgłoszenia, nawet gdy w profilu leży nowsze CV —
  ramka „W profilu jest nowsze CV” była tylko w doku.
- Podgląd nie stosował reguły kwarantanny tożsamości (audyt 13.10.2026, pkt 8)
  przy „Oryginał CV: z profilu” — dok tak.

## Co weszło

| Decyzja | Zmiana | Pliki |
|---|---|---|
| D1 | „Pobierz CV” w pasku źródeł przed „Wgraj CV”, także bez prawa wgrania (przegląd DL, edytor CV) | `CandidatePreviewPane.tsx` |
| D2 | Pobiera to, co widać: kopię ze zgłoszenia, główne CV z profilu albo zaznaczony plik; dymek z nazwą pliku i źródłem (`originalCvSentence`); plik z kwarantanny nie jest oryginałem (`withoutQuarantinedCv` przeniesione do `lib`, znacznik tylko z pamięci zapytań) | `CandidatePreviewPane.tsx`, `dock-cv-summary.ts`, `PipelineCandidateDock.tsx` |
| D3 | „Pobierz Word” + „PDF” przy CV firmowym w tym samym miejscu (`fetchStageCvFile` / `fetchStageCvPdf`, `surface=preview`); bez zgody RODO wyłączone; „Pobierz DOCX” w treści zakładki ukryte (`hideDownload`) | `CandidatePreviewPane.tsx`, `StageCvPreview.tsx` |
| D4 | Ramka „W profilu jest nowsze CV” nad oryginałem; „Użyj w tej rekrutacji” tylko z prawem wgrania (`canRefresh`) | `CandidatePreviewPane.tsx`, `DockCvFreshness.tsx` |
| D5 | Przy otwartej „Historii osoby” przycisku nie ma; oryginał bez wpisu `cv_file_downloaded` | `CandidatePreviewPane.tsx` |
| laptop | Na 1280 px rząd się zawijał — poniżej 56 rem „Zwiń CV” jako ikona, „⤓ Word” / „PDF”, odstęp 6 px | `CandidatePreviewPane.tsx` |

Do tego: inwentarz `screening-form.preview-cv-download`, harness
`/preview/screening-form` (stan `cvnewer`, `cvUpload` w pasku), przewodnik Jarvisa
`jobs.person` (odpowiedź „Jak przygotować CV do klienta?” mówi o „Pobierz CV”)
przestemplowany. Bez migracji, bez zmian backendu.

Uwaga: przy CV firmowym w stanie „legacy” (stary szablon, tylko podgląd) podgląd
nie ma już „Pobierz DOCX” — jak dok, który pobiera tylko CV w stanie „ready”.

## Weryfikacja

- Vitest (lokalnie): `CandidatePreviewPane` 56 testów (14 nowych, najpierw 13
  czerwonych), `dock-cv-summary` +3, razem 22 pliki sąsiednie (dok, przegląd DL,
  edytor CV, inwentarz, harnessy, granice paczek) — 973 zielone.
- `tsc --noEmit`, eslint zmienionych plików — czysto.
- Backend bez bazy: `test_screen_guides_freshness.py` 18, `test_claude_md_index.py` 4,
  `check_stamps.py` — czysto.
- Przeglądarka, harness `/preview/screening-form`, 1280×720:
  - „CV oryginalne”: jeden rząd (693 z 745 px), dymek „… CV.pdf · dołączony do
    zgłoszenia · 5.10.2026”;
  - „CV firmowe” z historią i wgrywaniem: jeden rząd 707 z 745 px, bez „Pobierz DOCX”;
  - stan `cvnewer`: ramka nad oryginałem, „Pokaż” → „Inne pliki (3)” z nowszym plikiem;
  - „Historia osoby” otwarta: bez przycisku;
  - 1600×900: pełne etykiety „Pobierz Word”, „Zwiń CV”.
- Kliknięcie pobrania w harnessie nie pobiera (brak API) — zachowanie pokrywają testy.

## Po wdrożeniu (okno 19:00–07:00)

1. `/api/health` → `version` = SHA z maina z tym PR-em.
2. Rekrutacja → osoba w „Nowych” → „Rozwiń” w 1280×720: „Pobierz CV” pobiera
   ten sam plik co podgląd; „CV firmowe” u osoby z gotowym CV → Word i PDF.
