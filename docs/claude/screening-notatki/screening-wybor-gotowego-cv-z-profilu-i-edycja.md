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
  zrzut zgody i reguły klienta źródłowego nie jadą z kopią. Nazwa pliku
  i nagłówek kopii biorą nazwę roli TEJ rekrutacji jak generator
  (`job_working_title.cv_role_title_for_job`, D2), nigdy surowy `jobs.title`:
  wzór PKO `ZOB-{PROJEKT}_{STANOWISKO}_…` dokładał wtedy numer drugi raz
  (zgłoszenie DL 15.10.2026; nazwy już zapisane poprawił jednorazowo krok
  startu `stage-cv-copy-filenames`, `services/stage_cv_copy_filename_repair.py`).
  Kopia CV z innej
  rekrutacji dostaje w nagłówku tytuł TEJ rekrutacji i traci linię „Rozważany
  na stanowisko” (tytuł źródłowy bywa numerem zapytania innego klienta); CV
  blind ma w nazwie pliku „Kandydat”, nie nazwisko. Klient z wymogiem
  zrzutu zgody: od 12.10.2026 kopia powstaje z wymogiem zamrożonym na sobie,
  pobranie czeka na zrzut, a zgodę dołącza się do CV etapu (do tej daty 422
  `consent_client_needs_generator` i wyszarzone opcje) — szczegóły w
  `generator-cv/zrzut-zgody-rodo-na-koncu-cv-wymog-pko-bp.md`. Nie przywracaj
  powiązania z dokumentem generatora dla kopii z innej rekrutacji — blokada
  pobrania i pakiet czytają wtedy cudzego klienta.
- **Import Word → edytor: `services/cv_docx_import.py`**, bez AI. Jest
  odwrotnością układu `render_approved_docx`: sekcje po tytułach, tabela
  edukacji jako akapit, blok „daty / Nazwa firmy: / Stanowisko:” jako rola ze
  znacznikami `data-cv-section`; czego nie rozpozna, zostaje akapitem albo
  punktem. Czyta wszystkie runy akapitu (hiperłącza, pola formularza Worda,
  wstawki śledzenia zmian), klauzulę zgody bierze z pola tekstowego szablonu,
  a gdy jej nie ma — dokłada standardową w języku pliku. Plik jest
  niezaufany (formularz kariery, import), a konwersja biegnie w procesie
  aplikacji: komórki tabeli czytaj przez `app/core/docx_cells.py`, nigdy
  `row.cells` (powtarza komórkę `gridSpan` razy — liczba z pliku; reguła dla
  wszystkich czytników w `podstawy/tabele-worda-z-wgranych-plikow.md`),
  i trzymaj limity `MAX_LINES` / `MAX_TABLE_DEPTH`. Pomiar na 200
  plikach z produkcji: 200 wczytanych, 0 zgubionych akapitów (także po
  ponownym renderze do Worda), sekcje rozpoznane w 198, role w 182.
  Zmieniasz import albo renderer — sprawdź obieg w `test_cv_docx_import.py`
  i powtórz pomiar na prawdziwych plikach (same liczby, bez treści).
  Nagłówek tabeli edukacji to wiersz, którego KAŻDA niepusta komórka jest
  etykietą („Daty”, „Nazwa uczelni/kierunek”, angielskie odpowiedniki; bez
  odstępów) — nie dokładna para. 19.10.2026 plik pobrany z NEXUSA i poprawiony
  w Wordzie miał nagłówek bez „Daty” i „Nazwa uczelni/kierunek” wchodziło do
  CV jako pierwsza uczelnia.
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

## „Użyj innego CV” w karcie „CV do klienta” (12.10.2026)

Pomiar na produkcji 12.10.2026: 16 z 22 auto-CV z dwóch tygodni powstało dla
osób, które miały już gotowe CV (11 — plik Word „B2B”, 5 — CV generatora
z innej rekrutacji, 4 — CV etapu w innej rekrutacji), a karta dawała tylko
„Wygeneruj ponownie”. Decyzje Artura: automat zostaje bez zmian, karta
podpowiada gotowe CV, przepięcie przenosi je samo. Raport:
`docs/cv-reuse-in-card-completion-report.md`.

