# Nowe CV w rekrutacji — kafelek w panelu osoby i „Dodaj do rekrutacji z tym CV” (13.10.2026)
<!-- indeks: „Wgraj nowe CV”, `…/cv/original/upload`, „Użyj w tej rekrutacji”, „Dodaj CV” w profilu i CV do klienta z nowego CV (29.10) -->

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
  `quarantine_restore` (patrz niżej), `client_cv_repair` (naprawa D3 z
  15.10.2026, patrz „Gotowe CV do klienta z kafelka”).
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

### Pobieranie z podglądu (15.10.2026, D1–D5)

Prośba z zespołu: z dużego podglądu nie dało się pobrać CV, które się ogląda
(oryginał tylko przez dok: sekcja „CV” → „Pokaż CV oryginalne” → okno →
„Pobierz”). Makiety i decyzje: https://claude.ai/artifact/EBFqwhJjt1CoSUGkjYnPTV,
raport `docs/cv-download-from-preview-completion-report.md`.

- **D1 — miejsce.** „Pobierz CV” stoi w pasku źródeł PRZED „Wgraj CV”, także
  bez prawa wgrania (przegląd DL, Rozmowy) — trasy pobrania wymagają tylko
  odczytu. Znacznik inwentarza `screening-form.preview-cv-download`.
- **D2 — to, co widać.** „CV oryginalne” → kopia ze zgłoszenia
  (`…/stages/{id}/cv/original/download`) albo główne CV z profilu; „Inne
  pliki” → zaznaczony plik. Dymek: nazwa pliku i zdanie z `originalCvSentence`.
  Plik z kwarantanny tożsamości nie jest oryginałem (`withoutQuarantinedCv`,
  ta sama reguła co dok); znacznik z danych kandydata bierzemy tylko z pamięci
  zapytań (`enabled: false`) — podgląd nie dokłada żądania, harnessy bez zmian.
- **D3 — CV firmowe.** W tym samym miejscu „Pobierz Word” + „PDF”: ten sam plik
  co dok (`fetchStageCvFile` / `fetchStageCvPdf` na `cvStageId`, wpis
  `surface=preview`), tylko przy `stageCvStatus === "ready"` i poza „Zmień CV”.
  Bez zgody RODO wyłączone. `StageCvPreview` dostaje `hideDownload` —
  „Pobierz DOCX” w treści zakładki zniknęło; przegląd DL (`CvColumn`) go nie ukrywa.
- **D4 — „aktualne”.** Nad oryginałem ramka `DockCvFreshness` („W profilu jest
  nowsze CV”): „Pokaż” przełącza na „Inne pliki” z tym plikiem, „Użyj w tej
  rekrutacji” tylko z prawem wgrania (`canRefresh`). Bez ramki „Pobierz CV”
  po cichu dawałby starszy plik.
- **D5.** Przy otwartej „Historii osoby” przycisku nie ma. Pobranie oryginału
  i plików z profilu nie trafia do `cv_file_downloaded` — liczymy CV firmowe.
- **Laptop 1280 px.** Strefa ma ok. 750 px; z „Historią osoby”, „Pobierz” i
  „Wgraj CV” rząd się zawijał. Zakładka jest kontenerem `cvsources`: poniżej
  56 rem „Zwiń CV” zostaje ikoną (z `aria-label`), przy CV firmowym znika słowo
  „Pobierz” i ikona przy „PDF”, a odstęp spada do 6 px. Najgorszy przypadek
  w harnessie: 707 z 745 px. Nowy przycisk w tym rzędzie = pomiar w
  `/preview/screening-form` (stan `cvnewer` pokazuje ramkę D4).

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

## Poprawki po audycie 13.10.2026 (14.10.2026)

- **Plik z kwarantanny nie jest bieżącym CV.** `cv_source.current_cv_filters`
  wyklucza dokument z żywą kwarantanną tożsamości (`confirmed_mismatch` bez
  zwolnienia admina/HoR, `source_is_eligible_clause`), a `get_current_cv`
  nie schodzi do wskaźnika kandydata z kwarantanną `legacy_cv`. Kwarantanna
  zdejmuje z pliku tylko `is_primary`, więc osoba bez innego CV dostawała
  cudzy plik w każdej następnej kopii etapu i w generatorze.
  `restore_stage_copies_after_quarantine` robi `flush` przed wyborem
  następcy (sesje mają `autoflush=False`) — kopia dostaje poprzednie CV
  osoby, a nie pustkę. Panel osoby nie bierze pliku wskazanego przez
  `_identity_quarantine_source` jako „Oryginał CV: z profilu” ani do ramki
  „W profilu jest nowsze CV” (`withoutQuarantinedCv` w doku), chyba że ktoś
  ustawił go ponownie jako główne CV.
