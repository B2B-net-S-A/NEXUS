# Notatki: przypięcie, odpowiedzi, automaty bez notatek (0399, 29.09.2026)

Decyzje Artura 29.09.2026 — historia kandydata ma być tym, co napisali ludzie.

- **Automaty nie piszą notatek.** Auto-match z CV (`auto_match_service`)
  i scraper JJIT/RocketJobs (`integrations/jjit/nexus_client.py`, pole
  `auto_match` w `proposals/bulk`, przyjmowane WYŁĄCZNIE od tokenu integracji)
  zapisują wynik w `recruitment_processes.entry_meta`
  (`services/process_entry_meta.py`); tablica i zakładka „Rekrutacje” niosą
  `entry_auto_match` → plakietka „Auto-match 67/100 · JJIT”. Nie wracaj do
  `note=` w automacie.
- **Dopasowania z portali NIE zakładają kart (decyzja Artura 30.09.2026).**
  Zmierzone: 1 819 kart scrapera na „Ogłoszeniach”, każda osoba w ~3,9
  rekrutacjach, dalej przeszły 2. `proposals/bulk` od tokenu integracji Z polem
  `auto_match` idzie przez `proposals_bulk.propose_candidates_for_job`: te same
  twarde bramki co dodanie (kandydat istnieje, czarna lista, już w rekrutacji,
  weto HM — w `skipped`), potem propozycja `job_board` w „Do przejrzenia”
  (wynik = `score`, `evidence.auto_match` + `matched_must`, `cv_revision` =
  `candidate_revision`). Odpowiedź: `added=[]` + nowe `proposed`/`total_proposed`;
  runner JJIT liczy `proposed` jako dopasowanie. **Integracja BEZ `auto_match`
  też nie zakłada karty (06.10.2026)** — `proposals/bulk`, `assign-to-job`
  i `/move` dla nowej osoby dają propozycję `job_board` bez wyniku, chyba że
  jest dowód zgłoszenia do TEJ rekrutacji (`services/integration_intake.py`:
  `application_submissions` z `matched_candidate_id`, źródło `posting` z tym
  `job_id`, notatka `application_form` z tym `job_id`); `/move` odpowiada wtedy
  202, a `/bulk-move` takiej osoby nie przyjmuje (422). Scraper wysyła źródło
  i notatkę formularza BEZ `job_id`, więc dziś każde jego dodanie bez
  `auto_match` (także zgłoszenia z pracuj.pl do konkretnej rekrutacji) jest
  propozycją — kartę daje dopiero dowód z `job_id`. Człowiek dodaje kartę
  jak dotąd. Front: etykieta „Z portalu (JJIT/RocketJobs)”. Stare karty przenosi
  jednorazowo `POST /api/admin/proposals/convert-integration-cards?dry_run=true`
  (admin; próba oddaje liczby per rekrutacja, `blocked_by` per powód i ≤ 20
  przykładów z samymi ID) → `dry_run=false&expected=N` (w tle; wymaga próby
  z 7 dni zrobionej PO ostatnim deployu i `expected` = liczbie par teraz;
  `GET …/status`). `mode=delete` (06.10.2026) — ta sama reguła dla kart na
  rekrutacjach ZAMKNIĘTYCH (z Traffita i z NEXUSA): karta znika drogą „Usuń
  z rekrutacji” (`reason=job_board_closed_job_cleanup`), bez propozycji,
  osobne klucze stanu i odwrócenia (`…closed_cleanup_2026_10`). Propozycja
  z przeniesionej karty ma `first_seen_at` = data otwarcia procesu. Bierze WYŁĄCZNIE nietknięte karty: rekrutacja opublikowana
  spoza Traffita, jeden otwarty proces `auto_match` z plakietką integracji
  (`source` ≠ `nexus`), jeden wiersz etapu `posting` bez screeningu/scorecardu,
  bez notatek z tą rekrutacją, `application_screenings` i `screening_notes`,
  CV etapu tylko jako automatyczna migawka z dodania, i zero wierszy w tabelach
  z FK do tego etapu/procesu/migawki (lista FK z `pg_constraint` w chwili
  biegu). Na parę w savepoincie ta sama droga co „Usuń z rekrutacji” (archiwum
  `candidate_stage_removals` → `void_process` → `delete_voided_stage_history`
  → zamknięcie okazji kontaktu; migawka etapów ze wspólnego
  `candidate_stage_removal_snapshot`), wiersze skrzynki pary `added` wracają
  do `proposed`, potem propozycja `job_board` z wynikiem z `entry_meta`. Pliki CV
  kandydata zostają. Dane do odwrócenia pod
  `repair_details_job_board_cards_to_proposals_2026_09`
  (`services/job_board_cards_to_proposals.py`).
