# Screening: wybór gotowego CV z profilu i edycja — raport

Gałąź `claude/screening-cv-selection-edit-9fab1f`, 09.10.2026. Bez migracji bazy.

## Skąd zmiana

Zgłoszenie: „screening → możliwość wyboru CV z gotowych już w profilu kandydata i następnie możliwość edycji”.

W screeningu podgląd „CV firmowe” mówił tylko „CV firmowe jeszcze nie powstało — generuje się po przekazaniu osoby na
«Zweryfikowany»”. CV firmowe rekrutacji dało się zacząć wyłącznie od CV z generatora dla tej samej rekrutacji.

Pomiar na produkcji 09.10.2026 (tylko odczyt), 50 osób w „Nowych”/„Screeningu” w opublikowanych rekrutacjach
(ostatnie 30 dni):

| Co osoba ma w profilu | Osób |
|---|---|
| plik Word „…B2B…” | 34 |
| CV z generatora z innej rekrutacji | 9 |
| CV z generatora z tej rekrutacji | 4 |

W bazie: 16 008 plików DOCX „B2B”, ok. 750 PDF „B2B”, 274 gotowe CV z generatora, 35 CV firmowych etapu.

## Decyzja Artura (09.10.2026)

Do wyboru są CV z generatora (także z innych rekrutacji tej osoby) i pliki Word „B2B”. PDF-y poza zakresem.

## Co się zmieniło

### Ekran

- Screening → podgląd → „CV” → „CV firmowe”. Gdy para nie ma CV firmowego, jest lista „Wybierz gotowe CV z profilu”:
  „Z generatora” (klient, język, data, autor; „ta rekrutacja” / „inna rekrutacja” / „bez rekrutacji”) i „Pliki Word
  z profilu” (pliki „…B2B….docx”, z „Podglądem”). Przełącznik pokazuje liczbę opcji: „CV firmowe · wybierz (3)”.
- „Wybierz” podpina CV jako szkic CV firmowego tej rekrutacji. Plik w profilu i źródłowe CV zostają bez zmian.
- Po wyborze: podgląd w szablonie firmowym, „Edytuj” (istniejący edytor) i „Zmień CV” (ta sama lista, zastąpienie
  szkicu po potwierdzeniu).
- Klient z wymogiem zrzutu zgody RODO (dziś PKO BP): opcje spoza generatora tej rekrutacji są wyszarzone ze zdaniem
  „wygeneruj CV w generatorze”.
- Zamknięta rekrutacja i zakończony proces: bez listy i bez przycisków. Przegląd DL i zakładki CV/Rozmowy bez zmian.

### Backend

- `services/cv_docx_import.py` (nowy): plik Word → HTML edytora, bez AI.
- `api/candidate_stage_cv.py`: `select-generated` przyjmuje CV tej samej osoby z dowolnej rekrutacji; nowa trasa
  `POST …/cv/branded/select-document`; obie zakładają brakujący wiersz CV etapu; wspólny zapis szkicu
  `_write_stage_draft`; `CVBrandedResponse.source`.
- `services/candidate_stage_cv_service.detached_copy_settings`: nazwa pliku i wymóg zgody z klienta tej rekrutacji.
- `services/cv_auto_generate.py`: auto-CV po „Zweryfikowany” pomija parę, która ma już CV firmowe (`pair_cv_exists`).
  Zamyka też przypadek sprzed zmiany: ręczna generacja w „Nowych” + ruch dawały drugą płatną generację, która
  przykrywała pierwszą.

### Kopia odłączona

CV, które nie powstało w generatorze dla tej rekrutacji (plik Word, CV z innej rekrutacji), nie ma powiązania
z dokumentem generatora:

- nazwa pliku i wymóg zgody liczą się z klienta tej rekrutacji,
- zrzut zgody z cudzego CV nie jest przenoszony,
- kontrola AI treści przy zatwierdzaniu daje „niedostępna” (brak źródła generacji).

## Pomiar importu na prawdziwych plikach

Skrypt uruchomiony w kontenerze backendu na produkcji, tylko odczyt, 200 plików DOCX „B2B” (60 najnowszych + 140
losowych). Wypisywał wyłącznie liczby.

| Miara | Wynik |
|---|---|
| wczytane | 200 z 200 |
| akapity źródła nieobecne w HTML edytora | 0 w każdym pliku |
| akapity źródła nieobecne po ponownym renderze do Worda | 0 w każdym pliku |
| render do Worda bez błędu | 200 z 200 |
| pliki z rozpoznanymi sekcjami | 198 (3–6 sekcji w 194) |
| pliki z rozpoznanymi stanowiskami | 182 |
| czas importu | średnio 0,07 s, najdłużej 0,31 s |

W 18 plikach bez rozpoznanych stanowisk doświadczenie zostaje zwykłymi akapitami i punktami (tekst i pogrubienia
zachowane, bez linii między stanowiskami).

## Weryfikacja

| Część | Stan | Dowód |
|---|---|---|
| Import Word | zielone | `pytest tests/test_cv_docx_import.py` — 13 testów; pomiar na 200 plikach wyżej |
| Kontrakty tras | zielone | `test_authz_guard_matrix`, `test_job_scope_contract`, `test_section_ceiling_contract`, `test_route_authz_contract`, `test_candidate_pipeline_section_contract` — 91 testów; wzorzec uprawnień +1 trasa |
| Trasy i auto-CV z bazą | tylko CI | `tests/test_stage_cv_pick_from_profile.py` (lokalnie brak bazy) |
| Front | zielone | vitest: `stage-cv-options`, `CandidatePreviewPane` (18), `cv-to-client`, `harness-seeds` (62), `recruitment-feature-parity`; `tsc --noEmit`; eslint |
| Ekran | przeklikane lokalnie | `/preview/screening-form?state=cvpick`, `cvconsent`, `cvready` przy 1280 × 720 i 1900 × 1000: lista, wyszarzenie, podgląd, „Zmień CV” z potwierdzeniem, „Edytuj” otwiera edytor |

## Niepotwierdzone

- Wybór CV na prawdziwym kandydacie na produkcji (zapis). Harness nie wysyła żądań, a zapisu na żywych danych nie
  wykonywałem.
- Wygląd Worda po imporcie plików spoza szablonu firmowego oceniony liczbami (tekst kompletny), nie wzrokiem —
  treść tych plików to dane osobowe.

## Poza zakresem

- pliki PDF i stare `.doc`,
- dołączanie zrzutu zgody do kopii odłączonej (PKO BP zostaje przy generatorze),
- ten sam wybór w karcie „CV do klienta” na „Zweryfikowanym”,
- blokada 12 h dla tras CV etapu (dziś jej nie respektują — bez zmian).
