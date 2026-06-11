# Champion Profile Workflow — raport ukończenia (2026-06-11)

> Sesja: dwustronna weryfikacja profilu championa + briefing DL z Fireflies +
> rekomendowane wyszukiwania AI. Wszystko **soft** (badge'e/statusy, zero
> twardych bramek publikacji) — zgodnie z decyzją Artura.

## Cel biznesowy

Profil championa nie może być przepisanym requestem klienta. DL tworząc
rekrutację:

1. weryfikuje request **z klientem** (czego naprawdę potrzebują),
2. weryfikuje realia **z naszym konsultantem pracującym u tego klienta**
   (jak wygląda praca na co dzień),
3. nagrywa **breakout session** (Fireflies) tłumacząc rolę własnymi słowami,
4. zatwierdza **zaproponowany przez AI search** w bazie — a każdy rekruter
   wchodzący na rekrutację aktywuje go jednym klikiem.

## Zmergowane PR-y

| PR | Zakres | Status |
|---|---|---|
| [#485](https://github.com/artur-t-96/Nexus/pull/485) | Dwustronna weryfikacja (klient + konsultant) | merged + prod, E2E przez Chrome ✓ |
| [#489](https://github.com/artur-t-96/Nexus/pull/489) | Briefing DL — Fireflies audio/transkrypt + AI cross-check | merged + prod, UI smoke ✓ |
| [#491](https://github.com/artur-t-96/Nexus/pull/491) | Rekomendowane wyszukiwania AI (DL approve → pinned shared SavedSearch) | merged + prod |

## Co powstało

### 1. Weryfikacja dwustronna (#485)
- Sekcja `verification` w `jobs.champion_profile` JSONB (bez migracji DB):
  `client` (status/method/key_corrections/confirmed_as_is + stamping) i
  `consultant` (status verified/skipped, consultant_candidate_id/name,
  insights, skip_reason + stamping).
- `POST /api/jobs/{id}/champion-profile/verification` — server-side stamping,
  walidacje 422 po polsku (delta-vs-request ALBO „potwierdzony 1:1";
  skip wymaga powodu; weryfikacja konsultancka wymaga wniosków z rozmowy).
- `GET /api/jobs/{id}/champion-profile/consultant-suggestions` — nasi ludzie
  aktualnie u klienta joba (hired-latest + active Contract + conflict
  current_employment, scoped do `client_id`). Na prodzie dla PKO BP zwraca
  ~19 konsultantów z tytułami ról.
- PUT champion-profile **zachowuje** stored verification (anty-forge/wipe);
  `apply_suggestion` nie wycina (pole w schemacie Pydantic).
- FE: `ChampionVerificationChecklist` — badge Niezweryfikowany/Częściowo/
  Zweryfikowano, formularze inline, „Cofnij".

### 2. Briefing DL (#489)
- Migracja **0129**: `notes.source_ref` + `notes.audio_url` (idempotentna).
- `fireflies_sync`: pole `audio_url` w GraphQL query (fallback bez pola gdy
  plan-gated) + **dedup po source_ref** (in-memory last_synced_at po
  restarcie dublował notatki).
- Sekcja `briefing` w champion_profile (server-stamped, chroniona na PUT).
- `POST/DELETE /api/jobs/{id}/champion-profile/briefing` + `GET
  .../briefing/audio-url` (presigned 10 min; `<audio>` nie wysyła
  Authorization). Audio kopiowane do Hetzner Object Storage
  (`briefings/...`) — linki Fireflies CDN wygasają; download best-effort.
- `enrich=true` → istniejący `enrich_from_meeting` jako **AI cross-check**
  (co DL powiedział, a czego nie ma w profilu → ChampionProfileSuggestion).
- FE: trzeci wiersz checklisty „Briefing dla rekruterów (nagranie)" — picker
  meetingów joba, checkbox cross-check, `AudioPlayer` (reuse z CloudTalk).
- Konwencja tytułu nagrania: **„Briefing: {nazwa roli}"** (podbija auto-match
  `fireflies_job_matcher`).

### 3. Rekomendowane wyszukiwania AI (#491)
- LLM (prompt `CHAMPION_RECOMMENDED_SEARCHES`, model per `CHAMPION_AI_MODEL`)
  zamienia profil championa + wymagania joba w 2-3 strategie w **ścisłym
  schemacie** `RecommendedSearchParams` (whitelist subset
  `CandidateSearchRequest`: q_all/q_any_groups/q_none, skills_must/any/none,
  lata doświadczenia, miasta). Puste/niepoprawne propozycje odrzucane.
- Karta w profilu championa: nazwa + uzasadnienie + chipsy + **live licznik
  „N kandydatów dziś"** (ten sam `POST /api/search/candidates` co zakładka
  Wyszukaj manualnie).
- **Zatwierdź dla zespołu** → `SavedSearch(pinned_to_job_id, shared=True)`
  z filtrami w formacie manual-search; **phase4 lista pinned zwraca też
  shared searche innych userów przypięte do joba** → rekruter aktywuje
  strategię DL-a jednym klikiem (istniejący `loadSavedSearch`).
- Odrzuć / Cofnij decyzję (reset kasuje zmaterializowany SavedSearch).
- Quota: `champion_draft` (`check_and_increment`).

## Testy

- `tests/test_champion_verification.py` — 8 testów
- `tests/test_champion_briefing.py` — 7 testów
- `tests/test_champion_recommended_searches.py` — 6 testów (mocked Anthropic)
- Wszystkie w CI (`ci.yml` pytest list). Lokalna weryfikacja: 21 passed
  + tsc/ESLint/ruff czyste przy każdym PR.

## Weryfikacja na produkcji

- `/api/health` version-match po każdym deployu ✓
- Chrome E2E (job „Tester Middle ZOB-2732", id 143770): karta „Weryfikacja
  i briefing" renderuje się; weryfikacja klienta zapisana → stamping „Artur
  Twardowski • 11.06.2026 • Rozmowa telefoniczna" + badge „Częściowo
  zweryfikowano" → Cofnij (stan czysty); picker konsultantów zwraca realnych
  ludzi u PKO BP; wiersz briefingu z poprawnym empty-state.

## Znane ograniczenia / TODO

- **Fireflies `audio_url`** — pole bywa plan-gated; sync ma fallback, ale
  realny round-trip audio (download → Object Storage → odtwarzacz) zweryfikuje
  się przy pierwszym prawdziwym briefingu z nagraniem.
- Wiersz briefingu pokazuje tylko meetingi **podpięte** do joba — podpinanie
  nowych meetingów nadal w panelu „Meetingi i AI" (Phase 14) poniżej.
- Brak KPI „% zweryfikowanych profili per DL" — łatwy follow-up do panelu KPI
  (dane są w JSONB: `verification.client.status` itd.).
- Stare propozycje searchy nie wygasają automatycznie po dużej zmianie
  profilu — DL może kliknąć „Wygeneruj ponownie" (proposed są zastępowane,
  decyzje zostają).
