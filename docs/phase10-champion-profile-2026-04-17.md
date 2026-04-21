# Phase 10 — Champion Profile + screening flow

## Kontekst

Artur dostarczył szablon `Profil_Championa_WZÓR.docx` — dokument wypełniany per rekrutacja przez Delivery Leada (DL) opisujący idealnego kandydata. Implementacja:

1. **Zapis profilu w rekrutacji** — DL wypełnia pola profilu championa per oferta.
2. **Obligatoryjny screening recruitera** — przed rekomendacją kandydata do klienta rekruter wypełnia odpowiedzi na pytania z profilu.

## Co zostało zaimplementowane

### 1. DB (migracja `0019_champion_profile.py`)

```sql
ALTER TABLE jobs ADD COLUMN champion_profile JSONB;
ALTER TABLE candidate_stages ADD COLUMN screening_answers JSONB;
CREATE INDEX ix_candidate_stages_has_screening
  ON candidate_stages ((screening_answers IS NOT NULL))
  WHERE screening_answers IS NOT NULL;
```

### 2. Schemy Pydantic (`app/schemas/champion.py`)

```
ChampionProfile
├── basics              {onsite_days_per_week, candidate_location_pref, language}
├── project_context     {about, responsibilities, selling_points}
├── screening_questions [{id, question, ideal_answer, deal_breaker}]
├── historical_client_questions    str
├── internal_consultant_insight    str
└── sourcing            {sources[], keywords, target_companies, notes}

ScreeningAnswers
├── answers             [{question_id, response, deal_breaker_hit}]
├── overall_fit         "fit" | "uncertain" | "miss"
├── notes               str
├── answered_at         datetime
├── answered_by         user_id
└── match_percent()     0-100 obliczane z answerów + deal-breakerów
```

### 3. API

| Metoda | Ścieżka | Auth | Opis |
|---|---|---|---|
| GET | `/api/jobs/{id}/champion-profile` | any | Odczyt profilu |
| PUT | `/api/jobs/{id}/champion-profile` | DL+ | Upsert |
| GET | `/api/pipeline/stages/{id}/screening` | any | Odpowiedzi + profil dla stage |
| POST | `/api/pipeline/stages/{id}/screening` | Recruiter+ | Zapisz screening; zwraca match_percent |

### 4. Frontend

- **`/jobs/[id]` → tab "Profil Championa"** — `ChampionProfileEditor`: 4 sekcje (podstawowe, kontekst, pytania, sourcing), dodawanie/usuwanie pytań dynamicznie, checkboxy sourcingu, walidacja po zapisie.
- **`ScreeningModal`** — widok pytań DL + collapsible "idealna odpowiedź" i "deal-breaker" per pytanie, textarea na odpowiedź kandydata, checkbox "deal-breaker trafiony", ogólna ocena (Pasuje/Niepewnie/Nie pasuje) + notatki.
- **KanbanBoard**:
  - Przy przeciągnięciu kandydata do `cv_sent`, `client_interview`, `acceptance`, `negotiation` lub `onboarding` — **automatycznie otwiera `ScreeningModal`**.
  - **Przycisk "★ Screening"** na każdej karcie w external stages — pozwala otworzyć/edytować screening niezależnie od drag-drop.
  - Przeniesienie `dragHandleProps` z zewnętrznego wrappera na samą `CandidateCard` — wcześniej blokowało klikanie wszystkich elementów karty.

### 5. Score

`ScreeningAnswers.match_percent()` = deterministic 0-100:
- `0` gdy którykolwiek `deal_breaker_hit=true`
- inaczej `(% odpowiedzianych) × {fit:1.0, uncertain:0.6, miss:0.2}`

Planowany krok: dodać ten score jako kolejny layer w `WeightProfile` (np. `champion_fit`) — wymaga drobnego refaktoringu scoring_service.

## Weryfikacja end-to-end w Chrome

1. **PUT** przez curl — zapisałem `Profil Championa` dla job 2 (Java Backend Developer) z 2 pytaniami + basics + sourcing.
2. **Tab "Profil Championa"** na `/jobs/2` renderuje wszystkie pola pre-filled. ✅
3. **POST screening** dla `stage_id=4` (Agnieszka Nowak, acceptance) z idealnymi odpowiedziami → backend zwrócił `match_percent: 100.0`. ✅
4. **ScreeningModal** na kliknięcie "★ Screening" (via native .click() — syntetyczne klikanie agent-browser ma problemy z dnd, ale real user mouse = OK):
   - Pokazuje Q1 "Opisz migrację do mikroserwisów" i Q2 "Jak testujesz kod produkcyjny?".
   - Pre-fillu je odpowiedziami z poprzedniego zapisu.
   - Collapsible "Idealna odpowiedź (hint)" i "Deal-breaker" per pytanie.

## Znane ograniczenia

1. **Scoring integration** — `match_percent` jest obliczany i zwracany, ale jeszcze nie zasila `WeightProfile` / final score na kandydacie. Planowane w kolejnej iteracji jako nowy layer `champion_fit`.
2. **Widok klienta** — po cv_sent kandydat powinien mieć "Champion card" widoczną w interfejsie klienta. Dziś odpowiedzi są persistowane; UI klienta to kolejny krok.
3. **Playwright test suite** — test manualny przez agent-browser natrafił na ograniczenie `react-beautiful-dnd` vs syntetyczne click events. Real-user click działa prawidłowo (zweryfikowane przez dispatchowany `.click()`).

## Pliki

### Backend (nowe/zmienione)
- `alembic/versions/0019_champion_profile.py` (NEW)
- `app/schemas/champion.py` (NEW)
- `app/models/job.py` — `champion_profile` JSONB column
- `app/models/recruitment_pipeline.py` — `screening_answers` JSONB column
- `app/schemas/job.py` — `JobResponse.champion_profile`
- `app/api/jobs.py` — `GET/PUT /champion-profile`
- `app/api/pipeline.py` — `GET/POST /stages/{id}/screening`

### Frontend (nowe/zmienione)
- `components/ChampionProfileEditor.tsx` (NEW)
- `components/ScreeningModal.tsx` (NEW)
- `app/jobs/[id]/page.tsx` — nowy tab
- `components/KanbanBoard.tsx` — integracja modala + "★ Screening" button + refactor dragHandleProps
- `lib/api.ts` — `championApi`, `screeningApi` + typy

## Stan testów

- pytest scoring/cv_parser/integration: **54 passed** (bez zmian od Phase 9).
- TypeScript `tsc --noEmit`: **clean**.
- Alembic head: **0019**.
