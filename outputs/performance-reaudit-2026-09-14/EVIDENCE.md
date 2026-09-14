# Dowody ponownego audytu NEXUS — 14.09.2026

Raport: [performance-and-availability-reaudit-2026-09-14.md](../../docs/performance-and-availability-reaudit-2026-09-14.md).

Audyt kodu na `2c00f7cb9eb39bbe8b11271f61685ac0a91c8b8d`, poprawki PR #1502 / live API `6504fef580964904d6096bf1fd0a16263781ea1b`. Te dwie wersje różnią tylko 3 pliki UAT. Ponowny fetch przy końcowej kontroli potwierdził ten sam `origin/main`. Baseline poprzedniego audytu: `ab10c8bba7e06e79a146f4dc48e6e70e168cf7f1`.

## Zapisane artefakty

| Plik | Znaczenie i ograniczenie |
|---|---|
| [public-probes.json](public-probes.json) | Sześć lekkich GET-ów 08:22:58–59 UTC, statusy, czas z klienta, wybrane nagłówki, publiczne odpowiedzi health. Przekierowania śledzone, JSON odkodowany. Bez load testu |
| [uptime-history.json](uptime-history.json) | Historia odczytanych runów GitHub Uptime. Success dowodzi zaliczenia danej próbki, nie ciągłości pomiędzy nimi |
| [pr-1502.json](pr-1502.json) | Odczyt PR, SHA, treści i statusCheckRollup. Treść PR jest deklaracją autora; statusy CI zweryfikowano niezależnie |
| [ui-observations.json](ui-observations.json) | Ręczny zapis bieżących obserwacji Chrome przez narzędzia UI: dashboard, Insights, błędne końcowe położenie Sources oraz DOM rect. Bez danych kandydatów, HAR i pomiaru CLS |
| [backend-repro.py](backend-repro.py) | Kopia uruchomionego harnessu offline: oryginalne funkcje z AST, syntetyczne fixture’y, SQLite w pamięci, tempy. Nie wykonuje lifespan, zdalnego SQL/HTTP/LLM ani zapisów biznesowych |
| [backend-repro-result.json](backend-repro-result.json) | Wyniki cancellation, HoR multi-role, thread buildera XLSX, izolacji 20 tempów i oversized przed 413 |
| [frontend-reaudit.test.tsx](frontend-reaudit.test.tsx) | Kopia 8 niezależnych testów charakterystyki rzeczywistych komponentów/hooków; HTTP/WS zastąpione fixture’ami. Zawarty ciąg local-audit-token jest syntetyczny |
| [frontend-vitest.config.mts](frontend-vitest.config.mts) | Konfiguracja użyta przy niezależnych testach, jsdom, jeden worker |
| [frontend-results.json](frontend-results.json) | JSON Vitest: 8/8 PASS. PASS obejmuje odtworzenie opisanych błędów, nie dowodzi ich naprawy |

Harnessy zachowują ścieżkę analizowanego snapshotu `/tmp/nexus-performance-reaudit-2026-09-14`. To kopie dowodowe wykonanej próby, nie nowy zestaw testów aplikacji włączony do CI. Przy odtwarzaniu po usunięciu snapshotu utworzyć checkout pod tą ścieżką z wymienionego SHA albo zmienić jawne ścieżki ROOT, aliasu i importu Sentry. Użyć zgodnych zależności repo; nie uruchamiać kopii na starym głównym checkoutcie użytkownika.

Istniejące testy backendu wykonano poleceniem `PYTHONPATH=backend python3 -m pytest --noconftest -q backend/tests/test_core_cache_single_flight.py backend/tests/test_entrypoint_document_kind_guard.py` w snapshotcie: 6 PASS, bez conftest/DB. Istniejące 30 testów frontend: QueryProvider.test.tsx (4), api-transient-retry.test.ts (11), InsightsSectionNavContract.test.ts (15), Vitest 3.2.6 / Node 24.17, istniejące zależności hosta. Nie wykonywano lokalnego Dockera ani pełnej integracji.

## GitHub / produkcja

Wszystkie poniższe czasy w UTC.

| Dowód | Wynik |
|---|---|
| [PR #1502](https://github.com/B2B-net-S-A/NEXUS/pull/1502) | Merged 13.09 20:43:50, `6504fef580964904d6096bf1fd0a16263781ea1b` |
| [CI](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34780789123) / [CI Gate](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34780789039) | Sukces PR; head `bca2e849e67ac9ca8a65963e0299acf07c396196` |
| [CI po merge](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34781667133) / [Gate](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34781667142) | Sukces |
| [Deploy poprawek](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34781753173) | 13.09: 20:50:34 healthy/SHA6504; 20:50:35 frontend200 final/login; 20:50:37 wszystkie corecheckshealthy |
| [Ostatni deploy main](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34788844018) | 13.09: webhook200 23:08:55; Coolify failed23:09:07 przy git ls-remote refs/heads/main, exit128. DeploymentUUID q1pv0w5crg1967r6uqvxhyld. Fragment nie ujawnia pierwotnej przyczyny SSH/Git |
| [Coolify Ops — action=list](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34822503590) | 14.09 ok.08:24: queue[], nexus running:unknown. To read-only listing, nie pomiar zasobów/health kontenerów |
| [Uptime 13.09 22:55](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34788173646) | Success |
| [Uptime 14.09 00:46](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34793760688) | Success |
| [Uptime 14.09 05:51](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34811125357) | Success; ponad5h od poprzedniej próbki |
| [Najnowszy odczytany Sentry daily](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34756756967) | 13.09 12:19, przed poprawkami; nie stanowi odbioru ich telemetry |
| [Najnowszy odczytany E2E](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34747273625) | 13.09 08:16, przed poprawkami; brak nowego potwierdzenia 50/100 |
| [Backup Restore Drill](https://github.com/B2B-net-S-A/NEXUS/actions/runs/34805878641) | 14.09 04:24: konfiguracja reach/decrypt off-site niekompletna; błąd zanim wykonano restore. Nie dowodzi uszkodzenia backupu |

Pełne odczytane logi GHA pozostawiono poza repo w katalogu tymczasowym audytu. Raport nie wymaga utrwalania surowych logów operacyjnych; podano konkretne runy i fragmenty wnioskowania. Żadnych tokenów ani prywatnych kluczy nie kopiowano.

## Źródła techniczne i granice

- [Coolify rolling updates](https://coolify.io/docs/applications/deployments/rolling-updates): zakres obsługi, ograniczenie Docker Compose.
- [SQLAlchemy pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html): semantyka pool_size/max_overflow; parametry runtime NEXUS wymagają osobnego pomiaru.
- [RFC 9110 Retry-After](https://www.rfc-editor.org/rfc/rfc9110.html#section-10.2.3): obie dopuszczalne postacie nagłówka.

Bezpośrednie linki do kodu i linii są w raporcie, przypięte do wdrożonego SHA. Żaden z testów offline ani lekkich GET-ów nie dowodzi pojemności 50/100 aktywnych sesji. Nie przeprowadzano zmian konfiguracji, deployu, restartu usług, testu obciążeniowego produkcji ani zapisów danych użytkowników.
