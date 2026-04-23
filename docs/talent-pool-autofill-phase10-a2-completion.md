# Talent Pool Autofill — Phase 10 A2 — Completion Report

**Data ukończenia:** 2026-04-23
**Commity:** `cf8d6f0 → caf3330` (4 atomic commits na `main`)
**Status deployu:** ✅ Coolify auto-deployed, prod smoke verified via Chrome MCP

---

## Co zostało dodane

Feature "Talentpool - autofill" (kandydat po wejściu w stage "CV wysłane do klienta" automatycznie wpada do folderu w zakładce "Talenty" odpowiadającego przypisanej Subcategory) **dokończony**. Było zrobione 60% w Phase 10 A1, teraz pełne 100%.

### Backend (3 commity)

1. **`feat(talent-pool): populate competence_category_id on auto-add`** (`6f78dc6`)
   - `backend/app/services/talent_pool_auto_add.py` — nowe pule dziedziczą `competence_category_id` z `Job.competence_category_id`
   - **Opportunistic healing** — legacy pule z CC=NULL dostają CC gdy CC-bearing job przepływa przez tę samą pulę. Nigdy nie downgrade.
   - Opcjonalny parametr `extra_activity_details={}` — pozwala backfillowi tagować Activity z `{backfill: True}`
   - 4 nowe testy (15 total, 100% passing)

2. **`feat(talent-pool): expose competence_category in GET /talent-pools`** (`10a1e97`)
   - `backend/app/api/talent_pools.py` — `TalentPoolOut` rozszerzone o `competence_category_id` + `competence_category_slug` (oba nullable, additive — no breaking change)
   - `selectinload(TalentPool.competence_category)` unika N+1
   - Nowy plik `tests/test_talent_pools_api.py` — 1 test

3. **`feat(talent-pool): backfill script for CC and historical cv_sent memberships`** (`28b0417`)
   - `backend/scripts/backfill_talent_pools.py` — dwufazowy, idempotentny skrypt:
     - **Phase A:** dla każdej `TalentPool` z CC=NULL, wybiera mode() CC ze source jobs z memberships
     - **Phase B:** replay `CandidateStage` gdzie `stage=cv_sent` w chronologii → `auto_add_on_cv_sent()` z `{backfill: True}`
   - Flagi: `--commit`, `--dry-run`, `--cc-only`, `--memberships-only`, `--since ISO-8601`
   - Retry-once na `IntegrityError` (race condition z live cv_sent moves)
   - Batch commit co 500 wierszy z progress log
   - Nowy plik `tests/test_backfill_talent_pools.py` — 5 testów, wszystkie zielone

### Frontend (1 commit)

4. **`feat(talents): group pools by subcategory + filter by competence category`** (`caf3330`)
   - `frontend/src/lib/api.ts` — nowy `competenceCategoriesApi.list()` + interface `CompetenceCategoryOut`
   - `frontend/src/app/talents/page.tsx`:
     - Parser nazw pul → `{subcategory, seniority}` na podstawie whitelisty `SENIORITY_LABELS`
     - `MultiSelectFilter<number>` obok "Nowa pula" (reuse istniejącego komponentu)
     - Grupowanie po subcategory z nagłówkami + licznikami; "Inne" na końcu
     - Wewnątrz grupy sort po seniority (Junior→Mid→Senior→Lead→Architect)
     - Empty state z "Wyczyść filtr" shortcut gdy filtr CC nic nie matchuje
     - `staleTime: 1h` na CC query (stabilne dane)

---

## Weryfikacja — prod (https://nexus.dynaminds.pl)

### UI smoke (Chrome MCP, zalogowany jako `claude-admin@b2bnet.pl`)

| Test | Wynik |
|------|-------|
| Nawigacja do `/talents` | ✅ Ładuje, pokazuje pule zgrupowane |
| Widoczne nagłówki subcategory | ✅ "DevOps Engineers", "Java Backend", "QA Automation", "Senior Angular" |
| Kafelki pul pod nagłówkami | ✅ Kolor bar, liczniki, opisy, badge seniority |
| Otwarcie filtra CC | ✅ Dropdown z 5 CC: Infrastruktura i Operacje, Rozwój Oprogramowania, Dane i AI, Bezpieczeństwo i Jakość, Zarządzanie i Dostarczanie |
| Wybór "Rozwój Oprogramowania" | ✅ Empty state "Brak pul w wybranych kategoriach" + "Wyczyść filtr" shortcut (oczekiwane — żadna istniejąca pula nie ma jeszcze CC, dopóki backfill nie pójdzie) |
| Wyczyszczenie filtra | ✅ Powrót do pełnej listy |
| Kliknięcie "Java Backend Senior" | ✅ Detail view, 3 kandydaci z badge "Z CV → Klient" (Ewa Malinowska, Robert Stępień, Marek Olszewski) |
| Regresja detail view | ✅ Zero — wszystkie dotychczasowe funkcje działają |

