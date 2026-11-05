# Kwarantanna tożsamości: co znika z profilu

Gdy plik zostaje uznany za CV innej osoby, `_clear_cv_projection` usuwa z profilu
fakty z tego pliku. Decyzje z 05.11.2026, po ręcznej naprawie dwóch profili:

- Porównujesz kolumnę z tym, co naprawdę zapisał `_apply_cv_enrichment`, nie
  z surowym odczytem. Umiejętności idą przez `normalize_llm_skills`, LinkedIn przez
  `normalize_linkedin_url`, e-mail małymi literami. Wykształcenie, lata i telefon
  zapisują się bez zmian (sama przycięta spacja), więc tam wystarcza równość.
- Umiejętności dopisane z notatek zostają. Notatki dopisują na końcu listy, więc
  zgodny początek to odczyt CV. Inna kolejność nie jest dowodem pochodzenia, bo
  `FILL_EMPTY` nie nadpisuje kolumny.
- Blokady są wiążące: `skills_manually_curated` i każda `_manual_override_<pole>`.
- Decyzja człowieka (`mark_confirmed_mismatch`) sprawdza też, czy tekst CV w profilu
  jest tekstem tego pliku, i wtedy czyści fakty, choć plik nie jest główny, a odczyt
  nie ma `source_document_id`. Automat tego nie robi, bo decyzja parsera bywa
  fałszywym alarmem.

## Nazwa z nagłówka CV nie daje kwarantanny

Gdy model nie poda imienia albo nazwiska, albo w ogóle nie odpowie,
`_apply_contact_fallbacks` bierze je z pierwszej linii CV o 2–4 słowach pisanych
wielką literą. Bywa to stanowisko albo nazwa firmy: 05.11.2026 przegląd 9 plików
pokazał same fałszywe alarmy, reguła odtwarza nazwę w 7 z nich, a w 4 linia nie była
nazwą osoby. Profil 91859 stracił przez to 10 pól.

- Taki odczyt ma `_name_from_header`, a wołający przekazuje go bramce jako
  `observed_name_from_header`. Inna nazwa niż w profilu daje wtedy `inconclusive`,
  zgodna nadal `confirmed_match`. Nazwa od modelu inna niż w profilu nadal daje
  `confirmed_mismatch`.
- Nie opieraj tego na `_confidence`. Model ocenia też puste pola, a `setdefault`
  zostawia jego wartość, więc nazwa z nagłówka bywa z pewnością 0,0, a nie 0,6
  (profil 662327).
- Koszt: cudze CV, w którym model nie poda nazwy, nie trafi do kwarantanny.
  `evidence.observed_name_from_header` w przeglądzie pozwala policzyć takie decyzje.
  Starsze decyzje nie mają tego pola, bo odczyt z kwarantanny nigdy nie trafił do
  profilu, więc źródła ich nazwy nie da się odtworzyć.
- Decyzja `confirmed_mismatch` zapisana wcześniej zostaje. Zwalnia ją tylko człowiek.

## Nazwa z nagłówka i z pliku nie nazywa profilu

Decyzja Artura z 05.11.2026. Nazwę w pustym profilu daje model albo człowiek.

Pomiar na 57 568 odczytach, w których model podał obie części nazwy z pewnością
powyżej 0,6. Reguła nagłówka dawała nazwę w 47 626 plikach: ta sama osoba 73%,
częściowo zgodna 4%, obca 23%. Nazwa z pliku w 44 707: 79%, 9%, 12%. Na produkcji
przy pewności 0,0 (model nie znalazł nazwy, kod ją wstawił) nazwisko jest w mailu
albo w linku LinkedIn w 0 z 29 profili.

- `_name_from_header` wymienia pola z tej reguły, np. `["last_name"]`. Część od
  modelu zapisuje się dalej. Kto zapisuje nazwę z odczytu, bierze ją przez
  `name_part_for_profile`: uzupełnianie profilu, `/from-cv`, podgląd w formularzu.
- Wartość wpisana w formularzu zdejmuje znacznik tego pola, bo potwierdził ją człowiek.
- Poczta nie zakłada profilu po nazwie z nagłówka (`identity_insufficient`). CV
  dopasowane do profilu po adresie albo po pliku idzie dalej jak dotąd.
- Odczyt zostaje w `cv_extracted_data` razem ze znacznikiem. `_names_from_stored_read`
  przepisuje nazwę tylko bez znacznika i przy pewności powyżej 0,6 przy obu częściach.
  Zapis w tekście CV nic tu nie dowodzi, bo nazwa z nagłówka zawsze w nim jest. Nie
  porównuj odczytu z wynikiem `_split_name_from_header` uruchomionym dziś: po zmianie
  reguły stara nazwa przestałaby się z nim zgadzać i wyglądałaby jak nazwa od modelu.
- Nazwa z pliku działa tylko przy pliku bez tekstu, bo tam model nie miał czego
  przeczytać (37 profili, 29 potwierdzonych mailem albo LinkedInem).
- Koszt: CV z nazwą wyłącznie w nazwie pliku albo w nagłówku, którego model nie uzna
  za nazwę, zostaje z wypełniaczem do ręcznego wpisu. Odczyt bez modelu (awaria,
  `prefer_llm=False`) też nie nazywa profilu, a następny bieg z modelem próbuje znowu.