- **Kopia z wgrania powstaje z bajtów żądania** (`refresh_original_cv_snapshot(current=…)`),
  bez ponownego odczytu głównego CV. Przy awarii magazynu odczyt schodził do
  wskaźnika kandydata i kopia dostawała starsze CV pod nazwą nowego pliku.
- **Ramka „CV firmowe powstało z poprzedniego CV” po ruchu karty.** Ruch
  zakłada nowy wiersz etapu bez CV, a szkic zostaje na poprzednim. Dok
  pokazuje ramkę także przy szkicu pary na innym wierszu (`pairCvElsewhere`,
  prop `cvStageId`): ramka czyta szkic i kopię CV tamtego wiersza, liczy
  najpóźniej podmienioną ręcznie kopię z obu wierszy (`replacedCopy`),
  „Użyj nowej wersji” i „Zostaw obecne” idą na wiersz ze szkicem. Wcześniej
  znikała po ruchu i CV ze starego pliku szło do klienta bez ostrzeżenia.
  „Użyj w tej rekrutacji” dalej podmienia kopię bieżącego wiersza.
- **Upuszczenie pliku na podgląd CV poniżej 1024 px wgrywa raz.** Lewa strefa
  jest wtedy ukryta, podgląd z własnym `CvFileDropTarget` stoi w DOM-ie
  panelu i oba obszary wgrywały ten sam plik. Zewnętrzny pomija upuszczenie
  z `defaultPrevented`.

## Gotowe CV do klienta z kafelka (15.10.2026, D1–D3)

Zgłoszenie rekrutera: „wgrane CV ma być CV do użycia w rekrutacji, bez
kolejnego przeklikania”. Rekruterzy wgrywali kafelkiem gotowe CV do klienta
(„B2B_Stanowisko_Imię_Nazwisko.docx”), a trasa robiła z niego główne CV profilu
(AI czytało profil z wersji firmowej) i „Oryginał CV”. CV do klienta trzeba było
potem podmienić paskiem „Ta osoba ma już gotowe CV” („Użyj tego CV” +
„Zastąp”). Pomiar na produkcji: od 13.10 15 z 37 wgrań w panelu to takie
pliki; 16 z 17 importów pliku z profilu dotyczyło pliku wgranego przez tę samą
osobę najwyżej 30 min wcześniej. Makiety i decyzje:
https://claude.ai/artifact/U6wAqaH4nqF55RF9RiWPP2, raport
`docs/cv-upload-client-cv-completion-report.md`.

- **D1 — rozpoznanie po nazwie** (`services/client_cv_upload.py`,
  `looks_like_client_cv`): tylko `.docx`, „B2B” jako osobne słowo (lustro
  `isClientCvFilename` z frontu) albo stały początek wzoru nazwy klienta
  rekrutacji (`client_filename_pattern`: zatwierdzona reguła, a bez niej
  katalog `cv_policies.json`). Samo „B2B” pomijało czterech klientów: PKO BP
  „ZOB-…”, Orlen, Energa, Bank Pocztowy. Porównanie po zwinięciu separatorów,
  więc „ZOB-2962_…” i „ZOB_…” (pusty projekt) pasują; początek krótszy niż
  3 znaki nie rozpoznaje niczego. PDF „B2B” zostaje CV kandydata.
- **Ta sama trasa, `outcome` w odpowiedzi** (`StageCvUploadResponse`):
  `original` (jak dotąd), `client_cv` (szkic CV do klienta z importu Worda,
  `_import_docx_as_draft` jak „Użyj tego CV”, QC w tle) albo `client_cv_kept`.
  Przy `client_cv` główne CV profilu, odczyt AI i kopia oryginału zostają bez
  zmian. Pole `mode=original` wymusza starą ścieżkę.
- **Wiersz CV pary jak w karcie** (`cvStageId`): bieżący, a gdy pusty — wiersz
  sprzed ruchu karty ze szkicem albo zatwierdzonym CV.
