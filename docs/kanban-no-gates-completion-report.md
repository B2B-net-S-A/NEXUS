# Kanban bez bramek — raport ukończenia

> Data: 17.09.2026. Decyzje: Artur (sesja planowania 17.09.2026).
> Plan: `~/.claude/plans/zaplanuj-wszytskie-poprawki-i-warm-perlis.md` (część A).
> Część B (przełącznik „Rekrutacja prowadzona w NEXUSIE"): [traffit-managed-in-nexus-completion-report.md](traffit-managed-in-nexus-completion-report.md).

## Po co

Tylko 0,4 % ruchów w pipeline (131 z 32 872 w 90 dniach) powstawało w NEXUSIE,
reszta przychodziła z nocnego importu Traffita. Bramki (karta „Oczekuje" do
akceptacji admina, obowiązkowa stawka, twarde 409 z czarnej listy/NDA/weta HM)
zniechęcały do przeciągania kart. Decyzja: żadna bramka nie blokuje przepływu —
ostrzeżenia i odznaki zamiast blokad; podpis umowy offline.

## Co się zmieniło

| Obszar | Przed | Po |
|---|---|---|
| Stawka ponad budżet przy „Zweryfikowany" | karta „Oczekuje", akceptuje tylko admin, każdy ruch 409 | ruch przechodzi; odznaka „ponad budżet" (PLN/h rekrutacji); bramka za flagą `PENDING_VERIFICATION_ENABLED` (domyślnie off, #1593) |
| Stawka przy „Zweryfikowany" | obowiązkowa (422) | opcjonalna; okno podpowiada stawkę z profilu, „Pomiń stawkę" |
| Czarna lista / NDA / konkurent / weto HM | twarde 409 | 409 `ELIGIBILITY_WARNING` → okno „Przenieś mimo to" → ruch + `Activity(eligibility_acknowledged)` |
| „Zatrudniony" przy konflikcie kontraktów | cały ruch cofnięty (409) | ruch zapisany, `Activity(contract_draft_skipped)` + powiadomienie Delivery |
| Podpis umowy (QES, „oznacz jako wysłane", Generator B2B) | przesuwał kartę na „Umowa wysłana/podpisana/Zatrudniony" | nie rusza pipeline'u |
| Mail odrzucenia | domyślnie planowany po odrzuceniu z etapu klienta | wyłącznie po zaznaczeniu checkboxa (domyślnie odznaczony) |
| Screening / scorecard po ruchu | okno otwierało się samo | odznaka „Uzupełnij screening" / „Scorecard" na karcie |
| Podpowiedź „komplet obsady" | do każdego admina/DL/TAC w firmie | do zespołu rekrutacji (+ admini) |
| Komunikaty 403 ról | nieaktualna lista ról | zgodne z `recruitment_access.py` |

## Pliki

**Backend**
- `app/api/pipeline.py` — stawka opcjonalna przy wyłączonej fladze bramki; ostrzeżenie dopuszczalności; savepoint szkicu kontraktu; mail opt-in; odbiorcy podpowiedzi; `screening_done`/`scorecard_done`/`candidate_expected_rate_hourly` w payloadzie tablicy; `_notify_pending_verification` tylko przy włączonej fladze.
- `app/services/pipeline_eligibility.py` — `check_candidate_move_eligibility` + `EligibilityBlock` (tablica); `assert_candidate_move_eligible` zostaje twarde (wtyczka LinkedIn).
- `app/services/recruitment_process_commands.py` — `update_latest_expected_rate` przy wyłączonej fladze `PENDING_VERIFICATION_ENABLED` zawsze aktywuje wiersz „Zweryfikowany” (także stary `pending`) i zalicza weryfikatora.
- `app/schemas/pipeline.py` — `acknowledge_eligibility`, nowe pola odpowiedzi, opisy.
- `app/services/signing/pipeline_hook.py` — **usunięty**; `app/services/signing/sender.py`, `app/api/signing.py` bez ruchu kart; `app/api/b2b_contract_generator.py` `ensure_hired=False`.
- Bramka „Oczekuje" — flaga `PENDING_VERIFICATION_ENABLED` i jednorazowa promocja starych kart przyszły równolegle z #1593; ten PR dokłada opcjonalną stawkę i korektę stawki bez `pending`.

**Frontend**
- Nowe: `lib/rate-to-hourly.ts`, `lib/pipeline-eligibility-warning.ts`, `components/v2/jobs/useEligibilityWarning.tsx` (okno „Przenieś mimo to” dla warsztatów „Wysyłka CV” i „Rozmowy”; tablica i screening mają je wbudowane).
- `components/v2/pages/KanbanBoardV2.tsx` — okno ostrzeżenia, odznaki, bez okien po ruchu, bez akcji approvera, budżet godzinowy.
- `components/v2/modals/VerifiedRateModal.tsx` (prefill + „Pomiń stawkę"), `RejectionV2.tsx` (opt-in).
- `lib/verified-rate-gate.ts`, `lib/pipeline-flow.ts`, `lib/pipeline-next-action.ts`, `lib/job-header-kpis.ts`, `lib/api.ts`, `lib/job-flow-stages.ts`.
- `components/v2/jobs/{ScreeningWorkbench,CvHandoffWorkbench,PipelineCandidateDock,InterviewDecisionDock,JobInterviewsTab,PipelineFiltersRail}.tsx`, `components/v2/screening/VerifiedRateFields.tsx`, `components/v2/pages/B2BContractGeneratorV2.tsx`, `components/v2/shell/{SidebarV2,BreadcrumbV2}.tsx`, `app/jobs/[id]/page.tsx`.
- **Usunięte:** `app/pending-verifications/page.tsx`, `app/dashboard/delivery-lead/_components/PendingVerificationsWidget.tsx` (+ test).

## Migracje i endpointy

- Brak migracji w części A (stare `pending` zalicza `pending_verification_promotion.py` z #1593).
- `POST /api/pipeline/move` — nowe pole `acknowledge_eligibility`; nowy kształt 409 `ELIGIBILITY_WARNING`.
- `GET /api/pipeline/kanban/{job_id}` — nowe pola kart `screening_done`, `scorecard_done`, `candidate_expected_rate_hourly`.
- Za flagą (404 przy wyłączonej, #1593): `GET /api/pipeline/pending-verifications`, `POST /api/pipeline/{id}/accept-verification`, `POST /api/pipeline/{id}/reject-verification`.

## Znane ograniczenia

- Ruchy zbiorcze z tablicy, które trafią na ostrzeżenie, liczą się jako nieudane w toaście — potwierdza się je pojedynczo.
- `/bulk-move` (API bez klienta w UI) i dodawanie z wtyczki LinkedIn zostają twarde.
- Karta pokazuje „ponad budżet" tylko, gdy stawka na karcie i budżet godzinowy rekrutacji są porównywalne (PLN).
