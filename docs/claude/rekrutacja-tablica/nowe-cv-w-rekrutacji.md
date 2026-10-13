# Nowe CV w rekrutacji — kafelek w panelu osoby i „Dodaj do rekrutacji z tym CV” (13.10.2026)
<!-- indeks: „Wgraj nowe CV” w sekcji CV panelu osoby i upuszczenie pliku na panel, trasa `…/cv/original/upload` (główne CV + kopia etapu w jednej transakcji, tylko PDF/DOC/DOCX), „W profilu jest nowsze CV · Użyj w tej rekrutacji”, „CV firmowe powstało z poprzedniego CV”, kwarantanna, okno „Dodaj z CV” przy osobie z bazy (Nowi, podmiana, przywrócenie, identyczny plik) -->

Dwa zgłoszenia rekruterów z 13.10.2026. Pierwsze: w panelu osoby nie dało się
wgrać CV, gdy osoba miała już jakiekolwiek CV — trzeba było wyjść do profilu,
a po wgraniu panel dalej pokazywał stare CV ze zgłoszenia. Drugie: okno „Dodaj
z CV” przy osobie z bazy nie dawało „dodaj do rekrutacji i CV na górę profilu”.
Makiety i decyzje D1–D6: https://claude.ai/artifact/TMRtSJ7TDZt5hdbbijmdhd,
raport `docs/cv-upload-in-recruitment-completion-report.md`.

## Reguła (decyzje Artura D1–D6)

- **Jedna akcja „nowe CV w rekrutacji”.** Plik staje się głównym CV profilu
  (AI odświeża profil w tle, jak przy każdym głównym CV) i od razu kopią CV
  etapu („Oryginał CV”), z której biorą podgląd, QC i generator. Stare pliki
  zostają w profilu — nic nie kasujemy. W rekrutacji nowe CV jest zawsze
  główne (D2); wersja obok (np. angielska) dalej idzie przez zakładkę
  „CV i dokumenty”.
- **Trasa** `POST /api/candidates/stages/{stage_id}/cv/original/upload`
  (`api/candidate_stage_cv.py`): te same kroki co `POST /api/candidates/{id}/documents`
  z `is_primary` (deduplikacja po SHA ustawia też identyczny plik jako główny,
  odczyt AI i bramka tożsamości w tle), a potem `refresh_original_cv_snapshot(source="manual_upload")`
  — w jednej transakcji. Dwa żądania z przeglądarki zostawiały CV w profilu
  bez kopii w rekrutacji. Wszystkie odmowy padają przed zapisem pliku na dysk
  (`_ingest_candidate_cv_file`), którego rollback nie cofa.
- **Tylko PDF, DOC, DOCX** (415 z polskim zdaniem). `get_current_cv` widzi
  wyłącznie te rozszerzenia, więc ODT/RTF/TXT dałyby kopię etapu ze starszego
  pliku. Inne formaty dalej przez profil.
- **Bramka:** `CandidateWriteAccess`, członkostwo w rekrutacji
  (`_load_csv_for_stage`) i sekcja Sourcing jak przy `/documents` — trasa
  ustawia główne CV profilu. Na froncie kafelek, przycisk i nakładka tylko przy
  `!readOnly && useCapability("candidate.document.manage")`; bez prawa zostaje
  link „Dodaj CV w profilu kandydata ↗”.
- **„Aktualizuj snapshot” = „Użyj w tej rekrutacji”** (`…/cv/original/refresh`).
  Trasa zakłada brakujący wiersz CV etapu (`create_missing=True`) — do tej daty
  etapy z importu Traffita dostawały 404. `original_snapshot_source`:
  `manual_upload` (wgrane z rekrutacji), `manual_refresh` (podmienione z profilu),
  `quarantine_restore` (patrz niżej).
- **Kwarantanna sprząta też kopie etapu** (przegląd bezpieczeństwa 13.10.2026).
  Bramka tożsamości biegnie po zapisie; gdy uzna plik za CV innej osoby, oddaje
  główne CV poprzedniemu plikowi, a `restore_stage_copies_after_quarantine`
  (`candidate_stage_cv_service.py`, wołane z `_clear_quarantined_cv_projection`)
  daje każdej kopii etapu z tym SHA bieżące CV osoby albo zostawia ją bez pliku.
  Bez tego cudze CV zostawało w podglądzie, w pobraniu i w przeglądzie zgodności
  jako „oryginał” tej osoby. Panel mówi: „Oryginał CV: poprzednie CV · … —
  wgrane nie pasowało do tej osoby”.

## Panel osoby (`PipelineCandidateDock.tsx`, sekcja CV)

- Kafelek `StageCvUploadTile` (`person/StageCvUpload.tsx`, na `ds/FileDropZone`)
  pod listą stanu CV: „Wgraj nowe CV”, a przy braku CV „Wgraj CV” zamiast linku
  do profilu.
- **Upuszczenie pliku w dowolnym miejscu panelu** (`CvFileDropTarget` na korzeniu
  doku) wgrywa CV także przy zwiniętej sekcji. Nakładka reaguje tylko na
  `dataTransfer.types` z „Files” — Tablica przesuwa karty przez
  `@hello-pangea/dnd` (zdarzenia wskaźnika), a przeciągnięty tekst czy link
  nie ma typu „Files”. Dwie granice (przegląd kodu 13.10.2026):
  - tylko zdarzenia z DOM-u obszaru (`root.contains(target)`). W Reakcie
    zdarzenia z portali wędrują do przodków: plik Championa z okna generatora,
    plik Word z „Użyj innego CV” albo upuszczenie na podgląd w lewej strefie
    (drugi `CvFileDropTarget`) wgrałyby się jako CV — także dwa razy;
  - pole pliku w środku (`ds/FileDropZone`, znak `[data-drag-over]`: kafelek
    CV, „Wgraj plik” notatki w Screeningu) dostaje plik samo. Nakładka jest
    samą grafiką (`pointer-events-none`) i znika nad takim polem.
