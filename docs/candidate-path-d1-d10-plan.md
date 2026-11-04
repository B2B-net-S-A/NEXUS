# Ścieżka kandydata D1–D10 — plan trzech PR-ów i stan prac

Stan na 08.10.2026 — wszystkie trzy PR-y na produkcji (`/api/health` = `68c4c47fe`):

- **PR1 — formularz screeningu:** #2083. Pomiar `python -m scripts.eval_recommendation_card_note --limit 40`
  na produkcji (08.10): 40/40 notatek bez awarii modelu, stawka zgodna z regułą 31/31, 109/117 odpowiedzi
  zachowanych, 3/109 zdań odrzuconych przez kontrolę nowych faktów → `RECOMMENDATION_CARD_ASSIST_ENABLED=true`
  (workflow „Coolify set env”). Przeklik w przeglądarce (para QA 113818 i 732435): panel `split`, „Wklej tekst”
  wypełnia 5 pól i proponuje 3, „Cofnij wypełnienie” — bez zapisu (0 wersji, 0 notatek, 0 ruchów).
- **PR2 — ekran Delivery Leada (D6, D9, D10):** #2087. Przeklik: przegląd w trzech kolumnach, marża na żywo,
  podpowiedź stawki ze źródłem, wcześniejsze wysyłki, okno „Wróć do poprawy” z listą pól — bez wysyłki.
  Raport: `docs/dl-review-v2-completion-report.md`.
- **PR3 — stawki z rekrutacji w zamówieniu i umowie:** #2084. Kod `rate_recruitment_mismatch` w kolejce
  zamówień z maila potwierdzi pierwsza ponowna weryfikacja (8:00–18:00) — do sprawdzenia.
- Po przekliku: „Cofnij wypełnienie” zostawiało „Niezapisane zmiany” (brakujący klucz `card_origins` ≠ klucz
  z wartością pustą w porównaniu formularza) i komunikat „pracuje 0 os.” w przeglądzie DL — poprawione
  w PR z tym stanem.

Kontrakt PR1: `docs/screening-form-contract.md`, raport PR1: `docs/screening-form-completion-report.md`.

---


## Context
Artur 07.10.2026: arkusz screeningu i karta rekomendacji to jeden proces. Rekruter rozmawia na podstawie Profilu
Championa i zapisuje wynik **dla Delivery Leada** — z NEXUSA nic nie idzie do klienta. DL akceptuje / odrzuca / odsyła
do poprawy, a przy akceptacji zapisuje **stawkę do klienta** (wysyła mailem poza NEXUSEM). Ta stawka ma zgadzać się
z przychodem w zamówieniu, a stawka kandydata od rekrutera — z kosztem w zamówieniu i umowie B2B.

Weryfikacja 07.10 (kod + produkcja): dane kandydata wpisuje się w 2–4 miejscach (stawka w czterech); CV i wymagania
otwierają się w oknach zamiast obok; „Karta Championa dla klienta” jest aktywna; DL nie widzi budżetu ani marży
i wpisuje stawkę od zera; stawka do klienta nigdzie dalej nie płynie (archiwum: 6 z 30 zamówień ma inną stawkę niż
ta, za którą DL wysłał osobę); arkusz od „Zweryfikowany” tylko do odczytu; brak historii wersji. W NEXUSIE są dziś
4 prawdziwe arkusze — zmiana przepływu jest tania.

Makieta zatwierdzona („wszystko zgodnie z rekomendacjami”): https://claude.ai/artifact/TNGomEmwM6ehsbdPDSaaBi.
D9 odwraca decyzję z 23.09 („przegląd DL bez marży”).

**Sposób pracy:** trzy PR-y po kolei, bez pytania między nimi (każdy = kroki jako commity w JEDNYM PR-ze).
Każdy od świeżego `origin/main` (ten worktree jest na 0421, main na 0423 — nowa migracja to `0424`, `down_revision
"0423_notes_facts_to_fields"`; przy kolizji `scripts/rechain_migration.py`). Po `gh pr create`: get_status →
set_monitor (auto_fix, address_comments) → set_auto_merge squash. Meta każdego PR-a: `/api/health` = SHA z maina.

