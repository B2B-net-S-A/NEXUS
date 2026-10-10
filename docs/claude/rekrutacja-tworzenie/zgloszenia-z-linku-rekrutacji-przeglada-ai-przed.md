# Zgłoszenia z linku rekrutacji przegląda AI przed „Nowi” (0404, 29.09.2026)

Decyzje Artura 29.09.2026. Kod: `services/application_screening.py` (reguła
i pętla), `tasks/application_screening.py` (co 30 s, heartbeat),
`api/application_screenings.py`, front `components/v2/jobs/ScreenedOutSection.tsx`,
harness `/preview/job-board-screening`.

- **Link `kind='job'` NIE otwiera procesu w requeście** (oba formularze —
  `submit_application`). Kandydat, CV, zgoda, źródło (`CandidateSourceEvent`
  od 0404 także dla osoby już w bazie) i wiersz `application_screenings`
  (`pending`, tekst CV w `cv_text`) w jednej transakcji; dzwonek
  `new_application` dopiero po decyzji. Stały link rekrutera bez zmian.
- **Werdykt liczy KOD** (`decide`): `not_fit` wyłącznie, gdy GPT-6 Luna
  (`AIFeatureKey.application_screening`, F27) mówi `not_fit` z co najmniej
  jednym cytatem obecnym w CV/profilu ORAZ must-have technologie
  (`search_dealbreaker_inputs` + `must_text_evidence`) są w CV w < 50% (albo
  rekrutacja ich nie ma). Powód z cytatem spoza CV wypada. Awaria modelu,
  brak CV = `unclear` → osoba wchodzi do „Nowi” („AI nie oceniło”). AI nie
  może zgubić kandydata; nie zamieniaj tego w bramkę „w razie wątpliwości
  odrzuć”.
- **Wyniki:** `added` (proces „Nowi”, `entry_meta` kind
  `application_screening` → plakietka „AI: pasuje / do sprawdzenia / nie
  oceniło”), `screened_out` (baza + „Odrzuceni przez AI (N)” w „Nowi”
  z „Dodaj mimo to”), `blocked` (czarna lista, weto HM —
  `submission_block_reason`, teraz także dla nowego e-maila), `job_closed`,
  `already_in_job`; 3 nieudane przebiegi = `failed`, też na liście odrzuconych.
- **Wiersz nowego kandydata czeka na odczyt CV** (`cv_parsed_at`, najwyżej
  10 min); istniejący kandydat gotowy od razu. Dzierżawa `claimed_until`,
  model nigdy w otwartej transakcji. Rano jeden skrót
  `application_screening_digest` na rekrutację do prowadzącego.
- **`APPLICATION_SCREENING_ENABLED=false`** = zachowanie sprzed 0404; pętla
  biegnie dalej i dodaje oczekujące bez modelu. W testach flaga jest
  wyłączona autouse-fixturą (`conftest.py`). **Domyślnie OFF** — włącza się
  ją workflowem „Coolify set env” dopiero po pomiarze
  `python -m scripts.eval_application_screening --per-group 40` w kontenerze
  backendu (ta sama `assess`, bez zapisu decyzji): grupa `verified` (osoby
  zweryfikowane w rekrutacji) nie może mieć ani jednego `not_fit`, a każde
  `not_fit` z grupy `posting` (aplikujący z ogłoszeń Traffita) przegląda
  człowiek. Historycznych zgłoszeń z linków prawie nie ma (1 do 29.09.2026),
  stąd te dwie grupy. Zmiana promptu albo progu = ponowny pomiar.
