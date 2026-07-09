# AI scoring justification tab ("Dopasowanie") — completion report

**Date:** 2026-07-09
**Branch:** `claude/ai-scoring-justification-tab-6d89a4`

## Problem

Na profilu kandydata (`/candidates/{id}?from=job&jobId=N`) brakowało uzasadnienia
punktacji AI — analogicznego do panelu „Dopasowanie" znanego z Traffita (score
ring + „Podsumowanie" + „Może być dobrym wyborem, ponieważ" + „Oceń ten
scoring"). Nexus liczył już hybrydowy wynik (0-100), ale nie generował prozy
tłumaczącej *dlaczego*.

## Rozwiązanie

Nowa zakładka **„Dopasowanie"** (obok „Rekrutacje") na profilu kandydata.
Dla wybranej pary (kandydat ↔ oferta) pokazuje:

- **Score ring** — ten sam hybrydowy wynik 0-100 co pierścień na kanbanie
  (deterministyczny silnik `scoring_service`, cache `match_score_cache`).
- **Podsumowanie** — proza LLM (Claude) tłumacząca wynik.
- **Może być dobrym wyborem, ponieważ** — punkty pozytywne poparte konkretami z CV.
- **Do weryfikacji / luki** — braki i rzeczy do potwierdzenia na screeningu.
- **Oceń ten scoring** — feedback kciuk w górę/dół.

Kluczowa zasada: **LLM tylko tłumaczy wynik, nie zmienia go**. Liczba zawsze
pochodzi z deterministycznego silnika → pierścień jest spójny z resztą aplikacji,
a model nie może „zawyżyć" dopasowania.

### Cache + koszt

- Jeden wiersz na parę (kandydat, oferta) w `candidate_match_justifications`.
- `input_hash` (SHA-256 z CV + wymagań + Championa + wyniku) → proza
  regeneruje się automatycznie tylko gdy wejścia faktycznie się zmienią.
- Płatne wywołanie Claude tylko przy cache-miss / `refresh=true`, bramkowane
  przez zarezerwowaną capability `AIFeatureKey.scoring` (Ustawienia → AI,
  „Scoring kandydatów") + licznik zużycia (`ai_usage_log`). Nieudana generacja
  nie konsumuje limitu (rollback przed commitem usage).

## Pliki

### Backend
- `app/models/match_justification.py` — model `CandidateMatchJustification` (nowa tabela).
- `app/models/__init__.py` — rejestracja modelu (żeby `create_all` safety-net utworzył tabelę na prod).
- `app/services/llm_prompts.py` — prompt `MATCH_JUSTIFICATION` (PL, anty-fabrykacja).
- `app/services/match_justification_service.py` — score + cache + gate + LLM + sanityzacja + upsert.
- `app/api/candidate_scoring.py` — `GET /{cid}/scoring/{jid}` + `POST .../feedback`.
- `app/main.py` — rejestracja routera (`/api/candidates`).
- `alembic/versions/0156_candidate_match_justifications.py` — migracja (down_revision `0155`) + seed wiersza `scoring` w `ai_features`.

### Frontend
- `frontend/src/lib/api.ts` — `matchScoringApi` (`get`, `feedback`) + typ `MatchJustification`.
- `frontend/src/components/v2/pages/DopasowanieTab.tsx` — nowy komponent zakładki.
- `frontend/src/components/v2/pages/CandidateDetailV2.tsx` — nowa zakładka „Dopasowanie" + rozszerzony warunek ładowania `history`.

### Testy / CI
- `backend/tests/test_match_justification.py` — 18 testów jednostkowych (hash, sanityzacja, buildery kontekstu, `generate_prose` z zamockowanym LLM).
- `.github/workflows/ci.yml` — dopięcie testu do listy pytest.

## Endpointy

| Metoda | Ścieżka | Opis |
|---|---|---|
| GET | `/api/candidates/{candidate_id}/scoring/{job_id}?refresh=` | Uzasadnienie (cache lub generacja) |
| POST | `/api/candidates/{candidate_id}/scoring/{job_id}/feedback` | Ocena `{rating: -1\|0\|1, comment?}` |

Kody: `404` (brak kandydata/oferty), `503` (AI wyłączone / limit), `502` (błąd generacji).

## Weryfikacja

- ✅ `tsc --noEmit` (frontend) — zielone.
- ✅ ESLint — 0 błędów na nowych plikach (warningi `any` tylko pre-existing w `CandidateDetailV2`).
- ✅ `ruff check` + `py_compile` na wszystkich nowych plikach backendu — zielone.
- ✅ Migracja `0156` extenduje czysto head `0155` (brak kolizji z origin/main).
- ⏳ Backend pytest (`test_match_justification.py`) — walidowane w CI (Python 3.12; lokalny worktree ma Py 3.9 + brak venv).
- ⏳ UI przez Chrome MCP — do wykonania po deployu (`AIFeatureKey.scoring` musi być włączone w Ustawieniach → AI, plus `ANTHROPIC_API_KEY` w Coolify).

## Znane ograniczenia / uwagi

- Aktywacja na prod wymaga: `ANTHROPIC_API_KEY` (jest — używany przez champion/cv), oraz włączonej capability „Scoring kandydatów" w Ustawieniach → AI (seed migracji ją tworzy, domyślnie enabled, limit 0 = bez limitu). Serwis toleruje też brak wiersza (traktuje jako enabled).
- Model: `MATCH_SCORING_MODEL` (domyślnie `claude-sonnet-5`, thinking wyłączony — patrz reguła [[claude5-thinking-block-parse]]).
- Zakładka domyślnie wybiera ofertę z `?from=job&jobId=`; w innym wypadku pierwszą z listy rekrutacji.
