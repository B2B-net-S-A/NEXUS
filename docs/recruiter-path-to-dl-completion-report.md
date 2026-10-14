# Droga rekrutera do Delivery Leada — raport z wdrożenia D1–D7 (14.10.2026)

Makiety i analiza: https://claude.ai/artifact/89gzGUHT22CXbGkTBtC4pw. Decyzja Artura
14.10.2026: „tak na wszystkie D1–D7, wdrażaj”. Reguła zbiorcza:
`docs/claude/rekrutacja-tablica/droga-rekrutera-do-dl.md`.

## Cel

Mniej kliknięć i żadnego czekania bez sygnału od dodania osoby do przekazania CV
Delivery Leadowi. Przykład z makiet (osoba z „Propozycji z bazy”, 5 pytań, 3 uwagi
QC): 24 → 15 kliknięć; czekanie na CV i propozycje AI dzieje się w tle.

## Co weszło

| Decyzja | Zmiana | Gdzie |
|---|---|---|
| D1 | Dopasowanie liczy się samo dla widocznych wierszy; „+ Dodaj” w wierszu z „Cofnij” (do 15 min propozycja wraca na listę); do 3 plakietek wymagań; „Szukaj ręcznie” jako zakładka okna | `AddCandidatesPanel.tsx`, `pick-list.tsx`, `reason-chips.ts`, `job_proposals.reopen_after_quick_undo` |
| D2 | Okno stawki przy ruchu na „Zweryfikowany” tylko bez stawki etapu; pole stawki z cytatu notatki / karty / „Stawka od”; poprawka zapisu stawki z karty | `usePipelineMove.tsx`, `lib/screening-form.ts`, `ScreeningFullForm.tsx`, `rate_hints.card_raw` |
| P2 | Formularz od razu (bez „Zacznij screening” i „Biorę — 12 h”), zwinięty blok „Co już wiemy”; rezerwacja 12 h przy pierwszym zapisie | `ScreeningWorkbench.tsx`, `BeforeCallProfile.tsx`, `screening_form._claim_on_save` |
| D3 | „Zapisz notatkę i wypełnij formularz” — notatka zapisuje się raz (`note_import.note_id`) | `PipelineCandidateDock.tsx`, `lib/note-fill-channel.ts`, `screening_form._reused_note` |
| P3 | Po „Zapisz i przekaż dalej” panel na „CV” z postępem (CV / źródło gotowego CV / powód pominięcia → QC) i „Następna w Screeningu” | `KanbanBoardV2.tsx` (`onForwarded`), `CvToClientCard.tsx` |
| D4 | Dzwonek `cv_ready` („CV gotowe do sprawdzenia” z wynikiem QC albo „Automat nie zrobił CV” z powodem) — migracja 0440 + lustro w `entrypoint.sh` | `cv_auto_generate.py` |
| D5 | Po automacie QC i propozycje poprawek AI od razu; edytor i okno QC ładują propozycje same | `cv_auto_generate._prefetch_fixes`, `CvEditorIssues.tsx`, `CvQcDialog.tsx` |
| D6 | Stopka edytora: „Uwaga dla Delivery Leada”, „Zapisz i przekaż do DL”, „Przekaż mimo uwag…”; uwaga na górze przeglądu DL | `CvEditorHandoffBar.tsx`, `CvHandoffWorkbench.tsx`, `dl_review.recruiter_handoff_remark`, `DlReviewPanel.tsx` |
| D7 | Strzałka bez braków przesuwa od razu z „Cofnij” (ruch odroczony o 10 s); brak CV firmowego z „Zweryfikowany” = brak | `usePipelineMove.deferMove`, `board-card-badges.knownForwardGap` |
| — | „Czeka u Delivery Leada od …” zamiast martwego „Przekaż Delivery Leadowi”; dzwonek-zadanie „QC CV do poprawy”; plakietki „CV w przygotowaniu…” / „CV gotowe · N do poprawy” | `move-primary.ts`, `MoveNextDialog.tsx`, `cv_qc.run_after_move` |

Gotowe CV i upload zostają (pytanie Artura 14.10): wybór CV z profilu, „Użyj innego
CV”, wgranie CV firmowego z dysku i „Wgraj nowe CV” działają jak wcześniej; QC liczy
się dla każdego źródła, a automat dalej pomija parę z CV.

## Sprawdzone

- Front: `npm run type-check` czysto; eslint 82 zmienionych plików czysto; vitest
  zmienionych plików: tablica 270, źródła 164 + 404, formularz 232 + 429, edytor/DL
  316, strażnicy (inwentarz, harnessy) 402 — wszystkie zielone.
- Backend: `ruff check` / `ruff format --check` czysto; testy bez bazy zielone;
  testy z Postgresem (`test_recruiter_cv_path.py`, `test_screening_form*.py`,
  `test_quick_undo_returns_proposal.py` i reszta) — pełny bieg CI na gałęzi.
- Harnessy przeklikane w oknie 1280 × 720: `/preview/screening-form` (formularz ze
  stawką widoczny bez przewijania), `/preview/pipeline-v4` (plakietki CV),
  `/preview/cv-editor?state=handoff|handoff-blocking`, `/preview/dl-review` (uwaga
  rekrutera), `/preview/job-detail?sources=base|manual`; test e2e
  `responsive-preview.spec.ts` „profil przed telefonem…” zielony.
- Inwentarz funkcji: 13 nowych wpisów, „Zacznij screening” zastąpiony blokiem „Co już
  wiemy”; przewodniki Jarvisa `jobs.board` i `jobs.person` przejrzane i przestemplowane.

## Ryzyka i rzeczy do obserwacji

- Koszt AI: każde auto-CV z uwagami QC (i CV z innego źródła na „Zweryfikowany” lub
  dalej) to jedno wywołanie poprawek (`dz_review`), z pamięcią per treść.
- Dzwonek „QC CV do poprawy” bywa częsty (13.10: 8 z 15 par w „QC CV” miało uwagi);
  mailem idzie jak „CV wróciło do poprawy” (polityka maili w Ustawieniach).
- Utracony wykonawca generacji (pętla odzyskiwania oznacza dokument jako nieudany bez
  haka) nie wysyła „Automat nie zrobił CV” — luka sprzed tej zmiany.
- Ruch odroczony: zamknięcie karty przeglądarki w ciągu 10 s pyta o wyjście; odmowa
  serwera po 10 s cofa kartę i pokazuje powód.
