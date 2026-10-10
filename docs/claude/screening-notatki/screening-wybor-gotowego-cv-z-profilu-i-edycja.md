# Screening: wybór gotowego CV z profilu i edycja (09.10.2026)

Pomiar na produkcji 09.10.2026: z 50 osób w „Nowych”/„Screeningu” 34 miały
w profilu plik Word „…B2B…”, 13 — CV z generatora (9 z innej rekrutacji), a
podgląd „CV firmowe” mówił tylko „jeszcze nie powstało”. Decyzja Artura:
do wyboru są CV z generatora (także z innych rekrutacji tej osoby) i pliki
Word „B2B”; PDF-y poza zakresem. Raport: `docs/screening-cv-pick-completion-report.md`.

- **Wybór jest w podglądzie screeningu** (`screening-form/StageCvPicker.tsx`,
  włączany propem `cvActions` w `CandidatePreviewPane`; reguła opcji
  `lib/stage-cv-options.ts`). Przegląd DL i zakładki CV/Rozmowy nie podają
  `cvActions` i zostają tylko do odczytu. „Wybierz” podpina SZKIC CV firmowego,
  potem „Edytuj” (ten sam `CVBrandedEditModal`) i „Zmień CV” (potwierdzenie
  przed zastąpieniem szkicu). Plik w profilu i źródłowe CV zostają nietknięte.
- **Dwie trasy, jeden zapis szkicu** (`candidate_stage_cv._write_stage_draft`):
  `select-generated` przyjmuje CV tej samej OSOBY (do 09.10 tej samej
  rekrutacji), nowa `select-document` wczytuje plik Word. Obie zakładają
  brakujący wiersz `candidate_stage_cvs` (`create_missing`) — etapy z importu
  Traffita go nie mają (5 837 z 5 958 wierszy „Nowi”/„Screening”).
- **CV spoza generatora TEJ rekrutacji to kopia odłączona**
  (`generated_document_id = NULL`, `branded_render_metadata.source` =
  `document` | `generated_other_job`): nazwa pliku i wymóg zgody RODO liczą się
  z klienta tej rekrutacji (`candidate_stage_cv_service.detached_copy_settings`),
  zrzut zgody i reguły klienta źródłowego nie jadą z kopią. Kopia CV z innej
  rekrutacji dostaje w nagłówku tytuł TEJ rekrutacji i traci linię „Rozważany
  na stanowisko” (tytuł źródłowy bywa numerem zapytania innego klienta); CV
  blind ma w nazwie pliku „Kandydat”, nie nazwisko. Klient z wymogiem
  zrzutu zgody = 422 `consent_client_needs_generator` (kopii nie da się dziś
  dołączyć zgody, więc pobranie byłoby zablokowane na stałe); front wyszarza
  takie opcje. Nie przywracaj powiązania z dokumentem generatora dla kopii
  z innej rekrutacji — blokada pobrania i pakiet czytają wtedy cudzego klienta.
- **Import Word → edytor: `services/cv_docx_import.py`**, bez AI. Jest
  odwrotnością układu `render_approved_docx`: sekcje po tytułach, tabela
  edukacji jako akapit, blok „daty / Nazwa firmy: / Stanowisko:” jako rola ze
  znacznikami `data-cv-section`; czego nie rozpozna, zostaje akapitem albo
  punktem. Czyta wszystkie runy akapitu (hiperłącza, pola formularza Worda,
  wstawki śledzenia zmian), klauzulę zgody bierze z pola tekstowego szablonu,
  a gdy jej nie ma — dokłada standardową w języku pliku. Plik jest
  niezaufany (formularz kariery, import), a konwersja biegnie w procesie
  aplikacji: komórki tabeli czytaj z `tr.tc_lst`, nigdy `row.cells` (powtarza
  komórkę `gridSpan` razy — liczba z pliku), i trzymaj limity `MAX_LINES`
  / `MAX_TABLE_DEPTH`. Pomiar na 200
  plikach z produkcji: 200 wczytanych, 0 zgubionych akapitów (także po
  ponownym renderze do Worda), sekcje rozpoznane w 198, role w 182.
  Zmieniasz import albo renderer — sprawdź obieg w `test_cv_docx_import.py`
  i powtórz pomiar na prawdziwych plikach (same liczby, bez treści).
- **`CVBrandedResponse.source`** (`generator` | `document` | `legacy`) —
  `stageCvStatus` traktuje `document` jak zwykły szkic, nie stary szablon.
- **Auto-CV po „Zweryfikowany” pomija parę, która ma już CV firmowe**
  (`cv_auto_generate._enqueue`, powód `pair_cv_exists`): nowy dokument podpięty
  do nowego wiersza etapu przykryłby CV wybrane albo wygenerowane wcześniej
  (nowszy etap wygrywa w `_branded_cv_summary_for_pair`) i kosztował drugą
  generację.
- Kontrola AI przy zatwierdzaniu kopii odłączonej daje „niedostępna”
  (`no_generated_source`) — istniejące zachowanie, nie błąd.
- Harness `/preview/screening-form?state=cvpick|cvconsent|cvready`.
