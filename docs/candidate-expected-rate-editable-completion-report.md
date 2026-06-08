# Edytowalna „Stawka kandydata" (expected_rate) per rekrutacja — completion report

**Data:** 2026-06-08
**Zgłoszenie Artura:** „Nie da się przypisać kandydatowi stawki" → „Ma być: da się
przypisać kandydatowi stawkę" (profil kandydata → zakładka Rekrutacje / sekcja
„Stawka do klienta" na Profilu).

## Problem

W profilu kandydata przy każdej rekrutacji pokazywaliśmy dwie stawki obok siebie:
- **Stawka kandydata** (`expected_rate` — oczekiwania kandydata) — **read-only**,
  ustawiana wyłącznie przy ruchu na etap „Zweryfikowany" przez `VerifiedRateModal`.
- **Stawka do klienta** (`client_rate` — sell) — edytowalna od PR #390/#397.

Gdy kandydat trafiał do rekrutacji inną drogą (lub bez etapu „Zweryfikowany"),
„Stawka kandydata" zostawała `—` i nie było jak ją uzupełnić ani skorygować z
poziomu profilu. Stąd zgłoszenie.

## Rozwiązanie

Symetrycznie do „Stawki do klienta" — „Stawka kandydata" jest teraz edytowalna
in-line (Uzupełnij/Edytuj → kwota + jednostka + Zapisz/Anuluj).

### Backend

`PATCH /api/candidates/{candidate_id}/recruitments/{job_id}/expected-rate`
(`backend/app/api/candidates.py`, `set_recruitment_expected_rate`) — lustrzane do
`set_recruitment_client_rate`:
- Body = istniejący `ClientRateUpdate` (`{rate_value, rate_unit?, rate_currency?}`).
- Zapis na **najnowszym** `CandidateStage` pary (candidate, job) — w pola
  `expected_rate_value/unit/currency`. Odczyt w `/history` bierze ostatnią
  niepustą wartość (bez zmian).
- `rate_value=null` czyści stawkę.
- **Świadoma decyzja:** edycja NIE re-triggeruje budżetowego gate'u zatwierdzania
  (pending verification). Ten gate pozostaje na poziomie ruchu na etap `verified`,
  gdzie jest jego pierwotny cel. To jest bezpośrednia korekta danych, nie ruch po
  pipeline.

### Frontend

- `candidatesApi.setRecruitmentExpectedRate(candidateId, jobId, payload)`
  (`frontend/src/lib/api.ts`).
- Refaktor `RecruitmentRateRow` w `CandidateDetailV2.tsx`: wydzielony współdzielony
  komponent `EditableRateCell` (wartość + jednostka, własny stan edycji + mutacja +
  prefix-invalidate `["candidate-history"]`). Używany dla obu kolumn — „Stawka
  kandydata" i „Stawka do klienta". Marża nadal liczona z wartości z serwera
  (props), więc aktualizuje się po zapisie którejkolwiek ze stawek.
- Komponent renderuje się w dwóch miejscach (oba korzystają z refaktoru):
  `SellRatePanel` (Profil) i `RekrutacjeTab` (zakładka Rekrutacje).

## Trzy pojęcia stawek (przypomnienie, bez zmian)

- `CandidateStage.expected_rate_*` — oczekiwania kandydata (**teraz edytowalne**).
- `CandidateStage.client_rate_*` — cena wysłania do klienta (sell).
- `Contract.rate_*` — finalne rate'y po `hired`.
- `RateHistory` — ledger historycznych stawek kandydata (osobny widget).

## Weryfikacja

- `ruff check` backend — pass.
- `tsc --noEmit` + `eslint` (zmienione pliki) — pass (0 errors).
- E2E przez Chrome MCP na prodzie — set/persist/clear „Stawki kandydata".

## Pliki

- `backend/app/api/candidates.py` — endpoint `set_recruitment_expected_rate`.
- `frontend/src/lib/api.ts` — `setRecruitmentExpectedRate`.
- `frontend/src/components/v2/pages/CandidateDetailV2.tsx` — `EditableRateCell` +
  refaktor `RecruitmentRateRow`.
