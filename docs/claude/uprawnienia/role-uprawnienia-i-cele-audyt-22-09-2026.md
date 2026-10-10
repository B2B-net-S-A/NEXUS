# Role, uprawnienia i cele — audyt 22.09.2026

Raport i decyzje Artura: `docs/roles-permissions-targets-audit-2026-09-22.md`.
Cztery warstwy dostępu: sekcja (`rbac_role_section_permissions`, sufit) → akcja
(`rbac_role_action_permissions`) → guard roli na trasie → capability analityczne.
Reguły, które łatwo cofnąć:

- **Funkcji TAC nie używamy; roli `tac` nie ma od 0411 (02.10.2026)** — jej
  konta są rekruterami (sekcja „Jedna rola „Rekruter”…”). Mutacje kontraktów/klientów/podpisów to
  `DeliveryLeadPlus`; zakres „zespołu DL" liczy się z rekrutacji
  DL (`recruiter_id`, `tac_id`, współpracownicy), nie tylko z `ClientTacAssignment`.
  Alias `TacPlus` usunięty 23.09.2026: rekrutację zakłada/publikuje/zamyka/usuwa
  `DeliveryLeadPlus`, „Prowadzona w NEXUSIE" włącza `RecruiterPlus` + członkostwo,
  szablony maili (POST/PUT) zapisuje admin/HoR/DL. Pełną redakcję rekrutacji
  (`job.update`) daje od 0410 uprawnienie `recruitment_manage` (obok roli TAC:
  `recruitment_access.JOB_FULL_EDIT_LEGACY_ROLES`).
- **Rekrutację ZAKŁADA admin/DL** (`/jobs/new`, capability `job.create`),
  **EDYTUJE też rekruter prowadzący i współpracownicy** — ale tylko treść (opis,
  ogłoszenia, Champion). `GET /api/jobs/{id}` niesie `can_edit` (treść) i
  `can_manage` (status, klient, właściciele, widełki, cykl życia); jedna reguła
  `recruitment_access.job_edit_level`. Front: `lib/job-edit-access.ts`.
- **Stawki w generatorze B2B**: wszystkie widzi admin i Finanse; DL — swój
  portfel; pozostali — tylko umowy, które sami wygenerowali albo z rekrutacji,
  którą prowadzą. Cudzy DOCX = 403. Legacy `user` nie wchodzi do generatora.
- **Finanse zmieniają kwoty** kontraktów, zamówień i linii MD przez
  `MANAGE_FINANCE`; osoba wpuszczona WYŁĄCZNIE przez tę capability dostaje 403
  `finance_amounts_only` na każde pole niebędące kwotą
  (`financial_access.assert_amounts_only`). Front:
  „Edytuj stawki" na kontrakcie wysyła tylko pola kwot.
- **TCM**: Delivery = odczyt, generator B2B = `manage` (0347 dla świeżej bazy).
- **Cele KPI: jeden katalog** `services/kpi_catalog.py` (stare id panelu „Moje
  KPI" to aliasy). Precedencja: osobisty cel → dla KAŻDEJ roli osoby wiersz
  `kpi_role_defaults` albo domyślna z katalogu → MAKSIMUM z ról
  (`services/kpi_targets.py`). Po 0346 tabela ról trzyma tylko świadome
  odstępstwa. Liczby: placementy/mc 1, nowi kandydaci/dzień 5, weryfikacje/dzień 4,
  precyzja 75%, rekomendacje/tydzień 15 (jedna rola od 0411). Edytora w aplikacji
  nie ma — zmiana liczby = zmiana katalogu.
- **Wyścig miesięczny (1500 zł)**: weryfikacje/dzień i precyzja czytane z celów
  KPI; minimum placementów = `insights_scoring_config.monthly_race_min_placements`
  (2, świadomie wyżej niż cel).
- **KPI rozmów milczy przy `CLOUDTALK_ENABLED=false`.** Raport PowerCalling
  11:45 i `GET /api/reports/power-calling` usunięte 23.09.2026 (do 22.09 HoR
  dostawał codziennie tabelę „0/15 ❌"); typ `powercalling_kpi` zostaje dla
  historycznych powiadomień.
- **Cele liderów**: `GET /api/kpis/me/goals` — DL: kwartalne hit ratio (30%) i
  placementy portfela liczone tą samą funkcją co liga DL
  (`competitions.dl_portfolio_counts`); HoR/TCM: cele zespołu (suma celów ludzi).
  Hit ratio bez rekrutacji = `null` („niepoliczony"), nigdy 0.
  `DL_HIT_RATIO_TARGET_PCT` żyje w `metric_definitions` (jedna stała).
- DL ma `VIEW_RECRUITMENT_RANKING`; TCM nie ma już „własnych KPI".