- **Trzecie źródło: CV ETAPU z innej rekrutacji** (`services/stage_cv_copy.py`,
  `GET …/cv/branded/sources`, `POST …/select-stage-cv`). Kopia bierze treść po
  poprawkach rekrutera (zatwierdzoną, a bez niej szkic); `select-generated`
  dla innej rekrutacji renderuje wynik generatora od nowa i poprawki gubi,
  więc lista chowa generację rekrutacji, która ma CV etapu
  (`lib/stage-cv-options.ts`). Stary szablon „CV firmowe” nie jest źródłem.
- **Metadane kopii z listy dozwolonych kluczy, nigdy przez przepisanie źródła**
  (`detached_metadata`). Skrót treści generatora dałby kopii fałszywe
  „zweryfikowane” przy zatwierdzaniu, a migawka reguł — limity cudzego klienta.
  `source` zostaje przy `document` / `generated_other_job` (każda inna wartość
  robi z kopii „stary szablon” tylko do odczytu); pochodzenie niesie
  `origin {kind, label, job_id, selected_at}` i z niego karta bierze plakietkę.
- **Nagłówek kopii podmienia `retitle_copied_html`** (na `cv_qc.EditableCv`,
  nie regexem i nie przez lxml): pierwsze `<h1>` dostaje tytuł tej rekrutacji,
  linia „Rozważany na stanowisko” znika, reszta dokumentu wychodzi bez zmian.
  Tylko dla treści z generatora — nagłówek pliku Word pochodzi z pliku.
- **Plik z dysku NIE trafia do plików kandydata** (`POST …/cv/branded/upload`):
  w teczce mógłby stać się „aktualnym CV” osoby i źródłem dla generatora oraz
  auto-CV, a powtórne wgranie tych samych bajtów przemianowałoby istniejący
  plik. Zostaje nazwa i skrót treści w śladzie; ponowne użycie daje kopia CV
  etapu. Kafelek „Wgraj nowe CV” w panelu osoby (15.10.2026) zapisuje gotowe
  CV do klienta w profilu jako „CV dla klientów”, ale tylko u osoby z głównym
  CV — wtedy nie zostanie „aktualnym CV”
  (`rekrutacja-tablica/nowe-cv-w-rekrutacji.md`). Od tej daty `select-document`,
  `branded/upload` i `select-stage-cv` odmawiają po „CV wysłane” (409
  `client_cv_locked_after_send`).
- **`GET …/cv/branded` dla etapu bez wiersza CV to stan pusty (200), nie 404**
  — karta jest widoczna także w „Nowych” i „Screeningu” (bez sekcji wysyłki),
  a etapy z importu Traffita wiersza nie mają.
- **Pasek „Ta osoba ma już gotowe CV”** pokazuje się, gdy CV nie ma albo leży
  nieprzejrzane auto-CV; karta pyta o gotowe CV dopiero po wczytaniu własnego
  stanu. „Użyj nowej wersji” dotyczy tylko generacji młodszych niż
  `origin.selected_at` — inaczej karta od razu radziłaby nadpisać CV, które
  rekruter przed chwilą świadomie wskazał.
- **Zwykłe przepięcie nie kopiuje CV od 27.10.2026** (panel podobnych
  rekrutacji, „Do przejrzenia”, przypisanie z listy, automat). Zgłoszenie
  zespołu: po screeningu i ruchu na „Zweryfikowany” karta miała już gotowe CV
  z poprzedniej rekrutacji, zrobione przed tym screeningiem — wyglądało, jakby
  CV wygenerowało się samo. Od 21.10 CV powstaje po trzech potwierdzeniach
  (`generator-cv/cv-po-potwierdzeniu.md`), a powód kopii z 12.10 (automat by
  zrobił nowe) zniknął. Stare CV karta podpowiada przez „Użyj gotowego CV”.
  Decyzja Artura 27.10.2026.
- **„Match” DL-a nadal kopiuje CV** (`carry_on_reassign` w
  `add_candidates_to_job`, tylko przy jawnym `reassign_from_job_id`, zaraz po
  migawce oryginału), bo od razu wysyła osobę do klienta: savepoint, nigdy nie
  rzuca, `flush` przed kopią. Ta sama reguła
  dostępu co przy ręcznym wyborze: kopię przenosi tylko osoba, która może
  czytać rekrutację źródłową (`ensure_job_read_access`); odmowa i brak osoby
  działającej (automat bez właściciela rekrutacji) to „nie przenoś”, nie błąd.
  CV wczytane z pliku Word jedzie z nagłówkiem z pliku — karta każe go sprawdzić.
- Harness `/preview/cv-generator?state=card` (pięć stanów karty i okno wyboru).
