# Automat przydziału: zasady w Ustawieniach (29.10.2026)

Decyzja Artura 29.10.2026 (makiety: https://claude.ai/artifact/LoWjSGVpsx85bp5muLn8CQ,
wariant B). Administrator i Head of Recruitment zmieniają zasady automatu bez
deployu w Ustawienia → Zespół rekrutacji → zakładka „Automat przydziału”
(`/settings/team-structure?zakladka=automat`, `AllocationRulesPanel`).
Automat to planer `services/request_allocation_plan.py`, nie model AI.

- **Zasady działają tylko na nowe przydziały.** Artur: „nic nie zmieniaj
  w tych, co są już przydzielone, po prostu na przyszłość”. Żadna zasada nie
  zwalnia osoby, która pracuje przy rekrutacji — pilnuje tego test
  `test_no_rule_releases_people_who_already_work` (wszystkie kombinacje).
  Po wyłączeniu P2 osoby przy P2 zostają; znikają tylko żywe propozycje
  (`not_p1`). Urlop dalej zwalnia tylko przy P0/P1 (`automat_assigns`).
- **Dziewięć zasad** w `app_settings['request_allocation_rules']`
  (`services/request_allocation_rules.py`; brak klucza = wartość domyślna =
  zachowanie sprzed 29.10): tryb (wiersz stanu, `PUT /api/recruitment-allocation/mode`),
  `include_p2`, `people_per_p1` (1–3, P0 tyle samo, P2 jedna osoba),
  `max_load` (limit rekrutacji P1 na osobę, liczony jak „Obłożenie”; P2 nie
  zajmuje miejsca), `overflow` (0–3, dawne stałe „+1”), `outsiders`,
  `order` (`sent_first` / `deadline_first`), `leave_policy` (`wait` /
  `ignore` — „Przydzielaj” zdejmuje też odmowę 409 przy włączaniu
  „Przydziela sam”), `review_time`.
- **Planer**: `PlanRules` w `PlanInput.rules`; `RequestInfo.staffed_by(rules)`
  mówi, czy automat dobiera ludzi (P0/P1 zawsze, P2 z zasadą, „Przyjmujemy”
  nigdy), `wanted(rules)` — ilu. `automat_assigns` zostaje „P0/P1” i nadal
  steruje obłożeniem i zwolnieniem za urlop. Przy P2 osobę wybiera suma P1
  i P2 (`other_load`), żeby kolejne przebiegi nie dawały wszystkiego jednej
  osobie. Obsada liczy też osoby bez wiersza (`staffed_people` z
  `_unseen_workers`).
- **Podgląd „na sucho”** `POST /api/competence-team/rules/preview`
  (`request_allocation.preview_allocation`): te same odczyty i planer co
  pętla, tryb podglądu, bez adopcji prowadzących i bez zapisu; zwraca dziś
  zapisane i szkic (pula, nowe przydziały, kto ile, czekające na HoR, osoby
  przy limicie). Front przed zapisem w trybie „Przydziela sam” z ≥ 20 nowymi
  przydziałami pyta `useConfirmV2`.
- **Historia** `GET /api/competence-team/rules/history`: wpisy
  `allocation_rules_changed` (pola przed/po) i `allocation_mode_changed`
  z `recruitment_priority_audit_events`, 30 ostatnich.
- Godzina przeglądu zniknęła z dołu zakładki „Kategorie” — jest tam odnośnik.
- **Poza zakresem (osobne zadanie):** komunikaty „automat dobiera tylko do
  P1” (`automatAssigns`, `AUTOMATIC_ONLY_P1_NOTE` w 7 plikach frontu) nie
  znają zasady P2 — po jej włączeniu mówią nieprawdę.
