# Plan poprawy QA po audycie 14.09.2026 — raport wykonania

Audyt: [nexus-test-coverage-and-qa-audit-2026-09-14.md](nexus-test-coverage-and-qa-audit-2026-09-14.md).
Wykonanie: 15.09.2026, dwa PR-y — hotfix bezpieczeństwa [#1543](https://github.com/B2B-net-S-A/NEXUS/pull/1543)
(scalony i wdrożony, `29292eb`) oraz domknięcie planu [#1544](https://github.com/B2B-net-S-A/NEXUS/pull/1544).

## Stan zadań

| ID | Zadanie | Stan | Dowód |
|---|---|---|---|
| QA-01 | Coverage i archiwizacja | ✅ zrobione | Backend: pomiar linii **i gałęzi** w 4 shardach, scalenie z kontrolą kompletu shardów, bramka „bez spadku” (`.github/coverage-baseline.json`, `.github/scripts/coverage_gate.py`), wynik w wymaganym kontekście „Backend (pytest)”. Pierwszy pomiar: **71,46%** (baseline 71,4, minimum 70,9). Frontend w CI: 53,55% linii / 78,14% gałęzi / 55,16% funkcji (audyt: 49,41 / 78,18 / 53,87). Frontend: progi w `vitest.config.ts` (linie/instrukcje 53, gałęzie 77,5, funkcje 54) + artefakt `frontend-coverage`. Codecov tylko z tokenem (krok Artura). |
| QA-02 | Preview vs E2E po zalogowaniu, środowisko | ✅ zrobione | `docker-compose.e2e.yml` + job `stack` w `e2e.yml` (PR + nocny), konta ról z `backend/scripts/seed_e2e.py`, osobne projekty `ci-chromium` / `prod-smoke` / `preview-chromium`; brak hasła na stacku = błąd, pominięty przypadek = czerwony bieg. |
| QA-03 | Słabe asercje, prawdziwe przepływy | ✅ zrobione (7 procesów) | 15 scenariuszy `@stack` w 8 plikach, **16/16 PASS w CI** (z setupem logowania, 0 pominiętych): kandydat (+duplikat 409), pipeline (+konflikt wersji, odmowa spoza zespołu), wzmianka → powiadomienie, RBAC API+UI, kontrakt ↔ zamówienie, regresje 27.05 z tokenem, dostępność. Pierwszy bieg wykrył brak etykiety selektora sortowania (a11y critical) i dwie przestarzałe regresje. 27 `test.fixme` zastąpione backlogiem `docs/uat/09-backlog-scenariuszy-e2e.md`. Kontrakt zakazuje `toBeLessThan(500)`, `test.fixme(`, `test.skip(true`. |
| QA-04 | Odtworzenie backupu | ⛔ krok Artura | Kod drillu jest poprawny i uczciwie czerwony — brak sekretów off-site (B2 `dynaminds-nexus-offsite` założony 27.07). |
| QA-05 | Triage security + polityka | ✅ zrobione | Hotfix #1543: Next.js 15.5.25 (CRITICAL RCE w optymalizatorze obrazów), sharp 0.35.4, postcss 8.5.28, browserslist 4.28.9 — Trivy frontendu 0. DS-0002 = fałszywy alarm (gosu) w `.trivyignore` z terminem. Trivy blokuje nowe HIGH/CRITICAL (liczy też `Failures:`). |
| QA-06 | Wykluczone testy | ✅ zrobione | 0 wykluczeń: 4 pliki live przeniesione na `app_client`, 2 „kolekcyjne” przechodziły (powód nieaktualny). |
| QA-07 | Macierz flag | ✅ zrobione | `pipeline_mode` na 7 dodatkowych plikach CV (+32 przypadki), fixture `contract_order_sync_mode` na zapisach zamówień. |
| QA-08 | Frontend w punktach ryzyka | ✅ zrobione | 71 testów: `ApplyForm` 0→100%, `global-error` 0→100%, `NotificationsTab` 0→88%, `MaterialsTab` 15→70%, 4 hooki 0→~100%. |
| QA-09 | Zadania tła | ✅ zrobione | 7 nowych plików (63 testy): rejection email loop, marketplace sweeper, centroidy CC, workdays sync, signing sweeper, CloudTalk sync, PAdES. |
| QA-10 | AI eval w decyzji o wydaniu | ⏸ świadomie poza | Wymaga ocenionego korpusu rekruterów; bez niego bramka byłaby udawana. |
| QA-11 | Wydajność, dostępność, wygląd | ◐ częściowo | Dostępność: axe na 3 ekranach (blokuje `critical`). Regresja wizualna i obciążeniowa — poza zakresem (baseline zrzutów wymaga stabilnego środowiska renderu; wydajność ma własny plan z 13.09). |
| QA-12 | Właściciel QA, katalog UAT | ◐ częściowo | Backlog scenariuszy z priorytetami; procedura `tested_sha`/`final_sha` była już w Fali 0. Właściciele imienni — decyzja Artura. |

## Błędy produktu znalezione przy okazji

1. **Duplikat e-maila kandydata → 500** (IntegrityError bez obsługi). Teraz 409 z komunikatem; test `test_candidate_create_duplicate_email.py`.
2. **Backend nie startuje na pustej bazie**: manifest portfela (`--apply-once`, fail-closed) blokuje entrypoint. Dla stacku E2E jawny przełącznik `CLIENT_PORTFOLIO_MANIFEST_SKIP=1` (kontrakt zabrania go w compose produkcyjnych). Instalacja od zera poza stackiem nadal wymaga świadomej decyzji.
3. **`seed.py` pada na każdej świeżej bazie** (użytkownicy bez `ensure_roles_invariant()`) — i **świadomie NIE naprawiony**: entrypoint uruchamia go przy każdym starcie także na produkcji, a jedyną bramką jest istnienie `artur@b2bnet.pl`. Gdyby na produkcji tego konta nie było, naprawiony seed zasiałby ją kontami demo z domyślnym hasłem. Dziś chroni przed tym wyłącznie to, że seed się wywraca. Do decyzji: usunąć `python seed.py` z entrypointu (stack E2E zakłada konta przez `backend/scripts/seed_e2e.py`) i dopiero potem naprawić seed dla lokalnego dev.
4. **`global-error.tsx` bez strażnika błędu chunka** — stara karta po deployu kończyła na ekranie awarii zamiast przeładowania.
5. **Formularz aplikacji bez CV** pokazywał „zły format” zamiast „Dodaj swoje CV”.
6. **`auth.setup.ts` celował w nieistniejący placeholder** i niejednoznaczny przycisk — setup E2E nie mógł się zalogować nawet z sekretami.
7. Wszystkie `request.*` w scenariuszach E2E szły bez tokena (401 spełniało `< 500`).

## Kroki Artura

1. **Backup (QA-04):** sekrety `BACKUP_S3_ACCESS_KEY`, `BACKUP_S3_SECRET_KEY`, `BACKUP_AGE_PUBLIC_KEY` (Coolify) i `BACKUP_AGE_PRIVATE_KEY` (GitHub Secrets drillu), `BACKUP_ENABLED=true`, ręczne uruchomienie drillu.
2. **Ruleset `main-baseline`:** dopisać `Trivy + hadolint`; po ~2 tygodniach stabilności także `E2E stack (ci-chromium)`.
3. **Nocny `prod-smoke`:** produkcja ma wyłącznie SSO, więc konto E2E musi być na `PASSWORD_LOGIN_BREAK_GLASS_EMAILS` (rola z samym odczytem) + sekrety `E2E_USER_EMAIL`/`E2E_USER_PASSWORD`.
4. Opcjonalnie `CODECOV_TOKEN`.

## Utrzymanie

- Ratchet pokrycia: `::notice::` o wzroście → podbij `.github/coverage-baseline.json` / progi Vitest w tym samym PR.
- Nowy przepływ E2E: tag `@stack`, własne dane przez `e2e/helpers/entities.ts`, dokładny status (`expectStatus`) i ponowny odczyt.
- Nowy wyjątek Trivy: tylko z uzasadnieniem i `exp:`.
