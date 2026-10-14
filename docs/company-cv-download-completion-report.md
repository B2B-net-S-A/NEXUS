# CV dla klienta w panelu osoby — raport z wdrożenia D1–D5 (14.10.2026)

Prośba Delivery Leada: „czy CV pod konkretną rekrutację może być w tym panelu?
Bo jak mam otwartą rekrutację, to muszę przechodzić do profilu kandydata i tam
szukać i pobierać CV”. Makiety i decyzje D1–D5:
https://claude.ai/artifact/J6p2cjG5opYDpkh2P6iMaE — decyzja Artura: „tak na
wszystkie D1–D5, wdrażaj”. Reguła: `docs/claude/generator-cv/cv-w-procesie.md`,
sekcja „Pobieranie CV firmowego”.

## Co było nie tak (sprawdzone w kodzie przed zmianą)

- Sekcja „CV” panelu osoby nie miała pobierania CV firmowego.
- Za „Zweryfikowanym” link „Wysyłka CV do klienta” otwierał widok tylko do
  odczytu (`PanelSavedViews.tsx`) bez pobierania, ze zdaniem odsyłającym do
  profilu kandydata.
- Zdanie „CV firmowe: … — z etapu X, nie podpięte do bieżącego etapu” w kolorze
  akcentu wyglądało jak błąd.
- Profil → „Dokumenty” → „CV wysłane klientom” → „Pobierz” dawał surowy plik
  generatora: edycja CV etapu pisze tylko `branded_draft_html`, a lista nie
  podawała zatwierdzonej wersji. Klient mógł dostać CV bez poprawek po QC.

## Co weszło

| Decyzja | Zmiana | Pliki |
|---|---|---|
| D1 | „Pobierz Word” i „PDF” przy CV firmowym w sekcji „CV”, na każdym etapie, z wiersza etapu, na którym CV leży; bez zgody RODO wyłączone z powodem; wpis pobrania `surface=dock` | `PipelineCandidateDock.tsx`, `useStageBrandedCv.ts` (opcja `enabled`), `cv-download-intent.ts`, `cv_download_log.py` |
| D2 | Zdanie o CV bez „nie podpięte do bieżącego etapu”, kropka `bg-info`; „Edytuj CV” bez nazwy etapu; awaria odczytu z „Ponów” zamiast „Generuj CV” | `dock-cv-summary.ts`, `PipelineCandidateDock.tsx` |
| D3 | Zakładka „CV” za „Zweryfikowanym”: karta „CV do klienta” zamiast widoku tylko do odczytu; od „CV wysłane” `lockedAfterSend` (bez podmiany i generowania); link „CV do klienta: strony i wersje” poza „Zweryfikowanym” | `CvHandoffWorkbench.tsx`, `CvToClientCard.tsx`, `board-stages.ts` (`isAtClientColumn`), `pipeline-flow.ts` (`findPersonEntry`), `PersonWorkbenchTabs.tsx`; usunięty `PanelSavedViews.tsx` |
| D4 | `GET /api/cv-generator/generated` podaje CV etapu podpiętego dokumentu (`stage_cv_*`) i `job_title`; profil pobiera i podgląda CV etapu, surowy plik w „⋯”, „nieużyte w rekrutacji” przy dokumencie, którego nikt nie podpiął | `cv_generator_b2b.py`, `CandidateFilesTab.tsx`, `GeneratedCvPreviewModal.tsx` (`loadDocx`), `api.ts` |
| D5 | Grupa „CV wysłane klientom” → „CV dla klientów” | `CandidateFilesTab.tsx`, inwentarz, przewodnik Jarvisa `candidate.profile` |

Przewodniki Jarvisa `jobs.person` i `candidate.profile` poprawione i
przestemplowane. Inwentarze: `dock.cv-download` (nowy), `panel.saved-cv`
(przeniesiony do warsztatu), `panel.saved-cv-links-all-stages` (`removed_reason`:
widok zastąpiony kartą; linki dla klienta i tak wyłączone flagą),
`d.client_cv` (nowa nazwa). Bez migracji.

## Weryfikacja

- Front (vitest, lokalnie): `PipelineCandidateDock` + `dock-cv-summary` 122,
  `CvToClientCard` 49, `CvHandoffWorkbench` + `PersonWorkbenchTabs` 75,
  `board-stages` + `pipeline-flow` 112, inwentarz rekrutacji 344, pliki
  w profilu (5 plików) 154, harnessy 128 — wszystkie zielone; `npm run type-check`
  i ESLint zmienionych plików czyste.
- Backend: `ruff check` i `ruff format --check` czyste; `test_cv_download_log`
  bez bazy 13/13 (w tym `surface=dock`); `test_claude_md_index` +
  `test_screen_guides_freshness` 22/22. Testy z bazą
  (`test_cv_generated_list_stage_cv.py`, trasy pobrań) — w CI.
- Przeklikane w harnessach (`next dev`, Playwright, 1280×720):
  - `/preview/job-detail`, osoba na „Rozmowie z klientem” z CV na wierszu
    sprzed ruchu: sekcja „CV” — „CV firmowe: zatwierdzone 13.10.2026”,
    „Pobierz Word”, „PDF”, „Edytuj CV”, bez uciętego tekstu; link „CV do
    klienta: strony i wersje” → zakładka „CV” z kartą, zdaniem o etapie
    i blokadą, menu „⋯” = „Pobierz PDF”, „Historia wersji”;
  - `/preview/candidate-profile` → „Dokumenty”: „CV dla klientów · 4”, wiersz
    „CV rekrutacji Java Developer · szkic, zmienione 13.10.2026 · PL”, menu
    „Pobierz PDF”, „Plik z generatora (bez poprawek)”, „Otwórz w rekrutacji”;
  - `/preview/cv-to-client`: karta „Po „CV wysłane” — bez podmiany CV”.

## Poza zakresem i ryzyka

- Pobranie SZKICU etapu wymaga prawa zapisu (`preview-docx`,
  `CandidateWriteAccess`). Osoba z sekcją tylko do odczytu dostanie komunikat
  serwera; plik z generatora zostaje w „⋯”.
- Kopia CV z innej rekrutacji (`generated_document_id = NULL`) nie łączy się
  z dokumentem generatora — taki dokument pokazuje się jako „nieużyte
  w rekrutacji”, a CV etapu pobiera się w panelu osoby.
- Pobieranie na karcie Tablicy, nazwa pliku szkicu (`SZKIC_…`) i linki dla
  klienta — bez zmian.
- Liczby pobrań według miejsca (`cv_file_downloaded.surface`) przed zmianą —
  niepotwierdzone, odczyt produkcji wymaga zgody.

## Wiadomość dla Delivery Leada (po wdrożeniu, wysyła Artur)

> CV dla klienta pobierzesz teraz prosto z panelu osoby: w sekcji „CV”
> pod zdaniem „CV firmowe” są „Pobierz Word” i „PDF” — na każdym etapie, także
> po wysłaniu. To ten sam plik, który rekruter poprawił po QC. W profilu
> („Dokumenty” → „CV dla klientów”) „Pobierz” daje teraz też ten plik, a wersja
> z generatora bez poprawek jest w „⋯”.
