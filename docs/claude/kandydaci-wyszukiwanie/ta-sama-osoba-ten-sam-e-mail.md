# Ta sama osoba = ten sam e-mail; nowe CV czytane od razu (12.10.2026)
<!-- indeks: duplikaty w oknach, /from-cv, poczcie i imporcie; LinkedIn z adresu profilu -->

Zgłoszenie z 12.10.2026: okno „Dodaj kandydata” pokazało „Znaleziono 34 podobnego
kandydata”, a kandydata nie było w bazie. Pomiar na produkcji (tylko odczyt):
dopasowanie po LinkedInie brało ostatni kawałek adresu z dowolnej wartości pola,
1 579 z 27 583 wartości nie było adresem profilu, a dokładnie 34 osoby miały
w polu `linkedin.com`. Imiennika z innym e-mailem miało 8 713 osób (13% bazy),
więc ostrzeżenie „podobny kandydat” trafiało bardzo często i nic nie znaczyło.

## Reguła (decyzja Artura)

- **Ta sama osoba = ten sam e-mail**, bez rozróżniania wielkości liter. Inny
  e-mail to inna osoba i zapis idzie bez ostrzeżeń. CV bez e-maila zakłada nowy
  profil — w oknie, w `/from-cv`, w imporcie masowym i w poczcie M365 tak samo.
- Jedyny inny dowód to **ten sam plik** (SHA-256) leżący już w czyimś profilu,
  bo jest dokładny, a nie zgadywany. Plik z kwarantanny tożsamości się nie
  liczy (`source_is_eligible_clause` w `_duplicates_by_file_hash`): leży
  w profilu, ale system sam uznał go za CV innej osoby, więc wskazywałby cudzy
  profil. 12.10.2026 takich plików było 155.
- Telefon, LinkedIn oraz imię i nazwisko nie odmawiają i nie podpinają CV,
  bo wspólny numer (agencja, biuro) wrzucał CV do cudzego profilu — na
  produkcji 313 numerów należało do kilku różnych osób.
- **Wyjątek w `/from-cv` (decyzja Artura, 22.10.2026): ten sam telefon ORAZ
  to samo imię i nazwisko** (bez wielkości liter i spacji na brzegach, numer
  po ostatnich 9 cyfrach) → 409 z `existing_candidate_id`, powody
  `["phone_exact", "name_exact"]`. Powód: scraper JustJoin (panel nie podaje
  telefonu, e-mail z CV inny niż w starym profilu) założył 20–22.10.2026
  drugi profil 7 osobom z bazy; scalone tego samego dnia. To dopasowanie, nie
  dowód — `?force=true` je pomija, okna mają „To inna osoba? Załóż osobny
  profil” („Dodaj z CV”) i „Wczytaj mimo to” („Dodaj kandydata”). Sam telefon
  albo samo imię i nazwisko nadal nie odmawiają. Sprawdzenie idzie PO odczycie
  CV (`find_candidate_by_phone_and_name`), sito przed odczytem bez zmian.

## Gdzie to mieszka

- `services/dedup_service.find_candidate_by_email` — reguła tożsamości. Bierze
  ją każde miejsce, które decyduje: `POST`/`PATCH /api/candidates`, skan
  w `/from-cv`, sito `cv_upload_dedup.find_duplicates_without_llm`,
  `m365/attachment_handler.try_create_candidate_from_cv`. Wyrażenie zostaje
  dokładnie `func.lower(func.btrim(Candidate.email))`, bo tylko wtedy planer
  bierze indeks `ix_candidates_email_lower_btrim`
  (`test_candidate_email_lower_index.py`).
- `find_candidate_duplicates` to lista podpowiedzi dla człowieka: okno scalania
  (`candidateMerge.ts`), `/check-duplicates`, wtyczka `/from-linkedin`. Niczego
  nie blokuje. LinkedIn pasuje tylko po identyfikatorze z adresu
  `…linkedin.com/in/<slug>` (`normalize_linkedin_url`), równością na kolumnie
  `linkedin_slug`; zapasowego `ILIKE` nie ma, bo dla krótkiej końcówki ładował
  pół bazy razem z tekstem CV przy każdym sprawdzeniu.
- `/from-cv` robi jedno sprawdzenie e-maila: bez `force` odmowa 409 niesie
  `existing_candidate_id` (czytają go okna i klient JustJoin, który podpina
  wtedy CV do tego profilu), z `force` zostaje zdanie „Kandydat z tym adresem
  e-mail już istnieje.” Adres z formularza wygrywa z nagłówkiem pliku także
  w sicie (`form_email`; wyczyszczone pole = brak kroku e-mail).
