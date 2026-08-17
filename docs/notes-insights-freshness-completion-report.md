# Świeżość faktów z notatek — pętla `notes_insights_sync` + repo-izacja ad-hoców

Data: 2026-08-17 · Kontynuacja importu champion+notes z 13–14.08 (pamięć projektu:
`champion-notes-import-complete-2026-08-14`).

## Problem

Import 08.2026 przemielił pełny korpus notatek jednorazowo (~14k kandydatów,
8,9k stawek do `expected_rate_hourly`, 7,3k z potwierdzonymi umiejętnościami).
Notatki przybywają codziennie (nocny Traffit sync + wpisy w aplikacji), a
ekstrakcje starzały się bezterminowo — nowa stawka z rozmowy nie trafiała do
warstwy finansowej scoringu, nowa dostępność nie zasilała fallbacku. Do tego
wszystkie skrypty importu żyły WYŁĄCZNIE w `/root/` na serwerze prod.

## Co weszło

| Plik | Rola |
|---|---|
| `app/services/notes_insights_extractor.py` | Jeden prompt (unia schematów v1+v2), `notes_fingerprint`, `apply_insights` — skonsolidowana polityka zapisu |
| `app/tasks/notes_insights_sync.py` | Pętla dzienna: selekcja przeterminowanych → ekstrakcja → zapis + reindeks + stale-cache; watermark `notes_insights` w `traffit_sync_state` |
| `app/api/admin_notes_insights.py` | `POST /api/admin/notes-insights/sync` (admin JWT; nadganianie zaległości) |
| `alembic/versions/0230_notes_extraction_ai_feature.py` | Klucz kwotowy `notes_extraction` (kalka 0214) + lustro w `entrypoint.sh` |
| `scripts/adhoc_2026_08_champion_notes/` | Archiwum 8 skryptów importu z `/root` + README (artefakt historyczny, nie narzędzie) |

Status biegu: `GET /api/admin/traffit/sync/status` — wiersz `phase=notes_insights`
(endpoint czyta wszystkie fazy z `traffit_sync_state`, zero zmian po jego stronie).

## Zasada kosztowa — płacą tylko zmienieni

- **Fingerprint** = sha256(id+updated_at ostatnich 20 notatek + wersja promptu
  + model), zapisywany jako `_notes_insights._input_hash`. Zgodny odcisk →
  pomijamy bez wywołania AI.
- **Wiersze legacy** (import 08.2026, bez `_input_hash`) są honorowane jako
  świeże, dopóki kandydat nie dostanie notatki NOWSZEJ niż jego znacznik
  ekstrakcji (`legacy_row_is_fresh`). Bez tego pierwsze włączenie pętli
  przemieliłoby ~14k kandydatów bez żadnej zmiany danych (~30 USD w koszu).
- **Budżet per bieg**: `NOTES_INSIGHTS_SYNC_BATCH_LIMIT` (default 300/dzień,
  ~0,002 USD/kandydata na Haiku) — zaległość zbiega w kolejnych dobach;
  operator może przyspieszyć wielokrotnym `POST .../sync`.
- **Kwota**: `AIFeatureKey.notes_extraction` — osobny kubełek (Ustawienia → AI),
  bieg tła nie zjada limitów funkcji interaktywnych.

## Polityka zapisu (inwarianty z importu)

- Kolumny FILL_EMPTY (`expected_rate_hourly`, `years_it_experience`,
  `notice_period`, `availability_date`, status przy „od zaraz").
- **Jedyny dozwolony overwrite: stawka, którą sami wpisaliśmy z notatek**
  (marker `_rate_from_notes` albo równość kolumny z poprzednią ekstrakcją) —
  świeższa notatka aktualizuje NASZ wpis, nigdy ludzki.
- Skills: APPEND z dedupem przez `normalize_llm_skills`;
  `_manual_override_skills` = kandydat nietykalny.
- `client_vetoes` zapisywane do insights, NIGDY nie tworzą automatycznie
  konfliktów (przegląd ręczny). Notatki nie zasilają wektorów ani promptów
  uzasadnień — ekstrakcja to jedyne wywołanie AI.

## Aktywacja na prodzie

1. Coolify env vault: `NOTES_INSIGHTS_SYNC_ENABLED=true` (reszta ma sensowne
   defaulty: kontrola co 30 min, okno od 04:00 UTC — po nocnym Traffit syncu,
   budżet 300/bieg).
2. Redeploy (force=false wystarczy — zmiana runtime env).
3. Pierwszy bieg rusza od razu (ignoruje godzinę okna); postęp w
   `GET /api/admin/traffit/sync/status` → `phase=notes_insights`.

## Świadomie poza zakresem

- **Parse pól CV wpięty w nocny sync** (nowe/zmienione CV → `cv_field_backfill`)
  — osobny PR; dotyka faz `traffit_sync`, nie tej pętli.
- **Sync profili Championa** — zablokowany na wsparciu Traffita (integration
  API nie wystawia plików rekrutacji); list do supportu dostarczony.
- Testy: `tests/test_notes_insights_extractor.py` (11) — polityka zapisu,
  fingerprint, świeżość legacy, harmonogram `_is_due`.
