# M13 — Automaty w tle (Traffit, poczta zamówień, Compass, alerty, health, backup)

| Pole | Wartość |
|---|---|
| Tryb | **R** — wyłącznie odczyt przez API i workflow GitHub; ŻADNEGO ręcznego uruchamiania syncu |
| Persony | admin (JWT) |
| Zależności | Fala 0 (`ai-przed.json`, baseline Sentry) |
| Czas | ~2 h + jedna noc (sprawdzenie „po nocy”) |
| Głębokość | pełna — to, czego nikt nie widzi na ekranie |
| Akcje AI | nie |

## Zakres

Pętle tła w `backend/app/main.py` (lifespan) i ich sondy w `/api/health.checks`:

| Automat | Flaga | Sonda / status | Co robi |
|---|---|---|---|
| Traffit daily sync | `TRAFFIT_SYNC_ENABLED` | `checks.traffit`; `GET /api/admin/traffit/sync/status` | nocny import delta 02:00 UTC, tygodniowy full; kursory wznawialne |
| Poczta zamówień | `ORDER_MAIL_INGEST_ENABLED` | `checks.order_mail`; `GET /api/order-mail/sync/status` | co 60 min czyta skrzynkę współdzieloną (app-only), planuje i auto-zapisuje pewne zamówienia |
| Compass: dni robocze | `COMPASS_WORKDAYS_ENABLED` | `checks.compass_workdays` | co 6 h pobiera dni robocze minus urlop (D5 Insights) |
| Compass: cykl życia kont | `COMPASS_LIFECYCLE_ENABLED` | log | co 6 h deaktywuje konta `exited`; jednokierunkowe |
| Alerty DL | `DL_ALERTS_ENABLED` | `dl_alerts` tabela | dzienny skan, powtórka co 7 dni do `handled` |
| Skaner wygasania | — | powiadomienia 30/14/7 dni | zamówienia, kontrakty, umowy ramowe; dedup (odbiorca, obiekt, próg, data końca) |
| Promocja statusów kontraktów | — | `contract_alerts` | nocne `active → ending → ended` po `end_date` |
| Retencja przeglądów bazy | `CANDIDATE_SEARCH_RETENTION_ENABLED` | `GET /api/admin/index-coverage` → `candidate_search` | kasuje zakończone przeglądy > 7 dni, chroni najnowszy per (autor, otwarta rekrutacja) ≤ 90 dni |
| Sprzątanie wejść CV | `CV_JOB_INPUT_RETENTION_ENABLED` | log | co 15 min; wejścia nieudanych generacji > 7 dni |
| Autofreeze konkursów | — | `competition_winners` | mrozi 4 typy wyścigów (NIE Hall of Fame) |
| Alarm wydatków AI | — | `spend_alert_level` w `ai_features` | ostrzega przy krotnościach progu — **uwaga: pamięć projektu mówi, że nigdy nie wystartował** |
| Backup lokalny + off-site | cron hosta + kontener `backup` | `backup-drill.yml` (poniedziałek 04:00 UTC) | patrz Fala 0 §2.2 |
| Uptime probe | `uptime-probe.yml` | GitHub Actions | cron na `/api/health` |
| Sentry daily monitor | `sentry-daily-monitor.yml` | GitHub Actions | dzienny raport |

## Scenariusze — odczyt stanu (dzień 1)

