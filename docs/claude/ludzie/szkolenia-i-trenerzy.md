# Szkolenia i trenerzy — zamówienie, wycena A–E, umowa szkoleniowa, pliki, biblioteka (0694)
<!-- indeks: szkolenia, trener, umowa szkoleniowa, Załącznik nr 1, wycena A–E, podpis kwalifikowany, przekazanie plików, faktura trenera, biblioteka nagrań, zapisy na szkolenie, obecność z Teams, SharePoint szkoleń, Akademia Compassa -->

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

## Poza zakresem (13.11.2026)

Dzwonki dla TCM o nowej wycenie i podpisie (ekran `/trainings` pokazuje stany), stan
zapłaty z eBI24 zamiast przycisku Finansów, postęp oglądania, test wiedzy w bibliotece.
