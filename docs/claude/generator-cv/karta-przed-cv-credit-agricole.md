# Karta przed CV (Credit Agricole, 0626, 29.10.2026)

Credit Agricole Bank Polska wymaga z każdym CV jednostronicowej karty dostawcy
w Wordzie: imię i nazwisko, rola, poziom doświadczenia, staż, profil
kompetencji, dostępność, lokalizacja, wynagrodzenie za 1 MD i opiekun po
stronie dostawcy. CV wysyła Delivery Lead, więc kartę też.

Decyzje Artura 29.10.2026 (ostateczne):

- **Karta istnieje tylko w przeglądzie DL-a przed wysyłką** („Przejrzyj
  i wyślij”, `DlReviewPanel`): trzecia pigułka „Karta do klienta” obok „CV
  firmowe / CV oryginalne”. Rekruter karty nie widzi, bo ma stawkę do klienta —
  trasy karty pary oddają rekruterowi 403 (`user_can_view_client_rate`),
  a ekran w ogóle o nią nie pyta (`canViewClientRate`).
- **Włączenie per klient wzorem w edytorze reguły CV** (sekcja „Karta przed CV
  (Word)” w `CvRuleSettingsTab`). Wzór jest = karta włączona; usunięty =
  wyłączona. Bez nazwy klienta w kodzie. Wzór zapisuje się od razu, osobno od
  „Zapisz regułę”, z wpisem `Activity` klienta (`cover_sheet_template_*`).
- **Wzór nie trafia do repo** — ma telefony pracowników. Leży w bazie,
  w osobnej tabeli `client_cover_sheet_templates` (bytea, jeden wiersz na
  klienta), nie w kolumnie `clients`, którą czyta się wszędzie. Kolumna pliku
  jest odroczona w modelu. Testy budują fikcyjną kartę w tym samym układzie
  (`tests/_cover_sheet_docx.py`).
- **Osobny plik Word obok CV**, nie doklejony do CV:
  `Karta_<Imię>_<Nazwisko>.docx`.
- **Poziom z lat doświadczenia komercyjnego** (`candidates.years_it_experience`):
  poniżej 3 — Junior, 3–7 — Specjalista, od 8 — Expert. Poziom jest ZAWSZE
  „do sprawdzenia” (żółty, „z N lat stażu — sprawdź”); brak lat = puste pole
  do wybrania.

Reguły, które łatwo cofnąć:

- **Odczyt wzoru bez AI** (`services/cover_sheet.py`): pole znajduje się po
  etykiecie bez wielkości liter i polskich znaków („imie i nazwisko”, „rola”,
  „poziom doswiadczenia”, „staz”, „profil kompetencji”, „dostepnosc”,
  „lokalizacja”, „wynagrodzenie”). Zmienia się tylko miejsce na wartość za
  etykietą (do złamania wiersza albo następnej etykiety): ciąg „x” (też
  „xx.xxxx”), lista „Junior/Specjalista/Expert”, a w wynagrodzeniu „xxxx,00”.
  Formatowanie przebiegu zostaje; nagłówek i blok opiekuna z łączami zostają
  bajt w bajt. Wzór CA nie ma tabel, więc odczyt ich nie czyta. Odmowa (422):
  nie DOCX, makra, ponad 5 MB albo mniej niż 4 rozpoznane etykiety.
- **Wartości liczy serwer:** imię i nazwisko z profilu, rola = `jobs.title`,
  staż „N lat/lata/rok” (polska liczba mnoga, zamienia się tylko „x”, słowa
  wzoru „doświadczenia komercyjnego” zostają), profil = pogrubienia z sekcji
  „Dlaczego nasz kandydat” CV firmowego pary (`candidate_stage_cvs.branded_draft_html`,
  najnowsze), a bez niego umiejętności obowiązkowe rekrutacji, które osoba ma
  w profilu; dostępność „MM.RRRR” z daty dostępności (data z przeszłości =
  bieżący miesiąc) albo z okresu wypowiedzenia od `business_today()`
  („01.2027 (3 mies. wypowiedzenia)”); lokalizacja = `candidates.city`.
  Dostępności z karty rekomendacji karta nie bierze — `recommendation_cards`
  wolno importować tylko modułom z listy w `test_recommendation_cards.py`.