| ID | Kroki | Oczekiwane | Prio |
|---|---|---|---|
| S01 | `GET /api/health` → `checks` (pełny JSON do raportu) | jak Fala 0 §2.1; każdy klucz z opisem po polsku w raporcie; `background_tasks = healthy` | P1 |
| S02 | `GET /api/admin/traffit/sync/status` | `enabled: true`; `__daily__` < 36 h; per faza: `processed/updated/errors`, kursory (`cursor_payload` z slotami `delta`/`full`); `skipped_pages` w `candidate_sources`; jeśli `degraded` — POWÓD (faza, klasa wyjątku) | P1 |
| S03 | S02 → faza `candidate_files`/`candidates_enrich_names` z kursorem | kursor `after_id` obecny = sweep w toku (poprawne); `full_sweep_pending` → full należny co noc | P2 |
| S04 | `GET /api/order-mail/sync/status` | `auth_mode: app`, `app_only_ready: true`, `last_status` ∈ {ok, running, interrupted, error}; `finished_at` < 2 h (poll 60 min); `stats` z licznikami | P1 |
| S05 | `GET /api/order-mail/queue?status=needs_review` | wpisy z `rule_versions` w meta; brak wpisów starszych niż 14 dni bez decyzji (jeśli są — obserwacja dla DL, P3) | P2 |
| S06 | `checks.compass_workdays` | `healthy` wymaga `last_status == 'ok'` (nie samej świeżości); `last_sync` < 12 h | P1 |
| S07 | `GET /api/insights/reconciliation/placements` (admin) | raport FULL OUTER dwu rodzin atrybucji; liczby (np. 213/228/317/332) — zapisz jako referencję; nazwiska tylko dla ról z odczytem kandydatów | P2 |
| S08 | `GET /api/admin/index-coverage` | blok `candidate_search` (rozmiar tabel), pokrycie indeksu Qdrant vs SQL; brak sierot > 1 % (jeśli więcej — obserwacja, `index-cleanup` GET plan do raportu, **bez POST**) | P2 |
| S09 | `GET /api/admin/index-cleanup` (GET = plan, bez zapisu) | plan z odciskiem; liczby sierot i ofert bez punktu | P3 |
| S10 | `GET /api/admin/engagement-inventory` | checki `order_client_mismatch`, `periodic_duplicates_group_line` — liczby; > 0 = obserwacja do decyzji Delivery | P2 |
| S11 | `GET /api/admin/client-mixups` | rodziny klientów o wspólnym rdzeniu; tylko odczyt; liczba rodzin do raportu | P3 |
| S12 | `GET /api/admin/schema-drift` | brak dryfu albo `error` z opisem; `alembic` head | P1 |
| S13 | `GET /api/health/alembic` | wersja bookmarku; pamięć projektu: bookmark bywa osierocony (entrypoint jest wdrożeniem) — zapisz stan | P2 |
| S14 | `GET /api/settings/ai` → `spend_alert_level`, ostatnie ostrzeżenie | zapisz; jeśli zużycie > próg, a `spend_alert_level` = 0 → alarm nie działa (P1) | P1 |
| S15 | GitHub: `gh run list --workflow uptime-probe.yml --limit 10`, `sentry-daily-monitor.yml`, `order-mail-cleanup.yml`, `disk-alert.yml`, `coolify-queue-maintenance.yml` | wszystkie `success` w ostatnich biegach; czerwony = zgłoszenie z linkiem do runu | P1 |
| S16 | GitHub: `backup-drill.yml` | patrz Fala 0 §2.2 — czerwony = BLOCKER startu (nie UAT) | P0 |
| S17 | Sentry: `nexus-be` issues z tagiem `logger:app.tasks.*` / `background` z ostatnich 7 dni | lista do raportu; nowe względem baseline → zgłoszenia | P1 |

## Scenariusze — „po nocy” (dzień 2, ≥ 24 h po S02)

| ID | Kroki | Oczekiwane | Prio |
|---|---|---|---|
| S20 | powtórz S02 | `__daily__` przesunięty o ~24 h; `errors` nie rosną w nieskończoność (porównaj); `degraded` → `healthy`, jeśli Fala 0 naprawiła powód | P1 |
| S21 | powtórz S04 | `finished_at` przesunięty; `last_status: ok`; liczniki biegów rosną | P1 |
| S22 | kontrakt PRAWDZIWY, który miał `end_date` = wczoraj (znajdź w `GET /api/contracts?status=ending` dzień wcześniej; tylko ID) | dziś `ended`; jego zamówienia `completed`; osoba w „Zakończonych” u klienta | P1 |
| S23 | powiadomienia dzwonka admina | brak DUPLIKATÓW alertu wygasania (ten sam obiekt, próg, data końca) między dzień 1 i 2 | P2 |
| S24 | Insights → Placementy dla D3 (po P2 „Zatrudniony”) | placement testowy WIDOCZNY następnego dnia (widok `analytics_first_milestones` odświeżony) — i sprzątnięty po Fali 2 | P2 |
| S25 | jeśli okres przejściowy = „równolegle”: zmień w Trafficie notatkę u kandydata TESTOWEGO (CZŁOWIEK) → po nocy | notatka w NEXUS z `source_ref=traffit:activity:<id>`; bez duplikatu | P1 |

## Kontrole (skrypt do raportu)

```bash
TOK=…; API=https://api.nexus.dynaminds.pl; H="Authorization: Bearer $TOK"
for p in /api/health /api/health/deep /api/health/alembic /api/admin/traffit/sync/status /api/order-mail/sync/status \
         /api/admin/index-coverage /api/admin/schema-drift /api/admin/engagement-inventory /api/admin/client-mixups; do
  echo "== $p"; curl -fsS -H "$H" "$API$p" | jq -c 'if type=="object" then with_entries(select(.key|test("status|last|enabled|errors|count|total|degraded|drift|alembic"))) else . end' 2>/dev/null | head -c 800; echo; done
for w in uptime-probe.yml sentry-daily-monitor.yml order-mail-cleanup.yml disk-alert.yml coolify-queue-maintenance.yml backup-drill.yml e2e.yml; do
  printf '%-32s ' "$w"; gh run list --workflow "$w" --limit 3 --json conclusion --jq 'map(.conclusion)|join(",")'; done
```

## Znane pułapki

- Health Traffita to sonda ŚWIEŻOŚCI, nie kompletności — `healthy` nie znaczy „dane zgodne z Traffitem”.
- Błędy WIERSZY faz wzbogacania są doradcze (nie wstrzymują watermarku) — `errors > 0` przy `healthy` jest możliwe.
- Każdy deploy restartuje kontener: `running` bez blokady = przerwany bieg, nie awaria.
- Kolejka Coolify: burst merge'y = 429; deploy job koalesuje. Nie zgłaszaj „deploy nie poszedł”, sprawdź `/api/health.version`.

## Do raportu

Pełny JSON `checks` dzień 1 i 2 obok siebie; tabela workflowów; wynik S14 (alarm wydatków); lista obserwacji z S08/S10/S11.
