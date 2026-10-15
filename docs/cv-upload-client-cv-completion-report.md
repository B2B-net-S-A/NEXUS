# Gotowe CV do klienta z kafelka „Wgraj nowe CV” — raport

Gałąź `claude/cv-upload-confirmation-efcf15`, 15.10.2026. Makiety i decyzje:
https://claude.ai/artifact/U6wAqaH4nqF55RF9RiWPP2. Reguła:
`docs/claude/rekrutacja-tablica/nowe-cv-w-rekrutacji.md` (sekcja „Gotowe CV do klienta z kafelka”).
Bez migracji.

## Skąd zmiana

Zgłoszenie rekrutera: „Jak wgrywamy CV, to ma to być równoznaczne z tym, że jest to CV do użycia w danej
rekrutacji. Bez potrzeby kolejnego przeklikania”.

Rekruterzy wgrywali kafelkiem w panelu osoby gotowe CV do klienta („B2B_Stanowisko_Imię_Nazwisko.docx”).
`POST …/stages/{id}/cv/original/upload` robił z pliku główne CV profilu (AI czytało profil z wersji
firmowej) i „Oryginał CV”, a CV do klienta zostawało stare. Karta „CV do klienta” pokazywała wtedy pasek
„Ta osoba ma już gotowe CV” i kazała kliknąć „Użyj tego CV” i „Zastąp”.

Odczyt produkcji 15.10.2026 (tylko do odczytu, same liczby):

- para ze zgłoszenia: wgranie 16:44:42, „Użyj tego CV” 16:44:55;
- od 13.10 15 z 37 wgrań w panelu to pliki „B2B” (7 osób);
- od 12.10 16 z 17 importów pliku z profilu do CV do klienta to plik wgrany przez tę samą osobę ≤ 30 min
  wcześniej;
- 4 z 11 par z wgranym gotowym CV zostały ze szkicem generatora, wszystkie już na „CV wysłane” albo dalej;
- 27 plików „B2B” wgranych od 13.10 jest głównym CV profilu;
- ten sam plik trafił 30 min później do panelu innej osoby — zatrzymała go tylko bramka tożsamości.

## Decyzje Artura (15.10.2026: „D1 A, D2 A, D3 A — rób PR”)

| | Decyzja |
|---|---|
| D1 | CV do klienta po nazwie pliku: „B2B…” albo wzór nazwy klienta rekrutacji |
| D2 | Nieprzejrzane auto-CV podmieniamy bez pytania; poprawione, wybrane albo zatwierdzone — po pytaniu |
| D3 | Naprawa profili z „B2B” jako głównym CV od 13.10, najpierw na sucho |

## Co się zmieniło

Serwer:

- `services/client_cv_upload.py`: rozpoznanie pliku (`looks_like_client_cv`, wzór klienta przez
  `client_filename_pattern`), sprawdzenie osoby z nagłówka CV (`other_person_name`), predykat D2
  (`is_untouched_auto_cv`) i odczyt wgrania do „Cofnij” (`last_upload_if_current`).
- `upload_original_cv`: pola `mode` i `replace_client_cv`, odpowiedź `StageCvUploadResponse` z `outcome`
  (`original` | `client_cv` | `client_cv_kept`). Ścieżka CV do klienta (`_upload_client_cv`) pisze szkic
  na wierszu CV pary jak karta, plik w profilu tylko przy istniejącym głównym CV, bez odczytu AI.
  „Cofnij” (`_undo_client_cv_upload`) przywraca auto-CV albo pusty stan.
- Blokada po „CV wysłane” na serwerze dla trzech tras „Użyj innego CV” (wcześniej tylko w interfejsie).
- `_import_docx_as_draft` rozdzielone na konwersję i zapis bez commitu (`_write_imported_draft`).
- `restore_stage_copies_after_quarantine` dostało parametry etykiety (domyślne bez zmian).
- CLI `python -m app.cli.client_cv_primary_repair` (D3).

Front:

- `StageCvUpload.tsx`: trzy wyniki, pytanie „Zastąpić CV do klienta?” (`useConfirmV2`), komunikat
  z „Cofnij”, krótszy podpis kafelka. Dok i podgląd renderują pytanie; podgląd przechodzi na „CV firmowe”.
- `AddCandidateFromCVModal.tsx`: ekrany wyniku `client_cv` i `client_cv_kept`.
- `dock-cv-summary.ts`: zdanie dla `client_cv_repair`; ramka „W profilu jest nowsze CV” nie podsuwa pliku
  CV do klienta jako oryginału.
