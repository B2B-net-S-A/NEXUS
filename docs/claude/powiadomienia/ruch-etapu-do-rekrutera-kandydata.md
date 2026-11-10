# Ruch etapu idzie do rekrutera kandydata, prowadzący dostaje tylko ważne etapy (10.11.2026)
<!-- indeks: reguła „rekruter rekrutacji” (job_recruiter), job_recruiter_ids, LEAD_STAGE_CODES, users.stage_moves_all_led_jobs (0680), „Kandydata prowadzi …”, bez „w ofercie (#id)” -->

Zgłoszenie z 10.11.2026: prowadzący rekrutację 43209 dostał w okienku
„Rekrutacje” „Kandydat … → Odrzucony” o kandydacie innej rekruterki i nie mógł
tego wyłączyć sobie bez utraty ruchów własnych kandydatów. Pomiar na kopii
produkcji z 14 dni: 1 751 z 3 579 dzwonków ruchu (49%) to prowadzący
o cudzym kandydacie, 20 osób, 63 ze 136 rekrutacji; 78% z nich to Screening
i Odrzucony, a Interview Klient i Zatrudniony razem 14. Makiety i decyzja
Artura (R1 + R2 + R3): https://claude.ai/artifact/6wfDBoKrmLMA46c1JHQPnG

- **Reguła „rekruter rekrutacji” wskazuje rekrutera kandydata**
  (`stage_notification_resolver.job_recruiter_ids`). Prowadzący
  (`working_owner_id`) dostaje ruch cudzego kandydata tylko na etapach
  z `LEAD_STAGE_CODES` (Interview Klient, Akceptacja, Zatrudniony) albo gdy
  wybrał to sam. Własny kandydat i kandydat bez rekrutera — prowadzący, jak dotąd.
  Nie dopisuj prowadzącego z powrotem „dla pewności”: on widzi te ruchy na Tablicy.
- **Bez zmian:** przekazania z przepływu (QC, Cpro, „CV wysłane”, etapy-odznaki),
  zastępstwa (`notification_route`), reguły z rolą, `specific_user`, DL rekrutacji
  i override'y klienta. Zmiana dotyczy wyłącznie typu odbiorcy `job_recruiter`.
- **Wybór konta:** `users.stage_moves_all_led_jobs` (0680 + lustro w
  `entrypoint.sh`), `PATCH /api/users/me/preferences`. W „Moje konto” pod
  włączoną kategorią „Ruchy w rekrutacjach” są dwie opcje: „Tylko moi
  kandydaci” (domyślnie) i „Wszyscy kandydaci w rekrutacjach, które prowadzę”.
  Przy wyłączonej kategorii wyboru nie ma, bo nic nie przychodzi.
- **Treść dzwonka:** odbiorca, który nie jest rekruterem kandydata, czyta
  najpierw „Kandydata prowadzi …” (pierwsze słowa widoczne w okienku). Zwykły
  ruch mówi „w rekrutacji „…””, nigdy „w ofercie '…' (#id)” — wewnętrzne id
  nie wychodzi w treści. Po skrócie nazwiska („Julia S.”) bez drugiej kropki.
- Testy: `tests/test_stage_moves_candidate_recruiter.py`, front
  `NotificationPreferencesPanel.test.tsx`.
