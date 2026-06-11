# Saved-search alerts — raport ukończenia (V1)

> Data: 2026-06-11 · PR [#481](https://github.com/artur-t-96/Nexus/pull/481) (merged `69f53db`) + follow-up first-open anchor
> Zakres: powiadomienia o nowych kandydatach pasujących do zapisanych wyszukiwań + wyróżnianie „Nowy" na liście.

## Co zostało zbudowane

Zapisane wyszukiwania kandydatów (istniejące od Phase 4: menu **Zapisane** na `/candidates`, do 50/user, share, pin do joba) dostały subskrypcję alertów:

1. **Dzwonek per saved search** (`SavedSearchesMenu`) — toggle `notify_new_matches`. Przy zapisie/włączeniu FE dokłada do `filters` obok `qs` także `api` (wynik `filtersToApiParams`) — z tych parametrów skaner odtwarza search.
2. **Skaner w tle** `app/tasks/saved_search_alerts.py` (19. background task w lifespan, default co 30 min, env `SAVED_SEARCH_ALERTS_INTERVAL_SECONDS`, clamp ≥300 s):
   - odtwarza search przez **realny** `GET /api/candidates` in-process (httpx `ASGITransport` + JWT mintowany dla właściciela) → wyniki 1:1 z UI, zero duplikacji logiki 38 filtrów,
   - watermark po PK: parametr `id_after` (nowy na liście kandydatów) tnie zbiór przed wszystkimi innymi filtrami,
   - jedna zbiorcza notyfikacja `saved_search_match` per search, dedup dzienny (`ix_notif_dedup_daily` + `dedupe_resurface` — licznik w treści jest skumulowany od ostatniego otwarcia), push przez WS,
   - commit per search (jedna awaria nie cofa pozostałych), błędy izolowane per search.
3. **Badge'e nieobejrzanych** — `unseen_count` przy nazwie searcha w menu + zbiorczo na przycisku Zapisane; reset przez `POST /api/saved-searches/{id}/viewed` (zwraca POPRZEDNI `last_viewed_at`).
4. **Wyróżnienie „Nowy"** — wiersze z `created_at` > poprzedniego `last_viewed_at` dostają zielony badge przy nazwisku + tint wiersza; działa z menu i z linku powiadomienia (`/candidates?<qs>&ss=ID`; mount-init czyta `ss` z URL).
5. **First-open anchor** (follow-up): włączenie dzwonka ustawia też `last_viewed_at = now`, żeby już pierwsze kliknięcie w powiadomienie wyróżniało nowych (bez tego previous=NULL → brak wyróżnienia; złapane podczas E2E).

## Pliki

- **Migracja:** `backend/alembic/versions/0129_saved_search_alerts.py` — 4 kolumny na `saved_searches` (`notify_new_matches`, `last_seen_candidate_id`, `unseen_count`, `last_viewed_at`) + enum `saved_search_match` (autocommit block, wzorzec 0100).
- **Safety-net:** `backend/entrypoint.sh` — enum + kolumny (lekcja z incydentu kpi_coach).
- **Backend:** `app/tasks/saved_search_alerts.py` (nowy), `app/api/phase4.py` (schematy, watermark+anchor przy enable, endpoint `/viewed`), `app/api/candidates.py` (`id_after`), `app/models/saved_search.py`, `app/models/notification.py`, `app/main.py` (rejestracja taska).
- **Frontend:** `lib/api.ts` (typy + `markViewed`), `components/v2/filters/SavedSearchesMenu.tsx` (dzwonek, badge, payload `filters.api`), `components/v2/pages/CandidatesListV2.tsx` (stan `ss` z URL + sync, mount-init, badge „Nowy", tint wiersza).
- **Testy:** `backend/tests/test_saved_search_alerts.py` (13 testów: sanityzacja parametrów replay, polska liczba mnoga, deep-link) — dodane do listy pytest w CI.

## Weryfikacja na produkcji (E2E przez Chrome, 2026-06-11)

- ✅ zapis searcha `q=SavedSearchTest` + włączenie dzwonka → `notify_new_matches=t`, watermark=MAX(id), `filters.api` zapisane
- ✅ dodanie kandydata → **automatyczna pętla** złapała go sama (9 s od utworzenia, log `notified 1 searches`), notyfikacja w dzwonku z poprawną polską odmianą i linkiem
- ✅ link z powiadomienia otwiera listę z filtrami + `ss=ID`
- ✅ badge „Nowy" + zielony tint wiersza dla kandydata nowszego niż poprzednie otwarcie; starsi bez wyróżnienia
- ✅ licznik nieobejrzanych w menu i na przycisku; reset po otwarciu
- ✅ dane testowe posprzątane (4 kandydatów + search przez API aplikacji, notyfikacje przez SQL)

## Decyzje architektoniczne

- **Self-call zamiast refactoru filtrów**: 340 linii inline'owej logiki filtrów w `list_candidates` zostało nietknięte — skaner woła endpoint in-process. Zero ryzyka regresji na najgorętszym endpoincie i zero driftu semantyki. Ewentualny refactor do współdzielonego serwisu — osobna decyzja.
- **„Nowy" = nowy w bazie** (created_at/PK), nie „istniejący zaczął pasować" — świadome ograniczenie V1.
- **Alerty tylko dla właściciela**; shared searches bez alertów.

## Znane ograniczenia / V2 (jeśli się przyjmie)

- Brak digestu mailowego (in-app + WS only) — kandydat na V2 (dzienny mail 8:00).
- Alerty tylko dla `entity='candidates'` (searche jobów — V2).
- Przy >100 nowych w jednym przebiegu watermark przesuwa się do max id strony — nadwyżka wpada w kolejny przebieg (świadome).
- Edycja filtrów zapisanego searcha (PATCH `filters`) przy włączonym alercie odświeża `api` tylko gdy robi to FE — stary klient mógłby zostawić nieaktualne `api` (skaner used last known good).
