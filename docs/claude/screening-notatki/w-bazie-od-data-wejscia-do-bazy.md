# „W bazie od” — kiedy osoba trafiła do bazy (13.10.2026)

<!-- indeks: `source_created_at` (0437), „Nowy w bazie” do 14 dni -->

Prośba rekrutera: świeże osoby są najlepsze, więc przy osobie ma być od razu widać, od kiedy jest w bazie
(jak „Dodano” w Traffit). Makiety: https://claude.ai/artifact/8BSoHNnWMcWv6nJEK6aufP. Decyzje Artura 13.10.2026:
wariant A, próg 14 dni, zgoda na pobranie dat z Traffita.

- **Jedna reguła daty** — `backend/app/services/candidate_added_date.py`: „w bazie od” =
  `LEAST(created_at, source_created_at)`. `created_at` to chwila wstawienia wiersza do NEXUSA; dla osób
  z Traffita był to dzień importu (33 824 osoby z 16.04.2026, 9 949 z 04.05.2026). `source_created_at`
  (migracja 0437) to data dodania u źródła — Traffit `created_at` z listy `/employees/`.
- **Nie nadpisuj `candidates.created_at` datą z Traffita.** Import liczy z niej ponowienia plików
  i CV („pending since”, `importer.py`), a podświetlenie „Nowy” zapisanego wyszukiwania, analityka
  i eksport zostają na surowym `created_at`.
- **Data niedokładna**: brak `source_created_at` przy wierszu z importu (`traffit`, `tr_legacy`) albo
  założonym najpóźniej w dniu pierwszego importu (16.04.2026, Europe/Warsaw). Ekran pisze wtedy
  „przed DD.MM.RRRR · dokładnej daty nie znamy”, nigdy nie pokazuje pigułki, a praktykant nie dostaje
  roku „W bazie od”. Lepiej „przed …” niż dzień importu udający prawdę.
- **Gdzie to widać**: blok „Osoba w bazie” na górze „Notatek i historii” (od kiedy, skąd, kto dodał,
  od kiedy w tej rekrutacji) i wiersz „Dodany do bazy” na końcu historii — `components/v2/person/PersonInBase.tsx`,
  wpięte w `NotesTab`, nie w `PersonNotesHistory` (dok i czytnik historii zostają bez bloku); pigułka
  „Nowy w bazie · N dni” w głowie doku (`PipelineCandidateDock.tsx`, ta sama głowa w rozwiniętym panelu);
  wiersz „W bazie od” w „Kandydat” profilu przed telefonem; plakietka „Nowy · N dni” na karcie
  w „Nowych” i „Screeningu” (`lib/board-card-badges.ts`, klucz `new_in_base`, poza skracanymi do ikon);
  kolumna „Dodano” i kolejność „Najnowsi”/„Najstarsi” listy kandydatów.
- **Próg 14 dni i dni kalendarzowe Europe/Warsaw** liczy `frontend/src/lib/added-to-base.ts`
  (`NEW_IN_BASE_DAYS`). Serwer podaje datę i flagę dokładności, nie decyduje o pigułce.
- **API**: `CandidateResponse` ma `source_created_at`, `added_to_base_at`, `added_to_base_exact`,
  `added_via` — liczone w walidatorze schematu, więc lista, detal i odpowiedzi zapisu mają je same.
  Karta Tablicy (`build_kanban_view`) ma `candidate_added_at`, `candidate_added_exact`,
  `candidate_added_by_name` — to samo zapytanie o kolumny kandydata, nazwiska w zbiorczym zapytaniu
  o użytkowników. Panel bierze pola z `GET /api/candidates/{id}` pod kluczem `candidateQueryKeys.detail`
  (cache doku) — bez drugiej trasy.
- **„Skąd”** (`added_via_label`): pierwszy tag `traffit_source` → „Traffit · <nazwa>”; import zapisał
  nazwę w `domain`, `value` jest puste. Nazwy techniczne tłumaczy `_SOURCE_LABELS`
  (`candidate_quick_view.py`, np. `career_page` → „Strona kariery”). W NEXUSIE — `candidates.source`
  („CV upload”, „E-mail”, „Formularz aplikacyjny”). „Źródło” w profilu przed telefonem to dalej
  wejście do TEJ rekrutacji (`entry_source`), nie do bazy.
- **Sortowanie** listy używa `added_to_base_sql()` — dokładnie wyrażenia indeksu
  `ix_candidates_added_to_base_id` (migracja i `_INDEX_STATEMENTS` w `entrypoint.sh`). Inne wyrażenie
  w `ORDER BY` = skan i sortowanie 65 tys. wierszy.
- **Import z Traffita** zapisuje datę przy INSERT, przy zmianie (`COALESCE` — brak w payloadzie nie
  kasuje) i przy adopcji. `candidate_payload_sha` pomija ten klucz — inaczej najbliższy pełny bieg
  przepisałby 57 tys. kartotek. Istniejące wiersze uzupełnia naprawa:
  `POST /api/admin/traffit/added-dates-repair?dry_run=true&pages=` → raport w `GET …/status`
  → `dry_run=false` (wymaga próby z 7 dni). Przegląd listy `/employees/` stronami po 100, kursor = strona,
  zmienia wyłącznie `source_created_at` (bez `updated_at`), zapis warunkowy, daty sprzed zmiany
  w `repair_details_traffit_added_dates_2026_10`. Kod: `services/traffit_added_dates_repair.py`.
- Harness: `/preview/job-detail` — Anna z Traffita od 2019 (bez pigułki), Jan z importu bez daty
  („przed 16.04.2026”), Piotr i Marek świeżo w bazie (pigułka i plakietka); `/preview/screening-form?state=nowi`
  — wiersz „W bazie od” i pigułka.