---

## PR 1 — Jeden formularz screeningu z podglądami i historią (D1, D2, D3, D4, D5, D8)

### Backend
- **Migracja 0424 `screening_form_versions`** (SQL w jednym `services/screening_form_schema.py`, import w migracji
  i w `entrypoint.sh`; model `models/screening_form_version.py` w `models/__init__.py`, sonda w `main.py`):
  `id, candidate_id (CASCADE), job_id (CASCADE), version_no, process_id/stage_id/note_id/created_by (SET NULL),
  attempt_no, action ('baseline','external','save','restore','undo','fix_requested'), source ('form','note_import'),
  restored_from_version, snapshot JSONB {schema, sheet, card{key:{raw,source,origin,keywords}}, rate{amount,unit,currency}},
  changes JSONB [{section,key,label,before,after}], meta JSONB NULL, created_at`; `UNIQUE(candidate_id, job_id, version_no)`.
  `fix_requested` i `meta` są dla PR2 (bez drugiej migracji). Ta sama migracja: CHECK
  `ck_candidate_rate_changes_source` += `screening` (`candidate_rate_change_schema.SOURCES` + `SOURCE_LABELS`; jawne
  DROP + ADD w migracji i w entrypoincie, bo `CREATE TABLE IF NOT EXISTS` nie poszerzy istniejącego CHECK-a) oraz
  `UPDATE champion_card_share_tokens SET revoked = true` (lustro w `_DATA_STATEMENTS`). Downgrade odmawia przy danych.
- **Serwis** `services/screening_form_rules.py` (czyste: snapshot, diff, `sheet_has_content`, reguła edytowalności)
  i `services/screening_form.py` (`pair_edit_state`, `load_state`, `save`, `restore`, `list_versions`,
  `merge_versions`). `_latest_filled_screening` przenieść do `screening_sheets.latest_filled_sheet` (pipeline i assist
  importują z serwisu).
- **Trasy** `api/screening_form.py` (sekcja Pipeline):
  - `GET /api/screening-form?candidate_id&job_id` — pytania Championa, arkusz (+ `legacy_notes`), karta z pochodzeniem,
    stawka (+ podpowiedzi: karta / „Stawka od”), `version`, `editable` + `read_only_reason`, `stage_id`,
    `process_state_version`, `assist_enabled`, `phrase_language`, podpowiedzi z notatek.
  - `PUT /api/screening-form` — `{expected_version, sheet, card{fields, origins}, rate, note_import}`.
  - `GET /api/screening-form/versions`, `POST /api/screening-form/restore` (`mode: restore|undo`).
- **Kolejność zapisu w `PUT`** (jedna transakcja): `ensure_job_membership` → `assert_pair_editable` (409
  `SCREENING_FORM_READ_ONLY`: rekrutacja zamknięta, proces zamknięty/unieważniony — `candidate_claim.load_process`,
  bez procesu `board_column_for`) → `candidate_claim.assert_can_act` (423) → blokada kandydata, potem wierszy etapów
  pary `FOR UPDATE` (kolejność jak `change_rate`) → wersja ≠ `expected_version` = 409 `SCREENING_FORM_VERSION_CONFLICT`
  → wersja `baseline`/`external`, gdy stan różni się od ostatniej wersji (ślad starych tras i automatów) →
  `note_import` = `Note(kind=HUMAN)` → arkusz na NAJNOWSZY wiersz (`humanize_origins` → `stamp_sheet`, `notes`
  przepisane, `screening_answered` tylko przy pierwszym arkuszu albo w Nowi/Screening; moduł do `_SHEET_WRITERS`
  w `test_screening_note_sync_guard.py`) → karta `save_manual` tylko dla pól różnych od wartości efektywnej +
  `after_card_save(..., rate_change=False)` (nowa flaga — `_card_rate_change` robi commit w środku) → stawka przez
  `candidate_rate_change.change_rate(source="screening", reason="conversation")` w każdej kolumnie (przed
  „Zweryfikowany” = `noted` bez powiadomień), pole karty `rate` = tekst stawki → wersja `save` + Activity
  `screening_form_saved` (same nazwy pól) → commit → `send_pending_emails`, `mark_stale_for_candidate`.
