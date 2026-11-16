# Porcja dnia: polski i lider w kolejności, reguła z braków od razu, programista nie jest „pokrewny” DevOps
<!-- indeks: `POLISH_LEVEL_PENALTY` = 8, `POLISH_UNKNOWN_PENALTY` = 5, `LEADER_GAP_PENALTY` = 5, `Bonus.polish`, `Bonus.leader_gap`, `order_signals_if_enabled`, `order_signals_for_ids`, `review_batch_facts.polish_states`, `role_family.leader_gap`, `_NOT_RELATED_THIS_WAY`, `autofill_withdraw.withdraw_failing_rules`, `autofill_withdrawn_learned_rule`, `order_polish_later`, `order_leader_gap` -->

Decyzja Artura z 16.11.2026 („rób wszystko teraz”), raport z pomiarem i makietami:
https://claude.ai/artifact/GCBD2zD1RU8hyiTwtaeas5. 16.11 porcja dała 43% „Pasuje”
(bez rekrutacji, w której dwie osoby przyjęły 43 z 44 kart) wobec 50% w piątek
13.11. W obrębie jednej rekrutacji wynik silnika prawie nie odróżnia „Pasuje”
od „Nie pasuje” (górna połowa kart 40,6%, średnia 41,4%), więc ta zmiana
poprawia kolejność sygnałami, które odróżniają, i łata trzy dziury w filtrze.

## Reguły

- **Polski w kolejności** (`review_batch_order.polish_penalty`): w rekrutacji
  wymagającej polskiego (`job_needs_polish`) polski z poziomem w profilu albo
  odrzucony za brak polskiego −8 punktów kolejki, brak danych −5, ojczysty
  (profil, CV po polsku, polskie imię i nazwisko — `polish_states`) 0. Pomiar
  na 1 948 decyzjach od 15.10: ojczysty 61% „Pasuje”, poziom 34%, brak danych
  42%; górna połowa kart rekrutacji-dnia 13.11 i 16.11 z 50,2% do 57,1%
  (kara nasyca się przy 8/5). Nikt nie wypada: od 15.10 19 takich osób doszło
  do klienta.
- **Lider i wykonawca** (`role_family.leader_gap`): rekrutacja z „lead / head of /
  manager / kierownik / lider / architect / CTO / principal / director”
  w tytule, a znane stanowisko osoby bez tych słów, −5. Od 09.11 122 takie
  decyzje dały 0 osób u klienta (lider do lidera 4,7%), choć „Pasuje” 57% —
  dlatego kolejność, nie wycinanie. Na decyzjach od 15.10 „Pasuje” w górnej
  połowie bez zmian, do klienta 83 → 85.
- **Jedna kolejność wszędzie:** te same punkty idą do porcji (`with_order_facts`),
  doboru z puli (`pick_bonuses` → `_with_known_points`) i Tablicy
  (`entry_autofill.queue_bonus`). Bez włączonej porcji (`REVIEW_BATCH_ENABLED`)
  nic się nie zmienia. Procent na karcie zostaje wynikiem.
- **Karta mówi dlaczego:** „Kolejność: 72% · polski nie ojczysty, szukamy lidera
  → dalej” (`order_polish_later`, `order_leader_gap`), a polski z poziomem to
  „~ B2 w profilu · nie ojczysty” na żółto, nie zielony znak jak ojczysty.
- **Reguła z braków działa od razu** (`withdraw_failing_rules`): odrzucenie
  z klikniętymi brakami zdejmuje nietknięte karty od systemu tej rekrutacji,
  które nie spełniają reguły (`job_learned_rules.keep_passing`), tą samą drogą
  co inne wycofania systemu (archiwum, wpis „Praca w tle” z `why = learned_rule`,
  bez `autofill_feedback`). Plan dnia dopełnia porcję przy następnym przebiegu.
  16.11 bez tego 23 odrzucenia były powtórką (DevOps Lead 17 × „brak IBM MDM”
  po trzecim, Playwright 6); w rekrutacjach z Playwrightem wszystkie 17 osób
  przyjętych od 13.11 miało go w CV.
- **Programista do rekrutacji DevOps to inna rola** (`_NOT_RELATED_THIS_WAY`):
  od 09.11 64 takie decyzje, 0 osób u klienta; 16.11 w „DevOps Lead” 5 z 11
  „Inna rola” to programiści Java. DevOps do rekrutacji programisty zostaje
  pokrewny.

## Czego świadomie nie zrobiono (pomiar 16.11.2026)

- **Reguł z samych tytułów** (podrole, uczenie się z odrzuceń „Inna rola”
  w rekrutacji, podobieństwo wektora CV do przyjętych): w teście czasowym
  „Pasuje” w tym, co zostaje, rośnie o 0,5–2 punkty. Rola idzie przez profil
  „Kogo szukamy” i ocenę roli (osobne PR-y z tej samej decyzji).

Testy: `test_review_batch_stage0_unit.py::test_polish_and_leader_gap_push_the_card_back`,
`test_role_family.py` (`test_developer_on_a_devops_job_is_another_role`, `test_leader_gap`),
`test_job_learned_rules.py::test_rule_withdraws_waiting_cards_without_the_item_at_once`,
`ReviewBatchCard.test.tsx` (`orderLine`), `ReviewBatchKeyFacts.test.tsx`.