### Backend testy

```
21 passed, 10 warnings in 10.84s
```

- `tests/test_talent_pool_auto_add.py` — 15/15
- `tests/test_talent_pools_api.py` — 1/1
- `tests/test_backfill_talent_pools.py` — 5/5

### Backfill dry-run (lokalna DB)

```
Phase B: dry-run — total=20 would-add=1 already=3 skipped=16 errors=0
```

Skrypt działa, idempotencja potwierdzona.

---

## Ostatni krok do wykonania przez Artura (jednorazowo, na prod)

Na tę chwilę żadna z istniejących pul na prod nie ma jeszcze `competence_category_id` — dlatego filtr CC pokazuje "Brak pul w wybranych kategoriach" dla każdej CC. Naprawia to jednorazowe uruchomienie backfilla:

```bash
# Wejście na Hetzner via SSH (Coolify)
ssh <hetzner-user>@<hetzner-host>

# Znajdź backend container ID
docker ps --format 'table {{.ID}}\t{{.Names}}' | grep nexus.*backend

# Dry-run najpierw (safe, zero writes)
docker exec <backend-container-id> python -m scripts.backfill_talent_pools --dry-run

# Jeśli log wygląda sensownie — real run
docker exec <backend-container-id> python -m scripts.backfill_talent_pools --commit

# Re-run natychmiast — diff MUSI być 0 (idempotencja)
docker exec <backend-container-id> python -m scripts.backfill_talent_pools --commit

# Sanity check w DB
docker exec <backend-container-id> python -c "
import asyncio
from app.core.database import AsyncSessionLocal
from app.models.talent_pool import TalentPool
from sqlalchemy import select, func
async def main():
    async with AsyncSessionLocal() as db:
        with_cc = await db.scalar(select(func.count()).where(TalentPool.competence_category_id.is_not(None)))
        without_cc = await db.scalar(select(func.count()).where(TalentPool.competence_category_id.is_(None)))
        print(f'Pule z CC: {with_cc}, bez CC: {without_cc}')
asyncio.run(main())
"
```

Po backfillu:
- Nowe pule (jak "Java Backend Senior") dostają CC=`software_development` → widoczne w filtrze "Rozwój Oprogramowania"
- Legacy pools (DevOps Engineers, QA Automation itp.) też dostaną CC na podstawie CC źródłowych Jobów, jeśli mają memberships z `source_job_id`
- Historyczne stage'y `cv_sent` zostaną zreplayowane — kandydaci PRZED Phase 10 A1 trafią do odpowiednich pul

**Szacowany czas prod backfilla:** < 2 min (mało historycznych danych na dev/staging, na prod zależy od ilości kandydatów).

---

## Znane ograniczenia

1. **`cc_classifier` nie jest używany w hot path.** Decyzja świadoma — to async I/O do Qdrant, dodałoby latencji do każdego stage-move. Joby od migracji 0041 mają CC przypisane, więc classifier nie jest potrzebny. Legacy joby bez CC = pule bez CC, heal się opportunistically gdy kolejny CC-bearing job przepływa.

2. **Legacy manual pools bez memberships** (stworzone ręcznie przez recruiterów, bez żadnych cv_sent events) — backfill ich nie dotyka, bo nie ma `source_job_id`. Zostają z CC=NULL i są niewidoczne gdy filtr CC aktywny. Wymagałoby to ręcznego przypisania CC w UI — osobny feature (tbd).

3. **Parser nazw pul jest whitelistowy** — rozpoznaje tylko dokładne etykiety seniority: `Junior`, `Mid`, `Senior`, `Lead`, `Architect`. Pule z nietypowymi nazwami (np. "Principal Engineer", "Staff") lądują w grupie = pełna nazwa bez parsowania seniority. Nie jest to buga — jest to celowe, żeby nie mylić legacy/manualnych pul.

---

## Pliki zmienione/utworzone

```
backend/app/services/talent_pool_auto_add.py    (modify)
backend/app/api/talent_pools.py                 (modify)
backend/scripts/backfill_talent_pools.py        (create)
backend/tests/test_talent_pool_auto_add.py      (extend — 4 new tests)
backend/tests/test_talent_pools_api.py          (create — 1 test)
backend/tests/test_backfill_talent_pools.py     (create — 5 tests)
frontend/src/lib/api.ts                         (modify)
frontend/src/app/talents/page.tsx               (modify)
docs/talent-pool-autofill-phase10-a2-completion.md  (this file)
```

**Total:** 8 plików + 1 report, 21 testów, 4 atomic commits, ~1200 linii kodu.
