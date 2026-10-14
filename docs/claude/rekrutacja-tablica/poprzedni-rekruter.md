# „Poprzedni rekruter” — zejście z P1 i zamknięcie usypia zespół (14.10.2026)
<!-- indeks: zejście z P1 albo zamknięcie przenosi zespół do „Poprzedni rekruter”, powrót na P1 albo otwarcie przy P1 przywraca go samo, nic nie jest kasowane (tabela `job_previous_recruiters`), kto nie wraca, czytelnicy „kto pracuje teraz” vs dostęp i historia, „Priorytet po otwarciu”, „Usuń z poprzednich” -->

Prośba Head of Recruitment, decyzje Artura 14.10.2026 („zrób zgodnie
z rekomendacjami”). Makiety: https://claude.ai/artifact/B3ourrtpaHov5Uu6EkZuCX.
Pomiar przed zmianą (14.10): 203 otwarte rekrutacje — 27 P1, 169 „Bez
priorytetu” (51 z zespołem, 57 osób), 7 „Przyjmujemy kandydatów”.

## Reguła

- **Zejście z P1** (na „Bez priorytetu” albo „Przyjmujemy kandydatów”)
  i **zamknięcie** przenoszą wszystkich, którzy pracują jako „Rekruter”
  (`job_team.working(recruiters_for_jobs)` — prowadzący, przypisanie,
  ręczny współpracownik; bez propozycji), do „Poprzedni rekruter”.
- **Powrót na P1** i **ponowne otwarcie przy P1** przywracają ich samo,
  w tej samej transakcji co zmiana (automat nie zdąży dobrać nowej osoby).
  Przy ponownym otwarciu z innym priorytetem nikt nie wraca.
- **Reguła działa na zdarzeniach**, nie jako „nie-P1 = nikt”: przy „Bez
  priorytetu” wolno pracować, a osoba dodana ręcznie jest zwykłym
  rekruterem i po powrocie na P1 zostaje (zespół = suma).
- P2 ↔ „Przyjmujemy kandydatów” i zmiana priorytetu ZAMKNIĘTEJ rekrutacji
  niczego nie ruszają.
- **Bez danych wstecz**: 56 otwartych rekrutacji spoza P1 z zespołem i 4 261
  zamkniętych sprzed wdrożenia zachowują się jak dawniej, aż do pierwszego
  zdarzenia.

## Nic nie jest kasowane

`jobs.recruiter_id`, wiersze `job_collaborators` i historia zostają — wisi na
nich dostęp (`job_membership.is_member_of_job`, `candidate_membership`),
kreator metryk („me” przez `jobs_mine_clause`, grupowanie po
`recruiter_id`), rejestr umów B2B i dzwonki o własnych kandydatach.
„Poprzedni” to otwarty wiersz `job_previous_recruiters` (migracja 0446,
jeden na parę; `cleared_reason`: `restored` | `dismissed` | `readded` |
`removed` | `skipped`). Serwis: `services/job_previous_recruiters.py`.

Wyjątek: przy **zejściu z P1** żywe przypisania (`job_work_assignments`)
uśpionych osób dostają powód `parked` — automat nie liczy ich w obłożeniu.
Osoba, która pracowała wyłącznie przez przypisanie, traci wtedy wynikający
z niego dostęp do powrotu (14.10: takich osób na otwartych rekrutacjach 0).
Zamknięcie przypisań nie zwalnia — robi to automat (`finished`).

## Kto nie wraca przy P1

- konto nieaktywne i osoba bez roli rekrutera (`skipped`);
- osoba usunięta przyciskiem „Usuń z poprzednich”
  (`DELETE /api/jobs/{id}/previous-recruiters/{user_id}`, bramka jak
  `DELETE /owner`; `dismissed`);
- osoba zdjęta z zespołu (`remove_recruiter`, `DELETE /collaborators`,
  zastąpiony prowadzący; `removed`).

Wraca od razu, gdy człowiek doda ją ponownie (`add_manual_member`, `/owner`,
`/claim`, `POST /collaborators`, PATCH `recruiter_id`, onboarding;
`readded`). Uśpiony prowadzący może sam wziąć rekrutację („Biorę”) —
uśpiony = brak prowadzącego. Wyjątek: powrót ludzi po zdjęciu championa
(`restore_after_champion_removed`, `unpark=False`).

Przypisanie automatu wraca jako przypisanie automatu (planer zwolni je za
urlop jak każde inne); reszta osób, które po zdjęciu znacznika nadal nie
pracują, dostaje trwały wpis w zespole.

## Czytelnicy „kto pracuje teraz” (pomijają uśpionych)

- reguła zespołu: `owner_is_working_clause`, `jobs_worked_by_clause`,
  `jobs_nobody_working_clause`, `recruiters_for_jobs` (warianty
  `exclude_parked=True` podzapytań; gołe podzapytania zostają dla dostępu);
- „Moje”: `jobs_mine_working_clause` (lista, „Moje następne kroki”);
  uśpiony z własnym kandydatem w toku zostaje przez `my_open_process_job_ids`;
- filtr „Rekruter” w zakresie „Wszystkie” (bez `open_only`) znajduje też
  uśpionych — inaczej nikt nie znalazłby swoich zamkniętych rekrutacji;
- dzwonki: `list_job_member_ids(include_parked=False)` u producentów
  dzwonków (komplet obsady, wiadomość czatu), `working_owner_id` wszędzie,
  gdzie dzwonek szedł do `jobs.recruiter_id` (ścieżka zapasowa na DL-a);
- automat: `_adopt_owners` nie adoptuje uśpionego prowadzącego,
  `load_workloads` go nie liczy.

## Ekrany i dzwonki

- Panel „Zespół”: wiersz „Poprzedni rekruter” pod „Rekruter” (szare osoby,
  „do DD.MM · wróci przy P1”, × „Usuń z poprzednich”); pusty „Rekruter” przy
  uśpionych mówi zdaniem, nie bursztynowym „Bez rekrutera”.
- Zejście z P1 przy niepustym zespole pyta o potwierdzenie (wspólny hook
  `useJobPriorityChange` — panel i plakietka w nagłówku).
- „Otwórz ponownie”: pole „Priorytet po otwarciu” (domyślnie P1,
  `JobPublishRequest.priority`) i zdanie, kto wraca.
- Lista: komórka „Rekruter” pokazuje „poprzedni” zamiast „Bez rekrutera”.
- Dzwonki `recruiter_parked` („Rekrutacja zeszła z P1”) i
  `recruiter_restored` („Rekrutacja wróciła na P1”) — kategoria „Wzmianki”
  (jak `request_assignment_changed`), bez osoby, która zmieniła priorytet.
  Zamknięcie usypia bez dzwonka. Przy ponownym otwarciu prowadzący dostaje
  dawny „request wrócił” (`request_assignment_changed`), reszta
  `recruiter_restored`. Poranny skrót automatu pomija zwolnienia `parked`.
