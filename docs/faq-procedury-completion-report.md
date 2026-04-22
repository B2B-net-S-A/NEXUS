# FAQ z procedurami — raport ukończenia

**Data:** 2026-04-21
**Plan:** [`~/.claude/plans/faq-z-procedurami-stateful-sutton.md`](../../.claude/plans/faq-z-procedurami-stateful-sutton.md)

## Co zostało dostarczone

Wewnętrzna baza wiedzy (SOP) dla zespołu rekruterów — osobna strona w sidebarze (System → Pomoc), pełne CRUD w rękach admina, wyszukiwarka po tytule i treści, markdown z podglądem live.

## Zmiany (pliki)

### Backend — nowe pliki
- `backend/app/models/procedure.py` — model SQLAlchemy `Procedure` (id, title, slug, content, sort_order, is_published, audit fields).
- `backend/app/api/procedures.py` — router z 5 endpointami (list/get/post/put/delete), Pydantic schemas, helpery `_slugify` / `_ensure_unique_slug`, ILIKE search.
- `backend/alembic/versions/0029_procedures.py` — migracja tworząca tabelę `procedures` + 3 indeksy.
- `backend/tests/test_procedures.py` — 9 testów pokrywających RBAC, CRUD, search, published_only, unikalność slug, autoryzację.

### Backend — modyfikacje
- `backend/app/models/__init__.py` — export `Procedure`.
- `backend/app/main.py` — import `procedures` + `include_router(procedures.router, prefix="/api", tags=["procedures"])`.

### Frontend — nowe pliki
- `frontend/src/lib/api/procedures.ts` — typed API client (`proceduresApi.list/get/create/update/remove`).
- `frontend/src/app/help/page.tsx` — route `/help`.
- `frontend/src/components/v2/pages/HelpPageV2.tsx` — layout dwukolumnowy (search + lista po lewej, markdown content po prawej), integracja z React Query, toastach i hasRole.
- `frontend/src/components/v2/modals/ProcedureEditorModal.tsx` — Radix Dialog z edytorem split-view (textarea + live markdown preview), walidacja Zod, React Hook Form.

### Frontend — modyfikacje
- `frontend/src/components/v2/shell/SidebarV2.tsx` — import `HelpCircle` + nowy item **"Pomoc"** jako pierwszy w sekcji System.
- `frontend/package.json` — deps: `react-markdown@^9.0.1`, `remark-gfm@^4.0.0`, `@tailwindcss/typography@^0.5.15` (dev).
- `frontend/tailwind.config.ts` — `plugins: [require("@tailwindcss/typography")]`.

## Endpointy API

| Metoda | Ścieżka | Auth | Opis |
|---|---|---|---|
| GET | `/api/procedures` | zalogowany | Lista. Params: `q` (search), `published_only` (non-admin zawsze `true`) |
| GET | `/api/procedures/{id\|slug}` | zalogowany | Szczegóły; non-admin nie widzi szkiców (404) |
| POST | `/api/procedures` | admin | Tworzy; slug generowany serwerowo |
| PUT | `/api/procedures/{id}` | admin | Parcjalna edycja; zmiana tytułu regeneruje slug |
| DELETE | `/api/procedures/{id}` | admin | Twarde usunięcie |

## Schemat tabeli `procedures`

```sql
CREATE TABLE procedures (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    slug VARCHAR(255) NOT NULL UNIQUE,
    content TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_published BOOLEAN NOT NULL DEFAULT true,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- + 3 indeksy (slug, sort_order, published_sort composite)
```

## Weryfikacja — stan obecny

### ✅ Zweryfikowane
- **TypeScript type-check** (`npx tsc --noEmit`): kod procedur przechodzi clean. Pre-existing błędy w innych plikach (`@/lib/ui-flag`, `@/components/Sidebar`, `@/components/OpenTabs`, `ScorecardModal`) są niezwiązane.
- **Backend import sanity** (w kontenerze): `from app.api.procedures import router` → router z 5 endpointami załadowany OK. `from app.models.procedure import Procedure` → model OK.
- **Migracja DB**: tabela `procedures` została zastosowana do lokalnej bazy ręcznie via `psql` (migracja alembic nie dała się uruchomić automatycznie — powód w sekcji "Znane bloki" niżej). Struktura i indeksy zgodne z modelem.

### ❌ NIE zweryfikowane live (zablokowane pre-existing issues)
- **Backend API smoke test** (`curl /api/procedures`) — backend w restart loop, patrz niżej.
- **Backend pytest** (`pytest tests/test_procedures.py`) — testy napisane i kompletne, ale nie uruchomione z powodu restart loop.
- **Chrome verification UI** (agent-browser) — wymaga działającego backendu + świeżego obrazu frontendu.

## Znane bloki weryfikacyjne (pre-existing, niezwiązane z tym taskiem)

### 1. Multi-head / broken revision chain w Alembic
W `backend/alembic/versions/` **pięć** migracji ma `revision = "0029"` (nie tylko moja):
```
0029_candidate_availability.py
0029_job_collaborators.py
0029_notifications_triggers.py
0029_procedures.py          ← moja
0029_proposal_snapshots.py
```
Plus inne migracje (`0031_champion_profile_notification_type.py`) odwołują się do `down_revision = "0030"` która nie istnieje (jest tylko `0030_candidate_created_by`).

