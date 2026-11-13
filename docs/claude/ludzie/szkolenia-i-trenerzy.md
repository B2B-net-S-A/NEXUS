# Szkolenia i trenerzy — zamówienie, wycena A–E, umowa szkoleniowa, pliki, biblioteka (0694)
<!-- indeks: szkolenia, spotkanie Teams z NEXUSA, szkolenia@, zaproszenie po zapisie, limit miejsc, nagranie z Teams, transkrypt, ocena szkolenia, nagranie dla zapisanych, trener, umowa szkoleniowa, Załącznik nr 1, wycena A–E, podpis kwalifikowany, przekazanie plików, faktura trenera, biblioteka nagrań, zapisy na szkolenie, obecność z Teams, SharePoint szkoleń, Akademia Compassa -->

Decyzje Artura z 13.11.2026 (makiety: https://claude.ai/artifact/JTaxcwJQSG7fkNLqbGkwh4).
Szkolenia i biblioteka nagrań są w NEXUSIE. Akademia w Compassie nie startuje, a Compass
idzie do wygaszenia (osobna sesja). Wzór umowy: „Umowa B2B - Szkolenia” → szablon
`backend/app/templates/contract/umowa_szkoleniowa_pl.docx` (builder
`backend/scripts/build_training_agreement_template.py`).

Kod: `app/services/trainings/` (`core.py` stany i widoki, `agreement.py` umowa,
`signing.py` podpisy, `storage.py` pliki, `media.py` bilet odtwarzania, `attendance.py`
raport Teams, `notify.py` maile do trenera), trasy `app/api/trainings.py`
(`/api/trainings`), sekcja „Szkolenia” w `app/api/consultant_portal.py`,
`app/api/trainings_media.py` (`/api/public/training-media`). Ekrany: `/trainings`
w NEXUSIE, `/konsultant/szkolenia` i `/konsultant/trener` w panelu.

## Zapisy umowy, które sterują kodem

- **Tylko zdalnie (§ 3).** Zgłoszenie trenera nie pyta o formę ani o salę.
- **Cena to wycena zamówienia w pozycjach A–E (§ 7 ust. 3, § 11, Zał. 1 pkt 6),** nie
  stawka za dzień. Niewykonany element = brak tej części wynagrodzenia, więc każda pozycja
  ma osobną kwotę: A program i materiały, B przeprowadzenie, C prezentacja (tylko gdy
  zamówiona), D pliki audio (tylko gdy zamówione), E przeniesienie praw.
- **Załącznik nr 1 to formularz:** dane szkolenia i pliki do przekazania wpisuje TCM
  w zamówieniu, agendę, materiały własne i osób trzecich oraz kwoty trener w wycenie.
  Generator przenosi pola 1:1 do szablonu.
- **Podpis odręczny albo kwalifikowany obu stron (§ 17).** Skan, mail i podpis zaufany się
  nie liczą (art. 53 pr. aut.), dlatego zgoda zaznaczona w polu nie zastępuje umowy.
  Obieg jak przy umowie B2B (`kontrakty/podpis-umowy-b2b-w-nexusie.md`): PDF zamrożony
  odciskiem, każde wgranie zaczyna się bajtami poprzedniej wersji, trener podpisuje
  pierwszy (w panelu), potem reprezentant z listy `company_signer_ids` (w NEXUSIE).
  Własne kolumny w `trainings`, bo `b2b_signing_requests` wymaga wiersza Generatora.
- **Prawa przechodzą z zapłatą (§ 8 ust. 3).** Do zapłaty firma ma tylko licencję na to
  szkolenie, więc szkolenie trenera B2B wchodzi do biblioteki dopiero po „Zapłacone”
  od Finansów. Szkolenie prowadzone przez pracownika nie ma umowy i publikuje się od razu.
- **Faktura po szkoleniu i przyjęciu plików z Zał. 1 pkt 4 (§ 7 ust. 5).** Zwrot pliku do
  poprawy niesie termin 3 dni roboczych (§ 11 ust. 4, `add_business_days`).

## Kto co robi

- **TCM i admin**: zamówienie, przyjęcie albo odesłanie wyceny, dane do umowy i PDF,
  przyjęcie plików, nagranie i pliki wewnętrzne, „dla uczestników”, publikacja, obecność.
- **Finanse** (uprawnienie „Moduł Finanse”): rejestr z kwotami, „Zapłacone”.
- **Reprezentant** (lista podpisu B2B): wgrywa PDF z podpisem za B2B Network; reguła
  w handlerze, nie w bramce, bo lista jest w ustawieniach.
- **Każdy pracownik** po wejściu do NEXUSA i **każdy konsultant z panelem**: biblioteka
  i zapisy na szkolenia na żywo. Kwot nie widzą.
- Bramki tras mają przedrostek `require_hr_trainings_*`, a router stoi za `_HR_PROGRAM`
  (grupa „Ludzie”, jak panel konsultanta).

## Reguły, które łatwo cofnąć

- **Nagranie publikuje druga osoba** niż ta, która je wgrała (`core.publish`, kod
  `four_eyes`), jak w planie Akademii z 10.11.2026.
- **Plik z biblioteki** tylko z opublikowanego szkolenia, z `for_participants` i przyjęty
  (`core._LIBRARY_FILE`): plik od trenera, którego TCM nie przyjął albo zwrócił do poprawy,
  nie wychodzi do wszystkich, także po publikacji (przegląd bezpieczeństwa 13.11.2026).
  PPTX do edycji domyślnie zostaje wewnętrzny.
- **Duże pliki (do 2 GB) idą surowym ciałem z nazwą w `X-File-Name`,** nie multipartem
  (`services/trainings/raw_upload.py`). FastAPI parsuje multipart przed zależnościami
  trasy, więc wywołanie bez sesji zapisywało 2 GB na dysk, zanim dostało odmowę. Surowe
  ciało czyta dopiero handler, po bramce. Wyższy limit ciała mają tylko te dwie trasy
  (`BodySizeLimitMiddleware(pattern_limits=…)`), a `X-File-Name` jest w CORS.
- **Odtwarzacz dostaje bilet, nie sesję.** `<video>` nie dołoży nagłówka
  `X-Portal-Session`, więc trasa z sesją wydaje bilet HMAC jednego pliku ważny 6 h
  (`media.py`), a `/api/public/training-media/{id}?t=…` go sprawdza. Sesji ani tokenu
  pracownika w adresie nie ma. Bilet z biblioteki (zakres `lib`) trasa sprawdza przy
  każdym żądaniu jeszcze raz, więc wycofanie z biblioteki zamyka też wydane bilety.
- **Pliki: SharePoint, gdy skonfigurowany** (`app_settings['trainings_sharepoint']`,
  link do folderu wkleja admin w `PUT /api/trainings/settings`). Folder szkoleń leży na
  witrynie B2B_ALL, a rejestracja „NEXUS Contract Documents” ma `Sites.Selected` na innej
  witrynie: nadanie tej witryny to krok admina w Azure. Bez niego pliki idą na dysk
  (`STORAGE_ROOT/trainings/`), który nie ma kopii poza serwerem
  (`nexus-offsite-backup-never-existed`).
- **Pliki projektu montażowego (.drp) i surowe fragmenty nie są przyjmowane** — poprzedni
  trener przysłał projekt DaVinci, 79 MP3 i 82 PNG zamiast gotowego podcastu.
- **Maile do trenera** idą przez `portal_mail.send` (wyłącznik panelu), bez linku
  z tokenem i bez myślników „—”.
- **Scalanie kontraktów**: cztery kolumny w `_KNOWN_CONTRACT_FKS`, dubel zapisu na
  szkolenie rozstrzyga `_resolve_child_duplicates`. **Usunięcie kandydata** kasuje zapisy
  i anonimizuje obecność; szkolenie z umową zostaje.

## Teams, zapisy i nagranie z NEXUSA (0697, decyzje Artura 13.11.2026)

Analiza i makiety: https://claude.ai/artifact/KhP85yuVMjTE1rPhnaJnRz. Kod:
`services/trainings/teams.py` (spotkanie i zaproszenia), `recordings.py` (pętla
`trainings_teams`: przypomnienia, nagranie, transkrypt, obecność), `signals.py`
(dzwonki), `services/m365/teams_training_graph.py` (Graph).

- **Spotkanie zakłada NEXUS w kalendarzu skrzynki szkolenia@**
  (`TRAININGS_TEAMS_MAILBOX`, `TRAININGS_TEAMS_ENABLED`), gdy szkolenie jest `signed`
  i ma datę z godziną. Osobne konto z licencją Teams i OneDrive, bo nagranie ląduje
  w OneDrive organizatora; nie konto TCM (odejście osoby albo 120 dni = utrata) i nie
  wsparcie@ (decyzja Artura: wyjątek od jednej skrzynki, bez czytnika poczty).
  Wyłączone albo bez skrzynki = link wkleja TCM jak przed 0697.
- **Webinaru Teams z rejestracją nie zakładamy**: Graph pozwala na to tylko
  zalogowanemu człowiekowi. Rejestrację, limit miejsc (`seat_limit`, blokada wiersza
  przy zapisie) i przypomnienia robi NEXUS.
- **Zapis = osobne wydarzenie z linkiem** w kalendarzu zapisanego, bez własnego
  spotkania Teams. Nie dopisujemy ludzi do spotkania głównego, bo PATCH listy
  uczestników wysyła aktualizację każdemu. Konsultant dostaje zaproszenie tylko przy
  otwartym panelu (`open_for`), jak każdy mail panelu.
- **Bez poczekalni, prowadzący prezenterem** (`set_presenters`): skrzynki szkolenia@ nikt
  nie obsługuje na żywo. Gdy Graph odrzuci rolę prezentera gościa (trener B2B),
  zostaje `allowedPresenters=everyone`.
- **Awaria Graph nie cofa kroku**: `teams_status=failed` + „Spróbuj ponownie”
  (`POST /api/trainings/{id}/teams`). Graph wołamy po commicie kroku.
- **Nagranie wraca samo**: pętla co 5 min, ok. 20 min po końcu, kopiuje MP4
  strumieniem do magazynu szkoleń (nie do pamięci, 1 GB+), transkrypt VTT do
  `training_transcripts`, obecność z Graph zamiast CSV. Po 72 h bez nagrania
  `recording_status=none`. Uprawnienia ponad prepy: `OnlineMeetingRecording.Read.All`,
  `OnlineMeetingArtifact.Read.All`.
- **Nagranie dla zapisanych przed zapłatą** (`share_registered`, bilet `reg`):
  przed zapłatą firma ma licencję na to szkolenie (§ 8 ust. 4). Cała biblioteka dalej
  po zapłacie. Przed pierwszym użyciem opinia prawnika. Cztery oczy jak przy publikacji;
  nagranie z Teams nie ma wgrywającego, więc zatwierdza jedna osoba z TCM.
- **Przełożenie szkolenia pracownika po zatwierdzeniu** jest dozwolone (nie ma umowy);
  szkolenia trenera B2B po umowie nie (termin stoi w podpisanym Zał. 1).
- **Plik TCM dla uczestników**: plik wewnętrzny idzie do uczestników tylko po zaznaczeniu
  (inaczej szkolenie pracownika nie miało jak dać materiałów).
- **Ocena 1–5** tylko od zapisanego, po terminie; trener i TCM widzą średnią i treść
  bez nazwisk. **Dzwonki** (`training_*`, osobiste): TCM o wycenie, pliku i nagraniu,
  reprezentant o umowie, Finanse o fakturze, zapisani pracownicy przypomnienie dzień
  wcześniej od 9:00 i 15 min przed oraz o nagraniu. Bez kwot w treści.

## Poza zakresem (13.11.2026)

Stan zapłaty z eBI24 zamiast przycisku Finansów, postęp oglądania, test wiedzy
w bibliotece, rozdziały i podsumowanie z transkryptu przez model AI, próba techniczna
z trenerem, „obowiązkowe dla roli”, „Szukamy trenerów” w panelu.
