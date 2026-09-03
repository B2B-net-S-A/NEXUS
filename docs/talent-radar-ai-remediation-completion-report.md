# Talent Radar i platforma AI — raport z remediacji (jeden PR)

> Źródło planu: `~/.claude/plans/zaplanuj-wszystskie-poprawy-wedle-cryptic-fountain.md`
> Audyt: `docs/talent-radar-and-ai-features-audit-2026-09-02.md` (PR #1349).
> Gałąź: `feat/ai-platform-remediation`. Data: 2026-09-03.

## Po co

Audyt pokazał trzy rzeczy niewidoczne z zielonego CI, a jedną znaleziono przy
planowaniu (potwierdzoną na prodzie 03.09):

1. **Radar czytał ułamek requestu.** UI przyjmował 20 000 znaków, silnik
   embedował 1200 i szukał umiejętności w 4000 — mail z wymaganiami na końcu był
   rankowany po grzecznościach (`must 1/2`, sim 0,65 zamiast 0,73).
2. **Nazwa roli z profilu Championa ginęła** na styku promptu v5 i kodu
   czytającego kształt v3 — request wyszukiwania nie niósł `title`.
3. **Wyłącznik AI nie wyłączał AI.** Cztery ścieżki Claude stały poza kwotami
   (UoP potwierdzone: 15,4 s wywołania, licznik bez ruchu).
4. **Alarm wydatków nigdy nie wystartował.** Po decyzji 24.08 (bez sufitów,
   zamiast tego alarm) jedyną ochroną budżetu jest `ai_spend_alerts`. Pętla
   kończy się normalnie przy braku `SLACK_WEBHOOK_URL`, a health liczył tylko
   zadania zakończone WYJĄTKIEM → wydatki bez sufitu I bez wykrycia, health
   `healthy`.

## Commity (13, w wymuszonej kolejności)

| # | Commit | Co |
|---|---|---|
| C1 | `feat(ai-quota): klucze uop_check i cv_name_backfill + tokeny` | dwa klucze kwoty + kolumny `input_tokens`/`output_tokens` (migracja `0270`, lustro w entrypoint) |
| C2 | `feat(ai-quota): akumulator tokenów + declared_call` | `declared_call` (deklaracja bez naliczania) dla dwóch ścieżek `BackgroundTasks`; akumulator tokenów zapisywany po wywołaniu |
| C3 | `feat(claude-client): łańcuch modeli, cache promptu, ucięcie, thinking` | jeden klient Claude wchłania łańcuch fallbacków, `cache_control`, `ClaudeTruncated`, domyślny `thinking: disabled`, `call_claude_text` |
| C4 | `refactor(cv-generator): provider.py` | polityka generatora CV na wspólnym kliencie; pin Sonnet 4.6 (rewert #628) zachowany |
| C5 | `refactor(ai): kasacja drugiego stosu dostawcy` | usunięty `ai_client.py`, `_RAW_CLIENT_BASELINE` pusty; 19 testów zachowań przeniesionych |
| C6 | `feat(ai-quota): obciążenie i deklaracja w jednym kroku` | sześć ścieżek `check_and_increment` → `ai_feature`; `429 → 503` na `jobs.py` (C-8) |
| C7 | `feat(ai-quota): cztery ostatnie ścieżki Claude pod bramką` | UoP, M365 CV, Traffit backfill, Cortex CV-LLM |
| C8+C9 | `feat(talent-radar): silnik czyta cały request; STRICT w CI` | radar embeduje cały request (`max_field_chars=None`), nazwa roli z `_summary_basics`, `RADAR_PROFILE`, `raise_on_error`, `seniority_note`; `AI_QUOTA_STRICT=true` w CI |
| C10 | `feat(talent-radar): lokalizacja, braki przed dopasowaniami, timeouty` | pole lokalizacji, braki-przed-trafieniami, chip stawki, `SLOW_ENDPOINT_TIMEOUT_MS` na trzech wolnych endpointach |
| C11 | `refactor(ai): jeden rejestr modeli per AIFeatureKey` | `ai_models._REGISTRY` — jedno miejsce funkcja → model; 16 punktów zachowanych bit w bit; CV/MINDY i backfill/lint rozdzielone wąskimi env |
| C12 | `fix(health): sondy widzą martwy alarm wydatków AI` | wspólny klasyfikator zadań w tle; `background_tasks` łapie cichy krytyczny alarm; `ai_features` raportuje stan alarmu zamiast wiecznego `uncapped` |
| C13 | `feat(ai-settings): model per funkcja, tokeny, licznik w ai-matches` | panel: model + tokeny (jeden `GROUP BY`, koniec N+1), tekst „funkcje generatywne" (P-A), typ FE 8→16, pierwszy test panelu; **P-B**: `meta.eligibility_filtered` w /ai-matches + render + przepisany komentarz „wyrocznia na NDA" |
| C14 | `fix(ai): fallback Ollama tylko przy jawnym OLLAMA_BASE_URL` | C-12: default `OLLAMA_BASE_URL` → `""`; reszta C14 zbadana (patrz niżej) |

## Decyzje Artura wykonane

- **P-A** (retrieval poza wyłącznikiem AI): zero klucza `semantic_retrieval`,
  zero liczenia Voyage. Panel mówi „funkcje generatywne" + zdanie, że
  wyszukiwanie semantyczne działa niezależnie.
- **P-B** (licznik odsianych): NIE zdjęty z radaru — DODANY do /ai-matches
  (`meta.eligibility_filtered`, render na stronie oferty). Komentarz
  „wyrocznia na NDA" w `matching.py` przepisany: zapisuje odwrócenie decyzji
  z datą (2026-09-03) i autorem oraz akceptowany tradeoff.
- **P-C** (bez sufitów, naprawić alarm): sonda + tokeny w PR, webhook poza PR (O-1).

## Pozycje C14 zbadane, nietknięte lub odroczone

- **TR-15 (dedup osób)** — MOOT: pula radaru jest keyed by `candidate_id`
  w dict (`similarity_map`), więc duplikaty osób nie mogą powstać.
- **TR-16/TR-17 (docstring „v3", martwa gałąź `forbidden`)** — MOOT: obecny
  kod radaru jest czysty (`forbidden` żyje w `resolveViewState`).
- **C-11 (cache-gdy-wyłączone)** — ODRZUCONE: koliduje z udokumentowaną
  decyzją prywatnościową (`candidate_activity_summary.py`: „a disabled feature
  must never continue exposing an older cached note"). Ujednolicenie
  nadpisałoby świadomą decyzję bez nowej informacji.
- **TR-14 (cache radaru)** — ODROCZONE: nowa warstwa stanu (klucz+TTL+
  inwalidacja) jako ostatni commit ~90-plikowego PR-a; radar jest ad-hoc,
  więc trafialność cache'u niepewna. Osobny PR z pomiarem.
- **C-8 (kontrakt HTTP)** — konkretny defekt (429→503) naprawiony w C6;
  szersze ujednolicenie (Retry-After/502) odroczone jako polish.

## Weryfikacja

Wszystko przez obraz `nexus-verify:img` (Python 3.13) + własny Postgres
`nexus-remedy-pg`, pod `AI_QUOTA_STRICT=true` (tryb CI), z pełnym repo
zamontowanym (testy czytające `.github/workflows/*`).

- `ruff check app/` i `ruff format --check app/` — czyste.
- Wszystkie 17 plików dotkniętych C11 kompilują się (AST) i importują bez cyklu;
  rejestr pokrywa 16/16 `AIFeatureKey`.
- Zielone klastry (reprezentatywnie): `test_ai_models_registry`,
  `test_ai_quota_*`, `test_ai_spend_gating`, `test_claude_client_chain`,
  `test_cv_generator_provider`, `test_ai_settings_*`, `test_ai_provider_health`,
  `test_background_task_supervision`, `test_uptime_probe_health_checks`,
  `test_health_v2`, `test_ai_matches_*`, `test_cv_backfill`, `test_cv_field_backfill`,
  klaster champion/notes/order/match/radar (362 testy), `test_ollama_disabled_by_default`.
- FE: `type-check` i `lint` czyste; testy `talent-radar/*` i `settings/ai/page`
  zielone (`--no-file-parallelism`).

**Dwa testy padające po cofnięciu poprawki** (nie teatr): limit tekstu radaru
(5000 znaków, technologia na końcu → w `matching_must`) oraz rozdzielenie
CV/MINDY (`MINDY_MODEL` nie rusza `cv_parser`).

**Znane pre-existing (poza zakresem, poza CI):**
`test_cv_parser.py::test_parse_cv_uses_ollama_when_available` czerwony przez
stale `expected` bez pól normalizacji — plik jest w `--ignore` CI, a jedyna moja
zmiana w `cv_parser` to linia 376 (ścieżka Claude, nie Ollama).

## Po merge (poza PR)

- **O-1 — NAJPILNIEJSZE:** ustawić `SLACK_WEBHOOK_URL` na prodzie (workflow
  „Coolify set env", `redeploy=false`, potem deploy). Dopóki nieustawiony,
  alarm wydatków nadal nie istnieje — ten PR czyni to WIDOCZNYM
  (`ai_features` → „spend-alarm off"), nie naprawia webhooka. Potwierdzić przez
  `/api/admin/snapshot`, że `ai_spend_alerts` jest w `running`.
- **O-2:** `AI_QUOTA_STRICT=true` na prodzie po cyklu obserwacji (gdy `UNGATED`
  w logach puste).
- **M-1:** A/B flagi `TALENT_RADAR_STRUCTURED_SKILLS_ENABLED` (baseline od nowa).
- **M-2:** powtórka symulacji rekruterskich (C9/C10 zmieniają pulę i ranking).

## Sondy prodowe po merge

1. **TR-1:** wyszukiwanie z 4700 znakami wstępu → komplet wymagań, `semantic` ~0,73.
2. **TR-2:** upload profilu → chip pokazuje nazwę roli, request niesie `title`.
3. **Kwoty:** `POST /api/b2b-generator/check-uop` → licznik `uop_check` +1 i tokeny;
   główny wyłącznik OFF → 503 zamiast wywołania.
4. **Alarm:** `GET /api/admin/snapshot` → po O-1 `ai_spend_alerts` w `running`.
5. **Health:** `checks.ai_features` mówi o stanie alarmu, nie o braku sufitów.
6. **Generator CV:** jedna generacja end-to-end — porównać jakość z CV sprzed merge.