Moja migracja została zmieniona tak, by `revision = "0029_procedures"` (unique) → nie dokłada się do konfliktu. Ale `alembic upgrade` nadal wali się w runtime przez **pozostałe** duplikaty.

Obejście dev entrypoint: w DEBUG mode `Base.metadata.create_all()` tworzy tabele mimo niepowodzenia alembica.

**Rekomendacja:** osobna sesja — konsolidacja heads alembica (scal 5 migracji 0029 w single-chain, napraw `down_revision` w 0031 files).

### 2. Backend restart loop (`public_share.py`)
Backend Docker nie utrzymuje up-statusu dłużej niż ~30-60s. Root cause w logach:
```
fastapi.exceptions.FastAPIError: Invalid args for response field!
Hint: check that ForwardRef('UploadFile') is a valid Pydantic field type.
File "/app/app/api/public_share.py", line 207
```
Plik `backend/app/api/public_share.py:205-218` ma endpoint `POST /apply/{token}` z `cv: UploadFile = File(...)` — w kombinacji z return annotation `-> dict:` FastAPI próbuje zbudować `response_model` z ForwardRef i się wywala.

**Naprawa (< 1 min, ale poza scope tego taska):** dodać `response_model=None` w dekoratorze `@router.post("/apply/{token}", status_code=201, response_model=None)`.

Dopóki to nie zostanie naprawione, backend pada przy starcie → wszystkie testy integration i Chrome verification są zablokowane.

### 3. Frontend Docker image (stary)
Aktualnie działający kontener `nexusats-frontend-1` ma image sprzed 3 dni — **nie zawiera** moich zmian (help page / sidebar / markdown deps). `docker compose build frontend` rozpoczął się (npm install OK, 256s), ale trwał > 4 min bez ukończenia w sesji.

**Rekomendacja:** wykonać build wg instrukcji poniżej.

## Jak dokończyć weryfikację (po naprawie pre-existing issues)

### Krok 1: Napraw `public_share.py` (1 linia)
```python
# backend/app/api/public_share.py:205
@router.post("/apply/{token}", status_code=status.HTTP_201_CREATED, response_model=None)
```
Restart: `docker compose restart backend`. Powinien wstać stabilnie.

### Krok 2: Uruchom backend testy
```bash
docker compose exec backend pip install --quiet pytest pytest-asyncio httpx
docker compose exec backend python -m pytest tests/test_procedures.py -v
```
Oczekiwany wynik: 9 passed (dotyczą tylko `/api/procedures` — jobs.delivery_lead_id drift nie ma na nie wpływu, bo test nie tyka tabeli jobs).

### Krok 3: Rebuild + uruchom frontend
```bash
docker compose build frontend
docker compose up -d frontend
```

### Krok 4: Chrome verification (agent-browser)
Zgodnie z regułą `~/.claude/rules/autonomous-verification.md §2`:

1. **Admin flow:**
   - Zaloguj się jako `artur@b2bnet.pl` (admin)
   - Otwórz `http://localhost:3001/help` — sidebar pokazuje **Pomoc** w sekcji System
   - Klik "Dodaj procedurę" → wpisz tytuł `Jak skontaktować się z klientem`, treść `# Krok 1\n- …`
   - Zapisz → wpis pojawia się na liście, content renderuje markdown
   - Screenshot + analiza wizualna

2. **Recruiter flow:**
   - Wyloguj → zaloguj jako user z rolą `recruiter`
   - Otwórz `/help` — widzi wpis admina, **nie widzi** przycisków Edytuj/Usuń/Dodaj
   - Screenshot

3. **Search flow:**
   - Wpisz `klient` w wyszukiwarkę → lista filtruje się do wyników
   - Screenshot

### Krok 5: Rollback migracji (jeśli potrzeba)
```sql
-- jeśli trzeba cofnąć test-data lub tabelę:
DROP TABLE IF EXISTS procedures CASCADE;
```

## Świadomie pominięte (plan MVP)

Zgodnie z zatwierdzonym planem i regułą `common/coding-style.md §"don't add features beyond what the task requires"`:

- Kategorii/tagów (user ich nie wybrał w AskUserQuestion)
- Role-based widoczności pojedynczych wpisów
- Historii zmian / wersjonowania
- Pełnego FTS z `tsvector` (ILIKE wystarczy do skali kilkudziesięciu wpisów)
- Załączników (markdown wspiera linki zewnętrzne)
- **Frontend unit/E2E testów**: w repo nie istnieje żadna konfiguracja vitest/playwright (brak `vitest.config.*`, brak `playwright.config.*`, zero testów). Zbudowanie tej infrastruktury od zera wykracza poza scope tej funkcji — rekomendacja do osobnego taska "frontend test harness setup".

## Otwarte pytania / decyzje dla usera

1. **Napraw alembic head chain** (blokuje też inne feature branche). Rekomendacja: osobna sesja dedykowana konsolidacji migracji.
2. **Napraw public_share.py** (1-liniowy fix, ale technicznie "cudzy" kod — zdecyduj czy robić teraz czy osobno).
3. **Rozważ dodanie kategorii w v2 MVP+** po pierwszym feedbacku od zespołu (jeśli lista procedur > 10, kategoryzacja zacznie mieć sens).
