# Audyt manualny Codexa 13–15.09.2026 — reguły, które łatwo cofnąć

<!-- indeks: budżet PLN/h rekrutacji, szkic Championa, „W procesie”, prep kit, tagi kandydata, pasek boczny -->

Raport naprawczy: `docs/manual-audit-2026-09-13-remediation-report.md`.

- **Budżet PLN/h rekrutacji ma JEDNO pole do wyświetlania:
  `JobResponse.effective_budget_hourly`** (`resolve_job_budget_hourly` — jawne
  pole albo stawka Championa, ta sama funkcja co filtr). Nagłówek, pasek AI
  Matching i dok oferty czytają je przez `lib/job-budget.ts`. Pole jest
  redagowane dla viewera i zdejmowane z listy rekrutacji (wyliczane także ze
  stawki Championa). `budget_max_at_move` w doku to migawka MIESIĘCZNYCH
  widełek z chwili ruchu — podpisana jako taka, nigdy jako budżet (B62/B72).
- **Akceptacja szkicu Championa synchronizuje kolumny rekrutacji** jak zapis
  z edytora (`_sync_job_columns_from_applied_sections`): stack → `must_skills`/
  `nice_skills`, podstawy → `rate_budget_hourly` itd. (FILL_EMPTY).
- **Pole sekcji 1 zmienione ręcznie w edytorze Championa nadpisuje kolumnę
  rekrutacji** (30.09.2026, `champion_job_sync.overwrite_edited_job_columns`):
  budżet, tryb pracy, dni w biurze, miasto — tylko ZMIENIONE w tym zapisie
  i niepuste; import z pliku zostaje przy FILL_EMPTY i „Uzgodnij”. Od
  08.10.2026 tak samo „Deadline na kandydatów” → `jobs.deadline` (data zdejmuje
  „Klient nie podał”; wyczyszczone pole terminu nie kasuje) — ale WYŁĄCZNIE
  z zapisu osoby z pełną redakcją rekrutacji (`set_deadline` w
  `champion_job_sync`, poziom z `ensure_champion_job_editor`): termin jest
  w `JOB_MEMBER_LOCKED_FIELDS`, więc zapis treści, import pliku i akceptacja
  szkicu AI go nie ruszają. FILL_EMPTY terminu działa tylko bez decyzji
  „Klient nie podał” i tylko dla daty, która jeszcze nie minęła — stary profil
  nie robi z rekrutacji „po terminie”. Do tej daty bramka pytała o termin,
  a data wpisana w Championie zostawała w profilu. Do tej daty
  poprawka „0 → 1 dzień” zapisywała się w profilu, a walidacja czytała 0
  z kolumny. Pola liczbowe na `/jobs/new` i w edytorze mają
  `blurNumberInputOnWheel` (kółko myszy nad aktywnym polem zmieniało liczbę).
- **„W procesie” w AI Matching = `countInProcess` z kanbana** (bez odrzuconych).
  `pipeline_candidate_ids` obejmuje też etapy końcowe i służy wyłącznie
  plakietce „już w pipeline” (B71).
- **Prep kit opisuje stack z wymagań roli** (`job_skill_requirements`), nie
  z `ClientKnowledge.tech_stack`; pytania z poziomów 1–3 (podobne rekrutacje,
  wiedza klienta) o technologie spoza wymagań odpadają (`_fits_job`) (B70).
- **Rekrutacje klienta `hidden` albo `deleted_at` nie trafiają do rejestru,
  dashboardu procesów ani dashboardu Delivery** (`job_client_listed_clause`,
  EXISTS z `correlate_except(Client)`). Świadomie BEZ `archived_at` —
  archiwalny prawdziwy klient ma historyczne rekrutacje (B73).
- **Edycja kandydata edytuje wyłącznie tagi-napisy** (`lib/candidate-tags.ts`);
  obiekty importu (`traffit_source`) wracają do zapisu nietknięte, a
  niezmienione tagi w ogóle nie jadą w PATCH (backend zastępuje listę) (B60).
- **Kolumna „Stawka” listy kandydatów = stawka z profilu**
  (`expected_rate_hourly`, ta, po której filtruje lista); `last_rate` z etapu
  to druga linia „w procesie” (B58).
- **Powody niepewności odczytu PDF zamówień są po polsku**: prompt v7 +
  `_polish_model_reason` przy parsowaniu i `polish_gate_reason` przy
  wyświetlaniu zapisanych `gate_reasons` (stare dokumenty) (B77).
- **Karta M365 pokazuje `last_error_code`** (`services/m365/error_codes.py`,
  klasyfikacja przy odczycie, bez migracji); surowy `last_error` tylko
  w „Szczegółach technicznych” (B61).
- **`Button asChild` renderuje sam `Slot` z jednym dzieckiem** — loader obok
  children rzucał wyjątek Radix (B74).
- **Pasek boczny: pionowe wymiary identyczne w obu stanach**
  (`SIDEBAR_VERTICAL_LAYOUT`), a rozwinięcie pod kursorem to nakładka nad
  treścią. Nie przywracaj nagłówka sekcji zależnego od stanu ani różnych
  `space-y` — klik trafiał w sąsiedni link (B57).