- **D2 — kiedy pytamy.** Brak CV do klienta albo nieprzejrzane auto-CV
  (`is_untouched_auto_cv`: szkic z dokumentu `origin=auto`, wpis podpięcia
  automatu z bieżącą rewizją, bez zrzutu zgody RODO) → podmiana bez pytania,
  z migawką szkicu. Każde inne CV (poprawione, wybrane, zatwierdzone) → 409
  `client_cv_replace_confirm` z treścią pytania; front pyta „Zastąpić CV do
  klienta?” i wysyła ponownie z `replace_client_cv=true`. „Nie podmieniaj” =
  nic nie wgrywamy.
- **„Cofnij” w komunikacie** tylko po podmianie bez pytania: ten sam plik
  idzie z `mode=original`, a `_undo_client_cv_upload` przywraca poprzednie CV
  do klienta (auto-CV z dokumentu generatora albo pusty stan) — wyłącznie gdy
  CV do klienta to wciąż ten plik w nietkniętej rewizji
  (`last_upload_if_current`). Ślad: `branded_cv_uploaded_in_recruitment`
  (z `prior` i `replaced`) i `branded_cv_upload_undone`.
- **Po „CV wysłane”** (`integration_cv.locked_after_send` na bieżącym wierszu
  karty) CV do klienta się nie podmienia: plik idzie tylko do profilu
  (`client_cv_kept`). Ta sama blokada (409 `client_cv_locked_after_send`)
  stoi od tej daty na trasach „Użyj innego CV”: `select-document`,
  `branded/upload`, `select-stage-cv` — wcześniej pilnował jej tylko front.
- **Plik w profilu** jako „CV dla klientów” (niegłówny, bez odczytu AI) tylko
  wtedy, gdy osoba ma główne CV. Bez głównego CV najnowszy plik CV staje się
  „bieżącym CV” (`current_cv_ordering`) — źródłem generatora i kopii
  oryginału — więc wtedy pliku nie zapisujemy, jak przy pliku z dysku
  w karcie.
- **CV innej osoby → 422 `client_cv_other_person`** przed jakimkolwiek zapisem
  (`other_person_name`): nagłówek „stanowisko – imię nazwisko” z co najmniej
  dwoma słowami po łączniku, a nazwiska osoby nie ma ani w nagłówku, ani
  w nazwie pliku. Bramka tożsamości oryginału tego pliku nie widzi, a 15.10
  ten sam plik trafił do panelu innej osoby. CV blind i nagłówek bez łącznika
  przechodzą; komunikat wskazuje drogę awaryjną („Gotowe CV do klienta z dysku
  (bez AI)” w oknie „Użyj innego CV” karty).
- **D3 — naprawa profili z okresu przejściowego:**
  `python -m app.cli.client_cv_primary_repair` (na sucho), potem
  `--apply --expected N`. Główne CV „B2B” wgrane od 13.10 → najnowszy własny
  plik PDF/DOC/DOCX osoby zostaje głównym, kopie etapu z bajtami pliku do
  klienta dostają CV osoby (`client_cv_repair` — panel nie pisze „nie
  pasowało do tej osoby”), AI czyta profil od nowa. Osoba bez innego CV
  zostaje bez zmian. Paragon `client_cv_primary_repair_2026_10` (same liczby)
  blokuje drugi bieg.

## Nowe CV od kandydata: profil, rekrutacja i CV do klienta (29.10.2026, D1–D3)

Zgłoszenie Artura: rekruter dostaje nowe CV na LinkedInie albo mailem i nie wie,
jak dodać je do profilu; z rekrutacji musiał wracać do profilu, a CV do klienta
dalej szło ze starego pliku. Pomiar na kopii produkcji 13–28.10: 187 CV wgranych
osobom z otwartą rekrutacją, 34 przez panel rekrutacji; 10 osób miało CV do
klienta ze starszego CV niż wgrane. Makiety: https://claude.ai/artifact/81NLWbfecdy6EsiT2Hzzrc.
Ta sekcja odwraca regułę z 13.10 „Nie generujemy CV firmowego automatycznie po
nowym CV” — w granicach niżej.

