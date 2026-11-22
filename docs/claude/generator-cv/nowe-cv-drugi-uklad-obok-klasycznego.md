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

## Zdanie „najmocniejszy wynik”

Trzecie zdanie „Dlaczego nasz kandydat” na stronie 1 (wariant E2): najmocniejszy
wynik z całego CV. Kod: `services/cv_page1_results.py` (model, zapis, wyzwalacze)
i `services/cv_page1_result_checks.py` (sprawdzenie, bez sieci i bazy).

- **Co:** osobne wywołanie modelu generatora (klucz `cv_generator`, GPT-6.1 Sol),
  prompt PL albo EN według języka CV; prompt generatora (`legacy_v7`) bez zmian.
  Model dostaje role z HTML-a edytora (firma, stanowisko, okres, punkty) i punkty
  1–2, bez imienia i kontaktu. Oddaje do 4 wyników, każdy jednym zdaniem od
  rzeczownika, z `**pogrubieniem**` faktu, dosłownym cytatem i firmą. Wynik leży
  w `page1_extras.results` (`text`, `quote`, `company`, `verified`, przy
  niesprawdzonym `issue`), `result_index` wraca do 0 tylko przy innych wynikach,
  `results_source_sha` = sha256 HTML-a, z którego liczono.
- **Sprawdzenie (kod, nie model):** cytat stoi w jednym punkcie albo nazwie
  stanowiska jednej roli (po słowach: wielkość liter, cudzysłowy, myślniki
  i interpunkcja się nie liczą, zmienione słowo tak); każda liczba ze zdania stoi
  w cytacie albo w tej roli; jedno zdanie do 170 znaków; w Blind CV bez nazw firm.
  Zdanie o latach albo powtarzające punkt 1 lub 2 znika. Niesprawdzone zostają dla
  edytora, ale strona 1 ich nie bierze (`cv_layout.chosen_result`); sprawdzone
  stoją pierwsze, w kolejności modelu. Firmę bierze kod z roli z cytatem.
- **Wyzwalacze:** `POST …/stages/{id}/cv/page1/results` (przycisk rekrutera, liczy
  zawsze od nowa, limit 20/min, awaria = 503) oraz bieg w tle po commicie:
  `PATCH …/cv/layout` na „Nowe CV” i szkic z generacji w układzie „Nowe CV”
  (`apply_generated_to_stage_cv`). Tło tylko przy `CV_NEW_LAYOUT_ENABLED`, kluczu
  dostawcy i nieaktualnym `results_source_sha`. Zapis pod blokadą wiersza na
  świeżych dodatkach, więc `why` i `result_text` z innych zapisów zostają.
- **Fallback:** bez sprawdzonego wyniku (CV z samymi obowiązkami, awaria modelu)
  strona 1 bierze trzeci punkt generatora. Awaria nie zmienia dodatków, ślad
  jest w logu. Zatwierdzona wersja ma dodatki zamrożone — wynik policzony później
  trafia do szkicu, nie do wysłanej treści.
- **Pomiar 22.11.2026** (kopia produkcji, 30 CV: 20 EN, 10 PL, sam Sol bez
  zapasu, tylko odczyt): sprawdzony wynik w 26 CV, 72 propozycje, 0 odrzuconych
  przez kod, 4 CV bez wyniku (model zwrócił pustą listę przy samych obowiązkach),
  zdanie do 136 znaków (mediana 110), mediana 5 s na CV.
- **Własny klucz AI** (osobny model w env i licznik w Ustawieniach → AI) wymaga
  migracji enuma `aifeaturekey` i wpisu w rejestrze; dziś liczy się jako generator.

## Czego nie cofać

- Nie dokładaj osobnego „Pobierz Word” w nowym układzie — Word jest klasyczny
  z tej samej treści (decyzja „Word w nowym CV”).
- Nie pokazuj przełącznika tylko w generatorze: decyzja „Wszędzie, jeden stan”
  zapadła po makietach obu wariantów.
- Nie blokuj ścieżki CV na wyniku modelu: zdanie „najmocniejszy wynik” jest
  dodatkiem, bez niego strona 1 bierze trzeci punkt „Dlaczego”.
- Nie wpuszczaj na stronę 1 zdania bez `verified` i nie luzuj sprawdzenia cytatu
  ani liczb „bo model jest dobry”: na pomiarze nic nie odpadło, ale to jedyna
  bariera przed liczbą spoza CV u klienta.
- Nie dopisuj tego zdania do promptu generatora — klasyczne CV mają zostać bez
  zmian, a wynik liczy się z treści po poprawkach rekrutera.

