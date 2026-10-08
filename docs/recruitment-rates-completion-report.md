# Stawki z rekrutacji w zamówieniu i umowie — raport (PR 3, D7, 08.10.2026)

Plan: `docs/candidate-path-d1-d10-plan.md`, sekcja „PR 3”. Decyzja Artura D7
(07.10.2026): stawka do klienta, za którą Delivery Lead wysłał osobę, jest
punktem odniesienia dla przychodu w zamówieniu; stawka kandydata — dla kosztu
w zamówieniu i umowie B2B. Różnica = „do sprawdzenia”, nigdy blokada.

## Czeka na Ciebie

- Po scaleniu i wdrożeniu: „Przelicz plan” albo zwykła godzinowa ponowna
  weryfikacja kolejki zamówień z maila pokaże, ile wpisów dostanie nowy powód
  „stawka różni się od stawki do klienta z rekrutacji” (podgląd powodów, bez
  „Zastosuj”). Archiwum z 07.10: 6 z 30 zamówień miało inną stawkę niż ta, za
  którą DL wysłał osobę — tyle mniej więcej wpisów może zmienić kategorię
  z „zapisane automatycznie” na „do weryfikacji”.
- Testy z bazą (`test_recruitment_rates.py`) uruchamia dopiero CI.

## Zmienione

Backend:

- `services/recruitment_rate_check.py` — czysta reguła `compare` (`equal |
  differs | not_comparable`), `hourly_pln`, `format_rate`, `RateRef`.
- `services/recruitment_rates.py` — `for_pairs`, `for_client` (rodzina
  scalonych klientów), `for_contracts` (para z `contract.job_id`, bez stawek —
  najnowsza para osoby u klienta), `client_family_ids`, `RecruitmentRate.as_dict`.
- `services/order_mail_gate.py` — `CODE_RATE_RECRUITMENT_MISMATCH`,
  `GateInput.recruitment_rates` (domyślnie puste), krok 7-bis; pomija
  `MATCH_NONE`, zamówienia kosztowe, brak stawki, nieporównywalne.
- `services/order_mail_ingest.py` — `_recruitment_client_rates` w
  `_plan_and_gate` (savepoint; awaria = pusta mapa).
- `api/client_orders.py` — `recruitment_rates` na kartach kontraktorów (tylko
  z podglądem kwot klienta, redakcja razem z kwotami), `GET
  /api/clients/{id}/recruitment-rates?candidate_id&job_id`.
- `api/client_order_groups.py` — `OrderPlanContractRead.recruitment_rate`
  w odczycie „Nowe zamówienie”.
- `services/b2b_agreement_prefill.py` + schemat — `recruitment_rate` (stawka
  kandydata z etapu tej rekrutacji, nigdy „Stawka od”).
- Teksty: `pipeline_move_rules.py`, `stage_client_rate.py`.
- Procedura DL zamówień (sekcja „Stawki z rekrutacji — punkt odniesienia, nie
  blokada”, sytuacja w kolejce, „Każda inna przyczyna”, karta MD, „z kontraktu”)
  + `ORDERS_LOGIC_SOURCES` + przestemplowanie; przewodniki `contracts.order_mail`,
  `contracts.b2b_generator`, `jobs.board` + przestemplowanie.
- Wzorzec uprawnień: `tests/data/authz_golden/client_orders.json` (nowa trasa,
  bramka jak lista zamówień).

Frontend:

- `lib/recruitment-rate-check.ts` (lustro reguły), fixture
  `lib/__fixtures__/recruitment-rate-check-cases.json`,
  `lib/recruitment-rate-hint.ts` (zdania), `lib/api/recruitmentRates.ts`.
- `components/orders/RecruitmentRateHint.tsx` w `EditOrderDialog`
  (z `ContractorOrderPanel`) i `NewContractorOrderDialog`.
- Ostrzeżenie `lineRevenueWarning` w `OrderPlanLineCard` (osoba z odczytu PDF)
  i `ConsultantLineModal` (zapytanie po osobie).
- Generator B2B: notka pod „Stawka godz. (netto)” (pierwszy etap w PLN).
- Teksty `ClientRateModal.tsx`, `CvHandoffWorkbench.tsx`.

Testy: `test_recruitment_rate_check.py`, `test_order_mail_recruitment_rate_gate.py`
(równe → auto, różne → kolejka z kodem, pominięcia, `classify_hold` → other,
maskowanie kwot w kolejce), `test_recruitment_rates.py` (baza: źródło, rodzina
klienta, kontrakt bez rekrutacji, lista kontraktorów z redakcją, podpowiedź
formularza, prefill). Front: `recruitment-rate-check.test.ts` (fixture + zdania),
`EditOrderDialog.recruitmentRate.test.tsx`, nowy przypadek
w `NewContractorOrderDialog.test.tsx` i `B2BContractGeneratorForm.test.tsx`
(notki widoczne, zapis przechodzi).

## Znalezione

- Stawka do klienta bywa wpisywana później przez `PATCH …/client-rate` na
  najnowszym wierszu etapu — wtedy „kto” w linii „Z rekrutacji” to osoba, która
  przesunęła ten wiersz, nie zawsze ta, która wpisała stawkę (wiersz etapu nie
  pamięta autora stawki). Do rozważenia: kolumna autora stawki.
- Złoty wzorzec uprawnień na `main` nie zawiera kilku tras innych PR-ów
  (`notes-insights/profile-fill`, `proposal-inbox/dismiss-bulk`,
  `proposal-inbox/opened`) — regeneracja je dopisuje; w tym PR-ze świadomie
  zostawione, żeby nie mieszać zakresów.
- Zamówienia kosztowe nie są porównywane w kolejce (kwota zlecenia, nie stawka
  osoby), ale karta okna „Nowe zamówienie” ostrzega także przy linii kosztowej,
  bo linia niesie stawkę osoby.
