# Ta sama osoba = ten sam e-mail; nowe CV czytane od razu (12.10.2026)
<!-- indeks: reguła duplikatów kandydata w oknach, /from-cv, poczcie M365 i imporcie; LinkedIn tylko z adresu profilu; główne CV = odczyt AI; blokady ręcznych poprawek -->

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
  bo jest dokładny, a nie zgadywany.
- Telefon, LinkedIn oraz imię i nazwisko nie odmawiają i nie podpinają CV,
  bo wspólny numer (agencja, biuro) wrzucał CV do cudzego profilu — na
  produkcji 313 numerów należało do kilku różnych osób.

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
- Okna: `ExistingCandidateNotice` w „Dodaj kandydata” (`AppShell.tsx`)
  i w „Dodaj z CV” rekrutacji. Okno pyta `/check-duplicates` tylko o e-mail.

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
- „Dodaj to CV do profilu” w oknach wysyła plik od razu jako główne CV
  (`attachCvFormData`). W zakładce Pliki pole „Ustaw jako główne CV (AI odświeży
  profil)” jest domyślnie zaznaczone; przy kilku plikach głównym zostaje ostatni,
  bo każde główne CV to osobny płatny odczyt.
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

- 966 grup „ten sam telefon i nazwisko, inny e-mail” to prawdopodobnie podwójne
  profile; reguła ich nie sygnalizuje — temat dla narzędzia scalania.
- Unikalny indeks jest na surowej kolumnie `email`. 12.10.2026 było 5 par
  różniących się wielkością liter; po ich scaleniu warto dodać unikalny indeks
  na `lower(btrim(email))`.
- Zewnętrzny scraper sam pyta `/check-duplicates` — żeby trzymał regułę, ma
  wysyłać tylko `email`.
