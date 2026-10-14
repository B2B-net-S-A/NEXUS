# „Screening dla” — raport ukończenia (PR 2 z 2, 14.10.2026)

Prośba Artura 14.10.2026: osobę, która jest (albo powinna być) w kilku rekrutacjach, rekruter screenuje w jednej
rozmowie pod wszystkie, zadaje pytania każdej rekrutacji i przekazuje dalej w każdej. Makiety i decyzje D1–D4:
https://claude.ai/artifact/RTUD8nEm1dRXrarnwHrE7f (B1–B3). PR 1 („Pasuje też do”) — `docs/also-fits-completion-report.md`.
Reguła w repo: `docs/claude/screening-notatki/jeden-formularz-screeningu.md`, sekcja „Screening pod kilka rekrutacji”;
kontrakt tras: `docs/screening-form-contract.md`, sekcja „Screening dla”.

## Co zmienione

| Część | Gdzie |
|---|---|
| Inne rekrutacje osoby do jednej rozmowy (do wyboru / z powodem) | `services/screening_form.py` (`joint_anchor`, `joint_pairs`), `GET /api/screening-form/joint-context` w `api/screening_form.py` |
| To samo pytanie w kilku rekrutacjach | `services/screening_question_groups.py`, `GET /api/screening-form/question-groups` |
| Notatka z rozmowy wspólna dla par | `services/screening_form.py` (`_reused_note` → `_joint_note_from_other_pair`) |
| „W innych rekrutacjach” bez bieżącej i z sumą | `api/candidates.py` (quick-view `exclude_job_id`, `current_recruitments_total`), `schemas/candidate.py`, `BeforeCallProfile.tsx` |
| Wzorce dostępu | `tests/data/authz_golden/screening_form.json` (dwie trasy) |
| Stan wspólny i rzut na parę | `frontend/src/lib/joint-screening.ts` (`jointDefaults`, `projectPair`, `forwardBlockers`, `dealBreakerHit`, `budgetVerdict`, `noteFillPatches`) |
| „Screening dla” (B1) | `JointScreeningPicker.tsx`, `ScreeningWorkbench.tsx` |
| Formularz wspólny i karta wyniku (B2–B3) | `JointScreeningForm.tsx`, `lib/api/screeningForm.ts` (`useJointContext`, `useScreeningQuestionGroups`) |
| „Screening razem” z karty Tablicy | `kanban-other-jobs-chip.tsx`, `KanbanBoardV2.tsx`, `store/joint-screening.ts` |
| Spis funkcji, przewodnik | `recruitment-feature-inventory.json` (`screening-form.joint-picker`, `screening-form.joint`), `guides.json` `jobs.board` + stempel |
| Harness | `/preview/screening-form?state=joint` (dwie inne rekrutacje, wspólne pytanie, deal-breaker w jednej) |

## Jak to działa (skrót)

Jeden `useForm` dla rozmowy; przy zapisie każda para dostaje swój zwykły `PUT /api/screening-form` zbudowany
z rzutu stanu wspólnego na JEJ stan (`projectPair` + `buildSavePayload`) — wersje, odcisk stanu, blokada 12 h
i odmowy 409/423 bez zmian, per para. Potem ruch na „Zweryfikowany” per para (`usePipelineMoveCore`, `silent`).
Para z trafionym deal-breakerem albo odmową kwalifikowalności zostaje zapisana, ale nie przechodzi sama —
„Przekaż mimo to” na karcie wyniku. Szczegóły reguł pól wspólnych i stawki — w pliku reguły.

## Weryfikacja

- Backend bez bazy (lokalnie, py3.12): `test_screening_question_groups.py` (6), `test_authz_guard_matrix`,
  `test_job_scope_contract`, strażnik prywatności `screening_form`, przewodniki i stemple — zielone.
- Backend z bazą (`test_joint_screening_db.py`: joint-context z powodami, grupy pytań, notatka drugiej pary
  bez kopii, odmowy notatki — inny autor / stara / osoba bez etapu w rekrutacji notatki, quick-view) — w CI.
- Front: vitest `joint-screening.test.ts`, `JointScreeningForm.test.tsx` (PUT per para z właściwymi
  `question_id`, ruch per rekrutacja, deal-breaker bez ruchu, notatka), `JointScreeningPicker.test.tsx`,
  `ScreeningWorkbench`, `ScreeningFullForm`, `BeforeCallProfile`, `KanbanBoardV2`, spis funkcji; `type-check` czysty.
- Harness przeklikany (Playwright, 1280 × 900): „Screening dla” z rekrutacją do wyboru, wyszarzoną i podpowiedzią,
  „4 pytania zamiast 6”, stawki per rekrutacja z budżetem, karta wyniku: kotwica przekazana, para z deal-breakerem
  „Przekaż mimo to”.

## Poprawki po przeglądzie kodu i bezpieczeństwa

- Rzut pary od najświeższego stanu i tylko ruszone pola z rozmowy — zapis po odświeżeniu w tle nie cofa cudzej
  zmiany (test: cudzy zapis „Notatki” w drugiej rekrutacji zostaje, `expected_version` = 4).
- Nieruszona odpowiedź na wspólne pytanie nie nadpisuje zapisanej odpowiedzi innej rekrutacji; widać ją pod polem.
- Wspólna stawka na ekranie = stawka zapisu (para bez stawki dostaje ją; zaznaczenie „Ta sama” bez zmiany kwoty też).
- „Cofnij wypełnienie” zdejmuje tylko pola z notatki.
- Formularz i karta wyniku zostają do zamknięcia karty (kotwica przesunięta = wcześniej znikały odmowy pozostałych par).
- Najwyżej 4 rekrutacje w rozmowie (5+ dawało 422 trasy grup pytań i cały formularz w błędzie).
- Nazwa klienta z `display_name` w „Screening dla” i w podpowiedziach „Pasuje też do”.
- Przegląd bezpieczeństwa: bez uwag blokujących (zakres DL, `CandidatePIIAccess`, `budget_hourly` = budżet
  rekrutacji widoczny już w formularzu, nie stawka do klienta; notatka tylko autora).

## Odstępstwa od planu

- Logika joint-context w `services/screening_form.py` (nie w osobnym `services/joint_screening.py`) — korzysta
  z `pair_edit_state`/`_claim_state` tego modułu, a strażnik prywatności i tak dopuszcza tylko ten moduł.
- „Screening razem” przekazuje wybór przez mały magazyn stanu (`store/joint-screening.ts`), nie parametr adresu
  `with=` — panel osoby otwiera się w tej samej karcie, a parametr trzeba by czyścić w kilku miejscach.
- Karta wyniku: „Przekaż mimo to” i „Otwórz jej kartę” (odrzucenie z powodem robi się na karcie tej rekrutacji);
  bez przełącznika wymagań „Obie / A / B” po lewej — wymagania pokazuje kotwica.

## Świadomie poza zakresem

- „Użyj tej odpowiedzi”, „Pomiń brakujące”, „Ułóż w zdanie” w trybie wspólnym (zostają w pojedynczym formularzu).
- Pochodzenie pól „z notatki” w trybie wspólnym (pola idą jak wpisane ręcznie).
- Quick-view bez `job_read_scope_clause` (tytuły rekrutacji spoza zakresu DL) — sprzed tej zmiany.

## Po scaleniu

Wdrożenie w oknie 19:00–07:00, potem `/api/health` = SHA z maina. Na produkcji: odczyt
`GET /api/screening-form/joint-context` dla osoby w dwóch rekrutacjach (bez zapisu screeningu prawdziwej osoby
bez zgody Artura).
