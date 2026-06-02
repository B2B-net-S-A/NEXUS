[← README](../README.md)

# Completion report — „Sugerowane rekrutacje" pokazuje też szkice (draft+published)

**Data:** 2026-06-02
**PR:** [#389](https://github.com/artur-t-96/Nexus/pull/389) (squash → `main` jako `78c1d4a`)
**Status:** ✅ zdeployowane i zweryfikowane na prodzie

## Problem

Widget **„Sugerowane rekrutacje"** na profilu kandydata (`SuggestedJobsWidget`,
endpoint `GET /api/candidates/{id}/recommendations`) pokazywał *„Brak sugerowanych
projektów"* dla ~99,6% kandydatów.

**Root cause** (zweryfikowane na prodzie 2026-06-02): endpoint domyślnie miał
`only_open=True`, co filtrowało **wyłącznie** `Job.status == published`. Na prodzie
jest ~**14 published z 3883** jobów — reszta to drafty. Semantic search prawie zawsze
zwracał 0 published matchy → widget pusty.

Dla kontrastu marketplace („targ", `scan_candidate_for_top_jobs`) filtruje
`draft+published` i **znajduje** dopasowania — dlatego przycisk „Wrzuć na targ"
(PR #386) działał, a widget obok — nie.

## Decyzja

Decyzja produktowa potwierdzona z Arturem → **opcja (a): włączyć szkice**
(mirror filtra marketplace), z `published` jako sygnałem wyższego priorytetu.

## Zmiany

### Backend — `backend/app/api/recommendations.py`
- `_RECOMMENDABLE_STATUSES = (JobStatus.draft, JobStatus.published)` — mirror
  `marketplace_service.scan_candidate_for_top_jobs` („otwarte joby"); `closed`
  nigdy nierekomendowane.
- `only_open` (domyślnie `True`) przedefiniowane: *otwarte* = draft+published
  (zamiast published-only). `only_open=False` nadal = wszystkie incl. closed.
- Fallback przy pustym/offline Qdrant: `draft+published` zamiast published-only.
- `_recommendation_rank_key(total, status)` — **published rankowane przed draftami**
  (higher-priority signal). Re-rank odbywa się **przed** cięciem `top_k`, żeby
  published matche nie wypadły przez sort tylko po score. W obrębie jednego
  bucketu statusu: wyższy score wygrywa.

### Frontend — `frontend/src/components/SuggestedJobsWidget.tsx`
- Badge **„Szkic"** (amber) dla `job.status === "draft"` — spójny z labelami
  w `jobs/[id]` i `clients/[id]`.
- Poprawiony tekst pustego stanu: usunięte mylące „masz opublikowane oferty",
  teraz wskazuje na CV / uzupełnione umiejętności.

> Z fixu korzysta też `QuickAssignV2` (zakładka „AI sugestie") — używa tego samego
> endpointu bez `only_open`, więc automatycznie dostaje draft+published.

### Test + CI
- `backend/tests/test_recommendation_status_filter.py` — 5 pure unit testów
  (zestaw statusów + klucz rankujący published-first). Wpięte w selektywną listę
  pytest w `.github/workflows/ci.yml`.

## Weryfikacja

| Krok | Wynik |
|---|---|
| `ruff check` + `ruff format --check` (backend) | ✅ green (po fixup `style:` commit) |
| `python -c "from app.main import app"` | ✅ importuje się |
| `pytest tests/test_recommendation_status_filter.py` | ✅ 5 passed |
| `tsc --noEmit` (frontend) | ✅ green |
| `next lint` | ✅ green (0 nowych warningów) |
| CI PR #389 (backend/frontend/gitleaks/trivy/review) | ✅ all green |
| Deploy `/api/health` | ✅ `status: healthy`, version `84e8f90` (zawiera fix) |
| Chrome UI — kandydat z CV (Ibrahim Alizade, id 137646) | ✅ widget pokazuje 5 dopasowań |

**Dowód UI:** dla Ibrahima Alizade (Accounting Analyst) widget zwrócił 5 ról
analitycznych — wszystkie z badge „Szkic" (czyli drafty, które wcześniej były
ukryte przez filtr published-only). Job IDs: 1418, 4821, 5126, 4625, 20653;
score 31/29.

## Znane ograniczenia / uwagi

- **Niski zakres score:** composite (0–100) ma niski absolutny zakres jako sygnał
  rankingowy (patrz `RECOMMENDATION_MIN_SCORE` / pamięć „AI matching show-all").
  Widget nie progu­je score (pokazuje top_k z puli) — to świadome, bo inaczej
  byłby pusty.
- **Published-first w praktyce rzadko przestawia:** skoro published jobów jest
  mało (~14), większość kandydatów i tak zobaczy same drafty. Ranking published-first
  zadziała dopiero gdy w hitach semantycznych pojawi się published job.
- **Brak migracji** — zmiana czysto aplikacyjna.
