# „Oferty" → „Rekrutacje" — raport z wdrożenia

**Data:** 2026-08-10
**Zakres:** ujednolicenie nazwy modułu `/jobs` w całym interfejsie i w komunikatach API.

## Dlaczego

Nazwa była **niespójna wewnątrz samego modułu**. Sidebar, breadcrumby i nagłówek
listy mówiły „Oferty" / „Oferty pracy", podczas gdy rail otwartych kart
(`JobTabsRail.tsx`), zakładka na profilu kandydata (`CandidateDetailV2.tsx`) i
kolumna listy kandydatów już mówiły „Rekrutacje". Zmiana domyka migrację, która
zaczęła się wcześniej, zamiast wprowadzać nową nazwę.

## Co się zmieniło

**80 plików, 168 zmienionych literałów** (diff 1:1 — zero zmian logiki poza
reformatowaniem jednej linii przez `ruff format`).

| Warstwa | Zakres |
|---|---|
| Nawigacja i nagłówki | sidebar, command palette, dwie mapy breadcrumbów (`BreadcrumbV2` + `AppShell`), H1 i eyebrow listy, quick actions, skróty klawiszowe, global search |
| Język modułu | ~28 plików: modale (QuickAssign, CloseJobAsLost, ReassignOwner, CriteriaPreview, ScreeningSheet), onboardingi DL/Recruiter, Kanban, Dopasowanie, generator CV, marketplace, sourcing, analytics |
| Backend user-facing | 15 komunikatów: `detail=` w HTTPException (matching, prep_kit, interview_questions ×4, phase3_actions ×3, pipeline ×2, candidate_scoring, candidates), notyfikacje marketplace, opisy OpenAPI w contracts, katalog metryk |
| Testy | `AppShellJobOwner.test.tsx`, `e2e/auth.spec.ts`, `test_champion_historical_jobs.py` + nazwy przypadków w 3 plikach |

Odmiana: **Rekrutacja / Rekrutacje** („Nowa rekrutacja", „Przypisz do rekrutacji",
„Brak rekrutacji", kolumna „Rekrutacja").

## Czego świadomie NIE zmieniono

