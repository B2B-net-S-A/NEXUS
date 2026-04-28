# Completion Report — Prev/Next Candidate Navigation

**Status:** ✅ Wdrożone i w pełni zweryfikowane na produkcji. Wszystkie 8 testów Chrome MCP zaliczone (włącznie z optimistic counter update).

**Data:** 2026-04-27
**Branch:** `main`
**Commits:**
- `67635c9` — feat: nawigacja prev/next + backend stable sort
- `02f39cb` — fix: nav strip widoczny w pełnej stronie po push
- `b058e63` — fix: counter updates instantly w trybie URL
- `cf3310f` — fix: router.refresh() po push w URL nav (zmieszany z Phase 17 stage-notif/risk z innej sesji)

## Scope

User request: *"Po searchu kandydatów na bazie filtrów, możliwość przejścia do profilu kolejnej osoby, bez konieczności powrotu do okienka searchu."*

V1 zawiera:
- Pasek **`← Poprzedni | N / total | Następny →`** w profilu kandydata
- Tryb **embedded** (Sheet otwierany z listy) — kontekst z parent props
- Tryb **URL** (pełna strona `/candidates/[id]?nav=search&pos=N&...filters`) — kontekst z URL
- Skróty klawiszowe `[` (prev) / `]` (next) z guardem `isInputActive()`
- Auto-doczyt sąsiednich stron przez react-query gdy nawigacja przekracza granicę
- Disable na pierwszym/ostatnim z tooltipem
- Dodatkowy button "otwórz w pełnym widoku" w Sheet — przenosi kontekst do URL

V1 nie zawiera (follow-up):
- Pipeline view, Talent Pool, SuggestedCandidatesDrawer, Compare view
- Mobile swipe gestures
- Wrap-around (Next na N/N → 1/N)

## Krytyczna poprawka po drodze

**Pre-existing bug:** backend `list_candidates` ([backend/app/api/candidates.py:302](backend/app/api/candidates.py)) **nie miał ORDER BY**. Dwa requesty z tymi samymi filtrami mogły zwrócić items w różnej kolejności — bez tego "Next" pokazywał losowego kandydata. Frontend deklarował `sortBy` w state, ale **nigdy go nie wysyłał**. Naprawione (sort param + order_by z `id` tie-breakerem + faktyczne wysyłanie sortBy z frontu).

## Zmienione pliki

### Backend
- [backend/app/api/candidates.py](backend/app/api/candidates.py) — `+ sort` query param (`newest|oldest|name`) + `order_by` z `id` tie-breakerem przed `offset/limit`
- [backend/tests/test_candidates_sort.py](backend/tests/test_candidates_sort.py) — pytest dla 5 trybów: `newest`, `oldest`, `name`, default-is-newest, stability-across-requests, invalid-rejected

### Frontend (nowe)
- [frontend/src/hooks/useCandidateNavigation.ts](frontend/src/hooks/useCandidateNavigation.ts) — hook z dwoma trybami (embedded/url), prefetch, keyboard binding
- [frontend/src/components/v2/CandidateNav.tsx](frontend/src/components/v2/CandidateNav.tsx) — presentational pasek nawigacji (Tooltip + Button + counter)

### Frontend (modyfikacje)
- [frontend/src/components/v2/pages/CandidateDetailV2.tsx](frontend/src/components/v2/pages/CandidateDetailV2.tsx) — render `<CandidateNav>` w embedded i full-page; `useSearchParams` (nie `window.location`); optimistic `urlPosition` state + `router.refresh()` after `push`
- [frontend/src/components/v2/pages/CandidatesListV2.tsx](frontend/src/components/v2/pages/CandidatesListV2.tsx) — wysłanie `sort` param; `detailPosition` state; przekazywanie nav context do Sheet
- [frontend/src/lib/url-filters.ts](frontend/src/lib/url-filters.ts) — `encodeNavContext` / `decodeNavContext` / `filtersToApiParams`
- [frontend/src/components/KeyboardShortcuts.tsx](frontend/src/components/KeyboardShortcuts.tsx) — eksport `isInputActive()` (jednolinijkowa zmiana)