- **Przywracanie:** ten sam aplikator; stawka wraca tylko poza `NOTIFY_COLUMNS` (inaczej `rate_not_restored`),
  odpowiedzi na zmienione pytania pomijane (`skipped_answers`), `undo` z `reason="typo"`.
- **Scalanie kandydatów:** `merge_versions` w `candidate_merge` przed pętlą referencji (przesunięcie numerów).
- **Stare trasy** `POST /stages/{id}/screening` i `PUT /recommendation-cards` zostają (stare karty przeglądarki);
  ich zmiany łapie wersja `external`. Usuwamy `POST /recommendation-cards/note/apply` i `_write_answers`.
  `build_proposal` dokłada stawkę strukturalną (PLN/h).
- **Bez klienta (D2):** `POST /stages/{id}/share-token` → 410 `CHAMPION_SHARE_REMOVED` (DELETE zostaje); publiczny
  GET `public_share.py` → 410 bez odczytu bazy (limit zapytań zostaje); `notes` zdjęte z `_CLIENT_SCREENING_KEYS`
  (generator CV i tak ich nie czyta, odpowiedzi nadal są źródłem treści CV).
- Etykiety `move_requirements`: `open_card` → „Uzupełnij w screeningu”.

### Frontend
- **Formularz** `components/v2/screening-form/ScreeningFullForm.tsx` (widok + kontener, jeden `useForm`; logika
  `lib/screening-form.ts`, API `lib/api/screeningForm.ts`, klucz `["screening-form", jobId, candidateId]`):
  - na górze `NoteFillBar` „Uzupełnij z notatki” (istniejące `readNote`/`readNoteFile`; puste pola wypełnia w miejscu
    z plakietką „z notatki”, przy pełnych chip „Użyj”; widoczny tylko przy `assist_enabled`);
  - 1 Pytania Championa (`ScreeningFormFields` bez „Notatek rekrutera”, `ScreeningReassignSuggestions`, „Ułóż w zdanie”);
  - 2 Warunki kandydata (`VerifiedRateFields`/`evaluateRateGate` + pola karty, `ScreeningSuggestionChips`);
  - 3 Ocena rekrutera (ocena, „Dlaczego ten kandydat”, motywacja, red flags z „Ułóż w zdanie”; `LegacySheetNote`
    „Notatka z arkusza” z „Przenieś do Dlaczego ten kandydat”);
  - stopka: „Zapisz” / „Zapisz i przekaż dalej → Zweryfikowany” (PUT, potem `usePipelineMoveCore` z
    `expected_rate_*` i `process_state_version`) / „Odrzuć”; 409 wersji → `reset(..., {keepDirtyValues})`;
    toast po zapisie z notatką ma „Cofnij” (`restore` `mode:"undo"`).
- **Historia** `ScreeningFormHistory` (wersje, zmiany przed→po, „Przywróć”).
- **Podgląd** `CandidatePreviewPane` (za `next/dynamic`), zakładki:
  - CV: przełącznik oryginał (`FilePreviewContent` z `loadDocumentBlob` na `/cv/original/download` — da też DOCX) /
    CV firmowe (`StageCvPreview` + `useStageBrandedCv`, bez `max-h`) / inne pliki (`cvDocuments`); chipy wymagań
    ustawiają szukanie w CV;
  - Wymagania: `JobRequirementsSummary` wydzielony z `ChampionBriefView` (`Fact`, `Chips`, warunki; budżet od–do
    z zapytania `["job", id]`);
  - Po ludzku: `PlainBriefBlock parts="summary" compact` + `DockCallCheatsheet`.