- **Stare notatki automatów = `external_source='system'`** (jednorazowo,
  znacznik `0399_auto_match_notes_system`; SQL w `note_threads_schema.py`,
  lustro w `entrypoint.sh`) — nic nie jest kasowane. Lista notatek niesie
  `is_system`, UI chowa je za „Pokaż systemowe (N)”, podgląd kandydata ich
  nie pokazuje.
- **Notatki jednej rekrutacji = ta sama lista co w profilu**
  (`candidate-profile/JobNotesList.tsx` na `NotesList`, akcje
  `useNoteActions`): dok osoby na Tablicy, panel osoby i warsztaty kroków
  (`DockNotesPanel`) pokazują odpowiedzi, przypięte pierwsze i systemowe za
  przełącznikiem. Nie dokładaj czwartej, uproszczonej listy.
- **Zwinięta notatka liczy wyłącznie linie z tekstem**
  (`visibleNoteLines`/`collapsedNotePreview`): puste akapity Traffita
  (`<p>&nbsp;</p>`) dawały podgląd z samych wzmianek i „…”.
- **Przypięcie wspólne dla zespołu:** `POST/DELETE /api/notes/{id}/pin`
  (bramka `CandidateWriteAccess` jak dodanie notatki, `Activity`
  `note_pinned`/`note_unpinned`, odpowiedzi nie da się przypiąć). Przypięte są
  pierwsze na liście, w szybkim podglądzie i w doku osoby w rekrutacji
  (`PinnedCandidateNotes`, `?pinned_only=true` — z KAŻDEJ rekrutacji).
- **Odpowiedzi: `notes.parent_note_id`, jeden poziom** (odpowiedź na odpowiedź
  = 422), CASCADE z notatką główną. Serwer nadpisuje kandydata i rekrutację
  z notatki głównej, a **kontraktu NIGDY nie dziedziczy** (`contract_id` =
  NULL): notatki kontraktu pisze DL w zakresie klienta (F03), a `POST
  /api/notes` wymaga tylko zapisu kandydata; oś kontraktu dodatkowo pomija
  odpowiedzi. Lista (`GET /api/notes`) zwraca WYŁĄCZNIE notatki główne
  z `replies[]`, `total` ich nie liczy, `notes_count` kandydata też nie; oś
  czasu zagnieżdża odpowiedzi. Autor notatki głównej dostaje `note_reply`
  (kategoria „Wzmianki”, sekcja Sourcing, bez maila); usunięcie odpowiedzi
  (także kaskadą z notatką główną) czyści jej dzwonek jak wzmiankę.
  Usunięcie kandydata kasuje odpowiedzi PRZED kaskadą ORM.
- **„Historia” otwiera się na „Notatkach”** (`?tab=activity` bez filtra);
  `?tab=timeline`/`podglad`/`activity=timeline` dalej otwierają „Wszystko”.
  Licznik zakładki = notatki ludzi. Oś czasu nie pokazuje `traffit:Email`,
  `traffit:Reply`, `traffit:Rozmowa telefoniczna`, `traffit:Spotkanie` —
  promocja robi z nich notatki. Reguły listy: `lib/candidate-notes-view.ts`.
