# Fakty z notatek rekruterów na profilu kandydata (22.09.2026)

Nocna pętla `notes_insights_sync` (włączona na prodzie) czyta notatki
kandydata (także przeniesione z Traffita) i zapisuje fakty w
`cv_extracted_data._notes_insights`. Profil pokazuje je w karcie
„Z notatek rekruterów” (`CandidateNotesFactsCard`, `GET/POST
/api/candidates/{id}/notes-facts[/apply]`), a tryb pracy ma pole w pasku
faktów (`PATCH /api/candidates/{id}/work-mode`). Jedna reguła:
`services/candidate_notes_facts.py` (lustro frontu: `lib/work-mode.ts`).

- **Tryb pracy wynika z dni w biurze:** N dni akceptuje też mniej (0 =
  zdalnie, 1–4 = też hybrydowo, 5+ = też stacjonarnie) — ta sama reguła co
  bramka dni w biurze w wyszukiwaniu. Dni: liczba podana wprost > „tylko
  zdalnie” (0) > „stacjonarnie” (5); „hybrydowo” bez liczby zostawia dni puste.
  Ekstrakcja (prompt `v5-work-modes`, pole `preferences.work_modes`) wypełnia
  `preferences.remote_modes` i `max_onsite_days_per_week` WYŁĄCZNIE, gdy pole
  jest puste — każde osobno.
- **Stawka z notatek NIGDY nie zapisuje się sama, jeśli nie jest PLN/h.**
  Karta pokazuje odpowiednik (MD ÷ 8, miesiąc ÷ 168), zapis dopiero po
  „Zapisz w profilu”, z wersją stawki (412 przy zmianie w innym oknie),
  `source="notes_confirmed"` + `_manual_override_rate`. Inna waluta — bez
  przeliczenia.
- **„Zapisz w profilu” wskazuje POLE, wartość wylicza serwer** z zapisanych
  faktów (rate, work_mode, contract_form, availability, office_cities).
  Zastrzeżenia do klientów są tylko pokazywane — nie tworzą konfliktu.
- **Puste pola profilu wypełnia JEDNA reguła** (07.10.2026,
  `services/notes_profile_fill.py`: nocna ekstrakcja i jednorazowe
  `POST /api/admin/notes-insights/profile-fill` — próba → `expected=` →
  paragon `notes_profile_fill_backfill_2026_10` + `repair_details_…`). Tylko
  puste pola; bez progu czasowego, ale **dostępność liczona od DNIA NOTATKI
  O DOSTĘPNOŚCI** (`notes_days(rows).availability`: najnowsza notatka wejścia,
  której treść mówi „od zaraz / wypowiedz… / dostępn… / start…”; dzień =
  `coalesce(source_created_at, created_at)`): „od zaraz” = ten dzień, okres
  wypowiedzenia = ten dzień + okres. Bez takiej notatki „od zaraz” i okres
  wypowiedzenia NIE dają daty; pełna data i miesiąc („11.2026”, „od
  listopada”) tak — z „stan na” = dzień najnowszej notatki. Noc i domknięcie
  historii liczą to JEDNĄ funkcją na tym samym zbiorze (`load_note_rows` /
  `load_note_rows_bulk` — notatki czytane przez odczyt AI). Przegląd #2062:
  „od zaraz” z 2023 + „zna Pythona” z 30.09.2026 dawało „stan na 30.09.2026”.
  Znacznik `_availability_from_notes` (`date`, `as_of`, `basis`) — profil
  pokazuje „z notatek · stan na DD.MM.RRRR”; nowsza notatka poprawia datę,
  którą wpisały notatki, poprawki człowieka nie rusza. Lista `/candidates`
  i szybki podgląd dostają to samo jako `availability_from_notes` /
  `available_from_notes` (`{as_of, basis}`, `availability_origin` — liczone
  z załadowanego `cv_extracted_data`, bez zapytania per wiersz) i pokazują
  drugą linię „z notatki · DD.MM.RRRR” z opisem w dymku. **Data wpisana przez
  notatki znika razem ze źródłem:** usunięcie ostatniej czytelnej notatki
  (`clear_notes_facts`, obok stawki) i nocna ekstrakcja, której fakty już tej
  daty nie dają (`release_stale_availability=True` w `apply_insights`),
  zerują `availability_date` i znacznik — tylko gdy profil nadal ma datę ze
  znacznika. Domknięcie historii dat nie zdejmuje. Do 07.10 datę dawał
  wyłącznie ISO w `available_from` (6 327 osób z dostępnością w notatkach
  miało pustą datę). **Języki** z `languages_observed` zapisuje writer ze
  źródłem `notes` (CHECK `ck_candidate_languages_provenance`, 0423): tylko
  DOPISUJE język, którego profil nie zna — wiersza z CV, Traffita ani
  ręcznego nie zmienia (także poziomu), nigdy nie usuwa (nagrobek blokowałby
  później język z CV). Status „szuka aktywnie” z „od zaraz” stawia tylko
  nocna ścieżka, nie domknięcie historii.
- **Doganianie starszej wersji promptu:** po kandydatach ze zmienionymi
  notatkami bieg dobiera najwyżej `NOTES_INSIGHTS_SYNC_UPGRADE_LIMIT` (700)
  kandydatów z `_extractor` innym niż bieżąca wersja (bez wierszy
  `_no_content`). ~16 tys. wierszy ≈ 3 tygodnie; na GPT-6 Luna ~0,0005 USD/kandydata (pomiar 03.10.2026; 0,004 USD to stawka sprzed 25.09).
  Zmiana promptu = bump `PROMPT_VERSION`, a doganianie ruszy samo.
