# Jarvis mówi, czego brakuje (27.10.2026)
<!-- indeks: report_gap i tabela jarvis_gaps, `skipped` w /api/search/global, imię+nazwisko w wyszukiwarce, lista możliwości roli w /status -->

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
