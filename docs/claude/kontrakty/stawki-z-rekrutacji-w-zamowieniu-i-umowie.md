# Stawki z rekrutacji w zamówieniu i umowie (D7, 08.10.2026)

Decyzja Artura 07.10.2026 (D7): stawka do klienta, za którą Delivery Lead
wysłał osobę przy „CV wysłane”, jest punktem odniesienia dla PRZYCHODU
w zamówieniu klienta; stawka kandydata od rekrutera — dla KOSZTU w zamówieniu
i w umowie B2B. Różnica to „do sprawdzenia”, **nigdy blokada**. Plan:
`docs/candidate-path-d1-d10-plan.md` (PR 3), raport:
`docs/recruitment-rates-completion-report.md`.

- **Reguła porównania jest JEDNA** (`services/recruitment_rate_check.py`,
  lustro `lib/recruitment-rate-check.ts` na wspólnym
  `__fixtures__/recruitment-rate-check-cases.json`): `equal | differs |
  not_comparable`; godzina, dzień i MD = 8 h, miesiąc wyłącznie z miesiącem,
  waluta inna niż PLN = nieporównywalne, tolerancja 0,01 zł/h. Zmieniasz
  regułę — zmień plik przypadków (oba zestawy testów go czytają).
- **Źródło: `services/recruitment_rates.py`** — z wierszy `candidate_stages`
  pary: najnowsza stawka do klienta (z osobą `moved_by` i datą wiersza) i
  najnowsza stawka kandydata. `for_pairs`, `for_contracts` (para z
  `contract.job_id`, a bez stawek — najnowsza para osoby u klienta),
  `for_client` (rodzina scalonych klientów, jeden krok w każdą stronę). Nic nie
  zapisuje. Stawkę do klienta pokazuje tylko `user_can_view_client_rate`
  (`as_dict(show_client_rate=…)`).
- **Poczta zamówień:** `CODE_RATE_RECRUITMENT_MISMATCH` w `order_mail_gate`
  (krok 7-bis), dane w `GateInput.recruitment_rates` (domyślnie puste, więc
  stare wywołania bez zmian) dociąga `_recruitment_client_rates` w
  `_plan_and_gate` — godzinowa ponowna weryfikacja widzi poprawioną stawkę bez
  osobnego kroku. Pomija `MATCH_NONE`, zamówienia kosztowe, brak stawki
  i nieporównywalne. Kod jest POZA `AWAITING_CONTRACT_CODES` (karta DL po
  trzech próbach). Powód zawiera słowo „stawka”, więc `_hide_amounts` maskuje
  kwoty rolom bez finansów. „Zastosuj” bez zmian — człowiek zapisuje świadomie.
  Awaria odczytu stawek nie zatrzymuje dokumentu (savepoint, pusta mapa).
- **Formularze zamówień:** `ContractWithOrdersRead.recruitment_rates`
  (redagowane razem z kwotami — `_CONTRACTOR_FINANCE_FIELDS`), `GET
  /api/clients/{id}/recruitment-rates?candidate_id&job_id` (rekrutacja spoza
  rodziny klienta = `rate: null`), `OrderPlanContractRead.recruitment_rate`
  w odczycie „Nowe zamówienie”. Front: `RecruitmentRateHint` w
  `EditOrderDialog` i `NewContractorOrderDialog`, `lineRevenueWarning`
  w `OrderPlanLineCard` i `ConsultantLineModal` (`lib/recruitment-rate-hint.ts`).
  **Żadna z tych notek nie blokuje zapisu** — nie dokładaj jej do walidacji.
- **Generator B2B:** prefill niesie `recruitment_rate` (stawka kandydata
  z etapu TEJ rekrutacji; nigdy „Stawka od” ani karta), a pod „Stawka godz.
  (netto)” stoi notka, gdy pierwszy etap w PLN się różni (`contractRateNote`)
  — nie walidacja, nie toast.
- **Po renegocjacji z klientem poprawia się stawkę do klienta w rekrutacji**
  (zakładka „Rekrutacje” profilu, panel osoby). Inaczej każde kolejne
  zamówienie tej osoby z maila czeka w weryfikacji z powodem różnicy.