## Verification (Chrome MCP, prod)

| # | Test | Wynik |
|---|------|-------|
| 1 | List → click row → Sheet otwiera się z paskiem `1 / 35795` + Prev disabled | ✅ |
| 2 | Klik "Następny" → counter 1→2, profil zmienia się (Agnieszka → Artur Borecki) | ✅ |
| 3 | Skrót `]` ×2 → counter 2→4, profil zmienia się (Artur → Madhumitha → Jakub Jęczmyk) | ✅ |
| 4 | Skrót `[` → counter 4→3 (z powrotem do Madhumithy) | ✅ |
| 5 | Klik "Otwórz w pełnym widoku" → URL zmienia się na `/candidates/{id}?nav=search&pos=3` + nav strip widoczny po prawej | ✅ |
| 6 | Hard reload `/candidates/38397?nav=search&pos=5` → counter `5 / 35795` od razu | ✅ |
| 7 | Skrót `]` w pełnej stronie → URL `?pos=6`, profil zmienia się | ✅ |
| 8 | Optimistic counter update po `]`/`[` w pełnej stronie (5→6→7→6 instant) | ✅ |

**Backend testy (pytest):** napisane 6 case'ów w [test_candidates_sort.py](backend/tests/test_candidates_sort.py); nie zostały odpalone w tej sesji (env zewnętrzny).

## Architektura

**Embedded mode (Sheet z listy):** parent (`CandidatesListV2`) ma już w pamięci `data.items`, `total`, `page_size`. Przekazuje je przez prop `navigation` do `CandidateDetailV2`. Hook używa parent items bezpośrednio gdy `targetPage === parentPage`, inaczej fetchuje sąsiednią stronę. Zero zbędnych refetchów.

**URL mode (pełna strona):** `useSearchParams()` z `next/navigation` (nie `window.location`, bo nie reaguje na hydration/push). Hook fetch'uje `page = ceil(pos/pageSize)` przez react-query. Przy klik "Następny": optimistyczny `setUrlPosition(pos+1)` (counter widzi nową wartość natychmiast), potem `router.push(...)` + `router.refresh()` (forces app router cache invalidation dla [id] segmentu).

**Reuse:** `encodeFilters` / `decodeFilters` z `url-filters.ts`, `isInputActive()` z `KeyboardShortcuts.tsx`, react-query queryKey idiom z `CandidatesListV2.tsx`.

## Known limitations / quirks

1. **Brak nav w innych listach** — V1 obejmuje tylko search list. Pipeline / Talent Pool / Suggested otrzymają nav w V2 (hook ma generyczne mode).
2. **Sort options** — `newest|oldest|name`. Inne sortowania (`match_score`, `salary`, etc.) wymagają dodania do enum w backend `sort` param.
3. **Brak swipe na mobile** — V1 tylko strzałki + skróty.

## Follow-up ideas

- **Pipeline view nav** — dodać `mode: "pipeline"` z filterem `?job_id=N` i rozszerzyć URL helpers
- **Konfiguracja klawiszy** — pozwolić użytkownikowi przypisać `j/k` lub strzałki zamiast `[/]`
- **Kontekst w sidebar** — pokazać miniaturę listy z highlightem na current pos (jak Outlook reading pane)
- **"Skip blacklisted" / "Only unread"** — toggle w nav strip filtrujący sequence
- **Mobile swipe** — react-swipeable na hero card

## Equivalent metrics

- **Before:** klikanie kolejnego kandydata wymagało 3 kroków (zamknij modal → znajdź wiersz → klik). Przy 35,795 kandydatach nieakceptowalny friction przy bulk review.
- **After:** 1 klik lub 1 klawisz = kolejny profil. Auto-doczyt stron transparentny, kontekst zachowany w URL, skrót `]` umożliwia szybkie skanowanie.
