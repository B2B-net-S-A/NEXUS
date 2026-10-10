# Praktykant — „Telefony na dziś” (0374, 24.09.2026)

Nowi sourcerzy/rekruterzy przez pierwsze 40 dni roboczych tylko dzwonią do
kandydatów z codziennej listy i zapisują fakty, bez których rekruter dzwoni
na próżno. Decyzje Artura 24.09.2026, makieta
https://claude.ai/artifact/2cF9QaY3YwoezR8dU8ga7x, kontrakt
`docs/trainee-call-lists-contract.md`. Kod: `services/trainee_rules.py`
(czyste reguły), `trainee_call_list.py` (pula, listy), `trainee_program.py`
(dzień, zapis rozmowy, panel), `api/trainee.py`, `tasks/trainee_call_lists.py`.

- **Rola `trainee` jest wyłączna** (CHECK `ck_users_exclusive_finance_viewer_roles`,
  `ensure_exclusive_roles`, `_normalized_role_values`, AAD) i **nie ma żadnej
  sekcji**. `get_current_user` odmawia jej 403 `trainee_restricted` na KAŻDEJ
  trasie domenowej; trasy `/api/trainee/*` praktykanta stoją na `TraineeUser`
  (wpisy w `_SECTIONLESS_ALLOWLIST`). Profil kandydata jest dla niej zamknięty —
  karta na liście to wąski odczyt jej własnej pozycji. Front przekierowuje ją
  na `/trainee` (middleware) i nie pokazuje menu.
- **Minimalna stawka B2B netto idzie do `expected_rate_hourly`**
  (`write_profile_rate(source="trainee_call")`, audyt z `rate_meaning:
  "minimum"`, `_manual_override_rate`). Dzięki temu istniejąca bramka budżetu
  już znaczy „budżet poniżej minimum → ukryj”. Reszta to kolumny `candidates`:
  `b2b_willingness`, `accepts_below_min_rate`, `accepts_more_office_days`,
  `work_time_preference`, `call_facts_verified_at/by`.
- **Bramki (`dealbreaker_filters.apply_dealbreakers`, wszystkie powierzchnie
  dopasowań):** `employment_only` chowa ZAWSZE (niezależnie od wyłącznika
  rubryk); zgoda na niższy budżet / więcej dni w biurze zostawia osobę
  widoczną z `rate_fit="below_min_consented"` / `office_fit="over_consented"`;
  sprzeczny wymiar pracy (`part_time_only` przy `fulltime`, `full_time_only`
  przy `parttime`) NIE ukrywa — wiersz niesie plakietkę `work_time_fit`
  (decyzja Artura 24.09.2026; licznik `work_time_mismatch` zostaje w
  `meta.hidden` i jest zawsze 0). `Job.work_mode` z Traffita to zawsze
  `fulltime` — świadomie traktowane jako pełny etat (decyzja). Zmiana semantyki
  bramek = bump `MUST_GATE_POLICY_VERSION`.
- **Fakty z rozmowy da się poprawić** (audyt 24.09.2026): pasek faktów profilu
  („Popraw”, `PATCH /api/candidates/{id}/call-facts`, bramka faktów profilu,
  `Activity candidate_call_facts_corrected`). Każda zmiana stawki spoza telefonu
  praktykanta (`write_profile_rate`) czyści `accepts_below_min_rate`.
- **Lista dnia bez dziur:** poranny ranking i oddzwonienia „później” przechodzą
  przed wpisaniem przez twarde warunki puli (`_hard_conditions_sql`); pusta
  lista jest uzupełniana przy kolejnym `GET /today` (pusty ranking liczony
  ponownie najwyżej co 10 min). W „podglądzie jako” `GET /today` niczego nie
  zapisuje (`preview_not_generated`). Przekazanie rekruterowi tylko z dzisiejszej
  pozycji z wynikiem `call` (409); pominięta propozycja pary wraca do „Do
  przejrzenia”. Zmiana ról z grupy AAD woła `sync_program_for_roles`.
- **Pula (jedno zapytanie, `trainee_call_list.pool_sql`):** telefon, nie
  czarna lista, nie „tylko etat”, bez umowy u nas, bez sprawy w „Do
  przedzwonienia”, bez ruchu w opublikowanej rekrutacji (30 dni), bez telefonu
  od nikogo (30 dni) i od praktykanta (60 dni), nigdy po „niezainteresowany”,
  nie po „zły numer” przy tym samym numerze; do tego luka w danych. Popyt:
  ta sama kategoria i ≥ 60% must-have rekrutacji z 18 miesięcy. Reguły
  w `app_settings['trainee_call_rules']` (Ustawienia → Rekrutacja).
- **Lista dnia powstaje rano w pętli ALBO przy pierwszym `GET /today`**
  (blokada doradcza na dzień, ranking w pamięci procesu na dzień). Dzień
  zaliczony = wszystkie pozycje mają wynik. „Nie odbiera” pierwszy raz zostawia
  pozycję otwartą z `retry_after` +3 h.
- **Pozycja listy jest dziennikiem telefonu** — generator czyta z niej 60 dni,
  „niezainteresowany” i „zły numer”. Każdy wynik zapisuje też wiersz `calls`
  (`contact_source="trainee"`), a rozmowa — notatkę `external_source="trainee_call"`.
- **„Przekaż rekruterowi” = propozycja `source="trainee"`** w „Do przejrzenia”
  (evidence `{"trainee": {user_id, note}}`, wiersz skrzynki niesie
  `trainee_handover`). Praktykant widzi tylko tytuł rekrutacji i prowadzącego.
- **Awans robi admin albo Head of Recruitment** (`POST /programs/{id}/decision`,
  tylko na sourcera/rekrutera, `role_changed` w historii, opcjonalnie przypięcie
  rozmówców „szuka/rozważy” w „Moich ludziach”, bez przejmowania cudzych).
  Zmiana roli w adminie też zakłada/kończy program (`sync_program_for_roles`).
  Powiadomienie `trainee_program_decision` raz, 5 dni roboczych przed końcem.
- **Nie ma nagrań rozmów** — kontrolą jest próbka jakości i flaga, gdy % odebranych
  jest poniżej połowy średniej praktykantów.