- **Panel osoby:** `PersonPanelShell size: "dock"|"wide"|"split"` (split = `max-w-[min(1200px,100vw)]`, `data-wide`
  zostaje, dochodzi `data-size`). Kliknięcie osoby w Nowi/Screening otwiera od razu split (D3: „od razu z boku”),
  „Zwiń” wraca do doku. Nowi: lewa kolumna `BeforeCallProfile` (fakty, dopasowanie, historia z nami, ostatnia
  notatka, „Biorę”/„Nie odebrał”/„Zacznij screening”), prawa — podgląd na zakładce CV. Screening: formularz +
  podgląd na zakładce Wymagania. Siatka `lg:grid-cols-2`, prawa kolumna `sticky`; poniżej `lg` podgląd zwijany.
  `defaultPanelSectionFor`: Nowi → `screening`.
- **Inne etapy (D8):** sekcja Screening w panelu = ten sam formularz, dopóki `editable`; po „CV wysłane” baner
  (zmiana dotyczy tego, co widzi DL, i następnego CV firmowego); po końcu procesu `SavedScreeningView` + karta tylko do
  odczytu + historia.
- **ScreeningWorkbench** zostaje gospodarzem (pigułki, Prep-kit, „Baza pytań”, formularz, podgląd); znikają zakładki
  „Stawka i decyzja”/„Karta”/„Notatki” i układ „full”. KB: `open_screening`, `open_card`,
  `onVerifiedRequirementsMissing` i przycisk „Screening” otwierają panel na screeningu; `ScreeningSheet` (JobInterviewsTab)
  renderuje ten sam formularz bez podglądu.
- **Karta tylko do odczytu:** `RecommendationCardSection` z „Edytuj w screeningu”; `RecommendationCardDialog` bez
  kroków edit/review (zostaje „Kopiuj” i link do panelu); DL review `editable={false}`; usuwamy
  `useSaveRecommendationCard`, `useApplyNote`, `RecommendationCardNoteReview`, `buildApplyInput`.
- **Bez klienta:** usuwamy przycisk z `JobInterviewsTab`, link z `CvHandoffWorkbench`, `ChampionCard.tsx` (martwy),
  `createShareToken`/`revokeShareToken`; strona `/share/champion-card` pokazuje „link nieważny”.

### Testy, spisy, dokumentacja
- Backend nowe: `test_screening_form.py` (najnowszy wiersz bez przesłaniania, baseline/external, idempotencja, 409
  wersji, 409 tylko-odczyt: zamknięta rekrutacja / zamknięty / unieważniony proces / para bez procesu / onboarding,
  423, notatka HUMAN, stawka `noted` vs `requested` z mailem po commicie, Activity bez wartości, przywracanie i
  cofanie, pusty szkic nie spełnia bramki, scalanie), `test_screening_form_rules.py`,
  `test_screening_form_migration_mirror.py`. Aktualizacje: note_sync guard, czytelnicy karty
  (`test_recommendation_cards.py`), prywatność AI (tabelę wersji czytają tylko ludzie), assist, share (410),
  `test_job_scope_contract.py`, `test_public_surface_hardening.py`, `test_champion_client_history.py`,
  `test_candidate_rate_change.py`; `AUTHZ_GOLDEN_WRITE=1`.
- Front: `screening-form.test.ts`, `ScreeningFullForm`, `NoteFillBar`, `ScreeningFormHistory`, `CandidatePreviewPane`;
  aktualizacje `PersonPanelShell`, `PersonWorkbenchTabs`, `KanbanBoardV2`, `ScreeningWorkbench`, `JobInterviewsTab`,
  `CvHandoffWorkbench`, karty, DL review, `heavy-bundle-boundaries`, `harness-seeds`.