## Gdzie idzie układ (22.11.2026, #3717)

Każde miejsce, które oddaje CV dalej, patrzy na układ zatwierdzonej wersji
(`cv_document_versions.cv_layout`), a szkic — na układ CV etapu. Wspólny
render: `cv_new_pdf.approved_version_pdf` / `stage_draft_pdf` (treść, język,
szablon, dodatki strony 1 i zrzut zgody zamrożone w wersji; przed renderem
koniec transakcji; awaria = `NewCvPdfError` → 503 z polskim komunikatem).

- **Bot Cpro** (`GET /integrations/cpro-bot/runs/{run}/cv/{stage}`): zlecenie
  `cv_format = "pdf"` i wersja „Nowe CV” → PDF nowego układu, nagłówek
  `X-CV-Layout: new`; token biegu sprawdzany ponownie po renderze. Historyczny
  DOCX zostaje Wordem. Bez strony panelu (jak dotąd).
- **Kolejka Cpro na pulpicie** (`CproQueueDialog`): „CV” pobiera
  `fetchStageCvForClient` — PDF przy „Nowym CV”, inaczej Word.
- **Panel klienta** (`client_panel.candidate_pdf`, `…/cv.pdf`): PDF nowego
  układu z wersji albo szkicu. Bez strony z linkiem — klient już jest w panelu.
- **Pobranie PDF „Nowego CV” dla klienta** (`…/versions/{n}/pdf` i
  `…/preview-pdf` z `intent=download`): ramka panelu z pliku Word (QR, link,
  krótki adres, ważność) idzie na **ostatnią stronę** PDF
  (`client_panel.stamp_pdf_for_download` → `client_panel_stamp.append_panel_page`:
  WeasyPrint + scalenie pypdfium2). Strona 1 musi się mieścić na jednej kartce,
  więc pod tytułem ramki nie ma. Awaria = PDF bez tej strony. Podgląd
  w NEXUSIE — bez niej. Decyzja Artura z 22.11.2026: ostatnia strona (za zrzutem
  zgody PKO BP), nie pierwsza — strona 1 z podsumowaniem zostaje pierwsza.
- **API v1** (`…/cv/file`): `format=pdf` przy „Nowym CV” = PDF nowego układu;
  `docx` zostaje domyślne i zawsze klasyczne — zmiana domyślnego formatu
  zmieniłaby znaczenie wywołania bez parametru (v2). Nagłówek `X-CV-Layout`
  mówi o oddanym pliku, stan CV (`GET …/cv`) ma pole `cv_layout`.
- **Nazwa pliku**: zapis (`branded_docx_filename`, `docx_filename`) zostaje
  `.docx` — to nazwa pliku Word. Odpowiedź CV etapu (`current_filename`,
  `pattern_filename`) i zmiana nazwy pokazują przy „Nowym CV” ten sam wzór
  z `.pdf` (`cv_layout.filename_for`); `clean_cv_filename` odcina `.docx`
  i `.pdf`, a `CvFileNameRow` zostawia końcówkę z serwera.
- **Przegląd DL, panel osoby, QC**: odznaka „Nowe CV · PDF” / „Klasyczne · Word”
  (`CvLayoutBadge` w `StageCvPreview`; w oknie QC z pola `cv.cv_layout` wyniku
  QC, bez osobnego żądania). QC czyta HTML CV etapu — ten sam w obu układach,
  zrzut zgody z tej samej kopii — więc nie zakłada pliku Word.
- **Reguła klienta „Układ CV”** (`client_cv_rules.cv_layout`, NULL = klasyczny):
  pole recepty (`RULE_FIELDS`) — wersja, diff w historii, publikacja, kopia
  z innego klienta. Wiersz w „Plik i język” i fakt „Układ” w pasku reguły tylko
  przy fladze (`new_layout_enabled` w `GET …/cv-rule` i `/settings/cv-rules`);
  ukryty wiersz i tak wysyła układ (pełny zapis). Przy zasadach centralnych
  (zapis reguły = 403) układ ma własny zapis `PUT /clients/{id}/cv-rule/layout`
  z `central_lock=False` — jak wzór „Karty przed CV”: od razu nowa wersja,
  publikacja i wpis historii; bez zasad centralnych ta trasa daje 409.
  Domyślny układ czyta `cv_layout.default_for_client` wprost z zatwierdzonego
  wiersza (resolver zasad centralnych buduje regułę spoza katalogu w pamięci,
  bez układu). Generator (baner, „Reguły CV klienta” w warsztacie) pokazuje
  układ z `rule-for-generation` (`cv_layout`, `null` przy wyłączonej fladze).

