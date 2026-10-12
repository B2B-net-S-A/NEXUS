# Ta sama osoba = ten sam e-mail; nowe CV czytane od razu — raport z wdrożenia

12.10.2026. Reguły: `docs/claude/kandydaci-wyszukiwanie/ta-sama-osoba-ten-sam-e-mail.md`.

## Po co

Rekruterka dodawała kandydata przez „Dodaj kandydata” i dostała naraz:
„Nie udało się przeczytać CV”, „Znaleziono 34 podobnego kandydata” (obce osoby
z powodem `linkedin_slug_match`) oraz ramkę „Ten kandydat może już być w bazie”
wskazującą obcą osobę. Kandydata w bazie nie było i nie został dodany.

## Przyczyny (potwierdzone odczytem produkcji, bez zapisu)

- **34 „podobnych”**: `dedup_service._linkedin_slug` brał ostatni kawałek po „/”
  z dowolnej wartości pola LinkedIn. 1 579 z 27 583 wartości nie było adresem
  profilu; dokładnie 34 osoby kończyły się na `linkedin.com`. Zapytanie miało
  też zapasowe `ILIKE '%końcówka%'` i ładowało pełne wiersze z tekstem CV.
- **Odczyt CV**: serwer odpowiedział 200 po 36,8 s, okno czekało domyślne 30 s.
  Tego dnia 16 z 67 zapisów z CV trwało ponad 30 s.
- **Ramka decyzji**: zawsze nazywała pierwszą osobę z listy, a „Zapisz mimo to”
  przy tym samym e-mailu serwer i tak odrzucał.
- **Nowe CV w istniejącym profilu**: plik z zakładki Pliki nie był czytany
  przez AI, dopóki ktoś nie kliknął „Ustaw jako główne CV”.

## Decyzje Artura

- Ta sama osoba = ten sam e-mail, bez rozróżniania wielkości liter; także
  w automatach (poczta, JustJoin, import masowy).
- CV bez e-maila zakłada nowy profil.
- Zakładka Pliki: pole „Ustaw jako główne CV (AI odświeży profil)”, domyślnie
  włączone.
- Ręczne poprawki lat doświadczenia, wykształcenia i podsumowania są chronione
  przed nadpisaniem przez nowe główne CV.

## Co weszło

- `backend/app/services/dedup_service.py` — `find_candidate_by_email` (reguła
  tożsamości na indeksie `lower(btrim(email))`); `find_candidate_duplicates`
  zostaje listą podpowiedzi dla okna scalania i wtyczki LinkedIn: LinkedIn tylko
  z adresu profilu, równość na `linkedin_slug`, bez `ILIKE`, lekkie kolumny,
  stała kolejność przy remisie.
- `backend/app/api/candidates.py` — `/from-cv`: jedno sprawdzenie e-maila
  (bez `force` odmowa z `existing_candidate_id`, z `force` zdanie przy polu);
  `POST`/`PATCH` odmawiają zajętego e-maila bez względu na wielkość liter;
  `PATCH` blokuje ręcznie zmienione lata doświadczenia, wykształcenie
  i podsumowanie.
- `backend/app/services/cv_upload_dedup.py` — sito przed płatnym odczytem:
  identyczny plik, potem e-mail; bez telefonu; adres z formularza wygrywa
  z nagłówkiem pliku.
- `backend/app/services/m365/attachment_handler.py` — CV z poczty: e-mail
  kandydata → podpięcie; inny e-mail albo brak → nowy profil; ten sam plik już
  w czyimś profilu → CV idzie tam; adres albo plik na dwóch profilach → nic.
- `backend/app/services/candidate_identity_quarantine.py` (znalezione
  w przeglądzie bezpieczeństwa) — CV innej osoby wgrane jako główne nie czyści
  profilu właściwej osoby. Nowy plik przejmuje główne CV i `cv_filename`, zanim
  odczyt dojdzie do bramki tożsamości; kwarantanna brała zgodność nazwy pliku
  za dowód, że fakty pochodzą z niego, i kasowała tekst CV, podsumowanie
  i wektor, zostawiając kandydata bez głównego CV. Mechanizm istniał wcześniej,
  ale „główne CV” stało się ustawieniem domyślnym (niezgodność wychodzi w 2%
  odczytów dokumentów). Wgranie i „Ustaw jako główne CV” podają teraz, które CV
  zostało zastąpione; przy niezgodności wraca ono jako główne, a profil pokazuje,
  że wgrany plik nie zasilił danych. Ręcznie poprawione podsumowanie nie jest
  czyszczone.
- Front: `ExistingCandidateNotice` w „Dodaj kandydata” i w „Dodaj z CV”
  rekrutacji („Dodaj to CV do profilu”, „Otwórz profil”, „Wczytaj mimo to”);
  okno pyta tylko o e-mail i pamięta „Wczytaj mimo to” przy zapisie; limit 120 s
  dla odczytu i zapisu z CV z osobnym komunikatem po przekroczeniu czasu;
  import masowy z tym samym limitem; pole wyboru w zakładce Pliki.
- Harness `/preview/candidates-list` odpowiada lokalnie na żądania okna
  (fikcyjne dane).
- Bez migracji i bez zmian w danych.

## Czego zmiana nie robi

- Nie sprząta 1 579 śmieciowych wartości LinkedIna — po zmianie nie szkodzą.
- Nie scala 5 par profili z e-mailem różniącym się wielkością liter i nie
  dodaje unikalnego indeksu na `lower(btrim(email))`.
- Nie sygnalizuje 966 grup „ten sam telefon i nazwisko, inny e-mail”.
- Nie zmienia zewnętrznego scrapera: żeby trzymał regułę, ma wysyłać do
  `/check-duplicates` tylko e-mail.
- Nie pokazuje nieudanego odczytu CV w tle w profilu, który miał już odczytane CV.

## Testy

- Lokalnie, bez bazy: `test_dedup_service.py`, `test_candidate_email_lower_index.py`,
  część `test_cv_upload_dedup.py`, `test_auto_match.py` (CV z poczty),
  `test_m365_multi_cv_mail.py`, `test_candidate_identity_quarantine.py`,
  `test_claude_md_index.py` — nowe przypadki
  padały przed zmianą i przechodzą po niej; `ruff check` i `ruff format --check`
  na `app/`.
- W CI (Postgres): `test_candidates_from_cv.py` (imiennik, wspólny telefon
  i LinkedIn, wielkość liter, `force`), `test_candidates_cv_preview.py` (adres
  z formularza kontra nagłówek), `test_candidate_create_duplicate_email.py`,
  `test_cv_document_enrichment_languages.py` (blokady ręcznych poprawek; CV innej
  osoby wgrane jako główne przez prawdziwą trasę zostawia profil i stare CV).
- Front: vitest na oknach, zakładce Pliki, strażniku limitów czasu i harnessach;
  `tsc --noEmit`; eslint na zmienionych plikach.
- Przeglądarka, 1280 × 720, harnessy `/preview/candidates-list`
  i `/preview/candidate-profile`: nowa osoba, zajęty e-mail z plikiem i bez,
  „Dodaj to CV do profilu”, długi odczyt, identyczny plik, pole w zakładce Pliki.