## Wskaźnik `cv_storage_key` po kwarantannie pliku

Kwarantanna nie zdejmuje `cv_storage_key`. Pomiar 05.11.2026 na 243 aktywnych
kwarantannach plików: klucz nie jest kluczem dokumentu w żadnej, 66 wskaźników
trzyma te same bajty pod własnym kluczem, a 177 to inny plik, często własne CV
osoby. Zdjęcie wskaźnika odebrałoby tym 177 osobom plik, a zwolnienie
z kwarantanny nie miałoby czego przywrócić.

Kto czyta bajty ze wskaźnika, sprawdza je przez `cv_bytes_quarantined`, po skrócie,
nie po kluczu: `get_current_cv`, `cv_text_backfill`, `cv_backfill`. 54 z tych 66
dokumentów nie ma `content_sha256`, więc funkcja liczy go z pliku. Nieczytelny plik
liczy się jako kopia, bo cudzy tekst w profilu jest gorszy niż brak tekstu.

`cv_text_backfill` zapisuje wtedy końcowy znacznik `quarantined`, żeby nie pobierać
pliku co bieg. `override_identity_quarantine` zdejmuje ten znacznik, więc po
zwolnieniu tekst wraca przy następnym biegu, bez naprawy danych.

## Drugi dokument z bajtami pliku z kwarantanny

Decyzja dotyczy jednego wiersza, a `current_cv_filters` patrzy na id. Pomiar 05.11.2026:
17 żywych dokumentów w 16 profilach ma bajty pliku z kwarantanny. W SQL ich nie
znajdziesz, bo `ux_candidate_documents_candidate_sha` nie pozwala na dwa takie same
skróty w profilu, więc para nigdy nie ma obu.

Kto wybiera plik jednej osoby, bierze `current_cv_filters_for`, a kto oznacza pliki na
liście, `quarantined_copy_document_ids`. Tak robią `get_current_cv`, domyślny plik
generatora, QC, „Zmień plik” w CV oryginalnym i lista plików w karcie. Ponowny odczyt
głównego CV pomija taką kopię, zanim plik pójdzie do modelu. Bez tego odczyt z imieniem
`?` przeszedłby bramkę jako `inconclusive` i wpisał cudze dane do profilu.

Odpowiedź liczymy przy odczycie, nie zapisujemy jej przy kopii:

- decyzja parsera bywa fałszywym alarmem, więc kopia nie dostaje własnej decyzji. Zwolnienie
  oryginału (`override_identity_quarantine`) od razu oddaje wszystkie kopie, bez naprawy
  danych i nowego kroku. To też jedyna droga powrotu, gdy kopia była jedynym plikiem osoby;
- wiersz z własnym werdyktem (zwolniony albo `confirmed_match`) nie jest kopią, bo to dowód
  o nim samym;
- nieczytelny plik nie jest kopią. Przy wskaźniku jest odwrotnie, bo tam odpowiedź dotyczy
  jednej kopii, a tu jeden brakujący plik w magazynie ukryłby wszystkie pliki osoby.

Profil bez kwarantanny płaci jedno zapytanie i nie pobiera plików. Narzędzia naprawcze
w `app/cli` zostają przy `current_cv_filters`: nie wysyłają pliku dalej, a sam wybór
i tak przechodzi przez powyższe.

## Zwolnienie z listy plików profilu

Decyzja Artura z 05.11.2026 (wariant A z makiety): zakładka „Dokumenty” → Pliki
pokazuje stan w wierszu, bo po #3060 fałszywy alarm może zostawić osobę bez
bieżącego CV, a rekruter nie miał następnego kroku.

- `GET /api/candidates/{id}/identity-quarantine` zwraca pliki w kwarantannie i kopie.
  Jest osobno od `GET /documents`, bo kopie liczą się czasem z plików w magazynie,
  a tamtej listy używają też podgląd i panel rekrutacji. Awaria tej trasy ma na
  ekranie własny komunikat, bo nie może wyglądać jak brak kwarantanny.
- Widzi każdy, kto widzi pliki. Zwalnia admin i Head of Recruitment
  (`candidate.identity_quarantine.override`), z powodem w `askReason`.
- „Zwolnij” stoi przy oryginale, bo zwolnienie oddaje od razu wszystkie kopie. Przy
  kopii stoi tylko wtedy, gdy oryginał usunięto z profilu. Usunięty oryginał nadal
  trzyma kopie w kwarantannie, dlatego trasa zwolnienia przyjmuje taki plik.
- Plik w kwarantannie i kopia nie mają „Ustaw jako główne CV”: pierwszy wróciłby
  z kwarantanny bez odczytu, a druga zostałaby główna bez odczytu.
- Zwolnienie nie czyta pliku i nie robi z niego głównego CV. Okno i komunikat mówią,
  że trzeba go potem ustawić jako główne CV. Zdejmuje za to znacznik
  `_identity_quarantine_source`, gdy wskazuje ten plik, bo inaczej ramka w profilu
  dalej prosiłaby o zwolnienie.
- Powód nie wraca na ekran: trasa go nie zwraca, bo można w nim wpisać dane osobowe.
