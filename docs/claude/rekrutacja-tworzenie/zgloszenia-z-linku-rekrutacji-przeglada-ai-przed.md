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

## Osoba z linku jest właściciela linku (etap 2 linków, 19.10.2026)

Decyzje Artura A i B z 19.10.2026, makiety
https://claude.ai/artifact/8aVZkzVxkVnkVVNBUDgL4h (plansze 2a i 2b).

- **Blokada 12 h i właściciel procesu = właściciel linku**
  (`candidate_claim.link_claim_kwargs` → `open_process(claim_for_user_id=…,
  process_owner_user_id=…)`) we wszystkich trzech miejscach, które otwierają
  kartę ze zgłoszenia: nowy e-mail bez przeglądu AI (`public_apply`), osoba
  już w bazie (`_ensure_submission_process(link_owner_id=…)`) i decyzja pętli
  (`open_in_new`). „Dodaj mimo to” też zakłada blokadę dla właściciela linku
  z `context["link_owner_id"]` — klikający zostaje autorem ruchu
  i `overridden_by`. Ręczne rozstrzygnięcie zgłoszenia przez recenzenta
  (`resolve_application_submission`) bez blokady, jak dotąd.
- **12 h liczy się od wejścia karty do „Nowi”** (po przeglądzie AI), nie od
  wysłania formularza. Nieaktywne konto właściciela linku = bez blokady i bez
  właściciela z linku. Admin, DL i HoR przejmują jak przy ręcznym dodaniu.
- **Kredyt KPI bez zmian (decyzja B):** `kpi_eligible=None`,
  `credit_user_id` dopiero przy pierwszej weryfikacji. Liga i Cele liczą jak
  dotąd; właściciel procesu to pole operacyjne.
- **Atrybucja:** `entry_meta.link_owner_id` (kind `application_link` bez
  przeglądu AI, `application_screening` z przeglądem;
  `process_entry_meta.application_link_owner_id`). Stempel zostaje, gdy
  blokada wygaśnie albo karta zmieni właściciela — na nim stoi plakietka
  „Z Twojego linku” / „Z linku: Marta” na Tablicy (`entry_link_owner_id`,
  `entry_link_owner_name`) i etap 4 (statystyki „Pozyskani z linków”).
- **Dzwonki** (`public_apply._notify_owner`, oba tryby przeglądu): nowa
  karta dopisuje „Jest w „Nowi” i jest Twoja do HH:MM”. Osoba już w tej
  rekrutacji (wynik `already_in_job` albo karta sprzed zgłoszenia przy
  wyłączonym przeglądzie): karta i blokada prowadzącego bez zmian, właściciel
  linku dostaje „jest już w tej rekrutacji — prowadzi X, etap Y”, a
  prowadzący (aktywna blokada, inaczej właściciel otwartego procesu), gdy to
  ktoś inny, dzwonek „Twoja osoba zgłosiła się ponownie”
  (`application_screening.existing_card`).
- **Ślad ponownego zgłoszenia na karcie** (makieta 2a): osoba już w
  rekrutacji, która zgłosi się z czyjegoś linku, ma w „Nowi” i „Screening”
  plakietkę „Zgłosił się też z Twojego linku” (u innych: „Zgłosił się też
  z linku: Marta”), obok ewentualnej „Z linku …” linku, który kartę
  przyprowadził. Pole karty `reapplied_via_links` = `[{owner_id,
  owner_name}]` liczy `pipeline._link_reapplications` jednym zapytaniem dla
  całej tablicy z dwóch źródeł: `application_submissions` (status `linked`
  albo `merged`, właściciel linku po `invite_link_token_sha256` →
  `candidate_invite_links.created_by`) i `application_screenings`
  (`already_in_job`, `context.link_owner_id`). Liczą się tylko zgłoszenia
  **po otwarciu karty** (`created_at > opened_at` procesu — zgłoszenie, które
  kartę otworzyło, jest starsze albo z tej samej transakcji) i bez
  właściciela linku ze stempla `entry_meta.link_owner_id`. Nic nie zapisuje,
  karty, blokady ani kredytu KPI nie rusza.