- Harness `/preview/screening-form?state=nowi|filled|note|readonly|history` (dane fikcyjne) dopisany do
  `e2e/responsive-preview.spec.ts` (w tym 1280×720). Spis funkcji: `removed_reason` dla `card.workbench-tab`,
  `card.note-import`, nowe `screening-form.*`. Przewodnik `jobs.person` (kotwica formularza) +
  `stamp_screen_guides.py`. CLAUDE.md: nowa sekcja (0424) w środku pliku + korekty sekcji 0413, 0421, note_sync,
  Pipeline v4. Raport `docs/screening-form-completion-report.md`.

### Po wdrożeniu PR1
`python -m scripts.eval_recommendation_card_note --limit 40` w kontenerze backendu (tylko odczyt + AI) → przy dobrym
wyniku `RECOMMENDATION_CARD_ASSIST_ENABLED=true` workflowem „Coolify set env” → na produkcji „Wklej tekst”
z fikcyjną notatką bez zapisu.

---

## PR 2 — Ekran Delivery Leada (D6, D9, D10)

### Backend
- **Prośba o poprawki (D6):** `StageMove.fix_fields` (≤30; klucze `field:<pole karty>`, `field:overall_fit`,
  `question:<id>` z zapisaną treścią, `candidate_rate`, `cv`), tylko przy ruchu z QC CV na „Zweryfikowany”, poza
  Nordeą (422 `FIX_FIELDS_INVALID` / `FIX_FIELDS_NOT_ALLOWED`). `services/screening_fix_requests.py`: `fix_options`,
  `validate`, `record` (wiersz `screening_form_versions` z `action="fix_requested"` + `meta.stage_id`, zaraz po
  `stage_remarks.record`), `open_for_pair` (otwarta, dopóki najnowszy wiersz pary = `meta.stage_id`; `changed` per pole
  z porównania migawki). Dzwonek „Do poprawy (N): …” i lista „CV w drodze” (`TransitRow.fix_labels`); GET formularza
  niesie `fix_request` i `handback_stage_def_id`.
- **`GET /api/dl-review/context?candidate_id&job_id`** (`api/dl_review.py`, `recruitment_manage` + odczyt rekrutacji):
  stawka kandydata, budżet od–do (`resolve_job_budget_hourly`, `job_budget_range.effective_min`), podpowiedź stawki do
  klienta (ta para → ta osoba u tego klienta, rodzina scalonych klientów; `stage_client_rate.latest_client_rates`),
  mediana marży i zakres stawek konsultantów u klienta w tej samej kategorii (wydzielić `_order_hourly_leg`,
  `_finance_rates_in_pln` z `api/clients.py` do `services/client_consultant_rates.py`; tylko agregaty), poprzednie
  wysyłki tej osoby, inni wysłani w tej rekrutacji, ostatni kontrakt (wydzielić `_paid_rates`/`_contract_hourly`
  z `api/candidate_rates.py`), wymagania z dowodem i źródłem (`requirement_contract.evaluate_requirements`,
  `attach_gate_evidence`, nowe `must_text_evidence.mention_sources`, `critical_skills.effective_critical`,
  doświadczenie z sekcji 4), ryzyka (`pipeline_eligibility`, `current_employment`, karta `worked_at_client`,
  deal-breakery, ponad budżet, `my_people_matching.last_sent_to_client` rozszerzone o etapy od „CV wysłane”).
  Kwoty tylko przy `can_read_client_finance` (per klient), stawki do klienta przy `user_can_view_client_rate`.
- **`GET /api/dl-review/jobs/{job_id}/queue` (D10):** wiersze `KIND_DL_REVIEW` jednej rekrutacji (`load_snapshot(job_id=)`),
  ten sam builder co kontekst (X/Y wymagań, koszt, start, ryzyka, czeka od, rundy poprawek), stała liczba zapytań,
  limit 50; u Nordei pusto. `GET /api/board-tasks` bez zmian (odpytywany cyklicznie).