- **Wynagrodzenie za 1 MD:** godzinowa × 8, dzienna bez zmian, miesięcznej
  karta nie przelicza (409 z prośbą o godzinową albo dzienną), tylko PLN.
  Źródło: stawka wpisywana właśnie w przeglądzie (parametry `client_rate`,
  `client_rate_unit`, `client_rate_currency`), a bez nich — ostatnia zapisana
  stawka do klienta pary (`latest_client_rates`). Bez stawki plik się nie
  pobiera: 409 „Wpisz stawkę do klienta — bez niej karta nie ma wynagrodzenia.”
  Ekran przelicza MD na żywo z pola „Stawka do klienta” i pokazuje „tylko DL”,
  gdy jest puste.
- **Poprawki DL-a** (poziom, staż, profil, dostępność, lokalizacja) leżą per
  para w `candidate_client_forms` z `kind = 'cover'` (bez `job_file_id`;
  unikalność `(candidate_id, job_id, kind)`, bez CHECK na `kind`). Poprawka
  wygrywa z wartością wyliczoną; pusta = z powrotem wartość wyliczona. Imienia,
  roli i wynagrodzenia DL tu nie poprawia (422). Zapis = uprawnienie do stawki
  do klienta (`resolve_client_rate_write`) i dostęp do rekrutacji; audyt
  `cover_sheet_saved` niesie tylko nazwy pól, bez wartości.
- **Po wysyłce** panel osoby ma „Karta (Word)” przy „Do klienta” (tylko
  u klienta z wzorem i dla ról ze stawką do klienta) — plik z zapisaną stawką.

Trasy (`api/cover_sheets.py`, bramki w `tests/data/authz_golden/cover_sheets.json`):

- `GET/PUT/DELETE /api/clients/{id}/cover-sheet-template` — jak odczyt i zapis
  reguły CV klienta (`client_cv_rules`: „Klienci: dodawanie i edycja”, sekcja
  Delivery, dostęp do klienta);
- `GET /api/candidates/{cid}/recruitments/{jid}/cover-sheet` — `{enabled: false}`
  u klienta bez wzoru, inaczej pola z wartością, źródłem, `to_check`, układ
  kartki do podglądu i stawka za MD;
- `PUT …/cover-sheet` — poprawki DL-a;
- `GET …/cover-sheet/docx` — plik Word (`nosniff`, nazwa przez
  `content_disposition`).

Front: `lib/api/coverSheet.ts`, `components/v2/recruitment/dl-review/ClientCoverSheet.tsx`,
`components/cv-rules/CoverSheetTemplateSection.tsx`. Migracja `0626`, DDL
w `services/cover_sheet_schema.py`, lustro w `entrypoint.sh` po
`candidate_client_forms`.

## Zasady centralne nie blokują wzoru (29.10.2026, po wdrożeniu)

Na produkcji `CV_CENTRAL_POLICIES_ENABLED` przełącza edytor reguły CV w widok
„zarządzane centralnie” i daje 403 na każdy zapis reguły
(`_require_client_rule_access`). Wzoru karty katalog zasad nie prowadzi —
trasy wzoru wołają bramkę z `central_lock=False` (graf klienta i uprawnienie
„Klienci: dodawanie i edycja” dalej obowiązują), a sekcja „Karta przed CV
(Word)” stoi także w widoku zasad centralnych (`CvRuleEditor`). Bez tego
wzoru nie dało się wgrać: pierwsza próba na produkcji po #2835.

## Profil kompetencji: same technologie (30.10.2026)

Decyzja Artura po pierwszej karcie na produkcji: generator pogrubia w „Dlaczego
nasz kandydat” także zdania o stażu i dziedzinie („Posiada 6 lat doświadczenia
komercyjnego”, „sektorze bankowym”). Profil bierze tylko krótkie nazwy
technologii (`cover_sheet._is_technology`: do 3 słów, jedno z wielką literą,
cyfrą albo znakiem, bez słów o latach i doświadczeniu), najwyżej 8. Dziedzinę
DL dopisuje ręcznie.
