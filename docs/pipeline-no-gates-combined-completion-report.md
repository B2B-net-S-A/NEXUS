# Kanban bez bramek + poprawki rekrutera — połączenie #1591 i #1593

Data: 17.09.2026. Jeden PR zamiast dwóch konfliktujących (26 plików w konflikcie,
41 wspólnych). Baza: `batch/2026-09-17-prs` (zawiera #1588 z migracjami 0323/0324).

Raporty źródłowe zostają bez zmian:
[kanban-no-gates-completion-report.md](kanban-no-gates-completion-report.md),
[traffit-managed-in-nexus-completion-report.md](traffit-managed-in-nexus-completion-report.md),
[recruiter-tools-fixes-completion-report.md](recruiter-tools-fixes-completion-report.md),
[recruiter-tools-audit-2026-09-17.md](recruiter-tools-audit-2026-09-17.md).
Tam, gdzie opisują flagę `PENDING_VERIFICATION_ENABLED` albo serwerowe
`budget_exceeded`, obowiązuje ten raport.

## Decyzje Artura (17.09.2026) i co z którego PR-a

| # | Decyzja | Skąd | Uwagi |
|---|---|---|---|
| 1 | Bramka „Oczekuje” usunięta NA STAŁE, bez flagi | #1591 | Trasy `GET /pipeline/pending-verifications`, `POST …/accept-verification`, `…/reject-verification` usunięte (404), razem z `accept/reject_pending_verification`, `_lock_current_pending_verification` i schematami listy/odrzucenia. `/pending-verifications` → `/jobs` (przekierowanie z #1593). |
| 2 | Stare karty `pending`: odblokować wszystkie, zaliczyć „Zweryfikowany” | #1593 (rozszerzone) | `pending_verification_promotion.py` bierze KAŻDY wiersz `pending`; etap `verified` → `record_accepted_verification`, inne etapy tylko `active`. Skrót SQL #1591 z `_DATA_STATEMENTS` usunięty. |
| 3 | Migracje #1591 za #1588 | — | `0325_pending_verification_retired` (← `0324_candidate_auto_match`), `0326_jobs_managed_in_nexus`. Jeden head. |
| 4 | Stawka przy „Zweryfikowany” opcjonalna, „Pomiń stawkę” | #1591 | — |
| 5 | „Ponad budżet” z AKTUALNEGO budżetu PLN/h | #1591 | Serwerowe `budget_exceeded` (#1593) usunięte. Karta, dok, Screening, Wysyłka CV, Rozmowy, `selectOverBudget`, KPI liczą `isOverHourlyBudget`. `budgetHidden`/`isJobBudgetHiddenFor` usunięte (budżet PLN/h nie jest redagowany). |
| 6 | Weto HM / globalna czarna lista = ostrzeżenie „Przenieś mimo to” | #1591 | `/bulk-move` i dodawanie kandydata twarde. Ruch zbiorczy na tablicy POMIJA karty z wetem HM na etapie klienta (`bulkMoveSkipReason`) z toastem „Pominięto N: nazwisko — powód” (filtr z #1593). |
| 7 | Po ruchu odznaka „do uzupełnienia”, bez okien | #1591 | — |
| 8 | Screening: obie informacje | nowe | Nagłówek: 4 liczby (ponad budżet + z ostrzeżeniem). Lewa kolumna: „Ponad budżet” i „Z ostrzeżeniem” (`selectWithWarning`). |
| 9 | Reszta #1593 i #1591 w całości | oba | HoR = parytet (także komunikaty 403 na `/move`), stawka do klienta z `can_write_client_rate`, `?tab=` (`useUrlTab`), `?candidate=`, zaznaczanie po `candidate_id`, kalendarz, wyszukiwarka, powiadomienia, generator CV; szkic kontraktu w savepoincie, podpis offline, mail odrzucenia opt-in, podpowiedź obsady do zespołu, przełącznik NEXUS/Traffit. |
| 10 | Jeden test bramki | — | `backend/tests/test_pending_verification_retired.py` zastępuje `test_pending_verification.py`, `test_pending_verification_disabled.py`, `test_pending_verification_promotion.py` i `test_pending_verification_retired_mirror.py`. |

## Decyzje podjęte przy łączeniu (poza listą)

- **Migracja 0325 woła serwis tylko na schemacie HEAD.** Serwis jest ORM-owy,
  a ORM czyta kolumny modeli z kodu HEAD — na bazie przed 0326 zapytanie o `jobs`
  padało na `managed_in_nexus` (sprawdzone na Postgresie: wiersz `verified` zostawał
  `pending`, znacznik nie powstawał). Migracja sprawdza więc, czy baza ma każdą
  tabelę i kolumnę modeli; jeśli nie — nic nie robi, a promocję wykonuje blok
  `entrypoint.sh` po `alembic upgrade heads`. Wspólny znacznik
  `pending_verification_promotion_2026_09_17`.
- **„Z ostrzeżeniem” = weto HM.** Kanban nie niesie na karcie globalnej czarnej
  listy (ta pojawia się dopiero w 409 przy ruchu), więc sekcja i liczba liczą weto HM.
- **Aliasy `?tab=`** mieszkają w `lib/job-detail-tab-param.ts`
  (`JOB_DETAIL_TAB_ALIASES`, z #1590 + `notes` z #1593) — jedna lista dla
  `useUrlTab` i `resolveJobDetailTab`; `test_client_tab_links.py` czyta je stamtąd.
- **Baseline `check-unreachable-modules.mjs`** przycięty o pliki usunięte przez oba PR-y.
- **`teams_notifications`** zachowuje typy `decision_accepted/rejected` (brak
  wywołań po usunięciu tras) — tylko docstring zaktualizowany.