### Frontend
- `components/v2/recruitment/dl-review/`: `RequirementsColumn` (tabela „wymaganie / kandydat / źródło”, ocena
  rekrutera z formularza PR1, ryzyka), `CvColumn` (przełącznik z PR1 + QC), `DecisionPanel` (koszt, budżet, stawka do
  klienta z walutą i podpowiedzią ze źródłem, marża /h i /mies. — `lib/dl-review-margin.ts` na `rateToHourly` i 168 h,
  ostrzeżenie poniżej mediany klienta, punkty odniesienia, „Akceptuj — wysyłam za X”, „Wróć do poprawy…”, „Odrzuć…”),
  `ReturnForFixDialog` (checkboksy z `fix_options` + uwaga). `DlReviewBody` zostaje re-eksportem; układ `@container`
  (3 kolumny ≥ ~1150 px), na Tablicy w szerokości `split`, na pulpicie okno `min(96vw,1440px)`.
- D10: pulpit grupuje przegląd po rekrutacji — przy 2+ osobach `DlReviewQueueDialog` z tabelą porównawczą; na Tablicy
  w nagłówku „QC CV” przycisk „Porównaj (N)” dla DL (poza Nordeą).
- Rekruter: baner „Delivery Lead prosi o poprawki (N)”, podświetlone pola („poprawione” po zmianie), „Zapisz i oddaj do
  przeglądu DL” (PUT + ruch na `handback_stage_def_id`).

### Testy i dokumentacja
- `test_dl_review_context.py` (kolejność podpowiedzi, macierz redakcji: DL z portfelem / spoza / HoR+DL / rekruter z
  uprawnieniem / admin, ryzyka, źródła dowodów), `test_dl_review_queue.py` (Nordea pusto, stała liczba zapytań dla 3 i 10
  osób), `test_screening_fix_requests.py`; aktualizacje board_tasks, cv_in_transit, stage_remarks, czytelnicy karty,
  authz golden. Front: DlReviewPanel (odwrócić asercję „brak marży”), tabela porównania, okno poprawek, baner, marża;
  harness `/preview/dl-review?state=returned|queue`; spis funkcji.
- CLAUDE.md: korekta „Pipeline v4” i „Przegląd Delivery Leada (03.10)” (marża od 07.10, lista poprawek) + sekcja
  przeglądu DL v2; komentarze „bez marży” w `KanbanBoardV2.tsx`/`DlReviewPanel.tsx`; stempel przewodnika `jobs.board`.

---

## PR 3 — Stawki z rekrutacji w zamówieniu i umowie (D7: „do sprawdzenia”, nigdy blokada)

- **Reguła porównania** `services/recruitment_rate_check.py` (`compare` → `equal|differs|not_comparable`: PLN/h, dzień
  i MD ÷ 8, miesiąc tylko z miesiącem, inna waluta = nieporównywalne, tolerancja 0,01 zł/h) + lustro
  `lib/recruitment-rate-check.ts` na wspólnym fixture. **Źródło** `services/recruitment_rates.py` (`for_pairs`,
  `for_contracts` z `contract.job_id`, `for_client` po rodzinie scalonych klientów).
- **Zamówienie z maila:** `CODE_RATE_RECRUITMENT_MISMATCH` w `order_mail_gate.py`, `GateInput.recruitment_rates`
  (domyślnie puste), krok w ocenie przez `reasons.append((CODE, tekst))` (pomija MATCH_NONE, zamówienia kosztowe, brak
  stawki, nieporównywalne); dane dociągane w `_plan_and_gate` (`order_mail_ingest.py`), więc recheck działa sam; kod
  NIE w `AWAITING_CONTRACT_CODES` (karta dla DL po 3 próbach); „Zastosuj” bez zmian; liczby maskowane dla ról bez
  finansów (słowo „stawka” w powodzie).
- **Formularze zamówień:** `ContractWithOrdersRead.recruitment_rates` (redakcja jak kwoty; stawka do klienta tylko przy
  `user_can_view_client_rate`), `GET /api/clients/{id}/recruitment-rates?candidate_id&job_id`, pole w `OrderPlanContract`.
  `EditOrderDialog` i `NewContractorOrderDialog`: linia „Z rekrutacji „X” (DL, data): 165 zł/h · kandydat 140 zł/h” +
  notka przy różnicy; `OrderPlanLineCard`/`ConsultantLineModal`: ostrzeżenie dla `md_rate_revenue` vs stawka ×8.