**1. Warstwa techniczna zostaje po angielsku.** Route `/jobs`, `/api/jobs`, tabela
`jobs`, kolumny `job_id`, nazwy plików. Powód: powiadomienia mają `link="/jobs/{id}"`
**zapisane w produkcyjnej bazie** (`job_deadline_alerts.py:177`, `job_chat.py:254`,
`activities.py:218`) — zmiana routingu zepsułaby historyczne wpisy albo wymusiłaby
wieczny redirect. Dodatkowo cały routing NEXUSa jest angielski (`/candidates` przy
„Kandydaci"), więc `/jobs` nie jest wyjątkiem.

**2. „Oferta" tam, gdzie znaczy co innego** — ślepe zamienianie zepsułoby te miejsca:

| Znaczenie | Przykłady |
|---|---|
| Etap pipeline'u — propozycja dla kandydata | `offer_sent`, `offer_accepted`, „Oferta wysłana/zaakceptowana", „Wycofał się PO akceptacji oferty", funnel „Oferta" |
| Status kandydata | `open_to_offers` → „Otwarty na oferty" |
| Szablon maila | „Oferta współpracy" |
| Oferty handlowe | dynareporter: „Leady, oferty, wygrane / przegrane" |
| Mail wychodzący do kandydata | „Oferta pracy: {tytuł}" — odbiorcą jest kandydat, nie rekruter |

**3. Prompty LLM** (`services/llm_prompts.py`) — „Kontekst oferty:" zostaje.
Zmiana treści promptu zmienia zachowanie modelu i unieważnia cache oparty o hash
promptu, bez zysku dla użytkownika.

**4. Komentarze i docstringi w kodzie** (~35 wystąpień) — nie są widoczne dla
użytkownika; zmiana rozdęłaby diff bez efektu funkcjonalnego.

**5. Historyczne raporty w `docs/`** (`matching-eval-2026-08-10-baseline.md`,
`faza0-pomiary-produkcji-2026-07-27.md`, `qa-session-2026-05-27.md`) — to zapisy
pomiarów z konkretnych dat; przepisanie ich zafałszowałoby, co widziano wtedy.
Zaktualizowano tylko żywy `qa-process-runbook.md`.

## Zmiany warte odnotowania

- **`MyPriorityQueue`: `job_cancelled` „Oferta pracy anulowana" → „Rekrutacja
  anulowana".** Wcześniej sąsiadowało z `offer_declined` („Oferta odrzucona") i
  `offer_expired` („Oferta wygasła") — dwa różne pojęcia wyglądały identycznie.
- **Generator CV: tryb „Pod ofertę" → „Pod rekrutację"** (`lib/cv-generator.ts`).
  Wartość `content_mode="tailored"` w backendzie bez zmian — to tylko etykieta.
- **`candidates.py` / `recruitment_process_commands.py`:** komunikat „Brak
  rekrutacji dla tego kandydata i tej oferty." zastąpiony przez „Ten kandydat nie
  bierze udziału w tej rekrutacji." — dosłowna zamiana dawała tautologię
  („…i tej rekrutacji").

## Weryfikacja

| Bramka | Wynik |
|---|---|
| `tsc --noEmit` | czysto |
| `next lint --max-warnings=300` | 2 warningi (pre-existing, nie z tej zmiany) |
| `vitest run` | **1115/1115 passed** (119 plików) |
| `next build` | przeszedł |
| `ruff check app/` | All checks passed |
| `ruff format --check app/` | 625 plików sformatowanych |
| `pytest` (Docker + Postgres) | **zero regresji** — patrz niżej |

Lokalny Python to 3.9, a repo wymaga 3.12+ (`X | Y` w adnotacjach runtime) —
testy backendu uruchomiono w kontenerze `nexus-verify:img` podpiętym do
działającego `nx-pg`.

### Jak ustalono „zero regresji"

Lokalny pełny suite ma **dużo failów niezależnych od tej zmiany** (świeża baza
bez pełnego setupu). Sama liczba nic nie mówi, więc porównano **listy nazw**
failujących testów: pełny przebieg na kodzie **przed** zmianą (worktree na
`646ef760`) vs **po** zmianie, każdy na własnej, świeżo utworzonej bazie.

```
baseline: 457 failed, 3275 passed, 1515 errors
changed:  458 failed, 3274 passed, 1515 errors
```

`comm` na posortowanych listach `FAILED` dał **dokładnie jedną** różnicę:
`test_schema_inventory.py::test_schema_a_builds_to_single_expected_head`.
To **nie jest regresja** — ten test tworzy bazy o **stałych** nazwach
`schema_inv_a` / `schema_inv_b` (niezależnych od `DATABASE_URL`), więc dwa
przebiegi puszczone równolegle kolidują na `CREATE TABLE alembic_version`.
Uruchomiony w izolacji: **18/18 passed**.

> Pułapka na przyszłość: `docker run ... pytest | tail -30` zwraca exit code
> **`tail`, nie pytesta** — przebieg z 96 failami zgłosił się jako „exit 0".
> Czytaj linię podsumowania, nie kod wyjścia potoku.

**Weryfikacja wizualna:** publiczne harnessy `/preview/*` nie renderują
nawigacji, a `/preview/shell` wymaga ważnego JWT — sidebar sprawdzony na prodzie
po wdrożeniu.

## Ochrona przed cofnięciem

Do `CLAUDE.md` dodano sekcję **„Nazewnictwo: «Rekrutacja», nie «Oferta»"** z
rozróżnieniem obu znaczeń i uzasadnieniem, dlaczego `/jobs` zostaje po angielsku
— żeby kolejna sesja nie wprowadziła nazwy z powrotem ani nie „poprawiła" URL-i.