- **Dwa zapisy tego samego e-maila naraz** (14.10.2026, audyt 13.10):
  `/from-cv` i poczta M365 (albo dwa przebiegi synchronizacji) mijały
  sprawdzenie `find_candidate_by_email`, bo nie widzi ono niezatwierdzonego
  wiersza równoległej transakcji; drugi zapis padał na unikalnym indeksie
  `email` i kończył się 500 (a w poczcie wywracał całą sesję
  synchronizacji). Teraz zapis idzie w SAVEPOINCIE (`db.begin_nested()`):
  `/from-cv` wpisuje e-mail już w INSERT-cie i przy kolizji odpowiada 409 jak
  przy zwykłym duplikacie (bez `force` z `existing_candidate_id` profilu,
  który wygrał — `_raise_from_cv_duplicate_conflict`; z `force` „Kandydat
  z tym adresem e-mail już istnieje.”); poczta M365
  (`try_create_candidate_from_cv`) przy kolizji podpina CV do profilu
  z tym adresem (`_parse_into_existing`), a gdy adres ma kilka profili —
  `parse_error = "conflicting_identity"`; uzupełnienie adresu z CV
  w `finish_cv_ingest` (`_fill_email_unless_taken`) pomija adres zajęty
  w międzyczasie i zapisuje resztę profilu. Testy:
  `test_fix48_ws10_email_race.py`, `test_fix48_ws10_email_race_db.py`.
- Okna: `ExistingCandidateNotice` w „Dodaj kandydata” (`AppShell.tsx`).
  Okno pyta `/check-duplicates` tylko o e-mail. „Dodaj z CV” w rekrutacji ma
  od 13.10.2026 własny widok osoby z bazy: „Dodaj do rekrutacji z tym CV”
  (CV na górę profilu i „Nowi”), „Podmień CV w tej rekrutacji” przy osobie
  w toku, „Przywróć” przy zamkniętej karcie, a przy identycznym pliku drugi
  profil tylko z linku — `rekrutacja-tablica/nowe-cv-w-rekrutacji.md`.

## Czego nie przywracać

- Listy „podobnych” ze „score” i nazwami powodów (`linkedin_slug_match`) na
  ekranie rekrutera.
- „Zapisz mimo to” przy tym samym e-mailu — serwer i tak odmawia, więc był to
  przycisk bez wyjścia. Zostaje wyłącznie dla identycznego pliku.
- Telefonu w sicie przed odczytem i `possible_duplicate_name` w poczcie.

## Nowe CV osoby, która już jest w bazie

- Serwer czyta CV modelem i odświeża profil tylko wtedy, gdy plik jest
  **głównym CV** (`POST /api/candidates/{id}/documents` z `is_primary=true`,
  odczyt w tle, `CvWritePolicy.REFRESH`). Zwykły plik CV tylko leży w Plikach.
- „Dodaj to CV do profilu” (okno „Dodaj kandydata”) i „Dodaj do rekrutacji
  z tym CV” (okno „Dodaj z CV”) wysyłają plik od razu jako główne CV
  (`attachCvFormData`). W zakładce Pliki pole „Ustaw jako główne CV (AI odświeży
  profil)” jest domyślnie zaznaczone; przy kilku plikach głównym zostaje ostatni,
  bo każde główne CV to osobny płatny odczyt.
- CV innej osoby wgrane jako główne nie może zniszczyć profilu. Bramka
  tożsamości (imię i nazwisko z pliku) biegnie w tle, a nowy plik przejmuje
  główne CV i `cv_filename` od razu, więc wgranie i „Ustaw jako główne CV”
  podają bramce stan sprzed zmiany (`ReplacedPrimaryCv` z
  `_primary_cv_before_change`: poprzednie główne CV i wskaźnik pliku). Przy
  niezgodności ten stan wraca, fakty i wektor zostają, a profil dostaje
  znacznik `_identity_quarantine_source` („wgrane CV nie zasiliło profilu”).
  Dotyczy to także profilu bez głównego dokumentu (dane z importu; 254 takie
  profile) — wgrany plik niczego jeszcze w profilu nie zapisał, bo odczyt
  biegnie po bramce. Sama zgodność nazwy pliku jest dowodem pochodzenia faktów
  tylko przy ponownym odczycie pliku, który już był głównym CV: 91% profili
  nie ma zapisanego dokumentu źródłowego. Pomiar z 12.10.2026: 155 niezgodności
  na 7 757 odczytów dokumentów (2%), 88 profili ze znacznikiem i bez głównego CV.
- Odświeżenie nie rusza danych kontaktowych ani pól poprawionych ręcznie:
  `PATCH` ustawia `_manual_override_<pole>` dla umiejętności i historii pracy,
  a od 12.10.2026 także dla lat doświadczenia, wykształcenia i podsumowania
  (blokuje dopiero zmiana wartości, nie samo przysłanie pola).

## Limity czasu

Odczyt CV liczy model: 12.10.2026 serwer odpowiedział po 36,8 s, a okno na
domyślnych 30 s pokazało „Nie udało się przeczytać CV”. Wywołania
`/api/candidates/cv/preview` i `/from-cv` niosą `SLOW_ENDPOINT_TIMEOUT_MS`
(pilnuje `api-slow-endpoint-timeout.test.ts`), a przekroczenie czasu ma własny
komunikat (`isClientTimeout` w `lib/http-timeouts.ts`).

## Znane koszty i zaległości

- 966 grup „ten sam telefon i nazwisko, inny e-mail” (12.10.2026) to
  prawdopodobnie podwójne profile; od 22.10.2026 `/from-cv` nie dokłada
  nowych, ale istniejące czekają na narzędzie scalania.
- Unikalny indeks jest na surowej kolumnie `email`. 12.10.2026 było 5 par
  różniących się wielkością liter; po ich scaleniu warto dodać unikalny indeks
  na `lower(btrim(email))`.
- Zewnętrzny scraper sam pyta `/check-duplicates` — żeby trzymał regułę, ma
  wysyłać tylko `email`.
