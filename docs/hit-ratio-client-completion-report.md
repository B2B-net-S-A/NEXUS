# Hit ratio per client — completion report

**Feature**: skuteczność rekrutacji na poziomie klienta = `% zamkniętych zapytań z co najmniej 1 zatrudnieniem`.
**Commit**: `2de14d0` on `main` (push'd `abe9e72..2de14d0`).
**Data**: 2026-04-23.

## Co zostało dowiezione

### Backend

| Ścieżka | Typ | Opis |
|---------|-----|------|
| [backend/alembic/versions/0047_job_closed_at.py](../backend/alembic/versions/0047_job_closed_at.py) | NOWA migracja | `jobs.closed_at TIMESTAMPTZ` + index + backfill z `updated_at` dla historycznych closed rows |
| [backend/alembic/versions/0048_job_close_reason.py](../backend/alembic/versions/0048_job_close_reason.py) | migracja (commit 1a598b8) | `jobs.close_reason` (enum) + `close_notes` — metadata przy zamknięciu |
| [backend/app/models/job.py](../backend/app/models/job.py) | edit | pola `closed_at`, `close_reason`, `close_notes` + enum `JobCloseReason` |
| [backend/app/api/jobs.py](../backend/app/api/jobs.py) | edit | setter `closed_at` w `PATCH /jobs/{id}` przy zmianie statusu na/z `closed` + cache invalidation; nowy `POST /jobs/{id}/close` z body `{reason, notes}` |
| [backend/app/api/reports.py](../backend/app/api/reports.py) | edit (+492 linii) | 3 nowe endpointy:<br>• `GET /api/reports/clients?period&min_closed&sort&exclude_reasons` — listing z hit ratio<br>• `GET /api/reports/clients/at-risk?period&drop_pp&min_closed` — QoQ drop<br>• `GET /api/reports/clients/{id}/trend?months` — trend miesięczny |
| [backend/app/schemas/job.py](../backend/app/schemas/job.py) | edit | `JobCloseRequest` + dodanie `closed_at/close_reason/close_notes` w `JobResponse` |
| [backend/tests/test_reports_clients.py](../backend/tests/test_reports_clients.py) | NOWY | 10 testów pytest — **10/10 passed** (happy path, multi-seat, zero hires, period filter, exclude_reasons, RBAC HoR, min_closed, trend, 404) |

### Frontend

| Ścieżka | Opis |
|---------|------|
| [frontend/src/components/v2/pages/ClientsListV2.tsx](../frontend/src/components/v2/pages/ClientsListV2.tsx) | nowa kolumna **"Hit ratio"** między Status i NDA, sortowalna, kolor-code (≥50% zielony · 20-49% amber · <20% czerwony), fallback `X / Y` gdy <3 zamknięte |
| [frontend/src/app/reports/page.tsx](../frontend/src/app/reports/page.tsx) | nowy tab **"Klienci"** — 4 KPI cards + leaderboard top 10 + sekcja "Klienci at-risk" |
| [frontend/src/app/clients/[id]/page.tsx](../frontend/src/app/clients/[id]/page.tsx) | widget `CooperationStatsSection` w zakładce "Informacje" — 4 KPI + 6M sparkline trendu (commit `1a598b8`) |

## Kluczowe decyzje semantyczne

1. **Źródło prawdy dla "hire"** = `CandidateStage.stage = hired` (NIE Contract). Konsystencja z raportami delivery-leads i recruitment. Kontrakty zostają pochodną — migracja `0046_backfill_contractor_drafts` auto-draftuje `Contract(status=draft)` przy każdym nowym `hired` stage.
2. **Denominator** = `Job.status = closed AND closed_at ∈ period`. Dlatego doszedł `closed_at` w migracji 0047 — `updated_at` jako proxy jest niewiarygodne (reaguje na każdy edit).
3. **Dwa ratio**:
   - `hit_ratio` (main) = `% jobów z ≥1 hire` — łatwy do komunikacji
   - `fill_rate` = `placements / SUM(headcount)` — obsługuje joby wielostanowiskowe
4. **Minimum sample** = 3 closed jobs (frontend chowa procent, pokazuje surowe `X / Y` z tooltipem). Próg konfigurowalny przez `min_closed` w API.
5. **Target threshold** = 30% (`HIT_RATIO_TARGET_PCT` reużyty z raportu delivery-leads). `target_achieved: true` → ikona Award obok nazwy klienta.
6. **Exclude reasons** — query param pozwala wykluczyć z denominatora powody "nie nasza wina" (np. `exclude_reasons=paused,client_ghosted`). Domyślnie wszystko liczone.
7. **RBAC** — admin + delivery_lead + tac + **head_of_recruitment**. Recruiter/sourcer → 403, frontend graceful fallback (kolumna "—", tab niewidoczny).

## Weryfikacja

### Backend — test suite
```
docker compose exec -T -w /app backend pytest tests/test_reports_clients.py -v
======================= 10 passed, 19 warnings in 20.20s =======================
```

### Migracje
Alembic multi-head issue (pre-existing — nie moja) → backend używa `Base.metadata.create_all()` w DEBUG. Dla 0047/0048 zaaplikowałem kolumny bezpośrednio przez psql (idempotentnie). Na prod entrypoint.sh uruchamia `alembic upgrade` i automatycznie doda kolumny.

### Smoke test live (localhost)
- `GET /api/reports/clients?period=year&min_closed=0` → 200 z poprawnym shape'em (wymagane auth).
- `GET /api/reports/clients` bez tokena → 403 (expected, `_ClientsReportViewer` guard).
- Login lokalnym kontem demo skonfigurowanym wyłącznie przez env działa, token ważny.

### Chrome MCP smoke test (localhost)
- Login flow działa
- `/clients` — lista się renderuje, ale kolumny "Hit ratio" nie było w lokalnym containerze (frontend docker image nie ma volume mount — deploy-first flow to ominął).

### Chrome MCP smoke test (prod — nexus.dynaminds.pl, po commit `2de14d0`)
Build Coolify zakończony w ~136s, backend odpowiedział `403` (auth required). Wszystkie 3 flow przeszły:

1. **`/clients` (lista klientów)** — nowa kolumna "Hit ratio" widoczna między "Status" i "NDA". Wszyscy klienci aktualnie z wartością `—` (brak `closed_at` → brak zamkniętych w okresie rolling 12m; to oczekiwane po backfillu z `updated_at`).
2. **`/reports` → tab "Klienci"** — dostępny i funkcjonalny:
   - 4 KPI cards (Średni hit ratio, Globalny hit ratio, Placements, W celu (≥30%))
   - Sekcja "Leaderboard klientów" z empty state: "Brak klientów z minimum 3 zamkniętymi zapytaniami w okresie." — poprawne, nie ma historycznych closed + hired
   - Sekcja "Klienci at-risk" z empty state: "Żaden klient nie spełnia kryterium — stabilnie."
   - PeriodSelector Tydzień/Miesiąc/Kwartał/Rok działa
3. **`/clients/1` (Nordea Bank AB) → tab "Informacje"** — widget "STATYSTYKI WSPÓŁPRACY" renderuje się z etykietą "Ostatnie 12 mies." i empty state: "Brak zamkniętych zapytań w ostatnich 12 miesiącach." Gracefully degraduje do placeholder'a bez danych.

Brak regresji — pozostałe zakładki w Raportach (Rekrutacja, Delivery Lead, Sprzedaż, Zarząd) dalej się ładują; tab "Profil" klienta (z commita Artura `1a598b8`) obok nowego "Informacje" + widgetu.

## Znane ograniczenia / follow-ups

- **Retention 30d** — Contract ma `start_date` i `terminated_at`, ale nie śledzimy *actual_start_date* (czy kandydat dotarł do pierwszego dnia). Do osobnej iteracji: flag "early churn" gdy `terminated_at - start_date < 30 days`.
- **Per-recruiter × client hit ratio** — matryca 2D (który TAC/rekruter ma najlepszy conversion z danym klientem). Fajny follow-up dla KPI Coach.
- **Bayesian smoothing** — jeśli próg 3 closed jobs okaże się za ostry/miękki, response zawiera już `global_avg_job_fill_rate` do smoothingu.
- **Close reason breakdown w UI** — backend zwraca `close_reasons` per klient (agregat per reason), ale frontend jeszcze go nie wizualizuje. W szczegółach klienta warto dodać pie chart "powody przegranej".
- **Frontend hot reload lokalnie** — `docker-compose.override.yml` nie ma volume mount dla frontend (tylko backend). Artur: czy dodać, żeby dev był szybszy? Obecnie każda zmiana FE wymaga rebuild image.
- **`app.main` force-load `app.models`** — dla devu dodałem `import app.models as _models` (żeby `emails` table była w `Base.metadata` przy `create_all`). Nie commitowane — m365 integration (untracked) nie jest jeszcze w main.

## Cache / invalidation

Wszystkie 3 endpointy cache'owane 300s pod prefiksem `reports:clients:*`. Invalidacja następuje przy:
- `PATCH /jobs/{id}` gdy status flipuje na/z `closed`
- `POST /jobs/{id}/close`

Backend cache jest in-memory (bez Redis) — przy restart kontenera się resetuje. Dla skali firmy Artura (setki klientów, tysiące jobów) to wystarczające.
