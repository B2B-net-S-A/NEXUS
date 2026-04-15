# DynaMinds Nexus — QA Strategy
**Wersja:** 1.0 | **Data:** 2026-03-19

---

## Zasada #1: Żaden feature nie jest "gotowy" bez testów

```
Definition of Done (DoD):
✅ Kod napisany i działa lokalnie
✅ Testy napisane i przechodzą
✅ Test plan zaktualizowany
✅ Code review (jeśli >100 LOC)
✅ Smoke test na staging
```

---

## Piramida Testów

```
         🔺 E2E (Playwright)
        /    \     — krytyczne ścieżki użytkownika
       /      \    — 10-15 scenariuszy
      /────────\
     / Integration \   — API endpoint testy (pytest + httpx)
    /    (pytest)    \  — 50-100 testów
   /──────────────────\
  /    Unit Tests       \  — logika biznesowa, utility
 /     (pytest + vitest) \  — 100+ testów
/────────────────────────────\
```

### Podział:
| Warstwa | Narzędzie | Co testujemy | Target |
|---------|-----------|-------------|--------|
| **Unit** (Backend) | pytest | Modele, schematy, utility, kalkulacje | 100+ testów |
| **Unit** (Frontend) | vitest + RTL | Komponenty, hooks, formattery | 50+ testów |
| **Integration** (API) | pytest + httpx | Endpointy, auth, pipeline flow | 50+ testów |
| **E2E** | Playwright | Pełne ścieżki user journey | 15 scenariuszy |

---

## Test Plan Template

Każdy nowy feature dostaje swój test plan PRZED implementacją:

```markdown
### Feature: [Nazwa]
**Ticket:** [link]
**Autor:** [kto]

#### Test Cases:
| # | Scenariusz | Typ | Priorytet | Status |
|---|-----------|-----|-----------|--------|
| 1 | Happy path — opis | Integration | P0 | ⬜ |
| 2 | Edge case — opis | Unit | P1 | ⬜ |
| 3 | Error handling — opis | Integration | P1 | ⬜ |
| 4 | UI renders correctly | E2E | P2 | ⬜ |

#### Acceptance Criteria:
- [ ] Kryterium 1
- [ ] Kryterium 2
```

---

## Backend Tests (pytest)

### Struktura
```
backend/
├── tests/
│   ├── conftest.py          # Fixtures: test DB, test client, auth headers
│   ├── test_auth.py         # Login, token, permissions
│   ├── test_candidates.py   # CRUD kandydatów
│   ├── test_jobs.py         # CRUD ofert
│   ├── test_pipeline.py     # Pipeline move, kanban, overview, stages
│   ├── test_contracts.py    # Kontrakty, marże
│   ├── test_dashboard.py    # KPI stats
│   ├── test_search.py       # Search + AI matching
│   ├── test_screenings.py   # Structured screenings
│   ├── test_prep_kit.py     # AI Prep Kit generation
│   └── test_cv_generator.py # CV generation
```

### conftest.py — kluczowe fixtures
```python
@pytest.fixture
async def db_session():
    """Isolated test database session — rollback after each test."""

@pytest.fixture
async def client(db_session):
    """Async httpx test client with app mounted."""

@pytest.fixture
async def auth_headers(client):
    """Login as admin, return headers with Bearer token."""

@pytest.fixture
async def sample_data(db_session):
    """Seed minimal test data: 1 user, 3 candidates, 2 jobs, pipeline entries."""
```

### Przykładowe testy pipeline:
```python
async def test_move_candidate_through_pipeline(client, auth_headers, sample_data):
    """Kandydat przechodzi new → prep_call → screening → interview."""
    
async def test_kanban_returns_all_stages(client, auth_headers, sample_data):
    """GET /kanban/{job_id} zwraca kolumny dla wszystkich stage'ów."""

async def test_overview_detects_bottleneck(client, auth_headers):
    """3+ kandydatów na prep_call → bottleneck alert."""

async def test_overview_detects_opportunity(client, auth_headers):
    """Kandydat na acceptance → opportunity alert."""

async def test_days_in_stage_calculation():
    """Kandydat dodany 5 dni temu → days_in_stage = 5."""

async def test_reject_candidate_with_reason(client, auth_headers, sample_data):
    """Move to rejected z notatką powodu."""

async def test_withdrawn_candidate(client, auth_headers, sample_data):
    """Kandydat wycofuje się — stage = withdrawn."""
```

---

## Frontend Tests (vitest + React Testing Library)

### Struktura
```
frontend/
├── __tests__/
│   ├── components/
│   │   ├── KanbanBoard.test.tsx
│   │   ├── CandidateCard.test.tsx
│   │   ├── Sidebar.test.tsx
│   │   └── DataTable.test.tsx
│   ├── pages/
│   │   ├── manager.test.tsx
│   │   └── candidates.test.tsx
│   └── utils/
│       └── formatters.test.ts
```

### Przykłady:
```typescript
test('KanbanBoard renders all stage columns', () => {})
test('KanbanBoard filters by internal/external tab', () => {})
test('CandidateCard shows red badge when >7 days', () => {})
test('CandidateCard shows amber badge when 3-7 days', () => {})
test('Manager page shows bottleneck alerts', () => {})
```

