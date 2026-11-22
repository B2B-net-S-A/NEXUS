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

## Edytor nowego CV: Strona 1 i Stanowiska (22.11.2026)

Makiety: wariant A (Artur, 22.11.2026) — „Strona 1” i „Stanowiska” jako
formularz po lewej i strona PDF z ramką po prawej.

- **Kiedy:** tylko CV etapu z układem `new` i włączoną flagą
  (`new_layout_enabled`). Nagłówek ma wtedy zakładki „Strona 1 · Stanowiska ·
  Cały tekst · Jak u klienta”; „Cały tekst” to dotychczasowa kartka (wszystko,
  czego formularze nie obejmują, zostaje edytowalne). Pierwsze wczytanie
  otwiera „Stronę 1”, przełączenie na klasyczne wraca do „Edycji”. Klasyczne CV
  i wynik generatora mają edytor bez zmian. Pasek w formularzach to tylko
  cofnij / ponów i „Więcej” (`CvEditorToolbar.historyOnly`).
- **Formularz pisze do dokumentu Tiptapa, nie obok niego**
  (`lib/cv-new-layout-form.ts`). Pole czyta tekst akapitu, zmiana to
  najmniejsza podmiana tekstu w transakcji — pogrubienia wokół zostają,
  dopisek za pogrubionym słowem pogrubiony nie jest, cyfra doklejona do
  pogrubionej liczby jest. Autozapis, historia cofania (Ctrl+Z w polu = cofnij
  w edytorze), QC i plik Word działają jak przy pisaniu na kartce. Nie dodawaj
  formularzowi własnej kopii treści ani osobnej trasy zapisu.
- **Strona 1:** punkty 1–2 to punkty sekcji `why_points` w dokumencie
  (wspólne z Wordem). Pod punktem 1 „Z dat stanowisk: X lat Y mies.” —
  suma dat stanowisk tą samą arytmetyką co `client-form-years`
  (`unionMonths`, `monthsText`). Punkt 3 „Najmocniejszy wynik” to dodatek
  nowego CV: pole zapisuje `page1_extras.result_text` (1,2 s po ostatnim
  znaku albo przy wyjściu z pola; puste = brak), „Inny wynik (N)” pokazuje
  tylko sprawdzone `results` (`verified`) i zapisuje `result_index`
  z `result_text: null`. Pole pokazuje tekst bez `**`; zdanie poprawione
  ręcznie zapisuje się bez pogrubień. Zwinięte wiersze: „Przebieg kariery”
  otwiera „Stanowiska”, „Umiejętności” / „Edukacja” / „Języki” — „Cały tekst”
  z kursorem w tej sekcji.
- **Stanowiska:** lista z `cvOutline` (firma z akapitu `employer` bez branży,
  stanowisko, okres), „wyżej / niżej” przestawia całe zakresy ról
  (`moveRoleAt`, ta sama transakcja co „Więcej → Stanowisko pod kursorem”),
  „Dodaj” wstawia rolę z polami w nawiasach za wybraną (`insertRole(lang,
  after)`). Formularz: okres od – do (linia `role` po pogrubionej nazwie),
  firma (`employer`, brakujący akapit powstaje), stanowisko (zawsze
  pogrubiony początek linii `role`), punkty zakresu zadań (ostatni usunięty
  znika z listą i etykietą, pierwszy dodany przywraca „Zakres zadań:”),
  technologie po etykiecie z `CV_TEMPLATE_LABELS` (akapit bez etykiety dostaje
  ją z powrotem).
- **Trasa:** `PATCH /api/candidates/stages/{id}/cv/page1`
  (`api/cv_page1.py`, `{result_index?, result_text?}`): bramka zapisu
  w kandydatach + zespół rekrutacji (`_load_csv_for_stage`), 409 po „CV
  wysłane”, przy wyłączonej fladze, bez CV i na zatwierdzonej wersji (dodatki
  są w niej zamrożone — edytor najpierw zakłada szkic, `ensureDraft`).
  Niesprawdzony albo nieistniejący wynik i zdanie ponad 400 znaków → 422.
  Pozostałe pola `page1_extras` (`why`, `results`) zostają. Wpis
  `cv_page1_changed` bez treści zdania. `GET …/cv/branded` niesie
  `page1_extras`. Wzorzec bramek: `tests/data/authz_golden/cv_page1.json`
  (te same litery co `preview-pdf`), moduł w `_SCOPED_MODULES`.
- **Podgląd** (`useNewCvPreview`, `CvPdfPageView`): ta sama trasa
  `…/preview-pdf` co „Jak u klienta” (limit 20/min na osobę, wspólny). Pierwszy
  PDF od razu, kolejny 4 s po ostatniej zmianie treści albo dodatków, tylko
  gdy zakładka formularza jest na ekranie i karta przeglądarki widoczna,
  najwyżej 8 na minutę (`previewDelay`). Stary obraz zostaje na czas
  odświeżania i po błędzie (komunikat przez `apiErrorMessage` + „Ponów”);
  błąd tej samej treści nie ponawia się sam. Chip „Strona 1 z N · mieści się ·
  pismo 10 pt” z nagłówków `X-CV-Page1-*` (czerwony przy „nie mieści się”).
  Ramka: pdf.js czyta warstwę tekstu, linie z początkami punktów „Dlaczego”
  (strona 1) albo z firmą, stanowiskiem, okresem, punktami i technologiami
  wybranego stanowiska (strona z największą liczbą trafień; przy powtórzonym
  tekście linia najbliżej pierwszego trafienia). Bez trafień strona bez ramki
  i zdanie „Stanowisko jest na tej stronie — bez ramki”.
- **Harness:** `/preview/cv-editor?layout=new` — fikcyjne CV
  (`new-layout-fixture.ts`), dodatki w pamięci, podgląd to
  `public/preview/cv-editor/nowe-cv-przyklad.pdf` z renderu serwera tego CV
  z nagłówkami jak z trasy. Po zmianie CV albo wyników w fiksturze wygeneruj
  PDF ponownie: `cv_json_from_editor_html` → `NewCvDocument.from_cv_json(…,
  why=compose_page1_why(…))` → `render_new_cv_pdf_with_report` w obrazie
  backendu (bez `entrypoint.sh`, sieć wyłączona).
- Testy: `lib/__tests__/cv-new-layout-form.test.ts`,
  `cv-new-preview.test.ts`, `cv-editor/__tests__/CvNewLayout*.test.tsx`,
  `modals/__tests__/CVBrandedEditModal.newLayout.test.tsx`,
  `backend/tests/test_cv_page1.py`.
