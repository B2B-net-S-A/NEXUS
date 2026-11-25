# „Nowe CV” — drugi układ obok klasycznego Worda (22.11.2026)

<!-- indeks: `cv_layout` przy CV etapu / wersji / generacji / regule klienta, `CV_NEW_LAYOUT_ENABLED`, PDF WeasyPrint z HTML-a edytora (`cv_new_content`, `cv_new_layout`, `cv_new_pdf`), przełącznik wszędzie, blokada po wysyłce, Word zawsze klasyczny; strona 1 po warsztatach 23.11: nazwisko pod stanowiskiem, języki od B1, miasto, zdania z liniami, oś A1, wieniec certyfikat/dyplom (`page1_extras.wreath`); runda 37 (25.11): nagłówek T2, wyróżnik pod nazwiskiem (`page1_extras.highlight`, auto = praca u klienta), oś po kolei S1, Edukacja bez wieńca z ikonami, pismo do 11 pt, stały odstęp sekcji; zdania 1–3 (25.11): `cv_page1_why`, `page1_extras.why` / `why_generated`, lata z dat kodem, MUST z cytatem, `key_task` z dowodem, „Przywróć z generatora” -->

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

## Strona 1 po warsztatach (23.11.2026)

Decyzje Artura po warsztatach z zespołem (makiety rundy 36:
https://claude.ai/artifact/KQVGVPioPeiDDUQnQDmKcq, prywatne).

- **Tytuł:** stanowisko, a pod nim imię i nazwisko — bez „–” (Blind: samo
  stanowisko). `page1.title_row`.
- **Obok tytułu, w jednym rzędzie:** języki tylko od B1 w górę (A1, A2 i opis
  „podstawowy/basic” znikają; opis bez poziomu, np. „komunikatywny”, zostaje)
  i miasto kandydata z pinezką. Miasto to `candidates.location` czytane przy
  renderze (`cv_new_pdf.cv_facts`), „, PL” obcięte, inny kraj zostaje kodem;
  puste albo Blind CV = bez pastylki. `lang_parts` dzieli też po „–”, „—” i „:”.
- **„Dlaczego nasz kandydat”:** trzy zdania bez punktorów, oddzielone cienkimi
  liniami poziomymi (wariant W1). Treść zdań od 25.11.2026: sekcja „Zdania 1–3
  strony 1” niżej.
- **Oś kariery (zastąpiona 25.11.2026, niżej):** gdy przed 12-letnim oknem są więcej niż 2 stanowiska, starsze
  lata to jasny odcinek tego samego paska z przerwą „//”, nad nim lata
  („1997–2014”), pod nim zwykłym pismem „13 stanowisk, m.in. …” z dwiema
  najdłuższymi firmami (wariant A1). Drobny blok „Wcześniej” z boku zniknął.
- **Edukacja i wieniec (wariant E4):** wieniec przyciąga wzrok, więc trafia do
  niego to, co dla klienta ważniejsze. Domyślnie (`page1_extras.wreath` puste
  albo „auto”) certyfikat, gdy klient go wymaga — wszystkie słowa wymagania MUST
  z Profilu Championa (`stack.must`) stoją w nazwie certyfikatu; kurs ani
  szkolenie się nie liczy — inaczej najwyższy dyplom. Rekruter zmienia to w karcie
  „CV do klienta” (obok układu) albo w edytorze, zakładka „Strona 1”
  (`PATCH …/cv/page1` z `wreath: auto|cert|school`). „Certyfikat” bez certyfikatu
  z MUST bierze najważniejszy certyfikat zawodowy dla roli (punktacja
  `top_certs`). Z certyfikatem w wieńcu (skrót PMP/ISTQB/PL-900 w środku, rok pod
  nim) obok stoją podpisane „Wykształcenie” i „Inne certyfikaty i szkolenia · N”;
  z dyplomem — „Wykształcenie” i „Certyfikaty i szkolenia · N”. Liczba N = wszystkie.
- **Rekruter, generator:** wybór układu to osobny krok „3 · Jak CV zobaczy
  klient” z dwiema kartami (schemat strony 1, co dostaje klient, „polecane” przy
  Nowym CV), przed „Treścią CV”. Domyślny układ bez zmian (reguła klienta).
  Wieńca nie wybiera się w oknie generatora: zapamiętanie wyboru do podpięcia CV
  wymagałoby kolumny w `cv_generated_documents`; wybór jest od razu po generacji
  w karcie i w edytorze.

## Strona 1, runda 37 (25.11.2026)

Decyzje Artura z 25.11.2026 po makietach (prywatny artefakt:
https://claude.ai/artifact/USSM8YEU8BSmS49CUZ5fFi, wersje 1–4).

- **Nagłówek (T2):** stanowisko 19 pt czerwone, pod nim cienka linia i imię
  z nazwiskiem 12 pt. Bez napisu „Kandydat na stanowisko”.
- **Wyróżnik pod nazwiskiem** (`highlight.py`, `page1_extras.highlight`):
  wieniec ze znakiem, etykieta i jedno zdanie, bez ramki i tła. `mode`:
  „auto” (domyślne) = kandydat pracował u klienta rekrutacji — firma ze
  stanowiska ma te same słowa po kolei co nazwa, nazwa wyświetlana albo pełna
  nazwa klienta (`matches_client`; „ING” nie trafia w „Ingenium”, samo „Bank”
  w nic). Etykieta „Doświadczenie w PKO BP · 2018–2023”, zdanie z dat
  i stanowiska („**4 lata 6 mies. jako Tester, Analityk** w PKO BP.”), bez
  dopowiadania. W wieńcu nazwa klienta do 8 znaków, inaczej staż („5 lat”).
  CV anonimowe = bez automatu. „custom” = etykieta (≤ 60), znak (≤ 8) i zdanie
  (≤ 160) rekrutera — bez etykiety albo zdania 422; „off” = bez wyróżnika.
  Nie pisz „Zna klienta od środka” (Artur: brzmi źle). Edytor: sekcja
  „Wyróżnik” w zakładce „Strona 1”, ten sam `PATCH …/cv/page1`; Historia
  zdarzeń zapisuje tylko tryb, bez treści.
- **Wieniec raz na stronie:** z wyróżnikiem Edukacja idzie bez wieńca —
  dwie kolumny z ikonami (biret, odznaka): kierunek, stopień · rok, uczelnia;
  certyfikat, wystawca · rok (`education_plain`). Bez wyróżnika jak dotąd.
- **Oś kariery po kolei (S1, `axis.py`):** odcinki NIE w skali czasu — każdy
  ma miejsce na pełną nazwę firmy w 2 liniach (przy ciasnocie 3), resztę
  dzielą prace według pierwiastka ze stażu. Nad odcinkiem firma, pod nim rok
  rozpoczęcia i stanowisko, bez przerw. Kolejne krótkie zlecenia (< 9 mies.)
  jednym odcinkiem „A · B · C — 3 krótkie projekty”; najwyżej 7 odcinków,
  najstarsi w „Wcześniej · N stanowisk, m.in. …”. Nazwy bez branży
  dopisanej w edytorze („Firma · Bankowość”). Okno 10/12 lat i oś w skali
  lat odrzucone.
- **Wypełnienie kartki (R2):** pismo strony 1 od 11 pt w dół (10–11 pt to nie
  „skrócenie” w komunikacie), stały odstęp 5,5 mm nad każdą sekcją, wolne
  miejsce: połowa w środek sekcji (`inner_mm`: odstępy zdań, wierszy, osi),
  reszta równo między sekcje. Zdania „Dlaczego” rosną z pismem strony.
- **Zdania „Dlaczego”** (zbudowane, sekcja „Zdania 1–3 strony 1”): zdanie 2 bez „Z wymagań
  klienta:”, zdanie 3 bez „Najważniejsze zadanie w tej roli to…” — od razu
  zadanie z dowodem w formie rzeczownikowej; w zdaniu 1 metodyka bez rodzaju
  („przez ten czas w zespołach pracujących w Agile i Scrum”), nie „praca
  w Agile” ani „pracował”.
- **Harness:** `public/preview/cv-editor/nowe-cv-przyklad.pdf` z fikstury
  z klientem „Bank Przykładowy” (pokazuje wyróżnik), nagłówek pisma 11 pt.

## Zdania 1–3 strony 1 (25.11.2026)

Treść trzech zdań „Dlaczego nasz kandydat” według decyzji z warsztatów (23.11)
i rundy 37 (25.11). Kod: `services/cv_page1_why.py` (prompt, wejście, odcisk)
i `services/cv_page1_why_checks.py` (sprawdzenie, bez sieci i bazy); bieg razem
z wynikami w `cv_page1_results.refresh_stage_cv`.

- **Co:** osobne wywołanie modelu generatora (klucz `cv_generator`, model
  z rejestru, w tym samym `ai_feature` co wyniki — jedna jednostka limitu, oba
  wywołania naraz). Prompt `legacy_v7` bez zmian. Wejście: role z HTML-a
  edytora (z branżą z zapisu generatora), MUST z `champion_profile.stack.must`,
  `project.key_task` i odpowiedź kandydata na pytanie screeningu oznaczone
  `key_task` (`CandidateStage.screening_answers`: dopasowanie po zapisanym
  tekście pytania, przy starych arkuszach po numerze; bez pominiętych, bez
  stawek i dostępności, bez zdań przeczących). Bez imienia i kontaktu.
- **Zdanie 1 (doświadczenie):** lata w IT → lata na roli → branże → metodyka.
  Model pisze znaczniki `{LATA_IT}` / `{LATA_ROLA}` i numery ról, a lata
  wstawia kod z dat (suma bez nakładek, pełne lata w dół, poniżej roku
  miesiące). Inna liczba musi stać w punkcie 1 generatora albo być rokiem
  z dat wskazanych ról (miesiąc „12.2025” nie przepuszcza „12 lat”). Metodyka
  (Agile, Scrum, Kanban, SAFe…) tylko, gdy stoi w CV.
- **Zdanie 2 (wymagania klienta):** tylko MUST z profilu, każdy z cytatem
  z punktu jednej roli, w którym (albo w technologiach roli) stoi; MUST nazwany
  w zdaniu bez dowodu = odrzucone. Profil bez MUST = bez zdania 2.
- **Zdanie 3 (najważniejsze zadanie):** forma rzeczownikowa z dowodem — cytat
  z punktu roli (`source: cv`) albo z odpowiedzi ze screeningu
  (`source: screening`). Rekrutacja bez `key_task` = bez zdania 3.
- **Każde zdanie:** jedno, do 220 znaków, bez etykiety na początku („Z wymagań
  klienta:”, „Najważniejsze zadanie…”), bez form z rodzajem („pracował”, „she”),
  w Blind CV bez nazw firm. Liczby jak przy wynikach (cytat, rola, odpowiedź).
- **Zapis:** `page1_extras.why_generated` (trzy wpisy: `slot`, `text`,
  `verified`, przy odrzuconym `issue`, dowody `evidence` / `quote`, `source`),
  `why_source_sha` = odcisk HTML-a, MUST, zadania i odpowiedzi (zmiana profilu
  Championa też liczy zdania od nowa w tle). `page1_extras.why` = trzy sloty na
  stronę 1: sprawdzone zdanie albo poprawka rekrutera; `""` = slot bierze to, co
  dotąd (punkt 1 / 2 generatora, w slocie 3 najmocniejszy wynik, a bez niego
  punkt 3 — `cv_layout.compose_page1_why`). Nowy bieg nadpisuje tylko sloty
  puste albo równe poprzedniemu zdaniu generatora; poprawka rekrutera zostaje.
- **Awaria:** jedno wywołanie padło — druga część się zapisuje, padła zostaje
  bez zmian (ślad w logu, bieg w tle spróbuje przy następnym wyzwalaczu); oba —
  dodatki bez zmian, przycisk dostaje 503.
- **Edytor „Strona 1”:** pola „1 · Doświadczenie”, „2 · Wymagania klienta”,
  „3 · Najważniejsze zadanie” edytują `why` (`PATCH …/cv/page1` z `why`:
  `null` = slot bez zmiany, `""` = „Przywróć z generatora”), nie treść CV —
  punkty w Wordzie zostają. Pod polem: skąd jest zdanie (generator z dowodem,
  punkt z CV, wpisane ręcznie, odrzucone i dlaczego, brak MUST / zadania).
  „Wynik z CV (N)” wstawia sprawdzony najmocniejszy wynik do slotu 3. „Ułóż
  zdania od nowa” = `POST …/cv/page1/results` (zdania i wyniki naraz). Historia
  zdarzeń zapisuje tylko, które sloty mają zdanie.
- **Poligon:** osoby 990108 i 990109 rekrutacji ćwiczebnej mają od startu
  „Nowe CV”, więc „Edytuj CV” otwiera „Stronę 1” ze zdaniami z
  `lib/poligon/cv-fiction.ts`; zmiany strony 1 i „Ułóż od nowa” idą w pamięci
  (`lib/poligon/tools.ts`). Lekcja `lekcja-nowe-cv-strona-1` (wyróżnik + zdania).

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
- **Wynik po zmianie treści (przegląd 25.11.2026):** `verified` dotyczy HTML-a
  z `results_source_sha`. Gdy treść jest inna (rekruter usunął rolę, zmienił
  liczbę), render PDF sprawdza wybrany wynik jeszcze raz na bieżących rolach tym
  samym kodem (`cv_page1_result_checks.rechecked_extras` w `cv_new_pdf._render`,
  bez sieci, bez zapisu); niesprawdzony ustępuje trzeciemu punktowi generatora.
  Zdanie wpisane przez rekrutera (`result_text`) nie przechodzi tej kontroli —
  to jego słowa. Wczytanie innego CV (nowa generacja bez „zachowaj poprawki”
  w `apply_generated_to_stage_cv`, wgrany plik Word w `_write_imported_draft`)
  czyści `results`, `result_index`, `result_text`, `results_source_sha`,
  zdania 1–3 (`why`, `why_generated`, `why_source_sha`) i własny wyróżnik
  (`highlight.mode == "custom"`) — `cv_layout.forget_page1_result`.
  Wybór wieńca i wyłączony wyróżnik zostają. Od 25.11.2026 (#3972) przycisk
  to „Ułóż zdania od nowa” w nagłówku „Dlaczego nasz kandydat” (dawne „Policz
  wyniki od nowa” przy polu wyniku): najpierw zapis szkicu, potem
  `POST …/cv/page1/results` liczy wyniki i zdania naraz; w czasie liczenia pola
  zdań czekają; 503 i 429 jako zdanie przez `apiErrorMessage`.
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
  bariera przed liczbą spoza CV u klienta. Z tego samego powodu nie ufaj samej
  fladze po edycji CV — kontrola przy renderze na bieżącej treści zostaje.
- Nie dopisuj tego zdania do promptu generatora — klasyczne CV mają zostać bez
  zmian, a wynik liczy się z treści po poprawkach rekrutera.

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
- **Strona 1:** od 25.11.2026 pola 1–3 to zdania `page1_extras.why` (sekcja
  „Zdania 1–3 strony 1”); niżej stan z 22.11. Punkty 1–2 to punkty sekcji `why_points` w dokumencie
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