- **Generator B2B:** prefill zwraca `recruitment_rate` (tylko z rekrutacji, bez „Stawki od”); notka pod „Stawka godz.
  (netto)”, gdy pierwszy etap w PLN się różni — nie w walidacji i nie toastem.
- **Teksty:** poprawić `ClientRateModal.tsx`, `CvHandoffWorkbench.tsx`, `pipeline_move_rules.py`, `stage_client_rate.py`
  („stawka do klienta jest punktem odniesienia dla zamówienia; do umowy idzie stawka kandydata”).
- **Testy:** `test_recruitment_rate_check.py`, `test_recruitment_rates.py`, bramka (równe → auto, różne → kolejka z
  kodem, pominięcia, test AST, `classify_hold` → other), maskowanie kwot w kolejce, redakcja listy kontraktorów,
  prefill generatora; front: fixture reguły, notki w formularzach i generatorze (zapis przechodzi).
- **Procedura i przewodniki:** treść instrukcji DL dla zamówień (lista sytuacji w kolejce, „Każda inna przyczyna”,
  opisy „z kontraktu”, co zrobić przy renegocjacji) → `python3 scripts/stamp_orders_procedure.py`; nowe serwisy do
  `ORDERS_LOGIC_SOURCES`; `stamp_screen_guides.py` dla contracts.order_mail, contracts.b2b_generator, jobs.board
  (i client.orders, jeśli zmieni się jego plik). CLAUDE.md: sekcja „Stawki z rekrutacji w zamówieniu i umowie”.

---

## Weryfikacja
- Lokalnie (bez Dockera): `ruff check`/`ruff format --check` na zmienionych plikach; pytest bez bazy (reguły, test AST
  bramki, strażnicy, authz golden); `npx vitest run <zmienione>` + `npm run type-check`. Testy z bazą: sito na PR-ze,
  pełny bieg `gh workflow run CI --ref <gałąź>` przed oddaniem do kolejki.
- Przeglądarka: harnessy `/preview/screening-form`, `/preview/dl-review`, `/preview/job-detail` — zrzuty przy
  1280×720, 1536×864 i telefonie; przeklikanie: Nowi → CV obok, Screening → wymagania obok, „Uzupełnij z notatki”,
  zapis, historia, przywrócenie, przegląd DL z marżą, „Wróć do poprawy” → baner rekrutera.
- Po każdym merge'u: `/api/health` → SHA z maina; zalogowane ścieżki przez API (token mintowany w kontenerze):
  GET/PUT formularza na parze testowej (QA), 410 na share-token, kontekst DL, a po PR3 przeliczenie kolejki zamówień
  z maila (podgląd powodów, bez „Zastosuj”).
- Przegląd kodu po każdym PR-ze (code-reviewer + security-reviewer przy PR1 i PR2: nowe trasy, kwoty, dane osobowe
  w historii wersji).
- Raport końcowy: Czeka na mnie / Zmienione / Znalezione; aktualizacja pamięci.

## Ryzyka
- Laptop 1280×720: głowa doku zabiera ~200 px — w `split` zwinąć przypięte notatki; mierzyć harnessem.
- Testy `KanbanBoardV2` (zmiana panelu) — `data-wide` zostaje, część asercji do przepisania.
- Zmiana stawki w formularzu po „CV wysłane” otwiera zadanie DL (0418) — ostrzeżenie przy polu.
- Tabela wersji trzyma wartości (w tym narodowość) — strażnik, że nie czytają jej modele AI; CASCADE przy usunięciu
  kandydata.
- Fałszywe alarmy stawek po renegocjacji — instrukcja w procedurze: popraw stawkę do klienta w rekrutacji.
