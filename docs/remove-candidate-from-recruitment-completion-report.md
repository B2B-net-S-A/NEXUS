# Completion report — Usuwanie kandydata z rekrutacji

**Data:** 2026-06-05
**Zgłoszenie:** „Jest: nie da się usunąć kandydata z rekrutacji / Ma być: da się usunąć kandydata z rekrutacji" (profil kandydata → zakładka **Rekrutacje**).

## Co zostało zrobione

Dodano akcję **„Usuń z rekrutacji"** na karcie rekrutacji w profilu kandydata
(zakładka Rekrutacje). To operacja **korekcyjna** („dodano nie tego kandydata /
nie na tę ofertę") — odrębna od odrzucenia (`reject`) i wycofania (`withdrawn`),
które zostawiają kandydata w pipeline na etapie końcowym dla audytu.

### Backend

- **Nowy endpoint:** `DELETE /api/candidates/{candidate_id}/recruitments/{job_id}`
  (`backend/app/api/candidates.py`).
  - Kasuje **wszystkie** `CandidateStage` pary (candidate, job) — czyli całą
    append-only historię etapów na tej rekrutacji.
  - Kaskadowo (DB `ON DELETE CASCADE`, zweryfikowane na prodzie) sprząta artefakty
    per-rekrutacja: `candidate_stage_cvs` → `cv_share_tokens` (snapshoty CV
    oryginalnego/brandowanego + linki udostępnień), `champion_card_share_tokens`,
    `scheduled_rejection_emails`.
  - Zostają nietknięte: rekord `Candidate`, umowy (`Contract`), notatki ze
    screeningu (`screening_notes`, kluczowane po candidate+job), oraz job-level
    Champion Profile (`champion_profile_suggestions`, kluczowany po job_id).
  - `404` gdy nie ma żadnej rekrutacji dla pary (candidate, job).
  - Wpis do `Activity` (`action="removed_from_recruitment"`, z liczbą i listą
    usuniętych etapów) dla audytu.
  - Uprawnienia: `RecruiterPlus` — spójne z tym, kto może dodać/przenieść
    kandydata w pipeline (operacja odwrotna do dodania).

### Frontend

- **`candidatesApi.removeFromRecruitment(candidateId, jobId)`** (`frontend/src/lib/api.ts`).
- **Przycisk „Usuń z rekrutacji"** (czerwony, ikona kosza) na karcie rekrutacji
  w `RekrutacjeTab` (`CandidateDetailV2.tsx`) + **dialog potwierdzenia** jasno
  opisujący, co zostanie usunięte i że to nie to samo co odrzucenie.
- Po sukcesie invalidowane są oba widoki na zakładce: lista po lewej
  (`["candidate-history"]` — karty + badge) i panel po prawej
  „W jakich pipeline'ach…" (`["candidate-pipelines", id]`).
- **`CandidatePipelinesWidget`** przekonwertowany z ręcznego `useEffect`-fetch na
  React Query (`candidatePipelinesQueryKey`), żeby panel po prawej odświeżał się
  spójnie z listą po usunięciu (wcześniej pokazywałby nieaktualne „(1)").

### Testy

- `backend/tests/test_candidate_remove_from_recruitment.py` (dodany do listy CI
  w `.github/workflows/ci.yml`): wymagana autoryzacja, `404` bez rekrutacji,
  usunięcie wszystkich etapów + zniknięcie z `/history` + idempotentny `404` na
  powtórne usunięcie, oraz kaskada `candidate_stage_cvs`.

## Weryfikacja

- Backend: `ruff` clean, route zarejestrowany.
- Frontend: `tsc --noEmit` exit 0; ESLint 0 errors (warnings = istniejący dług `any`).
- DB cascade potwierdzone zapytaniem do prod Postgres (3 FK → `candidate_stages`
  wszystkie `ON DELETE CASCADE`; `candidate_stage_cvs` → `cv_share_tokens` CASCADE).
- UI smoke-test przez Chrome MCP na prod — po deployu (zgodnie z
  `autonomous-verification.md` §2).

## Znane ograniczenia / świadome decyzje

- **Hard delete** (kasujemy historię), nie soft-delete — zgodne ze scope NEXUSa
  (bez wymogów GDPR/retencji) i z intencją „korekta pomyłki". Audyt zostaje w
  `Activity`.
- Notatki ze screeningu i job-level Champion Profile **nie** są usuwane (nie są
  per-stage; przeżyją ewentualne ponowne dodanie kandydata do rekrutacji).