- Nic nie dochodzi do paska osoby — reguła z 09.10.2026 (`duzy-podglad-po-lewej-stronie-panelu-osoby.md`).
- **`DockCvFreshness.tsx`:**
  - „W profilu jest nowsze CV” (D4): plik, który „Użyj w tej rekrutacji”
    naprawdę skopiuje (`stageCopySource` = reguła `get_current_cv`: tylko
    PDF/DOC/DOCX, najpierw główne), młodszy od kopii etapu o co najmniej minutę
    (`newerProfileCv`) — CV z poczty, z profilu albo z innej rekrutacji. Główne
    CV w TXT nie wywołuje ramki, bo do kopii nie trafi. Inne rekrutacje osoby
    nie podmieniają się same, bo CV mogło już pójść do innego klienta. Lista
    plików CV jest dlatego pobierana także obok kopii ze zgłoszenia, ale tylko
    dla osoby z prawem do wgrania.
  - „Profil: AI czyta nowe CV” przez 3 minuty po wgraniu; szczegóły kandydata
    odpytywane co 15 s do zmiany `cv_parsed_at`.
- **`recruitment/CompanyCvStaleNotice.tsx` (D3):** szkic CV firmowego starszy
  niż kopia podmieniona ręcznie (`companyCvStale`, początek szkicu z
  `companyDraftSince`) → „Wygeneruj od nowa” i „Zostaw obecne” (pamięć per etap
  i data kopii). Generator nie podmienia istniejącego szkicu
  (`attach_as_stage_draft`), więc gotowa nowa wersja pojawia się w tej samej
  ramce jako „Użyj nowej wersji” (`branded.selectGenerated`, wiersze przez
  `hooks/useCvToClientRows.ts`, wspólny z kartą „CV do klienta”). Zatwierdzone
  CV i wysłane linki bez zmian; nic nie generuje się samo.

## Podgląd po „Rozwiń” (`CandidatePreviewPane.tsx`)

Prop `cvUpload` (podgląd w panelu i w Screeningu): „Wgraj CV” w pasku źródeł,
upuszczenie pliku na podgląd i kafelek w pustym stanie. Po wgraniu podgląd
przechodzi na „CV oryginalne”. Przegląd DL i edytor CV go nie dostają.

## Okno „Dodaj z CV” w rekrutacji (`AddCandidateFromCVModal.tsx`)

- Okno samo dodaje osobę do „Nowych” (`proposals/bulk`, `quick_add`) — także
  nową osobę z CV — i pokazuje wynik w sobie; strona podaje tylko `job`,
  `onChanged` i `onOpenPerson` (`?candidate=` przez `useUrlWriter`).
- **Osoba z bazy** (ten sam e-mail albo identyczny plik): „{osoba} już jest
  w bazie”, lista „co się stanie” i jeden główny przycisk. Karta w tej
  rekrutacji z `GET /api/candidates/{id}/pipelines` — pole `board_column` to ta
  sama reguła kolumny co Tablica i `proposals/bulk` (`board_column_for`).
  `is_terminal` się do tego nie nadaje: „Lista rezerwowa” nie jest etapem
  końcowym, a jest zamknięta; zatrudniony jest etapem końcowym, a nie jest
  zamknięty. Karta jest czytana od nowa przy kliknięciu:
  - brak karty → CV jako główne (`attachCvFormData`) i „Nowi”;
  - karta w toku → „Podmień CV w tej rekrutacji” = trasa uploadu etapu (D5);
  - zatrudniony → „Dodaj CV do profilu”, kopia przy zgłoszeniu bez zmian;
  - zamknięta karta (także lista rezerwowa) → CV na górę profilu, potem
    „Przywróć” (`ClosedCardRestore`) z powodem z serwera. Nie jednym kliknięciem:
    rekruter ma zobaczyć, kto i kiedy zamknął kartę
    (`dodaj-do-rekrutacji-zamknieta-karta.md`);
  - `proposals/bulk` mówi `already_in_job`, choć odczyt karty jej nie znał →
    CV tylko w profilu; kopię podmienia ramka D4 w panelu, okno nie zgaduje;
  - inny powód (czarna lista, weto HM) → zdanie w oknie, bez widoku sukcesu.
- **Identyczny plik** (D6): „Dodaj do rekrutacji” ustawia plik jako główne CV
  (deduplikacja po SHA). Drugi profil z tym samym plikiem tylko z linku
  „To CV innej osoby? Załóż osobny profil” (`force=true`).
- Spacja na polu pliku otwiera wybór pliku (do tej daty porównanie z pustym
  napisem).

## Czego nie robimy

- Nie generujemy CV firmowego automatycznie po nowym CV.
- Nie podmieniamy kopii CV w innych rekrutacjach osoby.
- Nie wgrywamy przez upuszczenie pliku na kartę Tablicy (wariant C odłożony).

Harness: `/preview/job-detail` trzyma kopie CV etapu po wgraniu w pamięci strony.
