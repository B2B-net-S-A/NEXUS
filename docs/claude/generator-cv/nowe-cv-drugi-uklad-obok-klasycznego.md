# „Nowe CV” — drugi układ obok klasycznego Worda (22.11.2026)

<!-- indeks: `cv_layout` przy CV etapu / wersji / generacji / regule klienta, `CV_NEW_LAYOUT_ENABLED`, PDF WeasyPrint z HTML-a edytora (`cv_new_content`, `cv_new_layout`, `cv_new_pdf`), przełącznik wszędzie, blokada po wysyłce, Word zawsze klasyczny -->

Decyzje Artura z 22.11.2026 (makiety i plan: https://claude.ai/artifact/BNgS14uStdSdnbFMWC5T4E,
prywatne; projekt strony 1: https://claude.ai/artifact/5iLRazHADMeQZHhes3BTNS, runda 34).

## Zasady

- **Jedna treść, dwa układy.** Oba układy czytają HTML edytora CV etapu
  (`branded_draft_html`, w wersji zatwierdzonej `content_html`). Nowe CV czyta
  go tym samym kontraktem co plik Word (`data-cv-section`, w starszym HTML
  kształt akapitów) — `services/cv_new_content.py` używa helperów
  `cv_approved_docx`. Przełączenie układu nie generuje CV od nowa i nie kasuje
  poprawek. Nie dokładaj drugiego źródła treści (np. renderu z `render_payload`):
  edycje i poprawki QC żyją tylko w HTML-u.
- **Zapis generatora tylko uzupełnia** to, czego HTML nie niesie: branżę
  stanowiska i słowa do pogrubienia (`highlight_keywords`). Dopasowanie po
  firmie i stanowisku albo firmie i datach; edycja zawsze wygrywa.
- **Układ to jedno ustawienie CV** (`candidate_stage_cvs.cv_layout`:
  `classic` | `new`). Widać je w generatorze (przed „Generuj”), w karcie
  „CV do klienta” i w pasku edytora — wszędzie to samo pole. Zmiana:
  `PATCH /api/candidates/stages/{id}/cv/layout`. Zatwierdzona, niewysłana
  wersja przełącza się razem z CV (`cv_document_versions.cv_layout`). Po
  „CV wysłane” 409, tak jak podmiana CV (`new_cv_company_cv.locked_after_send`).
- **Start:** domyślnie klasyczny. Nowe CV domyślnie tylko u klienta z regułą
  `client_cv_rules.cv_layout = 'new'` (`cv_layout.default_for_client`), przez
  2 tygodnie od włączenia; potem decyzja Artura na liczbach.
- **Generator** zapisuje wybrany układ w `cv_generated_documents.cv_layout`;
  gdy wynik staje się szkicem etapu (`apply_generated_to_stage_cv`), układ
  przechodzi na CV etapu. Automaty i stare generacje biorą układ z reguły klienta.
- **Word to zawsze układ klasyczny.** Nowe CV istnieje tylko jako PDF.
  `…/preview-pdf` i `…/versions/{n}/pdf` renderują nowe CV, gdy układ to
  `new` (albo `?layout=new` — miniatura drugiego układu); klasyczny PDF dalej
  powstaje z pliku Word przez LibreOffice.
- **Render** (`services/cv_new_pdf.py` → `services/cv_new_layout/`) idzie
  w wątku, najwyżej dwa naraz, po zamknięciu transakcji żądania. Awaria = 503
  z polskim komunikatem, ślad w logu. Nagłówki `X-CV-Layout`,
  `X-CV-Page1-Fits`, `X-CV-Page1-Font`, `X-CV-Unmapped-Sections` są na liście
  `expose_headers` w `main.py` (bez tego przeglądarka ich nie widzi).
- **Strona 1 zawsze mieści się na jednej kartce A4** — render skraca listy
  krokami i mówi, jakie pismo zostało („strona 1 mieści się · pismo 10 pt”).
- **Sekcje dopisane ręcznie**, których nowy układ nie zna, nie znikają po
  cichu: `X-CV-Unmapped-Sections` podaje ich liczbę.
- **Dodatki strony 1** (`page1_extras`, JSON): to, czego nie ma w HTML-u
  edytora — zdania strony 1 poprawione w edytorze (`why`), wybrany
  „najmocniejszy wynik”. Zamrażane w wersji przy zatwierdzeniu.
- **Flaga `CV_NEW_LAYOUT_ENABLED`** (rejestr flag): wyłączona = interfejs bez
  wyboru układu, PDF zawsze z pliku Word, generator ignoruje `cv_layout`.
  Włącza się przez workflow „Coolify set env”, w oknie wdrożeń.

## Schemat

Migracja 0753, SQL w `services/cv_layout_schema.py` (czyta go też
`entrypoint.sh`): `candidate_stage_cvs.cv_layout` (NOT NULL, domyślnie
`classic`), `candidate_stage_cvs.page1_extras`, `cv_document_versions.cv_layout`
i `page1_extras` (NULL w starych wierszach = klasyczny),
`cv_generated_documents.cv_layout`, `client_cv_rules.cv_layout`.

## Czego nie cofać

- Nie dokładaj osobnego „Pobierz Word” w nowym układzie — Word jest klasyczny
  z tej samej treści (decyzja „Word w nowym CV”).
- Nie pokazuj przełącznika tylko w generatorze: decyzja „Wszędzie, jeden stan”
  zapadła po makietach obu wariantów.
- Nie blokuj ścieżki CV na wyniku modelu: zdanie „najmocniejszy wynik” jest
  dodatkiem, bez niego strona 1 bierze trzeci punkt „Dlaczego”.