- Harness `/preview/job-detail`: odpowiedź `client_cv` dla pliku „B2B_…docx” i stan CV do klienta w pamięci.

## Odejścia od makiet

- W pytaniu przy poprawionym CV przyciski to „Zastąp” / „Nie podmieniaj” (nic nie wgrywamy), a nie
  „Zostaw obecne” z zapisem pliku do profilu. Jedno kliknięcie mniej do wyjaśnienia, a plik można wgrać
  ponownie.
- Podpis kafelka w panelu: „Plik „B2B_…” = od razu CV do klienta”. Pełne zdanie z makiety nie mieści się
  w jednej linii doku przy 1280 px i ucinało „CV do klienta”. Pełne zdanie zostaje w nakładce przy
  upuszczaniu pliku.
- Osoba bez głównego CV: plik nie trafia do profilu (stałby się „bieżącym CV”). Makieta tego nie pokazywała.

## Przeglądy

Przegląd kodu (serwer) — trzy problemy blokujące, poprawione:

- Nowa blokada po „CV wysłane” na `select-stage-cv` zmieniała wynik istniejącego testu
  `test_copy_is_refused_for_foreign_same_or_legacy_sources` (źródło w tej samej rekrutacji stało na
  „CV wysłane”, więc 409 zamiast 422). Sito PR-a tego pliku nie wybiera — wypadłoby w kolejce. Pomocnik
  `_source_cv` dostał etap; ten przypadek stoi przed wysyłką.
- Test D3: plik bez `uploaded_at` (kolumna bez domyślnej wartości) wypadał z planu.
- CLI D3: następca wybierany tylko po dacie (bez „cv przed other”, NULL pierwszy przy DESC) i wybór pliku
  bez warunku `.docx`. Teraz kolejność jak `current_cv_ordering`, wybór przez `looks_like_client_cv`,
  w raporcie rodzaj następcy.

Przegląd bezpieczeństwa — bez obejścia uprawnień, IDOR i danych osobowych w logach; cztery słabsze uwagi,
poprawione: `--until` w CLI (pliki wskazane jako główne po wdrożeniu nie są ruszane), „Cofnij” po
„CV wysłane” nie przywraca CV do klienta, świeży odczyt wiersza pod blokadą w „Cofnij”, stan karty
czytany po blokadzie wiersza CV. Nazwisko z nagłówka w komunikacie 422 przycięte do 80 znaków.

## Weryfikacja

- `ruff check app/` i `ruff format --check app/` (ruff 0.15.22 jak w CI): czysto.
- `tests/test_client_cv_upload_rules.py` (bez bazy, lokalnie): 28 testów zielonych.
- Testy z bazą (`test_stage_cv_upload.py`, `test_stage_cv_copy.py`): zebrane lokalnie (41), uruchamia CI.
- Front: `npx vitest run --no-file-parallelism` na zmienionych testach i strażnikach — 684 testy
  zielone (StageCvUpload, fix48, CandidatePreviewPane, AddCandidateFromCVModal, dock-cv-summary,
  PipelineCandidateDock, DockCvFreshness, recruitment-feature-parity, harness-seeds, fictional-people,
  heavy-bundle-boundaries, harness-fictional-data); `tsc --noEmit` exit 0.
- Przeklikane w `/preview/job-detail`, okno 1280 × 720: panel osoby → sekcja CV → upuszczenie
  „B2B_…docx” → „CV firmowe: szkic · zmienione 15.10.2026”, „Oryginał CV” bez zmian, komunikat
  „CV do klienta z pliku … · Cofnij”; „Cofnij” → „CV firmowe: brak”, plik jako „Oryginał CV”, komunikat
  „Cofnięte…”. Pytanie 409 sprawdzone testem komponentu (harness go nie symuluje).

## Po scaleniu

1. Po oknie 19:00–07:00: `/api/health` → `version` = SHA z maina ze zmianą.
2. D3 na sucho w kontenerze backendu:
   `python -m app.cli.client_cv_primary_repair --until <chwila wdrożenia ISO ze strefą>` → liczby do Artura.
3. Po OK Artura: to samo z `--apply --expected N`, potem paragon `client_cv_primary_repair_2026_10`.
4. Następnego dnia odczyt produkcji: aktywności `branded_cv_uploaded_in_recruitment` i brak nowych
   `branded_cv_imported_from_document` zaraz po wgraniu tego samego pliku.