- **D1 — CV do klienta po nowym CV** (`services/new_cv_company_cv.py`, pole
  `company_cv` odpowiedzi `…/cv/original/upload`, tylko `mode=auto`):
  - `regenerating` — szkic z generatora, którego od podpięcia nikt nie zmienił
    (`is_untouched_generated_draft`: wpis podpięcia automatu, ręcznej generacji
    albo naszej podmiany z bieżącą `edit_revision`, bez zrzutu zgody). Generacja
    z nowego pliku z tymi samymi źródłami, trybem, językiem i „anonimowe” co
    poprzednia wersja (`enqueue_regeneration`), wpis `branded_cv_regeneration_after_new_cv`
    z rewizją. Gotowa wersja zastępuje szkic w `attach_as_stage_draft`
    (`replace_after_regeneration`) tylko przy tej samej rewizji i tym samym
    dokumencie źródłowym; poprzedni szkic w migawce `replaced`, „Cofnij” =
    `restore-previous`. Edycja w trakcie generacji wygrywa — nowa wersja czeka
    na „Użyj nowej wersji”.
  - `ask` — CV poprawiane, wybrane, wczytane z Worda albo zatwierdzone; także
    gdy reguła klienta odmówiła generacji (wgranie i tak przechodzi). Panel
    pyta „Generuj z nowego CV” (`POST …/cv/branded/regenerate-from-original`,
    `expected_revision`, bramka Sourcing; plik = kopia „Oryginał CV”) albo
    „Zostaw obecne”.
  - `confirm` — CV do klienta nie ma: reguła z 21.10 zostaje
    (`generator-cv/cv-po-potwierdzeniu.md`), nowy plik jest od razu
    potwierdzonym plikiem w panelu potwierdzeń (`CvGeneratePanel`, wpis z
    pamięci zapytań). Decyzja Artura 29.10: bez generacji przed odpowiedziami
    i notatkami.
  - `locked` — karta na „CV wysłane” i dalej; `none` — klient bierze własny
    formularz (0521).
- **Blok „Nowe CV”** (`recruitment/NewCvProgress.tsx`, logika `lib/new-cv-upload.ts`):
  profil ✓, oryginał ✓, CV do klienta (generuje się / podmienione + „Cofnij” /
  pytanie / potwierdzenia / u klienta). Wpis zapisuje `useStageCvUpload` pod
  kluczem pary (`newCvUploadKey`), więc blok w karcie, w panelu i w oknie
  profilu widzi wgranie z każdego miejsca. Ramka `CompanyCvStaleNotice` milknie,
  dopóki blok stoi; „Zostaw obecne” zapisuje ją jako odrzuconą.
- **D2 — gdzie wgrać:** „Dodaj CV” w pasku osoby na profilu (`AddCvDialog`,
  capability `candidate.document.manage`, inwentarz `c.add_cv`): plik, „Ustaw
  jako główne CV” i rekrutacje w toku (bez zamkniętych; po „CV wysłane”
  wyszarzone). Każda zaznaczona = ta sama trasa etapu, po kolei; bez rekrutacji
  — `POST /api/candidates/{id}/documents`. W karcie „CV do klienta” kafelek
  „Mam nowsze CV — np. z LinkedIna” pod wierszem „Plik CV”, w wąskim panelu
  „Wgraj nowe CV” w nagłówku sekcji „CV” (`DockSection action`, widoczny po
  zwinięciu; po wgraniu sekcja się rozwija).
- **D3 — źródła CV (LinkedIn/mail) nie zapisujemy.**

Testy: `backend/tests/test_new_cv_company_cv.py`, `lib/__tests__/new-cv-upload.test.ts`,
`recruitment/__tests__/NewCvProgress.test.tsx`, `candidate-profile/__tests__/AddCvDialog.test.tsx`.

## Czego nie robimy

- Nie generujemy CV do klienta z nowego CV, gdy ktoś je poprawiał, wybrał albo
  zatwierdził, ani gdy go jeszcze nie ma (wtedy potwierdzenia z 21.10) — patrz
  sekcja z 29.10.
- Nie podmieniamy kopii CV w innych rekrutacjach osoby (okno „Dodaj CV” w
  profilu robi to tylko w zaznaczonych).
- Nie wgrywamy przez upuszczenie pliku na kartę Tablicy (wariant C odłożony).

Harness: `/preview/job-detail` trzyma kopie CV etapu po wgraniu w pamięci strony.
