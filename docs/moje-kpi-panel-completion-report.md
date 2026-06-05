# „Moje KPI" — panel statystyk per użytkownik (completion report)

**Data:** 2026-06-05
**Zakres:** Per-user panel KPI na panelu głównym dla sourcerów / TAC / rekruterów (+ DL).

## Cel (wymaganie Artura)

KPI zespołu:

| Rola | KPI |
|---|---|
| sourcer / TAC / recruiter | 4 weryfikacje/dzień · 75% precision (zweryfikowani → wysłani do klienta) · 1 placement/miesiąc |
| recruiter / TAC (licencja LinkedIn) | + 5 CV dodanych do bazy/dzień |
| delivery_lead | 30% hit ratio (≥30% otwartych rekrutacji kończy się placementem) |

Każdy user na panelu głównym widzi **swoje** staty: weryfikacje + rekomendacje za dzień / tydzień / miesiąc, plus placementy + zaproszenia na interview + akceptacje za bieżący miesiąc.

**Kluczowa reguła atrybucji (decyzja Artura):** zasługę za wszystkie kamienie milowe pary (kandydat × rekrutacja) dostaje osoba, która przeniosła kandydata na etap **„Zweryfikowany"** (`verified`) — niezależnie kto klika późniejsze etapy.

## Co już istniało (reused)

- **Tabele targetów** `kpi_role_defaults` + `user_kpi_targets` (precedencja: user override → role default → kod) — reused 1:1.
- **Helpery czasu Warsaw** `period_bounds` / `WARSAW` z `kpi_engine.py` — reused.
- **DL hit ratio 30%** — `/api/reports/my-delivery-lead` + widget `DlKpiRow` już to liczyły. Bez zmian.

## Co było nie tak

- Stary silnik KPI (`/api/kpis/me/today`) liczył z tabeli `user_activities`, która jest **martwa** (np. `stage_changed` = 42 rekordy / 120 dni) → pokazywał ~0 każdemu.
- Katalog 5 KPI nie odpowiadał liczbom Artura.
- `/api/reports/recruitment` miał błędne mapowanie etapów: `rekomendacje = interview` (zamiast `cv_sent`), `interviews = client_interview` (etap martwy, 1 ruch/90 dni → kolumna zawsze ~0).

## Co zbudowano

### Backend
- **`app/services/kpi_panel.py`** (nowy) — verifier-anchored funnel liczony z żywej `candidate_stages`:
  - Dla każdej pary (kandydat, job): `mf` = pierwszy ruch na każdy etap → `anchor` = weryfikator (mover `verified`) → `credited` = `COALESCE(weryfikator, mover danego kamienia)`.
  - Fallback (mover kamienia) gdy para nigdy nie przeszła przez `verified` — istotne: ~10% `cv_sent` i ~29% `hired` omija `verified`.
  - Precision = `cv_sent ÷ verified` w oknie kroczącym 30 dni; ukryte (`—`) gdy < 5 weryfikacji (za mała próbka).
  - CV do bazy = `candidates.created_by = user` (import masowy z NULL `created_by` się nie liczy).
- **`app/api/kpis.py`** — nowy endpoint `GET /api/kpis/me/panel` (+ schematy Pydantic).
- **`alembic/versions/0124_seed_kpi_panel_targets.py`** — seed targetów do `kpi_role_defaults` (idempotentny, `ON CONFLICT DO NOTHING`). Code-level defaults w `PANEL_KPI_DEFAULTS` działają nawet przed migracją.
- **`app/api/reports.py`** — naprawione mapowanie etapów funnel: `weryfikacje=verified`, `rekomendacje=cv_sent`, `interviews=interview`, `placements=hired` (spójne z panelem; ranking placementów / system konkursów bez zmian).

### Frontend
- **`components/v2/kpi/MojeKpiPanel.tsx`** (nowy) — widget z togglem Dziś / Tydzień / Miesiąc, gauge precision (cel 75%), kafle placement/interview/akceptacja (mc), CV do bazy (recruiter/TAC). Chowa się gdy `applies=false`.
- Zamontowany na `dashboard/recruiter` (góra) + `DashboardV2`.

## Walidacja na prod (przed wdrożeniem)

- Verifier-anchored funnel → realistyczne liczby per osoba; precision top performerów 78–96% (≈ cel 75%); placementy 0–6/mc (≈ cel 1/mc).
- Luka fallbacku: 658/6370 `cv_sent` (10%) i 86/300 `hired` (29%) bez kotwicy `verified` → fallback konieczny i zaimplementowany.
- CV do bazy: rekruterzy 6–9/workday (powyżej celu 5), import masowy wykluczony (NULL `created_by`).

## Znane ograniczenia / follow-up

1. **Team leaderboard (`/api/reports/recruitment`)** ma już poprawne definicje etapów, ale wciąż atrybucję per-mover (nie verifier-anchored). Osobisty „Moje KPI" jest autorytatywny; pełne ujednolicenie team-view = follow-up.
2. **Akceptacje** — etap `acceptance` jest dziś prawie nieużywany (7 ruchów/90 dni). Licznik gotowy, zacznie rosnąć gdy zespół zacznie konsekwentnie używać etapu.
3. **Stary KPI Coach / nudge'y** (`/api/kpis/me/today`, scheduler) wciąż czytają martwy `user_activities` — nietknięte (osobny system). Repointing = osobny follow-up.

## Pliki

- `backend/app/services/kpi_panel.py` (nowy)
- `backend/app/api/kpis.py` (endpoint + schematy)
- `backend/app/api/reports.py` (fix mapowania)
- `backend/alembic/versions/0124_seed_kpi_panel_targets.py` (nowy)
- `frontend/src/components/v2/kpi/MojeKpiPanel.tsx` (nowy)
- `frontend/src/app/dashboard/recruiter/page.tsx` (mount)
- `frontend/src/components/v2/pages/DashboardV2.tsx` (mount)