---

## E2E Tests (Playwright)

### Krytyczne ścieżki (P0):
| # | Scenariusz | Oczekiwany wynik |
|---|-----------|-----------------|
| 1 | Login → Dashboard | Dashboard loads z KPI |
| 2 | Dodaj kandydata → widoczny na liście | Redirect + kandydat w tabeli |
| 3 | Kanban drag & drop | Stage zmienia się po drag |
| 4 | Pipeline: new → prep_call → screening | 3 moves, history OK |
| 5 | Manager Dashboard loads | KPI cards + heatmap + alerts |
| 6 | Search kandydata po nazwisku | Wyniki search |
| 7 | CV Generator → pobranie PDF | HTML preview + download |
| 8 | Dodaj job → kanban widoczny | Empty kanban with all stages |
| 9 | Kontrakty: marże kalkulowane | Stawka klienta - stawka kandydata |
| 10 | Dark mode toggle | Klasy CSS zmienione |

### Smoke Test Suite (quick):
Zestaw 5 testów uruchamianych przed każdym deploy:
1. Login
2. Dashboard loads
3. Candidates list loads
4. Jobs list + kanban loads
5. Manager overview loads

---

## Workflow Agile

### Sprint (1 tydzień):
```
Poniedziałek:  Planning + Test Plan dla nowych features
Wtorek-Czwartek: Development + pisanie testów (TDD/BDD)
Piątek:        QA Review + Regression + Deploy to staging
```

### Każdy Pull Request:
1. ✅ Testy jednostkowe przechodzą (`pytest` / `vitest`)
2. ✅ Test plan zaktualizowany
3. ✅ Nowe testy dodane dla nowego kodu
4. ✅ Regression suite przechodzi (E2E smoke)

### CI Pipeline (docelowy):
```yaml
on: [push]
jobs:
  test:
    steps:
      - run: pytest backend/tests/ -v
      - run: cd frontend && npx vitest run
      - run: npx playwright test --project=smoke
  deploy:
    needs: test
    if: github.ref == 'main'
    steps:
      - run: docker compose build && deploy
```

---

## Regression Test Matrix

Aktualizowana przy każdym release:

| Moduł | Unit | Integration | E2E | Ostatni test | Status |
|-------|------|-------------|-----|-------------|--------|
| Auth & Login | ⬜ | ⬜ | ⬜ | - | 🔴 Brak |
| Kandydaci CRUD | ⬜ | ⬜ | ⬜ | - | 🔴 Brak |
| Pipeline (kanban) | ⬜ | ⬜ | ⬜ | - | 🔴 Brak |
| Manager Dashboard | ⬜ | ⬜ | ⬜ | - | 🔴 Brak |
| Oferty pracy | ⬜ | ⬜ | ⬜ | - | 🔴 Brak |
| Kontrakty | ⬜ | ⬜ | ⬜ | - | 🔴 Brak |
| Search | ⬜ | ⬜ | ⬜ | - | 🔴 Brak |
| CV Generator | ⬜ | ⬜ | ⬜ | - | 🔴 Brak |
| Prep Kit | ⬜ | ⬜ | ⬜ | - | 🔴 Brak |
| Screenings | ⬜ | ⬜ | ⬜ | - | 🔴 Brak |
| Reports | ⬜ | ⬜ | ⬜ | - | 🔴 Brak |
| Sales Pipeline | ⬜ | ⬜ | ⬜ | - | 🔴 Brak |
| Calendar | ⬜ | ⬜ | ⬜ | - | 🔴 Brak |
| Admin | ⬜ | ⬜ | ⬜ | - | 🔴 Brak |
| Settings | ⬜ | ⬜ | ⬜ | - | 🔴 Brak |

**Legenda:** ⬜ Brak | ✅ Pass | ❌ Fail | 🟡 Partial

---

## Quick Win: Co napisać najpierw

### Faza 1 (ten tydzień — razem z pipeline remodel):
1. **conftest.py** — test DB, client, auth fixtures
2. **test_pipeline.py** — pipeline flow, kanban, overview
3. **test_auth.py** — login, token, unauthorized access
4. **Playwright smoke** — 5 basic E2E tests

### Faza 2 (przyszły tydzień):
5. test_candidates.py
6. test_jobs.py
7. test_contracts.py
8. KanbanBoard.test.tsx
9. CandidateCard.test.tsx

### Faza 3 (przed deploy):
10. Full E2E suite (10 scenarios)
11. CI pipeline config
12. Pre-deploy checklist automation

---

## Narzędzia do zainstalowania

### Backend:
```bash
pip install pytest pytest-asyncio httpx pytest-cov
```

### Frontend:
```bash
npm install -D vitest @testing-library/react @testing-library/jest-dom @vitejs/plugin-react jsdom
```

### E2E:
```bash
npx playwright install
```

---

*Każdy feature bez testów to dług techniczny. Każdy test to inwestycja w spokojny sen.*
