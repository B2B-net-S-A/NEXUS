# Jarvis mówi, czego brakuje (27.10.2026)
<!-- indeks: report_gap i tabela jarvis_gaps, `skipped` w /api/search/global, imię+nazwisko w wyszukiwarce, polskie znaki, telefon, kategoria people, lista możliwości roli w /status -->

Decyzja Artura z 27.10.2026 po przeglądzie 32 rozmów z produkcji (30 dni):
ludzie mówili, że Jarvis „nic nie wie”. W 8 rozmowach odpowiedział „nie ma”,
choć osoba albo klient był w bazie. Przyczyny: wyszukiwarka nie znajdowała
„Imię Nazwisko”, a pusty wynik w kategorii, której rola nie widzi, wyglądał
jak „nie istnieje”. Makiety: prywatny artefakt `Sh6MLtWt4jLm9UNLn1GedS`.

- **`GET /api/search/global` i `GET /api/search/`** dopasowują kandydata także
  po „Imię Nazwisko” i „Nazwisko Imię” (`_candidate_full_name_match`).
  `global` zwraca `skipped` — kategorie, których rola nie widzi (rekruter:
  `clients`). Pusty wynik w takiej kategorii to „nie masz dostępu”, nie „nie ma”.
- **Karta „Tego nie zrobię”**: narzędzie `report_gap` (tier `link`, obsługa
  w `agent._handle_tool` jak `show_on_screen`). Trzy rodzaje: `no_access`,
  `not_supported`, `no_data` (`services/jarvis/gap_schema.py`, lustro
  `GapKind` we froncie). Serwer zapisuje wiersz w `jarvis_gaps` (0527, lustro
  w `entrypoint.sh`), „Zgłoś, że tego potrzebuję” ustawia `reported_at`
  (`POST /api/jarvis/gaps/{id}/report`, tylko własna karta). Admin czyta listę
  `GET /api/jarvis/gaps` — z rolą pytającego, bez nazwiska. Wiersz żyje tyle,
  co rozmowa (kaskada), więc retencja 30 dni i usunięcie kandydata go zabierają.
- **Nie dopisuj zdarzeń do `jarvis_ui_events`** po „brakach”: tabela ma CHECK
  na listę zdarzeń, a nowa wartość bez migracji CHECK-a wpada w 500 po cichu
  (telemetria połyka błąd). Braki mają własną tabelę.
- **Prompt**: nigdy samo „nie mogę / nie znalazłem” — `report_gap` z drogą
  dalej; na profilu kandydata najpierw ten profil; nie oceniać ID po wyglądzie;
  `explain_match` bez pytania o zgodę na koszt (NEXUS nie ma limitów AI).
- **Pusty panel** pokazuje „Sprawdzę od razu / Przygotuję / Tego nie zrobię”
  z `GET /api/jarvis/status` → `capabilities`, liczone z TYCH SAMYCH narzędzi
  roli co dla modelu (`_allowed_tools`, `services/jarvis/capabilities.py`).
  Nowa pozycja = wpis w `READ`/`WRITE` z nazwą istniejącego narzędzia
  (test `test_every_listed_tool_exists`).

## Polskie znaki, telefon i „Ludzie” w wyszukiwarce (07.11.2026)

Przegląd 146 pytań do Jarvisa (23.09–06.11.2026): po poprawce z 27.10 zostały
trzy „nie ma”, choć rekord był w bazie. Makiety: prywatny artefakt
`SM5Q8dK2temXWcc6GxUCZf`, sekcja 3.

- **Polskie znaki.** Imię, nazwisko, e-mail i pełne imię z nazwiskiem (obie
  kolejności) idą przez `polish_folded_ilike` w `GET /api/search/global`
  i `GET /api/search/` (`_candidate_quick_match` w `api/search.py`), jak lista
  rekrutacji i ⌘K. „Jerzy Leśniawski” znajduje „Lesniawski” i odwrotnie.
- **Telefon.** Ta sama gałąź kandydatów dopasowuje numer po samych cyfrach
  (`predicates.phone_digits_clause`: spacje, `+48`, ostatnie 9 cyfr). Bramka
  gałęzi = bramka profilu (`CandidatePIIAccess`: sekcja Kandydaci albo
  Rekrutacje ≥ odczyt i rola z `CANDIDATE_READ_ROLES`), który telefon i tak
  pokazuje. Odpowiedź wyszukiwarki numeru nie zwraca.
- **Kategoria `people`.** Konta z kartoteką w statusie z katalogu
  (`DIRECTORY_STATUSES`, bez `exited`), po `User.name`/`User.email` bez
  polskich znaków; `id` to `user_id`, `url` = `/people/{id}`, `subtitle` =
  stanowisko, dział albo e-mail (pola wizytówki z `card_payload`). Bramka
  `hr_gates.people_directory_open` — ta sama reguła co
  `require_hr_people_reader()` (`GET /api/hr/people`): moduł `people` otwarty
  i kartoteka albo uprawnienie z grupy „Ludzie” (Finanse mają „Płace”).
  Wyłączony program HR = brak kategorii i brak wpisu w `skipped`; program
  włączony, a konto bez dostępu = `skipped: people` („nie masz dostępu”).
- **Czego to nie daje.** Jarvis nie ma narzędzia do raportu godzin innej osoby
  (jest tylko `my_month`). Po znalezieniu osoby w `people` mówi to przez
  `report_gap` (`not_supported`) z ekranem `/people/{id}`, zamiast „nie ma”.

