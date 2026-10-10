# Przekazanie, propozycje i Champion po audycie 06.10.2026

Raport: `docs/audits/2026-10-06/rekrutacja-przekazanie-i-wyszukiwanie.md`.
Decyzje Artura: bez maila przy przypisaniu; propozycje wygasają także przy
zamknięciu rekrutacji (status `expired` i telemetria otwarcia skrzynki są
z #2058 — „Propozycje z bazy” bez limitu 60).

- **Dzwonek „dostałeś request” ma JEDNO miejsce:**
  `_sync_work_assignments_with_owner` (`api/jobs.py`) przy każdej zmianie
  prowadzącego (`/owner`, `/claim`, okno edycji, przekazanie, `POST /api/jobs`),
  bez dzwonka dla siebie i dla poprzedniego prowadzącego. Dodanie z pulpitu
  (`POST /api/request-board/jobs/{id}/people`) dzwoni przez `_notify_assigned`,
  ale nie do osoby, która już przy requeście pracuje. Nie dokładaj drugiego
  `notify_assigned` w ścieżce przekazania.
- **„Nowe requesty dla Ciebie”** (`board_flow._new_requests`, pole
  `flow.new_requests`): aktywne przypisanie z ostatnich `NEW_REQUEST_DAYS` (3)
  dni, rekrutacja w pracy, a od przypisania nikt nie przesunął karty
  (`candidate_stages.moved_by` po `assigned_at`). Pierwszy ruch zdejmuje wiersz.
- **Kolejka Head of Recruitment pokazuje opublikowane bez przekazania**
  (`new_job_leads._not_handed_off`, `pending_reason = "not_handed_off"`,
  `is_open` nie `True`, bez okna 7 dni, na końcu listy).
- **Uczestnicy kategorii (`auto_cc`) nie dostają dzwonków rekrutacji (D7)**
  — producenci dzwonków wołają `list_job_member_ids(...,
  include_category_participants=False)`; domyślne `True` zostaje dla dostępu.
  Odbiorcami zmiany Championa jest też Delivery Lead rekrutacji.
- **Poranny dzwonek „Do przejrzenia”** (`services/proposals_morning_bell.py`,
  wołany z `run_all_triggers`): dni robocze 8–17, raz dziennie, jeden na
  (rekrutacja, Rekruter z `job_team.working`), pary z `full_base` i `new_cv`
  od POPRZEDNIEGO dzwonka (`app_settings['proposals_morning_bell_state']`),
  a bez niego od 8:00 poprzedniego dnia roboczego, najwyżej 7 dni wstecz
  (`window_start` — stałe 24 h gubiło propozycje z weekendu i świąt);
  `job_proposals.fresh_open_pairs` — te same reguły widoczności co skrzynka,
  trzy nazwiska w treści. Zastąpił dzienny skrót z nowych CV
  (`auto_match_service._notify_proposals` usunięty — szedł tylko do
  `recruiter_id`/`tac_id`). Poniedziałkowy skrót DL liczy `open_counts_for_jobs`.
- **Dodanie do rekrutacji przez człowieka zamyka propozycję także poza
  „Dodaj”** — `open_process` stawia `added`, gdy `entry_source` jest
  w `candidate_claim.HUMAN_ENTRY_SOURCES` (albo jawne `mark_proposals=True`);
  integracja i automat — nie (decyzja z 07.10.2026). `add_candidates_to_job`
  przekazuje własne `mark_proposals`.
- **Każde zamknięcie rekrutacji wygasza jej otwarte propozycje**
  (`expire_open_for_job`: `close_job_core`, PATCH statusu w oknie edycji,
  zamknięcie przy usunięciu klienta) — nowa ścieżka zamykająca rekrutację woła
  to samo. `added` i `dismissed` zostają; osoba wraca jako `proposed` dopiero
  z kolejnym przeglądem. Jednorazowo `job_proposal_closed_expiry` (marker
  `job_proposals_closed_jobs_expired_2026_10`, paragon = liczby).
- **„Pomiń zaznaczone”**: `POST /api/jobs/{id}/proposal-inbox/dismiss-bulk`
  (≤ 100 osób, powód obowiązkowy jak przy pojedynczym, osoby spoza skrzynki
  i już w rekrutacji wracają w `skipped`).
- **„Przypisz do rekrutacji” z listy i profilu kandydata** (człowiek) idzie
  przez `proposals_bulk.add_candidates_to_job`: etap „Nowi”, blokada 12 h,
  `entry_source = added_manual`, `mark_proposals=True`, telemetria
  `candidate_list`. Kształty odpowiedzi
  (200 `assigned` / `already_in_pipeline`, 409) bez zmian. Integracja zostaje
  przy starej ścieżce. Telemetria dodań niesie id procesu w `event_id`
  (`latest_process_ids`), integracja ma źródło `integration`.
- **Zapis Championa ma ochronę przed nadpisaniem:** `PUT …/champion-profile`
  przyjmuje `expected_profile_hash` (= `champion_intake.profile_hash`,
  skrót samego `champion_profile`, zwracany jako `profile_hash`); rozjazd = 409
  `champion_profile_conflict` z aktualnym profilem. Bez pola — jak dotąd.
  Odpowiedź zapisu niesie `notices`.
- **Krytyczne, które przestało być technologią** (zmienione słowa wiersza)
  nie daje 422: zostaje „musi mieć”, zapis zwraca uwagę w `notices`; bez
  pozostałych krytycznych pole znika („nie zdecydowano”).
- **Kolumny `must_skills`/`nice_skills` rekrutacji z wierszami wymagań idą
  wyłącznie za Championem:** PATCH z innymi nazwami i „Kryteria”
  (`refresh-criteria`) = 409 (`ROWS_OWN_COLUMNS_DETAIL`); zapis z wierszami
  zawsze wyrównuje kolumny z etykietami wierszy.
- **Wiersze wymagań:** najwyżej 10 „musi mieć” — nadmiar schodzi do „mile
  widziane” (do 20), reszta trafia zdaniem do `stack.notes` („Nie zmieściło się
  w wymaganiach: …”). „A lub B” w słowie wiersza dzieli się na warianty,
  gwiazdka przy technologii ze słownika znika, jednoliterowe technologie ze
  słownika („C”, „R”) są dozwolone. Odczyt maila uzgadnia słowa z odmianą
  (`services/skill_inflection.py` na regułach `dz_review`) i mówi w uwagach,
  które wiersze pominął jako nieobecne w treści.
- **Szablon od innego klienta** przenosi z Championa wyłącznie `stack.notes`.
- **Tytuł dla rekrutera bierze tylko technologie ze słownika** (P10):
  `job_working_title._is_title_technology` = `critical_eligible` etykiety
  całego wiersza, a podgląd na `/jobs/new` filtruje wiersze po `eligible`
  z `critical-suggestion` (`suggestedWorkingTitle(form, criticalInfo)`). Bez
  słownika (serwer) i przed odpowiedzią (front) — wszystkie wiersze, jak dotąd.
- **`headcount: null` w `POST /api/jobs` = „nie podano”** (bramka odmawia);
  pole pominięte zostaje przy dawnym 1.
- **Indeks:** kategoria nadana po wektorze (`assign_cc_after_embed`) kolejkuje
  ponowny zapis punktu z kategorią. Notatka z „Karty z notatki” ma
  `external_source = card_note_import` (rodzaj `human`), a odpowiedzi z niej
  czytają arkusz tylko z bieżącej próby procesu (`screening_window`).
