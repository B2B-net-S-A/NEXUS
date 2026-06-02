[← README](../README.md)

# Completion report — „Stawka do klienta" (cena wysłania kandydata) per rekrutacja

**Data:** 2026-06-02
**PR:** [#390](https://github.com/artur-t-96/Nexus/pull/390) (squash → `main` jako `84e8f90`)
**Status:** ✅ zdeployowane i zweryfikowane na prodzie

## Problem

Na profilu kandydata brakowało możliwości **uzupełnienia ceny, za jaką kandydat
został wysłany do klienta**. Dostępne były tylko trzy inne (różne semantycznie)
pojęcia stawek:

- `CandidateStage.expected_rate_*` — oczekiwania kandydata (jego koszt), ustawiane
  przy ruchu na etap „Zweryfikowany" (`VerifiedRateModal`).
- `Contract.rate_candidate / rate_client / margin` — finalne stawki, ale dopiero
  **po** `hired` (widget `CurrentContractCard`).
- `RateHistory` („Historia stawek") — ledger historycznych stawek kandydata z
  poprzednich kontraktów.

Brakowało **sell rate** zaproponowanego klientowi *w trakcie* rekrutacji (moment
`cv_sent`). To pole jest z natury per-rekrutacja (konkretny klient + oferta).

## Decyzja

Decyzja produktowa potwierdzona z Arturem → **opcja „Per rekrutacja"**: edytowalne
pole „Stawka do klienta" na karcie każdej rekrutacji (zakładka **Rekrutacje** w
profilu kandydata), obok „Stawki kandydata" (read-only) i wyliczonej marży.
Symetryczne do `expected_rate_*` — trzymane na pipeline.

## Zmiany

### Backend — model + migracja
- `backend/app/models/recruitment_pipeline.py` — 3 kolumny na `candidate_stages`,
  lustrzane do `expected_rate_*`: `client_rate_value` NUMERIC(10,2),
  `client_rate_unit` (reuse PG enum `rateunit`), `client_rate_currency` VARCHAR(3).
- `backend/alembic/versions/0122_candidate_stage_client_rate.py` — idempotentna
  (`ADD COLUMN IF NOT EXISTS`), single head na bazie `0121`.

### Backend — API (`backend/app/api/candidates.py`)
- `GET /api/candidates/{id}/history` — każda rekrutacja w `jobs[]` zwraca teraz
  `client_rate` **i** `expected_rate` (`{value, unit, currency}` lub `null`).
  Odczyt = **ostatnia (najnowsza) niepusta** wartość w obrębie rekrutacji
  (`stages_result` sortowany `moved_at DESC`), analogicznie do expected_rate.
- `PATCH /api/candidates/{id}/recruitments/{job_id}/client-rate` — body
  `{rate_value, rate_unit?, rate_currency?}` (schemat `ClientRateUpdate`).
  Zapis na **najnowszym** `CandidateStage` pary (candidate, job);
  `rate_value=null` czyści stawkę. 404 gdy brak rekrutacji.

### Frontend
- `frontend/src/lib/api.ts` — `candidatesApi.setRecruitmentClientRate(candidateId, jobId, payload)`.
- `frontend/src/components/v2/pages/CandidateDetailV2.tsx` — komponent
  `RecruitmentRateRow` na karcie rekrutacji: edytowalne „Stawka do klienta"
  (kwota + jednostka /mies. /d /h), obok read-only „Stawka kandydata" i marży
  (gdy obie stawki w tej samej jednostce). Inwalidacja historii przez
  **prefix** `["candidate-history"]` (queryKey ma id jako string, komponent
  operuje na number — prefix match omija mismatch).

## Weryfikacja

| Krok | Wynik |
|---|---|
| ruff `app/` | ✅ All checks passed |
| Alembic single head | ✅ `0122_candidate_stage_client_rate` |
| import modelu/schematu/endpointu | ✅ kolumny + `ClientRateUpdate` + route obecne |
| frontend `tsc --noEmit` | ✅ bez błędów |
| eslint (2 pliki) | ✅ 0 errors (warnings = istniejący dług, < cap 300) |
| CI PR #390 (gitleaks/backend pytest/frontend/trivy/review) | ✅ all green (pytest 3m31s na realnym Postgresie z migracją 0122) |
| `/api/health` po deploy | ✅ `healthy`, version `84e8f90` |
| UI prod (Chrome, kandydat 137644 „Aleksandra Dudek" → Scrum Master) | ✅ set 22 000 PLN/mies. → persist po reload → edit → clear → „—"/„Uzupełnij" |

Dane testowe (22 000 PLN) wyczyszczone po weryfikacji — rekord kandydata bez śladu.

## Znane ograniczenia / uwagi

- Stawka żyje na najnowszym `CandidateStage` rekrutacji. **Każdy ruch na nowy etap
  startuje z pustą stawką** (nowy wiersz ma `client_rate_* = NULL`); odczyt w
  historii bierze ostatnią niepustą wartość, więc poprzednia stawka jest nadal
  widoczna, ale po ruchu warto ją potwierdzić/uzupełnić ponownie (świadomy, prosty
  model — bez carry-forward).
- Marża pokazywana tylko gdy „Stawka kandydata" i „Stawka do klienta" mają tę samą
  jednostkę (brak konwersji /h ↔ /mies.).
- Brak osobnego RBAC — ustawianie stawki dostępne dla każdego zalogowanego
  użytkownika (spójnie z ruchami pipeline i „Historią stawek"; aplikacja wewnętrzna).
