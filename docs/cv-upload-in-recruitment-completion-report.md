# Nowe CV w rekrutacji — raport

Gałąź `claude/cv-upload-accessibility-ccc62a`, 13.10.2026. Makiety i decyzje:
https://claude.ai/artifact/TMRtSJ7TDZt5hdbbijmdhd. Reguła: `docs/claude/rekrutacja-tablica/nowe-cv-w-rekrutacji.md`.
Bez migracji.

## Skąd zmiana

Dwa zgłoszenia rekruterów z 13.10.2026:

1. „Prośba, aby funkcja wgrania CV była na wierzchu… żeby ten kafelek do wgrywania CV był tutaj” (sekcja CV
   panelu osoby). Dziś: gdy osoba ma jakiekolwiek CV, wgrywania w panelu nie ma; trzeba wyjść do profilu
   (zakładka „CV i dokumenty”), a po wgraniu panel dalej pokazuje stare CV ze zgłoszenia — kopię w rekrutacji
   odświeżało tylko „⋯ → Aktualizuj snapshot” na profilu, a na etapach z Traffita dawało 404.
2. Okno „Dodaj z CV” przy osobie z bazy: „brakuje opcji dodaj tę osobę do rekrutacji i to CV na samą górę
   w jej profilu jako najnowsze”. Rekruter opisywał wersję sprzed #2144 (12.10); od #2144 okno dodawało CV
   i osobę do „Nowych”, ale żaden napis tego nie mówił, a identyczny plik, osoba w toku i zamknięta karta
   dalej nie miały wyjścia.

## Decyzje Artura (13.10.2026: „tak na wszystkie D1–D6, wdrażaj”)

| | Decyzja |
|---|---|
| D1 | Wariant A: panel osoby, podgląd po „Rozwiń” i okno „Dodaj z CV” |
| D2 | CV wgrane z rekrutacji zawsze jest głównym CV profilu |
| D3 | CV firmowe: ostrzeżenie i „Wygeneruj od nowa”, nic samo |
| D4 | „W profilu jest nowsze CV · Użyj w tej rekrutacji” |
| D5 | Osoba w toku: nowe CV zastępuje CV przy jej zgłoszeniu |
| D6 | Identyczny plik: dodać do rekrutacji i ustawić jako główne CV |

## Co się zmieniło

**Serwer**
- `POST /api/candidates/stages/{stage_id}/cv/original/upload` — główne CV profilu (ścieżka `/documents`)
  i kopia CV etapu w jednej transakcji; tylko PDF/DOC/DOCX; Sourcing + `CandidateWriteAccess` + członkostwo.
- `…/cv/original/refresh` zakłada brakujący wiersz CV etapu; polski komunikat 422.
- Kwarantanna tożsamości przywraca kopie etapu z odrzuconego pliku (`restore_stage_copies_after_quarantine`).
- `GET /api/candidates/{id}/pipelines` dostał `board_column` (reguła kolumny Tablicy).

**Front**
- `person/StageCvUpload.tsx` — hook, kafelek (`ds/FileDropZone`), `CvFileDropTarget` z nakładką.
- Dok: kafelek w sekcji CV, upuszczanie na cały panel, `DockCvFreshness` (nowsze CV, „AI czyta”),
  `CompanyCvStaleNotice` (D3), zdania „Oryginał CV” z pochodzeniem kopii.
- Podgląd po „Rozwiń”: „Wgraj CV” w pasku źródeł, upuszczanie, kafelek w pustym stanie.
- Okno „Dodaj z CV”: samo dodaje do „Nowych”; osoba z bazy → widok z listą „co się stanie” i decyzją według
  kolumny Tablicy; poprawka Spacji na polu pliku.
- `hooks/useCvToClientRows.ts` wyciągnięty z karty „CV do klienta”; `ClosedCardRestore` z `headline`.

## Odejścia od makiet

- Zamknięta karta: „Przywróć” po pierwszym kliknięciu, z powodem z serwera (reguła „rekruter ma zobaczyć
  zamknięcie przed przywróceniem”), zamiast jednego przycisku „Przywróć do „Nowych” z tym CV”.
- Osoba zatrudniona w tej rekrutacji: „Dodaj CV do profilu” bez podmiany kopii (makiety tego przypadku nie
  miały).
- Kwarantanna: zamiast ostrzeżenia z „Przywróć CV z profilu” serwer sam przywraca kopię etapu, panel mówi
  o tym w zdaniu „Oryginał CV”.

## Przeglądy

- **Bezpieczeństwo:** brak podatności do wykorzystania. Jeden problem integralności (kopia etapu zostawała
  z cudzym CV po kwarantannie) — naprawiony po stronie serwera z testami.
- **Kod:** trzy problemy blokujące, potwierdzone testem odtwarzającym i naprawione:
  1. nakładka łapała pliki z portali (okno generatora, podgląd w lewej strefie — podwójne wgranie) i z pola
     notatki w Screeningu → tylko zdarzenia z własnego DOM-u, pole pliku w środku dostaje plik samo;
  2. okno decydowało o podmianie według `is_terminal` (lista rezerwowa „w toku”, zatrudniony „zamknięty”) →
     `board_column` z serwera;
  3. „W profilu jest nowsze CV” obiecywało plik, którego serwer nie skopiuje (główne CV w TXT) → reguła
     `get_current_cv`.

## Weryfikacja

- Backend lokalnie (bez bazy): ruff check/format, kontrakty sekcji i zakresu rekrutacji, wzorzec uprawnień
  (`candidate_stage_cv.json` +1 trasa). Testy z Postgresem (`test_stage_cv_upload.py`, 9 przypadków) —
  w CI.
- Front: vitest zmienionych plików (476 testów) i pełny zestaw (912 plików; jedyna czerwień — strażnik granic
  paczek — naprawiona), `tsc --noEmit` czysty.
- Przeklikane w harnessie `/preview/job-detail` przy 1280 × 720 i 1280 × 650: kafelek w doku, nakładka nad
  całym panelem, stan po wgraniu („wgrane w rekrutacji”, „AI czyta”, „Wgraj nowe CV”, „Pokaż CV oryginalne”),
  przycisk i kafelek w podglądzie po „Rozwiń”.

## Po scaleniu

- `/api/health` → SHA z maina; `POST …/cv/original/upload` bez tokenu → 401 (trasa istnieje).
- Na zalogowanej produkcji tylko obejrzenie kafelka i okna — wgranie pliku prawdziwej osobie wymaga zgody.
