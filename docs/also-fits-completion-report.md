# „Pasuje też do” — raport ukończenia (PR 1 z 2, 14.10.2026)

Prośba Artura 14.10.2026: osoba dodana do rekrutacji A często pasuje do innych otwartych rekrutacji, a NEXUS
tego nie podpowiadał. Makiety i decyzje D1–D4: https://claude.ai/artifact/RTUD8nEm1dRXrarnwHrE7f (A1–A2).
Reguła w repo: `docs/claude/rekrutacja-tablica/prostszy-ekran-rekrutacji-fakty-kafle-kandydaci-do.md`,
sekcja „„Pasuje też do” po „+ Dodaj””. PR 2 („Screening dla” — screening pod kilka rekrutacji w jednym
panelu) idzie osobno, po scaleniu tego.

## Co zmienione

| Część | Gdzie |
|---|---|
| Ocena „pasuje też do” — ta sama co „Moi ludzie” | `backend/app/services/my_people_matching.py` (`fits_for_job`, `JobFit`; `score_people_for_job` woła ją bez zmiany zachowania) |
| Pula, zawężenie Qdrantem, top 3 ≥ 70, „+1 rekrutacja”, dzwonek | `backend/app/services/also_fits.py` |
| Trasa `GET /api/candidates/{id}/also-fits?from_job_id=` | `backend/app/api/also_fits.py`, `main.py`, `tests/data/authz_golden/also_fits.json`, `_SCOPED_MODULES` |
| Źródło dodania `also_fits` + `origin_job_id` | `api/proposals_bulk.py`, `services/match_telemetry_service.py`, `frontend/src/lib/candidate-search-api.ts` |
| Dzwonek `also_fits_added` | `models/notification.py`, migracja `0444_also_fits_added_notification`, `entrypoint.sh`, `notification_categories.py`, `notification_access.py`, `NotificationsDropdown.tsx` |
| `other_open_jobs` na karcie Tablicy | `api/pipeline.py` (`build_kanban_view`, flaga `with_other_jobs`), `schemas/pipeline.py` |
| Blok A1 pod dodaną osobą | `also-fits-block.tsx`, `useAlsoFitsJobs.ts`, `pick-list.tsx` (`PickRow.alsoFits`), `AddCandidatesPanel.tsx`, `useSearchBaseTab.tsx`, `useUndoWindow.ts` (klucz generyczny) |
| Chip A2 na karcie | `kanban-other-jobs-chip.tsx`, `KanbanBoardV2.tsx`, `kanban-shared.tsx` |
| Spis funkcji, przewodnik | `recruitment-feature-inventory.json` (`board.sources-row-also-fits`, `board.card-other-jobs`), `guides.json` `jobs.board` + stempel |
| Harness | `/preview/job-detail?sources=base` (Oskar Wzorcowy: 2 podpowiedzi), `/preview/job-detail` (Anna Przykładowa: „+1 rekrutacja”) |

## Weryfikacja

- Backend bez bazy (lokalnie, py3.12): `test_also_fits.py` (selekcja, przebieg z podmienionym Qdrantem i oceną,
  awaria = `unavailable`, słowniki źródeł, rejestr dzwonka), lustro migracji, `test_must_gate_evidence_wiring`,
  `test_search_round9` (refaktor „Moich ludzi”), `test_job_scope_contract`, `test_authz_guard_matrix`,
  przewodniki — zielone.
- Backend z bazą (`test_also_fits_db.py`: pula, trasa, dodanie z dzwonkiem i Activity, `other_open_jobs`) —
  w CI (lokalnie bez Postgresa).
- Front: vitest nowych plików (blok, hak, chip) + `AddCandidatesPanel`, `KanbanBoardV2`, `NotificationsDropdown`,
  spis funkcji — zielone; `type-check` czysty.
- Harness przeklikany (Playwright, 1280 × 720): blok z dwiema rekrutacjami, „+ Dodaj” → „Dodano · Cofnij”,
  „Cofnij” → z powrotem „+ Dodaj”; osoba bez podpowiedzi — brak bloku; chip na karcie otwiera okienko
  i nie otwiera panelu osoby.

## Poprawki po przeglądzie kodu

- Migracja przenumerowana na `0444` (na mainie weszła `0443_integrations_v1`).
- Dzwonek kluczowany nowym wierszem etapu w B, nie osobą — dedup dzienny gubił drugi dzwonek przy
  „Dodaj do wszystkich” u tego samego rekrutera (test z bazą: dwie rekrutacje, dwa dzwonki).
- Tablica pyta o inne rekrutacje tylko osoby z kart w „Nowych”/„Screeningu”, bez pełnych wierszy
  rekrutacji, z filtrem etapów w SQL.
- Okno pyta samo tylko o 3 ostatnio dodane osoby; reszta na „Sprawdź, gdzie jeszcze pasuje”.

## Świadomie poza zakresem

- Zakładka „Szukaj ręcznie” — bez bloku (nie ma tam też „Cofnij”). Dopisane 15.10.2026: pasek „Dodani teraz”
  z „Cofnij” i „Pasuje też do” (`ManualAddedStrip.tsx`).
- „Screening razem” w okienku chipa — PR 2.
- Quick-view bez `job_read_scope_clause` i limit 3 w „W innych rekrutacjach” — PR 2 poprawia limit.

## Po scaleniu

Wdrożenie w oknie 19:00–07:00, potem `/api/health` = SHA z maina. Na produkcji: jedno dodanie w rekrutacji
testowej i odczyt `GET …/also-fits` (tylko odczyt, bez dodawania prawdziwych osób bez zgody Artura).
