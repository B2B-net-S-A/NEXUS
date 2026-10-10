# Rekrutacje i kandydatów widzą wszyscy; stawki do klienta nie widzi rekruter (23.09.2026)

Decyzje Artura: „notatki i wszystkie elementy w panelu rekrutacji i kandydata
widzą wszyscy — nie musisz być przypisany do rekrutacji”; zapis też („każdy
może wszystko”); czaty czyta i pisze każdy; „tylko rekruterzy mają nie widzieć
stawki, za jaką osoby są wysyłane do klienta”.

- **Bramka zespołu jest otwarta dla każdej roli wewnętrznej**
  (`_JOB_MEMBERSHIP_BYPASS_ROLES = _INTERNAL_OPERATIONAL_ROLES` w
  `recruitment_access.py`). `ensure_job_membership`, `ensure_job_read_access`
  i `job_scope_clause` przepuszczają admin/HoR/DL/TCM/TAC/rekrutera/sourcera/
  Finanse — tablica, historia etapów, screening, CV etapu, feedback, werdykt HM,
  shortlista, propozycje, cudze CV z generatora i profil kandydata nie ukrywają
  już niczego przed osobą spoza zespołu. Stara rola podglądu `user` nadal
  przechodzi wyłącznie przez członkostwo. Zostają bramki RÓL („CV wysłane”
  poza Nordeą tylko DL/admin, sekcje `allowed_sections`, pola cyklu życia
  rekrutacji `JOB_MEMBER_LOCKED_FIELDS` tylko DL/admin; od 02.10.2026
  priorytet ustawia też Head of Recruitment). Ruch na
  „Zweryfikowany”, korektę stawki kandydata oraz zatrudnienie, odrzucenie
  i rezygnację wykonuje od 02.10.2026 każda rola wewnętrzna, także Talent
  Community Manager i sourcer (`RECRUITMENT_RATE_EDIT_ROLES`,
  `RECRUITMENT_TERMINAL_ROLES`; lustro stawki w `hooks/usePipelineMove.tsx`).
- **`oversight_bypass=False` = widok OSOBISTY i tak ma zostać** („Moja praca”
  rekrutera w operacjach rekrutacji, zakres „moje” w cyklu rozmów u klienta) —
  liczy przypisanie, nie dostęp. `is_member_of_job` i
  `is_member_of_candidate_chat` zostają listami ODBIORCÓW powiadomień, nie
  bramkami.
- **Treść rekrutacji (opis, ogłoszenia, Champion) redaguje każda rola
  wewnętrzna** (`job_edit_level` → `member` bez członkostwa).
- **Czat rekrutacji i czat kandydata** (`_require_member` w `job_chat.py`,
  `candidate_chat.py`): każda rola wewnętrzna czyta i pisze; nieistniejąca
  rekrutacja/kandydat = 404.
- **Podsumowanie aktywności AI** bierze też notatki, screeningi i feedback bez
  rekrutacji (`null_ok=True`, `VISIBILITY_SCOPE_VERSION` v2 unieważnia cache).
- **Stawka do klienta** (`CandidateStage.client_rate_*`): czytają
  `CLIENT_RATE_VIEW_ROLES` (admin, HoR, DL, TCM, Finanse; `has_any_role`, więc
  rekruter z dodatkową rolą DL widzi), zapisują `CLIENT_RATE_WRITE_ROLES`
  (admin, DL) — `candidate_access.py`, front `lib/client-rate-access.ts`.
  Własność rekrutacji nie daje zapisu, członkostwo też nie jest potrzebne.
  Redakcja na serwerze: `_stage_response(show_client_rate=…)` — argument BEZ
  wartości domyślnej, każdy wołający liczy go `user_can_view_client_rate`
  (tablica, „moje następne kroki”, historia etapów, odpowiedź `/move`) — oraz
  `_candidate_history_response_for_user` (profil → Rekrutacje), który niesie
  `can_view_client_rate`/`can_write_client_rate`. **Stawkę KANDYDATA
  (`expected_rate`) widzą wszyscy** — do 23.09 profil chował ją każdemu bez
  `VIEW_FINANCE`. Kwoty KONTRAKTÓW w `/history` zostają przy dostępie
  finansowym. Nowa powierzchnia niosąca `client_rate_*` = `user_can_view_client_rate`.
- **Rekruter prowadzi swoich kandydatów w cudzej rekrutacji** (decyzja Artura
  07.10.2026: ludzie przepinają swoich kandydatów poza oficjalnym przydziałem).
  Dodający zostaje właścicielem procesu (`recruitment_processes.owner_user_id`),
  więc dzwonki przekazań, follow-up i KPI idą do niego. Okno „Dodaj do
  rekrutacji” (`JobPicker`) szuka we WSZYSTKICH otwartych rekrutacjach — trybu
  „tylko moje” już nie ma. „Moje” LISTY `/jobs` = `jobs_mine_list_clause`
  (pracuję nad rekrutacją ALBO mam tam otwarty proces kandydata), wiersz niesie
  `priority_carry_over_count` → plakietka „Twoi kandydaci: N” w kolumnie
  „Rekruter”. `jobs_mine_clause` (zespół — „Moje następne kroki”, kreator
  metryk) i reguła „Rekrutera” (`job_team`) się NIE zmieniają; takiej osoby nie
  dopisujemy do zespołu. „Czeka na Ciebie” (`board_flow._owned_job_ids`) liczy
  Screening i Zweryfikowanych także z rekrutacji, w których osoba jest
  właścicielem procesu; Ogłoszenia i propozycje — tylko jako Rekruter.
- Wzmianki w starszych sekcjach o „członkostwie w zespole rekrutacji” jako
  bramce odczytu/zapisu opisują stan sprzed 23.09.2026.
